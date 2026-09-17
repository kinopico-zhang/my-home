"""My Music 查询测试: 专辑/艺人/曲目/歌词页, 在线歌词负缓存,
四板块搜索。"""


from app.music.library_database import Album, Artist, session_factory
from app.music import library_queries
from tests.music_library_helpers import _seed_library


# ---------------------------------------------------------------- 查询

def test_list_albums_sorts_and_filters(tmp_path):
    """added 倒序 / title 字母序; 语种按旗下曲目过滤; 分页总数对。"""
    _seed_library()
    with session_factory()() as session:
        page = library_queries.list_albums(session, sort="added")
        assert [card.title for card in page.albums] == ["甲", "丙", "乙"]
        assert page.total_count == 3
        # title 排序按码点: 丙(4E19) < 乙(4E59) < 甲(7532)
        assert [card.title for card in
                library_queries.list_albums(
                    session, sort="title").albums] == ["丙", "乙", "甲"]
        japanese = library_queries.list_albums(session, language="日文")
        assert [card.title for card in japanese.albums] == ["甲"]
        other = library_queries.list_albums(session, language="其他")
        assert [card.title for card in other.albums] == ["丙"]   # 空 script 曲目
        assert other.albums[0].artist_name == "老歌手"
        assert library_queries.list_albums(session, offset=2).albums[0] \
            .title == "乙"


def test_album_and_artist_pages(tmp_path):
    """专辑页碟/曲排序 + 可播性; 艺人页年份倒序 + 汇总。"""
    _seed_library()
    with session_factory()() as session:
        with session_factory()() as other:
            album_id = other.query(Album).filter_by(title="甲").one().id
            artist_id = other.query(Artist).filter_by(name="AI机组").one().id
        page = library_queries.album_page(session, album_id)
        assert page is not None
        assert page.album.track_count == 2
        assert [track.title for track in page.tracks] == ["曲A", "曲B"]
        assert page.tracks[0].playable and not page.tracks[1].playable  # tak
        assert page.tracks[0].lyrics_available
        assert page.tracks[0].language == "日文"
        assert library_queries.album_page(session, 99999) is None

        artist = library_queries.artist_page(session, artist_id)
        assert artist is not None
        assert [card.title for card in artist.albums] == ["乙", "甲"]  # 年份倒序
        assert artist.artist.album_count == 2
        assert artist.artist.track_count == 3
        assert library_queries.artist_page(session, 99999) is None

        artists = library_queries.list_artists(session)
        assert [brief.name for brief in artists.artists] == ["AI机组", "老歌手"]
        assert artists.artists[0].album_count == 2


def test_list_tracks_and_lyrics(tmp_path):
    """全曲列表: 最近添加的专辑在前, 专辑内按碟/曲; 歌词接口原样给。"""
    _seed_library()
    with session_factory()() as session:
        page = library_queries.list_tracks(session, limit=3)
        assert [track.title for track in page.tracks] == ["曲A", "曲B", "曲C"]
        assert page.total_count == 5
        assert page.offset == 0 and page.limit == 3
        # 语种过滤: 日文 2 首
        japanese = library_queries.list_tracks(session, language="日文")
        assert [track.title for track in japanese.tracks] == ["曲A", "曲B"]
        track_id = page.tracks[0].track_id
        lyrics = library_queries.lyrics_for_track(session, track_id)
        assert lyrics is not None
        assert lyrics.lyrics == "[00:01.00]さよならの向こう"
        assert lyrics.lyrics_synced
        assert library_queries.lyrics_for_track(session, 99999) is None


def test_lyrics_online_fetch_and_negative_cache(tmp_path, monkeypatch):
    """联网补歌词: 求到写回索引; 求不到记 24 小时负缓存 (同一首不再打外网)。"""
    _seed_library()
    library_queries.lyrics_queries._lyrics_fetch_misses.clear()   # 模块级账本, 别让别的测试留旧账
    calls = []

    def fake_fetch(api_base, title, artist, album_title):
        calls.append(title)
        return "[00:01.00]联网歌词" if title == "曲B" else ""

    monkeypatch.setattr(library_queries.lyrics_queries, "fetch_lyrics",
                        fake_fetch)
    api = (True, "https://lrc.invalid/api")
    with session_factory()() as session:
        page = library_queries.list_tracks(session, limit=10)
        ids = {track.title: track.track_id for track in page.tracks}

        # 曲B: 求到 → 写回, 之后再问直接走库 (不再打外网)
        got = library_queries.lyrics_for_track(session, ids["曲B"], api)
        assert got is not None
        assert got.lyrics == "[00:01.00]联网歌词" and got.lyrics_synced
        assert library_queries.lyrics_for_track(session, ids["曲B"], api) == got
        assert calls == ["曲B"]

        # 曲C: 求不到 → 保持空, 负缓存挡住紧跟着的再问
        miss = library_queries.lyrics_for_track(session, ids["曲C"], api)
        assert miss is not None and miss.lyrics == "" and not miss.lyrics_synced
        again = library_queries.lyrics_for_track(session, ids["曲C"], api)
        assert again is not None and again.lyrics == ""
        assert calls == ["曲B", "曲C"]


def test_search_four_boards(tmp_path):
    """搜索: 歌名/专辑/艺人/歌词四板块 + 语种过滤 + LIKE 转义。"""
    _seed_library()
    with session_factory()() as session:
        result = library_queries.search_library(session, "曲A")
        assert [track.title for track in result.tracks] == ["曲A"]
        assert result.albums == [] and result.artists == []
        # 1.8.6 数量口径: *_total = 同条件不截断的命中总数 (未截断时与
        # 列表长度一致; 页签/板块头挂它, 不再拿截断长度当命中数)
        assert result.track_total == 1 and result.album_total == 0
        assert result.artist_total == 0 and result.lyric_total == 0

        result = library_queries.search_library(session, "甲")
        assert [card.title for card in result.albums] == ["甲"]
        assert result.tracks == []

        result = library_queries.search_library(session, "AI, Crew")
        assert [brief.name for brief in result.artists] == ["AI机组"]  # 排序名命中
        # 1.8.5 修「搜艺人显示 0专辑0首歌」: 计数跟资料库艺人列表同一套聚合
        assert result.artists[0].album_count >= 1
        assert result.artists[0].track_count >= 1

        result = library_queries.search_library(session, "さよなら")
        assert len(result.lyric_hits) == 1
        assert result.lyric_hits[0].line_text == "さよならの向こう"
        assert result.lyric_hits[0].track.title == "曲A"
        assert result.lyric_total == 1

        # 语种过滤: 英文歌名在日文筛选下不出现
        assert library_queries.search_library(
            session, "hello", "日文").tracks == []
        assert library_queries.search_library(
            session, "hello").tracks[0].title == "Hello"
        # 空串: 空结果
        assert library_queries.search_library(session, "  ").tracks == []
        # 百分号不当通配符
        assert library_queries.search_library(session, "%曲%").tracks == []
