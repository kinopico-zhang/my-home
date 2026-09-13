"""My Music 测试: 语言检测 / 标签读取 / 扫描器增量 / 查询 / Range 流 / 接口。

音频文件是手工拼的最小 FLAC (魔数 + STREAMINFO + VORBIS_COMMENT + PICTURE),
不依赖曲库真文件; 扫描器用临时曲库目录, 接口用 TestClient 走完整 HTTP 栈。
"""
import os
import struct
import time
from pathlib import Path
from typing import Callable

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.main as m
from app import config
from app.music import service
from app.music.library_database import (Album, Artist, Track,
                                        session_factory)
from app.music.library_languages import (detect_script, language_for_script,
                                         scripts_for_language)
from app.music.library_media import parse_range_header
from app.music.library_scanner import LibraryScanner
from app.music.library_tags import (extract_album_artwork,
                                    read_track_metadata)
from app.music import library_queries

PICTURE_BYTES = b"\xff\xd8\xff\xe0FAKEJPEG" + b"x" * 64


def _flac_bytes(tags: dict[str, str] | None, picture: bytes | None = None,
                total_samples: int = 88200) -> bytes:
    """最小可读 FLAC: 标题/歌词等全走 vorbis 注释块, 封面走 PICTURE 块。

    tags=None 时连 vorbis 块都不写 (audio.tags 为 None 的裸文件)。"""
    packed = (44100 << 44 | 1 << 41 | 15 << 36
              | total_samples).to_bytes(8, "big")
    streaminfo = ((4096).to_bytes(2, "big") + (4096).to_bytes(2, "big")
                  + (0).to_bytes(3, "big") + (0).to_bytes(3, "big")
                  + packed + bytes(16))
    blocks = [bytes([0]) + (34).to_bytes(3, "big") + streaminfo]
    if tags is not None:
        vendor = b"pytest"
        comments = b"".join(
            struct.pack("<I", len(f"{key}={value}".encode()))
            + f"{key}={value}".encode() for key, value in tags.items())
        vorbis = (struct.pack("<I", len(vendor)) + vendor
                  + struct.pack("<I", len(tags)) + comments)
        blocks.append(bytes([4]) + len(vorbis).to_bytes(3, "big") + vorbis)
    if picture is not None:
        mime = b"image/jpeg"
        picture_block = ((3).to_bytes(4, "big") + len(mime).to_bytes(4, "big")
                         + mime + (0).to_bytes(4, "big")
                         + (500).to_bytes(4, "big") + (500).to_bytes(4, "big")
                         + (24).to_bytes(4, "big") + (0).to_bytes(4, "big")
                         + len(picture).to_bytes(4, "big") + picture)
        blocks.append(bytes([6]) + len(picture_block).to_bytes(3, "big")
                      + picture_block)
    head, body = blocks[-1][:1], blocks[-1][1:]
    blocks[-1] = bytes([head[0] | 0x80]) + body      # 最后一块打 is_last 标记
    return b"fLaC" + b"".join(blocks)


