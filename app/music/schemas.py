"""My Music 的接口模型 (扫描结果 + API 应答, 全部 pydantic, 不裸传 dict)。"""
from datetime import datetime

from pydantic import BaseModel, Field


# ---------------------------------------------------------------- 扫描

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


class ScanSummary(BaseModel):
    """一轮扫描的收尾统计。"""

    tracks_scanned: int = 0            # 重读了标签的
    tracks_skipped: int = 0            # mtime/size 没变直接跳过的
    tracks_removed: int = 0            # 磁盘上没了的
    artist_count: int = 0
    album_count: int = 0
    elapsed_seconds: float = 0.0


# ---------------------------------------------------------------- 浏览

class MusicStatusResponse(BaseModel):
    """/api/status 的应答: 扫描进度 + 库规模。"""

    scan: ScanStatus
    artist_count: int = 0
    album_count: int = 0
    track_count: int = 0


class RescanResponse(BaseModel):
    """POST /api/rescan 的应答 (已在扫就 409, 不在这里返回)。"""

    started: bool = True


class AlbumCard(BaseModel):
    """专辑卡片 (列表/网格用, 不带曲目)。"""

    album_id: int
    title: str
    artist_id: int           # 艺人名跳转用 (专辑页 hero)
    artist_name: str
    year: int
    track_count: int
    duration_seconds: float
    added_at: float
    has_artwork: bool


class TrackBrief(BaseModel):
    """曲目一行 (专辑页/歌曲列表/搜索)。"""

    track_id: int
    title: str
    artist: str
    album_id: int
    album_title: str
    track_number: int
    disc_number: int
    duration_seconds: float
    file_format: str
    playable: bool
    lyrics_available: bool
    language: str                      # 语种分组名 (中文/日文/英文/韩文/俄文/其他)


class AlbumPage(BaseModel):
    """专辑详情: 卡片 + 曲目。"""

    album: AlbumCard
    tracks: list[TrackBrief]


class ArtistBrief(BaseModel):
    """艺人卡片 (列表用)。"""

    artist_id: int
    name: str
    album_count: int
    track_count: int
    has_poster: bool


class ArtistPage(BaseModel):
    """艺人详情: 卡片 + 专辑。"""

    artist: ArtistBrief
    albums: list[AlbumCard]


class AlbumPageList(BaseModel):
    """专辑分页列表。"""

    albums: list[AlbumCard]
    total_count: int
    offset: int
    limit: int


class TrackPageList(BaseModel):
    """曲目分页列表 (歌曲视图 48k 首, 必须分页)。"""

    tracks: list[TrackBrief]
    total_count: int
    offset: int
    limit: int


class ArtistPageList(BaseModel):
    """艺人分页列表。"""

    artists: list[ArtistBrief]
    total_count: int
    offset: int
    limit: int


class FormatCount(BaseModel):
    """一种音频格式的曲目数 (playable=False 浏览器播不了, 前端置灰)。"""

    format: str = ""              # flac / mp3 / tak …
    count: int = 0
    playable: bool = False


class LibraryStats(BaseModel):
    """统计页: 库规模 + 各格式曲目数。"""

    artist_count: int = 0
    album_count: int = 0
    track_count: int = 0
    total_duration_seconds: float = 0.0
    formats: list[FormatCount] = []


# ---------------------------------------------------------------- 搜索

class LyricHit(BaseModel):
    """歌词命中的片段: 哪首歌的哪一行 (不含时间轴)。"""

    track: TrackBrief
    line_text: str = Field(default="")


class SearchResult(BaseModel):
    """一次搜索的四个板块 (关键词同时命中多板块)。"""

    query: str
    language: str = "全部"
    tracks: list[TrackBrief] = Field(default_factory=list)
    albums: list[AlbumCard] = Field(default_factory=list)
    artists: list[ArtistBrief] = Field(default_factory=list)
    lyric_hits: list[LyricHit] = Field(default_factory=list)


class LyricsResponse(BaseModel):
    """单曲歌词原文 (前端解析时间轴)。"""

    track_id: int
    lyrics: str
    lyrics_synced: bool
