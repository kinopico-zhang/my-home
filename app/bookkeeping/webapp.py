"""My Money (家庭记账) 的路由层 —— 独立小应用, 挂在主应用的 /bookkeeping 下。

与 My Tesla 只共享账号体系: 同一枚会话 cookie (authentication) +
同一个账号库 (account_store / users.db)。页面、静态资源、数据库、
路由都在本包; 未登录拦截在主应用中间件 (页面 302 / API 401), 这里再兜一层。
"""
from datetime import timezone
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .. import account_store, database
from ..models import User
from . import store
from .schemas import (CategoryTree, EntryOut, SyncRequest, SyncResponse)

STATIC_DIR = Path(__file__).resolve().parent / "static"

bk_app = FastAPI(title="My Money", docs_url=None, redoc_url=None,
                 openapi_url=None)
api = APIRouter(prefix="/api")


@bk_app.exception_handler(SQLAlchemyError)
async def sqlalchemy_error_handler(
        _: Request, exc: SQLAlchemyError) -> JSONResponse:
    """数据库异常统一 503 (挂载的子应用各自处理, 主应用的兜不到这里)。"""
    return JSONResponse({"detail": f"数据库查询失败: {exc}"}, status_code=503)


def _page(fname: str) -> FileResponse:
    """HTML 页面: 允许缓存但必须带 ETag 重新校验 (与主应用同一策略)。"""
    resp = FileResponse(STATIC_DIR / fname)
    resp.headers["Cache-Control"] = "no-cache"
    return resp


def _require_user(request: Request, users: Session) -> User:
    """已登录账号, 否则 401 (中间件已拦, 这里兜底)。"""
    user = account_store.user_for_cookie(request.cookies.get("auth", ""), users)
    if user is None:
        raise HTTPException(401, "未登录")
    return user


@bk_app.get("/")
def bookkeeping_page() -> FileResponse:
    """记账页: 离线优先 (本地保存, 联网同步), 多人账本。"""
    return _page("bookkeeping.html")


@api.post("/logout")
def logout() -> JSONResponse:
    """登出 (清本设备的 cookie; 与 My Tesla 是同一枚会话)。"""
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("auth", path="/tesla")   # 单用户时代的旧 path cookie
    resp.delete_cookie("auth", path="/")
    return resp


@api.get("/categories")
def bookkeeping_categories(request: Request,
                           users: Session = Depends(database.get_users_db),
                           bk: Session = Depends(store.get_db)
                           ) -> CategoryTree:
    """类别树 (挖财导入的两级类别): 支出/收入各自的大类 + 子类, 画弹层胶囊用。"""
    _require_user(request, users)
    return store.category_tree(bk)


@api.post("/sync", response_model=SyncResponse)
def bookkeeping_sync(body: SyncRequest, request: Request,
                     users: Session = Depends(database.get_users_db),
                     bk: Session = Depends(store.get_db)) -> SyncResponse:
    """同步: 上行本地改动 (LWW 合并) + 增量下发别人的改动。

    记账人 (created_by / updated_by) 由服务端按会话落, 客户端说了不算。
    """
    user = _require_user(request, users)
    try:
        rows, server_now = store.sync_entries(
            bk, user.uuid, body.entries, body.last_sync)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    names = {u.uuid: u.name for u in account_store.list_users(users)}
    entries = [EntryOut(
        id=row.id, date=row.date, time=row.time, amount=row.amount, kind=row.kind,
        category=row.category, tags=row.tags.split(",") if row.tags else [],
        note=row.note, deleted=row.deleted,
        updated_at=row.updated_at.replace(tzinfo=timezone.utc),
        created_by_name=names.get(row.created_by, "未知"),
        updated_by_name=names.get(row.updated_by, "未知")) for row in rows]
    return SyncResponse(
        server_now=server_now.replace(tzinfo=timezone.utc),
        entries=entries)


bk_app.include_router(api)
bk_app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
