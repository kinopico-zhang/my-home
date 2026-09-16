"""扫描结果落库: 艺人/专辑/曲目行的建改删 + 汇总重算 (索引写入层)。

全部是纯函数 (会话由调用方给); 艺人/专辑按目录归并, 曲目按路径幂等,
分批提交避开 SQLite 事务过大与绑定参数上限。
"""
import time

from sqlalchemy import delete, exists, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from ..library_database import Album, Artist, Track
from ..library_search_keys import search_keys
from ..library_tags import album_title_from_directory
from ..schemas import ScannedTrack

_COMMIT_BATCH_SIZE = 500       # 曲目入库分批提交, 免得事务太大
_DELETE_BATCH_SIZE = 500       # 删除分批, 免得单条 SQL 绑定参数超限


def known_file_signatures(session: Session) -> dict[str, tuple[int, float]]:
    """索引里已有的 路径 → (大小, mtime)。"""
    rows = session.execute(select(Track.file_path, Track.file_size,
                                  Track.file_mtime)).all()
    return {path: (size, mtime) for path, size, mtime in rows}


def artist_directory_of(relative_path: str) -> str:
    """曲目相对路径 → 艺人目录 (一级目录名)。"""
    return relative_path.split("/")[0]


def album_directory_of(relative_path: str) -> str:
    """曲目相对路径 → 专辑目录 (艺人/专辑 两级; 散在艺人目录的归艺人目录)。"""
    parts = relative_path.split("/")
    return "/".join(parts[:2]) if len(parts) > 2 else parts[0]


def store_scanned_tracks(database_sessions: sessionmaker[Session],
                         scanned: list[ScannedTrack]) -> None:
    """入库: 艺人/专辑按目录归并, 曲目按路径幂等 (分批提交)。"""
    with database_sessions() as session:
        artist_ids = ensure_artists(session, scanned)
        album_ids = ensure_albums(session, scanned, artist_ids)
        existing = existing_track_ids(session, scanned)
        for index, track in enumerate(scanned, start=1):
            upsert_track(session, track, album_ids, existing)
            if index % _COMMIT_BATCH_SIZE == 0:
                session.commit()
        session.commit()


def ensure_artists(session: Session,
                   scanned: list[ScannedTrack]) -> dict[str, int]:
    """艺人行 (按目录归并, 名字/排序名首个非空者胜); 返回 目录 → id。"""
    artists_by_directory = {
        artist.directory: artist for artist in
        session.execute(select(Artist)).scalars()}
    for track in scanned:
        directory = artist_directory_of(track.relative_path)
        artist = artists_by_directory.get(directory)
        if artist is None:
            artist = Artist(directory=directory)
            session.add(artist)
            artists_by_directory[directory] = artist
        if not artist.name:
            artist.name = track.album_artist
        if not artist.sort_name and track.album_artist_sort:
            artist.sort_name = track.album_artist_sort
    session.flush()
    return {directory: artist.id
            for directory, artist in artists_by_directory.items()}


def ensure_albums(session: Session, scanned: list[ScannedTrack],
                  artist_ids: dict[str, int]) -> dict[str, int]:
    """专辑行 (按目录归并, 标题/年份首个非空者胜); 返回 目录 → id。"""
    albums_by_directory = {
        album.directory: album for album in
        session.execute(select(Album)).scalars()}
    for track in scanned:
        directory = album_directory_of(track.relative_path)
        album = albums_by_directory.get(directory)
        if album is None:
            album = Album(directory=directory,
                          artist_id=artist_ids[directory.split("/")[0]])
            session.add(album)
            albums_by_directory[directory] = album
        if not album.title:
            album.title = track.album_title
        if not album.year:
            album.year = track.year
    session.flush()
    return {directory: album.id
            for directory, album in albums_by_directory.items()}


def existing_track_ids(session: Session,
                       scanned: list[ScannedTrack]) -> dict[str, int]:
    """这批扫描里已入库的曲目 路径 → id (重扫改, 新增插)。

    全表取回再交集, 不用 IN (...) —— 首扫就是四万多路径, 会顶到
    SQLite 绑定参数上限。"""
    scanned_paths = {track.relative_path for track in scanned}
    stored = {path: track_id for track_id, path in
              session.execute(select(Track.id, Track.file_path))}
    return {path: stored[path] for path in scanned_paths
            if path in stored}


