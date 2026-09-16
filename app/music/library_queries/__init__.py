"""曲库索引的查询层: SQL → pydantic 模型 (浏览 / 搜索 / 歌词 / 播放记录)。

路由层 (webapp/) 只做参数解析和鉴权, 数据组装都在这里。按资源域分家:
共用条件在 query_conditions, 专辑/艺人/曲目在 browse_queries, 播放列表在
playlist_queries, 歌词在 lyrics_queries, 播放记录在 play_history_queries,
搜索在 search_queries; 这里聚合对外名面 (调用方统一 library_queries.xxx,
不感知内部分层)。
"""
from .browse_queries import (album_card, album_page, artist_page,
                             library_stats, list_albums, list_artists,
                             list_tracks, track_brief)
from .lyrics_queries import credits_for_track, lyrics_for_track
from .play_history_queries import recent_plays, record_play
from .playlist_queries import list_playlists, playlist_page
from .search_queries import _matching_lyric_line, search_library

__all__ = [
    "_matching_lyric_line", "album_card", "album_page", "artist_page",
    "credits_for_track", "library_stats", "list_albums", "list_artists",
    "list_playlists", "list_tracks", "lyrics_for_track", "playlist_page",
    "recent_plays", "record_play", "search_library", "track_brief",
]
