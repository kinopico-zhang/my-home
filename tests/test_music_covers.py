"""My Music 自定义封面/单曲封面测试: 播放列表封面的上传-校验-撤除-随删,
曲目元数据封面接口 (播放列表每行用) 与扫描 changed 标记。"""
from app.music.library_media import playlist_cover_file
from tests.test_music import (PICTURE_BYTES, PNG_BYTES, _wait_scan_done,
                              _write_audio, _write_plain_track)


def test_playlist_cover_endpoints(auth):
    """自定义封面: 传 PNG/JPG (魔数认类型) → 版本号递增, 媒体地址长缓存;
    撤掉回 404; 删列表连封面文件一起清。"""
    created = auth.post("/music/api/playlists",
                        json={"name": "封面列表"}).json()
    playlist_id = created["playlist_id"]
    assert created["cover_version"] == 0
    assert auth.get(f"/music/media/playlists/{playlist_id}/cover"
                    ).status_code == 404

    # 上传 PNG → v1, 媒体接口透传原字节
    put = auth.put(f"/music/api/playlists/{playlist_id}/cover",
                   content=PNG_BYTES, headers={"content-type": "image/png"})
    assert put.status_code == 200 and put.json()["cover_version"] == 1
    cover = auth.get(f"/music/media/playlists/{playlist_id}/cover")
    assert cover.status_code == 200 and cover.content == PNG_BYTES
    assert cover.headers["content-type"] == "image/png"
    assert "immutable" in cover.headers["cache-control"]

    # 换成 JPG → v2, 旧扩展名文件被清, 新字节顶上
    put = auth.put(f"/music/api/playlists/{playlist_id}/cover",
                   content=PICTURE_BYTES,
                   headers={"content-type": "image/jpeg"})
    assert put.json()["cover_version"] == 2
    cover = auth.get(f"/music/media/playlists/{playlist_id}/cover")
    assert cover.content == PICTURE_BYTES
    assert cover.headers["content-type"].startswith("image/jpeg")

    # 清单/详情都带版本号 (前端拼 ?v=)
    listing = auth.get("/music/api/playlists").json()["playlists"]
    assert listing[0]["cover_version"] == 2
    assert auth.get(
        f"/music/api/playlists/{playlist_id}").json()[
        "playlist"]["cover_version"] == 2

    # 撤掉 → v0 + 媒体 404
    cleared = auth.delete(f"/music/api/playlists/{playlist_id}/cover")
    assert cleared.json()["cover_version"] == 0
    assert auth.get(f"/music/media/playlists/{playlist_id}/cover"
                    ).status_code == 404

    # 再传一次后删列表: 封面文件跟着走
    auth.put(f"/music/api/playlists/{playlist_id}/cover",
             content=PNG_BYTES, headers={"content-type": "image/png"})
    assert playlist_cover_file(playlist_id) is not None
    assert auth.delete(f"/music/api/playlists/{playlist_id}"
                       ).json() == {"ok": True}
    assert playlist_cover_file(playlist_id) is None
    assert auth.get(f"/music/media/playlists/{playlist_id}/cover"
                    ).status_code == 404


def test_playlist_cover_validation(auth):
    """封面校验: 列表不存在 404; 类型不对 / 魔数认不出 / 超 10MB → 400。"""
    created = auth.post("/music/api/playlists", json={"name": "校验"}).json()
    playlist_id = created["playlist_id"]
    assert auth.put("/music/api/playlists/99999/cover",
                    content=PNG_BYTES,
                    headers={"content-type": "image/png"}).status_code == 404
    assert auth.delete("/music/api/playlists/99999/cover"
                       ).status_code == 404
    assert auth.put(f"/music/api/playlists/{playlist_id}/cover",
                    content=b"plain text",
                    headers={"content-type": "text/plain"}).status_code == 400
    assert auth.put(f"/music/api/playlists/{playlist_id}/cover",
                    content=b"not an image",
                    headers={"content-type": "image/png"}).status_code == 400
    assert auth.put(f"/music/api/playlists/{playlist_id}/cover",
                    content=b"x" * (10 * 1024 * 1024 + 1),
                    headers={"content-type": "image/png"}).status_code == 400
    assert auth.get(
        f"/music/media/playlists/{playlist_id}/cover").status_code == 404


def test_track_artwork_endpoint_and_changed_flag(auth, tmp_path):
    """单曲封面接口 (播放列表行用): 各首歌自己的内嵌图, 缓存命中;
    扫描状态带 changed (动过库才 True, 前端据此决定要不要刷新)。"""
    root = tmp_path / "music-library"
    _write_audio(root, "A乐队/2001 甲 [aaaa1111]/01 曲A.flac",
                 {"TITLE": "曲A", "ARTIST": "A乐队", "ALBUMARTIST": "A乐队",
                  "ALBUM": "甲", "DATE": "2001"},
                 picture=PICTURE_BYTES, mtime=1000.0)
    assert auth.post("/music/api/rescan").json() == {"started": True}
    _wait_scan_done(auth)
    assert auth.get("/music/api/status").json()["scan"]["changed"] is True

    track = auth.get("/music/api/tracks").json()["tracks"][0]
    assert track["has_artwork"] is True
    artwork = auth.get(f"/music/media/tracks/{track['track_id']}/artwork")
    assert artwork.status_code == 200
    assert artwork.content == PICTURE_BYTES
    assert artwork.headers["content-type"].startswith("image/jpeg")
    assert "immutable" in artwork.headers["cache-control"]
    # 再取一次命中缓存文件 (mtime 已不早于 file_mtime)
    assert auth.get(f"/music/media/tracks/{track['track_id']}/artwork"
                    ).content == PICTURE_BYTES

    # 没变的一轮: changed False (自动重扫没变就不打扰)
    assert auth.post("/music/api/rescan").json() == {"started": True}
    _wait_scan_done(auth)
    assert auth.get("/music/api/status").json()["scan"]["changed"] is False

    # 没内嵌封面的曲子 404; 不存在的曲目 404
    _write_plain_track(root, "A乐队/2001 甲 [aaaa1111]/02 曲B.flac", "曲B")
    assert auth.post("/music/api/rescan").json() == {"started": True}
    _wait_scan_done(auth)
    tracks = {item["title"]: item
              for item in auth.get("/music/api/tracks").json()["tracks"]}
    assert tracks["曲B"]["has_artwork"] is False
    assert auth.get(
        f"/music/media/tracks/{tracks['曲B']['track_id']}/artwork"
    ).status_code == 404
    assert auth.get("/music/media/tracks/99999/artwork").status_code == 404
