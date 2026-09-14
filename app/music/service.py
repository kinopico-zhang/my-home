"""扫描器的进程内单例: 启动首扫 / 接口重扫 / 状态轮询共用一个实例。

引擎 (data/music.db) 与扫描器都在这里装配; lifespan 启动时调
start_service(), 路由层经 scanner() / trigger_scan() 触达。
启动链路 = 老库补数 → 首扫 → Plex 播放列表同步 (同一后台线程, 免得
几个写者抢 SQLite 锁; Plex 不在就静默跳过, 不挡服务起来)。
"""
import sqlite3
import threading
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from .library_database import (DEFAULT_MUSIC_DIRECTORY, create_all,
                               dispose_engine, ensure_columns, init_engine,
                               session_factory)
from . import library_playlists
from .library_scanner import LibraryScanner, backfill_legacy_rows


class _ServiceState:
    """进程级服务持有者 (避免 global 语句)。"""

    scanner: LibraryScanner | None = None
    scan_thread: threading.Thread | None = None


_service = _ServiceState()
_trigger_lock = threading.Lock()


def start_service(database_url: str | None = None,
                  music_directory: Path | None = None,
                  scan_immediately: bool = True) -> None:
    """建引擎建表 (缺省 data/music.db + /share/Media/Music), 起后台首扫。

    测试用参数注入临时库 (scan_immediately=False 只装配不扫);
    重复调用重装配 (换实例, 正在跑的扫描自然收尾)。"""
    init_engine(database_url, music_directory)
    create_all()
    ensure_columns()          # 老库补列 (added_at / 检索键), 新列带默认值
    _service.scanner = LibraryScanner(
        music_directory or Path(DEFAULT_MUSIC_DIRECTORY), session_factory())
    if scan_immediately:
        trigger_scan(after_backfill=True)


def stop_service() -> None:
    """关闭时释放连接池 (扫描线程是 daemon, 随进程退出)。"""
    _service.scanner = None
    dispose_engine()


def scanner() -> LibraryScanner:
    """当前扫描器 (start_service 之前调用是程序装配错误, 直接炸)。"""
    if _service.scanner is None:
        raise RuntimeError("My Music 未初始化 (start_service 未调用)")
    return _service.scanner


def trigger_scan(after_backfill: bool = False) -> bool:
    """起后台扫描线程; 已在扫返回 False (路由层答 409)。

    after_backfill: 启动首扫用 —— 先把老库缺的入库时刻/检索键补齐再扫,
    免得补数和扫描两个写者抢 SQLite 锁 (补数是新库时瞬间空跑)。"""
    current = _service.scanner
    if current is None or current.status().running:
        return False
    with _trigger_lock:
        if _service.scan_thread is not None and _service.scan_thread.is_alive():
            return False
        _service.scan_thread = threading.Thread(
            target=_run_scan, args=(current, after_backfill),
            daemon=True, name="music-scan")
        _service.scan_thread.start()
        return True


def _run_scan(current: LibraryScanner, after_backfill: bool) -> None:
    """线程体: 异常已记进扫描状态, 这里只吃掉重复触发的拒绝。"""
    try:
        if after_backfill:
            backfill_legacy_rows(session_factory())
        current.scan()
        if after_backfill:
            _sync_playlists_once()    # 启动链路收尾 (手动重扫不同步播放列表)
    except RuntimeError:
        pass            # 两个触发挤进同一窗口, 输的那个直接退


def _sync_playlists_once() -> None:
    """同步一次 Plex 播放列表 (库不在/读不动都静默跳过, 点按钮才见报错)。"""
    try:
        plex_playlists = library_playlists.read_plex_playlists(
            Path(library_playlists.DEFAULT_PLEX_LIBRARY_DATABASE))
        with session_factory()() as session:
            library_playlists.sync_playlists(session, plex_playlists)
    except (OSError, sqlite3.Error, SQLAlchemyError):
        pass            # Plex 以后会被下掉: 服务自身绝不依赖它
