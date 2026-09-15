"""My Music 的路由层 —— 独立小应用, 挂在主应用的 /music 下。

与 My Tesla 只共享账号体系: 同一枚会话 cookie + 账号库 (users.db)。
JSON 接口在 /music/api (主应用中间件统一 no-store), 媒体流在
/music/media (自带长缓存头: 封面带版本号可 immutable)。
"""
from pathlib import Path

from fastapi import (APIRouter, Depends, FastAPI, HTTPException, Query,
                     Request)
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .. import account_store, database
from ..models import User
from ..schemas import ChangelogVersion, OkResponse
from . import (changelog, library_media, library_playlists,
               library_queries, library_settings, service)
from .library_database import (Album, Artist, Track, get_db)
from .library_languages import LANGUAGE_FILTERS
from .schemas import (AlbumPage, AlbumPageList, ArtistPage, ArtistPageList,
                      CellularUsageReport, LibraryStats, LyricsResponse,
                      MusicSettingsState, MusicSettingsUpdate,
                      MusicStatusResponse,
                      PlayRecordRequest, PlaylistBrief, PlaylistCreateRequest,
                      PlaylistPage, PlaylistPageList,
                      PlaylistTrackRequest, RecentPlaysResponse,
                      TrackCredits,
                      RescanResponse, SearchResult, TrackPageList)

STATIC_DIR = Path(__file__).resolve().parent / "static"
HOME_STATIC_DIR = Path(__file__).resolve().parents[1] / "home" / "static"

music_app = FastAPI(title="My Music", docs_url=None, redoc_url=None,
                    openapi_url=None)
api = APIRouter(prefix="/api")
media = APIRouter(prefix="/media")
music_app.include_router(api)
music_app.include_router(media)
music_app.mount("/static", StaticFiles(directory=STATIC_DIR),
                name="music-static")


@music_app.exception_handler(SQLAlchemyError)
async def sqlalchemy_error_handler(
        _: Request, exc: SQLAlchemyError) -> JSONResponse:
    """数据库异常统一 503 (挂载的子应用各自处理, 主应用的兜不到这里)。"""
    return JSONResponse({"detail": f"数据库查询失败: {exc}"}, status_code=503)


def _page(file_name: str, directory: Path | None = None) -> FileResponse:
    """HTML 页面: 允许缓存但必须带 ETag 重新校验 (与主应用同一策略)。

    目录缺省听歌应用自己的静态目录; 登录页是门厅共享层的。"""
    response = FileResponse((directory or STATIC_DIR) / file_name)
    response.headers["Cache-Control"] = "no-cache"
    return response


def _require_user(request: Request, users: Session) -> User:
    """登录校验 (中间件已拦, 这里兜底); 返回账号 (播放记录按人记)。"""
    user = account_store.user_for_cookie(
        request.cookies.get("auth", ""), users)
    if user is None:
        raise HTTPException(401, "未登录")
    return user


def _require_admin(request: Request, users: Session) -> User:
    """管理员校验 (设置改的是服务器路径, 不能人人都动)。"""
    user = _require_user(request, users)
    if user.is_admin:
        return user
    raise HTTPException(403, "仅管理员可改设置")


def _validate_language(language: str) -> str:
    """语种胶囊值校验 (前端写错立刻 422, 不静默当全部)。"""
    if language not in LANGUAGE_FILTERS:
        raise HTTPException(422, f"不认识的语种: {language}")
    return language


@music_app.get("/")
def music_page() -> FileResponse:
    """My Music 主页: 资料库 + 搜索 + 播放器 (一个页面管全部)。"""
    return _page("music.html")


@music_app.get("/login")
def music_login_page() -> FileResponse:
    """听歌应用 scope 内的登录页 (门厅那张): 会话过期 302 过来不越界。"""
    return _page("login.html", directory=HOME_STATIC_DIR)


@music_app.get("/sw.js")
def music_service_worker() -> FileResponse:
    """离线播放的 Service Worker (scope /music): 只拦曲目流, 其他走网。

    放行不需要登录 —— SW 的更新检查不带 cookie, 302 到登录页会让注册
    失败; 脚本本身没有数据。"""
    response = FileResponse(STATIC_DIR / "sw.js",
                            media_type="text/javascript")
    response.headers["Cache-Control"] = "no-cache"
    return response


@music_app.get("/changelog")
def music_changelog_page() -> FileResponse:
    """更新日志页 (听歌应用自己的版本线, 与 My Tesla 的日志各自独立)。"""
    return _page("changelog.html")


