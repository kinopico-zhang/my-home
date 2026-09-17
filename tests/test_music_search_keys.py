"""My Music 检索键测试: 键位变体, 拼音/简繁, 旧行回填,
入库时间在重扫间的保持。"""
import os
import time


from app.music.library_database import Album, Artist, Track, session_factory
from app.music.library_scanner import backfill_legacy_rows
from app.music import library_queries
from app.music import library_search_keys
from tests.music_audio_seed import _write_audio
from tests.music_library_helpers import (_make_library, _scanner_for,
                                         _seed_library)


# ------------------------------------------------------ 检索键 / 入库时间

def test_search_key_variants():
    """纯函数: 原文/简体化/全拼/声母 + 去空格变体; 查询词简繁互换。"""
    keys = library_search_keys.search_keys("周傑倫")
    assert "周傑倫" in keys               # 原文 (小写化)
    assert "周杰伦" in keys               # 简体化 → 简体搜索词直接命中
    assert "zhoujielun" in keys           # 全拼
    assert "zjl" in keys                  # 声母
    squashed = library_search_keys.search_keys("Jay Chou")
    assert "jaychou" in squashed          # 去空格后能整词搜
    assert library_search_keys.search_keys("") == ""

    patterns = library_search_keys.query_patterns("周傑倫")
    assert patterns == ["周傑倫", "周杰伦"]     # 繁体词也带简体形态去撞键
    assert library_search_keys.query_patterns("晴天 jay") == [
        "晴天 jay", "晴天jay"]
    assert not library_search_keys.query_patterns("   ")


def _seed_search_library() -> None:
    """繁体名直插 (键齐全): 拼音/简繁互搜的目标行。"""
    with session_factory()() as session:
        artist = Artist(name="周杰倫", sort_name="", directory="周杰倫",
                        search_keys=library_search_keys.search_keys("周杰倫"))
        session.add(artist)
        session.flush()
        album = Album(title="七里香", artist_id=artist.id, year=2004,
                      directory="周杰倫/七里香",
                      search_keys=library_search_keys.search_keys(
                          "七里香", "周杰倫"))
        session.add(album)
        session.flush()
        session.add(Track(
            album_id=album.id, title="晴天", artist="周杰倫", track_number=1,
            disc_number=1, duration_seconds=269.0,
            file_path="周杰倫/七里香/01 晴天.flac", file_format="flac",
            script="Hant", lyrics="",
            search_keys=library_search_keys.search_keys(
                "晴天", "周杰倫", "七里香")))
        session.commit()


def test_search_pinyin_and_simplified_traditional(tmp_path):
    """拼音全拼/声母搜中文, 简体词搜繁体名, 原词搜简体名 (键里双向都存)。"""
    _seed_search_library()
    with session_factory()() as session:
        result = library_queries.search_library(session, "zhoujielun")
        assert [brief.name for brief in result.artists] == ["周杰倫"]
        assert [brief.name for brief in
                library_queries.search_library(
                    session, "zjl").artists] == ["周杰倫"]
        assert [brief.name for brief in
                library_queries.search_library(
                    session, "周杰伦").artists] == ["周杰倫"]   # 简查繁
        assert [brief.name for brief in
                library_queries.search_library(
                    session, "周杰倫").artists] == ["周杰倫"]   # 繁查繁
        assert [track.title for track in
                library_queries.search_library(
                    session, "qingtian").tracks] == ["晴天"]
        assert [track.title for track in
                library_queries.search_library(
                    session, "qt").tracks] == ["晴天"]
        assert [card.title for card in
                library_queries.search_library(
                    session, "qilixiang").albums] == ["七里香"]


def test_backfill_legacy_rows_fills_added_at_and_keys(tmp_path):
    """老行 (无键无入库时刻): 补数后 added_at 拿文件时间兜底, 键可拼音搜。"""
    _seed_library()
    added_at_count, key_count = backfill_legacy_rows(session_factory())
    assert (added_at_count, key_count) == (1, 5)   # 只有曲C 有文件时间
    with session_factory()() as session:
        track = session.query(Track).filter_by(title="曲C").one()
        assert track.added_at == 2000.0            # 只有文件时间可当线索
        no_mtime = session.query(Track).filter_by(title="曲A").one()
        assert no_mtime.added_at == 0.0            # 没线索的保持未知 (当最老)
        assert "quc" in track.search_keys
        artist = session.query(Artist).filter_by(name="老歌手").one()
        assert "laogeshou" in artist.search_keys
        album = session.query(Album).filter_by(title="丙").one()
        assert "bing" in album.search_keys
        result = library_queries.search_library(session, "lgs")
        assert [brief.name for brief in result.artists] == ["老歌手"]
        # 幂等: 再补一遍无事可做
        assert backfill_legacy_rows(session_factory()) == (0, 0)


def test_added_at_recorded_on_insert_preserved_on_rescan(tmp_path):
    """入库时刻只在首插记: 重扫 (mtime 都拨到未来) 不改; 新文件自己的时刻;
    专辑汇到旗下最晚。"""
    root = tmp_path / "library"
    _make_library(root)
    scanner = _scanner_for(root)
    before = time.time()
    scanner.scan()
    with session_factory()() as session:
        first = {track.file_path: track.added_at
                 for track in session.query(Track)}
        assert first and all(value >= before for value in first.values())
        for album_row in session.query(Album).all():
            track_times = [track.added_at for track in session.query(Track)
                           .filter_by(album_id=album_row.id)]
            assert album_row.added_at == max(track_times)   # 旗下最晚入库

    future = time.time() + 5000
    for flac in root.rglob("*.flac"):
        os.utime(flac, (future, future))
    scanner.scan()
    with session_factory()() as session:
        assert {track.file_path: track.added_at
                for track in session.query(Track)} == first

    _write_audio(root, "AI机组/2021 丁 [dddd4444]/01 曲E.flac",
                 {"TITLE": "曲E", "ARTIST": "AI机组", "ALBUMARTIST": "AI机组",
                  "ALBUM": "丁", "DATE": "2021"}, mtime=100.0)
    scanner.scan()
    with session_factory()() as session:
        track = session.query(Track).filter_by(title="曲E").one()
        assert track.added_at >= before
        album = session.query(Album).filter_by(title="丁").one()
        assert album.added_at == track.added_at
