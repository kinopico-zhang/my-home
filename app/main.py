"""My Tesla —— API 路由层 (薄)。

数据源: teslamate_cn (PostgreSQL, TeslaMate 标准表结构), 查询全部在
repository 层 (SQLAlchemy, 方言中立); 测试通过 database.init_engine()
注入 SQLite, 不碰真实库。
时间处理: 库内为 UTC 裸时间戳, 对外输出本地时间 (默认 Asia/Shanghai)。
鉴权: 登录后签发 HMAC 签名的会话 cookie (默认 90 天), 未登录跳转 /tesla/login。
"""
import hmac
import json
import os
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Awaitable, Callable

from fastapi import (APIRouter, Depends, FastAPI, HTTPException, Query,
                     Request, Response)
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               RedirectResponse)
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from . import authentication, config, database, repository, tracks_cache
from .schemas import (
    AmapConfig,
    CarInfo,
    ChargingSessionDetail,
    ChargingSessionsPage,
    ChargingSummary,
    CityCount,
    CostUpdateRequest,
    CostUpdateResult,
    LocationStat,
    LoginCredentials,
    MapSummary,
    MergedTrack,
    MonthlyStat,
    OkResponse,
    TracksDetailResponse,
    TracksResponse,
    TripCities,
    TripItem,
    TripTrack,
    TripsPage,
)

# 充电页面 API (页面: /tesla/charging)
charging = APIRouter(prefix="/tesla/charging/api")
# 足迹地图 API (页面: /tesla/map)
mapapi = APIRouter(prefix="/tesla/map/api")
# 行程轨迹 API (页面: /tesla/trips —— 行程卡片瀑布流 + 点击查看单条全精度轨迹)
trips = APIRouter(prefix="/tesla/trips/api")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """启动时建引擎 + 后台预热缓存, 关闭时释放连接池。"""
    database.init_engine()
    # 后台预热轨迹缓存 (全量下采样 ~15s, 不阻塞启动)
    threading.Thread(target=tracks_cache.warm,
                     args=(database.session_factory(),), daemon=True).start()
    yield
    database.dispose_engine()


app = FastAPI(title="My Tesla", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=2048)   # 轨迹 JSON 压缩 ~5x


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_error_handler(
        _: Request, exc: SQLAlchemyError) -> JSONResponse:
    """数据库异常统一 503 (与旧版 query() 包装行为一致)。"""
    return JSONResponse({"detail": f"数据库查询失败: {exc}"}, status_code=503)


@app.middleware("http")
async def auth_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """页面未登录跳登录页, API 未登录 401; 静态放行 + 缓存策略。"""
    path = request.url.path
    is_api = path.startswith("/tesla/") and "/api/" in path
    # 放行: 登录页 / 登录登出接口 / 静态资源
    if path in ("/tesla/login", "/tesla/api/login", "/tesla/api/logout") \
            or path.startswith("/tesla/static/"):
        resp = await call_next(request)
    elif is_api and not authentication.check_token(
            request.cookies.get("auth", "")):
        resp = JSONResponse({"detail": "未登录"}, status_code=401)
    elif path.startswith("/tesla") and not is_api and not authentication.check_token(
            request.cookies.get("auth", "")):
        resp = RedirectResponse("/tesla/login", status_code=302)
    else:
        resp = await call_next(request)
    if is_api:
        # API 数据 (如 map config) 禁止缓存, 否则配置更新后浏览器仍用旧响应
        resp.headers["Cache-Control"] = "no-store"
    elif path.startswith("/tesla/static/"):
        # JS 工具 (trackutil 等) 迭代频繁, 必须重新校验; ETag 命中时 304 很便宜。
        # 只发 Last-Modified 时浏览器走启发式缓存, 会继续用旧 JS (动画因此冻住过)。
        resp.headers["Cache-Control"] = "no-cache"
    return resp


def _page(fname: str) -> FileResponse:
    """HTML 页面: 允许缓存但必须带 ETag 重新校验 (no-cache), 更新即时生效。"""
    resp = FileResponse(config.STATIC_DIR / fname)
    resp.headers["Cache-Control"] = "no-cache"
    return resp


