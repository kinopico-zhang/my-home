"""My Music 设置/联网歌词/蜂窝流量测试: 设置接口的权限与校验、
曲库路径热切换、歌词 API 的各分支 (纯函数直测 + 接口闭环)。

音频文件与扫描等待复用 tests.test_music 的助手 (_write_audio/_wait_scan_done)。"""
import json
from datetime import datetime
from email.message import Message
from urllib.error import HTTPError

import pytest
from fastapi.testclient import TestClient

import app.main as m
from app import account_store, config
from app.music import service
from app.music.library_database import session_factory
from app.music import library_lyrics_api, library_queries, library_settings
from tests.test_music import _wait_scan_done, _write_plain_track


def test_settings_permissions_and_cellular_ledger(auth, usersdb):
    """设置接口: 管理员可读写, 普通用户 403 / 未登录 401; 流量月账按月累加。"""
    anon = TestClient(m.app)
    assert anon.get("/music/api/settings").status_code == 401
    account_store.create_user(usersdb, "试听丙", "password123")
    other = TestClient(m.app)
    assert other.post("/api/login",
                      json={"user": "试听丙", "password": "password123"}
                      ).status_code == 200
    assert other.get("/music/api/settings").status_code == 403
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


def test_lyrics_fetched_from_api_and_persisted(auth, tmp_path):
    """歌词联网补齐: 求到写回索引 (之后离线也有), 求不到保持空; 关了 API 不联网。"""
    root = tmp_path / "music-library"
    _write_plain_track(root, "A乐队/2001 甲 [aaaa1111]/01 曲A.flac", "曲A")
    _write_plain_track(root, "A乐队/2001 甲 [aaaa1111]/02 曲B.flac", "曲B")
    assert auth.post("/music/api/rescan").json() == {"started": True}
    _wait_scan_done(auth)
    tracks = {track["title"]: track["track_id"]
              for track in auth.get("/music/api/tracks").json()["tracks"]}

    # 求到带时间轴的 → 写回索引, synced 标记跟走
    calls = []

    def fake_fetch(api_base, title, artist, album_title):
        calls.append((api_base, title, artist, album_title))
        return "[00:10.00]从API求来的"

    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(library_queries, "fetch_lyrics", fake_fetch)
        lyrics = auth.get(f"/music/api/tracks/{tracks['曲A']}/lyrics").json()
    assert lyrics == {"track_id": tracks["曲A"],
                      "lyrics": "[00:10.00]从API求来的",
                      "lyrics_synced": True}
    assert calls == [(library_settings.LYRICS_API_DEFAULT,
                      "曲A", "A乐队", "曲A的专辑")]

    # 写回了索引: 再问不再联网 (替身这次一被调就炸)
    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(library_queries, "fetch_lyrics",
                        lambda *a: (_ for _ in ()).throw(
                            AssertionError("不该再联网")))
        again = auth.get(f"/music/api/tracks/{tracks['曲A']}/lyrics").json()
    assert again["lyrics"] == "[00:10.00]从API求来的"

    # 求不到 (空串): 保持没歌词
    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(library_queries, "fetch_lyrics", lambda *a: "")
        empty = auth.get(f"/music/api/tracks/{tracks['曲B']}/lyrics").json()
    assert empty == {"track_id": tracks["曲B"], "lyrics": "",
                     "lyrics_synced": False}

    # 设置里关掉歌词 API: 连求都不求
    assert auth.post("/music/api/settings",
                     json={"lyrics_api_enabled": False}
                     ).json()["lyrics_api_enabled"] is False
    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(library_queries, "fetch_lyrics",
                        lambda *a: (_ for _ in ()).throw(
                            AssertionError("关了 API 不该联网")))
        empty = auth.get(f"/music/api/tracks/{tracks['曲B']}/lyrics").json()
    assert empty["lyrics"] == ""


class _FakeResponse:
    """urlopen 的替身应答 (够 fetch_lyrics 用: status + read + 上下文)。"""

    def __init__(self, payload: bytes, status: int = 200):
        """带状态码的定身响应。"""
        self._payload = payload
        self.status = status

    def read(self) -> bytes:
        """一次性吐出全部响应体。"""
        return self._payload

    def __enter__(self):
        """with 块进入 (urlopen 是上下文管理器)。"""
        return self

    def __exit__(self, *exc):
        """交还异常 (有异常照常往外抛)。"""
        return False


def test_fetch_lyrics_paths(monkeypatch):
    """联网求词的分支: 优先带时间轴的 / 截断 / 各种失败一律空串不抛。"""
    requested = {}

    def fake_urlopen(request, timeout):
        requested["url"] = request.full_url
        requested["timeout"] = timeout
        return _FakeResponse(json.dumps(
            {"syncedLyrics": "[00:01.00]synced",
             "plainLyrics": "plain"}).encode())

    monkeypatch.setattr(library_lyrics_api, "urlopen", fake_urlopen)
    assert library_lyrics_api.fetch_lyrics(
        "https://example.com/api/", "曲", "艺人", "专辑") == "[00:01.00]synced"
    assert requested["url"].startswith("https://example.com/api/get?")
    assert "track_name=" in requested["url"]
    assert requested["timeout"] == library_lyrics_api._TIMEOUT_SECONDS  # noqa: SLF001

    # 只剩纯文本: 用 plainLyrics; 空地址 (相对 URL) 当失败
    monkeypatch.setattr(library_lyrics_api, "urlopen", lambda req, timeout:
                        _FakeResponse(b'{"plainLyrics": "plain text"}'))
    assert library_lyrics_api.fetch_lyrics(
        "https://example.com/api", "t", "a", "b") == "plain text"
    assert library_lyrics_api.fetch_lyrics("", "t", "a", "b") == ""

    # 超长截断 (与库里的歌词列同一上限)
    monkeypatch.setattr(library_lyrics_api, "urlopen", lambda req, timeout:
                        _FakeResponse(b'{"plainLyrics": "' + b"x" * 30000
                                      + b'"}'))
    assert len(library_lyrics_api.fetch_lyrics(
        "https://example.com/api", "t", "a", "b")) \
        == library_lyrics_api._MAX_LYRICS_BYTES                    # noqa: SLF001

    # 失败分支: 404 / 坏 JSON / 非对象 / 非 200 —— 都当求不到
    monkeypatch.setattr(library_lyrics_api, "urlopen", lambda req, timeout:
                        (_ for _ in ()).throw(
                            HTTPError(req.full_url, 404, "Not Found",
                                      Message(), None)))
    assert library_lyrics_api.fetch_lyrics(
        "https://example.com/api", "t", "a", "b") == ""
    monkeypatch.setattr(library_lyrics_api, "urlopen", lambda req, timeout:
                        _FakeResponse(b"not json"))
    assert library_lyrics_api.fetch_lyrics(
        "https://example.com/api", "t", "a", "b") == ""
    monkeypatch.setattr(library_lyrics_api, "urlopen", lambda req, timeout:
                        _FakeResponse(b"[1, 2]"))
    assert library_lyrics_api.fetch_lyrics(
        "https://example.com/api", "t", "a", "b") == ""
    monkeypatch.setattr(library_lyrics_api, "urlopen", lambda req, timeout:
                        _FakeResponse(b"{}", status=503))
    assert library_lyrics_api.fetch_lyrics(
        "https://example.com/api", "t", "a", "b") == ""