def _write_audio(root: Path, relative_path: str, tags: dict[str, str] | None = None,
                 picture: bytes | None = None,
                 sidecar_lyrics: str | None = None,
                 mtime: float | None = None) -> Path:
    """往临时曲库放一个音频文件 (+可选同名 .lrc / 指定 mtime)。"""
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_flac_bytes(tags or {}, picture))
    if sidecar_lyrics is not None:
        path.with_suffix(".lrc").write_text(sidecar_lyrics, encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


# ---------------------------------------------------------------- 语言

def test_detect_script_and_language_groups():
    """文字检测: 假名必日文, 谚文韩文, 汉字中文, 拉丁英文, 空白检不出。"""
    assert detect_script("レクイエム") == "Jpan"
    assert detect_script(" 첫사랑") == "Kore"
    assert detect_script("单身情歌") == "Hant"          # 汉字归中文组
    assert detect_script("Hello") == "Latn"
    assert detect_script("Привет") == "Cyrl"
    assert detect_script("!!!", "123") == ""
    # 组名映射 + 未知 script 归其他
    assert language_for_script("Hant") == "中文"
    assert language_for_script("Qaaa") == "其他"
    assert language_for_script("") == "其他"


def test_scripts_for_language_negation():
    """其他 = 已知 script 取反; 全部/未知 → None (不过滤)。"""
    assert scripts_for_language("全部") is None
    assert scripts_for_language("不存在的语种") is None
    japanese = scripts_for_language("日文")
    assert japanese is not None
    assert japanese[0] == frozenset({"Jpan"}) and japanese[1] is False
    others = scripts_for_language("其他")
    assert others is not None
    assert others[1] is True              # 已知集取反
    assert "Jpan" in others[0] and "Hant" in others[0] and "" not in others[0]


# ---------------------------------------------------------------- 标签

def test_read_track_metadata_full_tags(tmp_path):
    """全标签曲目: 值/编号/年份/时长/封面/同步歌词都对得上。"""
    path = _write_audio(tmp_path, "A/2019 示例 [abcdef12]/03 擬態人格.flac", {
        "TITLE": "擬態人格", "ARTIST": "AI机组", "ALBUM": "示例专辑",
        "ALBUMARTIST": "AI机组", "ALBUMARTISTSORT": "AI, Crew",
        "SCRIPT": "Jpan", "TRACKNUMBER": "3/12", "DISCNUMBER": "2",
        "DATE": "2019-04-01", "LYRICS": "[00:01.00]一行目",
    }, picture=PICTURE_BYTES)
    track = read_track_metadata(
        path, "A/2019 示例 [abcdef12]/03 擬態人格.flac", 123, 45.0)
    assert track is not None
    assert track.title == "擬態人格"
    assert track.artist == "AI机组"
    assert track.album_title == "示例专辑"
    assert track.album_artist_sort == "AI, Crew"
    assert track.script == "Jpan"
    assert track.track_number == 3 and track.disc_number == 2
    assert track.year == 2019
    assert track.duration_seconds == 2.0
    assert track.has_artwork
    assert track.lyrics_synced
    assert track.file_format == "flac"


def test_read_track_metadata_fallbacks_and_sidecar(tmp_path):
    """没标签的兜底: 标题剥音轨前缀, 专辑剥年份和 [hex], 艺人用目录名。"""
    relative = "中文歌手/2001 老歌 [00112233]/1-02 无题.flac"
    path = _write_audio(tmp_path, relative, sidecar_lyrics="[00:05.00]歌词行")
    track = read_track_metadata(path, relative, 1, 1.0)
    assert track is not None
    assert track.title == "无题"                    # "1-02 " 前缀剥掉
    assert track.album_title == "老歌"              # "2001 " 和 " [00112233]" 剥掉
    assert track.album_artist == "中文歌手"
    assert track.script == "Hant"                   # 标题检测兜底
    assert track.lyrics == "[00:05.00]歌词行"       # 同名 .lrc 优先
    assert not track.has_artwork
    assert track.disc_number == 1                   # 没写碟号默认 1
    # 不认识的扩展名直接 None
    assert read_track_metadata(tmp_path / "x.xyz", "x.xyz", 1, 1.0) is None


def test_extract_album_artwork(tmp_path):
    """封面抽取: FLAC 的 PICTURE 原样出来; 非 FLAC/文件没了返回 None。"""
    path = _write_audio(tmp_path, "A/a.flac", picture=PICTURE_BYTES)
    assert extract_album_artwork(path) == PICTURE_BYTES
    plain = tmp_path / "b.txt"
    plain.write_bytes(b"not audio")
    assert extract_album_artwork(plain) is None
    assert extract_album_artwork(tmp_path / "no-such.flac") is None


def test_read_track_metadata_without_any_tags(tmp_path):
    """连 vorbis 块都没有的 FLAC: tags 为 None, 全走文件名/目录兜底。"""
    relative = "散装艺人/01 单曲.flac"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(_flac_bytes(None))
    track = read_track_metadata(path, relative, 10, 1.0)
    assert track is not None
    assert track.title == "单曲"                  # "01 " 前缀剥掉
    assert track.album_title == "散装艺人"         # 没有专辑目录: 艺人目录当专辑
    assert track.artist == "散装艺人" and track.album_artist == "散装艺人"


def _syncsafe(value: int) -> bytes:
    """ID3v2.4 的同步安全整数 (7bit×4)。"""
    return bytes([(value >> 21) & 0x7f, (value >> 14) & 0x7f,
                  (value >> 7) & 0x7f, value & 0x7f])


def _id3_text_frame(frame_id: str, value: str) -> bytes:
    """v2.4 文本帧 (编码 3 = utf-8)。"""
    payload = b"\x03" + value.encode()
    return frame_id.encode() + _syncsafe(len(payload)) + b"\x00\x00" + payload


def _dsf_bytes(id3_tag: bytes) -> bytes:
    """最小 DSF: DSD 头 + fmt + data + 尾部 ID3v2.4 (mutagen 只读不验数据)。"""
    fmt = (b"fmt " + struct.pack("<Q", 52) + struct.pack("<IIIIII", 1, 0, 2, 2,
           2822400, 1) + struct.pack("<Q", 2822400)     # 采样率/样本数 = 1 秒
           + struct.pack("<II", 4096, 0))
    data = b"data" + struct.pack("<Q", 64) + bytes(64)
    metadata_offset = 28 + len(fmt) + len(data)
    header = b"DSD " + struct.pack("<QQQ", 28,
                                   metadata_offset + len(id3_tag),
                                   metadata_offset)
    return header + fmt + data + id3_tag


def _write_dsf_audio(root: Path, relative_path: str) -> Path:
    """DSF + 全套 ID3 帧 (TXXX:SCRIPT / USLT 歌词 / APIC 封面)。"""
    uslt = (b"USLT" + _syncsafe(len(b"\x03XXX\x00" + "DSDの歌詞".encode()))
            + b"\x00\x00" + b"\x03" + b"XXX" + b"\x00" + "DSDの歌詞".encode())
    apic = (b"APIC" + _syncsafe(len(b"\x03image/jpeg\x00\x03\x00"
                                    + PICTURE_BYTES)) + b"\x00\x00"
            + b"\x03" + b"image/jpeg" + b"\x00" + b"\x03" + b"\x00"
            + PICTURE_BYTES)
    script = (b"TXXX" + _syncsafe(len(b"\x03SCRIPT\x00Jpan")) + b"\x00\x00"
              + b"\x03" + b"SCRIPT\x00" + b"Jpan")
    frames = [_id3_text_frame(frame, value) for frame, value in (
        ("TIT2", "DSDの曲"), ("TPE1", "DSD歌手"), ("TALB", "DSD专辑"),
        ("TPE2", "DSD歌手"), ("TSO2", "DSD, Sort"), ("TSOP", "DSD, Sort"),
        ("TRCK", "5/10"), ("TPOS", "2"), ("TDRC", "2018-03-01"))]
    body = b"".join(frames) + script + uslt + apic
    tag = b"ID3\x04\x00\x00" + _syncsafe(len(body)) + body
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_dsf_bytes(tag))
    return path