def _date_range_or_400(frm: str | None,
                       to: str | None) -> repository.DateRange | None:
    """from/to (本地日期) → 库内 UTC 边界; 坏参数直接 400。"""
    try:
        return repository.parse_date_range(frm, to)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


# ---------------------------------------------------------------- 登录 / 登出

@app.get("/tesla/login", response_class=HTMLResponse)
def login_page() -> FileResponse:
    """登录页。"""
    return _page("login.html")


@app.post("/tesla/api/login")
def login(creds: LoginCredentials, request: Request) -> JSONResponse:
    """校验账密 (带单 IP 限速), 签发会话 cookie。"""
    ip = request.client.host if request.client else "?"
    if authentication.ip_locked(ip):
        raise HTTPException(
            429, f"尝试次数过多, 请 {config.LOGIN_LOCK_S} 秒后再试")
    ok_user = hmac.compare_digest(creds.user.encode(), config.AUTH_USER.encode())
    ok_pass = hmac.compare_digest(
        creds.password.encode(), config.AUTH_PASS.encode())
    if not (ok_user and ok_pass):
        authentication.record_fail(ip)
        raise HTTPException(401, "账号或密码错误")
    authentication.clear_fails(ip)
    resp = JSONResponse(OkResponse(ok=True).model_dump())
    resp.set_cookie("auth", authentication.make_token(),
                    max_age=config.SESSION_DAYS * 86400, httponly=True,
                    samesite="lax", path="/tesla")
    return resp


@app.post("/tesla/api/logout")
def logout() -> JSONResponse:
    """登出 (并吊销所有已签发会话)。"""
    # 轮换密钥: 登出即吊销所有已签发的会话 (单用户, 等同「所有设备退出」)
    authentication.rotate_secret()
    resp = JSONResponse(OkResponse(ok=True).model_dump())
    resp.delete_cookie("auth", path="/tesla")
    return resp


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


@charging.get("/cities")
def get_charging_cities(
        db: Session = Depends(database.get_db)) -> list[CityCount]:
    """充电城市列表 (筛选下拉数据源, 次数降序)。"""
    return repository.list_charging_cities(db)


@charging.get("/sessions")
def get_sessions(
        offset: int = 0, limit: int = 50, sort: str = "date_desc",
        type_: str = Query("all", alias="type"), q: str | None = None,
        city: str | None = None,
        frm: str | None = Query(None, alias="from"), to: str | None = None,
        db: Session = Depends(database.get_db)) -> ChargingSessionsPage:
    """充电列表: 过滤 (日期/快慢/城市/地址搜索) → 排序 → 分页。"""
    if sort not in repository.SORT_OPTIONS:
        raise HTTPException(400, f"不支持的排序: {sort}")
    if offset < 0 or limit < 0:
        raise HTTPException(400, "分页参数非法")
    flt = repository.SessionFilter(
        date_range=_date_range_or_400(frm, to), charge_type=type_,
        city=city or None, query=q, sort=sort, offset=offset, limit=limit)
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
def map_config() -> AmapConfig:
    """高德地图 Key (env: AMAP_KEY / AMAP_SECURITY_CODE, 见 .env.example)。"""
    return AmapConfig(amap_key=os.environ.get("AMAP_KEY"),
                      security_code=os.environ.get("AMAP_SECURITY_CODE"))


@mapapi.get("/summary")
def get_map_summary(
        frm: str | None = Query(None, alias="from"), to: str | None = None,
        db: Session = Depends(database.get_db)) -> MapSummary:
    """地图页汇总: 行程数 / 总里程 / 总时长 / 起止日期。"""
    return repository.map_summary(db, _date_range_or_400(frm, to))


