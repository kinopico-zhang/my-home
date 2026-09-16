"""分享链接域的接口模型: 开链接请求/应答 + 分享页数据。"""
from pydantic import BaseModel, Field

from .browse_schemas import TrackBrief
from .playlist_schemas import PlaylistBrief


class ShareCreateRequest(BaseModel):
    """POST /api/shares 的请求体 (分享一首歌 / 一个播放列表)。"""

    kind: str = Field(pattern="^(track|playlist)$")   # 分享什么
    id: int                                           # track_id / playlist_id


class ShareCreated(BaseModel):
    """开出来的分享 (前端拼 /music/share/{token} 发出去)。"""

    token: str
    expires_at: float          # epoch 秒 (创建 + 24h)


class SharePageData(BaseModel):
    """分享页的数据 (免登录接口): 页面照这个渲染 + 播放。"""

    kind: str                  # "track" | "playlist"
    title: str                 # 歌名 / 列表名
    subtitle: str              # 歌手 / "N 首 · 总时长"
    expires_at: float
    tracks: list[TrackBrief] = Field(default_factory=list)
    playlist: PlaylistBrief | None = None   # 列表分享才有 (封面版本号用)
