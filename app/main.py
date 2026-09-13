"""My Tesla —— API 路由层 (薄)。

数据源: teslamate_cn (PostgreSQL, TeslaMate 标准表结构), 查询全部在
repository 层 (SQLAlchemy, 方言中立); 测试通过 database.init_engine()
注入 SQLite, 不碰真实库。
时间处理: 库内为 UTC 裸时间戳, 对外输出本地时间 (默认 Asia/Shanghai)。
鉴权: 登录后签发 HMAC 签名的会话 cookie (默认 90 天), 未登录跳转 /tesla/login。
"""
import json
import math
import re
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Awaitable, Callable, Iterator

from fastapi import (APIRouter, Depends, FastAPI, HTTPException, Query,
                     Request, Response)
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               RedirectResponse, StreamingResponse)
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from . import (account_store, authentication, changelog,
                config, database, repository, settings_store, tracks_cache)
from .bookkeeping import store as bookkeeping_store, webapp
from .home import STATIC_DIR as HOME_STATIC_DIR
from . import models
from .models import OwnBase, User
from .schemas import (
    AmapConfig,
    CarInfo,
    ChargeDims,
    ChargeMapLocation,
    ChangelogItem,
    ChangelogVersion,
    ChargingSessionDetail,
    ChargingSessionsPage,
    ChargingSummary,
    AccountNameUpdate,
    AccountPasswordUpdate,
    CostUpdateRequest,
    CostUpdateResult,
    DriverIn,
    DriverInfo,
    DriverMark,
    DriverUpdate,
    InvitationCreated,
    InvitationItem,
    InvitationRequest,
    MeInfo,
    RegisterCredentials,
    UserItem,
    GapFillRequest,
    GapFillResponse,
    LocationStat,
    LiveStatus,
    LoginCredentials,
    MapSummary,
    MergedTrack,
    MonthlyStat,
    OkResponse,
    RegionNode,
    SettingsState,
    SettingsUpdate,
    TracksDetailResponse,
    TracksResponse,
    TripItem,
    TripGroupInfo,
    TripGroupIn,
    TripGroupRename,
    TripTollIn,
    TripRegions,
    TripTrack,
    TripsPage,
)

# 充电页面 API (页面: /tesla/charging)
charging = APIRouter(prefix="/tesla/charging/api")
# 足迹地图 API (页面: /tesla/map)
mapapi = APIRouter(prefix="/tesla/map/api")
# 行程轨迹 API (页面: /tesla/trips —— 行程卡片瀑布流 + 点击查看单条全精度轨迹)
trips = APIRouter(prefix="/tesla/trips/api")
# 当前驾驶 API (页面: /tesla/live —— 未结束行程的实时状态)
live = APIRouter(prefix="/tesla/live/api")
# 设置 API (页面: /tesla/settings —— TeslaMate 连接 / 高德 Key / 驾驶员)
settingsapi = APIRouter(prefix="/tesla/api")
changelogapi = APIRouter(prefix="/tesla/changelog/api")
# 账号管理 API (页面: /accounts, 仅管理员)
accounts = APIRouter(prefix="/accounts/api")


def _migrate_own_db() -> None:
    """create_all 只建新表不改旧表: 已有生产库要补的列写在这里 (幂等)。"""
    with database.own_engine().begin() as conn:
        cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(app_settings)")}
        if "amap_style" not in cols:   # v: 高德地图样式 (设置页可换, 三页地图共用)
            conn.exec_driver_sql(
                "ALTER TABLE app_settings ADD COLUMN amap_style TEXT NOT NULL DEFAULT ''")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """启动时建引擎 + 后台预热缓存, 关闭时释放连接池。

    自有库 (SQLite) 的表由应用自己建 (create_all), 与 TeslaMate
    原库 (迁移建的表, 只读) 完全隔离。"""
    # 先建自有库再读设置: TeslaMate 连接可被设置页覆盖 (未设回落 env 定位)
    database.init_own_engine()
    OwnBase.metadata.create_all(database.own_engine())
    _migrate_own_db()
    # 账号库 (独立文件): 首启种管理员 (env 账密, 之后走界面改);
    # 记账库 (独立文件) 只建表
    database.init_users_engine()
    models.UsersBase.metadata.create_all(database.users_engine())
    with database.users_session_factory()() as users:
        account_store.ensure_admin(users, config.AUTH_USER, config.AUTH_PASS)
    bookkeeping_store.init_engine()      # 记账库 (独立文件, 独立应用)
    bookkeeping_store.create_all()
    bookkeeping_store.seed_default_categories()   # 类别树 (空库才种, 挖财导入)
    with database.own_session_factory()() as own:   # pylint: disable=not-callable
        url = settings_store.engine_url(own)
    database.init_engine(url)
    # 后台预热轨迹缓存 (全量下采样 ~15s, 不阻塞启动)
    threading.Thread(target=tracks_cache.warm,
                     args=(database.session_factory(),), daemon=True).start()
    yield
    database.dispose_engine()
    database.dispose_own_engine()
    database.dispose_users_engine()
    bookkeeping_store.dispose_engine()


