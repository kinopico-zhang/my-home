"""分享链接: 一首歌 / 一个播放列表 24 小时免登录可看可听。

uuid4 hex 即凭证 —— 不查账号, 发给谁谁就能打开 (这正是分享的意义);
过期即废 (创建时顺手清掉全库的过期行, 量小不值得后台任务)。
公开面 (页面/数据/流/封面) 全部先过 token 校验, 每个路由只放行
"这份分享里确实有的东西" —— 拿着 A 的链接听不到 B 的歌。
"""
import time
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .library_database import Album, Playlist, PlaylistItem, ShareLink, Track
from .library_playlists import playlist_brief
from .library_queries import track_brief
from .schemas import ShareCreated, SharePageData

SHARE_TTL_SECONDS = 24 * 3600        # 有效期一天 (用户点名)


@dataclass(frozen=True)
class ShareScope:
    """公开路由 (流/封面) 的门禁底账: 这份链接能碰到哪些 id。"""

    kind: str                          # "track" | "playlist"
    track_ids: frozenset[int]          # 能播的曲目
    album_ids: frozenset[int]          # 能取的专辑封面 (这些曲目的专辑)
    playlist_id: int                   # 能取的列表封面 (单曲分享 = 0)


def create_share(session: Session, kind: str, target_id: int,
                 created_by: str) -> ShareCreated:
    """开一条分享 (track / playlist); 目标不在库里 KeyError → 404。

    过期行顺手清 (免得靠定时任务)。"""
    if kind == "track":
        if session.get(Track, target_id) is None:
            raise KeyError(target_id)
    elif kind == "playlist":
        if session.get(Playlist, target_id) is None:
            raise KeyError(target_id)
    else:
        raise ValueError(f"不认识的分享类型: {kind}")
    now = time.time()
    session.execute(delete(ShareLink).where(
        ShareLink.created_at < now - SHARE_TTL_SECONDS))
    link = ShareLink(token=uuid.uuid4().hex, kind=kind, target_id=target_id,
                     created_by=created_by, created_at=now)
    session.add(link)
    session.commit()
    return ShareCreated(token=link.token, expires_at=now + SHARE_TTL_SECONDS)


def _live_share(session: Session, token: str) -> ShareLink | None:
    """token → 没过期的行 (过期/不存在顺手删行并返回 None)。"""
    link = session.get(ShareLink, token)
    if link is None:
        return None
    if link.created_at + SHARE_TTL_SECONDS <= time.time():
        session.delete(link)
        session.commit()
        return None
    return link


def _shared_tracks(session: Session, link: ShareLink) -> list[Track]:
    """这份分享里的曲目 (列表按列表内顺序; 单曲就一首)。"""
    if link.kind == "track":
        track = session.get(Track, link.target_id)
        return [track] if track is not None else []
    return list(session.execute(
        select(Track).join(PlaylistItem, PlaylistItem.track_id == Track.id)
        .where(PlaylistItem.playlist_id == link.target_id)
        .order_by(PlaylistItem.position, PlaylistItem.id)).scalars())


def share_scope(session: Session, token: str) -> ShareScope | None:
    """公开路由的门禁: token → 能碰的 id 集合 (链接废了 None)。"""
    link = _live_share(session, token)
    if link is None:
        return None
    tracks = _shared_tracks(session, link)
    return ShareScope(
        kind=link.kind,
        track_ids=frozenset(track.id for track in tracks),
        album_ids=frozenset(track.album_id for track in tracks),
        playlist_id=link.target_id if link.kind == "playlist" else 0)


def share_page_data(session: Session, token: str) -> SharePageData | None:
    """分享页数据 (title/subtitle/曲目清单 + 列表卡片); 链接废了 None。"""
    link = _live_share(session, token)
    if link is None:
        return None
    tracks = _shared_tracks(session, link)
    albums = {album.id: album for album in session.execute(
        select(Album).where(Album.id.in_(
            {track.album_id for track in tracks}))).scalars()}
    briefs = [track_brief(track, albums[track.album_id].title,
                          albums[track.album_id].artist_id)
              for track in tracks if track.album_id in albums]
    if not briefs:
        return None                          # 目标被删空了: 当作链接失效
    if link.kind == "playlist":
        playlist = session.get(Playlist, link.target_id)
        if playlist is None:
            return None
        minutes = int(sum(track.duration_seconds for track in briefs) // 60)
        return SharePageData(
            kind="playlist", title=playlist.name,
            subtitle=f"{len(briefs)} 首 · {minutes} 分钟",
            expires_at=link.created_at + SHARE_TTL_SECONDS,
            tracks=briefs,
            playlist=playlist_brief(playlist))
    return SharePageData(
        kind="track", title=tracks[0].title, subtitle=tracks[0].artist,
        expires_at=link.created_at + SHARE_TTL_SECONDS, tracks=briefs[:1])
