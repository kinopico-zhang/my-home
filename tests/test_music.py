"""My Music 测试: 语言检测 / 标签读取 / 扫描器增量 / 查询 / Range 流 / 接口。

音频文件是手工拼的最小 FLAC (魔数 + STREAMINFO + VORBIS_COMMENT + PICTURE),
不依赖曲库真文件; 扫描器用临时曲库目录, 接口用 TestClient 走完整 HTTP 栈。
"""
import os
import struct
import threading
import time
from pathlib import Path
from typing import Callable

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

import app.main as m
from app import account_store, config
from app.music import service
from app.music.library_database import (Album, Artist, PlayStat, Track,
                                        session_factory)
from app.music.library_languages import (detect_script, language_for_script,
                                         scripts_for_language)
from app.music.library_media import parse_range_header
from app.music.library_scanner import LibraryScanner, backfill_legacy_rows
from app.music.library_tags import (extract_album_artwork,
                                    read_track_metadata)
from app.music import library_playlists, library_queries
from app.music import library_search_keys

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
                  "SCRIPT": "Jpan", "ALBUM": "甲", "DATE": "2019",
                  "LYRICIST": "词人甲", "COMPOSER": "曲人乙"},
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


def test_lyrics_online_fetch_and_negative_cache(tmp_path, monkeypatch):
    """联网补歌词: 求到写回索引; 求不到记 24 小时负缓存 (同一首不再打外网)。"""
    _seed_library()
    library_queries._lyrics_fetch_misses.clear()   # 模块级账本, 别让别的测试留旧账
    calls = []

    def fake_fetch(api_base, title, artist, album_title):
        calls.append(title)
        return "[00:01.00]联网歌词" if title == "曲B" else ""

    monkeypatch.setattr(library_queries, "fetch_lyrics", fake_fetch)
    api = (True, "https://lrc.invalid/api")
    with session_factory()() as session:
        page = library_queries.list_tracks(session, limit=10)
        ids = {track.title: track.track_id for track in page.tracks}

        # 曲B: 求到 → 写回, 之后再问直接走库 (不再打外网)
        got = library_queries.lyrics_for_track(session, ids["曲B"], api)
        assert got is not None
        assert got.lyrics == "[00:01.00]联网歌词" and got.lyrics_synced
        assert library_queries.lyrics_for_track(session, ids["曲B"], api) == got
        assert calls == ["曲B"]

        # 曲C: 求不到 → 保持空, 负缓存挡住紧跟着的再问
        miss = library_queries.lyrics_for_track(session, ids["曲C"], api)
        assert miss is not None and miss.lyrics == "" and not miss.lyrics_synced
        again = library_queries.lyrics_for_track(session, ids["曲C"], api)
        assert again is not None and again.lyrics == ""
        assert calls == ["曲B", "曲C"]


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


# ------------------------------------------------------ 检索键 / 入库时间

def test_search_key_variants():
    """纯函数: 原文/简体化/全拼/声母 + 去空格变体; 查询词简繁互换。"""
    keys = library_search_keys.search_keys("周傑倫")
    assert "周傑倫" in keys               # 原文 (小写化)
    assert "周杰伦" in keys               # 简体化 → 简体搜索词直接命中
    assert "zhoujielun" in keys           # 全拼
    assert "zjl" in keys                  # 声母
    squashed = library_search_keys.search_keys("Jay Chou")
    assert "jaychou" in squashed          # 去空格后能整词搜
    assert library_search_keys.search_keys("") == ""

    patterns = library_search_keys.query_patterns("周傑倫")
    assert patterns == ["周傑倫", "周杰伦"]     # 繁体词也带简体形态去撞键
    assert library_search_keys.query_patterns("晴天 jay") == [
        "晴天 jay", "晴天jay"]
    assert not library_search_keys.query_patterns("   ")


def _seed_search_library() -> None:
    """繁体名直插 (键齐全): 拼音/简繁互搜的目标行。"""
    with session_factory()() as session:
        artist = Artist(name="周杰倫", sort_name="", directory="周杰倫",
                        search_keys=library_search_keys.search_keys("周杰倫"))
        session.add(artist)
        session.flush()
        album = Album(title="七里香", artist_id=artist.id, year=2004,
                      directory="周杰倫/七里香",
                      search_keys=library_search_keys.search_keys(
                          "七里香", "周杰倫"))
        session.add(album)
        session.flush()
        session.add(Track(
            album_id=album.id, title="晴天", artist="周杰倫", track_number=1,
            disc_number=1, duration_seconds=269.0,
            file_path="周杰倫/七里香/01 晴天.flac", file_format="flac",
            script="Hant", lyrics="",
            search_keys=library_search_keys.search_keys(
                "晴天", "周杰倫", "七里香")))
        session.commit()


def test_search_pinyin_and_simplified_traditional(tmp_path):
    """拼音全拼/声母搜中文, 简体词搜繁体名, 原词搜简体名 (键里双向都存)。"""
    _seed_search_library()
    with session_factory()() as session:
        result = library_queries.search_library(session, "zhoujielun")
        assert [brief.name for brief in result.artists] == ["周杰倫"]
        assert [brief.name for brief in
                library_queries.search_library(
                    session, "zjl").artists] == ["周杰倫"]
        assert [brief.name for brief in
                library_queries.search_library(
                    session, "周杰伦").artists] == ["周杰倫"]   # 简查繁
        assert [brief.name for brief in
                library_queries.search_library(
                    session, "周杰倫").artists] == ["周杰倫"]   # 繁查繁
        assert [track.title for track in
                library_queries.search_library(
                    session, "qingtian").tracks] == ["晴天"]
        assert [track.title for track in
                library_queries.search_library(
                    session, "qt").tracks] == ["晴天"]
        assert [card.title for card in
                library_queries.search_library(
                    session, "qilixiang").albums] == ["七里香"]