app = FastAPI(title="My Tesla", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=2048)   # 轨迹 JSON 压缩 ~5x


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_error_handler(
        _: Request, exc: SQLAlchemyError) -> JSONResponse:
    """数据库异常统一 503 (与旧版 query() 包装行为一致)。"""
    return JSONResponse({"detail": f"数据库查询失败: {exc}"}, status_code=503)


# 无需登录即可访问的路径: 登录/注册页及其接口 (邀请令牌本身就是凭证);
# 登出只清 cookie, 不需要有效会话
_PUBLIC_PATHS = frozenset((
    "/login", "/register",
    "/api/login", "/api/logout",
    "/api/register", "/api/invite-status",
    "/bookkeeping/api/logout"))
_STATIC_PREFIXES = ("/static/", "/tesla/static/", "/bookkeeping/static/")

# 账号体系从 /tesla 搬到根路径 (账号属于 My Home, 不属于任何一个应用);
# 旧地址 302/307 兼容 —— 手机上的老书签和已经发出去的邀请链接还能用
_MOVED_PAGES = {
    "/tesla/login": "/login",
    "/tesla/register": "/register",
    "/tesla/accounts": "/accounts",
}
_MOVED_APIS = {
    "/tesla/api/login": "/api/login",
    "/tesla/api/logout": "/api/logout",
    "/tesla/api/register": "/api/register",
    "/tesla/api/invite-status": "/api/invite-status",
    "/tesla/api/me": "/api/me",
    "/tesla/api/account/name": "/api/account/name",
    "/tesla/api/account/password": "/api/account/password",
}


def _moved_target(path: str) -> str | None:
    """旧地址 → 新地址 (没搬过的返回 None); 查询串由中间件续上。"""
    new = _MOVED_PAGES.get(path) or _MOVED_APIS.get(path)
    if new is None and path.startswith("/tesla/accounts/api/"):
        new = "/accounts/api/" + path[len("/tesla/accounts/api/"):]
    return new


def _is_protected(path: str) -> bool:
    """保护面: 门厅 (/) + 两个应用 + 账号管理页 + 账号接口 (me / 自助改)。"""
    if path == "/" or path.startswith(("/tesla", "/bookkeeping", "/accounts")):
        return True
    return path == "/api/me" or path.startswith("/api/account/")


@app.middleware("http")
async def auth_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """旧地址搬家重定向; 页面未登录跳登录页, API 未登录 401; 静态放行 + 缓存策略。

    My Home (根路径) 是共享层: 账号体系 + 两个应用 (My Tesla / My Money),
    同一枚会话 cookie (path=/)。"""
    path = request.url.path
    moved = _moved_target(path)
    if moved is not None:
        if request.url.query:
            moved += "?" + request.url.query
        # 接口用 307 保住方法与请求体, 页面 302 即可
        api_move = moved.startswith(("/api/", "/accounts/api/"))
        return RedirectResponse(moved, status_code=307 if api_move else 302)
    token_ok = authentication.check_token(request.cookies.get("auth", ""))
    protected = _is_protected(path)
    is_api = protected and "/api/" in path
    if path == "/login" and token_ok:
        # 已登录的访客不再看表单, 直接进门厅
        resp = RedirectResponse("/", status_code=302)
    elif path in _PUBLIC_PATHS or path.startswith(_STATIC_PREFIXES):
        resp = await call_next(request)
    elif is_api and not token_ok:
        resp = JSONResponse({"detail": "未登录"}, status_code=401)
    elif protected and not is_api and not token_ok:
        resp = RedirectResponse("/login", status_code=302)
    else:
        resp = await call_next(request)
    if is_api:
        # API 数据 (如 map config) 禁止缓存, 否则配置更新后浏览器仍用旧响应
        resp.headers["Cache-Control"] = "no-store"
    elif path.startswith(_STATIC_PREFIXES):
        # JS 工具 (trackutil 等) 迭代频繁, 必须重新校验; ETag 命中时 304 很便宜。
        # 只发 Last-Modified 时浏览器走启发式缓存, 会继续用旧 JS (动画因此冻住过)。
        resp.headers["Cache-Control"] = "no-cache"
    return resp


def _page(fname: str, directory=None) -> FileResponse:
    """HTML 页面: 允许缓存但必须带 ETag 重新校验 (no-cache), 更新即时生效。

    目录缺省 My Tesla 的静态目录; 门厅/登录/注册/账号管理在 home 共享层。"""
    resp = FileResponse((directory or config.STATIC_DIR) / fname)
    resp.headers["Cache-Control"] = "no-cache"
    return resp


def _date_range_or_400(frm: str | None,
                       to: str | None) -> repository.DateRange | None:
    """from/to (本地日期) → 库内 UTC 边界; 坏参数直接 400。"""
    try:
        return repository.parse_date_range(frm, to)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


# --------------------------------------------- My Home 门厅 / 登录 / 登出

@app.get("/", response_class=HTMLResponse)
def home_page() -> FileResponse:
    """My Home 门厅: 所有应用的入口卡片 + 账号管理 (共享层, 不属于任何应用)。"""
    return _page("home.html", directory=HOME_STATIC_DIR)


@app.get("/login", response_class=HTMLResponse)
def login_page() -> FileResponse:
    """登录页 (My Home 的门, 全站唯一)。"""
    return _page("login.html", directory=HOME_STATIC_DIR)


