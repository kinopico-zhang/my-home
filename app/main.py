"""充电记录展示服务 —— 后端 API。

数据源: teslamate_cn (PostgreSQL, TeslaMate 标准表结构)。
时间处理: 库内为 UTC 裸时间戳, 对外输出本地时间 (默认 Asia/Shanghai)。
鉴权: 登录后签发 HMAC 签名的会话 cookie (默认 90 天), 未登录跳转 /tesla/login。
"""
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from psycopg.rows import dict_row
from pydantic import BaseModel

from .db import make_pool

LOCAL_TZ = ZoneInfo(os.environ.get("TZ_NAME", "Asia/Shanghai"))
CUR_SYMBOL = os.environ.get("CUR_SYMBOL", "¥")
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

# ---------------------------------------------------------------- 鉴权
AUTH_USER = os.environ.get("AUTH_USER", "admin")
AUTH_PASS = os.environ.get("AUTH_PASS", "daozi1994")
SESSION_DAYS = int(os.environ.get("SESSION_DAYS", 90))
SECRET_FILE = os.path.join(os.path.dirname(__file__), "..", ".session_secret")

# 登录限速: 单 IP 连续失败 5 次锁定 60 秒
LOGIN_MAX_FAILS = 5
LOGIN_LOCK_S = 60
_login_fails: dict = {}


def _load_secret() -> bytes:
    """会话签名密钥, 持久化在 .session_secret (重启不失效)。"""
    try:
        data = open(SECRET_FILE, "rb").read().strip()
        if len(data) >= 32:
            return data
    except OSError:
        pass
    data = secrets.token_hex(32).encode()
    with open(SECRET_FILE, "wb") as f:
        f.write(data)
    try:
        os.chmod(SECRET_FILE, 0o600)
    except OSError:
        pass
    return data


SECRET = hashlib.sha256(
    _load_secret() + b"|" + AUTH_USER.encode() + b"|" + AUTH_PASS.encode()
).digest()