def test_read_dsf_id3_frames(tmp_path):
    """DSF 走 ID3 帧: 标题/编号/年份/歌词/封面/时长全部读出 (曲库真实形态)。"""
    relative = "DSD歌手/2018 DSD [ddddd111]/01 曲.dsf"
    path = _write_dsf_audio(tmp_path, relative)
    track = read_track_metadata(path, relative, 100, 1.0)
    assert track is not None
    assert track.file_format == "dsf"
    assert track.title == "DSDの曲"
    assert track.artist == "DSD歌手" and track.album_artist == "DSD歌手"
    assert track.album_artist_sort == "DSD, Sort"
    assert track.track_number == 5 and track.disc_number == 2
    assert track.year == 2018
    assert track.script == "Jpan"                  # TXXX:SCRIPT
    assert track.lyrics == "DSDの歌詞"             # USLT
    assert track.has_artwork                       # APIC
    assert track.duration_seconds == 1.0


class _StubTags:
    """只有 get/keys 的标签桩 (MP4 / APE 的形状)。"""

    getall: Callable[[str], list[object]]   # ID3 桩动态挂 (attr 声明过 mypy 才认)

    def __init__(self, mapping: dict[str, object] | None = None):
        self._mapping = mapping or {}

    def get(self, key, default=None):
        """字典式取键 (vorbis 兜底读法)。"""
        return self._mapping.get(key, default)

    def keys(self):
        """APE 封面探测会遍历键名。"""
        return list(self._mapping)


class _StubAudio:
    """音频桩: 只带 tags (或 pictures)。"""

    def __init__(self, tags=None, pictures=None):
        self.tags = tags
        self.pictures = pictures


def test_tag_shapes_mp4_and_ape_and_id3():
    """_read_tag/_has_embedded_artwork 的分格式分支 (桩驱动)。"""
    from app.music.library_tags import _has_embedded_artwork, _read_tag  # noqa: SLF001
    mp4 = _StubTags({"©nam": ["曲名"], "trkn": [(3, 10)]})
    assert _read_tag(mp4, "title") == "曲名"
    assert _read_tag(mp4, "tracknumber") == "3"    # trkn 元组取第 0 位
    assert _read_tag(_StubTags(), "title") == ""   # MP4 键缺失
    assert _has_embedded_artwork(_StubAudio(tags=mp4)) is False

    assert _has_embedded_artwork(                  # MP4 covr
        _StubAudio(tags=_StubTags({"covr": [b"x"]})))
    assert _has_embedded_artwork(                  # APE Cover Art 键
        _StubAudio(tags=_StubTags({"Cover Art (Front)": b"x"})))
    assert _has_embedded_artwork(                  # flac pictures 属性
        _StubAudio(pictures=[object()]))
    id3_like = _StubTags({})
    id3_like.getall = lambda key: [object()]       # ID3 APIC
    assert _has_embedded_artwork(_StubAudio(tags=id3_like))
    assert _has_embedded_artwork(_StubAudio(tags=None)) is False


# ---------------------------------------------------------------- 扫描器

def _make_library(root: Path) -> None:
    """两人三张专辑: 一个带海报, 一个带封面, 一个坏文件。"""
    root.mkdir(parents=True, exist_ok=True)
    _write_audio(root, "AI机组/2019 甲 [aaaa1111]/01 曲A.flac",
                 {"TITLE": "曲A", "ARTIST": "AI机组", "ALBUMARTIST": "AI机组",
                  "SCRIPT": "Jpan", "ALBUM": "甲", "DATE": "2019"},
                 picture=PICTURE_BYTES, mtime=2000.0)
    _write_audio(root, "AI机组/2020 乙 [bbbb2222]/01 曲B.flac",
                 {"TITLE": "曲B", "ARTIST": "AI机组", "ALBUMARTIST": "AI机组",
                  "SCRIPT": "Jpan", "ALBUM": "乙", "DATE": "2020",
                  "LYRICS": "[00:01.00]乙の歌詞"},
                 mtime=3000.0)
    (root / "AI机组/poster.jpeg").write_bytes(PICTURE_BYTES)
    _write_audio(root, "老歌手/2001 丙 [cccc3333]/01 曲C.flac",
                 {"TITLE": "曲C", "ARTIST": "老歌手", "ALBUMARTIST": "老歌手",
                  "SCRIPT": "Hant", "ALBUM": "丙", "DATE": "2001"},
                 mtime=1000.0)
    _write_audio(root, "老歌手/2001 丙 [cccc3333]/02 曲D.flac", {}, mtime=1000.0)
    (root / "老歌手/notes.txt").write_text("不是音频")
    (root / ".隐藏/03 隐藏.flac").parent.mkdir(parents=True, exist_ok=True)
    (root / ".隐藏/03 隐藏.flac").write_bytes(_flac_bytes({"TITLE": "隐藏"}))


def _scanner_for(root: Path) -> LibraryScanner:
    return LibraryScanner(root, session_factory(), worker_count=2)


