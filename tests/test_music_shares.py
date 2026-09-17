"""My Music 分享链接测试: uuid 即凭证的公开面 (页面/数据/流/封面全免登录),
24 小时过期; 每个 token 只放行"这份分享里确实有的东西" —— 拿着 A 的
链接听不到 B 的歌。公开面能过, 也一并证明主应用中间件放行了该前缀。
"""
import time

import pytest
from fastapi.testclient import TestClient

import app.main as m
from app.music.library_database import (ShareLink, Track, music_directory,
                                        session_factory)
from tests.music_audio_seed import PICTURE_BYTES, _write_audio
from tests.music_library_helpers import _seed_library


def _seed_with_files() -> None:
    """索引行 + 对应的真实音频文件 (流/封面接口要读盘): 曲A 带内嵌封面。"""
    _seed_library()
    _write_audio(music_directory(), "AI机组/甲/01.flac",
                 {"TITLE": "曲A"}, PICTURE_BYTES)
    _write_audio(music_directory(), "AI机组/甲/02.flac", {"TITLE": "曲B"})


def _make_share(client, kind, target_id):
    response = client.post("/music/api/shares",
                           json={"kind": kind, "id": target_id})
    assert response.status_code == 200, response.text
    return response.json()


def test_share_track_public_flow(auth):
    """单曲分享全流程: 开链接 (32 位 hex, 24h 失效时刻) → 匿名访客打得开
    页面、拉到数据、播得到流 (Range 206)、取得到封面。"""
    _seed_with_files()
    made = _make_share(auth, "track", 1)
    assert len(made["token"]) == 32
    int(made["token"], 16)                        # 32 位十六进制 (uuid4 hex)
    assert made["expires_at"] == pytest.approx(time.time() + 24 * 3600, abs=5)

    anon = TestClient(m.app)                      # 不带 cookie: 分享面免登录
    page = anon.get(f"/music/share/{made['token']}")
    assert page.status_code == 200 and "share-mark" in page.text
    data = anon.get(f"/music/share/{made['token']}/api").json()
    assert data["kind"] == "track"
    assert data["title"] == "曲A" and data["subtitle"] == "AI机组"
    assert [t["title"] for t in data["tracks"]] == ["曲A"]
    assert data["playlist"] is None

    streamed = anon.get(f"/music/share/{made['token']}/stream/1")
    assert streamed.status_code == 200 and streamed.content
    ranged = anon.get(f"/music/share/{made['token']}/stream/1",
                      headers={"Range": "bytes=0-1"})
    assert ranged.status_code == 206 and len(ranged.content) == 2
    # 这首自己的内嵌封面 + 它的专辑封面都在白名单里
    assert anon.get(
        f"/music/share/{made['token']}/artwork/track/1").status_code == 200
    assert anon.get(
        f"/music/share/{made['token']}/artwork/album/1").status_code == 200


def test_share_create_requires_login():
    """开链接要登录 (分享是登录用户的动作); 公开面只是收链接那头。"""
    anon = TestClient(m.app)
    assert anon.post("/music/api/shares",
                     json={"kind": "track", "id": 1}).status_code == 401


def test_share_create_validation(auth):
    """分享对象不在库里 404; 类型不认识 422 (请求体模式拦在前面)。"""
    _seed_library()
    assert auth.post("/music/api/shares",
                     json={"kind": "track", "id": 999}).status_code == 404
    assert auth.post("/music/api/shares",
                     json={"kind": "playlist", "id": 999}).status_code == 404
    assert auth.post("/music/api/shares",
                     json={"kind": "album", "id": 1}).status_code == 422


def test_share_playlist_scopes_content(auth):
    """列表分享: 数据按列表内顺序; 库里有但列表里没有的歌, 流/封面/专辑
    封面一概 404 —— token 只认"这份分享里确实有的东西"。"""
    _seed_with_files()
    created = auth.post("/music/api/playlists",
                        json={"name": "分享单"}).json()
    for track_id in (1, 3):
        assert auth.post(
            f"/music/api/playlists/{created['playlist_id']}/tracks",
            json={"track_id": track_id}).status_code == 200
    made = _make_share(auth, "playlist", created["playlist_id"])

    anon = TestClient(m.app)
    data = anon.get(f"/music/share/{made['token']}/api").json()
    assert data["kind"] == "playlist" and data["title"] == "分享单"
    assert [t["title"] for t in data["tracks"]] == ["曲A", "Hello"]
    assert data["playlist"]["playlist_id"] == created["playlist_id"]

    # 曲B (id=2) 的文件在盘上、也在库里, 但不在这份分享里
    assert anon.get(f"/music/share/{made['token']}/stream/2").status_code == 404
    assert anon.get(
        f"/music/share/{made['token']}/artwork/track/2").status_code == 404
    assert anon.get(
        f"/music/share/{made['token']}/artwork/album/3").status_code == 404
    # 列表里的照常放行; 没传过自定义封面 → 列表封面 404 (前端落渐变占位)
    assert anon.get(f"/music/share/{made['token']}/stream/1").status_code == 200
    assert anon.get(
        f"/music/share/{made['token']}/artwork/playlist/"
        f"{created['playlist_id']}").status_code == 404