def _make_token() -> str:
    exp = str(int(time.time()) + SESSION_DAYS * 86400)
    sig = hmac.new(SECRET, exp.encode(), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def _check_token(token: str) -> bool:
    try:
        exp, sig = token.split(".", 1)
        expect = hmac.new(SECRET, exp.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expect, sig) and int(exp) > time.time()
    except Exception:
        return False


def _authed(request: Request) -> bool:
    return _check_token(request.cookies.get("auth", ""))


def _ip_locked(ip: str) -> bool:
    rec = _login_fails.get(ip)
    return bool(rec and rec[1] > time.time())


def _record_fail(ip: str):
    if len(_login_fails) > 10000:  # 防扫描器撑爆内存
        _login_fails.clear()
    fails, _ = _login_fails.get(ip, (0, 0))
    if fails + 1 >= LOGIN_MAX_FAILS:
        _login_fails[ip] = (0, time.time() + LOGIN_LOCK_S)
    else:
        _login_fails[ip] = (fails + 1, 0)


pool = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global pool
    pool = make_pool()
    # 后台预热轨迹缓存 (全量下采样 ~15s, 不阻塞启动)
    threading.Thread(target=_warm_tracks, daemon=True).start()
    yield
    pool.close()


app = FastAPI(title="My Tesla", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=2048)   # 轨迹 JSON 压缩 ~5x

# 充电记录页面专属 API (页面: /tesla/charging)
charging = APIRouter(prefix="/tesla/charging/api")


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    is_api = path.startswith("/tesla/") and "/api/" in path
    # 放行: 登录页 / 登录登出接口 / 静态资源
    if path in ("/tesla/login", "/tesla/api/login", "/tesla/api/logout") \
            or path.startswith("/tesla/static/"):
        resp = await call_next(request)
    elif is_api and not _authed(request):
        resp = JSONResponse({"detail": "未登录"}, status_code=401)
    elif path.startswith("/tesla") and not is_api and not _authed(request):
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


class Creds(BaseModel):
    user: str
    password: str


@app.get("/tesla/login", response_class=HTMLResponse)
def login_page():
    return _page("login.html")


@app.post("/tesla/api/login")
def login(creds: Creds, request: Request, response: JSONResponse):
    ip = request.client.host if request.client else "?"
    if _ip_locked(ip):
        raise HTTPException(429, f"尝试次数过多, 请 {LOGIN_LOCK_S} 秒后再试")
    ok_user = hmac.compare_digest(creds.user.encode(), AUTH_USER.encode())
    ok_pass = hmac.compare_digest(creds.password.encode(), AUTH_PASS.encode())
    if not (ok_user and ok_pass):
        _record_fail(ip)
        raise HTTPException(401, "账号或密码错误")
    _login_fails.pop(ip, None)
    resp = JSONResponse({"ok": True})
    resp.set_cookie("auth", _make_token(), max_age=SESSION_DAYS * 86400,
                    httponly=True, samesite="lax", path="/tesla")
    return resp


@app.post("/tesla/api/logout")
def logout():
    # 轮换密钥: 登出即吊销所有已签发的会话 (单用户, 等同「所有设备退出」)
    global SECRET
    new_secret = secrets.token_hex(32).encode()
    with open(SECRET_FILE, "wb") as f:
        f.write(new_secret)
    SECRET = hashlib.sha256(
        new_secret + b"|" + AUTH_USER.encode() + b"|" + AUTH_PASS.encode()
    ).digest()
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("auth", path="/tesla")
    return resp


# ---------------------------------------------------------------- helpers

def to_local(dt: datetime) -> datetime:
    return dt.replace(tzinfo=dt_timezone.utc).astimezone(LOCAL_TZ)


def fnum(x) -> Optional[float]:
    return None if x is None else float(x)


def ftime(dt: datetime) -> str:
    return to_local(dt).strftime("%Y-%m-%d %H:%M")


def fdate(dt: datetime) -> str:
    return to_local(dt).strftime("%Y-%m-%d")


# 聚合每条充电过程的峰值功率与是否快充 (带索引, 开销很小)
AGG_LATERAL = """
LEFT JOIN LATERAL (
    SELECT max(c.charger_power) AS power_max,
           bool_or(coalesce(c.fast_charger_present, false) OR c.charger_power >= 20) AS is_fast
      FROM charges c
     WHERE c.charging_process_id = cp.id
) agg ON TRUE
"""

# 充电过程主查询: 关联地址 / 地理围栏
SESSION_SELECT = f"""
  SELECT cp.id, cp.start_date, cp.end_date,
         cp.start_battery_level, cp.end_battery_level,
         cp.charge_energy_added, cp.charge_energy_used,
         cp.duration_min, cp.cost, cp.outside_temp_avg,
         cp.start_rated_range_km, cp.end_rated_range_km,
         agg.power_max, agg.is_fast,
         g.name AS geofence_name, a.name AS address_name,
         a.city, a.display_name
    FROM charging_processes cp
    {AGG_LATERAL}
    LEFT JOIN addresses a ON a.id = cp.address_id
    LEFT JOIN geofences g ON g.id = cp.geofence_id
"""

# 本地日期 (北京时间) 转成库内 UTC 裸时间戳
def range_clause(params: dict) -> str:
    """根据 from/to (本地日期) 生成过滤条件。"""
    parts = []
    if params.get("from"):
        parts.append("cp.start_date >= (%(from)s::date::timestamp "
                     "AT TIME ZONE %(tz)s AT TIME ZONE 'UTC')")
    if params.get("to"):
        parts.append("cp.start_date < ((%(to)s::date + 1)::timestamp "
                     "AT TIME ZONE %(tz)s AT TIME ZONE 'UTC')")
    return " AND ".join(parts) if parts else "TRUE"


def session_row(r: dict) -> dict:
    energy_used = fnum(r["charge_energy_used"])
    energy_added = fnum(r["charge_energy_added"])
    cost = fnum(r["cost"])
    base = energy_used or energy_added
    return {
        "id": r["id"],
        "start": ftime(r["start_date"]),
        "end": ftime(r["end_date"]) if r["end_date"] else None,
        "date": fdate(r["start_date"]),
        "location": r["geofence_name"] or r["address_name"] or "未知位置",
        "city": r["city"],
        "address": r["display_name"],
        "start_soc": r["start_battery_level"],
        "end_soc": r["end_battery_level"],
        "energy_added": energy_added,
        "energy_used": energy_used,
        "cost": cost,
        "price_per_kwh": round(cost / base, 3) if cost and base else None,
        "duration_min": r["duration_min"],
        "outside_temp": fnum(r["outside_temp_avg"]),
        "power_max": r["power_max"],
        "is_fast": r["is_fast"],
    }


def query(sql: str, params: dict | None = None) -> list[dict]:
    try:
        with pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, params or {})
                return cur.fetchall()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"数据库查询失败: {e}") from e


# ---------------------------------------------------------------- API

@charging.get("/car")
def get_car():
    rows = query("SELECT id, name, model, trim_badging, vin FROM cars")
    return [{"id": r["id"], "name": r["name"], "model": r["model"],
             "trim_badging": r["trim_badging"], "vin": r["vin"]} for r in rows]


