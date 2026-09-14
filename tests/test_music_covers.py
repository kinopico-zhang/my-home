"""My Music 自定义封面/单曲封面测试: 播放列表封面的上传-校验-撤除-随删,
曲目元数据封面接口 (播放列表每行用) 与扫描 changed 标记,
封面抽取的各格式分支 (flac 之外: mp3 / ape 系)。"""
from mutagen.apev2 import APEBinaryValue, APEv2
from mutagen.id3 import APIC, ID3

from app.music.library_media import playlist_cover_file
from app.music.library_tags import extract_album_artwork
from tests.test_music import (PICTURE_BYTES, PNG_BYTES, _wait_scan_done,
                              _write_audio, _write_plain_track)


def test_track_artwork_extraction_formats(tmp_path):
    """封面抽取不止 FLAC: mp3 (ID3 APIC) 与 ape 系 (tak 的 Cover Art 键) 也读得出
    (B站精选里游京那批 mp3 裂图就是这么来的); 都优先正面封面,
    APE 值里 "文件名\\0图像字节" 的前缀要剥掉, 切不出图像的当没有。"""
    front = b"\xff\xd8\xff\xe0" + b"F" * 40
    back = b"\xff\xd8\xff\xe0" + b"B" * 30

    # mp3: 垫几帧静音 MPEG 头 (mutagen 只认头不解码), ID3 里前后封面都挂
    mp3_path = tmp_path / "01 游京.mp3"
    mp3_path.write_bytes((b"\xff\xfb\x90\x64" + b"\x00" * 413) * 4)
    tags = ID3()
    tags.add(APIC(encoding=3, mime="image/jpeg", type=4, desc="back",
                  data=back))
    tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="",
                  data=front))
    tags.save(mp3_path)
    assert extract_album_artwork(mp3_path) == front

    # tak (ape 系): "(Back)" 是裸图像字节, "(Front)" 带文件名前缀 —— 取正面且剥掉
    tak_path = tmp_path / "01 Cello.tak"
    tak_path.write_bytes(b"tBaK\x00\x00\x00\x00")     # 头 + 立即结束的空块
    ape = APEv2()
    ape["Cover Art (Back)"] = APEBinaryValue(back)
    ape["Cover Art (Front)"] = APEBinaryValue(b"cover.jpg\x00" + front)
    ape.save(tak_path)
    assert extract_album_artwork(tak_path) == front

    # 切不出图像的一律 None (不是图像开头又没有 \\0 分隔); 文件没了也是 None
    broken = tmp_path / "02 坏.tak"
    broken.write_bytes(b"tBaK\x00\x00\x00\x00")
    ape = APEv2()
    ape["Cover Art (Front)"] = APEBinaryValue(b"not an image")
    ape.save(broken)
    assert extract_album_artwork(broken) is None
    assert extract_album_artwork(tmp_path / "没有.mp3") is None


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
