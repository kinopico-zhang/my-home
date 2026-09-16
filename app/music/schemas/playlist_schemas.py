"""播放列表域的接口模型: 行模型 + 建列表/加歌请求 + 清单/详情页。"""
from pydantic import BaseModel

from .browse_schemas import TrackBrief


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