@charging.get("/summary")
def get_summary(frm: Optional[str] = Query(None, alias="from"),
                to: Optional[str] = Query(None)):
    params = {"tz": LOCAL_TZ.key, "from": frm, "to": to}
    cond = range_clause(params)
    rows = query(f"""
        WITH s AS (
            SELECT cp.charge_energy_added, cp.charge_energy_used, cp.cost,
                   cp.duration_min, cp.start_date,
                   cp.end_battery_level - cp.start_battery_level AS soc_gain,
                   cp.end_rated_range_km - cp.start_rated_range_km AS range_gain,
                   agg.is_fast
              FROM charging_processes cp
              {AGG_LATERAL}
             WHERE {cond}
        )
        SELECT count(*) AS sessions,
               coalesce(sum(charge_energy_added), 0) AS energy_added,
               coalesce(sum(charge_energy_used), 0) AS energy_used,
               coalesce(sum(cost), 0) AS cost,
               coalesce(sum(duration_min), 0) AS duration_min,
               count(*) FILTER (WHERE is_fast) AS fast_sessions,
               coalesce(sum(soc_gain), 0) AS soc_gain,
               coalesce(sum(range_gain), 0) AS range_gain,
               min(start_date) AS first_date, max(start_date) AS last_date
          FROM s
    """, params)
    r = rows[0]
    cost, energy = float(r["cost"]), float(r["energy_used"]) or float(r["energy_added"])
    return {
        "sessions": r["sessions"],
        "fast_sessions": r["fast_sessions"],
        "energy_added": fnum(r["energy_added"]),
        "energy_used": fnum(r["energy_used"]),
        "cost": round(cost, 2) if cost else 0.0,
        "price_per_kwh": round(cost / energy, 3) if energy else None,
        "duration_min": r["duration_min"],
        "soc_gain": int(r["soc_gain"]),
        "range_gain": round(float(r["range_gain"]), 1),
        "first_date": fdate(r["first_date"]) if r["first_date"] else None,
        "last_date": fdate(r["last_date"]) if r["last_date"] else None,
    }


SORT_OPTIONS = {
    "date_desc": "cp.start_date DESC",
    "date_asc": "cp.start_date ASC",
    "cost_desc": "cp.cost DESC NULLS LAST",
    "cost_asc": "cp.cost ASC NULLS LAST",
    "energy_desc": "cp.charge_energy_used DESC NULLS LAST",
    "energy_asc": "cp.charge_energy_used ASC NULLS LAST",
    "duration_desc": "cp.duration_min DESC NULLS LAST",
    "power_desc": "agg.power_max DESC NULLS LAST",
}


@charging.get("/sessions")
def get_sessions(offset: int = 0, limit: int = 50,
                 sort: str = "date_desc", type_: str = Query("all", alias="type"),
                 q: Optional[str] = None,
                 frm: Optional[str] = Query(None, alias="from"),
                 to: Optional[str] = Query(None)):
    if sort not in SORT_OPTIONS:
        raise HTTPException(400, f"不支持的排序: {sort}")
    params = {"tz": LOCAL_TZ.key, "from": frm, "to": to, "limit": limit, "offset": offset}
    conds = [range_clause(params)]
    if type_ == "fast":
        conds.append("agg.is_fast")
    elif type_ == "slow":
        conds.append("NOT agg.is_fast")
    if q:
        params["q"] = f"%{q}%"
        conds.append("(coalesce(g.name,'') || ' ' || coalesce(a.name,'') || ' ' || "
                     "coalesce(a.city,'') || ' ' || coalesce(a.display_name,'')) ILIKE %(q)s")
    where = " AND ".join(conds)
    total = query(f"""
        SELECT count(*) AS n FROM charging_processes cp {AGG_LATERAL}
        LEFT JOIN addresses a ON a.id = cp.address_id
        LEFT JOIN geofences g ON g.id = cp.geofence_id
        WHERE {where}
    """, params)[0]["n"]
    rows = query(f"""
        {SESSION_SELECT} WHERE {where}
        ORDER BY {SORT_OPTIONS[sort]}
        LIMIT %(limit)s OFFSET %(offset)s
    """, params)
    return {"total": total, "items": [session_row(r) for r in rows]}


@charging.get("/sessions/{session_id}")
def get_session(session_id: int):
    rows = query(f"{SESSION_SELECT} WHERE cp.id = %(id)s", {"id": session_id})
    if not rows:
        raise HTTPException(404, "充电记录不存在")
    detail = session_row(rows[0])
    samples = query("""
        SELECT date, battery_level, charger_power, charger_voltage,
               charger_actual_current, charge_energy_added, outside_temp,
               conn_charge_cable, fast_charger_brand, fast_charger_type
          FROM charges WHERE charging_process_id = %(id)s ORDER BY date
    """, {"id": session_id})
    start = rows[0]["start_date"]
    def clean(s):
        return s if s and s != "<invalid>" else None
    cable = next((s["conn_charge_cable"] for s in samples if s["conn_charge_cable"]), None)
    brand = clean(next((s["fast_charger_brand"] for s in samples if s["fast_charger_brand"]), None))
    ctype = clean(next((s["fast_charger_type"] for s in samples
                        if s["fast_charger_type"]), None))
    detail.update({
        "start_rated_range": fnum(rows[0]["start_rated_range_km"]),
        "end_rated_range": fnum(rows[0]["end_rated_range_km"]),
        "cable": cable, "charger_brand": brand, "charger_type": ctype,
        "curve": {
            "minutes": [round((s["date"] - start).total_seconds() / 60, 1) for s in samples],
            "soc": [s["battery_level"] for s in samples],
            "kw": [s["charger_power"] for s in samples],
            "voltage": [s["charger_voltage"] for s in samples],
            "current": [s["charger_actual_current"] for s in samples],
            "energy": [fnum(s["charge_energy_added"]) for s in samples],
        },
    })
    return detail


