"""曲库扫描器: 走目录 → 并发读标签 → 增量写索引 (曲库本体始终只读)。

增量规则: 文件的 size/mtime 与索引一致就跳过 (只 stat 不读标签); 磁盘上没
了的行为删除; 专辑/艺人的汇总每轮扫完在 scanner_index_writer 重算。扫描在
后台线程跑, 进度对象线程安全, 重复触发会被拒绝。
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from ..library_database import AUDIO_EXTENSION_FORMATS, Album
from ..library_tags import read_track_metadata
from ..schemas import ScanStatus, ScanSummary, ScannedTrack
from .scanner_index_writer import (finalize_library, known_file_signatures,
                                   remove_vanished_tracks,
                                   store_scanned_tracks)

_POSTER_FILE_NAMES = frozenset({"poster.jpg", "poster.png", "poster.webp",
                                "poster.jpeg"})


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
        # 非阻塞拿锁 (拿不到说明已有扫描在跑, 要立刻报错), 语义上用不了 with
        if not self._scan_lock.acquire(blocking=False):  # pylint: disable=consider-using-with
            raise RuntimeError("扫描正在进行中")
        try:
            return self._run_scan()
        finally:
            self._scan_lock.release()

    def _run_scan(self) -> ScanSummary:
        started = time.monotonic()
        self._set_status(running=True, phase="walk", files_done=0,
                         files_total=0, started_at=datetime.now(),
                         finished_at=None, error="", changed=False)
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
        # 上一轮有没有动库 (前端据此决定要不要刷新列表; 自动重扫没变就不打扰)
        self._set_status(phase="done", running=False,
                         finished_at=datetime.now(),
                         changed=bool(summary.tracks_scanned
                                      or summary.tracks_removed))
        return summary

    def _set_status(self, **fields: object) -> None:
        """更新进度 (线程安全; ScanStatus 的字段类型兜住非法值)。"""
        with self._status_lock:
            self._status = self._status.model_copy(update=fields)

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

    def _scan_changed_files(
            self, candidates: list[tuple[str, int, float]],
            posters: dict[str, str]) -> ScanSummary:
        """跳过没变的, 并发读变了/新增的, 落库 + 清理消失的 + 重算汇总。"""
        with self._database_sessions() as session:
            known = known_file_signatures(session)
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
        store_scanned_tracks(self._database_sessions, scanned)
        summary.tracks_removed = remove_vanished_tracks(
            self._database_sessions,
            {candidate[0] for candidate in candidates})
        with self._database_sessions() as session:
            summary.artist_count = finalize_library(session, posters)
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