def test_backfill_legacy_rows_fills_added_at_and_keys(tmp_path):
    """老行 (无键无入库时刻): 补数后 added_at 拿文件时间兜底, 键可拼音搜。"""
    _seed_library()
    added_at_count, key_count = backfill_legacy_rows(session_factory())
    assert (added_at_count, key_count) == (1, 5)   # 只有曲C 有文件时间
    with session_factory()() as session:
        track = session.query(Track).filter_by(title="曲C").one()
        assert track.added_at == 2000.0            # 只有文件时间可当线索
        no_mtime = session.query(Track).filter_by(title="曲A").one()
        assert no_mtime.added_at == 0.0            # 没线索的保持未知 (当最老)
        assert "quc" in track.search_keys
        artist = session.query(Artist).filter_by(name="老歌手").one()
        assert "laogeshou" in artist.search_keys
        album = session.query(Album).filter_by(title="丙").one()
        assert "bing" in album.search_keys
        result = library_queries.search_library(session, "lgs")
        assert [brief.name for brief in result.artists] == ["老歌手"]
        # 幂等: 再补一遍无事可做
        assert backfill_legacy_rows(session_factory()) == (0, 0)


def test_added_at_recorded_on_insert_preserved_on_rescan(tmp_path):
    """入库时刻只在首插记: 重扫 (mtime 都拨到未来) 不改; 新文件自己的时刻;
    专辑汇到旗下最晚。"""
    root = tmp_path / "library"
    _make_library(root)
    scanner = _scanner_for(root)
    before = time.time()
    scanner.scan()
    with session_factory()() as session:
        first = {track.file_path: track.added_at
                 for track in session.query(Track)}
        assert first and all(value >= before for value in first.values())
        for album_row in session.query(Album).all():
            track_times = [track.added_at for track in session.query(Track)
                           .filter_by(album_id=album_row.id)]
            assert album_row.added_at == max(track_times)   # 旗下最晚入库

    future = time.time() + 5000
    for flac in root.rglob("*.flac"):
        os.utime(flac, (future, future))
    scanner.scan()
    with session_factory()() as session:
        assert {track.file_path: track.added_at
                for track in session.query(Track)} == first

    _write_audio(root, "AI机组/2021 丁 [dddd4444]/01 曲E.flac",
                 {"TITLE": "曲E", "ARTIST": "AI机组", "ALBUMARTIST": "AI机组",
                  "ALBUM": "丁", "DATE": "2021"}, mtime=100.0)
    scanner.scan()
    with session_factory()() as session:
        track = session.query(Track).filter_by(title="曲E").one()
        assert track.added_at >= before
        album = session.query(Album).filter_by(title="丁").one()
        assert album.added_at == track.added_at


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
    """轮询到扫描收尾 (done/error); idle 只是还没开始, 不算失败。

    触发返回后到线程真正置起 running 之间有个窗口 (状态还是 idle),
    一进就断言会冤枉好扫描; 真没扫起来 (触发被拒) 则一直 idle 到超时。"""
    deadline = time.monotonic() + timeout
    scan = {}
    while time.monotonic() < deadline:
        scan = client.get("/music/api/status").json()["scan"]
        if not scan["running"] and scan["phase"] != "idle":
            assert scan["phase"] == "done", scan
            return
        time.sleep(0.05)
    raise AssertionError(f"扫描超时未完成: {scan}")


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
    """统计页接线: 收进品牌下拉菜单 + hash 路由 + 渲染函数 (E2E 再验真数据)。"""
    static = Path(__file__).parent.parent / "app" / "music" / "static"
    html = (static / "music.html").read_text(encoding="utf-8")
    assert 'id="stats-link"' in html
    assert "stat-grid" in html and "format-bar" in html   # 统计卡片 + 比例条
    js = (static / "music.js").read_text(encoding="utf-8")
    assert 'if (name === "stats") return { view: "stats" };' in js
    assert "function renderStatsView()" in js
    assert '"/music/api/stats"' in js
    assert 'navigate("stats")' in js                      # 菜单按钮直通统计页


def test_music_home_page_wiring():
    """主页接线: 顶栏页签主页/资料库/搜索 + 播放列表/最近播放两段 +
    播放列表详情路由 (E2E 再验真数据)。"""
    static = Path(__file__).parent.parent / "app" / "music" / "static"
    html = (static / "music.html").read_text(encoding="utf-8")
    assert 'id="view-tabs"' in html
    assert ('data-view-tab="home"' in html and 'data-view-tab="library"' in html
            and 'data-view-tab="search"' in html)   # 搜索收进页签
    assert 'id="search-btn"' not in html    # 放大镜按钮已撤 (顶栏单行)
    assert 'id="sync-playlists"' not in html     # Plex 同步入口已撤
    assert "playlist-row" in html                  # 行样式在
    js = (static / "music.js").read_text(encoding="utf-8")
    assert "function renderHomeView()" in js
    assert '"/music/api/plays/recent?limit=20"' in js
    assert '"/music/api/playlists"' in js          # 主页播放列表段
    assert 'if (name === "playlist" && argument)' in js
    assert "function renderPlaylistView(" in js
    assert "playlistRowHTML" in js
    # 默认进主页; 旧段名 (recent/playlists) 收窄后回落专辑
    assert 'history.replaceState(null, "", "#home")' in js
    assert '["albums", "专辑"], ["artists", "艺人"], ["songs", "歌曲"], ["downloads", "已下载"]' in js


