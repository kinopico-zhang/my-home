"""My Music 重扫测试: 手动全量流程, 并发冲突, 自动增量重扫,
前端轮询签名。"""
import time


from app.music import service
from tests.music_static_files import music_browser_js
from tests.music_audio_seed import (PICTURE_BYTES, _write_audio,
                                    _write_plain_track)
from tests.music_library_helpers import _make_library, _wait_scan_done


def test_music_rescan_full_flow(auth, tmp_path):
    """手动重扫: 接口触发 → 后台扫 → 浏览/搜索/封面/流全链路有数据。

    分三批写文件重扫 (甲 → 乙 → 丙), 入库时间逐批变晚 → 最近添加 = 丙乙甲。"""
    root = tmp_path / "music-library"
    _write_audio(root, "AI机组/2019 甲 [aaaa1111]/01 曲A.flac",
                 {"TITLE": "曲A", "ARTIST": "AI机组", "ALBUMARTIST": "AI机组",
                  "SCRIPT": "Jpan", "ALBUM": "甲", "DATE": "2019"},
                 picture=PICTURE_BYTES, mtime=2000.0)
    assert auth.post("/music/api/rescan").json() == {"started": True}
    _wait_scan_done(auth)                              # 第一批: 甲

    _write_audio(root, "AI机组/2020 乙 [bbbb2222]/01 曲B.flac",
                 {"TITLE": "曲B", "ARTIST": "AI机组", "ALBUMARTIST": "AI机组",
                  "SCRIPT": "Jpan", "ALBUM": "乙", "DATE": "2020",
                  "LYRICS": "[00:01.00]乙の歌詞"}, mtime=3000.0)
    (root / "AI机组/poster.jpeg").write_bytes(PICTURE_BYTES)
    assert auth.post("/music/api/rescan").json() == {"started": True}
    _wait_scan_done(auth)                              # 第二批: 乙

    _write_audio(root, "老歌手/2001 丙 [cccc3333]/01 曲C.flac",
                 {"TITLE": "曲C", "ARTIST": "老歌手", "ALBUMARTIST": "老歌手",
                  "SCRIPT": "Hant", "ALBUM": "丙", "DATE": "2001"}, mtime=1000.0)
    _write_audio(root, "老歌手/2001 丙 [cccc3333]/02 曲D.flac", {}, mtime=1000.0)
    assert auth.post("/music/api/rescan").json() == {"started": True}
    _wait_scan_done(auth)                              # 第三批: 丙

    status = auth.get("/music/api/status").json()
    assert status["artist_count"] == 2 and status["album_count"] == 3
    assert status["track_count"] == 4

    albums = auth.get("/music/api/albums").json()["albums"]
    assert [album["title"] for album in albums] == ["丙", "乙", "甲"]  # 入库降序
    album_id = albums[2]["album_id"]                      # 甲 (唯一带内嵌封面)
    album_page = auth.get(f"/music/api/albums/{album_id}").json()
    assert album_page["album"]["has_artwork"]
    assert [track["title"] for track in album_page["tracks"]] == ["曲A"]

    # 语种筛选 + 搜索 (歌词命中)
    japanese = auth.get(
        "/music/api/albums", params={"language": "日文"}).json()["albums"]
    assert [album["title"] for album in japanese] == ["乙", "甲"]  # added_at 降序
    hits = auth.get("/music/api/search",
                    params={"q": "乙の"}).json()["lyric_hits"]
    assert hits and hits[0]["line_text"] == "乙の歌詞"
    tracks = auth.get("/music/api/tracks").json()["tracks"]
    assert len(tracks) == 4

    # 封面: 甲有内嵌 → 200 且字节等于 PICTURE; 乙没有 → 404
    artwork = auth.get(f"/music/media/albums/{albums[0]['album_id']}/artwork")
    assert artwork.status_code == 404               # 乙没有内嵌封面
    artwork = auth.get(f"/music/media/albums/{album_id}/artwork")
    assert artwork.status_code == 200
    assert artwork.content == PICTURE_BYTES
    assert artwork.headers["content-type"].startswith("image/jpeg")
    assert "immutable" in artwork.headers["cache-control"]

    # 艺人海报: poster.jpeg 透传
    artists = auth.get("/music/api/artists").json()["artists"]
    with_poster = next(a for a in artists if a["has_poster"])
    poster = auth.get(
        f"/music/media/artists/{with_poster['artist_id']}/artwork")
    assert poster.status_code == 200
    assert poster.content == PICTURE_BYTES

    # 流: 全量 200 + 分段 206
    track_id = album_page["tracks"][0]["track_id"]
    full = auth.get(f"/music/media/stream/{track_id}")
    assert full.status_code == 200
    assert full.headers["content-type"] == "audio/flac"
    assert full.headers["accept-ranges"] == "bytes"
    assert len(full.content) == int(full.headers["content-length"])
    probe = auth.get(f"/music/media/stream/{track_id}",
                     headers={"Range": "bytes=0-1"})
    assert probe.status_code == 206
    assert probe.content == full.content[:2]
    assert probe.headers["content-range"] == f"bytes 0-1/{len(full.content)}"
    tail = auth.get(f"/music/media/stream/{track_id}",
                    headers={"Range": "bytes=10-"})
    assert tail.status_code == 206
    assert tail.content == full.content[10:]
    assert auth.get("/music/media/stream/99999").status_code == 404
    assert auth.get(
        "/music/media/stream/99999",
        headers={"Range": "bytes=0-"}).status_code == 404


