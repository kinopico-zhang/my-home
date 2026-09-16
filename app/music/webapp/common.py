"""My Music 路由层的公共底座: 应用实例 / 静态目录 / 鉴权与校验助手。

与 My Tesla 只共享账号体系: 同一枚会话 cookie + 账号库 (users.db)。
JSON 接口在 /music/api (主应用中间件统一 no-store), 媒体流在
/music/media (自带长缓存头: 封面带版本号可 immutable)。
"""
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ... import account_store
from ...models import User
from ..library_languages import LANGUAGE_FILTERS

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
HOME_STATIC_DIR = Path(__file__).resolve().parents[2] / "home" / "static"

music_app = FastAPI(title="My Music", docs_url=None, redoc_url=None,
                    openapi_url=None)
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