def test_scanner_full_roundtrip(tmp_path):
    """首扫 → 增量跳过 → 删文件清行 → 删专辑清艺人, 汇总始终重算。"""
    root = tmp_path / "library"
    _make_library(root)
    scanner = _scanner_for(root)

    summary = scanner.scan()
    assert summary.tracks_scanned == 4          # 4 个真音频 (.txt/隐藏不算)
    assert summary.artist_count == 2 and summary.album_count == 3
    assert scanner.status().phase == "done"
    with session_factory()() as session:
        artists = {a.directory: a for a in session.query(Artist)}
        assert set(artists) == {"AI机组", "老歌手"}
        assert artists["AI机组"].name == "AI机组"
        assert artists["AI机组"].poster_file == "poster.jpeg"
        assert artists["老歌手"].poster_file == ""
        albums = {a.directory: a for a in session.query(Album)}
        assert albums["AI机组/2019 甲 [aaaa1111]"].has_artwork
        assert albums["AI机组/2019 甲 [aaaa1111]"].track_count == 1
        assert albums["老歌手/2001 丙 [cccc3333]"].track_count == 2
        # 曲D 没标签, 标题兜底成文件名
        track_d = session.query(Track).filter_by(title="曲D").one()
        assert track_d.script == "Hant"          # 检测兜底走专辑艺人名
        track_b = session.query(Track).filter_by(title="曲B").one()
        assert track_b.lyrics == "[00:01.00]乙の歌詞" and track_b.lyrics_synced

    # 二扫: mtime/size 没变, 全跳过
    summary = scanner.scan()
    assert summary.tracks_scanned == 0 and summary.tracks_skipped == 4

    # 删一首: 行没了, 专辑汇总降回 1
    (root / "老歌手/2001 丙 [cccc3333]/02 曲D.flac").unlink()
    summary = scanner.scan()
    assert summary.tracks_removed == 1
    with session_factory()() as session:
        album = session.query(Album).filter_by(
            directory="老歌手/2001 丙 [cccc3333]").one()
        assert album.track_count == 1

    # 删整张专辑 (老歌手唯一的一张): 专辑和艺人都清掉
    for path in (root / "老歌手/2001 丙 [cccc3333]").iterdir():
        path.unlink()
    (root / "老歌手/2001 丙 [cccc3333]").rmdir()
    scanner.scan()
    with session_factory()() as session:
        assert [a.directory for a in session.query(Artist)] == ["AI机组"]
        assert session.query(Album).count() == 2        # 甲 + 乙
        assert session.query(Track).count() == 2        # 曲A + 曲B


def test_scanner_skips_unreadable_and_rejects_double(tmp_path):
    """坏文件不进索引 (重试但读不出); 扫描中重复触发要拒绝。"""
    root = tmp_path / "library"
    root.mkdir()
    broken = root / "X/2000 坏 [00000000]/01 坏.flac"
    broken.parent.mkdir(parents=True)
    # 报了 100 字节的 PICTURE 却没写全 → mutagen 抛错 → 跳过
    broken.write_bytes(
        b"fLaC" + b"\x00\x00\x00\x22" + bytes(34)
        + b"\x86\x00\x00\x64" + bytes(100))
    scanner = _scanner_for(root)
    scanner.scan()
    with session_factory()() as session:
        assert session.query(Track).count() == 0
    # 非阻塞拿锁是刻意的: 验证并发第二把锁立刻报错, 没法写成 with
    assert scanner._scan_lock.acquire(  # noqa: SLF001 pylint: disable=consider-using-with
        blocking=False)
    try:
        with pytest.raises(RuntimeError):
            scanner.scan()
    finally:
        scanner._scan_lock.release()                        # noqa: SLF001


def test_scan_missing_directory_sets_error(tmp_path):
    """曲库目录没了: 异常抛出 + 状态记 error。"""
    scanner = _scanner_for(tmp_path / "nope")
    with pytest.raises(FileNotFoundError):
        scanner.scan()
    assert scanner.status().phase == "error"
    assert scanner.status().error


# ---------------------------------------------------------------- 查询

def _seed_library() -> None:
    """直插索引行 (查询层不走文件系统): 两艺人三专辑五曲目。"""
    with session_factory()() as session:
        ai = Artist(name="AI机组", sort_name="AI, Crew", directory="AI机组")
        old = Artist(name="老歌手", sort_name="", directory="老歌手")
        session.add_all([ai, old])
        session.flush()
        album_1 = Album(title="甲", artist_id=ai.id, year=2019,
                        directory="AI机组/甲", added_at=3000.0,
                        track_count=2, duration_seconds=4.0, has_artwork=True)
        album_2 = Album(title="乙", artist_id=ai.id, year=2020,
                        directory="AI机组/乙", added_at=1000.0,
                        track_count=1, duration_seconds=2.0, has_artwork=False)
        album_3 = Album(title="丙", artist_id=old.id, year=2001,
                        directory="老歌手/丙", added_at=2000.0,
                        track_count=2, duration_seconds=4.0, has_artwork=False)
        session.add_all([album_1, album_2, album_3])
        session.flush()
        session.add_all([
            Track(album_id=album_1.id, title="曲A", artist="AI机组",
                  track_number=1, disc_number=1, duration_seconds=2.0,
                  file_path="AI机组/甲/01.flac", file_format="flac",
                  script="Jpan", lyrics="[00:01.00]さよならの向こう",
                  lyrics_synced=True, has_artwork=True),
            Track(album_id=album_1.id, title="曲B", artist="AI机组",
                  track_number=2, disc_number=1, duration_seconds=2.0,
                  file_path="AI机组/甲/02.flac", file_format="tak",
                  script="Jpan", lyrics=""),
            Track(album_id=album_2.id, title="Hello", artist="AI机组",
                  track_number=1, disc_number=1, duration_seconds=2.0,
                  file_path="AI机组/乙/01.flac", file_format="flac",
                  script="Latn", lyrics="plain text line"),
            Track(album_id=album_3.id, title="曲C", artist="老歌手",
                  track_number=1, disc_number=2, duration_seconds=2.0,
                  file_path="老歌手/丙/01.flac", file_format="flac",
                  script="Hant", lyrics="", file_mtime=2000.0),
            Track(album_id=album_3.id, title="无题曲", artist="老歌手",
                  track_number=2, disc_number=2, duration_seconds=2.0,
                  file_path="老歌手/丙/02.flac", file_format="mp3",
                  script="", lyrics=""),
        ])
        session.commit()