def test_music_rescan_conflict(auth, monkeypatch, tmp_path):
    """扫描进行中再触发: 409。"""
    _make_library(tmp_path / "music-library")
    current = service.scanner()
    monkeypatch.setattr(current, "scan", lambda: time.sleep(0.5))
    assert auth.post("/music/api/rescan").status_code == 200
    assert auth.post("/music/api/rescan").status_code == 409
    deadline = time.monotonic() + 5
    while service.scanner().status().running and time.monotonic() < deadline:
        time.sleep(0.02)


def test_music_scan_polling_wiring():
    """增量扫描接线: 页面 30 秒问一次状态; 在扫出进度条, 收尾动过库
    (changed) 才静默刷新, 手动触发的才出提示, 重复一轮不再响应。"""
    js = music_browser_js()
    assert "SCAN_POLL_INTERVAL_MS = 30000" in js
    assert "function checkScanStatus" in js and "function digestScanSettled" in js
    assert "lastScanSignature" in js          # finished_at+changed 签名去重
    assert "document.hidden" in js            # 后台页签不空转
    assert "userRescanPending" in js          # 手动扫完才有提示
    assert "!manual && !scan.changed" in js   # 后台扫没变化: 不打扰


# ------------------------------------------------------------ 自动重扫
# (设置/歌词 API/蜂窝流量/自定义封面的用例在 test_music_settings.py
#  和 test_music_covers.py; 这里留共享的曲库小助手)
# 封面用 PNG 魔数够了 (服务端只认魔数不解码), 字节即所传即所得


def test_auto_rescan_picks_up_new_albums(auth, tmp_path, monkeypatch):
    """自动增量重扫: 到点起一轮, 新放进曲库的专辑不用手动按扫描。"""
    root = tmp_path / "music-library"
    _write_plain_track(root, "A乐队/2001 甲 [aaaa1111]/01 曲A.flac", "曲A")
    assert auth.post("/music/api/rescan").json() == {"started": True}
    _wait_scan_done(auth)
    assert auth.get("/music/api/status").json()["track_count"] == 1

    monkeypatch.setattr(service, "_AUTO_RESCAN_SECONDS", 0.2)
    service._start_auto_rescan()                # noqa: SLF001 短间隔看门线程
    _write_plain_track(root, "B乐队/2002 乙 [bbbb2222]/01 曲B.flac", "曲B")
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if auth.get("/music/api/status").json()["track_count"] == 2:
            break
        time.sleep(0.1)
    assert auth.get("/music/api/status").json()["track_count"] == 2
