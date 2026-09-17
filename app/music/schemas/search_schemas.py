"""搜索与播放记录域的接口模型: 搜索四板块 + 记播/最近播放/歌词/来源。"""
from pydantic import BaseModel, Field

from .browse_schemas import AlbumCard, ArtistBrief, TrackBrief


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
    # 各板块命中总数 (1.8.6): 列表按容量截断, 总数不截 —— 板块头/页签
    # 报总数, 截断时列表尾注明 (修「艺人 64 专辑, 专辑板块只有 20 张」)
    track_total: int = 0
    album_total: int = 0
    artist_total: int = 0
    lyric_total: int = 0


class PlayRecordRequest(BaseModel):
    """POST /api/plays 的请求体 (播一次报一次)。"""

    track_id: int


class RecentTrackBrief(TrackBrief):
    """最近播放行 (1.8.1): 曲目信息 + 这首播过几次 (页面上替掉时长)。"""

    play_count: int = 0


class RecentPlaysResponse(BaseModel):
    """GET /api/plays/recent 的应答 (本人的最近播放, 每首只一行)。"""

    tracks: list[RecentTrackBrief] = Field(default_factory=list)


class LyricsResponse(BaseModel):
    """单曲歌词原文 (前端解析时间轴)。"""

    track_id: int
    lyrics: str
    lyrics_synced: bool


class TrackCredits(BaseModel):
    """单曲 作词/作曲 标签 (全屏播放页来源行, 按需现读, 缺标签 = 空串)。"""

    lyricist: str = ""
    composer: str = ""