@mapapi.get("/tracks")
def get_tracks(frm: str | None = Query(None, alias="from"),
               to: str | None = None) -> TracksResponse:
    """全量粗轨迹 (每条 ~40 点, 两级缓存 + 增量), 可按日期过滤。"""
    _date_range_or_400(frm, to)   # 先校验再过滤, 空列表也要拦住坏参数
    tracks = tracks_cache.load_tracks(database.session_factory())
    tracks = tracks_cache.filter_by_date(tracks, frm, to)
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
def get_trip_sessions(offset: int = 0, limit: int = 24,
                      frm: str | None = Query(None, alias="from"),
                      to: str | None = Query(None, alias="to"),
                      from_city: str | None = None, to_city: str | None = None,
                      km_min: float | None = None, km_max: float | None = None,
                      db: Session = Depends(database.get_db)) -> TripsPage:
    """行程列表 (最新在前, 只含已结束行程); from/to 按出发时间过滤 (本地日期),
    from_city/to_city 按起终城市, km_min/km_max 按里程 (km) 过滤。"""
    if offset < 0 or not 1 <= limit <= 100:
        raise HTTPException(400, "分页参数非法")
    for v in (km_min, km_max):
        if v is not None and not 0 <= v <= 1e6:
            raise HTTPException(400, "里程参数非法")
    if km_min is not None and km_max is not None and km_min > km_max:
        raise HTTPException(400, "里程参数非法")
    total, items = repository.list_trips(db, offset, limit, repository.TripFilter(
        date_range=_date_range_or_400(frm, to),
        from_city=from_city or None, to_city=to_city or None,
        km_min=km_min, km_max=km_max))
    return TripsPage(total=total, items=items)


@trips.get("/cities")
def get_trip_cities(db: Session = Depends(database.get_db)) -> TripCities:
    """行程起终点城市列表 (筛选下拉数据源)。"""
    return repository.list_trip_cities(db)


@trips.get("/sessions/{drive_id}")
def get_trip_session(drive_id: int,
                     db: Session = Depends(database.get_db)) -> TripItem:
    """单条行程信息: 分享链接 /tesla/trips?id=X 直开弹层时前端拉取。"""
    item = repository.get_trip(db, drive_id)
    if item is None:
        raise HTTPException(404, "行程不存在或未完成")
    return item


@trips.get("/merged")
def get_merged_track(ids: str,
                     db: Session = Depends(database.get_db)) -> MergedTrack:
    """多选连续行程 → 一条连续轨迹 (分享链接 /tesla/trips?ids=a,b,c)。
    ts 为"累计行驶秒": 行程间的停驶时间剔除, 否则跨天合并后播放进度和
    实时时长全被停车时间淹没; pts/ts 结构与单条轨迹接口一致。"""
    try:
        id_list = list(dict.fromkeys(int(x) for x in ids.split(",")))
    except ValueError:
        raise HTTPException(400, "ids 参数非法") from None
    if not 2 <= len(id_list) <= 50:
        raise HTTPException(400, "ids 需为 2~50 个行程")
    try:
        return repository.merged_track(db, id_list)
    except repository.NotFound as exc:
        raise HTTPException(404, str(exc)) from exc


@trips.get("/{drive_id}/track")
def get_trip_track(drive_id: int,
                   db: Session = Depends(database.get_db)) -> TripTrack:
    """单条行程全精度轨迹: pts 为 [lng, lat, speed_km_h, power_W]
    (power 正=放电 负=动能回收, 可能为 null); ts 为相对起点的秒偏移
    (与 pts 下标对齐, 播放动画里用来算"已行驶时长"和平均功耗)。"""
    try:
        return repository.trip_track(db, drive_id)
    except repository.NotFound as exc:
        raise HTTPException(404, str(exc)) from exc


# ---------------------------------------------------------------- 静态页面

@app.get("/")
def root() -> RedirectResponse:
    """根路径 → /tesla。"""
    return RedirectResponse("/tesla", status_code=302)


@app.get("/tesla")
def tesla_home() -> RedirectResponse:
    """/tesla → 默认充电页。"""
    return RedirectResponse("/tesla/charging", status_code=302)


@app.get("/tesla/charging")
def charging_page() -> FileResponse:
    """充电记录页。"""
    return _page("index.html")


@app.get("/tesla/map")
def map_page() -> FileResponse:
    """足迹地图页。"""
    return _page("map.html")


@app.get("/tesla/trips")
def trips_page() -> FileResponse:
    """行程轨迹页。"""
    return _page("trips.html")


app.include_router(charging)
app.include_router(mapapi)
app.include_router(trips)
app.mount("/tesla/static", StaticFiles(directory=config.STATIC_DIR), name="static")