@music_app.get("/changelog/api/entries")
def music_changelog_entries(
        request: Request,
        users: Session = Depends(database.get_users_db)) -> list[ChangelogVersion]:
    """更新日志版本 (新→老), 每版是一批改动的合并。"""
    _require_user(request, users)
    return changelog.entries()


@api.post("/logout")
def logout() -> JSONResponse:
    """登出 (清本设备的 cookie; 与 My Home 是同一枚会话)。"""
    response = JSONResponse({"ok": True})
    response.delete_cookie("auth", path="/tesla")   # 单用户时代的旧 path cookie
    response.delete_cookie("auth", path="/")
    return response


@api.get("/status", response_model=MusicStatusResponse)
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


@api.get("/stats", response_model=LibraryStats)
def music_stats(request: Request,
                users: Session = Depends(database.get_users_db),
                library: Session = Depends(get_db)) -> LibraryStats:
    """统计页: 艺人/专辑/曲目数 + 总时长 + 各格式分布。"""
    _require_user(request, users)
    return library_queries.library_stats(library)


@api.post("/rescan", response_model=RescanResponse)
def music_rescan(request: Request,
                 users: Session = Depends(database.get_users_db)) -> RescanResponse:
    """手动触发重扫 (增量: 没变的文件只 stat 不读标签)。"""
    _require_user(request, users)
    if not service.trigger_scan():
        raise HTTPException(409, "扫描正在进行中")
    return RescanResponse(started=True)


# ---------------------------------------------------------------- 设置 / 流量

@api.get("/settings", response_model=MusicSettingsState)
def music_settings(request: Request,
                   users: Session = Depends(database.get_users_db),
                   library: Session = Depends(get_db)) -> MusicSettingsState:
    """设置页状态: 曲库路径 / 歌词 API 现值 + 蜂窝流量月账。

    谁登录都能看 (普通账号只读); 改要走 POST (管理员专属)。"""
    _require_user(request, users)
    return library_settings.settings_state(library)


@api.post("/settings", response_model=MusicSettingsState)
def music_settings_save(body: MusicSettingsUpdate, request: Request,
                        users: Session = Depends(database.get_users_db),
                        library: Session = Depends(get_db)) -> MusicSettingsState:
    """保存设置 (仅管理员); 曲库路径变了就同库换目录起全量重扫。"""
    _require_admin(request, users)
    try:
        new_directory = library_settings.save_settings(
            library, body.music_directory, body.lyrics_api_enabled,
            body.lyrics_api_base)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if new_directory is not None:
        service.apply_music_directory(new_directory)
    return library_settings.settings_state(library)


@api.post("/cellular-usage", response_model=OkResponse)
def music_cellular_usage(body: CellularUsageReport, request: Request,
                         users: Session = Depends(database.get_users_db),
                         library: Session = Depends(get_db)) -> OkResponse:
    """客户端报一笔蜂窝流量 (能认出蜂窝网络的浏览器定期上报, 记进当月账)。"""
    _require_user(request, users)
    library_settings.record_cellular_bytes(library, body.bytes)
    return OkResponse(ok=True)


@api.get("/playlists", response_model=PlaylistPageList)
def music_playlists(request: Request,
                    users: Session = Depends(database.get_users_db),
                    library: Session = Depends(get_db)) -> PlaylistPageList:
    """播放列表清单 (按排序位, 新建的在前)。"""
    _require_user(request, users)
    return library_queries.list_playlists(library)


@api.get("/playlists/{playlist_id}", response_model=PlaylistPage)
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


@api.post("/playlists", response_model=PlaylistBrief)
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


@api.post("/playlists/{playlist_id}/tracks", response_model=PlaylistBrief)
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


@api.delete("/playlists/{playlist_id}", response_model=OkResponse)
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


@api.put("/playlists/{playlist_id}/cover", response_model=PlaylistBrief)
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


@api.delete("/playlists/{playlist_id}/cover", response_model=PlaylistBrief)
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


@api.get("/albums", response_model=AlbumPageList)
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


@api.get("/albums/{album_id}", response_model=AlbumPage)
def music_album(album_id: int, request: Request,
                users: Session = Depends(database.get_users_db),
                library: Session = Depends(get_db)) -> AlbumPage:
    """专辑详情: 曲目列表 (播放从这里起)。"""
    _require_user(request, users)
    page = library_queries.album_page(library, album_id)
    if page is None:
        raise HTTPException(404, "专辑不存在")
    return page


@api.get("/artists", response_model=ArtistPageList)
def music_artists(
        request: Request,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=60, ge=1, le=200),
        users: Session = Depends(database.get_users_db),
        library: Session = Depends(get_db)) -> ArtistPageList:
    """艺人列表 (排序名优先, 字母序)。"""
    _require_user(request, users)
    return library_queries.list_artists(library, offset, limit)