def upsert_track(session: Session, track: ScannedTrack,
                 album_ids: dict[str, int],
                 stored_track_ids: dict[str, int]) -> None:
    """曲目行 (路径幂等: 有则改, 无则插)。"""
    album_id = album_ids[album_directory_of(track.relative_path)]
    values = {
        "album_id": album_id,
        "title": track.title, "artist": track.artist,
        "track_number": track.track_number,
        "disc_number": track.disc_number,
        "duration_seconds": track.duration_seconds,
        "file_size": track.file_size, "file_mtime": track.file_mtime,
        "file_format": track.file_format, "script": track.script,
        "lyrics": track.lyrics, "lyrics_synced": track.lyrics_synced,
        "has_artwork": track.has_artwork,
        "search_keys": search_keys(
            track.title, track.artist, track.album_title,
            track.album_artist)}
    track_id = stored_track_ids.get(track.relative_path)
    if track_id is None:
        session.add(Track(file_path=track.relative_path, **values,
                          added_at=time.time()))   # 入库时刻只记一次
    else:
        session.execute(update(Track).where(    # added_at 不进更新集
            Track.id == track_id).values(**values))


def remove_vanished_tracks(database_sessions: sessionmaker[Session],
                           live_paths: set[str]) -> int:
    """磁盘上没了的曲目行删掉 (分批, 避开绑定参数上限); 返回删了几行。"""
    with database_sessions() as session:
        stored_paths = {row[0] for row in
                        session.execute(select(Track.file_path))}
        vanished = sorted(stored_paths - live_paths)
        for start in range(0, len(vanished), _DELETE_BATCH_SIZE):
            session.execute(delete(Track).where(Track.file_path.in_(
                vanished[start:start + _DELETE_BATCH_SIZE])))
        session.commit()
    return len(vanished)


def finalize_library(session: Session, posters: dict[str, str]) -> int:
    """扫尾: 记海报 → 清空行 → 重算专辑汇总 → 目录名兜底; 返回艺人数。"""
    for artist in session.execute(select(Artist)).scalars():
        artist.poster_file = posters.get(artist.directory, "")
    session.execute(delete(Album).where(
        ~exists(select(Track.id).where(Track.album_id == Album.id))))
    session.execute(delete(Artist).where(
        ~exists(select(Album.id).where(Album.artist_id == Artist.id))))
    refresh_album_aggregates(session)
    for album in session.execute(select(Album)).scalars():
        if not album.title:
            album.title = album_title_from_directory(
                album.directory.split("/")[-1])
    for artist in session.execute(select(Artist)).scalars():
        if not artist.name:
            artist.name = artist.directory
    refresh_album_artist_search_keys(session)
    return session.scalar(select(func.count()).select_from(Artist)) or 0


def refresh_album_artist_search_keys(session: Session) -> None:
    """专辑/艺人的检索键整表重算 (曲目键在 upsert 时逐条算过了)。"""
    artist_names = {artist.id: artist.name or artist.directory
                    for artist in session.execute(select(Artist)).scalars()}
    for album in session.execute(select(Album)).scalars():
        album.search_keys = search_keys(
            album.title, artist_names.get(album.artist_id, ""))
    for artist in session.execute(select(Artist)).scalars():
        artist.search_keys = search_keys(
            artist.name, artist.sort_name, artist.directory)


def refresh_album_aggregates(session: Session) -> None:
    """一条 SQL 重算专辑汇总: 曲目数 / 总时长 / 最近添加 / 有无封面。"""
    track_counts = select(func.count()).where(
        Track.album_id == Album.id).scalar_subquery()
    session.execute(update(Album).values(
        track_count=track_counts,
        duration_seconds=select(func.coalesce(
            func.sum(Track.duration_seconds), 0.0)).where(
            Track.album_id == Album.id).scalar_subquery(),
        added_at=select(func.coalesce(
            func.max(Track.added_at), 0.0)).where(
            Track.album_id == Album.id).scalar_subquery(),
        has_artwork=select(func.coalesce(
            func.max(Track.has_artwork), False)).where(
            Track.album_id == Album.id).scalar_subquery()))