def test_music_downloads_wiring():
    """下载接线: 纯逻辑模块 (node 直测) + SW 拦流 + 已下载段 + 能力门控 + 下载管理。"""
    static = Path(__file__).parent.parent / "app" / "music" / "static"
    js = (static / "music.js").read_text(encoding="utf-8")
    assert "downloadsSupported" in js and "createDownloads" in js
    assert '"/music/sw.js"' in js                  # SW 注册
    assert "isSecureContext" in js                 # 明文 HTTP 整个功能收起
    assert 'segment === "downloads"' in js         # 已下载段不走接口分页
    assert "data-download-track" in js             # 曲目行下载标
    assert "storageUsage" in js and "formatBytes" in js    # 下载管理: 量大小并显示
    assert "dl-clear-all" in js and "removeAll" in js      # 一键清空 (confirm 后)
    assert "navigator.storage.estimate" in js      # 手机存储占用
    # 已下载行也带封面: 曲目封面接口 + 裂图退音符 (和播放列表行同款)
    assert 'src="/music/media/tracks/${entry.track_id}/artwork"' in js
    downloads_js = (static / "downloads.js").read_text(encoding="utf-8")
    assert "/music/media/stream/" in downloads_js  # 缓存键 = 音频流地址
    assert "AbortController" in downloads_js       # 下载中的删除 = 取消下载
    html = (static / "music.html").read_text(encoding="utf-8")
    assert ".dl-stats" in html and ".dl-clear" in html    # 统计行样式
    assert ("downloads.js?v=2" in html and "music.js?v=24" in html
            and "music-player.js?v=18" in html
            and "music-common.js?v=13" in html
            and "player-queue.js?v=3" in html)   # 版本号刷新
    sw = (static / "sw.js").read_text(encoding="utf-8")
    assert "TRACK_URL_PATTERN" in sw               # 曲目流: 缓存回源 + Range 切片
    assert "caches.open" in sw and "206" in sw
    assert "music-shell" in sw                     # 应用壳也进缓存 (断网打得开)
    assert "clients.claim" in sw                   # 装完立刻接管已开的页面


