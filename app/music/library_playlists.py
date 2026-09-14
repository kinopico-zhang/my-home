"""播放列表: 应用内自建自管 (建 / 加歌 / 删)。

2026-09-15 起不再从 Plex 同步 (用户要求, 界面与接口同步全撤): 撤之前
同步过来的列表原地保留为普通列表, 与自建的没有区别 —— 都能加歌、能删。
"""
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from .library_database import Playlist, PlaylistItem, Track
from .schemas import PlaylistBrief


def create_playlist(session: Session, name: str) -> PlaylistBrief:
    """新建空的播放列表 (position=0: 新建的排在已有列表前面)。

    名字撞车报 ValueError, 由路由层转 409。"""
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("播放列表的名字不能是空的")
    if session.scalar(select(Playlist).where(Playlist.name == cleaned)) is not None:
        raise ValueError("已经有叫这个名字的播放列表了")
    playlist = Playlist(name=cleaned, position=0, plex_playlist_id=0,
                        is_local=True)
    session.add(playlist)
    session.commit()
    return _playlist_brief(playlist)


def add_track_to_playlist(session: Session, playlist_id: int,
                          track_id: int) -> PlaylistBrief:
    """往列表末尾加一首 (可重复加; 长按曲目的「添加到播放列表」)。"""
    playlist = session.get(Playlist, playlist_id)
    if playlist is None:
        raise KeyError(playlist_id)
    if session.get(Track, track_id) is None:
        raise KeyError(track_id)
    next_position = (session.scalar(select(func.max(PlaylistItem.position))
                                    .where(PlaylistItem.playlist_id
                                           == playlist_id)) or 0) + 1
    session.add(PlaylistItem(playlist_id=playlist_id, track_id=track_id,
                             position=next_position, added_locally=True))
    playlist.track_count += 1
    session.commit()
    _refresh_playlist_aggregates(session)
    session.expire(playlist, ["track_count", "duration_seconds"])
    return _playlist_brief(playlist)   # 聚合 SQL 刚更新过, 定向失效取库里的新值


def delete_playlist(session: Session, playlist_id: int) -> None:
    """删掉播放列表 (连成员一起)。"""
    playlist = session.get(Playlist, playlist_id)
    if playlist is None:
        raise KeyError(playlist_id)
    session.execute(
        delete(PlaylistItem).where(PlaylistItem.playlist_id == playlist_id))
    session.delete(playlist)
    session.commit()


def _playlist_brief(playlist: Playlist) -> PlaylistBrief:
    return PlaylistBrief(playlist_id=playlist.id, name=playlist.name,
                         track_count=playlist.track_count,
                         duration_seconds=playlist.duration_seconds,
                         is_local=playlist.is_local)


def _refresh_playlist_aggregates(session: Session) -> None:
    """列表总时长重算 (成员曲目时长求和, 与专辑汇总同一套相关子查询写法)。"""
    session.execute(update(Playlist).values(
        duration_seconds=select(func.coalesce(
            func.sum(Track.duration_seconds), 0.0)).where(
            PlaylistItem.playlist_id == Playlist.id,
            PlaylistItem.track_id == Track.id).scalar_subquery()))
    session.commit()
