"""My Music 接口测试: 登录门槛, 浏览/搜索端点, 统计, Service
Worker, 播放计数, webapp 兜底。"""
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import app.main as m
from app import account_store, config
from app.music.library_database import PlayStat, session_factory
from app.music import library_queries
from tests.music_library_helpers import _seed_library


# ---------------------------------------------------------------- 接口

def _login(client):
    response = client.post(
        "/api/login",
        json={"user": config.AUTH_USER, "password": config.AUTH_PASS})
    assert response.status_code == 200


def test_music_page_requires_login(auth):
    """页面未登录 302 登录页, 接口未登录 401; 登录后页面 200。"""
    anonymous = TestClient(m.app)      # auth 会登录共享的 client, 这里另开
    assert anonymous.get("/music",
                         follow_redirects=False).status_code == 302
    assert anonymous.get("/music/api/status").status_code == 401
    assert anonymous.get("/music/api/stats").status_code == 401
    assert anonymous.get("/music/api/albums").status_code == 401
    assert auth.get("/music").status_code == 200   # 307 /music/ 跟一步到页面


def test_music_browse_and_search_endpoints(auth):
    """空库: 各接口空结果 + 404 + 参数校验 422。"""
    assert auth.get("/music/api/status").json()["track_count"] == 0
    assert auth.get("/music/api/stats").json() == {
        "artist_count": 0, "album_count": 0, "track_count": 0,
        "total_duration_seconds": 0.0, "formats": []}
    assert auth.get("/music/api/albums").json() == {
        "albums": [], "total_count": 0, "offset": 0, "limit": 60}
    assert auth.get("/music/api/artists").json()["artists"] == []
    assert auth.get("/music/api/tracks").json()["tracks"] == []
    assert auth.get("/music/api/search", params={"q": "x"}).json() == {
        "query": "x", "language": "全部", "tracks": [], "albums": [],
        "artists": [], "lyric_hits": [],
        "track_total": 0, "album_total": 0, "artist_total": 0, "lyric_total": 0}
    assert auth.get("/music/api/albums/1").status_code == 404
    assert auth.get("/music/api/artists/1").status_code == 404
    assert auth.get("/music/api/tracks/1/lyrics").status_code == 404
    assert auth.get("/music/api/albums/1/artwork").status_code == 404
    assert auth.get(
        "/music/api/albums", params={"language": "乱写"}).status_code == 422
    assert auth.get(
        "/music/api/albums", params={"sort": "乱写"}).status_code == 422
    assert auth.get(
        "/music/api/tracks", params={"limit": 0}).status_code == 422


def test_music_stats_endpoint(auth):
    """统计页: 库规模 + 总时长 + 格式分布 (多的在前, 同数按名, 播不了标记)。"""
    _seed_library()
    data = auth.get("/music/api/stats").json()
    assert data["artist_count"] == 2 and data["album_count"] == 3
    assert data["track_count"] == 5
    assert data["total_duration_seconds"] == 10.0      # 五曲各 2 秒
    assert data["formats"] == [
        {"format": "flac", "count": 3, "playable": True},
        {"format": "mp3", "count": 1, "playable": True},
        {"format": "tak", "count": 1, "playable": False}]


def test_music_service_worker_endpoint(client):
    """SW 脚本: 无需登录 200 (SW 更新检查不带 cookie), JS 类型, 可缓存校验。"""
    response = client.get("/music/sw.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    assert "music-downloads-v1" in response.text
    assert response.headers["cache-control"] == "no-cache"


def test_record_play_counts_and_dedups():
    """查询层: user+track 一行, 重播只加次数; 曲目不在库里不记。"""
    _seed_library()
    with session_factory()() as session:
        assert library_queries.record_play(session, "u-1", 1) is True
        assert library_queries.record_play(session, "u-1", 1) is True
        assert library_queries.record_play(session, "u-1", 999) is False
        stat = session.execute(select(PlayStat)).scalar_one()
        assert stat.play_count == 2
        assert [t.title for t in
                library_queries.recent_plays(session, "u-1")] == ["曲A"]
        assert library_queries.recent_plays(session, "u-1")[0].play_count == 2
        assert library_queries.recent_plays(session, "别人") == []


def test_play_record_endpoints_per_user(auth, usersdb):
    """播放记录接口: 重播把曲子顶回最前, 账号之间互不可见, 没登录 401。"""
    _seed_library()
    anon = TestClient(m.app)
    assert anon.post("/music/api/plays",
                     json={"track_id": 1}).status_code == 401
    assert anon.get("/music/api/plays/recent").status_code == 401

    assert auth.post("/music/api/plays", json={"track_id": 1}).status_code == 200
    time.sleep(0.002)
    assert auth.post("/music/api/plays", json={"track_id": 2}).status_code == 200
    time.sleep(0.002)
    assert auth.post("/music/api/plays", json={"track_id": 1}).status_code == 200
    assert auth.post("/music/api/plays",
                     json={"track_id": 9999}).status_code == 404
    recent = auth.get("/music/api/plays/recent").json()["tracks"]
    assert [t["title"] for t in recent] == ["曲A", "曲B"]   # 最近那次排前
    assert recent[0]["album_title"] == "甲"
    assert recent[0]["play_count"] == 2                # 1.8.1: 播过几次跟着行走
    assert recent[1]["play_count"] == 1

    # 另一个账号: 各记各的, 看不见管理员的记录
    account_store.create_user(usersdb, "试听乙", "password123")
    yi = TestClient(m.app)
    assert yi.post("/api/login",
                   json={"user": "试听乙", "password": "password123"}
                   ).status_code == 200
    assert yi.get("/music/api/plays/recent").json()["tracks"] == []
    assert yi.post("/music/api/plays", json={"track_id": 3}).status_code == 200
    assert [t["title"] for t in
            yi.get("/music/api/plays/recent").json()["tracks"]] == ["Hello"]
    assert [t["title"] for t in
            auth.get("/music/api/plays/recent").json()["tracks"]] == ["曲A", "曲B"]


def test_music_webapp_fallbacks(auth):
    """webapp 兜底: 登出 / 数据库异常 503 / 会话失效 401 / 资源不存在 404。"""
    from sqlalchemy.exc import SQLAlchemyError
    patched_queries = library_queries
    with pytest.MonkeyPatch.context() as patcher:   # 只撤自己的补丁
        patcher.setattr(patched_queries, "list_albums",
                        lambda *a, **k: (_ for _ in ()).throw(
                            SQLAlchemyError("boom")))
        assert auth.get("/music/api/albums").status_code == 503
    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr("app.account_store.user_for_cookie",
                        lambda *a, **k: None)
        assert auth.get("/music/api/status").status_code == 401
    assert auth.get("/music/api/artists/99999").status_code == 404
    assert auth.get("/music/api/tracks/99999/lyrics").status_code == 404
    assert auth.get("/music/api/tracks/99999/credits").status_code == 404
    response = auth.post("/music/api/logout")     # 登出清 cookie, 放最后
    assert response.status_code == 200 and response.json() == {"ok": True}
