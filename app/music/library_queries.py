"""曲库索引的查询层: SQL → pydantic 模型 (浏览 / 搜索 / 歌词)。

路由层 (webapp.py) 只做参数解析和鉴权, 数据组装都在这里;
语种筛选统一走曲目的 script 码 (刮削标签或文字检测来的), 专辑/艺人靠
"旗下有该语种曲目" 的 EXISTS 关联。
"""
import re

from sqlalchemy import ColumnElement, exists, func, or_, select
from sqlalchemy.orm import Session

from .library_database import (BROWSER_PLAYABLE_FORMATS, Album, Artist,
                               Track)
from .library_languages import language_for_script, scripts_for_language
from .schemas import (AlbumCard, AlbumPage, AlbumPageList, ArtistBrief,
                      ArtistPage, ArtistPageList, LyricHit, LyricsResponse,
                      SearchResult, TrackBrief, TrackPageList)

# 搜索结果的板块容量 (一次全给, 前端分块展示)
SEARCH_TRACK_LIMIT = 30
SEARCH_ALBUM_LIMIT = 20
SEARCH_ARTIST_LIMIT = 15
SEARCH_LYRICS_LIMIT = 30

_LRC_TAG_PATTERN = re.compile(r"\[[^\]]*\]")    # [00:12.34] 这类标签
_LYRIC_LINE_MAX_LENGTH = 120

# 曲目排序: 最近添加的专辑在前, 专辑内按碟号/音轨号
_TRACK_ORDER = (Album.added_at.desc(), Album.id, Track.disc_number,
                Track.track_number, Track.id)


def _like_pattern(query: str) -> str:
    """搜索词 → LIKE 模式 (转义 % _ \\, 调用处要带 ESCAPE '\\')。"""
    escaped = (query.replace("\\", "\\\\").replace("%", "\\%")
               .replace("_", "\\_"))
    return f"%{escaped}%"


def _script_condition(language: str) -> ColumnElement[bool] | None:
    """语种 → 曲目 script 过滤条件 (全部/认不出 → None 不过滤)。"""
    resolved = scripts_for_language(language)
    if resolved is None:
        return None
    scripts, negate = resolved
    condition = Track.script.in_(scripts)
    return ~condition if negate else condition


def _album_language_condition(language: str) -> ColumnElement[bool] | None:
    """语种 → 专辑过滤条件 (旗下有该语种曲目才算)。"""
    script_condition = _script_condition(language)
    if script_condition is None:
        return None
    return exists(select(Track.id).where(
        Track.album_id == Album.id, script_condition))


def _artist_name_expression() -> ColumnElement[str]:
    """艺人名 (标签名空了用目录名, 兜底展示)。"""
    return func.coalesce(func.nullif(Artist.name, ""), Artist.directory)


def track_brief(track: Track, album_title: str) -> TrackBrief:
    """曲目行 → API 模型 (可播性 / 语种分组在这里定)。"""
    return TrackBrief(
        track_id=track.id, title=track.title, artist=track.artist,
        album_id=track.album_id, album_title=album_title,
        track_number=track.track_number, disc_number=track.disc_number,
        duration_seconds=track.duration_seconds,
        file_format=track.file_format,
        playable=track.file_format in BROWSER_PLAYABLE_FORMATS,
        lyrics_available=bool(track.lyrics),
        language=language_for_script(track.script))


def album_card(album: Album, artist_name: str) -> AlbumCard:
    """专辑行 → API 模型。"""
    return AlbumCard(
        album_id=album.id, title=album.title, artist_id=album.artist_id,
        artist_name=artist_name,
        year=album.year, track_count=album.track_count,
        duration_seconds=album.duration_seconds, added_at=album.added_at,
        has_artwork=album.has_artwork)


def list_albums(session: Session, language: str = "全部", sort: str = "added",
                offset: int = 0, limit: int = 60) -> AlbumPageList:
    """专辑列表 (added = 最近添加在前, title = 按标题)。"""
    condition = _album_language_condition(language)
    order = ((Album.title, Album.id) if sort == "title"
             else (Album.added_at.desc(), Album.id))
    statement = (
        select(Album, _artist_name_expression().label("artist_name"))
        .join(Artist, Album.artist_id == Artist.id)
        .order_by(*order).offset(offset).limit(limit))
    total_statement = select(func.count()).select_from(Album)
    if condition is not None:
        statement = statement.where(condition)
        total_statement = total_statement.where(condition)
    albums = [(album, artist_name) for album, artist_name in
              session.execute(statement)]
    total = session.scalar(total_statement) or 0
    return AlbumPageList(
        albums=[album_card(album, artist_name)
                for album, artist_name in albums],
        total_count=total, offset=offset, limit=limit)


def album_page(session: Session, album_id: int) -> AlbumPage | None:
    """专辑详情: 卡片 + 全部曲目 (碟号/音轨号排序)。"""
    row = session.execute(
        select(Album, _artist_name_expression().label("artist_name"))
        .join(Artist, Album.artist_id == Artist.id)
        .where(Album.id == album_id)).first()
    if row is None:
        return None
    album, artist_name = row
    tracks = session.execute(
        select(Track).where(Track.album_id == album_id)
        .order_by(Track.disc_number, Track.track_number, Track.id)).scalars()
    return AlbumPage(album=album_card(album, artist_name),
                     tracks=[track_brief(track, album.title)
                             for track in tracks])


