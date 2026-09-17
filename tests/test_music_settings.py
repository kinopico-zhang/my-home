"""音乐设置测试: 权限与蜂窝账本, 保存与曲库目录热切换, 启动读
设置里的曲库目录。歌词测试拆去了 test_music_lyrics.py。
拆自原 test_music_settings.py (结构化重构, 代码逐字节未动)。"""
from datetime import datetime

from fastapi.testclient import TestClient

import app.main as m
from app import account_store, config
from app.music import service
from app.music.library_database import session_factory
from app.music import library_settings
from tests.music_audio_seed import _write_plain_track
from tests.music_library_helpers import _wait_scan_done

def test_settings_permissions_and_cellular_ledger(auth, usersdb):
    """设置接口: 普通用户能读不能写, 未登录 401; 流量月账按月累加。"""
    anon = TestClient(m.app)
    assert anon.get("/music/api/settings").status_code == 401
    account_store.create_user(usersdb, "试听丙", "password123")
    other = TestClient(m.app)
    assert other.post("/api/login",
                      json={"user": "试听丙", "password": "password123"}
                      ).status_code == 200
    # 普通账号: 看得到现值 (前端只读渲染), 保存被拒
    visible = other.get("/music/api/settings").json()
    assert visible["music_directory_default"]
    assert other.post("/music/api/settings", json={}).status_code == 403

    # 现值: 全默认 (没改过 = 空, 前端拿 *_default 作占位)
    state = auth.get("/music/api/settings").json()
    assert state["music_directory"] == ""
    assert state["music_directory_default"]            # 默认路径非空
    assert state["lyrics_api_enabled"] is True
    assert state["lyrics_api_base"] == ""
    assert state["lyrics_api_default"] == library_settings.LYRICS_API_DEFAULT
    assert state["cellular_months"] == []

    # 流量上报: 谁登录都能报 (报的是自己这台设备的消耗), 按月累加
    assert anon.post("/music/api/cellular-usage",
                     json={"bytes": 1}).status_code == 401
    assert other.post("/music/api/cellular-usage",
                      json={"bytes": 1234}).json() == {"ok": True}
    assert auth.post("/music/api/cellular-usage",
                     json={"bytes": 100}).json() == {"ok": True}
    months = auth.get("/music/api/settings").json()["cellular_months"]
    assert months == [{"month": datetime.now(config.LOCAL_TZ).strftime("%Y-%m"),
                       "bytes": 1334}]
    # 校验: 负数 / 超单次上限 422 (schema 兜住)
    assert auth.post("/music/api/cellular-usage",
                     json={"bytes": -1}).status_code == 422
    assert auth.post("/music/api/cellular-usage",
                     json={"bytes": 2 ** 30 + 1}).status_code == 422


def test_settings_save_and_directory_switch(auth, tmp_path):
    """保存设置: 歌词 API 开关/地址 (没传的字段不动); 曲库路径换目录 →
    同库换根重扫, 旧目录的曲目被清掉。"""
    root = tmp_path / "music-library"            # isolate 注入的曲库目录
    _write_plain_track(root, "A乐队/2001 甲 [aaaa1111]/01 曲A.flac", "曲A")
    assert auth.post("/music/api/rescan").json() == {"started": True}
    _wait_scan_done(auth)
    assert auth.get("/music/api/status").json()["track_count"] == 1

    # 歌词 API 地址不带协议头 400; 正常的存上
    assert auth.post("/music/api/settings",
                     json={"lyrics_api_base": "lrclib.net"}).status_code == 400
    saved = auth.post("/music/api/settings",
                      json={"lyrics_api_enabled": False,
                            "lyrics_api_base": "https://example.com/api"}).json()
    assert saved["lyrics_api_enabled"] is False
    assert saved["lyrics_api_base"] == "https://example.com/api"
    # 空请求体: 一个字段都不动
    assert auth.post("/music/api/settings", json={}).json()[
        "lyrics_api_base"] == "https://example.com/api"

    # 曲库路径: 不存在的 400; 换成新目录自动重扫, 甲被当消失清掉
    new_root = tmp_path / "switched-library"
    _write_plain_track(new_root, "B乐队/2002 乙 [bbbb2222]/01 曲B.flac", "曲B")
    assert auth.post("/music/api/settings", json={
        "music_directory": str(tmp_path / "no-such-dir")}).status_code == 400
    switched = auth.post("/music/api/settings",
                         json={"music_directory": str(new_root)}).json()
    assert switched["music_directory"] == str(new_root)
    _wait_scan_done(auth)
    assert auth.get("/music/api/status").json()["track_count"] == 1
    tracks = auth.get("/music/api/tracks").json()["tracks"]
    assert [track["title"] for track in tracks] == ["曲B"]


def test_startup_reads_music_directory_from_settings(auth, tmp_path):
    """设置里改过的曲库路径重启后仍生效 (不注入目录时读设置行)。"""
    service.stop_service()
    root = tmp_path / "settings-library"
    _write_plain_track(root, "A乐队/2001 甲 [aaaa1111]/01 曲A.flac", "曲A")
    url = f"sqlite:///{tmp_path / 'settings.db'}"
    service.start_service(url, tmp_path / "music-library",
                          scan_immediately=False)
    with session_factory()() as session:
        assert library_settings.save_settings(session, str(root), None, None)

    service.stop_service()
    service.start_service(url, None, scan_immediately=True)   # 读设置行扫新目录
    _wait_scan_done(auth)
    assert auth.get("/music/api/status").json()["track_count"] == 1
    assert [track["title"] for track in
            auth.get("/music/api/tracks").json()["tracks"]] == ["曲A"]
