"""扫描器的进程内单例: 启动首扫 / 接口重扫 / 状态轮询共用一个实例。

引擎 (data/music.db) 与扫描器都在这里装配; lifespan 启动时调
start_service(), 路由层经 scanner() / trigger_scan() 触达。
启动链路 = 老库补数 → 首扫 (同一后台线程, 免得补数和扫描两个写者
抢 SQLite 锁)。Plex 播放列表同步 2026-09-15 已撤 (用户要求): 撤之前
同步过来的列表原地保留, 此后播放列表全在应用内建、管。
"""
import threading
from pathlib import Path

from .library_database import (DEFAULT_MUSIC_DIRECTORY, create_all,
                               dispose_engine, ensure_columns, init_engine,
                               session_factory)
from .library_scanner import LibraryScanner, backfill_legacy_rows


class _ServiceState:
    """进程级服务持有者 (避免 global 语句)。"""

    scanner: LibraryScanner | None = None
    scan_thread: threading.Thread | None = None
    # 那条扫描线程是给哪个实例起的: 重装配换实例后, 旧线程还在收尾,
    # 不能拿它的存活挡住新实例的首扫 (否则新扫描器永远停在 idle)
    scan_thread_owner: LibraryScanner | None = None


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
    """起后台扫描线程; 同一实例已在扫 (或线程刚起步还没挂上 running)
    返回 False (路由层答 409)。

    挡的只是同一实例的重复触发 —— 上一代实例的线程还在收尾不挡
    新实例: 换代重装配是正常操作 (测试每个用例都换代), 旧线程
    迟几毫秒退场是常态, 不能因此把新扫描器卡在 idle。

    after_backfill: 启动首扫用 —— 先把老库缺的入库时刻/检索键补齐再扫,
    免得补数和扫描两个写者抢 SQLite 锁 (补数是新库时瞬间空跑)。"""
    current = _service.scanner
    if current is None or current.status().running:
        return False
    with _trigger_lock:
        if (_service.scan_thread is not None
                and _service.scan_thread.is_alive()
                and _service.scan_thread_owner is current):
            return False
        _service.scan_thread_owner = current
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
    except RuntimeError:
        pass            # 两个触发挤进同一窗口, 输的那个直接退
