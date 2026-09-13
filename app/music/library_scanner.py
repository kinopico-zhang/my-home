"""曲库扫描器: 走目录 → 并发读标签 → 增量写索引 (曲库本体始终只读)。

增量规则: 文件的 size/mtime 与索引一致就跳过 (只 stat 不读标签); 磁盘上没
了的行为删除; 专辑/艺人的汇总 (曲目数/总时长/最近添加/有无封面) 每轮扫完
用一条 SQL 重算。扫描在后台线程跑, 进度对象线程安全, 重复触发会被拒绝。
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, exists, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from .library_database import AUDIO_EXTENSION_FORMATS, Album, Artist, Track
from .library_tags import album_title_from_directory, read_track_metadata
from .schemas import ScanStatus, ScanSummary, ScannedTrack

_POSTER_FILE_NAMES = frozenset({"poster.jpg", "poster.png", "poster.webp",
                                "poster.jpeg"})
_COMMIT_BATCH_SIZE = 500       # 曲目入库分批提交, 免得事务太大
_DELETE_BATCH_SIZE = 500       # 删除分批, 免得单条 SQL 绑定参数超限


class LibraryScanner:
    """一轮扫描 = walk + 读标签 + 落库; 同一实例反复调用即增量重扫。"""

    def __init__(self, music_directory: Path,
                 database_sessions: sessionmaker[Session],
                 worker_count: int = 6) -> None:
        self._music_directory = music_directory
        self._database_sessions = database_sessions
        self._worker_count = worker_count
        self._status = ScanStatus(phase="idle")
        self._status_lock = threading.Lock()
        self._scan_lock = threading.Lock()

    def status(self) -> ScanStatus:
        """当前/上次扫描的进度 (拷贝出去, 不暴露内部对象)。"""
        with self._status_lock:
            return self._status.model_copy()

    def scan(self) -> ScanSummary:
        """同步执行一轮 (调用方放后台线程); 结束返回汇总统计。"""
        if not self._scan_lock.acquire(blocking=False):
            raise RuntimeError("扫描正在进行中")
        try:
            return self._run_scan()
        finally:
            self._scan_lock.release()

    def _run_scan(self) -> ScanSummary:
        started = time.monotonic()
        self._set_status(running=True, phase="walk", files_done=0,
                         files_total=0, started_at=datetime.now(),
                         finished_at=None, error="")
        try:
            if not self._music_directory.is_dir():
                # os.walk 对不存在的根不报错, 会把整个索引当 "消失" 清空
                raise FileNotFoundError(
                    f"曲库目录不存在: {self._music_directory}")
            candidates, posters = self._collect_audio_files()
            summary = self._scan_changed_files(candidates, posters)
        except Exception as exc:            # pylint: disable=broad-except
            self._set_status(phase="error", running=False, error=str(exc),
                             finished_at=datetime.now())
            raise
        summary.elapsed_seconds = time.monotonic() - started
        self._set_status(phase="done", running=False,
                         finished_at=datetime.now())
        return summary

    def _set_status(self, **fields: object) -> None:
        """更新进度 (线程安全; ScanStatus 的字段类型兜住非法值)。"""
        with self._status_lock:
            self._status = self._status.model_copy(update=fields)

    # -------------------------------------------------------------- walk

    def _collect_audio_files(
            self) -> tuple[list[tuple[str, int, float]], dict[str, str]]:
        """走一遍曲库 → (音频文件 [(相对路径, 大小, mtime)], 艺人目录 → 海报文件名)。

        隐藏文件/目录 (.DS_Store 之类) 不进索引; 根下散文件没有艺人上下文, 不收。"""
        candidates: list[tuple[str, int, float]] = []
        posters: dict[str, str] = {}
        root = self._music_directory
        for directory, subdirectories, file_names in root.walk():
            subdirectories[:] = [name for name in subdirectories
                                 if not name.startswith(".")]
            relative_directory = directory.relative_to(root).as_posix()
            if relative_directory == ".":
                continue
            is_artist_level = "/" not in relative_directory
            for file_name in sorted(file_names):
                if file_name.startswith("."):
                    continue
                if is_artist_level and file_name.lower() in _POSTER_FILE_NAMES:
                    posters[relative_directory] = file_name
                if (directory / file_name).suffix.lower() \
                        not in AUDIO_EXTENSION_FORMATS:
                    continue
                try:
                    stat = (directory / file_name).stat()
                except OSError:
                    continue        # 扫描瞬间被删/坏链接: 跳过
                candidates.append(
                    (f"{relative_directory}/{file_name}",
                     stat.st_size, stat.st_mtime))
        return candidates, posters

    # -------------------------------------------------- 读标签 + 落库

    def _scan_changed_files(
            self, candidates: list[tuple[str, int, float]],
            posters: dict[str, str]) -> ScanSummary:
        """跳过没变的, 并发读变了/新增的, 落库 + 清理消失的 + 重算汇总。"""
        with self._database_sessions() as session:
            known = self._known_file_signatures(session)
        pending = [candidate for candidate in candidates
                   if known.get(candidate[0]) != (candidate[1], candidate[2])]
        summary = ScanSummary(
            tracks_scanned=len(pending),
            tracks_skipped=len(candidates) - len(pending))
        self._set_status(phase="reading", files_total=len(pending),
                         files_done=0)
        scanned: list[ScannedTrack] = []
        with ThreadPoolExecutor(max_workers=self._worker_count) as pool:
            for index, result in enumerate(pool.map(self._read_one_file,
                                                    pending), start=1):
                if result is not None:
                    scanned.append(result)
                if index % 50 == 0:
                    self._set_status(files_done=index)
        self._set_status(files_done=len(pending), phase="commit")
        self._store_scanned_tracks(scanned)
        summary.tracks_removed = self._remove_vanished_tracks(
            {candidate[0] for candidate in candidates})
        with self._database_sessions() as session:
            summary.artist_count = self._finalize_library(session, posters)
            summary.album_count = session.scalar(
                select(func.count()).select_from(Album)) or 0
            session.commit()
        return summary

    def _read_one_file(
            self, candidate: tuple[str, int, float]) -> ScannedTrack | None:
        """读一个文件 (线程池里跑; 读不动返回 None, 不拖垮整轮)。"""
        relative_path, file_size, file_mtime = candidate
        try:
            return read_track_metadata(
                self._music_directory / relative_path, relative_path,
                file_size, file_mtime)
        except Exception:           # pylint: disable=broad-except
            return None

    @staticmethod
    def _known_file_signatures(session: Session) -> dict[str, tuple[int, float]]:
        """索引里已有的 路径 → (大小, mtime)。"""
        rows = session.execute(select(Track.file_path, Track.file_size,
                                      Track.file_mtime)).all()
        return {path: (size, mtime) for path, size, mtime in rows}

    def _store_scanned_tracks(self, scanned: list[ScannedTrack]) -> None:
        """入库: 艺人/专辑按目录归并, 曲目按路径幂等 (分批提交)。"""
        with self._database_sessions() as session:
            artist_ids = self._ensure_artists(session, scanned)
            album_ids = self._ensure_albums(session, scanned, artist_ids)
            existing_track_ids = self._existing_track_ids(session, scanned)
            for index, track in enumerate(scanned, start=1):
                self._upsert_track(session, track, album_ids,
                                   existing_track_ids)
                if index % _COMMIT_BATCH_SIZE == 0:
                    session.commit()
            session.commit()

    @staticmethod
    def _artist_directory_of(relative_path: str) -> str:
        """曲目相对路径 → 艺人目录 (一级目录名)。"""
        return relative_path.split("/")[0]

    @staticmethod
    def _album_directory_of(relative_path: str) -> str:
        """曲目相对路径 → 专辑目录 (艺人/专辑 两级; 散在艺人目录的归艺人目录)。"""
        parts = relative_path.split("/")
        return "/".join(parts[:2]) if len(parts) > 2 else parts[0]

    def _ensure_artists(self, session: Session,
                        scanned: list[ScannedTrack]) -> dict[str, int]:
        """艺人行 (按目录归并, 名字/排序名首个非空者胜); 返回 目录 → id。"""
        artists_by_directory = {
            artist.directory: artist for artist in
            session.execute(select(Artist)).scalars()}
        for track in scanned:
            directory = self._artist_directory_of(track.relative_path)
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

    def _ensure_albums(self, session: Session,
                       scanned: list[ScannedTrack],
                       artist_ids: dict[str, int]) -> dict[str, int]:
        """专辑行 (按目录归并, 标题/年份首个非空者胜); 返回 目录 → id。"""
        albums_by_directory = {
            album.directory: album for album in
            session.execute(select(Album)).scalars()}
        for track in scanned:
            directory = self._album_directory_of(track.relative_path)
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

    @staticmethod
    def _existing_track_ids(session: Session,
                            scanned: list[ScannedTrack]) -> dict[str, int]:
        """这批扫描里已入库的曲目 路径 → id (重扫改, 新增插)。

        全表取回再交集, 不用 IN (...) —— 首扫就是四万多路径, 会顶到
        SQLite 绑定参数上限。"""
        scanned_paths = {track.relative_path for track in scanned}
        stored = {path: track_id for track_id, path in
                  session.execute(select(Track.id, Track.file_path))}
        return {path: stored[path] for path in scanned_paths
                if path in stored}

    @staticmethod
    def _upsert_track(session: Session, track: ScannedTrack,
                      album_ids: dict[str, int],
                      existing_track_ids: dict[str, int]) -> None:
        """曲目行 (路径幂等: 有则改, 无则插)。"""
        album_id = album_ids[
            LibraryScanner._album_directory_of(track.relative_path)]
        values = dict(
            album_id=album_id,
            title=track.title, artist=track.artist,
            track_number=track.track_number,
            disc_number=track.disc_number,
            duration_seconds=track.duration_seconds,
            file_size=track.file_size, file_mtime=track.file_mtime,
            file_format=track.file_format, script=track.script,
            lyrics=track.lyrics, lyrics_synced=track.lyrics_synced,
            has_artwork=track.has_artwork)
        track_id = existing_track_ids.get(track.relative_path)
        if track_id is None:
            session.add(Track(file_path=track.relative_path, **values))
        else:
            session.execute(update(Track).where(
                Track.id == track_id).values(**values))

    def _remove_vanished_tracks(self, live_paths: set[str]) -> int:
        """磁盘上没了的曲目行删掉 (分批, 避开绑定参数上限); 返回删了几行。"""
        with self._database_sessions() as session:
            stored_paths = {row[0] for row in
                            session.execute(select(Track.file_path))}
            vanished = sorted(stored_paths - live_paths)
            for start in range(0, len(vanished), _DELETE_BATCH_SIZE):
                session.execute(delete(Track).where(Track.file_path.in_(
                    vanished[start:start + _DELETE_BATCH_SIZE])))
            session.commit()
        return len(vanished)

    @staticmethod
    def _finalize_library(session: Session,
                          posters: dict[str, str]) -> int:
        """扫尾: 记海报 → 清空行 → 重算专辑汇总 → 目录名兜底; 返回艺人数。"""
        for artist in session.execute(select(Artist)).scalars():
            artist.poster_file = posters.get(artist.directory, "")
        session.execute(delete(Album).where(
            ~exists(select(Track.id).where(Track.album_id == Album.id))))
        session.execute(delete(Artist).where(
            ~exists(select(Album.id).where(Album.artist_id == Artist.id))))
        LibraryScanner._refresh_album_aggregates(session)
        for album in session.execute(select(Album)).scalars():
            if not album.title:
                album.title = album_title_from_directory(
                    album.directory.split("/")[-1])
        for artist in session.execute(select(Artist)).scalars():
            if not artist.name:
                artist.name = artist.directory
        return session.scalar(select(func.count()).select_from(Artist)) or 0

    @staticmethod
    def _refresh_album_aggregates(session: Session) -> None:
        """一条 SQL 重算专辑汇总: 曲目数 / 总时长 / 最近添加 / 有无封面。"""
        track_counts = select(func.count()).where(
            Track.album_id == Album.id).scalar_subquery()
        session.execute(update(Album).values(
            track_count=track_counts,
            duration_seconds=select(func.coalesce(
                func.sum(Track.duration_seconds), 0.0)).where(
                Track.album_id == Album.id).scalar_subquery(),
            added_at=select(func.coalesce(
                func.max(Track.file_mtime), 0.0)).where(
                Track.album_id == Album.id).scalar_subquery(),
            has_artwork=select(func.coalesce(
                func.max(Track.has_artwork), False)).where(
                Track.album_id == Album.id).scalar_subquery()))