def _set_session_cookie(resp: JSONResponse, user_uuid: str) -> None:
    """会话 cookie 签到 path=/ (门厅 + 两个应用全站通用)。

    单用户时代的旧 cookie path 限定 /tesla, 同名残留会让浏览器在 /tesla
    下优先送旧值 —— 设置新 cookie 前先删掉它。"""
    resp.delete_cookie("auth", path="/tesla")
    resp.set_cookie("auth", authentication.make_token(user_uuid),
                    max_age=config.SESSION_DAYS * 86400, httponly=True,
                    samesite="lax", path="/")


@app.post("/api/login")
def login(creds: LoginCredentials, request: Request,
          users: Session = Depends(database.get_users_db)) -> JSONResponse:
    """校验账密 (账号库, 带单 IP 限速), 签发会话 cookie。"""
    ip = request.client.host if request.client else "?"
    if authentication.ip_locked(ip):
        raise HTTPException(
            429, f"尝试次数过多, 请 {config.LOGIN_LOCK_S} 秒后再试")
    user = account_store.authenticate(users, creds.user, creds.password)
    if user is None:
        authentication.record_fail(ip)
        raise HTTPException(401, "账号或密码错误")
    authentication.clear_fails(ip)
    resp = JSONResponse(OkResponse(ok=True).model_dump())
    _set_session_cookie(resp, user.uuid)
    return resp


@app.post("/api/logout")
def logout() -> JSONResponse:
    """登出 (清本设备的 cookie; 其他设备/其他人不受影响)。"""
    resp = JSONResponse(OkResponse(ok=True).model_dump())
    resp.delete_cookie("auth", path="/tesla")   # 单用户时代的旧 path cookie
    resp.delete_cookie("auth", path="/")
    return resp


def _current_user(request: Request, users: Session) -> User | None:
    """会话 cookie → 账号 (逻辑在账号库, 记账应用共用)。"""
    return account_store.user_for_cookie(request.cookies.get("auth", ""), users)


def _require_user(request: Request, users: Session) -> User:
    """已登录账号, 否则 401。"""
    user = _current_user(request, users)
    if user is None:
        raise HTTPException(401, "未登录")
    return user


def _require_admin(request: Request, users: Session) -> User:
    """管理员账号, 否则 401/403 (账号管理只有管理员能碰)。"""
    user = _require_user(request, users)
    if not user.is_admin:
        raise HTTPException(403, "仅管理员可管理账号")
    return user


@app.get("/register")
def register_page() -> FileResponse:
    """注册页 (凭邀请令牌进入, 无需登录)。"""
    return _page("register.html", directory=HOME_STATIC_DIR)


@app.get("/api/invite-status")
def invite_status(invite: str,
                  users: Session = Depends(database.get_users_db)) -> OkResponse:
    """邀请令牌是否可用 (注册页进页即查, 坏链接直接说原因)。"""
    try:
        account_store.invitation_usable(users, invite)
    except account_store.InvitationError as exc:
        raise HTTPException(400, str(exc)) from exc
    return OkResponse(ok=True)


@app.post("/api/register")
def register(creds: RegisterCredentials, request: Request,
             users: Session = Depends(database.get_users_db)) -> JSONResponse:
    """凭邀请注册账号 (一次一用), 注册即登录。"""
    ip = request.client.host if request.client else "?"
    if authentication.ip_locked(ip):
        raise HTTPException(
            429, f"尝试次数过多, 请 {config.LOGIN_LOCK_S} 秒后再试")
    try:
        account_store.invitation_usable(users, creds.invite)
        user = account_store.create_user(users, creds.name, creds.password)
        account_store.consume_invitation(users, creds.invite)
    except (account_store.NameError_, account_store.PasswordError,
            account_store.InvitationError) as exc:
        raise HTTPException(400, str(exc)) from exc
    authentication.clear_fails(ip)
    resp = JSONResponse(OkResponse(ok=True).model_dump())
    _set_session_cookie(resp, user.uuid)
    return resp


@app.get("/api/me", response_model=MeInfo)
def me(request: Request,
       users: Session = Depends(database.get_users_db)) -> MeInfo:
    """当前会话账号 (名称 + 是否管理员; uuid 不出接口)。"""
    user = _require_user(request, users)
    return MeInfo(name=user.name, is_admin=user.is_admin)


@app.post("/api/account/name", response_model=MeInfo)
def account_change_name(body: AccountNameUpdate, request: Request,
                        users: Session = Depends(database.get_users_db)) -> MeInfo:
    """自助改登录名 (uuid 不变, 会话不掉线)。"""
    user = _require_user(request, users)
    try:
        account_store.rename_user(users, user, body.name)
    except account_store.NameError_ as exc:
        raise HTTPException(400, str(exc)) from exc
    return MeInfo(name=user.name, is_admin=user.is_admin)


@app.post("/api/account/password", response_model=OkResponse)
def account_change_password(body: AccountPasswordUpdate, request: Request,
                            users: Session = Depends(database.get_users_db)) -> OkResponse:
    """自助改密码 (先验旧密码; 会话不受影响)。"""
    user = _require_user(request, users)
    try:
        account_store.set_password(users, user,
                                   body.old_password, body.new_password)
    except account_store.PasswordError as exc:
        raise HTTPException(400, str(exc)) from exc
    return OkResponse(ok=True)


