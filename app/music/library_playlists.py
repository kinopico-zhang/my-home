"""Plex 播放列表同步: 只读拉取 Plex 库 → 灌进本地索引库 (全量替换)。

服务不依赖 Plex —— 同步只是借 Plex 的库读一次播放列表定义, 拉完即可断;
Plex 以后下掉, 已同步的播放列表照常能用, 再点同步会得到干净报错。

Plex 侧结构 (2026-09-14 本机实测): 播放列表 = metadata_items.metadata_type=15,
成员在 play_queue_generators (playlist_id + metadata_item_id + order 千分步),
曲目文件路径经 metadata_items → media_items → media_parts.file。Plex 存的是
真实卷路径 (/share/CACHEDEV2_DATA/Media/Music/…), 剥掉 "Media/Music/" 前缀
即本库的曲目相对路径。
"""
import os
import sqlite3
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from .library_database import Playlist, PlaylistItem, Track
from .schemas import PlaylistBrief, PlaylistSyncResponse

DEFAULT_PLEX_LIBRARY_DATABASE = (
    os.environ.get("MYTESLA_PLEX_LIBRARY_DB")
    or "/share/CACHEDEV1_DATA/.qpkg/PlexMediaServer/Library/"
       "Plex Media Server/Plug-in Support/Databases/"
       "com.plexapp.plugins.library.db")

_MUSIC_ROOT_MARKER = "Media/Music/"

# 一条 SQL 拉全: 列表 + 成员序 + 曲目文件 (曲目行可能挂多个媒体版本, 去重在侧)
_PLEX_PLAYLIST_QUERY = """
SELECT p.id, p.title, g."order", mp.file
FROM metadata_items p
JOIN play_queue_generators g ON g.playlist_id = p.id
LEFT JOIN media_items mi ON mi.metadata_item_id = g.metadata_item_id
LEFT JOIN media_parts mp ON mp.media_item_id = mi.id
WHERE p.metadata_type = 15
ORDER BY p.title, g."order"
"""


class PlexPlaylist(BaseModel):
    """从 Plex 库读出的一个播放列表 (成员是本库口径的相对路径)。"""

    plex_playlist_id: int
    name: str
    member_paths: list[str]


def _relative_library_path(plex_file_path: str) -> str | None:
    """Plex 的绝对路径 → 本库相对路径; 曲库外的文件返回 None。"""
    marker = plex_file_path.find(_MUSIC_ROOT_MARKER)
    if marker < 0:
        return None
    return plex_file_path[marker + len(_MUSIC_ROOT_MARKER):]


def read_plex_playlists(plex_database_path: Path) -> list[PlexPlaylist]:
    """只读连 Plex 库拉播放列表 (空列表不算; 库不在抛 FileNotFoundError)。"""
    if not plex_database_path.is_file():
        raise FileNotFoundError(f"找不到 Plex 数据库: {plex_database_path}")
    connection = sqlite3.connect(f"file:{plex_database_path}?mode=ro", uri=True)
    try:
        rows = connection.execute(_PLEX_PLAYLIST_QUERY).fetchall()
    finally:
        connection.close()
    playlists: dict[int, PlexPlaylist] = {}
    for plex_id, title, _plex_order, file_path in rows:
        playlist = playlists.get(plex_id)
        if playlist is None:
            playlist = PlexPlaylist(plex_playlist_id=plex_id, name=title,
                                    member_paths=[])
            playlists[plex_id] = playlist
        if file_path is None:
            continue          # 成员指向已删对象 (Plex 侧就没有文件了)
        relative = _relative_library_path(file_path)
        if relative:
            playlist.member_paths.append(relative)
    return sorted(playlists.values(), key=lambda item: item.name)


