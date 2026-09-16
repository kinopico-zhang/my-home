"""My Music 的播放列表路由: 清单/详情/建删/加删歌/自定义封面, 全在
/api 下 (应用内自管, 不再与 Plex 同步)。"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ... import database
from ...schemas import OkResponse
from .. import library_playlists, library_queries
from ..library_database import get_db
from ..schemas import (PlaylistBrief, PlaylistCreateRequest,
                       PlaylistPage, PlaylistPageList,
                       PlaylistTrackRequest)
from .common import _require_user

router = APIRouter(prefix="/api")


@router.get("/playlists", response_model=PlaylistPageList)
def music_playlists(request: Request,
                    users: Session = Depends(database.get_users_db),
                    library: Session = Depends(get_db)) -> PlaylistPageList:
    """播放列表清单 (按排序位, 新建的在前)。"""
    _require_user(request, users)
    return library_queries.list_playlists(library)


@router.get("/playlists/{playlist_id}", response_model=PlaylistPage)
def music_playlist_page(request: Request,
                        playlist_id: int,
                        users: Session = Depends(database.get_users_db),
                        library: Session = Depends(get_db)) -> PlaylistPage:
    """播放列表详情: 有序曲目。"""
    _require_user(request, users)
    page = library_queries.playlist_page(library, playlist_id)
    if page is None:
        raise HTTPException(404, "没有这个播放列表")
    return page


@router.post("/playlists", response_model=PlaylistBrief)
def music_playlist_create(request: Request,
                          body: PlaylistCreateRequest,
                          users: Session = Depends(database.get_users_db),
                          library: Session = Depends(get_db)) -> PlaylistBrief:
    """新建播放列表 (应用内自管; 名字撞车 409)。"""
    _require_user(request, users)
    try:
        return library_playlists.create_playlist(library, body.name)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/playlists/{playlist_id}/tracks", response_model=PlaylistBrief)
def music_playlist_add_track(request: Request,
                             playlist_id: int,
                             body: PlaylistTrackRequest,
                             users: Session = Depends(database.get_users_db),
                             library: Session = Depends(get_db)) -> PlaylistBrief:
    """往播放列表末尾加一首 (长按曲目的「添加到播放列表」);
    已在列表里 409 (同一首只留一份)。"""
    _require_user(request, users)
    try:
        return library_playlists.add_track_to_playlist(
            library, playlist_id, body.track_id)
    except KeyError as exc:
        raise HTTPException(404, "播放列表或曲目不存在") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.delete("/playlists/{playlist_id}/tracks/{track_id}", response_model=PlaylistBrief)
def music_playlist_remove_track(request: Request,
                                playlist_id: int,
                                track_id: int,
                                users: Session = Depends(database.get_users_db),
                                library: Session = Depends(get_db)) -> PlaylistBrief:
    """从列表里移出一首 (列表页左滑删除)。"""
    _require_user(request, users)
    try:
        return library_playlists.remove_track_from_playlist(
            library, playlist_id, track_id)
    except KeyError as exc:
        raise HTTPException(404, "播放列表里没有这首歌") from exc


@router.delete("/playlists/{playlist_id}", response_model=OkResponse)
def music_playlist_delete(request: Request,
                          playlist_id: int,
                          users: Session = Depends(database.get_users_db),
                          library: Session = Depends(get_db)) -> OkResponse:
    """删掉播放列表 (连成员)。"""
    _require_user(request, users)
    try:
        library_playlists.delete_playlist(library, playlist_id)
    except KeyError as exc:
        raise HTTPException(404, "没有这个播放列表") from exc
    return OkResponse(ok=True)


@router.put("/playlists/{playlist_id}/cover", response_model=PlaylistBrief)
async def music_playlist_cover_upload(request: Request,
                                      playlist_id: int,
                                      users: Session = Depends(
                                          database.get_users_db),
                                      library: Session = Depends(
                                          get_db)) -> PlaylistBrief:
    """换播放列表自定义封面 (请求体就是图片字节, 类型看 Content-Type)。"""
    _require_user(request, users)
    data = await request.body()
    try:
        return library_playlists.set_playlist_cover(
            library, playlist_id, data,
            request.headers.get("content-type", ""))
    except KeyError as exc:
        raise HTTPException(404, "没有这个播放列表") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/playlists/{playlist_id}/cover", response_model=PlaylistBrief)
def music_playlist_cover_clear(request: Request,
                               playlist_id: int,
                               users: Session = Depends(database.get_users_db),
                               library: Session = Depends(
                                   get_db)) -> PlaylistBrief:
    """撤掉自定义封面 (列表卡片回默认的渐变音符块)。"""
    _require_user(request, users)
    try:
        return library_playlists.clear_playlist_cover(library, playlist_id)
    except KeyError as exc:
        raise HTTPException(404, "没有这个播放列表") from exc