# ---------------------------------------------------------------- 账号管理 API

@accounts.get("/users", response_model=list[UserItem])
def accounts_list_users(request: Request,
                        users: Session = Depends(database.get_users_db)) -> list[UserItem]:
    """账号列表 (仅管理员; uuid 不出接口)。"""
    _require_admin(request, users)
    return [UserItem(name=u.name, is_admin=u.is_admin,
                     created_at=repository.to_local(u.created_at))
            for u in account_store.list_users(users)]


@accounts.post("/invitations", response_model=InvitationCreated)
def accounts_create_invitation(body: InvitationRequest, request: Request,
                               users: Session = Depends(database.get_users_db)) -> InvitationCreated:
    """签发注册邀请 (仅管理员; 前端拼 /register?invite= 链接分享)。"""
    _require_admin(request, users)
    try:
        invitation = account_store.create_invitation(users, body.days)
    except account_store.InvitationError as exc:
        raise HTTPException(400, str(exc)) from exc
    return InvitationCreated(token=invitation.token,
                             expires_at=repository.to_local(invitation.expires_at))


@accounts.get("/invitations", response_model=list[InvitationItem])
def accounts_list_invitations(request: Request,
                              users: Session = Depends(database.get_users_db)) -> list[InvitationItem]:
    """邀请列表 (仅管理员, 签发时间倒序)。"""
    _require_admin(request, users)
    return [InvitationItem(token=i.token, created_at=repository.to_local(i.created_at),
                           expires_at=repository.to_local(i.expires_at),
                           used_at=repository.to_local(i.used_at) if i.used_at else None,
                           revoked=i.revoked)
            for i in account_store.list_invitations(users)]


@accounts.delete("/invitations/{token}", response_model=OkResponse)
def accounts_revoke_invitation(token: str, request: Request,
                               users: Session = Depends(database.get_users_db)) -> OkResponse:
    """撤销未使用的邀请 (仅管理员)。"""
    _require_admin(request, users)
    if not account_store.revoke_invitation(users, token):
        raise HTTPException(400, "邀请不存在或已被使用")
    return OkResponse(ok=True)



# ---------------------------------------------------------------- 充电 API

@charging.get("/car")
def get_car(db: Session = Depends(database.get_db)) -> list[CarInfo]:
    """车辆信息。"""
    return repository.list_cars(db)


@charging.get("/summary")
def get_charging_summary(
        frm: str | None = Query(None, alias="from"), to: str | None = None,
        db: Session = Depends(database.get_db)) -> ChargingSummary:
    """充电汇总 (次数/电量/费用/SOC 与续航增益), 可按日期过滤。"""
    return repository.charging_summary(db, _date_range_or_400(frm, to))


@charging.get("/dimensions")
def get_charging_dimensions(
        frm: str | None = Query(None, alias="from"), to: str | None = None,
        db: Session = Depends(database.get_db)) -> ChargeDims:
    """充电统计维度聚合: 快慢/开始时段/起充 SOC/峰值功率/城市 (统计页图表)。"""
    return repository.charging_dimensions(db, _date_range_or_400(frm, to))


@charging.get("/map-locations")
def get_charging_map_locations(
        frm: str | None = Query(None, alias="from"), to: str | None = None,
        db: Session = Depends(database.get_db)) -> list[ChargeMapLocation]:
    """充电地图充电点聚合 (按地址, 次数降序; 无坐标的地址不上图)。"""
    return repository.charging_map_locations(db, _date_range_or_400(frm, to))


@charging.get("/regions")
def get_charging_regions(
        db: Session = Depends(database.get_db)) -> list[RegionNode]:
    """充电地点省市区树 (级联下拉数据源, 按充电次数降序)。"""
    return repository.charging_region_tree(db)


@charging.get("/sessions")
def get_sessions(
        offset: int = 0, limit: int = 50, sort: str = "date_desc",
        type_: str = Query("all", alias="type"), q: str | None = None,
        region: str | None = None, cost: str | None = None,
        frm: str | None = Query(None, alias="from"), to: str | None = None,
        db: Session = Depends(database.get_db)) -> ChargingSessionsPage:
    """充电列表: 过滤 (日期/快慢/地点省市区/费用记录/地址搜索) → 排序 → 分页。

    region 是 "/" 连接的省市区路径 (1~3 段 = 精确到省/市/区县), 与行程页同款。
    """
    if sort not in repository.SORT_OPTIONS:
        raise HTTPException(400, f"不支持的排序: {sort}")
    if offset < 0 or limit < 0:
        raise HTTPException(400, "分页参数非法")
    if cost not in (None, "all", "recorded", "missing"):
        raise HTTPException(400, "不支持的费用筛选")
    if region and not 1 <= len([t for t in region.split("/") if t.strip()]) <= 3:
        raise HTTPException(400, "地区参数非法")
    flt = repository.SessionFilter(
        date_range=_date_range_or_400(frm, to), charge_type=type_,
        region=region or None, query=q, sort=sort, offset=offset, limit=limit,
        cost=None if cost == "all" else cost)
    total, items = repository.list_charging_sessions(db, flt)
    return ChargingSessionsPage(total=total, items=items)