class CostUpdate(BaseModel):
    cost: Optional[float] = None  # null = 清除费用


@charging.patch("/sessions/{session_id}/cost")
def update_cost(session_id: int, body: CostUpdate):
    """更新 / 添加 / 清除一条充电记录的费用 (写回 TeslaMate 库)。"""
    if body.cost is not None and not (0 <= body.cost <= 100000):
        raise HTTPException(400, "金额需在 0 ~ 100000 之间")
    rows = query("SELECT charge_energy_added, charge_energy_used FROM charging_processes "
                 "WHERE id = %(id)s", {"id": session_id})
    if not rows:
        raise HTTPException(404, "充电记录不存在")
    try:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE charging_processes SET cost = %(cost)s WHERE id = %(id)s",
                            {"cost": round(body.cost, 2) if body.cost is not None else None,
                             "id": session_id})
    except Exception as e:
        raise HTTPException(503, f"费用保存失败: {e}") from e
    base = float(rows[0]["charge_energy_used"] or 0) or float(rows[0]["charge_energy_added"] or 0)
    return {"ok": True, "cost": body.cost,
            "price_per_kwh": round(body.cost / base, 3) if body.cost is not None and base else None}


@charging.get("/monthly")
def get_monthly(frm: Optional[str] = Query(None, alias="from"),
                to: Optional[str] = Query(None)):
    params = {"tz": LOCAL_TZ.key, "from": frm, "to": to}
    cond = range_clause(params)
    rows = query(f"""
        WITH s AS (
            SELECT (cp.start_date AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s) AS local_start,
                   cp.charge_energy_added, cp.charge_energy_used, cp.cost,
                   cp.duration_min, agg.is_fast
              FROM charging_processes cp {AGG_LATERAL}
             WHERE {cond}
        )
        SELECT to_char(local_start, 'YYYY-MM') AS month, count(*) AS sessions,
               sum(charge_energy_used) AS energy_used, sum(cost) AS cost,
               count(*) FILTER (WHERE is_fast) AS fast_sessions
          FROM s GROUP BY 1 ORDER BY 1
    """, params)
    return [{"month": r["month"], "sessions": r["sessions"],
             "energy_used": fnum(r["energy_used"]), "cost": fnum(r["cost"]),
             "fast_sessions": r["fast_sessions"]} for r in rows]


@charging.get("/locations")
def get_locations(frm: Optional[str] = Query(None, alias="from"),
                  to: Optional[str] = Query(None)):
    params = {"tz": LOCAL_TZ.key, "from": frm, "to": to}
    cond = range_clause(params)
    rows = query(f"""
        WITH s AS (
            SELECT cp.charge_energy_used, cp.cost, agg.is_fast,
                   coalesce(g.name, a.name, '未知位置') AS loc, a.city
              FROM charging_processes cp {AGG_LATERAL}
              LEFT JOIN addresses a ON a.id = cp.address_id
              LEFT JOIN geofences g ON g.id = cp.geofence_id
             WHERE {cond}
        )
        SELECT loc, city, count(*) AS sessions,
               sum(charge_energy_used) AS energy_used, sum(cost) AS cost,
               count(*) FILTER (WHERE is_fast) AS fast_sessions
          FROM s GROUP BY loc, city
         ORDER BY sessions DESC
    """, params)
    return [{"location": r["loc"], "city": r["city"], "sessions": r["sessions"],
             "energy_used": fnum(r["energy_used"]), "cost": fnum(r["cost"]),
             "fast_sessions": r["fast_sessions"]} for r in rows]


# ---------------------------------------------------------------- 足迹地图 API (页面: /tesla/map)
mapapi = APIRouter(prefix="/tesla/map/api")


@mapapi.get("/config")
def map_config():
    """高德地图 Key (env: AMAP_KEY / AMAP_SECURITY_CODE, 见 .env.example)。"""
    return {"amap_key": os.environ.get("AMAP_KEY") or None,
            "security_code": os.environ.get("AMAP_SECURITY_CODE") or None}