def list_artists(session: Session, offset: int = 0,
                 limit: int = 60) -> ArtistPageList:
    """艺人列表 (排序名优先, 字母序)。"""
    name_order = func.coalesce(func.nullif(Artist.sort_name, ""),
                               Artist.name)
    statement = (select(Artist,
                        func.count(Album.id).label("album_count"),
                        func.coalesce(func.sum(Album.track_count),
                                      0).label("track_count"))
                 .outerjoin(Album, Album.artist_id == Artist.id)
                 .group_by(Artist.id).order_by(name_order, Artist.id)
                 .offset(offset).limit(limit))
    artists = [ArtistBrief(
        artist_id=artist.id, name=artist.name or artist.directory,
        album_count=album_count, track_count=track_count,
        has_poster=bool(artist.poster_file))
        for artist, album_count, track_count in session.execute(statement)]
    total = session.scalar(select(func.count()).select_from(Artist)) or 0
    return ArtistPageList(artists=artists, total_count=total,
                          offset=offset, limit=limit)


def artist_page(session: Session, artist_id: int) -> ArtistPage | None:
    """艺人详情: 卡片 + 专辑 (年份倒序)。"""
    artist = session.get(Artist, artist_id)
    if artist is None:
        return None
    brief = ArtistBrief(
        artist_id=artist.id, name=artist.name or artist.directory,
        album_count=0, track_count=0, has_poster=bool(artist.poster_file))
    albums = session.execute(
        select(Album).where(Album.artist_id == artist_id)
        .order_by(Album.year.desc(), Album.title, Album.id)).scalars()
    cards = [album_card(album, brief.name) for album in albums]
    brief.album_count = len(cards)
    brief.track_count = sum(card.track_count for card in cards)
    return ArtistPage(artist=brief, albums=cards)


def list_tracks(session: Session, language: str = "全部", offset: int = 0,
                limit: int = 100) -> TrackPageList:
    """全曲列表 (最近添加的专辑在前; 歌曲视图用, 必须分页)。"""
    condition = _script_condition(language)
    statement = (select(Track, Album.title)
                 .join(Album, Track.album_id == Album.id)
                 .order_by(*_TRACK_ORDER).offset(offset).limit(limit))
    total_statement = select(func.count()).select_from(Track)
    if condition is not None:
        statement = statement.where(condition)
        total_statement = total_statement.where(condition)
    tracks = [track_brief(track, album_title)
              for track, album_title in session.execute(statement)]
    total = session.scalar(total_statement) or 0
    return TrackPageList(tracks=tracks, total_count=total,
                         offset=offset, limit=limit)


def lyrics_for_track(session: Session, track_id: int) -> LyricsResponse | None:
    """单曲歌词原文 (前端解析时间轴)。"""
    track = session.get(Track, track_id)
    if track is None:
        return None
    return LyricsResponse(track_id=track.id, lyrics=track.lyrics,
                          lyrics_synced=track.lyrics_synced)


def _matching_lyric_line(lyrics: str, query: str) -> str:
    """歌词里第一处命中行 (剥时间轴; 大小写不敏感)。"""
    folded = query.casefold()
    for line in lyrics.splitlines():
        if folded in line.casefold():
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
    pattern = _like_pattern(query)
    script_condition = _script_condition(language)
    album_condition = _album_language_condition(language)

    track_statement = (
        select(Track, Album.title)
        .join(Album, Track.album_id == Album.id)
        .where(or_(Track.title.like(pattern, escape="\\"),
                   Track.artist.like(pattern, escape="\\")))
        .order_by(*_TRACK_ORDER).limit(SEARCH_TRACK_LIMIT))
    if script_condition is not None:
        track_statement = track_statement.where(script_condition)
    result.tracks = [track_brief(track, album_title)
                     for track, album_title in
                     session.execute(track_statement)]

    album_statement = (
        select(Album, _artist_name_expression().label("artist_name"))
        .join(Artist, Album.artist_id == Artist.id)
        .where(Album.title.like(pattern, escape="\\"))
        .order_by(Album.added_at.desc(), Album.id)
        .limit(SEARCH_ALBUM_LIMIT))
    if album_condition is not None:
        album_statement = album_statement.where(album_condition)
    result.albums = [album_card(album, artist_name)
                     for album, artist_name in
                     session.execute(album_statement)]

    result.artists = [ArtistBrief(
        artist_id=artist.id, name=artist.name or artist.directory,
        album_count=0, track_count=0, has_poster=bool(artist.poster_file))
        for artist in session.execute(
            select(Artist).where(or_(
                Artist.name.like(pattern, escape="\\"),
                Artist.sort_name.like(pattern, escape="\\"),
                Artist.directory.like(pattern, escape="\\")))
            .order_by(Artist.sort_name, Artist.id)
            .limit(SEARCH_ARTIST_LIMIT)).scalars()]

    lyric_statement = (
        select(Track, Album.title)
        .join(Album, Track.album_id == Album.id)
        .where(Track.lyrics != "",
               Track.lyrics.like(pattern, escape="\\"))
        .order_by(*_TRACK_ORDER).limit(SEARCH_LYRICS_LIMIT))
    if script_condition is not None:
        lyric_statement = lyric_statement.where(script_condition)
    result.lyric_hits = [
        LyricHit(track=track_brief(track, album_title),
                 line_text=_matching_lyric_line(track.lyrics, query))
        for track, album_title in session.execute(lyric_statement)]
    return result