@charging.get("/sessions/{session_id}")
def get_session(session_id: int,
                db: Session = Depends(database.get_db)) -> ChargingSessionDetail:
    """充电详情: 卡片字段 + 采样曲线。"""
    detail = repository.charging_session_detail(db, session_id)
    if detail is None:
        raise HTTPException(404, "充电记录不存在")
    return detail


@charging.patch("/sessions/{session_id}/cost")
def update_cost(session_id: int, body: CostUpdateRequest,
                db: Session = Depends(database.get_db)) -> CostUpdateResult:
    """更新 / 添加 / 清除一条充电记录的费用 (写回 TeslaMate 库)。"""
    cost_in_range = body.cost is None or 0 <= body.cost <= 100000
    if not cost_in_range:
        raise HTTPException(400, "金额需在 0 ~ 100000 之间")
    result = repository.update_charging_cost(db, session_id, body.cost)
    if result is None:
        raise HTTPException(404, "充电记录不存在")
    return result


@charging.get("/monthly")
def get_monthly(
        frm: str | None = Query(None, alias="from"), to: str | None = None,
        db: Session = Depends(database.get_db)) -> list[MonthlyStat]:
    """按月充电统计 (图表用)。"""
    return repository.monthly_stats(db, _date_range_or_400(frm, to))


@charging.get("/locations")
def get_locations(
        frm: str | None = Query(None, alias="from"), to: str | None = None,
        db: Session = Depends(database.get_db)) -> list[LocationStat]:
    """按充电地点分组统计 (图表用)。"""
    return repository.location_stats(db, _date_range_or_400(frm, to))


# ---------------------------------------------------------------- 足迹地图 API

@mapapi.get("/config")
def map_config(own: Session = Depends(database.get_own_db)) -> AmapConfig:
    """高德 Key 与地图样式: 设置页可改 (存自有库), 未设回落 env;
    每次现读, 改完刷新页面即生效。"""
    key, code = settings_store.amap_values(own)
    return AmapConfig(amap_key=key, security_code=code,
                      style=settings_store.amap_style_value(own))


@mapapi.get("/summary")
def get_map_summary(
        frm: str | None = Query(None, alias="from"), to: str | None = None,
        driver_id: int | None = Query(None),
        db: Session = Depends(database.get_db),
        own: Session = Depends(database.get_own_db)) -> MapSummary:
    """地图页汇总: 行程数 / 总里程 / 总时长 / 起止日期, 可按驾驶员过滤。"""
    return repository.map_summary(db, own, _date_range_or_400(frm, to), driver_id)


@mapapi.get("/tracks")
def get_tracks(frm: str | None = Query(None, alias="from"),
               to: str | None = None, driver_id: int | None = Query(None),
               own: Session = Depends(database.get_own_db)) -> TracksResponse:
    """全量粗轨迹 (每条 ~40 点, 两级缓存 + 增量), 可按日期/驾驶员过滤。"""
    _date_range_or_400(frm, to)   # 先校验再过滤, 空列表也要拦住坏参数
    tracks = tracks_cache.load_tracks(database.session_factory())
    tracks = tracks_cache.filter_by_date(tracks, frm, to)
    if driver_id is not None:     # 驾驶员标注在自有库 → 缓存轨迹后置过滤
        tracks = repository.filter_map_tracks_by_driver(tracks, own, driver_id)
    return TracksResponse(count=len(tracks), tracks=tracks)


