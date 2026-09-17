"""My Music 标签读取测试: vorbis/ID3/MP4/APE 各形状 + 封面抽取。"""
from typing import Callable


from app.music.library_tags import (extract_album_artwork,
                                    read_track_metadata)
from tests.music_audio_seed import (PICTURE_BYTES, _flac_bytes,
                                    _write_audio, _write_dsf_audio)


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
