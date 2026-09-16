"""单个音频文件 → ScannedTrack: 标签读出后的兜底与截断。

标签缺失时的兜底: 标题用文件名 (剥掉 01 / 1-01 这类音轨前缀), 专辑用目录名
(剥掉年份前缀和刮削器的 [hex] 尾巴), 艺人用目录名。歌词优先同名 .lrc
(同步歌词), 其次内嵌 lyrics 标签。只读, 不写任何标签。
"""
import re
from pathlib import Path

from mutagen import File as load_audio_file

from ..library_database import AUDIO_EXTENSION_FORMATS
from ..library_languages import detect_script
from ..schemas import ScannedTrack, TagFields
from .tag_readers import _read_tag_fields, _year_from_date

# 刮削器的目录命名: "2015 25 [2b4c1e9c]" → 标题 "25"
_YEAR_PREFIX_PATTERN = re.compile(r"^\d{4}\s+")
_SCRAPER_SUFFIX_PATTERN = re.compile(r"\s*\[[0-9a-f]{8}\]$")
# 文件名音轨前缀: "01 Hello" / "1-01 Get my way!" → 标题
_TRACK_PREFIX_PATTERN = re.compile(r"^\d{1,2}-?\d{0,3}[\s._-]+")
# lrc 的时间轴行: [01:53.54]Get my way!
_LRC_TIMECODE_PATTERN = re.compile(r"^\[\d{1,3}:\d{2}([.:]\d{1,3})?]")


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


def _read_sidecar_lyrics(audio_path: Path) -> str:
    """同名 .lrc (utf-8, 坏编码也不炸)。"""
    lyric_path = audio_path.with_suffix(".lrc")
    try:
        return lyric_path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


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