@mapapi.get("/tracks/detail")
def get_tracks_detail(
        ids: str, zoom: int = 15, w: float = -180.0, s: float = -90.0,  # pylint: disable=unused-argument
        e: float = 180.0, n: float = 90.0) -> TracksDetailResponse:
    """视野内高精度轨迹: bbox 过滤 + 按 ids 数量定下采样预算。"""
    # zoom 保留在签名里 (前端语义参数, 缩放档位语义), 服务端按 ids 数量算预算
    try:
        id_list = [int(x) for x in ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(400, "ids 格式错误") from None
    id_list = id_list[:repository.DETAIL_MAX_IDS]
    if not id_list:
        return TracksDetailResponse(count=0, tracks=[])
    bbox_valid = -180 <= w < e <= 180 and -90 <= s < n <= 90
    if not bbox_valid:
        raise HTTPException(400, "bbox 参数非法")
    bbox = repository.BBox(west=w, south=s, east=e, north=n)
    per = repository.detail_per_for(len(id_list))
    tracks = repository.query_detail_parallel(
        database.session_factory(), id_list, per, bbox)
    return TracksDetailResponse(count=len(tracks), tracks=tracks)


@mapapi.post("/diag")
async def map_diag(request: Request) -> OkResponse:
    """浏览器端诊断上报 (排查地图加载问题), 只写日志不落库。"""
    try:
        body = await request.json()
    except ValueError:
        body = {}
    print(f"MAPDIAG {json.dumps(body, ensure_ascii=False)[:800]}", flush=True)
    return OkResponse(ok=True)


# ---------------------------------------------------------------- 行程 API
# 只列已完成的行程: TeslaMate 记录中断会留下 end_date 为空的"未关闭"行程
# (无里程/起终点, Grafana 行程面板同样不显示), 与地图页全量轨迹
# (distance IS NOT NULL) 的过滤口径一致。

@trips.get("/sessions")
# 行程列表筛选项逐个加 (时间/起终地区/里程/驾驶员), 都是平铺查询参数
def get_trip_sessions(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    offset: int = 0, limit: int = 24,
                      frm: str | None = Query(None, alias="from"),
                      to: str | None = Query(None, alias="to"),
                      from_loc: str | None = None, to_loc: str | None = None,
                      km_min: float | None = None, km_max: float | None = None,
                      driver_id: int | None = None,
                      db: Session = Depends(database.get_db),
                      own: Session = Depends(database.get_own_db)) -> TripsPage:
    """行程列表 (最新在前, 只含已结束行程); from/to 按出发时间过滤 (本地日期),
    from_loc/to_loc 按起终省市区 ("/" 路径, 1~3 段 = 精确到省/市/区县),
    km_min/km_max 按里程 (km) 过滤, driver_id 按驾驶员 (含默认驾驶员兜底口径)。"""
    if offset < 0 or not 1 <= limit <= 100:
        raise HTTPException(400, "分页参数非法")
    for v in (km_min, km_max):
        if v is not None and not 0 <= v <= 1e6:
            raise HTTPException(400, "里程参数非法")
    if km_min is not None and km_max is not None and km_min > km_max:
        raise HTTPException(400, "里程参数非法")
    for loc in (from_loc, to_loc):
        if loc and not 1 <= len([s for s in loc.split("/") if s.strip()]) <= 3:
            raise HTTPException(400, "地区参数非法")
    total, items = repository.list_trips(db, own, offset, limit, repository.TripFilter(
        date_range=_date_range_or_400(frm, to),
        from_loc=from_loc or None, to_loc=to_loc or None,
        km_min=km_min, km_max=km_max, driver_id=driver_id))
    return TripsPage(total=total, items=items)


@trips.get("/regions")
def get_trip_regions(db: Session = Depends(database.get_db)) -> TripRegions:
    """行程起终点省市区树 (级联下拉数据源)。"""
    return repository.list_trip_regions(db)


@trips.get("/sessions/{drive_id}")
def get_trip_session(drive_id: int,
                     db: Session = Depends(database.get_db),
                     own: Session = Depends(database.get_own_db)) -> TripItem:
    """单条行程信息: 分享链接 /tesla/trips?id=X 直开弹层时前端拉取。"""
    item = repository.get_trip(db, own, drive_id)
    if item is None:
        raise HTTPException(404, "行程不存在或未完成")
    return item


@trips.get("/merged")
def get_merged_track(ids: str,
                     db: Session = Depends(database.get_db),
                     own: Session = Depends(database.get_own_db)) -> MergedTrack:
    """多选连续行程 → 一条连续轨迹 (整包 JSON)。
    ts 为"累计行驶秒": 行程间的停驶时间剔除, 否则跨天合并后播放进度和
    实时时长全被停车时间淹没; pts/ts 结构与单条轨迹接口一致。
    边下边播走 /merged_stream, 这里是缓存命中等一次性消费的整包版本。"""
    id_list = _merged_id_list(ids, db)
    if not 2 <= len(id_list) <= 100:
        raise HTTPException(400, "ids 需为 2~100 个行程")
    try:
        return repository.merged_track(db, own, id_list)
    except repository.NotFound as exc:
        raise HTTPException(404, str(exc)) from exc


def _merged_id_list(raw: str, db: Session) -> list[int]:
    """ids 参数两种写法: 逗号 id 列表, 或 "首-尾" 区间。

    连续行程本就要求头尾相接, 只记头尾 id 链接短得多; 区间在服务端
    展开成全部已结束行程 (未结束的自动跳过, 与行程列表同口径)。"""
    if "-" in raw and "," not in raw:
        m = re.fullmatch(r"(\d+)-(\d+)", raw)
        if m and int(m[1]) <= int(m[2]):
            return repository.closed_drive_ids_between(db, int(m[1]), int(m[2]))
        raise HTTPException(400, "ids 参数非法")
    try:
        return list(dict.fromkeys(int(x) for x in raw.split(",")))
    except ValueError:
        raise HTTPException(400, "ids 参数非法") from None


@trips.get("/merged_stream")
def get_merged_track_stream(ids: str,
                            db: Session = Depends(database.get_db),
                            own: Session = Depends(database.get_own_db)) -> StreamingResponse:
    """合并轨迹 NDJSON 流: 首行汇总头, 之后每行一段 (pts/ts)。

    38 段的轨迹整包要好几秒, 前端弹层先开、第一段到了就开播, 后续
    段到了追加 —— 不让用户对着死屏等全部数据下载完。"""
    id_list = _merged_id_list(ids, db)
    if not 2 <= len(id_list) <= 100:
        raise HTTPException(400, "ids 需为 2~100 个行程")
    try:
        plan = repository.merged_track_plan(db, id_list)   # 校验 + 头部 (404 在流开始前)
    except repository.NotFound as exc:
        raise HTTPException(404, str(exc)) from exc

    def gen() -> Iterator[str]:
        yield json.dumps({"summary": plan.header.model_dump(by_alias=True),
                          "segs": len(plan.budgets)},   # 有轨迹数据的段数 (前端判下载中断用)
                         ensure_ascii=False, separators=(",", ":")) + "\n"
        for seg_pts, seg_ts in repository.merged_track_segments(db, own, plan):
            yield json.dumps({"pts": seg_pts, "ts": seg_ts},
                             separators=(",", ":")) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@trips.post("/gap_fill")
def post_gap_fill(body: GapFillRequest,
                  db: Session = Depends(database.get_db),
                  own: Session = Depends(database.get_own_db)) -> GapFillResponse:
    """断档补路回传: 前端高德规划成功后把 WGS 折线存进自有库, 之后
    单条/合并轨迹接口直接在服务端拼好, 不再每次重新规划。"""
    if (len(body.a) != 2 or len(body.b) != 2
            or not all(math.isfinite(v) for v in [*body.a, *body.b])
            or not 2 <= len(body.path) <= 500
            or any(len(p) != 2 or not all(math.isfinite(v) for v in p)
                   for p in body.path)):
        raise HTTPException(400, "补路参数非法")
    try:
        km = repository.save_fill(db, own, body)
    except repository.NotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return GapFillResponse(ok=True, km=km)


@trips.get("/groups")
def list_groups(db: Session = Depends(database.get_db),
                own: Session = Depends(database.get_own_db)) -> list[TripGroupInfo]:
    """全部轨迹分组 (逻辑分组, 存自有库, 行程原数据不动)。"""
    return repository.list_trip_groups(db, own)


@trips.post("/groups")
def save_group(body: TripGroupIn,
               db: Session = Depends(database.get_db),
               own: Session = Depends(database.get_own_db)) -> TripGroupInfo:
    """多选行程存成命名分组; 段数/里程/日期跨度展示时现算, 不落库。"""
    if len(set(body.ids)) < 2:
        raise HTTPException(400, "ids 去重后需为 2~100 个行程")
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "名字不能为空")
    try:
        return repository.save_trip_group(db, own, name, body.ids)
    except repository.NotFound as exc:
        raise HTTPException(404, str(exc)) from exc