def test_share_expiry_and_unknown_token(auth):
    """过期 24 小时即废: 数据/流/封面一律 410 (页面壳仍 200, 失效态由页面
    自己拉 api 后显示); 过期行被顺手清掉; 从没开过的 token 同样 410。"""
    _seed_with_files()
    made = _make_share(auth, "track", 1)
    with session_factory()() as session:          # 拨回 25 小时前: 链接已过期
        link = session.get(ShareLink, made["token"])
        assert link is not None
        link.created_at = time.time() - 25 * 3600
        session.commit()

    anon = TestClient(m.app)
    assert anon.get(f"/music/share/{made['token']}").status_code == 200
    assert anon.get(f"/music/share/{made['token']}/api").status_code == 410
    assert anon.get(f"/music/share/{made['token']}/stream/1").status_code == 410
    assert anon.get(
        f"/music/share/{made['token']}/artwork/track/1").status_code == 410
    with session_factory()() as session:          # 惰性清除: 行已删
        assert session.get(ShareLink, made["token"]) is None
    assert anon.get(f"/music/share/{'f' * 32}/api").status_code == 410


def test_share_page_og_card(auth):
    """微信分享卡片 (og: 三件套, 微信不跑页面 JS 全看这里): 单曲卡 = 曲名 +
    自己的内嵌图; 列表卡 = 列表名 + 自定义封面, 没传过退第一首的专辑图;
    图片都是绝对地址; 死链也给通用文案 (占位符不漏空)。"""
    _seed_with_files()
    made = _make_share(auth, "track", 1)
    anon = TestClient(m.app)
    page = anon.get(f"/music/share/{made['token']}")
    assert page.status_code == 200
    assert '<meta property="og:title" content="曲A">' in page.text
    assert '<meta property="og:description" content="AI机组 · My Music">' \
        in page.text
    assert (f'<meta property="og:image" content="http://testserver'
            f'/music/share/{made["token"]}/artwork/track/1">') in page.text
    assert "<!--og-->" not in page.text          # 占位符换干净了

    created = auth.post("/music/api/playlists",
                        json={"name": "卡片单"}).json()
    auth.post(f"/music/api/playlists/{created['playlist_id']}/tracks",
              json={"track_id": 1})
    made = _make_share(auth, "playlist", created["playlist_id"])
    page = anon.get(f"/music/share/{made['token']}")
    assert '<meta property="og:title" content="卡片单">' in page.text
    # 没传过自定义封面 → 退第一首的专辑图
    assert f'/music/share/{made["token"]}/artwork/album/1">' in page.text

    page = anon.get(f"/music/share/{'0' * 32}")
    assert '<meta property="og:title" content="My Music 分享">' in page.text
    assert "music/static/icon-512.png" in page.text


def test_share_lyrics_scoped(auth):
    """分享页歌词路由: 走应用同一条取词通道 (带联网补词配置), 但只放行
    这份分享里确实有的; 死链 410。"""
    _seed_with_files()
    with session_factory()() as session:         # 给曲A 塞一首带时间轴的词
        track = session.get(Track, 1)
        assert track is not None
        track.lyrics = "[00:01.00]第一句\n[00:05.00]第二句"
        track.lyrics_synced = True
        session.commit()
    made = _make_share(auth, "track", 1)
    anon = TestClient(m.app)
    lyrics = anon.get(f"/music/share/{made['token']}/lyrics/1")
    assert lyrics.status_code == 200
    assert lyrics.json() == {"track_id": 1,
                             "lyrics": "[00:01.00]第一句\n[00:05.00]第二句",
                             "lyrics_synced": True}
    assert anon.get(f"/music/share/{made['token']}/lyrics/2").status_code == 404
    assert anon.get(f"/music/share/{'0' * 32}/lyrics/1").status_code == 410


def test_share_of_emptied_playlist_reads_as_expired(auth):
    """链接还活着但列表被清空: 当作链接失效 (410), 不给一张空壳页。"""
    _seed_with_files()
    created = auth.post("/music/api/playlists",
                        json={"name": "空单"}).json()
    auth.post(f"/music/api/playlists/{created['playlist_id']}/tracks",
              json={"track_id": 1})
    made = _make_share(auth, "playlist", created["playlist_id"])
    auth.delete(f"/music/api/playlists/{created['playlist_id']}/tracks/1")

    anon = TestClient(m.app)
    assert anon.get(f"/music/share/{made['token']}/api").status_code == 410
