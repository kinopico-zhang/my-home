"""My Music 的媒体流路由: 曲目音频 (Range/206) + 专辑/艺人/曲目封面 +
播放列表自定义封面, 全在 /media 下 (自带长缓存头, 登录用户)。"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ... import database
from .. import library_media
from ..library_database import get_db
from .common import _require_user

router = APIRouter(prefix="/media")


@router.get("/stream/{track_id}")
def music_stream(track_id: int, request: Request,
                 users: Session = Depends(database.get_users_db),
                 library: Session = Depends(get_db)) -> Response:
    """曲目音频流 (支持 Range/206; iOS Safari 的 <audio> 必须)。"""
    _require_user(request, users)
    return library_media.stream_track(
        library, track_id, request.headers.get("range"))


@router.get("/albums/{album_id}/artwork")
def music_album_artwork(album_id: int, request: Request,
                        users: Session = Depends(database.get_users_db),
                        library: Session = Depends(get_db)) -> Response:
    """专辑封面 (FLAC 内嵌抽取, data/music-art 缓存, ?v= 版本长缓存)。"""
    _require_user(request, users)
    return library_media.album_artwork_response(library, album_id)


@router.get("/tracks/{track_id}/artwork")
def music_track_artwork(track_id: int, request: Request,
                        users: Session = Depends(database.get_users_db),
                        library: Session = Depends(get_db)) -> Response:
    """单曲自己的内嵌封面 (播放列表里每行用各首歌的封面)。"""
    _require_user(request, users)
    return library_media.track_artwork_response(library, track_id)


@router.get("/playlists/{playlist_id}/cover")
def music_playlist_cover(playlist_id: int, request: Request,
                         users: Session = Depends(database.get_users_db),
                         library: Session = Depends(get_db)) -> Response:
    """播放列表自定义封面 (?v= 版本长缓存)。"""
    _require_user(request, users)
    return library_media.playlist_cover_response(library, playlist_id)


@router.get("/artists/{artist_id}/artwork")
def music_artist_artwork(artist_id: int, request: Request,
                         users: Session = Depends(database.get_users_db),
                         library: Session = Depends(get_db)) -> Response:
    """艺人海报 (曲库 poster.* 透传)。"""
    _require_user(request, users)
    return library_media.artist_artwork_response(library, artist_id)