def sync_playlists(session: Session,
                   plex_playlists: list[PlexPlaylist]) -> PlaylistSyncResponse:
    """全量替换 Plex 来源的播放列表两表; 应用内自建的 (is_local) 不动,
    对不上本库的曲目跳过并计数。

    同一曲目在一表里出现两次 (Plex 允许) 保留两次 —— 播放列表本就是有序可重复的。"""
    result = PlaylistSyncResponse()
    track_ids = {path: track_id for track_id, path in
                 session.execute(select(Track.id, Track.file_path))}
    # 只清 Plex 来源的; 本地自建列表 (position=0 排最前) 原样保留
    plex_ids = list(session.execute(
        select(Playlist.id).where(Playlist.is_local.is_(False))).scalars())
    if plex_ids:
        session.execute(
            delete(PlaylistItem).where(PlaylistItem.playlist_id.in_(plex_ids)))
        session.execute(delete(Playlist).where(Playlist.id.in_(plex_ids)))
    for position, plex_playlist in enumerate(plex_playlists, start=1):
        member_track_ids: list[tuple[int, int]] = []
        for member_position, member_path in enumerate(plex_playlist.member_paths):
            track_id = track_ids.get(member_path)
            if track_id is None:
                result.tracks_skipped += 1
                continue
            member_track_ids.append((member_position, track_id))
        if not member_track_ids:
            continue          # 整表对不上 (整个列表的文件都搬走了) → 不留空壳
        playlist = Playlist(name=plex_playlist.name, position=position,
                            plex_playlist_id=plex_playlist.plex_playlist_id,
                            track_count=len(member_track_ids))
        session.add(playlist)
        session.flush()       # 拿 playlist.id
        session.add_all([PlaylistItem(playlist_id=playlist.id,
                                      track_id=track_id, position=member_position)
                         for member_position, track_id in member_track_ids])
        result.playlists_synced += 1
        result.tracks_synced += len(member_track_ids)
    session.commit()
    _refresh_playlist_aggregates(session)
    return result


def _refresh_playlist_aggregates(session: Session) -> None:
    """列表总时长重算 (成员曲目时长求和, 与专辑汇总同一套相关子查询写法)。"""
    session.execute(update(Playlist).values(
        duration_seconds=select(func.coalesce(
            func.sum(Track.duration_seconds), 0.0)).where(
            PlaylistItem.playlist_id == Playlist.id,
            PlaylistItem.track_id == Track.id).scalar_subquery()))
    session.commit()


# ------------------------------------------------ 本地播放列表 (应用内自建)

def _playlist_brief(playlist: Playlist) -> PlaylistBrief:
    return PlaylistBrief(playlist_id=playlist.id, name=playlist.name,
                         track_count=playlist.track_count,
                         duration_seconds=playlist.duration_seconds,
                         is_local=playlist.is_local)


def create_local_playlist(session: Session, name: str) -> PlaylistBrief:
    """新建空的本地播放列表 (position=0: 在清单里排在 Plex 同步列表前面)。

    名字撞车 (不管是撞 Plex 的还是撞本地建的) 报 ValueError, 由路由层转 409。"""
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


def add_track_to_local_playlist(session: Session, playlist_id: int,
                                track_id: int) -> PlaylistBrief:
    """往本地列表末尾加一首 (可重复加; Plex 同步的列表拒绝改, 报 ValueError)。"""
    playlist = session.get(Playlist, playlist_id)
    if playlist is None:
        raise KeyError(playlist_id)
    if not playlist.is_local:
        raise ValueError("Plex 同步的播放列表以 Plex 为准, 不能在这里改")
    if session.get(Track, track_id) is None:
        raise KeyError(track_id)
    next_position = (session.scalar(select(func.max(PlaylistItem.position))
                                    .where(PlaylistItem.playlist_id
                                           == playlist_id)) or 0) + 1
    session.add(PlaylistItem(playlist_id=playlist_id, track_id=track_id,
                             position=next_position))
    playlist.track_count += 1
    session.commit()
    _refresh_playlist_aggregates(session)
    session.expire(playlist, ["track_count", "duration_seconds"])
    return _playlist_brief(playlist)   # 聚合 SQL 刚更新过, 定向失效取库里的新值


def delete_local_playlist(session: Session, playlist_id: int) -> None:
    """删掉本地列表 (连成员一起); Plex 同步的同样拒绝。"""
    playlist = session.get(Playlist, playlist_id)
    if playlist is None:
        raise KeyError(playlist_id)
    if not playlist.is_local:
        raise ValueError("Plex 同步的播放列表以 Plex 为准, 不能在这里删")
    session.execute(
        delete(PlaylistItem).where(PlaylistItem.playlist_id == playlist_id))
    session.delete(playlist)
    session.commit()
