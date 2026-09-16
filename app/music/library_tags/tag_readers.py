"""音频标签的 mutagen 读取底座: 逻辑标签名 → vorbis/ID3/MP4 三路取值。

逻辑标签 → (vorbis/ape 键, ID3 帧, MP4 键)。
FLAC/OGG/APE 是字典键 (大小写不敏感), mp3/dsf 是 ID3 帧, m4a 是 \xa9 开头的键。
"""
from pathlib import Path

from mutagen import File as load_audio_file, FileType, MutagenError

from ..schemas import TagFields

_TAG_SOURCES: dict[str, tuple[tuple[str, ...], tuple[str, ...], str | None]] = {
    "title":          (("title",), ("TIT2",), "©nam"),
    "artist":         (("artist", "artists"), ("TPE1",), "©ART"),
    "album":          (("album",), ("TALB",), "©alb"),
    "albumartist":    (("albumartist",), ("TPE2",), "aART"),
    "albumartistsort": (("albumartistsort",), ("TSO2",), None),
    "artistsort":     (("artistsort",), ("TSOP",), None),
    "tracknumber":    (("tracknumber",), ("TRCK",), "trkn"),
    "discnumber":    (("discnumber",), ("TPOS",), "disk"),
    "date":           (("originaldate", "originalyear", "date", "year"),
                       ("TDOR", "TDRC", "TYER"), "©day"),
    "script":         (("script",), ("TXXX:SCRIPT",), None),
    "lyrics":         (("lyrics", "unsyncedlyrics"), ("USLT",), "©lyr"),
    "lyricist":       (("lyricist",), ("TEXT",), None),
    "composer":       (("composer",), ("TCOM",), "©wrt"),
}


def _first_text(value: object) -> str:
    """标签值 → 文本: 列表取第一个非空, MP4 的 trkn 元组取第 0 位。"""
    items = value if isinstance(value, list) else [value]
    for item in items:
        if isinstance(item, tuple) and item:
            item = item[0]
        if item is None:                 # 缺的标签不能变成 "None"
            continue
        text = str(item).strip()
        if text:
            return text
    return ""


def _read_tag(tags: object, name: str) -> str:
    """按逻辑名读标签 (vorbis 键 → ID3 帧 → MP4 键, 先到先得)。"""
    if tags is None:
        return ""
    vorbis_keys, id3_frames, mp4_key = _TAG_SOURCES[name]
    if hasattr(tags, "get"):
        for key in vorbis_keys:
            text = _first_text(tags.get(key))
            if text:
                return text
    getall = getattr(tags, "getall", None)
    if getall is not None:
        for frame_name in id3_frames:
            for frame in getall(frame_name):
                text = _first_text(getattr(frame, "text", None))
                if text:
                    return text
    if mp4_key is not None and hasattr(tags, "get"):
        try:
            return _first_text(tags.get(mp4_key))
        except ValueError:
            return ""      # vorbis 字典对非 ASCII 键抛 ValueError (m4a 键)
    return ""


def _number_prefix(value: str) -> int:
    """"10" / "3/12" → 10 / 3 (取 / 前面的整数)。"""
    head = value.split("/")[0].strip()
    return int(head) if head.isdigit() else 0


def _year_from_date(value: str) -> int:
    """"2015-07-29" → 2015 (前四位不是年份就当 0)。"""
    head = value[:4]
    return int(head) if head.isdigit() else 0


def _has_embedded_artwork(audio: object) -> bool:
    """内嵌封面探测 (flac 有 pictures; mp3/dsf 走 APIC; m4a 走 covr; ape 走 Cover Art 键)。"""
    if getattr(audio, "pictures", None):
        return True
    tags = getattr(audio, "tags", None)
    if tags is None:
        return False
    if hasattr(tags, "getall") and tags.getall("APIC"):    # ID3 (mp3 / dsf)
        return True
    if hasattr(tags, "get"):
        try:
            if tags.get("covr") or tags.get("\xa9covr"):    # MP4
                return True
        except ValueError:               # vorbis 字典拒绝非 ASCII 键
            pass
        if any(str(key).startswith("Cover Art")
               for key in getattr(tags, "keys", lambda: ())()):   # APE
            return True
    return False


def _read_tag_fields(audio: FileType) -> TagFields:
    """音频对象的标签/时长/封面一次读全 (read_track_metadata 只管兜底与截断)。"""
    tags = getattr(audio, "tags", None)
    return TagFields(
        title=_read_tag(tags, "title"),
        artist=_read_tag(tags, "artist"),
        album_title=_read_tag(tags, "album"),
        album_artist=_read_tag(tags, "albumartist"),
        album_artist_sort=(_read_tag(tags, "albumartistsort")
                           or _read_tag(tags, "artistsort")),
        date_text=_read_tag(tags, "date"),
        script=_read_tag(tags, "script"),
        track_number=_number_prefix(_read_tag(tags, "tracknumber")),
        disc_number=_number_prefix(_read_tag(tags, "discnumber")) or 1,
        embedded_lyrics=_read_tag(tags, "lyrics"),
        duration_seconds=float(getattr(audio.info, "length", 0.0) or 0.0),
        has_artwork=_has_embedded_artwork(audio),
    )


def read_track_credits(audio_path: Path) -> tuple[str, str]:
    """作词/作曲 标签 (全屏播放页底部来源行; 读不出给空串, 不抛)。

    只有部分歌带这些标签, 前端拿不到就退专辑名, 所以这里不上索引。"""
    try:
        audio = load_audio_file(audio_path)
    except MutagenError:
        return "", ""
    if audio is None:
        return "", ""
    tags = audio.tags
    return _read_tag(tags, "lyricist"), _read_tag(tags, "composer")