@trips.patch("/groups/{group_id}")
def rename_group(group_id: int, body: TripGroupRename,
                 db: Session = Depends(database.get_db),
                 own: Session = Depends(database.get_own_db)) -> TripGroupInfo:
    """分组改名 (成员不动)。"""
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "名字不能为空")
    try:
        return repository.rename_trip_group(db, own, group_id, name)
    except repository.NotFound as exc:
        raise HTTPException(404, str(exc)) from exc


@trips.delete("/groups/{group_id}")
def delete_group(group_id: int,
                 own: Session = Depends(database.get_own_db)) -> OkResponse:
    """删分组 (只删自有库记录)。"""
    try:
        repository.delete_trip_group(own, group_id)
    except repository.NotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    return OkResponse(ok=True)


@trips.post("/{drive_id}/toll")
def post_trip_toll(drive_id: int, body: TripTollIn,
                   db: Session = Depends(database.get_db),
                   own: Session = Depends(database.get_own_db)) -> OkResponse:
    """高速费估价回传: 前端用高德驾车规划 (沿轨迹途经点) 估出 tolls 后
    存进自有库。tolls=0 也是有效结果 (没走收费路); 重算 = 覆盖更新。"""
    if repository.get_trip(db, own, drive_id) is None:
        raise HTTPException(404, "行程不存在或未完成")
    repository.save_trip_toll(own, drive_id, body)
    return OkResponse(ok=True)


@trips.post("/{drive_id}/driver")
def mark_trip_driver(drive_id: int, body: DriverMark,
                     db: Session = Depends(database.get_db),
                     own: Session = Depends(database.get_own_db)) -> TripItem:
    """标/清行程驾驶员 (driver_id 空 = 清除, 展示回默认驾驶员兜底)。
    返回更新后的行程条目 (前端直接刷新卡片与弹层)。"""
    if repository.get_trip(db, own, drive_id) is None:
        raise HTTPException(404, "行程不存在或未完成")
    try:
        repository.set_trip_driver(own, drive_id, body.driver_id)
    except repository.NotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    updated = repository.get_trip(db, own, drive_id)
    assert updated is not None   # 上面刚验证过存在
    return updated


@trips.get("/{drive_id}/track")
def get_trip_track(drive_id: int,
                   db: Session = Depends(database.get_db),
                   own: Session = Depends(database.get_own_db)) -> TripTrack:
    """单条行程全精度轨迹: pts 为 [lng, lat, speed_km_h, power_W]
    (power 正=放电 负=动能回收, 可能为 null); ts 为相对起点的秒偏移
    (与 pts 下标对齐, 播放动画里用来算"已行驶时长"和平均功耗)。"""
    try:
        return repository.trip_track(db, own, drive_id)
    except repository.NotFound as exc:
        raise HTTPException(404, str(exc)) from exc


# ---------------------------------------------------------------- 当前驾驶 API

@live.get("/status")
def get_live_status(db: Session = Depends(database.get_db)) -> LiveStatus:
    """当前驾驶状态 (未结束行程 + 足够新的位置点, 前端轮询)。"""
    return repository.live_status(db)


