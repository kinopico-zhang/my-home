"""歌词测试: LRCLIB 联网拉取与持久化, fetch_lyrics 路径分支。
拆自原 test_music_settings.py (结构化重构, 代码逐字节未动)。"""
import json
from email.message import Message
from urllib.error import HTTPError

import pytest

from app.music import library_lyrics_api, library_queries, library_settings
from tests.music_audio_seed import _write_plain_track
from tests.music_library_helpers import _wait_scan_done

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
        patcher.setattr(library_queries.lyrics_queries, "fetch_lyrics", fake_fetch)
        lyrics = auth.get(f"/music/api/tracks/{tracks['曲A']}/lyrics").json()
    assert lyrics == {"track_id": tracks["曲A"],
                      "lyrics": "[00:10.00]从API求来的",
                      "lyrics_synced": True}
    assert calls == [(library_settings.LYRICS_API_DEFAULT,
                      "曲A", "A乐队", "曲A的专辑")]

    # 写回了索引: 再问不再联网 (替身这次一被调就炸)
    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(library_queries.lyrics_queries, "fetch_lyrics",
                        lambda *a: (_ for _ in ()).throw(
                            AssertionError("不该再联网")))
        again = auth.get(f"/music/api/tracks/{tracks['曲A']}/lyrics").json()
    assert again["lyrics"] == "[00:10.00]从API求来的"

    # 求不到 (空串): 保持没歌词
    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(library_queries.lyrics_queries, "fetch_lyrics", lambda *a: "")
        empty = auth.get(f"/music/api/tracks/{tracks['曲B']}/lyrics").json()
    assert empty == {"track_id": tracks["曲B"], "lyrics": "",
                     "lyrics_synced": False}

    # 设置里关掉歌词 API: 连求都不求
    assert auth.post("/music/api/settings",
                     json={"lyrics_api_enabled": False}
                     ).json()["lyrics_api_enabled"] is False
    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(library_queries.lyrics_queries, "fetch_lyrics",
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
