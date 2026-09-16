"""扫描域的接口模型: 扫描器的工作单元 + 进度/汇总。"""
from datetime import datetime

from pydantic import BaseModel


class ScannedTrack(BaseModel):
    """一个音频文件读出来的元数据 (扫描器的工作单元)。"""

    relative_path: str                 # 相对曲库根, 索引唯一键
    file_size: int = 0
    file_mtime: float = 0.0
    file_format: str = ""              # flac / mp3 / tak …
    title: str = ""
    artist: str = ""                   # 这一首的演唱者
    album_title: str = ""
    album_artist: str = ""             # 归并艺人 (albumartist 标签优先)
    album_artist_sort: str = ""        # artistsort 标签 (艺人排序)
    year: int = 0
    track_number: int = 0
    disc_number: int = 1
    duration_seconds: float = 0.0
    script: str = ""                   # Latn / Jpan / Hant …
    lyrics: str = ""                   # lrc 原文或纯文本
    lyrics_synced: bool = False        # 有 [mm:ss.xx] 时间轴
    has_artwork: bool = False          # 内嵌封面


class TagFields(BaseModel):
    """音频标签读出的原始字段 (缺标签 = 空值, 文件名/目录名兜底在后面)。"""

    title: str = ""
    artist: str = ""
    album_title: str = ""
    album_artist: str = ""
    album_artist_sort: str = ""
    date_text: str = ""
    script: str = ""
    track_number: int = 0
    disc_number: int = 1
    duration_seconds: float = 0.0
    embedded_lyrics: str = ""
    has_artwork: bool = False


class ScanStatus(BaseModel):
    """扫描进度 (前端轮询; 不扫描时也能答上次结果)。"""

    running: bool = False
    phase: str = "idle"                # idle/walk/reading/commit/done/error
    files_done: int = 0
    files_total: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str = ""
    changed: bool = False              # 上一轮扫有没有动库 (前端决定要不要刷新)


class ScanSummary(BaseModel):
    """一轮扫描的收尾统计。"""

    tracks_scanned: int = 0            # 重读了标签的
    tracks_skipped: int = 0            # mtime/size 没变直接跳过的
    tracks_removed: int = 0            # 磁盘上没了的
    artist_count: int = 0
    album_count: int = 0
    elapsed_seconds: float = 0.0
