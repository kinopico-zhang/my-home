"""浏览域的接口模型: 状态/统计应答 + 专辑/艺人/曲目的行模型与分页。"""
from pydantic import BaseModel

from .scan_schemas import ScanStatus


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
