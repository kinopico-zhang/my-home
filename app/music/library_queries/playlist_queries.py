"""播放列表查询: 清单与详情 (有序曲目; 写操作在 library_playlists)。"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..library_database import Album, Playlist, PlaylistItem, Track
from ..schemas import PlaylistBrief, PlaylistPage, PlaylistPageList
from .browse_queries import track_brief


def list_playlists(session: Session) -> PlaylistPageList:
    """播放列表清单 (按同步顺序, 不分页 —— 就十几个)。"""
    playlists = [PlaylistBrief(
        playlist_id=playlist.id, name=playlist.name,
        track_count=playlist.track_count,
        duration_seconds=playlist.duration_seconds,
        is_local=playlist.is_local,
        cover_version=playlist.cover_version)
        for playlist in session.execute(
            select(Playlist).order_by(Playlist.position, Playlist.id)).scalars()]
    return PlaylistPageList(playlists=playlists)


def playlist_page(session: Session, playlist_id: int) -> PlaylistPage | None:
    """播放列表详情: 卡片 + 成员曲目 (按列表内顺序)。"""
    playlist = session.get(Playlist, playlist_id)
    if playlist is None:
        return None
    tracks = [track_brief(track, album_title, artist_id)
              for track, album_title, artist_id in session.execute(
                  select(Track, Album.title, Album.artist_id)
                  .join(PlaylistItem, PlaylistItem.track_id == Track.id)
                  .join(Album, Track.album_id == Album.id)
                  .where(PlaylistItem.playlist_id == playlist_id)
                  .order_by(PlaylistItem.position, PlaylistItem.id))]
    return PlaylistPage(
        playlist=PlaylistBrief(
            playlist_id=playlist.id, name=playlist.name,
            track_count=playlist.track_count,
            duration_seconds=playlist.duration_seconds,
            is_local=playlist.is_local,
            cover_version=playlist.cover_version),
        tracks=tracks)