def drive_range_clause(params: dict) -> str:
    """按本地日期过滤 drives (与充电 range_clause 同一套时区换算)。"""
    parts = []
    if params.get("from"):
        parts.append("d.start_date >= (%(from)s::date::timestamp "
                     "AT TIME ZONE %(tz)s AT TIME ZONE 'UTC')")
    if params.get("to"):
        parts.append("d.start_date < ((%(to)s::date + 1)::timestamp "
                     "AT TIME ZONE %(tz)s AT TIME ZONE 'UTC')")
    return " AND ".join(parts) if parts else "TRUE"


@mapapi.get("/summary")
def map_summary(frm: Optional[str] = Query(None, alias="from"),
                to: Optional[str] = None):
    params = {"tz": LOCAL_TZ.key, "from": frm, "to": to}
    rows = query(f"""
        SELECT count(*) AS drives, coalesce(sum(distance), 0) AS km,
               coalesce(sum(duration_min), 0) AS duration_min,
               min(start_date) AS first_date, max(start_date) AS last_date
          FROM drives d
         WHERE d.distance IS NOT NULL AND {drive_range_clause(params)}
    """, params)
    r = rows[0]
    return {"drives": r["drives"], "distance_km": round(float(r["km"]), 1),
            "duration_min": r["duration_min"],
            "first_date": fdate(r["first_date"]) if r["first_date"] else None,
            "last_date": fdate(r["last_date"]) if r["last_date"] else None}


# 轨迹缓存: 全量下采样要扫千万级行 (~15s), 结果落盘并按 drive id 增量追加。
# 已完成行程不会变更, 新行程 id 单调递增, 旧缓存无需失效;
# 下采样算法变更时版本号 +1, 旧缓存自动作废全量重建。
TRACKS_CACHE_VERSION = 2
TRACKS_SQL = """
WITH p AS (
    SELECT pos.drive_id, pos.date, pos.longitude, pos.latitude,
           row_number() OVER (PARTITION BY pos.drive_id ORDER BY pos.date) AS rn,
           count(*) OVER (PARTITION BY pos.drive_id) AS cnt
      FROM positions pos
      JOIN drives d ON d.id = pos.drive_id
     WHERE d.distance IS NOT NULL AND d.id > %(after_id)s
)
SELECT p.drive_id, p.longitude, p.latitude,
       d.start_date, d.distance, d.duration_min
  FROM p JOIN drives d ON d.id = p.drive_id
 WHERE rn = 1 OR rn = cnt OR (rn - 1) %% greatest((cnt / 40)::int, 1) = 0
 ORDER BY d.start_date, p.drive_id, p.date
"""

_tracks_mem: Optional[dict] = None  # {"max_id": int, "tracks": [...]}
_tracks_lock = threading.Lock()


def _map_cache_file() -> str:
    return os.environ.get("MAP_CACHE_FILE") or \
        os.path.join(os.path.dirname(__file__), "..", "data", "tracks_cache.json")


def _drive_max_id() -> int:
    return query("SELECT coalesce(max(id), 0) AS m FROM drives "
                 "WHERE distance IS NOT NULL")[0]["m"]


def _group_tracks(rows: list[dict]) -> list[dict]:
    """把下采样行按行程分组 (SQL 已按 start_date, drive_id 排序保证连续)。"""
    tracks, cur = [], None
    for r in rows:
        if cur is None or r["drive_id"] != cur["id"]:
            cur = {"id": r["drive_id"], "date": fdate(r["start_date"]),
                   "km": round(float(r["distance"]), 1) if r["distance"] else 0.0,
                   "min": r["duration_min"], "pts": []}
            tracks.append(cur)
        cur["pts"].append([round(float(r["longitude"]), 5),
                           round(float(r["latitude"]), 5)])
    return [t for t in tracks if len(t["pts"]) >= 2]


def _query_tracks(after_id: int) -> list[dict]:
    return _group_tracks(query(TRACKS_SQL, {"after_id": after_id}))


def _load_tracks() -> list[dict]:
    """全量轨迹: 首次全库下采样 (慢), 之后内存/磁盘缓存 + 增量追加新行程。"""
    global _tracks_mem
    with _tracks_lock:
        max_id = _drive_max_id()
        if _tracks_mem and _tracks_mem["max_id"] >= max_id:
            return _tracks_mem["tracks"]
        after, merged = -1, []
        if _tracks_mem:  # 内存缓存落后 (有新行程): 从内存增量
            after, merged = _tracks_mem["max_id"], _tracks_mem["tracks"]
        else:  # 进程首次: 尝试磁盘缓存, 从其 max_id 增量
            try:
                with open(_map_cache_file(), encoding="utf-8") as f:
                    data = json.load(f)
                if int(data.get("v", 1)) != TRACKS_CACHE_VERSION:
                    after, merged = -1, []  # 算法版本不符: 全量重建
                else:
                    after, merged = int(data.get("max_id", -1)), data.get("tracks", [])
            except (OSError, ValueError, TypeError):
                after, merged = -1, []
        new = _query_tracks(after) if after < max_id else []
        merged = sorted(merged + new, key=lambda t: t["date"])
        _tracks_mem = {"max_id": max_id, "tracks": merged}
        if new:  # 有新数据才落盘 (原子替换)
            try:
                cf = _map_cache_file()
                os.makedirs(os.path.dirname(cf), exist_ok=True)
                tmp = cf + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump({"v": TRACKS_CACHE_VERSION, "max_id": max_id,
                               "tracks": merged}, f, separators=(",", ":"))
                os.replace(tmp, cf)
            except OSError:
                pass  # 缓存写失败不影响本次响应
        return _tracks_mem["tracks"]


