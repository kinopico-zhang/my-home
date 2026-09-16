"""播放记录查询: 记一次播放 + 本人的最近播放。"""
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..library_database import Album, PlayStat, Track
from ..schemas import TrackBrief
from .browse_queries import track_brief


def record_play(session: Session, user_uuid: str, track_id: int) -> bool:
    """记一次播放 (user+track 一行, 重播只推进时刻/次数); 曲目不在库里 False。"""
    if session.get(Track, track_id) is None:
        return False
    stat = session.execute(
        select(PlayStat).where(PlayStat.user_uuid == user_uuid,
                               PlayStat.track_id == track_id)
    ).scalar_one_or_none()
    now = time.time()
    if stat is None:
        session.add(PlayStat(user_uuid=user_uuid, track_id=track_id,
                             last_played_at=now))
    else:
        stat.last_played_at = now
        stat.play_count += 1
    session.commit()
    return True


def recent_plays(session: Session, user_uuid: str, limit: int = 30
                 ) -> list[TrackBrief]:
    """最近播放 (本人的, 时刻倒序; 同一首只一行, 排的是最近那次)。"""
    rows = session.execute(
        select(Track, Album.title, Album.artist_id)
        .join(PlayStat, PlayStat.track_id == Track.id)
        .join(Album, Track.album_id == Album.id)
        .where(PlayStat.user_uuid == user_uuid)
        .order_by(PlayStat.last_played_at.desc(), PlayStat.track_id)
        .limit(limit))
    return [track_brief(track, album_title, artist_id)
            for track, album_title, artist_id in rows]