def test_list_albums_sorts_and_filters(tmp_path):
    """added 倒序 / title 字母序; 语种按旗下曲目过滤; 分页总数对。"""
    _seed_library()
    with session_factory()() as session:
        page = library_queries.list_albums(session, sort="added")
        assert [card.title for card in page.albums] == ["甲", "丙", "乙"]
        assert page.total_count == 3
        # title 排序按码点: 丙(4E19) < 乙(4E59) < 甲(7532)
        assert [card.title for card in
                library_queries.list_albums(
                    session, sort="title").albums] == ["丙", "乙", "甲"]
        japanese = library_queries.list_albums(session, language="日文")
        assert [card.title for card in japanese.albums] == ["甲"]
        other = library_queries.list_albums(session, language="其他")
        assert [card.title for card in other.albums] == ["丙"]   # 空 script 曲目
        assert other.albums[0].artist_name == "老歌手"
        assert library_queries.list_albums(session, offset=2).albums[0] \
            .title == "乙"


def test_album_and_artist_pages(tmp_path):
    """专辑页碟/曲排序 + 可播性; 艺人页年份倒序 + 汇总。"""
    _seed_library()
    with session_factory()() as session:
        with session_factory()() as other:
            album_id = other.query(Album).filter_by(title="甲").one().id
            artist_id = other.query(Artist).filter_by(name="AI机组").one().id
        page = library_queries.album_page(session, album_id)
        assert page is not None
        assert page.album.track_count == 2
        assert [track.title for track in page.tracks] == ["曲A", "曲B"]
        assert page.tracks[0].playable and not page.tracks[1].playable  # tak
        assert page.tracks[0].lyrics_available
        assert page.tracks[0].language == "日文"
        assert library_queries.album_page(session, 99999) is None

        artist = library_queries.artist_page(session, artist_id)
        assert artist is not None
        assert [card.title for card in artist.albums] == ["乙", "甲"]  # 年份倒序
        assert artist.artist.album_count == 2
        assert artist.artist.track_count == 3
        assert library_queries.artist_page(session, 99999) is None

        artists = library_queries.list_artists(session)
        assert [brief.name for brief in artists.artists] == ["AI机组", "老歌手"]
        assert artists.artists[0].album_count == 2


def test_list_tracks_and_lyrics(tmp_path):
    """全曲列表: 最近添加的专辑在前, 专辑内按碟/曲; 歌词接口原样给。"""
    _seed_library()
    with session_factory()() as session:
        page = library_queries.list_tracks(session, limit=3)
        assert [track.title for track in page.tracks] == ["曲A", "曲B", "曲C"]
        assert page.total_count == 5
        assert page.offset == 0 and page.limit == 3
        # 语种过滤: 日文 2 首
        japanese = library_queries.list_tracks(session, language="日文")
        assert [track.title for track in japanese.tracks] == ["曲A", "曲B"]
        track_id = page.tracks[0].track_id
        lyrics = library_queries.lyrics_for_track(session, track_id)
        assert lyrics is not None
        assert lyrics.lyrics == "[00:01.00]さよならの向こう"
        assert lyrics.lyrics_synced
        assert library_queries.lyrics_for_track(session, 99999) is None


def test_search_four_boards(tmp_path):
    """搜索: 歌名/专辑/艺人/歌词四板块 + 语种过滤 + LIKE 转义。"""
    _seed_library()
    with session_factory()() as session:
        result = library_queries.search_library(session, "曲A")
        assert [track.title for track in result.tracks] == ["曲A"]
        assert result.albums == [] and result.artists == []

        result = library_queries.search_library(session, "甲")
        assert [card.title for card in result.albums] == ["甲"]
        assert result.tracks == []

        result = library_queries.search_library(session, "AI, Crew")
        assert [brief.name for brief in result.artists] == ["AI机组"]  # 排序名命中

        result = library_queries.search_library(session, "さよなら")
        assert len(result.lyric_hits) == 1
        assert result.lyric_hits[0].line_text == "さよならの向こう"
        assert result.lyric_hits[0].track.title == "曲A"

        # 语种过滤: 英文歌名在日文筛选下不出现
        assert library_queries.search_library(
            session, "hello", "日文").tracks == []
        assert library_queries.search_library(
            session, "hello").tracks[0].title == "Hello"
        # 空串: 空结果
        assert library_queries.search_library(session, "  ").tracks == []
        # 百分号不当通配符
        assert library_queries.search_library(session, "%曲%").tracks == []


# ---------------------------------------------------------------- Range 流

def test_parse_range_header():
    """Range 解析: 常规/开放/尾缀区间, 非法格式, 越界 416。"""
    total = 1000
    first = parse_range_header("bytes=0-1", total)
    assert first is not None and first.model_dump() == {
        "start": 0, "end": 1, "total": total}
    second = parse_range_header("bytes=10-", total)
    assert second is not None and second.model_dump() == {
        "start": 10, "end": 999, "total": total}
    suffix = parse_range_header("bytes=-100", total)
    assert suffix is not None and suffix.model_dump() == {
        "start": 900, "end": 999, "total": total}
    overflow = parse_range_header(      # 越界终点截到文件尾
        "bytes=990-2000", total)
    assert overflow is not None and overflow.end == 999
    assert parse_range_header("not-bytes", total) is None
    assert parse_range_header("bytes=-", total) is None
    with pytest.raises(HTTPException) as exc_info:
        parse_range_header("bytes=1000-", total)     # 起点即越界
    assert exc_info.value.status_code == 416
    with pytest.raises(HTTPException):
        parse_range_header("bytes=-0", total)


# ---------------------------------------------------------------- 接口

def _login(client):
    response = client.post(
        "/api/login",
        json={"user": config.AUTH_USER, "password": config.AUTH_PASS})
    assert response.status_code == 200