def test_music_service_worker_endpoint(client):
    """SW 脚本: 无需登录 200 (SW 更新检查不带 cookie), JS 类型, 可缓存校验。"""
    response = client.get("/music/sw.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    assert "music-downloads-v1" in response.text
    assert response.headers["cache-control"] == "no-cache"


def test_music_rescan_full_flow(auth, tmp_path):
    """手动重扫: 接口触发 → 后台扫 → 浏览/搜索/封面/流全链路有数据。

    分三批写文件重扫 (甲 → 乙 → 丙), 入库时间逐批变晚 → 最近添加 = 丙乙甲。"""
    root = tmp_path / "music-library"
    _write_audio(root, "AI机组/2019 甲 [aaaa1111]/01 曲A.flac",
                 {"TITLE": "曲A", "ARTIST": "AI机组", "ALBUMARTIST": "AI机组",
                  "SCRIPT": "Jpan", "ALBUM": "甲", "DATE": "2019"},
                 picture=PICTURE_BYTES, mtime=2000.0)
    assert auth.post("/music/api/rescan").json() == {"started": True}
    _wait_scan_done(auth)                              # 第一批: 甲

    _write_audio(root, "AI机组/2020 乙 [bbbb2222]/01 曲B.flac",
                 {"TITLE": "曲B", "ARTIST": "AI机组", "ALBUMARTIST": "AI机组",
                  "SCRIPT": "Jpan", "ALBUM": "乙", "DATE": "2020",
                  "LYRICS": "[00:01.00]乙の歌詞"}, mtime=3000.0)
    (root / "AI机组/poster.jpeg").write_bytes(PICTURE_BYTES)
    assert auth.post("/music/api/rescan").json() == {"started": True}
    _wait_scan_done(auth)                              # 第二批: 乙

    _write_audio(root, "老歌手/2001 丙 [cccc3333]/01 曲C.flac",
                 {"TITLE": "曲C", "ARTIST": "老歌手", "ALBUMARTIST": "老歌手",
                  "SCRIPT": "Hant", "ALBUM": "丙", "DATE": "2001"}, mtime=1000.0)
    _write_audio(root, "老歌手/2001 丙 [cccc3333]/02 曲D.flac", {}, mtime=1000.0)
    assert auth.post("/music/api/rescan").json() == {"started": True}
    _wait_scan_done(auth)                              # 第三批: 丙

    status = auth.get("/music/api/status").json()
    assert status["artist_count"] == 2 and status["album_count"] == 3
    assert status["track_count"] == 4

    albums = auth.get("/music/api/albums").json()["albums"]
    assert [album["title"] for album in albums] == ["丙", "乙", "甲"]  # 入库降序
    album_id = albums[2]["album_id"]                      # 甲 (唯一带内嵌封面)
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


def test_playlist_create_add_delete(tmp_path):
    """查询层: 列表建/加/删全在应用内; 撞名/空名报错; 同一首只留一份
    (重复行会两行一起亮播放态、连播两遍, 2026-09-15 用户点名)。"""
    _seed_library()
    with session_factory()() as session:
        created = library_playlists.create_playlist(session, " 我的日常 ")
        assert created.name == "我的日常"            # 名字收边
        assert created.is_local is True
        assert created.track_count == 0
        with pytest.raises(ValueError):              # 撞自己的名
            library_playlists.create_playlist(session, "我的日常")
        with pytest.raises(ValueError):              # 空名
            library_playlists.create_playlist(session, "  ")
        # 加歌 (种子库第一首是 曲A): 计数/时长跟着走, 详情有序
        brief = library_playlists.add_track_to_playlist(
            session, created.playlist_id, 1)
        assert brief.track_count == 1
        assert brief.duration_seconds == pytest.approx(2.0)
        with pytest.raises(ValueError, match="已经在列表里"):
            library_playlists.add_track_to_playlist(
                session, created.playlist_id, 1)     # 同首不再重复加
        page = library_queries.playlist_page(session, created.playlist_id)
        assert page is not None
        assert [t.title for t in page.tracks] == ["曲A"]
        assert page.tracks[0].artist_id == 1         # 艺人号随行走 (长按菜单用)
        with pytest.raises(KeyError):                # 曲目不在库
            library_playlists.add_track_to_playlist(
                session, created.playlist_id, 9999)
        # 移出一首 (左滑删除): 再加两首构成顺序, 抽中间那首, 首尾顺序不动
        library_playlists.add_track_to_playlist(session, created.playlist_id, 3)
        library_playlists.add_track_to_playlist(session, created.playlist_id, 5)
        brief = library_playlists.remove_track_from_playlist(
            session, created.playlist_id, 3)
        assert brief.track_count == 2
        assert brief.duration_seconds == pytest.approx(4.0)
        page = library_queries.playlist_page(session, created.playlist_id)
        assert page is not None
        assert [t.title for t in page.tracks] == ["曲A", "无题曲"]
        for bad_playlist, bad_track in ((created.playlist_id, 3), (99999, 1)):
            with pytest.raises(KeyError):         # 不在列表里 / 列表不在库
                library_playlists.remove_track_from_playlist(
                    session, bad_playlist, bad_track)
        # 列表: 连成员一起清; 再删 404 路径 (KeyError)
        library_playlists.delete_playlist(session, created.playlist_id)
        assert library_queries.playlist_page(session, created.playlist_id) is None
        with pytest.raises(KeyError):
            library_playlists.delete_playlist(session, created.playlist_id)


def test_playlist_endpoints(auth):
    """接口层: 新建/加歌/删除; 撞名 409, 不存在 404; 同步接口已撤 (404)。"""
    _seed_library()
    created = auth.post("/music/api/playlists",
                        json={"name": " 开车听 "}).json()
    assert created["name"] == "开车听"
    assert created["is_local"] is True
    assert auth.post("/music/api/playlists",
                     json={"name": "开车听"}).status_code == 409
    assert auth.post("/music/api/playlists",
                     json={"name": " "}).status_code == 409
    # 加歌 + 回读: 详情带曲目行, 行里带艺人号; 同首再加 409 (不重复入列)
    added = auth.post(f"/music/api/playlists/{created['playlist_id']}/tracks",
                      json={"track_id": 1})
    assert added.json()["track_count"] == 1
    dup = auth.post(f"/music/api/playlists/{created['playlist_id']}/tracks",
                    json={"track_id": 1})
    assert dup.status_code == 409 and "已经在列表里" in dup.json()["detail"]
    page = auth.get(f"/music/api/playlists/{created['playlist_id']}").json()
    assert [t["title"] for t in page["tracks"]] == ["曲A"]
    assert page["tracks"][0]["artist_id"] == 1
    assert auth.post(f"/music/api/playlists/{created['playlist_id']}/tracks",
                     json={"track_id": 999}).status_code == 404
    # 左滑移出一首: (曲A 已在) 再加两首抽中间, 计数回走、顺序不乱;
    # 不在列表里 404、列表不存在 404
    for track_id in (3, 5):
        assert auth.post(f"/music/api/playlists/{created['playlist_id']}/tracks",
                         json={"track_id": track_id}).status_code == 200
    removed = auth.delete(
        f"/music/api/playlists/{created['playlist_id']}/tracks/3")
    assert removed.json()["track_count"] == 2
    assert [t["title"] for t in auth.get(
        f"/music/api/playlists/{created['playlist_id']}").json()["tracks"]] \
        == ["曲A", "无题曲"]
    assert auth.delete(f"/music/api/playlists/{created['playlist_id']}"
                       "/tracks/3").status_code == 404
    assert auth.delete("/music/api/playlists/99999/tracks/1").status_code == 404
    # Plex 同步接口撤了 (路径撞详情路由, 撤后只剩 GET → 405)
    assert auth.post("/music/api/playlists/sync").status_code == 405
    # 删除: 任何列表都删得掉; 再删 404
    assert auth.delete(
        f"/music/api/playlists/{created['playlist_id']}").json() == {"ok": True}
    assert auth.get("/music/api/playlists").json()["playlists"] == []
    assert auth.delete(
        f"/music/api/playlists/{created['playlist_id']}").status_code == 404
    assert auth.get("/music/api/playlists/99999").status_code == 404


def test_music_track_context_menu_wiring():
    """长按菜单接线: 检测 (500ms/右键/移动作废)、菜单四项、选择单、
    分享回落都在页面上; 行样式禁掉 iOS 长按气泡。"""
    static = Path(__file__).parent.parent / "app" / "music" / "static"
    html = (static / "music.html").read_text(encoding="utf-8")
    js = (static / "music.js").read_text(encoding="utf-8")
    for frag in ['id="track-menu"', 'id="track-menu-mask"',
                 'data-track-action="play"', 'data-track-action="artist"',
                 'data-track-action="playlist"', 'data-track-action="share"',
                 'id="track-menu-artist"', 'id="picker-sheet"',
                 'id="picker-list"', 'id="picker-create"', 'id="picker-name"',
                 'id="picker-close"', 'id="picker-mask"',
                 "-webkit-touch-callout: none"]:
        assert frag in html, f"播放页缺少 {frag}"
    for frag in ["function openTrackMenu", "function cancelTrackPress",
                 "function trackFromRow", "function shareTrack",
                 "function openPlaylistPicker", "trackListBindings",
                 "trackPressTimer = setTimeout",            # 500ms 长按计时
                 'document.addEventListener("contextmenu"',
                 "navigator.share", "execCommand",          # 分享 + 复制回落
                 "suppressTrailingTarget",                 # 长按尾随点击按元素吞
                 "navigate(`artist/${track.artist_id}`)",
                 'fetchJSON("/music/api/playlists"',
                 '`/music/api/playlists/${playlistId}/tracks`',
                 "error.status === 409",            # 已在列表里: 直说原因不算失败
                 '`/music/api/playlists/${playlistId}`, { method: "DELETE" }',
                 'id="playlist-delete"',           # 列表删除在详情页 (选择单只加歌)
        ]:
        assert frag in js, f"music.js 缺少 {frag}"
    # 新版图标/脚本地址随行; Plex 同步全撤了
    assert "music.js?v=24" in html
    # 长歌名不许把菜单撑超宽 (用户报"菜单非常宽, 建议截断"): 固定定位菜单
    # 收缩到内容, 不封顶会一路撑到视口; 320px 封顶后 nowrap 截断才接管
    assert "max-width: min(320px, calc(100vw - 24px))" in html
    # fetchJSON 把 HTTP 状态码挂上错误对象 (加歌 409 分叉靠它)
    common = (static / "music-common.js").read_text(encoding="utf-8")
    assert "status: response.status" in common
    assert "picker-sync" not in html and "picker-sync" not in js
    assert "picker-del" not in html and "picker-del" not in js
    assert "sync-playlists" not in html and "/playlists/sync" not in js


def test_music_settings_view_wiring():
    """设置页接线: 菜单入口 + 表单三件 (曲库路径/歌词开关/API 地址) +
    流量月账; 普通账号只读 (开关/输入框锁着, 保存钮不出)。"""
    static = Path(__file__).parent.parent / "app" / "music" / "static"
    html = (static / "music.html").read_text(encoding="utf-8")
    js = (static / "music.js").read_text(encoding="utf-8")
    assert '<button id="settings-link">设置</button>' in html
    assert ".settings-block" in html and ".switch" in html and ".month-row" in html
    assert 'if (name === "settings") return { view: "settings" };' in js
    assert "function renderSettingsView()" in js
    assert 'fetchJSON("/music/api/settings")' in js
    assert 'fetchJSON("/api/me")' in js and "editable" in js   # 按管理员分叉
    assert "music_directory" in js and "lyrics_api_enabled" in js \
        and "lyrics_api_base" in js
    assert "monthRowHTML" in js and "cellular_months" in js   # 月账一段
    assert 'const lock = editable ? "" : " disabled"' in js    # 只读锁
    assert "仅管理员可修改" in js                              # 非管理员的落地面


def test_music_cellular_wiring():
    """蜂窝流量接线: 纯逻辑模块 (node 直测) + 安卓 connection.type 判定 +
    keepalive 上报 + onHide 兜底 (切后台/离页都报)。"""
    static = Path(__file__).parent.parent / "app" / "music" / "static"
    html = (static / "music.html").read_text(encoding="utf-8")
    js = (static / "music.js").read_text(encoding="utf-8")
    assert "cellular-usage.js?v=1" in html                     # 模块加载
    assert "createCellularMonitor" in js
    assert 'connection.type === "cellular"' in js              # 只有认得出的才记
    assert '"/music/api/cellular-usage"' in js and "keepalive: true" in js
    assert "pagehide" in js and "visibilitychange" in js       # 离页/切后台兜底


def test_music_playlist_cover_and_track_art_wiring():
    """封面接线: 详情页点大封面换图, 长按/右键弹菜单 (换/移除) + 隐藏文件选择器;
    列表行/选择单/主页播放列表带封面; 曲目行带元数据封面 (没封面给音符占位)。"""
    static = Path(__file__).parent.parent / "app" / "music" / "static"
    html = (static / "music.html").read_text(encoding="utf-8")
    js = (static / "music.js").read_text(encoding="utf-8")
    common = (static / "music-common.js").read_text(encoding="utf-8")
    assert 'id="cover-file"' in html \
        and 'accept="image/png,image/jpeg,image/webp"' in html
    assert ".t-art" in html and ".pl-icon.art" in html           # 行样式
    assert "function uploadPlaylistCover" in js
    assert 'id="cover-tap"' in js and "function bindCoverPress" in js \
        and "openCoverMenu" in js          # 点封面直接换; 长按/右键弹封面菜单
    assert 'id="cover-menu"' in html and 'data-cover-action="change"' in html \
        and 'data-cover-action="remove"' in html \
        and 'id="cover-menu-remove"' in html                    # 菜单项 (移除可藏)
    assert "cover-hint" in html and "pl-cover-btn" in html       # 角标提示可点
    assert '`/music/api/playlists/${playlistId}/cover`' in js  # PUT/DELETE 两个口
    assert '`/music/api/playlists/${coverMenuPlaylistId}/cover`' in js  # 移除走菜单
    assert "trackArtHTML" in js and "has_artwork" in js        # 曲目封面 (含占位)
    assert 'onerror="this.replaceWith(' in js   # 封面取不到退回音符占位, 不裂图
    assert "function trackArtworkURL" in common and "artwork?v=" in common
    assert "function playlistCoverURL" in common \
        and "playlists/${playlist.playlist_id}/cover" in common


def test_music_search_page_and_lockscreen_wiring():
    """1.4.1 后半批接线: 搜索页语种筛选撤掉 (搜全语种, 资料库筛选保留) +
    页面不许横向溢出 (标题/右列文字收口, 长艺人名撑不宽) +
    锁屏进度随暂停/跳句/变速重报真实位置。"""
    static = Path(__file__).parent.parent / "app" / "music" / "static"
    html = (static / "music.html").read_text(encoding="utf-8")
    js = (static / "music.js").read_text(encoding="utf-8")
    player = (static / "music-player.js").read_text(encoding="utf-8")
    # 搜索页: 语种 chips 撤了, 查询不再带 language; 资料库的筛选行保留
    assert "search-chips" not in js and "search-chips" not in html
    assert "lib-chips" in js and "chipsHTML" in js
    assert "&language=" not in js
    # 横向溢出: html 兜底禁横滑 + 行内标题包收缩层 + 右列可省略
    assert "overflow: hidden" in html   # 固定壳 (2026-09-16): 连 x 带 y 一起锁
    assert ".t-title-text" in html and "t-title-text" in js
    t_time_block = html.split(".t-time {", 1)[1].split("}", 1)[0]
    assert "min-width: 0" in t_time_block and "ellipsis" in t_time_block
    # 锁屏进度: 暂停 (速率报 0) / 跳句 / 变速 / timeupdate 都重报
    assert "function syncPositionState" in player
    assert '"play", "pause", "seeked", "ratechange"' in player
    assert "audio.paused ? 0 : audio.playbackRate" in player
    assert "setPositionState" in player
    assert "syncPositionState();" in player       # timeupdate 里也在报


def test_music_lyrics_animation_wiring():
    """歌词滚动动画接线: 当前行放大清晰/其余模糊退后 (CSS 缓动) +
    rAF 逐帧缓动滚动, 手指一按就让位 (JS)。"""
    static = Path(__file__).parent.parent / "app" / "music" / "static"
    html = (static / "music.html").read_text(encoding="utf-8")
    player = (static / "music-player.js").read_text(encoding="utf-8")
    assert ".lyrics-line {" in html and "filter: blur(3px)" in html   # 其余模糊
    assert ".lyrics-line.active" in html and "font-size: 26px" in html \
        and "blur(0)" in html                                          # 当前行放大清晰
    assert "transition: filter .5s" in html                            # 状态切换也缓动
    for frag in ["function scrollLyricsTo", "function lyricsScrollFrame",
                 "function cancelLyricsScroll", "lyricsScrollRaf",
                 '"pointerdown", cancelLyricsScroll']:   # 手动滚动优先于动画
        assert frag in player, f"music-player.js 缺少 {frag}"


def test_music_click_play_starts_from_beginning():
    """点播一律从头 (用户报"有时点一首歌从一半播起, 怀疑存了每首的进度"):
    并没有按曲存进度 —— 冷启动恢复在 preload=none 的 audio 上写
    currentTime 是"待生效进度", Safari 会把它漏到之后点开的歌上。
    loadTrack 换源后显式归零兜底; 冷启动续听 (playerRestore) 不走
    loadTrack, 特性照旧。"""
    static = Path(__file__).parent.parent / "app" / "music" / "static"
    player = (static / "music-player.js").read_text(encoding="utf-8")
    html = (static / "music.html").read_text(encoding="utf-8")
    load_track = player[player.index("function loadTrack"):
                        player.index("function prefetchNextTrack")]
    assert "audio.currentTime = 0;" in load_track  # 点播归零, 待生效进度不外漏
    assert 'preload="none"' in html          # 恢复态不拉元数据 (待生效进度的温床)
    restore = player[player.index("function playerRestore"):
                     player.index("function renderPlayerChrome")]
    assert "if (saved.time) audio.currentTime = saved.time;" in restore  # 续听保留


def test_music_volume_ui_removed():
    """音量条全平台撤除 (用户点名"音量条去掉吧"): iOS 的 audio.volume
    写了也白写, 1.5.0 的 WebAudio 增益又拖不动还脱开音量键 —— 桌面也
    不留了, 音量统一设备自己的键。回归: 旧的音量代码不许再爬回来。"""
    static = Path(__file__).parent.parent / "app" / "music" / "static"
    html = (static / "music.html").read_text(encoding="utf-8")
    player = (static / "music-player.js").read_text(encoding="utf-8")
    for gone in ["AudioContext", "createGain", "createMediaElementSource",
                 "ensureVolumeRouting", "loadSavedVolume", "nativeVolumeWorks",
                 "applyVolume", "music-volume", "volume-off", "fp-volume"]:
        assert gone not in player, f"音量残留: {gone}"
        assert gone not in html, f"音量残留 (html): {gone}"


def test_music_lyrics_mark_row_badge():
    """词标 ❝: 行右侧图标簇的一员 (下载标前面), 17×17 与下载标同大、
    同 26px 高度框里垂直居中 —— 两个图标同一水平线, 不再像小上标;
    颜色同一档, 行右侧图标簇没有色差 (用户点名)。"""
    static = Path(__file__).parent.parent / "app" / "music" / "static"
    html = (static / "music.html").read_text(encoding="utf-8")
    js = (static / "music.js").read_text(encoding="utf-8")
    common = (static / "music-common.js").read_text(encoding="utf-8")
    assert 'width="17" height="17"' in common              # 与下载标同大
    assert ".t-lyric" in html and "height: 26px" in html   # 与 .t-dl 同框高
    # 同色: 词标和下载标都是 ink-2 (下载完的勾加深到 ink-1 是另一态)
    lyric_block = html[html.index(".t-lyric {"):]
    assert "color: var(--ink-2)" in lyric_block[:lyric_block.index("}")]
    dl_block = html[html.index(".t-dl {"):]
    assert "color: var(--ink-2)" in dl_block[:dl_block.index("}")]
    # 挪出 .t-title: 行级元素, 排在下载标前面 (❝ 在前, 下载标在它后面)
    assert '${track.lyrics_available ? `<i class="t-lyric">' in js
    t_title_pos = js.index('<span class="t-title">')
    lyric_pos = js.index('<i class="t-lyric">${ICON_LYRICS}')
    dl_pos = js.index('<span class="t-dl${downloads.isDownloaded')
    assert t_title_pos < lyric_pos < dl_pos, "词标应排在标题之后、下载标之前"


def test_music_scan_polling_wiring():
    """增量扫描接线: 页面 30 秒问一次状态; 在扫出进度条, 收尾动过库
    (changed) 才静默刷新, 手动触发的才出提示, 重复一轮不再响应。"""
    static = Path(__file__).parent.parent / "app" / "music" / "static"
    js = (static / "music.js").read_text(encoding="utf-8")
    assert "SCAN_POLL_INTERVAL_MS = 30000" in js
    assert "function checkScanStatus" in js and "function digestScanSettled" in js
    assert "lastScanSignature" in js          # finished_at+changed 签名去重
    assert "document.hidden" in js            # 后台页签不空转
    assert "userRescanPending" in js          # 手动扫完才有提示
    assert "!manual && !scan.changed" in js   # 后台扫没变化: 不打扰


def test_record_play_counts_and_dedups():
    """查询层: user+track 一行, 重播只加次数; 曲目不在库里不记。"""
    _seed_library()
    with session_factory()() as session:
        assert library_queries.record_play(session, "u-1", 1) is True
        assert library_queries.record_play(session, "u-1", 1) is True
        assert library_queries.record_play(session, "u-1", 999) is False
        stat = session.execute(select(PlayStat)).scalar_one()
        assert stat.play_count == 2
        assert [t.title for t in
                library_queries.recent_plays(session, "u-1")] == ["曲A"]
        assert library_queries.recent_plays(session, "别人") == []


def test_play_record_endpoints_per_user(auth, usersdb):
    """播放记录接口: 重播把曲子顶回最前, 账号之间互不可见, 没登录 401。"""
    _seed_library()
    anon = TestClient(m.app)
    assert anon.post("/music/api/plays",
                     json={"track_id": 1}).status_code == 401
    assert anon.get("/music/api/plays/recent").status_code == 401

    assert auth.post("/music/api/plays", json={"track_id": 1}).status_code == 200
    time.sleep(0.002)
    assert auth.post("/music/api/plays", json={"track_id": 2}).status_code == 200
    time.sleep(0.002)
    assert auth.post("/music/api/plays", json={"track_id": 1}).status_code == 200
    assert auth.post("/music/api/plays",
                     json={"track_id": 9999}).status_code == 404
    recent = auth.get("/music/api/plays/recent").json()["tracks"]
    assert [t["title"] for t in recent] == ["曲A", "曲B"]   # 最近那次排前
    assert recent[0]["album_title"] == "甲"

    # 另一个账号: 各记各的, 看不见管理员的记录
    account_store.create_user(usersdb, "试听乙", "password123")
    yi = TestClient(m.app)
    assert yi.post("/api/login",
                   json={"user": "试听乙", "password": "password123"}
                   ).status_code == 200
    assert yi.get("/music/api/plays/recent").json()["tracks"] == []
    assert yi.post("/music/api/plays", json={"track_id": 3}).status_code == 200
    assert [t["title"] for t in
            yi.get("/music/api/plays/recent").json()["tracks"]] == ["Hello"]
    assert [t["title"] for t in
            auth.get("/music/api/plays/recent").json()["tracks"]] == ["曲A", "曲B"]


def test_startup_chain_scans_and_playlists_alive(auth, tmp_path):
    """启动链 = 补数 → 首扫 (无同步步骤); 播放列表接口照常, 重启列表不丢。"""
    service.stop_service()
    root = tmp_path / "startup-library"
    _make_library(root)
    database_url = f"sqlite:///{tmp_path / 'boot.db'}"
    service.start_service(database_url, root, scan_immediately=True)
    _wait_scan_done(auth)
    assert auth.get("/music/api/playlists").json()["playlists"] == []

    service.stop_service()
    service.start_service(database_url, root, scan_immediately=True)
    _wait_scan_done(auth)
    assert auth.get("/music/api/playlists").json()["playlists"] == []
    stats = auth.get("/music/api/stats").json()
    assert stats["track_count"] > 0

def test_reinit_scans_even_if_old_thread_lingers(auth, tmp_path, monkeypatch):
    """换代重装配: 上一代扫描线程还没退场, 新实例的首扫也照起。

    旧版 trigger_scan 拿全局线程句柄的 is_alive 挡触发 —— 旧线程只是
    迟几毫秒收尾, 就把新扫描器永远卡在 idle (启动链测试偶发 phase=idle)。"""
    gate = threading.Event()
    real_run = service._run_scan

    def slow_run(current, after_backfill):
        if current is old:
            gate.wait(timeout=10)                      # 上一代卡在半路不退场
        real_run(current, after_backfill)

    monkeypatch.setattr(service, "_run_scan", slow_run)
    service.stop_service()
    root = tmp_path / "lingering-library"
    _make_library(root)
    service.start_service(f"sqlite:///{tmp_path / 'lingering.db'}", root,
                          scan_immediately=False)
    old = service.scanner()
    assert service.trigger_scan(after_backfill=True)   # 上一代扫描进行中
    # 旧线程卡着: 换库重装配, 新实例首扫必须照起, 不能被旧线程挡成 idle
    service.start_service(f"sqlite:///{tmp_path / 'fresh.db'}", root,
                          scan_immediately=True)
    _wait_scan_done(auth)
    assert auth.get("/music/api/status").json()["track_count"] == 4
    gate.set()                                         # 放旧线程收尾


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
    # 等扫描真正开始再等收尾 (线程刚起时 running 还没置位, 不能只看它)
    while service.scanner().status().phase == "idle" \
            and time.monotonic() < deadline:
        time.sleep(0.02)
    while service.scanner().status().running and time.monotonic() < deadline:
        time.sleep(0.02)
    assert service.scanner().status().phase == "done"
    current = service.scanner()
    with current._scan_lock:                      # noqa: SLF001 顶住锁再跑 → 让位
        service._run_scan(current, False)         # noqa: SLF001 不抛即过


def test_media_edge_cases(auth, tmp_path):
    """媒体边界: DSF 的 APIC 封面抽得出 / 封面缓存命中 / 海报缺失 / 源文件被删。"""
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
    # DSF 的封面走 ID3 APIC, 一样抽得出 (1.4.1 起不止 FLAC)
    assert auth.get(
        f"/music/media/albums/{albums['DSD专辑']}/artwork"
    ).content == PICTURE_BYTES
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

    # 作词/作曲 (全屏播放页来源行): 带标签的读得出来, 没标签的空串
    qu_a = next(track for track in tracks if track["title"] == "曲A")
    got_credits = auth.get(f"/music/api/tracks/{qu_a['track_id']}/credits").json()
    assert got_credits == {"lyricist": "词人甲", "composer": "曲人乙"}
    assert auth.get(f"/music/api/tracks/{qu_b['track_id']}/credits").json() \
        == {"lyricist": "", "composer": ""}

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
    assert auth.get("/music/api/tracks/99999/credits").status_code == 404
    response = auth.post("/music/api/logout")     # 登出清 cookie, 放最后
    assert response.status_code == 200 and response.json() == {"ok": True}


# ------------------------------------------------------------ 自动重扫
# (设置/歌词 API/蜂窝流量/自定义封面的用例在 test_music_settings.py
#  和 test_music_covers.py; 这里留共享的曲库小助手)
# 封面用 PNG 魔数够了 (服务端只认魔数不解码), 字节即所传即所得
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"p" * 32


def _write_plain_track(root: Path, relative_path: str, title: str,
                       mtime: float = 1000.0) -> None:
    """放一首无歌词无封面的 FLAC (设置/自动重扫用例的最小曲库)。"""
    _write_audio(root, relative_path,
                 {"TITLE": title, "ARTIST": "A乐队", "ALBUMARTIST": "A乐队",
                  "ALBUM": title + "的专辑", "DATE": "2001"}, mtime=mtime)


def test_auto_rescan_picks_up_new_albums(auth, tmp_path, monkeypatch):
    """自动增量重扫: 到点起一轮, 新放进曲库的专辑不用手动按扫描。"""
    root = tmp_path / "music-library"
    _write_plain_track(root, "A乐队/2001 甲 [aaaa1111]/01 曲A.flac", "曲A")
    assert auth.post("/music/api/rescan").json() == {"started": True}
    _wait_scan_done(auth)
    assert auth.get("/music/api/status").json()["track_count"] == 1

    monkeypatch.setattr(service, "_AUTO_RESCAN_SECONDS", 0.2)
    service._start_auto_rescan()                # noqa: SLF001 短间隔看门线程
    _write_plain_track(root, "B乐队/2002 乙 [bbbb2222]/01 曲B.flac", "曲B")
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if auth.get("/music/api/status").json()["track_count"] == 2:
            break
        time.sleep(0.1)
    assert auth.get("/music/api/status").json()["track_count"] == 2
