"""充电记录展示服务 —— 后端 API。

数据源: teslamate_cn (PostgreSQL, TeslaMate 标准表结构)。
时间处理: 库内为 UTC 裸时间戳, 对外输出本地时间 (默认 Asia/Shanghai)。
"""
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from psycopg.rows import dict_row

from .db import make_pool

LOCAL_TZ = ZoneInfo(os.environ.get("TZ_NAME", "Asia/Shanghai"))
CUR_SYMBOL = os.environ.get("CUR_SYMBOL", "¥")
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

pool = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global pool
    pool = make_pool()
    yield
    pool.close()


app = FastAPI(title="Tesla 充电记录", lifespan=lifespan)


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

@app.get("/api/car")
def get_car():
    rows = query("SELECT id, name, model, trim_badging, vin FROM cars")
    return [{"id": r["id"], "name": r["name"], "model": r["model"],
             "trim_badging": r["trim_badging"], "vin": r["vin"]} for r in rows]


@app.get("/api/summary")
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


@app.get("/api/sessions")
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


@app.get("/api/sessions/{session_id}")
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


@app.get("/api/monthly")
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


@app.get("/api/locations")
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


# ---------------------------------------------------------------- 静态页面

@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/", StaticFiles(directory=STATIC_DIR), name="static")