@api.get("/artists/{artist_id}", response_model=ArtistPage)
def music_artist(artist_id: int, request: Request,
                 users: Session = Depends(database.get_users_db),
                 library: Session = Depends(get_db)) -> ArtistPage:
    """艺人详情: 专辑列表 (年份倒序)。"""
    _require_user(request, users)
    page = library_queries.artist_page(library, artist_id)
    if page is None:
        raise HTTPException(404, "艺人不存在")
    return page


@api.get("/tracks", response_model=TrackPageList)
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


@api.post("/plays", response_model=OkResponse)
def music_record_play(body: PlayRecordRequest, request: Request,
                      users: Session = Depends(database.get_users_db),
                      library: Session = Depends(get_db)) -> OkResponse:
    """记一次播放 (最近播放的原料, 按人记; 曲目不在库里 404)。"""
    user = _require_user(request, users)
    if not library_queries.record_play(library, user.uuid, body.track_id):
        raise HTTPException(404, "曲目不存在")
    return OkResponse(ok=True)


@api.get("/plays/recent", response_model=RecentPlaysResponse)
def music_recent_plays(
        request: Request,
        limit: int = Query(default=30, ge=1, le=100),
        users: Session = Depends(database.get_users_db),
        library: Session = Depends(get_db)) -> RecentPlaysResponse:
    """本人的最近播放 (时刻倒序, 同一首只一行)。"""
    user = _require_user(request, users)
    return RecentPlaysResponse(
        tracks=library_queries.recent_plays(library, user.uuid, limit))


@api.get("/search", response_model=SearchResult)
def music_search(request: Request,
                 q: str = Query(default="", max_length=100),
                 language: str = Query(default="全部"),
                 users: Session = Depends(database.get_users_db),
                 library: Session = Depends(get_db)) -> SearchResult:
    """搜索: 歌名/艺人/专辑/歌词四板块 (歌词命中带原句)。"""
    _require_user(request, users)
    return library_queries.search_library(
        library, q, _validate_language(language))


@api.get("/tracks/{track_id}/lyrics", response_model=LyricsResponse)
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


@api.get("/tracks/{track_id}/credits", response_model=TrackCredits)
def music_credits(track_id: int, request: Request,
                  users: Session = Depends(database.get_users_db),
                  library: Session = Depends(get_db)) -> TrackCredits:
    """单曲 作词/作曲 标签 (全屏播放页底部来源行, 按需现读文件)。"""
    _require_user(request, users)
    track_credits = library_queries.credits_for_track(library, track_id)
    if track_credits is None:
        raise HTTPException(404, "曲目不存在")
    return track_credits


@media.get("/stream/{track_id}")
def music_stream(track_id: int, request: Request,
                 users: Session = Depends(database.get_users_db),
                 library: Session = Depends(get_db)) -> Response:
    """曲目音频流 (支持 Range/206; iOS Safari 的 <audio> 必须)。"""
    _require_user(request, users)
    return library_media.stream_track(
        library, track_id, request.headers.get("range"))


@media.get("/albums/{album_id}/artwork")
def music_album_artwork(album_id: int, request: Request,
                        users: Session = Depends(database.get_users_db),
                        library: Session = Depends(get_db)) -> Response:
    """专辑封面 (FLAC 内嵌抽取, data/music-art 缓存, ?v= 版本长缓存)。"""
    _require_user(request, users)
    return library_media.album_artwork_response(library, album_id)


@media.get("/tracks/{track_id}/artwork")
def music_track_artwork(track_id: int, request: Request,
                        users: Session = Depends(database.get_users_db),
                        library: Session = Depends(get_db)) -> Response:
    """单曲自己的内嵌封面 (播放列表里每行用各首歌的封面)。"""
    _require_user(request, users)
    return library_media.track_artwork_response(library, track_id)


@media.get("/playlists/{playlist_id}/cover")
def music_playlist_cover(playlist_id: int, request: Request,
                         users: Session = Depends(database.get_users_db),
                         library: Session = Depends(get_db)) -> Response:
    """播放列表自定义封面 (?v= 版本长缓存)。"""
    _require_user(request, users)
    return library_media.playlist_cover_response(library, playlist_id)


@media.get("/artists/{artist_id}/artwork")
def music_artist_artwork(artist_id: int, request: Request,
                         users: Session = Depends(database.get_users_db),
                         library: Session = Depends(get_db)) -> Response:
    """艺人海报 (曲库 poster.* 透传)。"""
    _require_user(request, users)
    return library_media.artist_artwork_response(library, artist_id)
