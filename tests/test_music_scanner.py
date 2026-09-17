"""My Music 扫描器测试: 全量/增量入库, 跳坏文件, 缺目录报错,
批量分片刷新。"""
import os

import pytest

from app.music.library_database import Album, Artist, Track, session_factory
from tests.music_audio_seed import _write_audio
from tests.music_library_helpers import _make_library, _scanner_for


# ---------------------------------------------------------------- 扫描器

def test_scanner_full_roundtrip(tmp_path):
    """首扫 → 增量跳过 → 删文件清行 → 删专辑清艺人, 汇总始终重算。"""
    root = tmp_path / "library"
    _make_library(root)
    scanner = _scanner_for(root)

    summary = scanner.scan()
    assert summary.tracks_scanned == 4          # 4 个真音频 (.txt/隐藏不算)
    assert summary.artist_count == 2 and summary.album_count == 3
    assert scanner.status().phase == "done"
    with session_factory()() as session:
        artists = {a.directory: a for a in session.query(Artist)}
        assert set(artists) == {"AI机组", "老歌手"}
        assert artists["AI机组"].name == "AI机组"
        assert artists["AI机组"].poster_file == "poster.jpeg"
        assert artists["老歌手"].poster_file == ""
        albums = {a.directory: a for a in session.query(Album)}
        assert albums["AI机组/2019 甲 [aaaa1111]"].has_artwork
        assert albums["AI机组/2019 甲 [aaaa1111]"].track_count == 1
        assert albums["老歌手/2001 丙 [cccc3333]"].track_count == 2
        # 曲D 没标签, 标题兜底成文件名
        track_d = session.query(Track).filter_by(title="曲D").one()
        assert track_d.script == "Hant"          # 检测兜底走专辑艺人名
        track_b = session.query(Track).filter_by(title="曲B").one()
        assert track_b.lyrics == "[00:01.00]乙の歌詞" and track_b.lyrics_synced

    # 二扫: mtime/size 没变, 全跳过
    summary = scanner.scan()
    assert summary.tracks_scanned == 0 and summary.tracks_skipped == 4

    # 删一首: 行没了, 专辑汇总降回 1
    (root / "老歌手/2001 丙 [cccc3333]/02 曲D.flac").unlink()
    summary = scanner.scan()
    assert summary.tracks_removed == 1
    with session_factory()() as session:
        album = session.query(Album).filter_by(
            directory="老歌手/2001 丙 [cccc3333]").one()
        assert album.track_count == 1

    # 删整张专辑 (老歌手唯一的一张): 专辑和艺人都清掉
    for path in (root / "老歌手/2001 丙 [cccc3333]").iterdir():
        path.unlink()
    (root / "老歌手/2001 丙 [cccc3333]").rmdir()
    scanner.scan()
    with session_factory()() as session:
        assert [a.directory for a in session.query(Artist)] == ["AI机组"]
        assert session.query(Album).count() == 2        # 甲 + 乙
        assert session.query(Track).count() == 2        # 曲A + 曲B


def test_scanner_skips_unreadable_and_rejects_double(tmp_path):
    """坏文件不进索引 (重试但读不出); 扫描中重复触发要拒绝。"""
    root = tmp_path / "library"
    root.mkdir()
    broken = root / "X/2000 坏 [00000000]/01 坏.flac"
    broken.parent.mkdir(parents=True)
    # 报了 100 字节的 PICTURE 却没写全 → mutagen 抛错 → 跳过
    broken.write_bytes(
        b"fLaC" + b"\x00\x00\x00\x22" + bytes(34)
        + b"\x86\x00\x00\x64" + bytes(100))
    scanner = _scanner_for(root)
    scanner.scan()
    with session_factory()() as session:
        assert session.query(Track).count() == 0
    # 非阻塞拿锁是刻意的: 验证并发第二把锁立刻报错, 没法写成 with
    assert scanner._scan_lock.acquire(  # noqa: SLF001 pylint: disable=consider-using-with
        blocking=False)
    try:
        with pytest.raises(RuntimeError):
            scanner.scan()
    finally:
        scanner._scan_lock.release()                        # noqa: SLF001


def test_scan_missing_directory_sets_error(tmp_path):
    """曲库目录没了: 异常抛出 + 状态记 error。"""
    scanner = _scanner_for(tmp_path / "nope")
    with pytest.raises(FileNotFoundError):
        scanner.scan()
    assert scanner.status().phase == "error"
    assert scanner.status().error


def test_scanner_batches_updates_and_refills(tmp_path):
    """大专辑走分批提交; 换文件走更新; 空标题/空艺人名扫完回填。"""
    from app.music import library_database as music_db
    root = tmp_path / "library"
    album_dir = "批量乐队/2017 批量 [dddd4444]"
    for index in range(1, 511):                    # 510 首, 超过提交批次 500
        _write_audio(root, f"{album_dir}/{index:03d} 曲{index}.flac",
                     {"TITLE": f"曲{index}", "ARTIST": "批量乐队",
                      "ALBUMARTIST": "批量乐队", "ALBUM": "批量",
                      "ALBUMARTISTSORT": "Batch, Band", "DATE": "2017"},
                     mtime=1000.0)
    (root / album_dir / ".DS_Store").write_bytes(b"junk")     # 隐藏文件跳过
    os.symlink(str(tmp_path / "missing.flac"),
               root / album_dir / "断链.flac")                 # 坏链接 stat 跳过
    scanner = _scanner_for(root)

    summary = scanner.scan()
    assert summary.tracks_scanned == 510 and summary.tracks_removed == 0
    assert summary.artist_count == 1 and summary.album_count == 1
    with session_factory()() as session:
        artist = session.query(Artist).one()
        assert artist.sort_name == "Batch, Band"
        assert session.query(Track).count() == 510

    # 改一个文件 (标题变 + mtime 变) → 只重读这一首, 行是更新不是新增
    _write_audio(root, f"{album_dir}/001 曲1.flac",
                 {"TITLE": "曲一改", "ARTIST": "批量乐队",
                  "ALBUMARTIST": "批量乐队", "ALBUM": "批量", "DATE": "2017"},
                 mtime=5000.0)
    summary = scanner.scan()
    assert summary.tracks_scanned == 1 and summary.tracks_skipped == 509
    with session_factory()() as session:
        assert session.query(Track).filter_by(title="曲一改").count() == 1
        assert session.query(Track).count() == 510

    # 清空专辑标题/艺人名再扫: 没变的文件不重读, 空字段从目录名回填
    with session_factory()() as session:
        session.query(Album).update({"title": ""})
        session.query(Artist).update({"name": ""})
        session.commit()
    assert scanner.scan().tracks_scanned == 0
    with session_factory()() as session:
        assert session.query(Album).one().title == "批量"
        assert session.query(Artist).one().name == "批量乐队"
    assert music_db.artwork_cache_directory().name == "music-art"
