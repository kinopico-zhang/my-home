"""浏览域查询: 专辑/艺人/曲目的列表与详情 + 行模型组装 + 库统计。"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..library_database import (BROWSER_PLAYABLE_FORMATS, Album, Artist,
                                Track)
from ..library_languages import language_for_script
from ..schemas import (AlbumCard, AlbumPage, AlbumPageList, ArtistBrief,
                       ArtistPage, ArtistPageList, FormatCount, LibraryStats,
                       TrackBrief, TrackPageList)
from .query_conditions import (_TRACK_ORDER, _album_language_condition,
                               _artist_name_expression, _script_condition)


def track_brief(track: Track, album_title: str,
                artist_id: int = 0) -> TrackBrief:
    """曲目行 → API 模型 (可播性 / 语种分组在这里定)。

    artist_id 是专辑的艺人 (长按菜单「进入艺人主页」用; 默认 0 = 不给)。"""
    return TrackBrief(
        track_id=track.id, title=track.title, artist=track.artist,
        album_id=track.album_id, album_title=album_title, artist_id=artist_id,
        track_number=track.track_number, disc_number=track.disc_number,
        duration_seconds=track.duration_seconds,
        file_format=track.file_format,
        playable=track.file_format in BROWSER_PLAYABLE_FORMATS,
        lyrics_available=bool(track.lyrics),
        has_artwork=track.has_artwork,
        mtime=track.file_mtime,
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
    albums = list(session.execute(statement))
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
                     tracks=[track_brief(track, album.title, album.artist_id)
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
    statement = (select(Track, Album.title, Album.artist_id)
                 .join(Album, Track.album_id == Album.id)
                 .order_by(*_TRACK_ORDER).offset(offset).limit(limit))
    total_statement = select(func.count()).select_from(Track)
    if condition is not None:
        statement = statement.where(condition)
        total_statement = total_statement.where(condition)
    tracks = [track_brief(track, album_title, artist_id)
              for track, album_title, artist_id
              in session.execute(statement)]
    total = session.scalar(total_statement) or 0
    return TrackPageList(tracks=tracks, total_count=total,
                         offset=offset, limit=limit)


def library_stats(session: Session) -> LibraryStats:
    """统计页: 艺人/专辑/曲目数 + 总时长 + 各格式分布 (多的在前, 同数按名)。"""
    formats = [FormatCount(format=name, count=count,
                           playable=name in BROWSER_PLAYABLE_FORMATS)
               for name, count in session.execute(
                   select(Track.file_format, func.count())
                   .group_by(Track.file_format)
                   .order_by(func.count().desc(), Track.file_format))]
    return LibraryStats(
        artist_count=session.scalar(
            select(func.count()).select_from(Artist)) or 0,
        album_count=session.scalar(
            select(func.count()).select_from(Album)) or 0,
        track_count=session.scalar(
            select(func.count()).select_from(Track)) or 0,
        total_duration_seconds=session.scalar(
            select(func.sum(Track.duration_seconds))) or 0.0,
        formats=formats)