def _warm_tracks():
    try:
        _load_tracks()
    except Exception:
        pass  # 预热失败不影响服务, 首次访问会重试


def _date_or_400(val: str, name: str) -> str:
    """校验 YYYY-MM-DD, 防止坏参数 (如 "NaN-NaN-NaN") 打穿到数据库。"""
    try:
        datetime.strptime(val, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, f"{name} 日期格式错误, 应为 YYYY-MM-DD")
    return val


@mapapi.get("/tracks")
def get_tracks(frm: Optional[str] = Query(None, alias="from"),
               to: Optional[str] = None):
    if frm:
        frm = _date_or_400(frm, "from")   # 先校验再过滤, 空列表也要拦住坏参数
    if to:
        to = _date_or_400(to, "to")
    tracks = _load_tracks()
    if frm:
        tracks = [t for t in tracks if t["date"] >= frm]
    if to:
        tracks = [t for t in tracks if t["date"] <= to]
    return {"count": len(tracks), "tracks": tracks}


# 视野内高精度轨迹: 粗轨迹 (40 点/条) 供全量概览, 缩放到 13 级以上后
# 前端把视野内 drive ids + 视野框发来, 按缩放档位逐级加密, 不走全量缓存。
DETAIL_SQL = """
WITH p AS (
    SELECT pos.drive_id, pos.longitude, pos.latitude,
           row_number() OVER (PARTITION BY pos.drive_id ORDER BY pos.date) AS rn,
           count(*) OVER (PARTITION BY pos.drive_id) AS cnt
      FROM positions pos
     WHERE pos.drive_id = ANY(%(ids)s)
       AND pos.longitude BETWEEN %(w)s AND %(e)s
       AND pos.latitude BETWEEN %(s)s AND %(n)s
)
SELECT p.drive_id, p.longitude, p.latitude
  FROM p
 WHERE rn = 1 OR rn = cnt OR (rn - 1) %% greatest((cnt / %(per)s)::int, 1) = 0
 ORDER BY p.drive_id, rn
"""

# 每条轨迹目标点数: 轨迹不多时全精度 (5000); 密集时按 25 万总点均摊,
# 但每条不低于 2000 —— 旧的总预算固定制会把密集走廊稀释成折线 (用户反馈:
# 总点数应随轨迹数量增长)。响应上限 ~30 万点 (~6MB, gzip 后 ~1MB)。
DETAIL_PER_MAX = 5000
DETAIL_PER_FLOOR = 2000
DETAIL_TOTAL_CAP = 250000
DETAIL_MAX_IDS = 150
DETAIL_WORKERS = 4


def _query_detail(id_list: list[int], per: int, box: dict) -> list[dict]:
    """视野内高精度点位。瓶颈是 drive_id 索引扫描 (~7k 行/条), 拆 4 份并行查。"""
    params = {"per": per, "w": box["w"], "s": box["s"], "e": box["e"], "n": box["n"]}
    if len(id_list) <= 40:
        return query(DETAIL_SQL, {**params, "ids": id_list})
    chunks = [id_list[i::DETAIL_WORKERS] for i in range(DETAIL_WORKERS)]
    with ThreadPoolExecutor(max_workers=DETAIL_WORKERS) as ex:
        parts = list(ex.map(lambda ch: query(DETAIL_SQL, {**params, "ids": ch}), chunks))
    rows = [r for part in parts for r in part]
    # 分组要求 drive_id 连续; 各份 drive_id 互斥, 稳定排序即可合并 (组内顺序不变)
    rows.sort(key=lambda r: r["drive_id"])
    return rows


def _group_detail(rows: list[dict]) -> list[dict]:
    """视野内轨迹按行程分组 (SQL 已按 drive_id 排序保证连续)。"""
    tracks, cur = [], None
    for r in rows:
        if cur is None or r["drive_id"] != cur["id"]:
            cur = {"id": r["drive_id"], "pts": []}
            tracks.append(cur)
        cur["pts"].append([round(float(r["longitude"]), 5),
                           round(float(r["latitude"]), 5)])
    return [t for t in tracks if len(t["pts"]) >= 2]


