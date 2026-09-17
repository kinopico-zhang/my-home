"""My Music 服务生命周期测试: 启动链扫描, 旧线程滞留下的重置,
引擎状态守卫, 停止/重启。"""
import threading
import time
from pathlib import Path

import pytest

from app.music import service
from tests.music_library_helpers import _make_library, _wait_scan_done


def test_startup_chain_scans_and_playlists_alive(auth, tmp_path):
    """启动链 = 补数 → 首扫 (无同步步骤); 播放列表接口照常, 重启列表不丢。"""
    service.stop_service()
    root = tmp_path / "startup-library"
    _make_library(root)
    database_url = f"sqlite:///{tmp_path / 'boot.db'}"
    service.start_service(database_url, root, scan_immediately=True)
    _wait_scan_done(auth)
    assert auth.get("/music/api/playlists").json()["playlists"] == []

    service.stop_service()
    service.start_service(database_url, root, scan_immediately=True)
    _wait_scan_done(auth)
    assert auth.get("/music/api/playlists").json()["playlists"] == []
    stats = auth.get("/music/api/stats").json()
    assert stats["track_count"] > 0

def test_reinit_scans_even_if_old_thread_lingers(auth, tmp_path, monkeypatch):
    """换代重装配: 上一代扫描线程还没退场, 新实例的首扫也照起。

    旧版 trigger_scan 拿全局线程句柄的 is_alive 挡触发 —— 旧线程只是
    迟几毫秒收尾, 就把新扫描器永远卡在 idle (启动链测试偶发 phase=idle)。"""
    gate = threading.Event()
    real_run = service._run_scan

    def slow_run(current, after_backfill):
        if current is old:
            gate.wait(timeout=10)                      # 上一代卡在半路不退场
        real_run(current, after_backfill)

    monkeypatch.setattr(service, "_run_scan", slow_run)
    service.stop_service()
    root = tmp_path / "lingering-library"
    _make_library(root)
    service.start_service(f"sqlite:///{tmp_path / 'lingering.db'}", root,
                          scan_immediately=False)
    old = service.scanner()
    assert service.trigger_scan(after_backfill=True)   # 上一代扫描进行中
    # 旧线程卡着: 换库重装配, 新实例首扫必须照起, 不能被旧线程挡成 idle
    service.start_service(f"sqlite:///{tmp_path / 'fresh.db'}", root,
                          scan_immediately=True)
    _wait_scan_done(auth)
    assert auth.get("/music/api/status").json()["track_count"] == 4
    gate.set()                                         # 放旧线程收尾


def test_engine_state_guards(tmp_path):
    """引擎模块的守卫: 未初始化全炸, 非SQLite库封面缓存落到 data/, dispose 幂等。"""
    from app.music import library_database as music_db
    service.stop_service()
    for accessor in (music_db.engine, music_db.session_factory,
                     music_db.music_directory, music_db.artwork_cache_directory):
        with pytest.raises(RuntimeError):
            accessor()
    music_db.init_engine(None)                    # 缺省 URL/曲库目录
    assert music_db.music_directory() == Path(music_db.DEFAULT_MUSIC_DIRECTORY)
    assert music_db.artwork_cache_directory_for(
        "postgresql://u:p@localhost/db") == Path("data") / "music-art"
    assert music_db.artwork_cache_directory_for(
        f"sqlite:///{tmp_path / 'x.db'}") == tmp_path / "music-art"
    music_db.dispose_engine()
    music_db.dispose_engine()                     # 重复释放不炸
    service.start_service(f"sqlite:///{tmp_path / 'guards.db'}",
                          tmp_path / "guards-library", scan_immediately=False)
    assert music_db.engine() is not None


def test_music_service_lifecycle(auth, tmp_path):
    """服务单例: 停了没扫描器/触发被拒; 起来自动首扫; 重复扫描静默让位。"""
    service.stop_service()
    with pytest.raises(RuntimeError):
        service.scanner()
    assert service.trigger_scan() is False        # 没有扫描器
    empty = tmp_path / "empty-library"
    empty.mkdir()
    service.start_service(f"sqlite:///{tmp_path / 'lifecycle.db'}", empty,
                          scan_immediately=True)  # 启动即首扫 (空目录秒完)
    deadline = time.monotonic() + 5
    # 等扫描真正开始再等收尾 (线程刚起时 running 还没置位, 不能只看它)
    while service.scanner().status().phase == "idle" \
            and time.monotonic() < deadline:
        time.sleep(0.02)
    while service.scanner().status().running and time.monotonic() < deadline:
        time.sleep(0.02)
    assert service.scanner().status().phase == "done"
    current = service.scanner()
    with current._scan_lock:                      # noqa: SLF001 顶住锁再跑 → 让位
        service._run_scan(current, False)         # noqa: SLF001 不抛即过
