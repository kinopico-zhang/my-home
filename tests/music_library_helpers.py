"""My Music 测试助手: 曲库播种 / 扫描器构造 / 等待扫描完成。

拆自 test_music.py (结构化重构, 代码逐字节未动)。"""
import time
from pathlib import Path


from app.music.library_database import Album, Artist, Track, session_factory
from app.music.library_scanner import LibraryScanner
from tests.music_audio_seed import (PICTURE_BYTES, _flac_bytes,
                                    _write_audio)


def _make_library(root: Path) -> None:
    """两人三张专辑: 一个带海报, 一个带封面, 一个坏文件。"""
    root.mkdir(parents=True, exist_ok=True)
    _write_audio(root, "AI机组/2019 甲 [aaaa1111]/01 曲A.flac",
                 {"TITLE": "曲A", "ARTIST": "AI机组", "ALBUMARTIST": "AI机组",
                  "SCRIPT": "Jpan", "ALBUM": "甲", "DATE": "2019",
                  "LYRICIST": "词人甲", "COMPOSER": "曲人乙"},
                 picture=PICTURE_BYTES, mtime=2000.0)
    _write_audio(root, "AI机组/2020 乙 [bbbb2222]/01 曲B.flac",
                 {"TITLE": "曲B", "ARTIST": "AI机组", "ALBUMARTIST": "AI机组",
                  "SCRIPT": "Jpan", "ALBUM": "乙", "DATE": "2020",
                  "LYRICS": "[00:01.00]乙の歌詞"},
                 mtime=3000.0)
    (root / "AI机组/poster.jpeg").write_bytes(PICTURE_BYTES)
    _write_audio(root, "老歌手/2001 丙 [cccc3333]/01 曲C.flac",
                 {"TITLE": "曲C", "ARTIST": "老歌手", "ALBUMARTIST": "老歌手",
                  "SCRIPT": "Hant", "ALBUM": "丙", "DATE": "2001"},
                 mtime=1000.0)
    _write_audio(root, "老歌手/2001 丙 [cccc3333]/02 曲D.flac", {}, mtime=1000.0)
    (root / "老歌手/notes.txt").write_text("不是音频")
    (root / ".隐藏/03 隐藏.flac").parent.mkdir(parents=True, exist_ok=True)
    (root / ".隐藏/03 隐藏.flac").write_bytes(_flac_bytes({"TITLE": "隐藏"}))


def _scanner_for(root: Path) -> LibraryScanner:
    return LibraryScanner(root, session_factory(), worker_count=2)


def _seed_library() -> None:
    """直插索引行 (查询层不走文件系统): 两艺人三专辑五曲目。"""
    with session_factory()() as session:
        ai = Artist(name="AI机组", sort_name="AI, Crew", directory="AI机组")
        old = Artist(name="老歌手", sort_name="", directory="老歌手")
        session.add_all([ai, old])
        session.flush()
        album_1 = Album(title="甲", artist_id=ai.id, year=2019,
                        directory="AI机组/甲", added_at=3000.0,
                        track_count=2, duration_seconds=4.0, has_artwork=True)
        album_2 = Album(title="乙", artist_id=ai.id, year=2020,
                        directory="AI机组/乙", added_at=1000.0,
                        track_count=1, duration_seconds=2.0, has_artwork=False)
        album_3 = Album(title="丙", artist_id=old.id, year=2001,
                        directory="老歌手/丙", added_at=2000.0,
                        track_count=2, duration_seconds=4.0, has_artwork=False)
        session.add_all([album_1, album_2, album_3])
        session.flush()
        session.add_all([
            Track(album_id=album_1.id, title="曲A", artist="AI机组",
                  track_number=1, disc_number=1, duration_seconds=2.0,
                  file_path="AI机组/甲/01.flac", file_format="flac",
                  script="Jpan", lyrics="[00:01.00]さよならの向こう",
                  lyrics_synced=True, has_artwork=True),
            Track(album_id=album_1.id, title="曲B", artist="AI机组",
                  track_number=2, disc_number=1, duration_seconds=2.0,
                  file_path="AI机组/甲/02.flac", file_format="tak",
                  script="Jpan", lyrics=""),
            Track(album_id=album_2.id, title="Hello", artist="AI机组",
                  track_number=1, disc_number=1, duration_seconds=2.0,
                  file_path="AI机组/乙/01.flac", file_format="flac",
                  script="Latn", lyrics="plain text line"),
            Track(album_id=album_3.id, title="曲C", artist="老歌手",
                  track_number=1, disc_number=2, duration_seconds=2.0,
                  file_path="老歌手/丙/01.flac", file_format="flac",
                  script="Hant", lyrics="", file_mtime=2000.0),
            Track(album_id=album_3.id, title="无题曲", artist="老歌手",
                  track_number=2, disc_number=2, duration_seconds=2.0,
                  file_path="老歌手/丙/02.flac", file_format="mp3",
                  script="", lyrics=""),
        ])
        session.commit()


def _wait_scan_done(client, timeout=10.0):
    """轮询到扫描收尾 (done/error); idle 只是还没开始, 不算失败。

    触发返回后到线程真正置起 running 之间有个窗口 (状态还是 idle),
    一进就断言会冤枉好扫描; 真没扫起来 (触发被拒) 则一直 idle 到超时。"""
    deadline = time.monotonic() + timeout
    scan = {}
    while time.monotonic() < deadline:
        scan = client.get("/music/api/status").json()["scan"]
        if not scan["running"] and scan["phase"] != "idle":
            assert scan["phase"] == "done", scan
            return
        time.sleep(0.05)
    raise AssertionError(f"扫描超时未完成: {scan}")
