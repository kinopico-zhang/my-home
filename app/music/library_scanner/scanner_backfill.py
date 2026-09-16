"""老库一次性补数 (启动首扫前跑): 入库时刻与检索键缺的行回填。"""
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, sessionmaker

from ..library_database import Album, Track
from ..library_search_keys import search_keys
from .scanner_index_writer import refresh_album_artist_search_keys


def backfill_legacy_rows(
        database_sessions: sessionmaker[Session]) -> tuple[int, int]:
    """老库一次性补数: 曲目入库时刻缺的按文件 mtime 回填 (最接近的入库代理),
    检索键为空的行按现名重算。返回 (补时刻行数, 补键行数); 新库无事可做时 (0, 0)。
    mtime 为 0 的行补不了 (实际不会发生, 扫描必写), 保持 0 = 未知, 排序当最老。"""
    added_at_count = 0
    search_keys_count = 0
    with database_sessions() as session:
        rows = session.execute(
            select(Track, Album.title)
            .join(Album, Track.album_id == Album.id)
            .where(or_(and_(Track.added_at == 0.0, Track.file_mtime > 0.0),
                       Track.search_keys == ""))).all()
        for track, album_title in rows:
            if track.added_at == 0.0 and track.file_mtime > 0.0:
                track.added_at = track.file_mtime
                added_at_count += 1
            if not track.search_keys:
                track.search_keys = search_keys(
                    track.title, track.artist, album_title)
                search_keys_count += 1
        session.commit()
        refresh_album_artist_search_keys(session)     # 专辑/艺人键整表
        session.commit()
    return added_at_count, search_keys_count
