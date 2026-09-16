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


class PlayRecordRequest(BaseModel):
    """POST /api/plays 的请求体 (播一次报一次)。"""

    track_id: int


class RecentPlaysResponse(BaseModel):
    """GET /api/plays/recent 的应答 (本人的最近播放, 每首只一行)。"""

    tracks: list[TrackBrief] = Field(default_factory=list)


class LyricsResponse(BaseModel):
    """单曲歌词原文 (前端解析时间轴)。"""

    track_id: int
    lyrics: str
    lyrics_synced: bool


class TrackCredits(BaseModel):
    """单曲 作词/作曲 标签 (全屏播放页来源行, 按需现读, 缺标签 = 空串)。"""

    lyricist: str = ""
    composer: str = ""