def _wait_scan_done(client, timeout=10.0):
    """轮询到扫描收尾 (done/error)。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        scan = client.get("/music/api/status").json()["scan"]
        if not scan["running"]:
            assert scan["phase"] == "done", scan
            return
        time.sleep(0.05)
    raise AssertionError("扫描超时未完成")


def test_music_page_requires_login(auth):
    """页面未登录 302 登录页, 接口未登录 401; 登录后页面 200。"""
    anonymous = TestClient(m.app)      # auth 会登录共享的 client, 这里另开
    assert anonymous.get("/music",
                         follow_redirects=False).status_code == 302
    assert anonymous.get("/music/api/status").status_code == 401
    assert anonymous.get("/music/api/stats").status_code == 401
    assert anonymous.get("/music/api/albums").status_code == 401
    assert auth.get("/music").status_code == 200   # 307 /music/ 跟一步到页面


def test_music_browse_and_search_endpoints(auth):
    """空库: 各接口空结果 + 404 + 参数校验 422。"""
    assert auth.get("/music/api/status").json()["track_count"] == 0
    assert auth.get("/music/api/stats").json() == {
        "artist_count": 0, "album_count": 0, "track_count": 0,
        "total_duration_seconds": 0.0, "formats": []}
    assert auth.get("/music/api/albums").json() == {
        "albums": [], "total_count": 0, "offset": 0, "limit": 60}
    assert auth.get("/music/api/artists").json()["artists"] == []
    assert auth.get("/music/api/tracks").json()["tracks"] == []
    assert auth.get("/music/api/search", params={"q": "x"}).json() == {
        "query": "x", "language": "全部", "tracks": [], "albums": [],
        "artists": [], "lyric_hits": []}
    assert auth.get("/music/api/albums/1").status_code == 404
    assert auth.get("/music/api/artists/1").status_code == 404
    assert auth.get("/music/api/tracks/1/lyrics").status_code == 404
    assert auth.get("/music/api/albums/1/artwork").status_code == 404
    assert auth.get(
        "/music/api/albums", params={"language": "乱写"}).status_code == 422
    assert auth.get(
        "/music/api/albums", params={"sort": "乱写"}).status_code == 422
    assert auth.get(
        "/music/api/tracks", params={"limit": 0}).status_code == 422


def test_music_stats_endpoint(auth):
    """统计页: 库规模 + 总时长 + 格式分布 (多的在前, 同数按名, 播不了标记)。"""
    _seed_library()
    data = auth.get("/music/api/stats").json()
    assert data["artist_count"] == 2 and data["album_count"] == 3
    assert data["track_count"] == 5
    assert data["total_duration_seconds"] == 10.0      # 五曲各 2 秒
    assert data["formats"] == [
        {"format": "flac", "count": 3, "playable": True},
        {"format": "mp3", "count": 1, "playable": True},
        {"format": "tak", "count": 1, "playable": False}]


def test_music_stats_page_wiring():
    """统计页接线: 标签栏第三格 + hash 路由 + 渲染函数 (E2E 再验真数据)。"""
    static = Path(__file__).parent.parent / "app" / "music" / "static"
    html = (static / "music.html").read_text(encoding="utf-8")
    assert 'data-tab="stats"' in html
    assert "stat-grid" in html and "format-bar" in html   # 统计卡片 + 比例条
    js = (static / "music.js").read_text(encoding="utf-8")
    assert 'if (name === "stats") return { view: "stats" };' in js
    assert "function renderStatsView()" in js
    assert '"/music/api/stats"' in js
    assert 'navigate(tab.dataset.tab)' in js              # 标签栏直通各视图


def test_music_rescan_full_flow(auth, tmp_path):
    """手动重扫: 接口触发 → 后台扫 → 浏览/搜索/封面/流全链路有数据。"""
    _make_library(tmp_path / "music-library")
    response = auth.post("/music/api/rescan")
    assert response.status_code == 200 and response.json() == {"started": True}
    _wait_scan_done(auth)

    status = auth.get("/music/api/status").json()
    assert status["artist_count"] == 2 and status["album_count"] == 3
    assert status["track_count"] == 4

    albums = auth.get("/music/api/albums").json()["albums"]
    assert [album["title"] for album in albums] == ["乙", "甲", "丙"]  # added_at 降序
    album_id = albums[1]["album_id"]                      # 甲 (唯一带内嵌封面)
    album_page = auth.get(f"/music/api/albums/{album_id}").json()
    assert album_page["album"]["has_artwork"]
    assert [track["title"] for track in album_page["tracks"]] == ["曲A"]

    # 语种筛选 + 搜索 (歌词命中)
    japanese = auth.get(
        "/music/api/albums", params={"language": "日文"}).json()["albums"]
    assert [album["title"] for album in japanese] == ["乙", "甲"]  # added_at 降序
    hits = auth.get("/music/api/search",
                    params={"q": "乙の"}).json()["lyric_hits"]
    assert hits and hits[0]["line_text"] == "乙の歌詞"
    tracks = auth.get("/music/api/tracks").json()["tracks"]
    assert len(tracks) == 4

    # 封面: 甲有内嵌 → 200 且字节等于 PICTURE; 乙没有 → 404
    artwork = auth.get(f"/music/media/albums/{albums[0]['album_id']}/artwork")
    assert artwork.status_code == 404               # 乙没有内嵌封面
    artwork = auth.get(f"/music/media/albums/{album_id}/artwork")
    assert artwork.status_code == 200
    assert artwork.content == PICTURE_BYTES
    assert artwork.headers["content-type"].startswith("image/jpeg")
    assert "immutable" in artwork.headers["cache-control"]

    # 艺人海报: poster.jpeg 透传
    artists = auth.get("/music/api/artists").json()["artists"]
    with_poster = next(a for a in artists if a["has_poster"])
    poster = auth.get(
        f"/music/media/artists/{with_poster['artist_id']}/artwork")
    assert poster.status_code == 200
    assert poster.content == PICTURE_BYTES

    # 流: 全量 200 + 分段 206
    track_id = album_page["tracks"][0]["track_id"]
    full = auth.get(f"/music/media/stream/{track_id}")
    assert full.status_code == 200
    assert full.headers["content-type"] == "audio/flac"
    assert full.headers["accept-ranges"] == "bytes"
    assert len(full.content) == int(full.headers["content-length"])
    probe = auth.get(f"/music/media/stream/{track_id}",
                     headers={"Range": "bytes=0-1"})
    assert probe.status_code == 206
    assert probe.content == full.content[:2]
    assert probe.headers["content-range"] == f"bytes 0-1/{len(full.content)}"
    tail = auth.get(f"/music/media/stream/{track_id}",
                    headers={"Range": "bytes=10-"})
    assert tail.status_code == 206
    assert tail.content == full.content[10:]
    assert auth.get("/music/media/stream/99999").status_code == 404
    assert auth.get(
        "/music/media/stream/99999",
        headers={"Range": "bytes=0-"}).status_code == 404


def test_music_rescan_conflict(auth, monkeypatch, tmp_path):
    """扫描进行中再触发: 409。"""
    _make_library(tmp_path / "music-library")
    current = service.scanner()
    monkeypatch.setattr(current, "scan", lambda: time.sleep(0.5))
    assert auth.post("/music/api/rescan").status_code == 200
    assert auth.post("/music/api/rescan").status_code == 409
    deadline = time.monotonic() + 5
    while service.scanner().status().running and time.monotonic() < deadline:
        time.sleep(0.02)


def test_matching_lyric_line_pure():
    """歌词命中行: 剥时间轴/大小写不敏感; 全文没命中返回空串。"""
    from app.music.library_queries import _matching_lyric_line  # noqa: SLF001
    lyrics = "[00:01.00]Hello World\n[00:02.00]再见"
    assert _matching_lyric_line(lyrics, "hello") == "Hello World"
    assert _matching_lyric_line(lyrics, "再见") == "再见"
    assert _matching_lyric_line(lyrics, "不存在") == ""


def test_extract_artwork_empty_picture(tmp_path):
    """FLAC 带空 PICTURE 块 (data 为空) → 没有可用封面。"""
    path = _write_audio(tmp_path, "A/a.flac", picture=b"")
    assert extract_album_artwork(path) is None


def test_scanner_batches_updates_and_refills(tmp_path):
    """大专辑走分批提交; 换文件走更新; 空标题/空艺人名扫完回填。"""
    from app.music import library_database as music_db
    root = tmp_path / "library"
    album_dir = "批量乐队/2017 批量 [dddd4444]"
    for index in range(1, 511):                    # 510 首, 超过提交批次 500
        _write_audio(root, f"{album_dir}/{index:03d} 曲{index}.flac",
                     {"TITLE": f"曲{index}", "ARTIST": "批量乐队",
                      "ALBUMARTIST": "批量乐队", "ALBUM": "批量",
                      "ALBUMARTISTSORT": "Batch, Band", "DATE": "2017"},
                     mtime=1000.0)
    (root / album_dir / ".DS_Store").write_bytes(b"junk")     # 隐藏文件跳过
    os.symlink(str(tmp_path / "missing.flac"),
               root / album_dir / "断链.flac")                 # 坏链接 stat 跳过
    scanner = _scanner_for(root)

    summary = scanner.scan()
    assert summary.tracks_scanned == 510 and summary.tracks_removed == 0
    assert summary.artist_count == 1 and summary.album_count == 1
    with session_factory()() as session:
        artist = session.query(Artist).one()
        assert artist.sort_name == "Batch, Band"
        assert session.query(Track).count() == 510

    # 改一个文件 (标题变 + mtime 变) → 只重读这一首, 行是更新不是新增
    _write_audio(root, f"{album_dir}/001 曲1.flac",
                 {"TITLE": "曲一改", "ARTIST": "批量乐队",
                  "ALBUMARTIST": "批量乐队", "ALBUM": "批量", "DATE": "2017"},
                 mtime=5000.0)
    summary = scanner.scan()
    assert summary.tracks_scanned == 1 and summary.tracks_skipped == 509
    with session_factory()() as session:
        assert session.query(Track).filter_by(title="曲一改").count() == 1
        assert session.query(Track).count() == 510

    # 清空专辑标题/艺人名再扫: 没变的文件不重读, 空字段从目录名回填
    with session_factory()() as session:
        session.query(Album).update({"title": ""})
        session.query(Artist).update({"name": ""})
        session.commit()
    assert scanner.scan().tracks_scanned == 0
    with session_factory()() as session:
        assert session.query(Album).one().title == "批量"
        assert session.query(Artist).one().name == "批量乐队"
    assert music_db.artwork_cache_directory().name == "music-art"


def test_engine_state_guards(tmp_path):
    """引擎模块的守卫: 未初始化全炸, 非SQLite库封面缓存落到 data/, dispose 幂等。"""
    from app.music import library_database as music_db
    service.stop_service()
    for accessor in (music_db.engine, music_db.session_factory,
                     music_db.music_directory, music_db.artwork_cache_directory):
        with pytest.raises(RuntimeError):
            accessor()
    music_db.init_engine(None)                    # 缺省 URL/曲库目录
    assert music_db.music_directory() == Path(music_db.DEFAULT_MUSIC_DIRECTORY)
    assert music_db.artwork_cache_directory_for(
        "postgresql://u:p@localhost/db") == Path("data") / "music-art"
    assert music_db.artwork_cache_directory_for(
        f"sqlite:///{tmp_path / 'x.db'}") == tmp_path / "music-art"
    music_db.dispose_engine()
    music_db.dispose_engine()                     # 重复释放不炸
    service.start_service(f"sqlite:///{tmp_path / 'guards.db'}",
                          tmp_path / "guards-library", scan_immediately=False)
    assert music_db.engine() is not None


def test_music_service_lifecycle(auth, tmp_path):
    """服务单例: 停了没扫描器/触发被拒; 起来自动首扫; 重复扫描静默让位。"""
    service.stop_service()
    with pytest.raises(RuntimeError):
        service.scanner()
    assert service.trigger_scan() is False        # 没有扫描器
    empty = tmp_path / "empty-library"
    empty.mkdir()
    service.start_service(f"sqlite:///{tmp_path / 'lifecycle.db'}", empty,
                          scan_immediately=True)  # 启动即首扫 (空目录秒完)
    deadline = time.monotonic() + 5
    while service.scanner().status().running and time.monotonic() < deadline:
        time.sleep(0.02)
    assert service.scanner().status().phase == "done"
    current = service.scanner()
    with current._scan_lock:                      # noqa: SLF001 顶住锁再跑 → 让位
        service._run_scan(current)                # noqa: SLF001 不抛即过


def test_media_edge_cases(auth, tmp_path):
    """媒体边界: DSF 抽不出封面 404 / 封面缓存命中 / 海报缺失 / 源文件被删。"""
    from app.music.library_media import _file_slice  # noqa: SLF001
    root = tmp_path / "music-library"
    _make_library(root)
    _write_dsf_audio(root, "DSF艺人/2018 DSDの作品 [dddd4444]/01 DSDの曲.dsf")
    assert auth.post("/music/api/rescan").status_code == 200
    _wait_scan_done(auth)
    status = auth.get("/music/api/status").json()
    assert status["track_count"] == 5 and status["album_count"] == 4

    albums = {album["title"]: album["album_id"]
              for album in auth.get("/music/api/albums").json()["albums"]}
    # DSF 专辑有内嵌 APIC 但只支持抽 FLAC → 抽取失败 404
    assert auth.get(
        f"/music/media/albums/{albums['DSD专辑']}/artwork").status_code == 404
    assert auth.get("/music/media/albums/99999/artwork").status_code == 404

    # 甲的封面: 第一次抽取落缓存, 第二次直接命中缓存文件
    assert auth.get(
        f"/music/media/albums/{albums['甲']}/artwork").content == PICTURE_BYTES
    assert auth.get(
        f"/music/media/albums/{albums['甲']}/artwork").content == PICTURE_BYTES

    # 艺人海报: 没海报的 404; 有海报但文件被删 404
    artists = {artist["name"]: artist["artist_id"]
               for artist in auth.get("/music/api/artists").json()["artists"]}
    assert auth.get(
        f"/music/media/artists/{artists['老歌手']}/artwork").status_code == 404
    (root / "AI机组/poster.jpeg").unlink()
    assert auth.get(
        f"/music/media/artists/{artists['AI机组']}/artwork").status_code == 404
    assert auth.get("/music/media/artists/99999/artwork").status_code == 404

    # 艺人详情 (年份倒序) + 单曲歌词的成功路径
    artist_page = auth.get(f"/music/api/artists/{artists['AI机组']}").json()
    assert [album["title"] for album in artist_page["albums"]] == ["乙", "甲"]
    tracks = auth.get("/music/api/tracks").json()["tracks"]
    qu_b = next(track for track in tracks if track["title"] == "曲B")
    lyrics = auth.get(f"/music/api/tracks/{qu_b['track_id']}/lyrics").json()
    assert lyrics["lyrics_synced"] and "乙の歌詞" in lyrics["lyrics"]

    # 源文件被删 (索引还在): 流 404; 尾缀 Range 比文件长 → 从 0 开始的 206
    dsf_track = next(track for track in tracks
                     if track["file_format"] == "dsf")
    suffix = auth.get(f"/music/media/stream/{dsf_track['track_id']}",
                      headers={"Range": "bytes=-999999"})
    assert suffix.status_code == 206 and suffix.content == auth.get(
        f"/music/media/stream/{dsf_track['track_id']}").content
    (root / "DSF艺人/2018 DSDの作品 [dddd4444]/01 DSDの曲.dsf").unlink()
    assert auth.get(
        f"/music/media/stream/{dsf_track['track_id']}").status_code == 404

    # _file_slice 读过文件尾: 产出到 EOF 就收手, 不无限读
    flac = root / "AI机组/2019 甲 [aaaa1111]/01 曲A.flac"
    assert b"".join(_file_slice(flac, 0, 10 ** 12)) == flac.read_bytes()


def test_music_webapp_fallbacks(auth):
    """webapp 兜底: 登出 / 数据库异常 503 / 会话失效 401 / 资源不存在 404。"""
    from sqlalchemy.exc import SQLAlchemyError
    patched_queries = library_queries
    with pytest.MonkeyPatch.context() as patcher:   # 只撤自己的补丁
        patcher.setattr(patched_queries, "list_albums",
                        lambda *a, **k: (_ for _ in ()).throw(
                            SQLAlchemyError("boom")))
        assert auth.get("/music/api/albums").status_code == 503
    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr("app.account_store.user_for_cookie",
                        lambda *a, **k: None)
        assert auth.get("/music/api/status").status_code == 401
    assert auth.get("/music/api/artists/99999").status_code == 404
    assert auth.get("/music/api/tracks/99999/lyrics").status_code == 404
    response = auth.post("/music/api/logout")     # 登出清 cookie, 放最后
    assert response.status_code == 200 and response.json() == {"ok": True}