@mapapi.get("/tracks/detail")
def get_tracks_detail(ids: str, zoom: int = 15,
                      w: float = -180.0, s: float = -90.0,
                      e: float = 180.0, n: float = 90.0):
    try:
        id_list = [int(x) for x in ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(400, "ids 格式错误")
    id_list = id_list[:DETAIL_MAX_IDS]
    if not id_list:
        return {"count": 0, "tracks": []}
    if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
        raise HTTPException(400, "bbox 参数非法")
    per = min(DETAIL_PER_MAX,
              max(DETAIL_PER_FLOOR, DETAIL_TOTAL_CAP // len(id_list)))
    rows = _query_detail(id_list, per, {"w": w, "s": s, "e": e, "n": n})
    tracks = _group_detail(rows)
    return {"count": len(tracks), "tracks": tracks}


@mapapi.post("/diag")
async def map_diag(request: Request):
    """浏览器端诊断上报 (排查地图加载问题), 只写日志不落库。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    print(f"MAPDIAG {json.dumps(body, ensure_ascii=False)[:800]}", flush=True)
    return {"ok": True}


# ---------------------------------------------------------------- 行程轨迹页
# 页面: /tesla/trips —— 行程卡片瀑布流 + 点击查看单条全精度轨迹
trips = APIRouter(prefix="/tesla/trips/api")

# 只列已完成的行程: TeslaMate 记录中断会留下 end_date 为空的"未关闭"行程
# (无里程/起终点, Grafana 行程面板同样不显示), 与地图页 TRACKS_SQL
# (d.distance IS NOT NULL) 的过滤口径一致。
TRIPS_BASE = """
SELECT d.id, d.start_date, d.end_date, d.distance, d.duration_min, d.speed_max,
       sa.display_name AS start_addr, ea.display_name AS end_addr
  FROM drives d
  LEFT JOIN addresses sa ON sa.id = d.start_address_id
  LEFT JOIN addresses ea ON ea.id = d.end_address_id
 WHERE d.end_date IS NOT NULL
"""
TRIPS_SQL = TRIPS_BASE + """
 ORDER BY d.start_date DESC
 LIMIT %(limit)s OFFSET %(offset)s
"""
TRIPS_ONE_SQL = TRIPS_BASE + " AND d.id = %(id)s"
TRIPS_IDS_SQL = TRIPS_BASE + " AND d.id = ANY(%(ids)s) ORDER BY d.start_date"
MERGED_TRACK_SQL = """
WITH p AS (
    SELECT pos.drive_id, pos.longitude, pos.latitude, pos.speed, pos.power, pos.date,
           row_number() OVER (PARTITION BY pos.drive_id ORDER BY pos.date) AS rn,
           count(*) OVER (PARTITION BY pos.drive_id) AS cnt
      FROM positions pos
     WHERE pos.drive_id = ANY(%(ids)s)
)
SELECT p.drive_id, p.longitude, p.latitude, p.speed, p.power, p.date
  FROM p
 WHERE rn = 1 OR rn = cnt OR (rn - 1) %% greatest((cnt / %(per)s)::int, 1) = 0
 ORDER BY p.date
"""


def _clean_addr(s: str | None) -> str:
    """地址去掉反查带来的尾部悬挂逗号/空白。"""
    return (s or "未知位置").rstrip(", ").strip()[:80] or "未知位置"


def _trip_item(r):
    """drives 行 → 前端行程卡片字段 (列表与单条共用)。"""
    return {
        "id": r["id"],
        "date": fdate(r["start_date"]),
        "start": ftime(r["start_date"]),
        "end": ftime(r["end_date"]) if r["end_date"] else None,
        "km": round(v, 2) if (v := fnum(r["distance"])) is not None else None,
        "min": r["duration_min"],
        "speed_max": r["speed_max"],
        "from": _clean_addr(r["start_addr"]),
        "to": _clean_addr(r["end_addr"]),
    }


@trips.get("/sessions")
def get_trip_sessions(offset: int = 0, limit: int = 24):
    if offset < 0 or not 1 <= limit <= 100:
        raise HTTPException(400, "分页参数非法")
    total = query("SELECT count(*) AS n FROM drives "
                  "WHERE end_date IS NOT NULL")[0]["n"]
    rows = query(TRIPS_SQL, {"limit": limit, "offset": offset})
    return {"total": total, "items": [_trip_item(r) for r in rows]}


@trips.get("/sessions/{drive_id}")
def get_trip_session(drive_id: int):
    """单条行程信息: 分享链接 /tesla/trips?id=X 直开弹层时前端拉取。"""
    rows = query(TRIPS_ONE_SQL, {"id": drive_id})
    if not rows:
        raise HTTPException(404, "行程不存在或未完成")
    return _trip_item(rows[0])


@trips.get("/merged")
def get_merged_track(ids: str):
    """多选连续行程 → 一条连续轨迹 (分享链接 /tesla/trips?ids=a,b,c)。
    ts 为"累计行驶秒": 行程间的停驶时间剔除, 否则跨天合并后播放进度和
    实时时长全被停车时间淹没; pts/ts 结构与单条轨迹接口一致。"""
    try:
        id_list = list(dict.fromkeys(int(x) for x in ids.split(",")))
    except ValueError:
        raise HTTPException(400, "ids 参数非法")
    if not 2 <= len(id_list) <= 50:
        raise HTTPException(400, "ids 需为 2~50 个行程")
    drows = query(TRIPS_IDS_SQL, {"ids": id_list})
    if len(drows) != len(id_list):
        raise HTTPException(404, "包含不存在或未完成的行程")
    # 下采样预算: 每条行程最多 ~4000/n 个点, 多条合并总量与单条相当
    prows = query(MERGED_TRACK_SQL,
                  {"ids": id_list, "per": max(200, 4000 // len(id_list))})
    if len(prows) < 2:
        raise HTTPException(404, "这些行程没有轨迹数据")
    pts, ts = [], []
    base = 0.0                    # 已计入的行驶秒 (不含行程间停驶)
    cur_drive, t0, last = None, None, None
    for r in prows:
        if r["drive_id"] != cur_drive:          # 换行程: 累计上一段的行驶时长
            if t0 is not None:
                base += (last - t0).total_seconds()
            cur_drive, t0 = r["drive_id"], r["date"]
        last = r["date"]
        pts.append([round(float(r["longitude"]), 5), round(float(r["latitude"]), 5),
                    r["speed"] or 0, r["power"]])
        ts.append(round(base + (r["date"] - t0).total_seconds()))
    first, last_row = drows[0], drows[-1]
    return {
        "ids": [r["id"] for r in drows],
        "n": len(drows),
        "pts": pts, "ts": ts,
        "date": fdate(first["start_date"]),
        "start": ftime(first["start_date"]),
        "end": ftime(last_row["end_date"]),
        "km": round(sum(r["distance"] or 0 for r in drows), 2),
        "min": sum(r["duration_min"] or 0 for r in drows),
        "speed_max": max((r["speed_max"] or 0) for r in drows) or None,
        "from": _clean_addr(first["start_addr"]),
        "to": _clean_addr(last_row["end_addr"]),
    }


# 行程弹层轨迹: 整条 (无视野框), 每点带车速 km/h, 供前端按速度着色 (慢红快绿)
TRIP_TRACK_SQL = """
WITH p AS (
    SELECT pos.longitude, pos.latitude, pos.speed, pos.power, pos.date,
           row_number() OVER (ORDER BY pos.date) AS rn,
           count(*) OVER () AS cnt
      FROM positions pos
     WHERE pos.drive_id = %(id)s
)
SELECT p.longitude, p.latitude, p.speed, p.power, p.date
  FROM p
 WHERE rn = 1 OR rn = cnt OR (rn - 1) %% greatest((cnt / %(per)s)::int, 1) = 0
 ORDER BY rn
"""


@trips.get("/{drive_id}/track")
def get_trip_track(drive_id: int):
    """单条行程全精度轨迹: pts 为 [lng, lat, speed_km_h, power_W]
    (power 正=放电 负=动能回收, 可能为 null); ts 为相对起点的秒偏移
    (与 pts 下标对齐, 播放动画里用来算"已行驶时长"和平均功耗)。"""
    rows = query(TRIP_TRACK_SQL, {"id": drive_id, "per": 5000})
    pts = [[round(float(r["longitude"]), 5), round(float(r["latitude"]), 5),
            r["speed"] or 0, r["power"]] for r in rows]
    if len(pts) < 2:
        raise HTTPException(404, "该行程没有轨迹数据")
    t0 = rows[0]["date"]
    ts = [round((r["date"] - t0).total_seconds()) for r in rows]
    return {"id": drive_id, "pts": pts, "ts": ts}


# ---------------------------------------------------------------- 静态页面

def _page(fname: str) -> FileResponse:
    """HTML 页面: 允许缓存但必须带 ETag 重新校验 (no-cache), 更新即时生效。"""
    resp = FileResponse(os.path.join(STATIC_DIR, fname))
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.get("/")
def root():
    return RedirectResponse("/tesla", status_code=302)


@app.get("/tesla")
def tesla_home():
    return RedirectResponse("/tesla/charging", status_code=302)


@app.get("/tesla/charging")
def charging_page():
    return _page("index.html")


@app.get("/tesla/map")
def map_page():
    return _page("map.html")


@app.get("/tesla/trips")
def trips_page():
    return _page("trips.html")


app.include_router(charging)
app.include_router(mapapi)
app.include_router(trips)
app.mount("/tesla/static", StaticFiles(directory=STATIC_DIR), name="static")
