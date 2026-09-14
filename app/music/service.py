"""扫描器的进程内单例: 启动首扫 / 接口重扫 / 自动增量重扫 / 状态轮询共用一个实例。

引擎 (data/music.db) 与扫描器都在这里装配; lifespan 启动时调
start_service(), 路由层经 scanner() / trigger_scan() 触达。
启动链路 = 老库补数 → 首扫 (同一后台线程, 免得补数和扫描两个写者
抢 SQLite 锁); 曲库路径可被设置页改过, 注入目录优先 (测试), 否则读
设置行 (空 = env 默认)。另有后台线程每隔几分钟自动增量重扫一轮
(walk + stat 秒级), 新放进曲库的专辑不用等人按「重新扫描」。
"""
import threading
import time
from pathlib import Path

from . import library_settings
from .library_database import (create_all, dispose_engine, ensure_columns,
                               init_engine,
                               database_url as current_database_url,
                               music_directory as current_music_directory,
                               session_factory)
from .library_scanner import LibraryScanner, backfill_legacy_rows

# 自动增量重扫间隔 (秒): 没变的文件只 stat 不读标签, 一轮秒级;
# 新专辑最迟这几分钟内自动出现, 不用任何人手动触发
_AUTO_RESCAN_SECONDS = 300


class _ServiceState:
    """进程级服务持有者 (避免 global 语句)。"""

    scanner: LibraryScanner | None = None
    scan_thread: threading.Thread | None = None
    # 那条扫描线程是给哪个实例起的: 重装配换实例后, 旧线程还在收尾,
    # 不能拿它的存活挡住新实例的首扫 (否则新扫描器永远停在 idle)
    scan_thread_owner: LibraryScanner | None = None
    # 自动重扫线程的代数: 每次重装配换代, 旧线程睡醒发现代数不对就退
    watch_generation: int = 0


_service = _ServiceState()
_trigger_lock = threading.Lock()


def start_service(database_url: str | None = None,
                  music_directory: Path | None = None,
                  scan_immediately: bool = True) -> None:
    """建引擎建表 (缺省 data/music.db + 设置行/env 里的曲库路径), 起后台首扫。

    测试用参数注入临时库 (scan_immediately=False 只装配不扫);
    重复调用重装配 (换实例, 正在跑的扫描自然收尾)。"""
    init_engine(database_url, music_directory)
    create_all()
    ensure_columns()          # 老库补列 (added_at / 检索键), 新列带默认值
    # 曲库路径: 测试注入的目录优先; 没注入就读设置行 (设置页改过的路径
    # 重启动也生效), 与默认不同就同库换个根目录重装配
    if music_directory is None:
        with session_factory()() as session:
            effective = library_settings.effective_music_directory(session)
        if effective != current_music_directory():
            url = current_database_url()
            dispose_engine()
            init_engine(url, effective)
    _service.scanner = LibraryScanner(current_music_directory(),
                                      session_factory())
    if scan_immediately:
        trigger_scan(after_backfill=True)
    _start_auto_rescan()


def stop_service() -> None:
    """关闭时释放连接池 (扫描线程是 daemon, 随进程退出)。"""
    _service.scanner = None
    dispose_engine()


def apply_music_directory(directory: Path) -> None:
    """设置页改了曲库路径: 同库换根目录, 起一轮全量重扫。

    旧目录的索引行会被新一轮当 "消失" 清掉; 旧扫描线程若还在写,
    自然收尾 (同一个 SQLite 文件, 顶多短暂抢锁)。"""
    url = current_database_url()
    dispose_engine()
    init_engine(url, directory)
    _service.scanner = LibraryScanner(directory, session_factory())
    trigger_scan()


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


# ---------------------------------------------------------------- 自动重扫

def _start_auto_rescan() -> None:
    """起 (或换代) 自动增量重扫线程: 隔几分钟扫一遍, 新专辑很快出现。

    每次 start_service 换一代 —— 旧线程睡醒发现代数不对就退,
    不会摸到新装配的实例 (与扫描线程同一条换代纪律)。"""
    _service.watch_generation += 1
    threading.Thread(target=_auto_rescan_loop,
                     args=(_service.watch_generation,), daemon=True,
                     name="music-auto-rescan").start()


def _auto_rescan_loop(generation: int) -> None:
    """线程体: 睡 → 查代数 → 触发一轮; 代数不对或服务停了就退。"""
    while True:
        time.sleep(_AUTO_RESCAN_SECONDS)
        if generation != _service.watch_generation or _service.scanner is None:
            return
        trigger_scan()     # 已在扫会被拒 (返回 False), 下一轮再说
