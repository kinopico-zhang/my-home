"""封面应答: 专辑/单曲封面从内嵌标签抽取后缓存 (曲库本体只读),
艺人海报透传 poster.*, 播放列表自定义封面透传用户上传的原图。"""
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..library_database import (Album, Artist, Playlist, Track,
                                artwork_cache_directory, music_directory)
from ..library_tags import extract_album_artwork

_POSTER_CONTENT_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                         ".png": "image/png", ".webp": "image/webp"}
_LONG_CACHE_HEADERS = {"Cache-Control": "public, max-age=31536000, immutable"}
# 播放列表自定义封面的三种扩展名 (上传时按魔数定, 找文件时挨个试)
_COVER_EXTENSIONS = (".jpg", ".png", ".webp")


def _first_artwork_track(session: Session, album_id: int) -> Track | None:
    """专辑里第一首有内嵌封面的曲目 (碟号/音轨序)。"""
    return session.execute(
        select(Track).where(Track.album_id == album_id,
                            Track.has_artwork.is_(True))
        .order_by(Track.disc_number, Track.track_number, Track.id)
        .limit(1)).scalar_one_or_none()


def _extract_to_cache(track: Track, cache_path: Path) -> None:
    """抽曲目内嵌封面并落缓存文件 (原子替换, 抽不出抛 404)。"""
    artwork = extract_album_artwork(music_directory() / track.file_path)
    if artwork is None:
        raise HTTPException(404, "封面抽取失败")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = cache_path.with_suffix(".tmp")
    temporary_path.write_bytes(artwork)
    temporary_path.replace(cache_path)


def album_artwork_response(session: Session, album_id: int) -> Response:
    """专辑封面: 优先缓存, 失效/没有就抽一遍 (抽不出 404, 前端放占位图)。

    有效性 = 缓存文件 mtime ≥ 专辑 added_at (专辑进了新文件就重抽);
    URL 带 ?v={added_at} 作版本, 应答可长缓存。"""
    album = session.get(Album, album_id)
    if album is None:
        raise HTTPException(404, "专辑不存在")
    cache_path = artwork_cache_directory() / f"album-{album_id}.jpg"
    if not (cache_path.is_file()
            and cache_path.stat().st_mtime >= album.added_at):
        track = _first_artwork_track(session, album_id)
        if track is None:
            raise HTTPException(404, "没有封面")
        _extract_to_cache(track, cache_path)
    return FileResponse(cache_path, media_type="image/jpeg",
                        headers=_LONG_CACHE_HEADERS)


def track_artwork_response(session: Session, track_id: int) -> Response:
    """单曲自己的内嵌封面 (播放列表行用; 与专辑封面互相独立缓存)。

    有效性 = 缓存文件 mtime ≥ 曲目 file_mtime (文件换过就重抽)。"""
    track = session.get(Track, track_id)
    if track is None:
        raise HTTPException(404, "曲目不存在")
    if not track.has_artwork:
        raise HTTPException(404, "没有封面")
    cache_path = artwork_cache_directory() / f"track-{track_id}.jpg"
    if not (cache_path.is_file()
            and cache_path.stat().st_mtime >= track.file_mtime):
        _extract_to_cache(track, cache_path)
    return FileResponse(cache_path, media_type="image/jpeg",
                        headers=_LONG_CACHE_HEADERS)


def artist_artwork_response(session: Session, artist_id: int) -> Response:
    """艺人海报: 曲库里现成的 poster.* 文件, 直接透传 (没有 404)。"""
    artist = session.get(Artist, artist_id)
    if artist is None or not artist.poster_file:
        raise HTTPException(404, "没有海报")
    poster_path = (music_directory() / artist.directory
                   / artist.poster_file)
    if not poster_path.is_file():
        raise HTTPException(404, "海报文件不存在")
    media_type = _POSTER_CONTENT_TYPES.get(poster_path.suffix.lower(),
                                           "application/octet-stream")
    return FileResponse(poster_path, media_type=media_type,
                        headers=_LONG_CACHE_HEADERS)


def playlist_cover_file(playlist_id: int) -> Path | None:
    """自定义封面文件 (三种扩展名里找现存的; 没传过 None)。"""
    for extension in _COVER_EXTENSIONS:
        path = artwork_cache_directory() / f"playlist-{playlist_id}{extension}"
        if path.is_file():
            return path
    return None


def playlist_cover_response(session: Session, playlist_id: int) -> Response:
    """自定义封面透传 (?v= 版本长缓存, 换图即换址); 没传过 404。"""
    playlist = session.get(Playlist, playlist_id)
    if playlist is None:
        raise HTTPException(404, "播放列表不存在")
    if not playlist.cover_version:
        raise HTTPException(404, "没有自定义封面")
    cover_path = playlist_cover_file(playlist_id)
    if cover_path is None:
        raise HTTPException(404, "封面文件不存在")
    media_type = _POSTER_CONTENT_TYPES.get(cover_path.suffix.lower(),
                                           "application/octet-stream")
    return FileResponse(cover_path, media_type=media_type,
                        headers=_LONG_CACHE_HEADERS)
