"""搜索查询: 歌名/艺人/专辑/歌词四个板块, 同一词可多板块命中。"""
import re
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from ..library_database import Album, Artist, Track
from ..library_search_keys import query_patterns
from ..schemas import ArtistBrief, LyricHit, SearchResult
from .browse_queries import album_card, track_brief
from .query_conditions import (_TRACK_ORDER, _album_language_condition,
                               _any_like, _artist_name_expression,
                               _like_patterns, _script_condition, _text_match)

# 搜索结果的板块容量 (一次全给, 前端分块展示)。命中超出时板块头仍报真实
# 总数、列表尾注明「已显示前 N」(1.8.6 修「艺人行 64 专辑, 专辑板块只有
# 20 张」的口径不一致 —— 容量只管列表, 不管报数)
SEARCH_TRACK_LIMIT = 100
SEARCH_ALBUM_LIMIT = 100
SEARCH_ARTIST_LIMIT = 50
SEARCH_LYRICS_LIMIT = 100


def _total(session: Session, statement: Select[Any]) -> int:
    """同条件不截断的命中总数 (子查询套一层 COUNT, 条件与取数零重复)。"""
    return session.execute(
        select(func.count()).select_from(statement.subquery())).scalar_one()

_LRC_TAG_PATTERN = re.compile(r"\[[^\]]*\]")    # [00:12.34] 这类标签
_LYRIC_LINE_MAX_LENGTH = 120


def _matching_lyric_line(lyrics: str, query: str) -> str:
    """歌词里第一处命中行 (剥时间轴; 大小写不敏感 + 简体化互搜)。"""
    folded_variants = query_patterns(query)
    for line in lyrics.splitlines():
        line_folded = line.casefold()
        if any(variant in line_folded for variant in folded_variants):
            text = _LRC_TAG_PATTERN.sub("", line).strip()
            return text[:_LYRIC_LINE_MAX_LENGTH]
    return ""


def search_library(session: Session, query: str,
                   language: str = "全部") -> SearchResult:
    """搜索: 歌名/艺人/专辑/歌词四个板块, 同一词可多板块命中。"""
    query = query.strip()
    result = SearchResult(query=query, language=language)
    if not query:
        return result
    patterns = _like_patterns(query)
    script_condition = _script_condition(language)
    album_condition = _album_language_condition(language)

    track_statement = (
        select(Track, Album.title, Album.artist_id)
        .join(Album, Track.album_id == Album.id)
        .where(_text_match(Track.search_keys, Track.title, Track.artist,
                           patterns=patterns))
        .order_by(*_TRACK_ORDER))
    if script_condition is not None:
        track_statement = track_statement.where(script_condition)
    result.track_total = _total(session, track_statement)
    result.tracks = [track_brief(track, album_title, artist_id)
                     for track, album_title, artist_id in
                     session.execute(track_statement.limit(SEARCH_TRACK_LIMIT))]

    album_statement = (
        select(Album, _artist_name_expression().label("artist_name"))
        .join(Artist, Album.artist_id == Artist.id)
        .where(_text_match(Album.search_keys, Album.title, patterns=patterns))
        .order_by(Album.added_at.desc(), Album.id))
    if album_condition is not None:
        album_statement = album_statement.where(album_condition)
    result.album_total = _total(session, album_statement)
    result.albums = [album_card(album, artist_name)
                     for album, artist_name in
                     session.execute(album_statement.limit(SEARCH_ALBUM_LIMIT))]

    # 艺人板块带专辑/歌曲计数 (1.8.5 修「搜艺人显示 0专辑0首歌」):
    # 与资料库艺人列表同一套聚合 (outerjoin 计专辑数, 专辑曲目数求和)
    artist_statement = (
        select(Artist,
               func.count(Album.id).label("album_count"),
               func.coalesce(func.sum(Album.track_count),
                             0).label("track_count"))
        .outerjoin(Album, Album.artist_id == Artist.id)
        .where(_text_match(Artist.search_keys, Artist.name,
                           Artist.sort_name, Artist.directory,
                           patterns=patterns))
        .group_by(Artist.id)
        .order_by(Artist.sort_name, Artist.id))
    result.artist_total = _total(session, artist_statement)
    result.artists = [ArtistBrief(
        artist_id=artist.id, name=artist.name or artist.directory,
        album_count=album_count, track_count=track_count,
        has_poster=bool(artist.poster_file))
        for artist, album_count, track_count
        in session.execute(artist_statement.limit(SEARCH_ARTIST_LIMIT))]

    lyric_statement = (
        select(Track, Album.title, Album.artist_id)
        .join(Album, Track.album_id == Album.id)
        .where(Track.lyrics != "",
               _any_like(Track.lyrics, patterns))
        .order_by(*_TRACK_ORDER))
    if script_condition is not None:
        lyric_statement = lyric_statement.where(script_condition)
    result.lyric_total = _total(session, lyric_statement)
    result.lyric_hits = [
        LyricHit(track=track_brief(track, album_title, artist_id),
                 line_text=_matching_lyric_line(track.lyrics, query))
        for track, album_title, artist_id
        in session.execute(lyric_statement.limit(SEARCH_LYRICS_LIMIT))]
    return result
