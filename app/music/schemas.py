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
    changed: bool = False              # 上一轮扫有没有动库 (前端决定要不要刷新)


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
    artist_id: int = 0       # 专辑的艺人 (长按菜单「进入艺人主页」用; 0 = 没有)
    track_number: int
    disc_number: int
    duration_seconds: float
    file_format: str
    playable: bool
    lyrics_available: bool
    has_artwork: bool = False    # 这一首文件里自己嵌了封面 (播放列表行用)
    mtime: float = 0.0           # 文件 mtime (单曲封面 URL 的 ?v= 版本号)
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


# ---------------------------------------------------------------- 播放列表

class PlaylistBrief(BaseModel):
    """播放列表一行 (资料库的播放列表段)。"""

    playlist_id: int
    name: str
    track_count: int
    duration_seconds: float
    is_local: bool = False   # 应用内列表 (2026-09-15 起全量如此, 历史同步列表也已转正)
    cover_version: int = 0   # 自定义封面版本 (0 = 没传过)


class PlaylistCreateRequest(BaseModel):
    """POST /api/playlists 的请求体 (本地新建列表)。"""

    name: str


class PlaylistTrackRequest(BaseModel):
    """POST /api/playlists/{id}/tracks 的请求体 (往本地列表里加一首)。"""

    track_id: int


class PlaylistPageList(BaseModel):
    """播放列表清单 (不分页 —— 十几个)。"""

    playlists: list[PlaylistBrief]


class PlaylistPage(BaseModel):
    """播放列表详情: 卡片 + 有序曲目。"""

    playlist: PlaylistBrief
    tracks: list[TrackBrief]



class PlayRecordRequest(BaseModel):
    """POST /api/plays 的请求体 (播一次报一次)。"""

    track_id: int


class RecentPlaysResponse(BaseModel):
    """GET /api/plays/recent 的应答 (本人的最近播放, 每首只一行)。"""

    tracks: list[TrackBrief] = Field(default_factory=list)


# ---------------------------------------------------------------- 歌词

class LyricsResponse(BaseModel):
    """单曲歌词原文 (前端解析时间轴)。"""

    track_id: int
    lyrics: str
    lyrics_synced: bool


# ---------------------------------------------------------------- 设置 / 流量

class MusicSettingsState(BaseModel):
    """设置页状态: 各字段现值 + 默认值参照 (空 = 用默认)。"""

    music_directory: str = ""
    music_directory_default: str = ""
    lyrics_api_enabled: bool = True
    lyrics_api_base: str = ""
    lyrics_api_default: str = ""
    cellular_months: list["CellularMonth"] = Field(default_factory=list)


class MusicSettingsUpdate(BaseModel):
    """POST /api/settings 的请求体 (缺字段 = 不动那项)。"""

    music_directory: str | None = None
    lyrics_api_enabled: bool | None = None
    lyrics_api_base: str | None = None


class CellularMonth(BaseModel):
    """一个月的蜂窝流量账。"""

    month: str               # "2026-09"
    bytes: int = 0


class CellularUsageReport(BaseModel):
    """POST /api/cellular-usage 的请求体 (一次上报的字节量)。"""

    bytes: int = Field(ge=0, le=1_073_741_824)   # 单次上限 1 GB, 灌水也灌不爆
