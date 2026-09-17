"""My Music 播放列表测试: 建列/加删歌, 接口 CRUD, 列表封面
与曲目封面接线。"""

import pytest

from app.music.library_database import session_factory
from app.music import library_playlists, library_queries
from tests.music_static_files import MUSIC_STATIC, music_browser_js, music_page_shell
from tests.music_library_helpers import _seed_library


def test_playlist_create_add_delete(tmp_path):
    """查询层: 列表建/加/删全在应用内; 撞名/空名报错; 同一首只留一份
    (重复行会两行一起亮播放态、连播两遍, 2026-09-15 用户点名)。"""
    _seed_library()
    with session_factory()() as session:
        created = library_playlists.create_playlist(session, " 我的日常 ")
        assert created.name == "我的日常"            # 名字收边
        assert created.is_local is True
        assert created.track_count == 0
        with pytest.raises(ValueError):              # 撞自己的名
            library_playlists.create_playlist(session, "我的日常")
        with pytest.raises(ValueError):              # 空名
            library_playlists.create_playlist(session, "  ")
        # 加歌 (种子库第一首是 曲A): 计数/时长跟着走, 详情有序
        brief = library_playlists.add_track_to_playlist(
            session, created.playlist_id, 1)
        assert brief.track_count == 1
        assert brief.duration_seconds == pytest.approx(2.0)
        with pytest.raises(ValueError, match="已经在列表里"):
            library_playlists.add_track_to_playlist(
                session, created.playlist_id, 1)     # 同首不再重复加
        page = library_queries.playlist_page(session, created.playlist_id)
        assert page is not None
        assert [t.title for t in page.tracks] == ["曲A"]
        assert page.tracks[0].artist_id == 1         # 艺人号随行走 (长按菜单用)
        with pytest.raises(KeyError):                # 曲目不在库
            library_playlists.add_track_to_playlist(
                session, created.playlist_id, 9999)
        # 移出一首 (左滑删除): 再加两首构成顺序, 抽中间那首, 首尾顺序不动
        library_playlists.add_track_to_playlist(session, created.playlist_id, 3)
        library_playlists.add_track_to_playlist(session, created.playlist_id, 5)
        brief = library_playlists.remove_track_from_playlist(
            session, created.playlist_id, 3)
        assert brief.track_count == 2
        assert brief.duration_seconds == pytest.approx(4.0)
        page = library_queries.playlist_page(session, created.playlist_id)
        assert page is not None
        assert [t.title for t in page.tracks] == ["曲A", "无题曲"]
        for bad_playlist, bad_track in ((created.playlist_id, 3), (99999, 1)):
            with pytest.raises(KeyError):         # 不在列表里 / 列表不在库
                library_playlists.remove_track_from_playlist(
                    session, bad_playlist, bad_track)
        # 列表: 连成员一起清; 再删 404 路径 (KeyError)
        library_playlists.delete_playlist(session, created.playlist_id)
        assert library_queries.playlist_page(session, created.playlist_id) is None
        with pytest.raises(KeyError):
            library_playlists.delete_playlist(session, created.playlist_id)


def test_playlist_endpoints(auth):
    """接口层: 新建/加歌/删除; 撞名 409, 不存在 404; 同步接口已撤 (404)。"""
    _seed_library()
    created = auth.post("/music/api/playlists",
                        json={"name": " 开车听 "}).json()
    assert created["name"] == "开车听"
    assert created["is_local"] is True
    assert auth.post("/music/api/playlists",
                     json={"name": "开车听"}).status_code == 409
    assert auth.post("/music/api/playlists",
                     json={"name": " "}).status_code == 409
    # 加歌 + 回读: 详情带曲目行, 行里带艺人号; 同首再加 409 (不重复入列)
    added = auth.post(f"/music/api/playlists/{created['playlist_id']}/tracks",
                      json={"track_id": 1})
    assert added.json()["track_count"] == 1
    dup = auth.post(f"/music/api/playlists/{created['playlist_id']}/tracks",
                    json={"track_id": 1})
    assert dup.status_code == 409 and "已经在列表里" in dup.json()["detail"]
    page = auth.get(f"/music/api/playlists/{created['playlist_id']}").json()
    assert [t["title"] for t in page["tracks"]] == ["曲A"]
    assert page["tracks"][0]["artist_id"] == 1
    assert auth.post(f"/music/api/playlists/{created['playlist_id']}/tracks",
                     json={"track_id": 999}).status_code == 404
    # 左滑移出一首: (曲A 已在) 再加两首抽中间, 计数回走、顺序不乱;
    # 不在列表里 404、列表不存在 404
    for track_id in (3, 5):
        assert auth.post(f"/music/api/playlists/{created['playlist_id']}/tracks",
                         json={"track_id": track_id}).status_code == 200
    removed = auth.delete(
        f"/music/api/playlists/{created['playlist_id']}/tracks/3")
    assert removed.json()["track_count"] == 2
    assert [t["title"] for t in auth.get(
        f"/music/api/playlists/{created['playlist_id']}").json()["tracks"]] \
        == ["曲A", "无题曲"]
    assert auth.delete(f"/music/api/playlists/{created['playlist_id']}"
                       "/tracks/3").status_code == 404
    assert auth.delete("/music/api/playlists/99999/tracks/1").status_code == 404
    # Plex 同步接口撤了 (路径撞详情路由, 撤后只剩 GET → 405)
    assert auth.post("/music/api/playlists/sync").status_code == 405
    # 删除: 任何列表都删得掉; 再删 404
    assert auth.delete(
        f"/music/api/playlists/{created['playlist_id']}").json() == {"ok": True}
    assert auth.get("/music/api/playlists").json()["playlists"] == []
    assert auth.delete(
        f"/music/api/playlists/{created['playlist_id']}").status_code == 404
    assert auth.get("/music/api/playlists/99999").status_code == 404


def test_music_playlist_cover_and_track_art_wiring():
    """封面接线: 详情页点大封面换图, 长按/右键弹菜单 (换/移除) + 隐藏文件选择器;
    列表行/选择单/主页播放列表带封面; 曲目行带元数据封面 (没封面给音符占位)。"""
    html = music_page_shell()
    js = music_browser_js()
    common = (MUSIC_STATIC / "js" / "music-common.js").read_text(encoding="utf-8")
    assert 'id="cover-file"' in html \
        and 'accept="image/png,image/jpeg,image/webp"' in html
    assert ".t-art" in html and ".pl-icon.art" in html           # 行样式
    assert "function uploadPlaylistCover" in js
    assert 'id="cover-tap"' in js and "function bindCoverPress" in js \
        and "openCoverMenu" in js          # 点封面直接换; 长按/右键弹封面菜单
    assert 'id="cover-menu"' in html and 'data-cover-action="change"' in html \
        and 'data-cover-action="remove"' in html \
        and 'id="cover-menu-remove"' in html                    # 菜单项 (移除可藏)
    assert "cover-hint" in html and "pl-cover-btn" in html       # 角标提示可点
    assert '`/music/api/playlists/${playlistId}/cover`' in js  # PUT/DELETE 两个口
    assert '`/music/api/playlists/${coverMenuPlaylistId}/cover`' in js  # 移除走菜单
    assert "trackArtHTML" in js and "has_artwork" in js        # 曲目封面 (含占位)
    assert 'onerror="this.replaceWith(' in js   # 封面取不到退回音符占位, 不裂图
    assert "function trackArtworkURL" in common and "artwork?v=" in common
    assert "function playlistCoverURL" in common \
        and "playlists/${playlist.playlist_id}/cover" in common
