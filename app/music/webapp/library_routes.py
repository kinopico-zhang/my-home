"""My Music 的曲库浏览与查询路由: 状态/统计/重扫 + 专辑/艺人/曲目/
播放记录/搜索/歌词/标签, 全在 /api 下 (登录用户)。"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ... import database
from ...schemas import OkResponse
from .. import library_queries, library_settings, service
from ..library_database import Album, Artist, Track, get_db
from ..schemas import (AlbumPage, AlbumPageList, ArtistPage, ArtistPageList,
                       LibraryStats, LyricsResponse,
                       MusicStatusResponse,
                       PlayRecordRequest, RecentPlaysResponse,
                       RescanResponse, SearchResult, TrackCredits,
                       TrackPageList)
from .common import _require_user, _validate_language

router = APIRouter(prefix="/api")


@router.get("/status", response_model=MusicStatusResponse)
def music_status(request: Request,
                 users: Session = Depends(database.get_users_db),
                 library: Session = Depends(get_db)) -> MusicStatusResponse:
    """扫描进度 + 库规模 (前端首屏轮询)。"""
    _require_user(request, users)
    return MusicStatusResponse(
        scan=service.scanner().status(),
        artist_count=library.scalar(
            select(func.count()).select_from(Artist)) or 0,
        album_count=library.scalar(
            select(func.count()).select_from(Album)) or 0,
        track_count=library.scalar(
            select(func.count()).select_from(Track)) or 0)


@router.get("/stats", response_model=LibraryStats)
def music_stats(request: Request,
                users: Session = Depends(database.get_users_db),
                library: Session = Depends(get_db)) -> LibraryStats:
    """统计页: 艺人/专辑/曲目数 + 总时长 + 各格式分布。"""
    _require_user(request, users)
    return library_queries.library_stats(library)


@router.post("/rescan", response_model=RescanResponse)
def music_rescan(request: Request,
                 users: Session = Depends(database.get_users_db)) -> RescanResponse:
    """手动触发重扫 (增量: 没变的文件只 stat 不读标签)。"""
    _require_user(request, users)
    if not service.trigger_scan():
        raise HTTPException(409, "扫描正在进行中")
    return RescanResponse(started=True)


@router.get("/albums", response_model=AlbumPageList)
def music_albums(
        request: Request,
        language: str = Query(default="全部"),
        sort: str = Query(default="added", pattern="^(added|title)$"),
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=60, ge=1, le=200),
        users: Session = Depends(database.get_users_db),
        library: Session = Depends(get_db)) -> AlbumPageList:
    """专辑列表 (added = 最近添加在前; language 按旗下曲目语种过滤)。"""
    _require_user(request, users)
    return library_queries.list_albums(library, _validate_language(language),
                                       sort, offset, limit)


@router.get("/albums/{album_id}", response_model=AlbumPage)
def music_album(album_id: int, request: Request,
                users: Session = Depends(database.get_users_db),
                library: Session = Depends(get_db)) -> AlbumPage:
    """专辑详情: 曲目列表 (播放从这里起)。"""
    _require_user(request, users)
    page = library_queries.album_page(library, album_id)
    if page is None:
        raise HTTPException(404, "专辑不存在")
    return page


@router.get("/artists", response_model=ArtistPageList)
def music_artists(
        request: Request,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=60, ge=1, le=200),
        users: Session = Depends(database.get_users_db),
        library: Session = Depends(get_db)) -> ArtistPageList:
    """艺人列表 (排序名优先, 字母序)。"""
    _require_user(request, users)
    return library_queries.list_artists(library, offset, limit)


@router.get("/artists/{artist_id}", response_model=ArtistPage)
def music_artist(artist_id: int, request: Request,
                 users: Session = Depends(database.get_users_db),
                 library: Session = Depends(get_db)) -> ArtistPage:
    """艺人详情: 专辑列表 (年份倒序)。"""
    _require_user(request, users)
    page = library_queries.artist_page(library, artist_id)
    if page is None:
        raise HTTPException(404, "艺人不存在")
    return page


@router.get("/tracks", response_model=TrackPageList)
def music_tracks(
        request: Request,
        language: str = Query(default="全部"),
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=300),
        users: Session = Depends(database.get_users_db),
        library: Session = Depends(get_db)) -> TrackPageList:
    """全曲列表 (最近添加的专辑在前; 歌曲视图, 无限滚动分页)。"""
    _require_user(request, users)
    return library_queries.list_tracks(library, _validate_language(language),
                                       offset, limit)


@router.post("/plays", response_model=OkResponse)
def music_record_play(body: PlayRecordRequest, request: Request,
                      users: Session = Depends(database.get_users_db),
                      library: Session = Depends(get_db)) -> OkResponse:
    """记一次播放 (最近播放的原料, 按人记; 曲目不在库里 404)。"""
    user = _require_user(request, users)
    if not library_queries.record_play(library, user.uuid, body.track_id):
        raise HTTPException(404, "曲目不存在")
    return OkResponse(ok=True)


@router.get("/plays/recent", response_model=RecentPlaysResponse)
def music_recent_plays(
        request: Request,
        limit: int = Query(default=30, ge=1, le=100),
        users: Session = Depends(database.get_users_db),
        library: Session = Depends(get_db)) -> RecentPlaysResponse:
    """本人的最近播放 (时刻倒序, 同一首只一行)。"""
    user = _require_user(request, users)
    return RecentPlaysResponse(
        tracks=library_queries.recent_plays(library, user.uuid, limit))


@router.get("/search", response_model=SearchResult)
def music_search(request: Request,
                 q: str = Query(default="", max_length=100),
                 language: str = Query(default="全部"),
                 users: Session = Depends(database.get_users_db),
                 library: Session = Depends(get_db)) -> SearchResult:
    """搜索: 歌名/艺人/专辑/歌词四板块 (歌词命中带原句)。"""
    _require_user(request, users)
    return library_queries.search_library(
        library, q, _validate_language(language))


@router.get("/tracks/{track_id}/lyrics", response_model=LyricsResponse)
def music_lyrics(track_id: int, request: Request,
                 users: Session = Depends(database.get_users_db),
                 library: Session = Depends(get_db)) -> LyricsResponse:
    """单曲歌词原文 (lrc 时间轴由前端解析)。

    库里没有时按设置联网求一遍 (求到写回索引)。"""
    _require_user(request, users)
    lyrics = library_queries.lyrics_for_track(
        library, track_id,
        library_settings.effective_lyrics_api(library))
    if lyrics is None:
        raise HTTPException(404, "曲目不存在")
    return lyrics


@router.get("/tracks/{track_id}/credits", response_model=TrackCredits)
def music_credits(track_id: int, request: Request,
                  users: Session = Depends(database.get_users_db),
                  library: Session = Depends(get_db)) -> TrackCredits:
    """单曲 作词/作曲 标签 (全屏播放页底部来源行, 按需现读文件)。"""
    _require_user(request, users)
    track_credits = library_queries.credits_for_track(library, track_id)
    if track_credits is None:
        raise HTTPException(404, "曲目不存在")
    return track_credits
