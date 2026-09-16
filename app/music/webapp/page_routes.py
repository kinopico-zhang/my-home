"""My Music 的页面与会话路由: HTML 页面入口 + 更新日志数据 + 登出。

页面路由挂在应用根 (无前缀); 登出走 /api (与门厅同一枚会话 cookie)。
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from ... import database
from ...schemas import ChangelogVersion
from .. import changelog
from .common import (HOME_STATIC_DIR, STATIC_DIR, _page, _require_user)

router = APIRouter()
api_router = APIRouter(prefix="/api")


@router.get("/")
def music_page() -> FileResponse:
    """My Music 主页: 资料库 + 搜索 + 播放器 (一个页面管全部)。"""
    return _page("music.html")


@router.get("/login")
def music_login_page() -> FileResponse:
    """听歌应用 scope 内的登录页 (门厅那张): 会话过期 302 过来不越界。"""
    return _page("login.html", directory=HOME_STATIC_DIR)


@router.get("/sw.js")
def music_service_worker() -> FileResponse:
    """离线播放的 Service Worker (scope /music): 只拦曲目流, 其他走网。

    放行不需要登录 —— SW 的更新检查不带 cookie, 302 到登录页会让注册
    失败; 脚本本身没有数据。"""
    response = FileResponse(STATIC_DIR / "sw.js",
                            media_type="text/javascript")
    response.headers["Cache-Control"] = "no-cache"
    return response


@router.get("/changelog")
def music_changelog_page() -> FileResponse:
    """更新日志页 (听歌应用自己的版本线, 与 My Tesla 的日志各自独立)。"""
    return _page("changelog.html")


@router.get("/changelog/api/entries")
def music_changelog_entries(
        request: Request,
        users: Session = Depends(database.get_users_db)) -> list[ChangelogVersion]:
    """更新日志版本 (新→老), 每版是一批改动的合并。"""
    _require_user(request, users)
    return changelog.entries()


@api_router.post("/logout")
def logout() -> JSONResponse:
    """登出 (清本设备的 cookie; 与 My Home 是同一枚会话)。"""
    response = JSONResponse({"ok": True})
    response.delete_cookie("auth", path="/tesla")   # 单用户时代的旧 path cookie
    response.delete_cookie("auth", path="/")
    return response
