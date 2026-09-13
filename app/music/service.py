"""扫描器的进程内单例: 启动首扫 / 接口重扫 / 状态轮询共用一个实例。

引擎 (data/music.db) 与扫描器都在这里装配; lifespan 启动时调
start_service(), 路由层经 scanner() / trigger_scan() 触达。
"""
import threading
from pathlib import Path

from .library_database import (DEFAULT_MUSIC_DIRECTORY, create_all,
                               dispose_engine, init_engine, session_factory)
from .library_scanner import LibraryScanner


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
    _service.scanner = LibraryScanner(
        music_directory or Path(DEFAULT_MUSIC_DIRECTORY), session_factory())
    if scan_immediately:
        trigger_scan()


def stop_service() -> None:
    """关闭时释放连接池 (扫描线程是 daemon, 随进程退出)。"""
    _service.scanner = None
    dispose_engine()


def scanner() -> LibraryScanner:
    """当前扫描器 (start_service 之前调用是程序装配错误, 直接炸)。"""
    if _service.scanner is None:
        raise RuntimeError("My Music 未初始化 (start_service 未调用)")
    return _service.scanner


def trigger_scan() -> bool:
    """起后台扫描线程; 已在扫返回 False (路由层答 409)。"""
    current = _service.scanner
    if current is None or current.status().running:
        return False
    with _trigger_lock:
        if _service.scan_thread is not None and _service.scan_thread.is_alive():
            return False
        _service.scan_thread = threading.Thread(target=_run_scan, args=(current,),
                                                daemon=True, name="music-scan")
        _service.scan_thread.start()
        return True


def _run_scan(current: LibraryScanner) -> None:
    """线程体: 异常已记进扫描状态, 这里只吃掉重复触发的拒绝。"""
    try:
        current.scan()
    except RuntimeError:
        pass            # 两个触发挤进同一窗口, 输的那个直接退
