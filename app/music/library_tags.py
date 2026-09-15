"""单个音频文件的元数据读取 (mutagen) → ScannedTrack。

标签缺失时的兜底: 标题用文件名 (剥掉 01 / 1-01 这类音轨前缀), 专辑用目录名
(剥掉年份前缀和刮削器的 [hex] 尾巴), 艺人用目录名。歌词优先同名 .lrc
(同步歌词), 其次内嵌 lyrics 标签。只读, 不写任何标签。
"""
import re
from pathlib import Path

from mutagen import File as load_audio_file, FileType, MutagenError

from .library_database import AUDIO_EXTENSION_FORMATS
from .library_languages import detect_script
from .schemas import ScannedTrack, TagFields

# 刮削器的目录命名: "2015 25 [2b4c1e9c]" → 标题 "25"
_YEAR_PREFIX_PATTERN = re.compile(r"^\d{4}\s+")
_SCRAPER_SUFFIX_PATTERN = re.compile(r"\s*\[[0-9a-f]{8}\]$")
# 文件名音轨前缀: "01 Hello" / "1-01 Get my way!" → 标题
_TRACK_PREFIX_PATTERN = re.compile(r"^\d{1,2}-?\d{0,3}[\s._-]+")
# lrc 的时间轴行: [01:53.54]Get my way!
_LRC_TIMECODE_PATTERN = re.compile(r"^\[\d{1,3}:\d{2}([.:]\d{1,3})?]")
# 逻辑标签 → (vorbis/ape 键, ID3 帧, MP4 键)。
# FLAC/OGG/APE 是字典键 (大小写不敏感), mp3/dsf 是 ID3 帧, m4a 是 \xa9 开头的键。
_TAG_SOURCES: dict[str, tuple[tuple[str, ...], tuple[str, ...], str | None]] = {
    "title":          (("title",), ("TIT2",), "©nam"),
    "artist":         (("artist", "artists"), ("TPE1",), "©ART"),
    "album":          (("album",), ("TALB",), "©alb"),
    "albumartist":    (("albumartist",), ("TPE2",), "aART"),
    "albumartistsort": (("albumartistsort",), ("TSO2",), None),
    "artistsort":     (("artistsort",), ("TSOP",), None),
    "tracknumber":    (("tracknumber",), ("TRCK",), "trkn"),
    "discnumber":     (("discnumber",), ("TPOS",), "disk"),
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
_SUFFIX_REPLACEMENTS = {"_": " ", ".": " "}


def _number_prefix(value: str) -> int:
    """"10" / "3/12" → 10 / 3 (取 / 前面的整数)。"""
    head = value.split("/")[0].strip()
    return int(head) if head.isdigit() else 0


def _year_from_date(value: str) -> int:
    """"2015-07-29" → 2015 (前四位不是年份就当 0)。"""
    head = value[:4]
    return int(head) if head.isdigit() else 0


def title_from_filename(file_name: str) -> str:
    """文件名 → 歌名兜底 (剥音轨前缀和扩展名)。"""
    stem = Path(file_name).stem
    stem = _TRACK_PREFIX_PATTERN.sub("", stem, count=1)
    return stem.strip()


def album_title_from_directory(directory_name: str) -> str:
    """专辑目录名 → 标题兜底 (剥年份前缀和 [hex] 尾巴)。"""
    title = _YEAR_PREFIX_PATTERN.sub("", directory_name, count=1)
    title = _SCRAPER_SUFFIX_PATTERN.sub("", title)
    return title.strip()


def looks_like_synced_lyrics(text: str) -> bool:
    """有没有 lrc 时间轴 (决定前端按行滚动还是整页显示)。"""
    for line in text.splitlines():
        if _LRC_TIMECODE_PATTERN.match(line.strip()):
            return True
    return False


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


def _read_sidecar_lyrics(audio_path: Path) -> str:
    """同名 .lrc (utf-8, 坏编码也不炸)。"""
    lyric_path = audio_path.with_suffix(".lrc")
    try:
        return lyric_path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


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


def read_track_metadata(audio_path: Path, relative_path: str,
                        file_size: int, file_mtime: float) -> ScannedTrack | None:
    """读一个音频文件 → ScannedTrack (读不出来返回 None, 调用方跳过)。

    mutagen 不认识的格式 (tak) 也建条目: 目录/文件名兜底 + 时长 0,
    前端按格式置灰不能播。"""
    file_format = AUDIO_EXTENSION_FORMATS.get(audio_path.suffix.lower(), "")
    if not file_format:
        return None

    audio = load_audio_file(audio_path)
    fields = TagFields() if audio is None else _read_tag_fields(audio)

    parts = relative_path.split("/")
    artist_directory = parts[0]
    album_directory = parts[1] if len(parts) > 2 else artist_directory
    if not fields.title:
        fields.title = title_from_filename(audio_path.name)
    if not fields.album_title:
        fields.album_title = album_title_from_directory(album_directory)
    if not fields.album_artist:
        fields.album_artist = fields.artist or artist_directory
    if not fields.script:
        fields.script = detect_script(fields.title, fields.artist,
                                      fields.album_artist)

    lyrics = _read_sidecar_lyrics(audio_path)
    if not lyrics:
        lyrics = fields.embedded_lyrics.strip()

    return ScannedTrack(
        relative_path=relative_path,
        file_size=file_size,
        file_mtime=file_mtime,
        file_format=file_format,
        title=fields.title[:300],
        artist=fields.artist[:200] or fields.album_artist[:200],
        album_title=fields.album_title[:300],
        album_artist=fields.album_artist[:200],
        album_artist_sort=fields.album_artist_sort[:200],
        year=_year_from_date(fields.date_text),
        track_number=fields.track_number,
        disc_number=fields.disc_number,
        duration_seconds=fields.duration_seconds,
        script=fields.script,
        lyrics=lyrics[:20000],
        lyrics_synced=looks_like_synced_lyrics(lyrics),
        has_artwork=fields.has_artwork,
    )


def _read_tag_fields(audio: FileType) -> TagFields:
    """音频对象的标签/时长/封面一次读全 (read_track_metadata 只管兜底与截断)。"""
    tags = audio.tags
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


def extract_album_artwork(audio_path: Path) -> bytes | None:
    """抽内嵌封面字节: flac pictures / ID3 APIC (mp3, dsf) / MP4 covr /
    APE 的 Cover Art 键 (ape, tak)。

    各格式都先挑正面封面; 探测端 (_has_embedded_artwork) 认得出的路,
    这里都得能走通 —— 否则 has_artwork=1 却抽不出图, 前端裂一张 404。"""
    try:
        audio = load_audio_file(audio_path)
    except (OSError, MutagenError):
        return None        # 文件没了/打不开: 当作没有封面
    if audio is None:
        return None
    return (_flac_artwork(audio) or _id3_artwork(audio)
            or _tag_dict_artwork(audio))


def _flac_artwork(audio: object) -> bytes | None:
    """flac: pictures 列表, type 3 (front cover) 优先。"""
    pictures = getattr(audio, "pictures", None) or ()
    for picture in pictures:
        if picture.type == 3 and picture.data:
            return bytes(picture.data)
    for picture in pictures:
        if picture.data:
            return bytes(picture.data)
    return None


def _id3_artwork(audio: object) -> bytes | None:
    """ID3 (mp3 / dsf): APIC 帧, type 3 (正面) 优先。"""
    tags = getattr(audio, "tags", None)
    if tags is None or not hasattr(tags, "getall"):
        return None
    for frame in tags.getall("APIC"):
        if frame.type == 3 and frame.data:
            return bytes(frame.data)
    for frame in tags.getall("APIC"):
        if frame.data:
            return bytes(frame.data)
    return None


def _tag_dict_artwork(audio: object) -> bytes | None:
    """字典式标签: MP4 的 covr; APE (ape / tak) 的 Cover Art 键,
    键名带 Front 的优先, 值里的 "文件名\\0" 前缀剥掉。"""
    tags = getattr(audio, "tags", None)
    if tags is None or not hasattr(tags, "get"):
        return None
    try:
        covers = tags.get("covr") or ()               # MP4
    except ValueError:                # vorbis 字典拒绝非 ASCII 键
        covers = ()
    for cover in covers:
        if bytes(cover):
            return bytes(cover)
    cover_keys = [str(key) for key in getattr(tags, "keys", lambda: ())()
                  if str(key).startswith("Cover Art")]
    for key in ([k for k in cover_keys if "front" in k.lower()]
                or cover_keys):
        value = tags.get(key)
        if value is None:
            continue
        image = _strip_ape_cover_name(bytes(getattr(value, "value", value)))
        if image:
            return image
    return None


def _strip_ape_cover_name(raw: bytes) -> bytes | None:
    """APE 封面值 = "文件名\\0图像字节"; 也有不带文件名直接写图像的, 都兜住。

    不是图像开头又切不出图像的, 当没有封面 (None)。"""
    if _looks_like_image(raw):
        return raw
    name_end = raw.find(b"\x00")
    if name_end >= 0 and _looks_like_image(raw[name_end + 1:]):
        return raw[name_end + 1:]
    return None


def _looks_like_image(data: bytes) -> bool:
    """常见封面图的魔数 (JPEG/PNG/GIF/WebP), 挡住空串/截断/纯文本。"""
    return (data.startswith(b"\xff\xd8")           # JPEG
            or data.startswith(b"\x89PNG")         # PNG
            or data.startswith(b"GIF8")            # GIF
            or (data.startswith(b"RIFF") and b"WEBP" in data[:16]))  # WebP
