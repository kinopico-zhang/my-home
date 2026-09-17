"""My Music 的接口模型 (扫描结果 + API 应答, 全部 pydantic, 不裸传 dict)。

按资源域分家: 扫描 / 浏览 / 搜索与播放记录 / 播放列表 / 分享 / 设置与流量;
这里聚合对外名面 (调用方统一 from ..schemas import …, 不感知内部分层)。
"""
from .browse_schemas import (AlbumCard, AlbumPage, AlbumPageList, ArtistBrief,
                             ArtistPage, ArtistPageList, FormatCount,
                             LibraryStats, MusicStatusResponse, RescanResponse,
                             TrackBrief, TrackPageList)
from .playlist_schemas import (PlaylistBrief, PlaylistCreateRequest,
                               PlaylistPage, PlaylistPageList,
                               PlaylistTrackRequest)
from .scan_schemas import (ScanStatus, ScanSummary, ScannedTrack, TagFields)
from .search_schemas import (LyricHit, LyricsResponse, PlayRecordRequest,
                             RecentPlaysResponse, RecentTrackBrief,
                             SearchResult, TrackCredits)
from .settings_schemas import (CellularMonth, CellularUsageReport,
                               MusicSettingsState, MusicSettingsUpdate)
from .share_schemas import ShareCreated, ShareCreateRequest, SharePageData

__all__ = [
    "AlbumCard", "AlbumPage", "AlbumPageList", "ArtistBrief", "ArtistPage",
    "ArtistPageList", "CellularMonth", "CellularUsageReport", "FormatCount",
    "LibraryStats", "LyricHit", "LyricsResponse", "MusicSettingsState",
    "MusicSettingsUpdate", "MusicStatusResponse", "PlayRecordRequest",
    "PlaylistBrief", "PlaylistCreateRequest", "PlaylistPage",
    "PlaylistPageList", "PlaylistTrackRequest", "RecentPlaysResponse",
    "RecentTrackBrief", "RescanResponse", "ScanStatus", "ScanSummary",
    "ScannedTrack", "SearchResult", "ShareCreated", "ShareCreateRequest",
    "SharePageData", "TagFields", "TrackBrief", "TrackCredits", "TrackPageList",
]