# ---------------------------------------------------------------- 静态页面

@app.get("/tesla")
def tesla_home() -> RedirectResponse:
    """/tesla → 默认充电页。"""
    return RedirectResponse("/tesla/charging", status_code=302)


@app.get("/tesla/charging")
def charging_page() -> FileResponse:
    """充电记录页。"""
    return _page("index.html")


@app.get("/tesla/stats")
def stats_page() -> FileResponse:
    """充电统计页: 统计卡片 + 各维度图表 (记录列表留在充电记录页)。"""
    return _page("stats.html")


@app.get("/tesla/chargemap")
def chargemap_page() -> FileResponse:
    """充电地图页: 热力图按充电点聚合, 颜色权重可切 电量/次数/费用 三种视图。"""
    return _page("chargemap.html")


@app.get("/tesla/map")
def map_page() -> FileResponse:
    """足迹地图页。"""
    return _page("map.html")


@app.get("/tesla/trips")
def trips_page() -> FileResponse:
    """行程轨迹页。"""
    return _page("trips.html")


@app.get("/tesla/groups")
def groups_page() -> FileResponse:
    """行程分组页: 分组的浏览/打开/改名/删除 (创建入口在行程列表)。"""
    return _page("groups.html")


@app.get("/tesla/live")
def live_page() -> FileResponse:
    """当前驾驶页: 在开时实时速度 / 位置 / 电耗 / 剩余电量。"""
    return _page("live.html")


@app.get("/tesla/settings")
def settings_page() -> FileResponse:
    """设置页: TeslaMate 数据库 / 高德 Key / 驾驶员 / 账号。"""
    return _page("settings.html")


@app.get("/accounts")
def accounts_page() -> FileResponse:
    """账号管理页 (My Home 共享层, 仅管理员; 非管理员进来只见提示)。"""
    return _page("accounts.html", directory=HOME_STATIC_DIR)


@app.get("/tesla/changelog")
def changelog_page() -> FileResponse:
    """更新日志页: 合并批次的版本条目, 用户视角文案。"""
    return _page("changelog.html")


@settingsapi.get("/settings")
def get_settings(own: Session = Depends(database.get_own_db)) -> SettingsState:
    """设置现值 (秘密打码, 密码只报是否在用)。"""
    return settings_store.settings_state(own)


@settingsapi.post("/settings")
def save_settings(body: SettingsUpdate,
                  own: Session = Depends(database.get_own_db)) -> SettingsState:
    """保存设置: 留空字段不动; TeslaMate 连接变了 → 换引擎实测, 连不上整体回滚。"""
    try:
        state, engine_changed = settings_store.save_settings(own, body)
    except settings_store.EngineError as exc:
        raise HTTPException(400, str(exc)) from exc
    except settings_store.StyleError as exc:
        raise HTTPException(400, str(exc)) from exc
    if engine_changed:
        # 换库了: 旧轨迹缓存全作废, 后台重灌 (不阻塞响应)
        tracks_cache.reset()
        threading.Thread(target=tracks_cache.warm,
                         args=(database.session_factory(),), daemon=True).start()
    return state


@settingsapi.get("/drivers")
def get_drivers(own: Session = Depends(database.get_own_db)) -> list[DriverInfo]:
    """全部驾驶员。"""
    return settings_store.list_drivers(own)


@settingsapi.post("/drivers")
def add_driver(body: DriverIn,
               own: Session = Depends(database.get_own_db)) -> DriverInfo:
    """添加驾驶员。"""
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "名字不能为空")
    return settings_store.create_driver(own, name)


@settingsapi.patch("/drivers/{driver_id}")
def change_driver(driver_id: int, body: DriverUpdate,
                  own: Session = Depends(database.get_own_db)) -> DriverInfo:
    """改驾驶员: 改名 / 设默认 (全库至多一个默认)。"""
    name = body.name.strip() if body.name is not None else None
    if name == "":
        raise HTTPException(400, "名字不能为空")
    try:
        return settings_store.update_driver(own, driver_id, name, body.is_default)
    except repository.NotFound as exc:
        raise HTTPException(404, str(exc)) from exc


@settingsapi.delete("/drivers/{driver_id}")
def remove_driver(driver_id: int,
                  own: Session = Depends(database.get_own_db)) -> OkResponse:
    """删驾驶员。"""
    try:
        settings_store.delete_driver(own, driver_id)
    except repository.NotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    return OkResponse(ok=True)


@changelogapi.get("/entries")
def get_changelog_entries() -> list[ChangelogVersion]:
    """更新日志版本 (新→老), 每版是一批改动的合并。"""
    return changelog.entries()


app.include_router(charging)
app.include_router(mapapi)
app.include_router(trips)
app.include_router(live)
app.include_router(settingsapi)
app.include_router(changelogapi)
app.include_router(accounts)
app.mount("/static", StaticFiles(directory=HOME_STATIC_DIR), name="home-static")
app.mount("/tesla/static", StaticFiles(directory=config.STATIC_DIR), name="static")
# My Money (家庭记账): 独立应用, 只共享账号体系 (会话 cookie + 账号库)
app.mount("/bookkeeping", webapp.bk_app)
