"""播放列表: 应用内自建自管 (建 / 加歌 / 删 / 自定义封面)。

2026-09-15 起不再从 Plex 同步 (用户要求, 界面与接口同步全撤): 撤之前
同步过来的列表原地保留为普通列表, 与自建的没有区别 —— 都能加歌、能删。
自定义封面原图直存库文件旁的缓存目录 (playlist-{id}.jpg/png/webp),
库里只记版本号, 换图加一, URL 带 ?v={版本} 长缓存。
"""
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from .library_database import (Playlist, PlaylistItem, Track,
                               artwork_cache_directory)
from .library_media import playlist_cover_file
from .schemas import PlaylistBrief

_MAX_COVER_BYTES = 10 * 1024 * 1024      # 封面上限 10 MB (手机照片直传够用)


def _sniff_image_extension(data: bytes) -> str | None:
    """字节流魔数 → 扩展名 (认不出返回 None; 文件名/头都不算数, 只信内容)。"""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp"
    return None


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
    return playlist_brief(playlist)


def add_track_to_playlist(session: Session, playlist_id: int,
                          track_id: int) -> PlaylistBrief:
    """往列表末尾加一首; 已经在列表里的不再加 (同一首只留一份 ——
    重复行会让两行一起亮播放态、连播两遍, 2026-09-15 用户点名)。

    已在列表里报 ValueError, 由路由层转 409。"""
    playlist = session.get(Playlist, playlist_id)
    if playlist is None:
        raise KeyError(playlist_id)
    if session.get(Track, track_id) is None:
        raise KeyError(track_id)
    already = session.scalar(select(PlaylistItem.id).where(
        PlaylistItem.playlist_id == playlist_id,
        PlaylistItem.track_id == track_id))
    if already is not None:
        raise ValueError("这首歌已经在列表里了")
    next_position = (session.scalar(select(func.max(PlaylistItem.position))
                                    .where(PlaylistItem.playlist_id
                                           == playlist_id)) or 0) + 1
    session.add(PlaylistItem(playlist_id=playlist_id, track_id=track_id,
                             position=next_position, added_locally=True))
    playlist.track_count += 1
    session.commit()
    _refresh_playlist_aggregates(session)
    session.expire(playlist, ["track_count", "duration_seconds"])
    return playlist_brief(playlist)   # 聚合 SQL 刚更新过, 定向失效取库里的新值


def remove_track_from_playlist(session: Session, playlist_id: int,
                               track_id: int) -> PlaylistBrief:
    """从列表里移出一首 (左滑删除); 列表里没有这首 KeyError → 404。

    position 留洞不补 (查询按 ORDER BY position, 顺序不受影响)。"""
    playlist = session.get(Playlist, playlist_id)
    if playlist is None:
        raise KeyError(playlist_id)
    item = session.scalar(select(PlaylistItem).where(
        PlaylistItem.playlist_id == playlist_id,
        PlaylistItem.track_id == track_id))
    if item is None:
        raise KeyError(track_id)
    session.delete(item)
    session.commit()
    _refresh_playlist_aggregates(session)
    session.expire(playlist, ["track_count", "duration_seconds"])
    return playlist_brief(playlist)


def delete_playlist(session: Session, playlist_id: int) -> None:
    """删掉播放列表 (连成员和封面文件一起)。"""
    playlist = session.get(Playlist, playlist_id)
    if playlist is None:
        raise KeyError(playlist_id)
    session.execute(
        delete(PlaylistItem).where(PlaylistItem.playlist_id == playlist_id))
    session.delete(playlist)
    _unlink_cover(playlist_id)
    session.commit()


def set_playlist_cover(session: Session, playlist_id: int, data: bytes,
                       content_type: str) -> PlaylistBrief:
    """换自定义封面 (内容按魔数认类型, 原图直存; 版本号 +1)。

    列表不在库 KeyError; 不是图片/太大/类型不对 ValueError (路由层转 404/400)。"""
    playlist = session.get(Playlist, playlist_id)
    if playlist is None:
        raise KeyError(playlist_id)
    if not (content_type or "").lower().startswith("image/"):
        raise ValueError("封面要传图片文件 (JPG / PNG / WebP)")
    if len(data) > _MAX_COVER_BYTES:
        raise ValueError("封面太大了 (上限 10 MB)")
    extension = _sniff_image_extension(data)
    if extension is None:
        raise ValueError("认不出这张图 (只收 JPG / PNG / WebP)")
    path = artwork_cache_directory() / f"playlist-{playlist_id}{extension}"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = playlist_cover_file(playlist_id)
    if existing is not None and existing != path:
        existing.unlink()          # 旧扩展名的文件别留着 (png 换成 jpg 之类)
    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_bytes(data)
    temporary_path.replace(path)
    playlist.cover_version = max(1, playlist.cover_version + 1)
    session.commit()
    return playlist_brief(playlist)


def clear_playlist_cover(session: Session, playlist_id: int) -> PlaylistBrief:
    """撤掉自定义封面 (回渐变音符块); 文件删不干净也不挡 (版本已归零)。"""
    playlist = session.get(Playlist, playlist_id)
    if playlist is None:
        raise KeyError(playlist_id)
    _unlink_cover(playlist_id)
    playlist.cover_version = 0
    session.commit()
    return playlist_brief(playlist)


def _unlink_cover(playlist_id: int) -> None:
    """封面文件尽力删 (删不掉就算了, 版本号不再引用它)。"""
    cover = playlist_cover_file(playlist_id)
    if cover is not None:
        try:
            cover.unlink()
        except OSError:
            pass


def playlist_brief(playlist: Playlist) -> PlaylistBrief:
    """列表行/卡片的数据形状 (queries / shares 也用它, 别再手抄这份构造)。"""
    return PlaylistBrief(playlist_id=playlist.id, name=playlist.name,
                         track_count=playlist.track_count,
                         duration_seconds=playlist.duration_seconds,
                         is_local=playlist.is_local,
                         cover_version=playlist.cover_version)


def _refresh_playlist_aggregates(session: Session) -> None:
    """列表 计数/总时长 重算 (成员曲目聚合, 与专辑汇总同一套相关子查询写法)。"""
    session.execute(update(Playlist).values(
        track_count=select(func.count()).where(
            PlaylistItem.playlist_id == Playlist.id).scalar_subquery(),
        duration_seconds=select(func.coalesce(
            func.sum(Track.duration_seconds), 0.0)).where(
            PlaylistItem.playlist_id == Playlist.id,
            PlaylistItem.track_id == Track.id).scalar_subquery()))
    session.commit()
