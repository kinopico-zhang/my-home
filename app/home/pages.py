"""My Home 门厅的 HTML 页面: 门厅 + 登录 (全站一张, Tesla scope 内复用)
+ 注册 + 账号管理 (静态文件在 app/home/static)。"""
from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse

from . import STATIC_DIR

router = APIRouter()


def _page(fname: str) -> FileResponse:
    """HTML 页面: 允许缓存但必须带 ETag 重新校验 (no-cache), 更新即时生效。"""
    resp = FileResponse(STATIC_DIR / fname)
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@router.get("/", response_class=HTMLResponse)
def home_page() -> FileResponse:
    """My Home 门厅: 所有应用的入口卡片 + 账号管理 (共享层, 不属于任何应用)。"""
    return _page("home.html")


@router.get("/login", response_class=HTMLResponse)
def login_page() -> FileResponse:
    """登录页 (My Home 的门, 全站唯一)。"""
    return _page("login.html")


@router.get("/tesla/login", response_class=HTMLResponse)
def tesla_login_page() -> FileResponse:
    """Tesla 应用 scope 内的登录页 (门厅那张): 会话过期 302 过来不越界。"""
    return _page("login.html")


@router.get("/register", response_class=HTMLResponse)
def register_page() -> FileResponse:
    """注册页 (凭邀请令牌进入, 无需登录)。"""
    return _page("register.html")


@router.get("/accounts")
def accounts_page() -> FileResponse:
    """账号管理页 (My Home 共享层, 仅管理员; 非管理员进来只见提示)。"""
    return _page("accounts.html")
