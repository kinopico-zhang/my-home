"""数据访问层: 全部 SQLAlchemy 查询 + 行 → Pydantic 模型转换。

约定:
- 只读 TeslaMate 库 (写点仅两处: 费用回写 update_charging_cost 落原库,
  断档补路 save_fill 落自有库 data/mytesla.db);
- 查询保持方言中立 (生产 Postgres, 测试 SQLite): 不用 ANY / AT TIME ZONE /
  FILTER / ILIKE / to_char 等 Postgres 专有语法, 时区换算、月份分组、
  排序分页都在 Python 侧;
- 本地日期 → UTC 边界、停驶剔除等行为与旧版 SQL 逐字段对齐。
"""
from collections.abc import Iterable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from functools import lru_cache
import json
import math
import re

from typing import Any, NamedTuple

from sqlalchemy import ColumnElement, Select, case, delete, func, or_, select
from sqlalchemy.orm import InstrumentedAttribute, Session, aliased, sessionmaker
from sqlalchemy.sql.selectable import Subquery

from . import config
from .models import (Address, Car, Charge, ChargingProcess, Drive, Geofence,
                     Position, TrackFill)
from .schemas import (
    CarInfo,
    ChargeCurve,
    ChargingSession,
    ChargingSessionDetail,
    ChargingSummary,
    CityCount,
    CostUpdateResult,
    GapFillRequest,
    LocationStat,
    MapDetailTrack,
    MapSummary,
    MapTrack,
    MergedTrack,
    MonthlyStat,
    RegionNode,
    TripItem,
    TripRegions,
    TripTrack,
)


class NotFound(LookupError):
    """查无数据 (路由捕获后转 404, detail 用异常消息)。"""


# ---------------------------------------------------------------- 时间与参数


def to_local(dt: datetime) -> datetime:
    """库内 UTC 裸时间戳 → 本地时间 (默认北京时间)。"""
    return dt.replace(tzinfo=dt_timezone.utc).astimezone(config.LOCAL_TZ)


def fdate(dt: datetime) -> str:
    """本地日期 (YYYY-MM-DD)。"""
    return to_local(dt).strftime("%Y-%m-%d")


def ftime(dt: datetime) -> str:
    """本地时间 (YYYY-MM-DD HH:MM)。"""
    return to_local(dt).strftime("%Y-%m-%d %H:%M")


def _fnum(value: float | int | None) -> float | None:
    return None if value is None else float(value)


@dataclass(frozen=True)
class DateRange:
    """本地日期区间 → 库内 UTC 裸时间戳边界 ([start, end), end 为 to 次日零点)。"""

    start: datetime | None
    end: datetime | None


def _local_date_to_utc(date_str: str, days: int = 0) -> datetime:
    """本地日期零点 (默认北京时间) → UTC 裸时间戳。

    与原 SQL `date AT TIME ZONE 'Asia/Shanghai' AT TIME ZONE 'UTC'` 等价。
    """
    naive = datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=days)
    return naive.replace(tzinfo=config.LOCAL_TZ).astimezone(
        dt_timezone.utc).replace(tzinfo=None)


def parse_date_range(frm: str | None, to: str | None) -> DateRange | None:
    """解析 from/to 查询参数 (YYYY-MM-DD); 非法格式抛 ValueError (路由转 400)。"""
    if not frm and not to:
        return None
    try:
        start = _local_date_to_utc(frm) if frm else None
        end = _local_date_to_utc(to, days=1) if to else None
    except ValueError as exc:
        raise ValueError("日期格式错误, 应为 YYYY-MM-DD") from exc
    return DateRange(start=start, end=end)


@dataclass(frozen=True)
class BBox:
    """地图视野框 (西/南/东/北)。"""

    west: float
    south: float
    east: float
    north: float


def _keep_indices(count: int, per: int) -> list[int]:
    """下采样保留的下标 (0-based): 首末点必留, 中间等间隔取。

    与旧版 SQL `rn=1 OR rn=cnt OR (rn-1) % greatest(cnt/per, 1) = 0` 等价。
    """
    stride = max(count // per, 1)
    return [i for i in range(count)
            if i == 0 or i == count - 1 or i % stride == 0]


def _clean_addr(s: str | None) -> str:
    """地址去掉反查带来的尾部悬挂逗号/空白。"""
    return (s or "未知位置").rstrip(", ").strip()[:80] or "未知位置"


# ---------------------------------------------------------------- 车辆


def list_cars(session: Session) -> list[CarInfo]:
    """车辆信息。"""
    rows = session.execute(
        select(Car.id, Car.name, Car.model, Car.trim_badging, Car.vin)
        .order_by(Car.id)).all()
    return [CarInfo(id=cid, name=name, model=model, trim_badging=trim, vin=vin)
            for cid, name, model, trim, vin in rows]


# ---------------------------------------------------------------- 充电


@dataclass
class ChargeAgg:
    """一次充电过程的采样聚合 (峰值功率 / 是否快充)。"""

    power_max: float | None
    is_fast: bool


_NO_AGG = ChargeAgg(power_max=None, is_fast=False)


def _charge_aggs(session: Session,
                 process_ids: Sequence[int]) -> dict[int, ChargeAgg]:
    """charges 采样聚合: max(功率) 与 bool_or(快充) 的方言中立等价写法。

    快充判定与旧 SQL 一致: fast_charger_present 为真 或 功率 ≥ 20kW;
    没有采样点的过程不在返回里 (等价 power_max=NULL, is_fast=false)。
    """
    if not process_ids:
        return {}
    fast_case = case(
        (or_(Charge.fast_charger_present.is_(True), Charge.charger_power >= 20), 1),
        else_=0)
    rows = session.execute(
        select(Charge.charging_process_id, func.max(Charge.charger_power),
               func.max(fast_case))
        .where(Charge.charging_process_id.in_(process_ids))
        .group_by(Charge.charging_process_id)).all()
    return {pid: ChargeAgg(power_max=pmax, is_fast=bool(fast))
            for pid, pmax, fast in rows}


def _range_conditions(column: InstrumentedAttribute[datetime],
                      date_range: DateRange | None) -> list[ColumnElement[bool]]:
    conds: list[ColumnElement[bool]] = []
    if date_range is not None:
        if date_range.start is not None:
            conds.append(column >= date_range.start)
        if date_range.end is not None:
            conds.append(column < date_range.end)
    return conds


@dataclass
class ChargeRow:
    """充电过程 + 关联地址/围栏 + 采样聚合 (列表/详情/汇总共用)。"""

    process: ChargingProcess
    address: Address | None
    geofence: Geofence | None
    agg: ChargeAgg


def _charge_rows(session: Session, date_range: DateRange | None,
                 q: str | None) -> list[ChargeRow]:
    """按日期区间与地址关键字取充电过程 (不排序不分页, 交由调用方)。"""
    conds: list[ColumnElement[bool]] = _range_conditions(ChargingProcess.start_date, date_range)
    if q:
        haystack = func.concat(
            func.coalesce(Geofence.name, ""), " ",
            func.coalesce(Address.name, ""), " ",
            func.coalesce(Address.city, ""), " ",
            func.coalesce(Address.display_name, ""))
        conds.append(func.lower(haystack).like(f"%{q.lower()}%"))
    stmt = (select(ChargingProcess, Address, Geofence)
            .join(Address, Address.id == ChargingProcess.address_id, isouter=True)
            .join(Geofence, Geofence.id == ChargingProcess.geofence_id, isouter=True))
    if conds:
        stmt = stmt.where(*conds)
    rows = [ChargeRow(process=cp, address=a, geofence=g, agg=_NO_AGG)
            for cp, a, g in session.execute(stmt).all()]
    _attach_aggs(session, rows)
    return rows


def _charge_rows_by_ids(session: Session,
                        ids: Sequence[int]) -> list[ChargeRow]:
    stmt = (select(ChargingProcess, Address, Geofence)
            .join(Address, Address.id == ChargingProcess.address_id, isouter=True)
            .join(Geofence, Geofence.id == ChargingProcess.geofence_id, isouter=True)
            .where(ChargingProcess.id.in_(ids)))
    rows = [ChargeRow(process=cp, address=a, geofence=g, agg=_NO_AGG)
            for cp, a, g in session.execute(stmt).all()]
    _attach_aggs(session, rows)
    return rows


def _attach_aggs(session: Session, rows: list[ChargeRow]) -> None:
    aggs = _charge_aggs(session, [row.process.id for row in rows])
    for row in rows:
        row.agg = aggs.get(row.process.id, _NO_AGG)


def _location_name(row: ChargeRow) -> str:
    if row.geofence is not None and row.geofence.name:
        return row.geofence.name
    if row.address is not None and row.address.name:
        return row.address.name
    return "未知位置"


def _session_item(row: ChargeRow) -> ChargingSession:
    cp = row.process
    energy_used = _fnum(cp.charge_energy_used)
    energy_added = _fnum(cp.charge_energy_added)
    cost = _fnum(cp.cost)
    base = energy_used or energy_added
    return ChargingSession(
        id=cp.id,
        start=ftime(cp.start_date),
        end=ftime(cp.end_date) if cp.end_date else None,
        date=fdate(cp.start_date),
        location=_location_name(row),
        city=row.address.city if row.address else None,
        address=row.address.display_name if row.address else None,
        start_soc=cp.start_battery_level,
        end_soc=cp.end_battery_level,
        energy_added=energy_added,
        energy_used=energy_used,
        cost=cost,
        price_per_kwh=round(cost / base, 3) if cost and base else None,
        duration_min=cp.duration_min,
        outside_temp=_fnum(cp.outside_temp_avg),
        power_max=row.agg.power_max,
        is_fast=row.agg.is_fast)


def _cost_of(row: ChargeRow) -> float | None:
    return row.process.cost


def _energy_of(row: ChargeRow) -> float | None:
    return row.process.charge_energy_used


def _duration_of(row: ChargeRow) -> int | None:
    return row.process.duration_min


def _power_of(row: ChargeRow) -> float | None:
    return row.agg.power_max


_SORT_FIELDS = {
    "cost_desc": _cost_of, "cost_asc": _cost_of,
    "energy_desc": _energy_of, "energy_asc": _energy_of,
    "duration_desc": _duration_of, "power_desc": _power_of,
}

SORT_OPTIONS = set(_SORT_FIELDS) | {"date_desc", "date_asc"}


def _sorted_charge_rows(rows: list[ChargeRow], sort: str) -> list[ChargeRow]:
    """排序; None 值排最后 (等价 Postgres NULLS LAST)。

    元组键的第一位保证 None 之间不再比较数值位 (None < None 会抛 TypeError)。
    """
    if sort == "date_desc":
        return sorted(rows, key=lambda r: r.process.start_date, reverse=True)
    if sort == "date_asc":
        return sorted(rows, key=lambda r: r.process.start_date)
    field = _SORT_FIELDS[sort]
    if sort.endswith("_asc"):
        return sorted(rows, key=lambda r: (field(r) is None, field(r)))
    return sorted(rows, key=lambda r: (field(r) is not None, field(r)),
                  reverse=True)


@dataclass(frozen=True)
class SessionFilter:
    """充电列表查询条件 (路由与仓库之间避免长参数列表)。"""

    date_range: DateRange | None
    charge_type: str        # all / fast / slow
    query: str | None       # 地址模糊搜索
    sort: str               # SORT_OPTIONS 之一
    offset: int
    limit: int
    city: str | None = None    # 充电城市 (空 = 全部)


def list_charging_sessions(session: Session,
                           flt: SessionFilter) -> tuple[int, list[ChargingSession]]:
    """充电列表: 日期/类型/搜索过滤 → 排序 → 分页; total 为过滤后总数。"""
    rows = _charge_rows(session, flt.date_range, flt.query)
    if flt.charge_type == "fast":
        rows = [row for row in rows if row.agg.is_fast]
    elif flt.charge_type == "slow":
        rows = [row for row in rows if not row.agg.is_fast]
    if flt.city:      # 无地址/无城市的充电不参与城市筛选
        rows = [row for row in rows
                if row.address is not None and row.address.city == flt.city]
    total = len(rows)
    rows = _sorted_charge_rows(rows, flt.sort)
    page = rows[flt.offset:flt.offset + flt.limit]
    return total, [_session_item(row) for row in page]


def charging_session_detail(session: Session,
                            session_id: int) -> ChargingSessionDetail | None:
    """充电详情: 卡片字段 + 采样曲线 / 充电线缆 / 快充品牌。"""
    rows = _charge_rows_by_ids(session, [session_id])
    if not rows:
        return None
    row = rows[0]
    cp = row.process
    samples = session.scalars(
        select(Charge).where(Charge.charging_process_id == session_id)
        .order_by(Charge.date)).all()

    def _clean(value: str | None) -> str | None:
        return value if value and value != "<invalid>" else None

    cable = next((c.conn_charge_cable for c in samples if c.conn_charge_cable), None)
    brand = _clean(next(
        (c.fast_charger_brand for c in samples if c.fast_charger_brand), None))
    charger_type = _clean(next(
        (c.fast_charger_type for c in samples if c.fast_charger_type), None))
    base = _session_item(row)
    return ChargingSessionDetail(
        **base.model_dump(),
        start_rated_range=_fnum(cp.start_rated_range_km),
        end_rated_range=_fnum(cp.end_rated_range_km),
        cable=cable, charger_brand=brand, charger_type=charger_type,
        curve=ChargeCurve(
            minutes=[round((c.date - cp.start_date).total_seconds() / 60, 1)
                     for c in samples],
            soc=[c.battery_level for c in samples],
            kw=[_fnum(c.charger_power) for c in samples],
            voltage=[_fnum(c.charger_voltage) for c in samples],
            current=[_fnum(c.charger_actual_current) for c in samples],
            energy=[_fnum(c.charge_energy_added) for c in samples]))


def update_charging_cost(session: Session, session_id: int,
                         cost: float | None) -> CostUpdateResult | None:
    """更新 / 添加 / 清除一条充电记录的费用 (唯一写库点, 金额已由路由校验)。

    返回 None 表示记录不存在。
    """
    process = session.get(ChargingProcess, session_id)
    if process is None:
        return None
    base = float(process.charge_energy_used or 0) \
        or float(process.charge_energy_added or 0)
    process.cost = round(cost, 2) if cost is not None else None
    session.commit()
    price = round(cost / base, 3) if cost is not None and base else None
    return CostUpdateResult(ok=True, cost=cost, price_per_kwh=price)


def list_charging_cities(session: Session) -> list[CityCount]:
    """充电城市列表 (按充电次数降序); 无城市信息的充电不参与筛选。"""
    rows = session.execute(
        select(Address.city, func.count())
        .join(ChargingProcess, ChargingProcess.address_id == Address.id)
        .where(Address.city.is_not(None), Address.city != "")
        .group_by(Address.city)
        .order_by(func.count().desc())).all()
    return [CityCount(city=city, count=int(n)) for city, n in rows]


def charging_summary(session: Session,
                     date_range: DateRange | None) -> ChargingSummary:
    """充电汇总: 次数 / 电量 / 费用 / 快充占比 / SOC 与续航增益。"""
    rows = _charge_rows(session, date_range, None)
    energy_added = sum(r.process.charge_energy_added or 0.0 for r in rows)
    energy_used = sum(r.process.charge_energy_used or 0.0 for r in rows)
    cost = sum(r.process.cost or 0.0 for r in rows)
    duration = sum(r.process.duration_min or 0 for r in rows)
    fast = sum(1 for r in rows if r.agg.is_fast)
    soc_gain = sum((r.process.end_battery_level or 0) -
                   (r.process.start_battery_level or 0) for r in rows)
    range_gain = sum((r.process.end_rated_range_km or 0.0) -
                     (r.process.start_rated_range_km or 0.0) for r in rows)
    dates = [r.process.start_date for r in rows]
    energy = energy_used or energy_added
    return ChargingSummary(
        sessions=len(rows), fast_sessions=fast,
        energy_added=float(energy_added), energy_used=float(energy_used),
        cost=round(cost, 2) if cost else 0.0,
        price_per_kwh=round(cost / energy, 3) if energy else None,
        duration_min=duration, soc_gain=int(soc_gain),
        range_gain=round(float(range_gain), 1),
        first_date=fdate(min(dates)) if dates else None,
        last_date=fdate(max(dates)) if dates else None)


def monthly_stats(session: Session,
                  date_range: DateRange | None) -> list[MonthlyStat]:
    """按本地月份分组的充电统计 (分组在 Python 侧, 免 to_char 方言差异)。"""
    rows = _charge_rows(session, date_range, None)
    grouped: dict[str, list[ChargeRow]] = {}
    for row in rows:
        grouped.setdefault(
            to_local(row.process.start_date).strftime("%Y-%m"), []).append(row)
    return [MonthlyStat(
        month=month, sessions=len(group),
        energy_used=_sum_field(group, "charge_energy_used"),
        cost=_sum_field(group, "cost"),
        fast_sessions=sum(1 for r in group if r.agg.is_fast))
        for month, group in sorted(grouped.items())]


def location_stats(session: Session,
                   date_range: DateRange | None) -> list[LocationStat]:
    """按充电地点 (围栏优先, 否则地址名) 分组的统计, 按次数降序。"""
    rows = _charge_rows(session, date_range, None)
    grouped: dict[tuple[str, str | None], list[ChargeRow]] = {}
    for row in rows:
        grouped.setdefault(
            (_location_name(row), row.address.city if row.address else None),
            []).append(row)
    stats = [LocationStat(
        location=location, city=city, sessions=len(group),
        energy_used=_sum_field(group, "charge_energy_used"),
        cost=_sum_field(group, "cost"),
        fast_sessions=sum(1 for r in group if r.agg.is_fast))
        for (location, city), group in grouped.items()]
    stats.sort(key=lambda s: s.sessions, reverse=True)
    return stats


def _sum_field(rows: list[ChargeRow], field: str) -> float | None:
    """对行的 process 属性求和 (忽略 None); 全空返回 None。"""
    values = [v for row in rows
              if (v := getattr(row.process, field)) is not None]
    return float(sum(values)) if values else None


# ---------------------------------------------------------------- 行程


def _trip_item(drive: Drive, start_addr: str | None,
               end_addr: str | None) -> TripItem:
    return TripItem(
        id=drive.id,
        date=fdate(drive.start_date),
        start=ftime(drive.start_date),
        end=ftime(drive.end_date) if drive.end_date else None,
        km=round(float(drive.distance), 2) if drive.distance is not None else None,
        min=drive.duration_min,
        speed_max=drive.speed_max,
        from_=_clean_addr(start_addr),
        to=_clean_addr(end_addr))


@dataclass(frozen=True)
class TripFilter:
    """行程列表过滤条件 (顶栏时间 + 筛选行起终地区 / 里程)。

    from_loc / to_loc 是 "/" 连接的省市区路径 (1~3 段):
    "广东省"=整省, "广东省/深圳市"=整市, "广东省/深圳市/龙华区"=精确到区县。
    """

    date_range: DateRange | None = None
    from_loc: str | None = None     # 起点地区 (空 = 全部)
    to_loc: str | None = None       # 终点地区 (空 = 全部)
    km_min: float | None = None     # 里程下限 (km)
    km_max: float | None = None     # 里程上限 (km)


# ---------------------------------------------------------------- 省市区解析
# TeslaMate (OSM) 的 display_name 是逗号分隔、从细到粗的地址链:
# "POI, 路, 街道/镇, 区县, 市, 省, 邮编, 中国", 但市/区偶尔重复或缺失
# ("…, 顺德区, 佛山市, 顺德区, 广东省", 省直辖县没有市)。addresses 的
# city 列则混着 市/区/街道, 不能当层级用 —— 三级只能从 display_name 解析。

_PROV_SUF = ("省", "自治区", "特别行政区")
_CITY_SUF = ("市", "盟", "地区", "自治州")
_DIST_SUF = ("区", "县", "旗", "镇", "街道", "市")
_LEGACY_RE = re.compile(r"^(?:(.{1,12}?(?:省|自治区))?)\s*(?:(.{1,12}?市)?)"
                        r"\s*(?:(.{1,12}?(?:区|县|镇|街道))?)")


def _suffixed(token: str, suffixes: tuple[str, ...]) -> bool:
    return any(token.endswith(s) for s in suffixes)


def _scan_left(parts: list[str], start: int, suffixes: tuple[str, ...],
               window: int = 2) -> int:
    """从 start 向左 window 格内找第一个以后缀结尾的 token 下标 (找不到 = -1)。"""
    for j in range(start - 1, max(-1, start - 1 - window), -1):
        if _suffixed(parts[j], suffixes):
            return j
    return -1


@lru_cache(maxsize=4096)
def parse_region(display_name: str) -> tuple[str | None, str | None, str | None]:
    """display_name → (省, 市, 区县)。

    兼容两种格式: OSM 逗号链 (向左窗口扫描, 容忍重复/缺失/邮编/中国大陆)
    和旧版连写 "广东省深圳市龙岗区坂田街道"。解析不出省 = 无地区信息。
    """
    if not display_name:
        return (None, None, None)
    if "," not in display_name:
        m = _LEGACY_RE.match(display_name)
        g = m.groups() if m else (None, None, None)
        return (g[0] or None, g[1] or None, g[2] or None)
    parts = [p.strip() for p in display_name.split(",") if p.strip()]
    i = len(parts) - 1
    while i >= 0 and (parts[i] in ("中国", "中国大陆") or parts[i].isdigit()):
        i -= 1
    if i < 0 or not _suffixed(parts[i], _PROV_SUF):
        return (None, None, None)
    prov = parts[i]
    city = dist = None
    cj = _scan_left(parts, i, _CITY_SUF)
    if cj >= 0:
        city = parts[cj]
        dj = _scan_left(parts, cj, _DIST_SUF)
        if dj >= 0:
            dist = parts[dj]
    else:                       # 省直辖县: 没有市级, 区县提升到市层
        dj = _scan_left(parts, i, _DIST_SUF)
        if dj >= 0:
            city = parts[dj]
    return (prov, city, dist)


def region_address_ids(session: Session, path: str) -> list[int]:
    """省市区路径 → 命中的地址 id 列表 (段数即精确到哪一级)。

    空路径返回 []; 无命中返回 [] (调用方 in_([]) 自然过滤成空列表)。
    """
    segs = [s for s in (p.strip() for p in path.split("/")) if s]
    if not segs:
        return []
    ids: list[int] = []
    for aid, name in session.execute(select(Address.id, Address.display_name)).all():
        prov, city, dist = parse_region(name or "")
        if (prov == segs[0]
                and (len(segs) < 2 or city == segs[1])
                and (len(segs) < 3 or dist == segs[2])):
            ids.append(aid)
    return ids


def _trip_rows_stmt(start_addr: type[Address],
                    end_addr: type[Address]) -> Select[Any]:
    """行程查询骨架: 只取已结束行程, 带起终点地址 (结束时间降序交给调用方)。"""
    return (select(Drive, start_addr.display_name, end_addr.display_name)
            .join(start_addr, Drive.start_address_id == start_addr.id, isouter=True)
            .join(end_addr, Drive.end_address_id == end_addr.id, isouter=True)
            .where(Drive.end_date.is_not(None)))


def _trip_conditions(session: Session,
                     flt: TripFilter | None) -> list[ColumnElement[bool]]:
    """时间 / 起终地区 / 里程过滤条件 (计数与列表共用)。"""
    conds = _range_conditions(Drive.start_date, flt.date_range if flt else None)
    if flt:
        if flt.from_loc:
            conds.append(Drive.start_address_id.in_(
                region_address_ids(session, flt.from_loc)))
        if flt.to_loc:
            conds.append(Drive.end_address_id.in_(
                region_address_ids(session, flt.to_loc)))
        if flt.km_min is not None:
            conds.append(Drive.distance >= flt.km_min)
        if flt.km_max is not None:
            conds.append(Drive.distance <= flt.km_max)
    return conds


def list_trips(session: Session, offset: int, limit: int,
               flt: TripFilter | None = None) -> tuple[int, list[TripItem]]:
    """行程列表 (最新在前), total 为已结束行程数; 按出发时间/起终地区/里程过滤。"""
    conds = _trip_conditions(session, flt)
    total = session.scalar(
        select(func.count()).select_from(Drive)
        .where(Drive.end_date.is_not(None), *conds)) or 0
    rows = session.execute(
        _trip_rows_stmt(aliased(Address), aliased(Address)).where(*conds)
        .order_by(Drive.start_date.desc())
        .offset(offset).limit(limit)).all()
    return int(total), [_trip_item(d, s, e) for d, s, e in rows]


class _RegionAcc:
    """建树用的临时累加器: 数 count, children 最后统一排序转 RegionNode。"""

    def __init__(self, name: str) -> None:
        """建一个 0 计数的空节点。"""
        self.name = name
        self.count = 0
        self.children: dict[str, _RegionAcc] = {}

    def child(self, name: str) -> "_RegionAcc":
        """取子节点 (没有就建)。"""
        node = self.children.get(name)
        if node is None:
            node = self.children[name] = _RegionAcc(name)
        return node

    def node(self) -> RegionNode:
        """转出定型的 RegionNode (children 按次数降序)。"""
        return RegionNode(
            name=self.name, count=self.count,
            children=[c.node() for c in
                      sorted(self.children.values(), key=lambda c: -c.count)])


def _region_tree(session: Session,
                 address_id: InstrumentedAttribute[int | None]) -> list[RegionNode]:
    """某个地址角色 (起点/终点) 的省→市→区县计数树 (次数降序, 未结束行程不计)。

    无省信息的地址 (解析不出省) 不进树, 但仍参与列表展示。
    """
    addr = aliased(Address)
    rows = session.execute(
        select(addr.display_name)
        .select_from(Drive)
        .join(addr, address_id == addr.id, isouter=True)
        .where(Drive.end_date.is_not(None))).all()
    root = _RegionAcc("")
    for (name,) in rows:
        prov, city, dist = parse_region(name or "")
        if not prov:
            continue
        prov_acc = root.child(prov)
        prov_acc.count += 1
        if city:
            city_acc = prov_acc.child(city)
            city_acc.count += 1
            if dist:
                dist_acc = city_acc.child(dist)
                dist_acc.count += 1
    return [c.node() for c in
            sorted(root.children.values(), key=lambda c: -c.count)]


def list_trip_regions(session: Session) -> TripRegions:
    """行程起终点省市区树 (级联下拉数据源)。"""
    return TripRegions(
        start=_region_tree(session, Drive.start_address_id),
        end=_region_tree(session, Drive.end_address_id))


def get_trip(session: Session, drive_id: int) -> TripItem | None:
    """单条行程 (未结束 / 不存在返回 None)。"""
    rows = session.execute(
        _trip_rows_stmt(aliased(Address), aliased(Address))
        .where(Drive.id == drive_id)).all()
    return _trip_item(rows[0][0], rows[0][1], rows[0][2]) if rows else None


TRIP_TRACK_PER = 5000

# 断档补路 (隧道/信号丢失): 原始采样不动, 补出来的点全部存自有库,
# 轨迹接口在服务端拼好 —— 所有消费方都不再看到断档, 前端也不用每次
# 重新调高德规划。own 参数即自有库会话 (与 TeslaMate 会话隔离)。

EARTH_RADIUS_KM = 6371.0
GAP_ANCHOR_MAX_KM = 0.15   # 断档端点离真实轨迹点多近才算锚上 (规划结果与采样本就有几十米差)


def _wgs_km(a: Sequence[float], b: Sequence[float]) -> float:
    """两个 WGS [lng, lat] 点的近似球面距离 (等距圆柱投影, 与前端
    TrackUtil.ptDistKm 同口径)。"""
    mid_lat = math.radians((a[1] + b[1]) / 2)
    dx = math.radians(b[0] - a[0]) * math.cos(mid_lat)
    dy = math.radians(b[1] - a[1])
    return EARTH_RADIUS_KM * math.hypot(dx, dy)


class _TrackPoint(NamedTuple):
    """轨迹点 (原始采样或补路插入), 合并轨迹按 drive_id 分段。"""

    drive_id: int
    date: datetime
    lng: float
    lat: float
    speed: float
    power: float | None


def _interpolated_fill(a: Position, b: Position,
                       path: list[list[float]]) -> list[_TrackPoint]:
    """补路折线 → 插值后的轨迹点 (date 按弧长比例落在两锚点间, speed
    在两锚点速度间线性, power 置 None —— 推算值不冒充实测)。

    高德路线的首尾就是断档端点本身, 与锚点重合的去掉, 不然轨迹出现重复点。"""
    # 弧长参数: 锚点 a → path → 锚点 b
    chain = [[a.longitude, a.latitude], *path, [b.longitude, b.latitude]]
    cum = [0.0]
    for i in range(1, len(chain)):
        cum.append(cum[-1] + _wgs_km(chain[i - 1], chain[i]))
    total = cum[-1]
    frac = [(cum[i + 1] / total if total else 0.0) for i in range(len(path))]
    span = (b.date - a.date).total_seconds()
    speed_a, speed_b = a.speed or 0.0, b.speed or 0.0
    anchors = {(round(a.longitude, 5), round(a.latitude, 5)),
               (round(b.longitude, 5), round(b.latitude, 5))}
    return [_TrackPoint(
        a.drive_id,
        a.date + timedelta(seconds=span * f),
        round(float(lng), 5), round(float(lat), 5),
        round(speed_a + (speed_b - speed_a) * f, 1), None)
        for (lng, lat), f in zip(path, frac)
        if (round(float(lng), 5), round(float(lat), 5)) not in anchors]


def _fill_points(own: Session,
                 positions: Sequence[Position]) -> dict[int, list[_TrackPoint]]:
    """读自有库断档补路, 按 a_pos_id 返回待插入的补路点。

    锚点行不在本次轨迹里 (理论上不会发生) 就整条跳过。"""
    drive_ids = sorted({p.drive_id for p in positions})
    fills = own.scalars(
        select(TrackFill).where(TrackFill.drive_id.in_(drive_ids))).all()
    by_id = {p.id: p for p in positions}
    out: dict[int, list[_TrackPoint]] = {}
    for fill in fills:
        a, b = by_id.get(fill.a_pos_id), by_id.get(fill.b_pos_id)
        if a is None or b is None or a.date >= b.date:
            continue
        try:
            path = json.loads(fill.path)
        except ValueError:
            continue
        pts = _interpolated_fill(a, b, path)
        if pts:
            out[fill.a_pos_id] = pts
    return out


def _track_points(own: Session, positions: Sequence[Position]
                  ) -> tuple[list[_TrackPoint], set[int]]:
    """原始轨迹点 + 自有库补路点 (插到各自锚点之后, 时间序保持)。

    返回 (points, fill_indices): 补路点在 points 里的下标集合 —— 它们
    本就稀疏珍贵, 下采样时全部保留, 不能被等间隔抽掉 (抽掉等于白补)。
    """
    pts = [_TrackPoint(p.drive_id, p.date, round(float(p.longitude), 5),
                       round(float(p.latitude), 5), p.speed or 0.0, p.power)
           for p in positions]
    fills = _fill_points(own, positions)
    if not fills:
        return pts, set()
    index = {p.id: i for i, p in enumerate(positions)}
    fill_indices: set[int] = set()
    inserted = 0                    # 已插入的补路点总数 (下标位移量)
    for a_pos_id in sorted(fills, key=lambda k: index[k]):
        seg = fills[a_pos_id]
        at = index[a_pos_id] + 1 + inserted
        pts[at:at] = seg
        fill_indices.update(range(at, at + len(seg)))
        inserted += len(seg)
    return pts, fill_indices


def _nearest_position(positions: Sequence[Position],
                      pt: Sequence[float]) -> int:
    """离 pt (WGS [lng, lat]) 最近的 positions 行下标。"""
    best, best_d = 0, float("inf")
    for i, p in enumerate(positions):
        d = _wgs_km([p.longitude, p.latitude], pt)
        if d < best_d:
            best, best_d = i, d
    return best


def _anchor_km(positions: Sequence[Position], idx: int,
               pt: Sequence[float]) -> float:
    """positions[idx] 到锚定候选点 pt 的距离 (km)。"""
    p = positions[idx]
    return _wgs_km([p.longitude, p.latitude], pt)


FILL_STEP_KM = 0.08   # 补路折线加密步长 (80m): 高德路径顶点可相距数百米
                      # (长直道只给两个端点), 原样入库拼进轨迹后相邻点仍超
                      # 断档识别阈值 (最低 160m), 会被再拆成断档无限重规划


def _densify(path: list[list[float]]) -> list[list[float]]:
    """折线相邻顶点间按 FILL_STEP_KM 线性插值加密。

    顶点之间本就是直线段 (高德路径是多段折线), 插值不引入任何虚构几何;
    加密后相邻点恒 < 80m, 任何下采样密度下都不再被识别成断档。"""
    out = [path[0]]
    for i in range(1, len(path)):
        lng0, lat0 = path[i - 1]
        lng1, lat1 = path[i]
        n = int(_wgs_km(path[i - 1], path[i]) / FILL_STEP_KM)
        for k in range(1, n + 1):
            r = k / (n + 1)
            out.append([round(lng0 + (lng1 - lng0) * r, 5),
                        round(lat0 + (lat1 - lat0) * r, 5)])
        out.append(path[i])
    return out


def save_fill(session: Session, own: Session,
              req: GapFillRequest) -> float:
    """把前端回传的断档补路锚定到原始 positions 行并存入自有库。

    a/b 各自锚到最近的采样点; 里程按回传 path 在服务端实算 (不信前端)。
    同一断档重复回传 = 覆盖更新 (按 a_pos_id 唯一)。
    """
    positions = session.scalars(
        select(Position).where(Position.drive_id == req.drive_id)
        .order_by(Position.date)).all()
    if len(positions) < 2:
        raise NotFound("该行程没有轨迹数据")
    ia = _nearest_position(positions, req.a)
    ib = _nearest_position(positions, req.b)
    if (_anchor_km(positions, ia, req.a) > GAP_ANCHOR_MAX_KM
            or _anchor_km(positions, ib, req.b) > GAP_ANCHOR_MAX_KM):
        raise ValueError("断档端点偏离轨迹超过 150 米")
    if ia >= ib or ib - ia > 50:
        raise ValueError("断档端点锚定失败 (先后顺序或跨度异常)")
    a, b = positions[ia], positions[ib]
    if a.date >= b.date:
        raise ValueError("断档端点锚定失败 (时间顺序异常)")
    path = _densify([[round(p[0], 5), round(p[1], 5)] for p in req.path])
    km = sum(_wgs_km(path[i - 1], path[i]) for i in range(1, len(path)))
    own.execute(delete(TrackFill).where(TrackFill.a_pos_id == a.id))
    own.add(TrackFill(drive_id=req.drive_id, a_pos_id=a.id, b_pos_id=b.id,
                      path=json.dumps(path, separators=(",", ":")),
                      km=round(km, 3), source="amap"))
    own.commit()
    return round(km, 3)


def trip_track(session: Session, own: Session, drive_id: int) -> TripTrack:
    """单条行程轨迹 (含速度/功耗), 下采样到 TRIP_TRACK_PER 点。

    自有库里的断档补路先拼进原始轨迹再下采样, 前端拿到的就是
    沿真实道路的连续轨迹 (无需再客户端补路)。
    """
    positions = session.scalars(
        select(Position).where(Position.drive_id == drive_id)
        .order_by(Position.date)).all()
    if len(positions) < 2:
        raise NotFound("该行程没有轨迹数据")
    pts_all, fill_idx = _track_points(own, positions)
    # 补路点全保留: 它们是整段稀疏折线, 被等间隔抽掉一点就重新露出断档
    keep = set(_keep_indices(len(pts_all), TRIP_TRACK_PER)) | fill_idx
    kept = [pts_all[i] for i in sorted(keep)]
    t0 = kept[0].date
    return TripTrack(
        id=drive_id,
        pts=[[p.lng, p.lat, p.speed, p.power] for p in kept],
        ts=[int(round((p.date - t0).total_seconds())) for p in kept])


MERGED_TRACK_BUDGET = 12000   # 多段合并的总点数预算, 按各段原始点数占比分配
MERGED_TRACK_PER_MIN = 200


@dataclass
class MergedPlan:
    """合并轨迹的头部汇总与各段下采样预算 (流式接口: 头部先行, 逐段跟上)。"""

    header: MergedTrack        # pts/ts/seg_starts 为空, 其余字段齐
    id_list: list[int]         # 按出发时间升序的行程 id
    budgets: dict[int, int]    # drive_id → 该段保留点数上限


def merged_track(session: Session, own: Session,
                 ids: Sequence[int]) -> MergedTrack:
    """多段行程合并成一条连续轨迹 (整包 JSON)。

    - ids 必须都是已结束行程, 否则 NotFound("包含不存在或未完成的行程");
    - ts 为累计行驶秒, 行程之间的停驶时段被剔除;
    - 各段按原始点数占比分享总预算下采样 (见 merged_track_plan);
    - 各段的断档补路同样在服务端拼好 (见 _track_points);
    - 逐段流式版本见 merged_track_segments (前端边下边播用)。
    """
    plan = merged_track_plan(session, ids)
    pts: list[list[float | None]] = []
    ts: list[int] = []
    seg_starts: list[int] = []
    for seg_pts, seg_ts in merged_track_segments(session, own, plan):
        seg_starts.append(len(pts))
        pts += seg_pts
        ts += seg_ts
    if len(pts) < 2:
        raise NotFound("这些行程没有轨迹数据")
    plan.header.pts = pts
    plan.header.ts = ts
    plan.header.seg_starts = seg_starts
    return plan.header


def merged_track_plan(session: Session, ids: Sequence[int]) -> MergedPlan:
    """校验 ids (须全为已结束行程) 并算好汇总头 + 各段下采样预算。"""
    drive_rows = session.execute(
        _trip_rows_stmt(aliased(Address), aliased(Address))
        .where(Drive.id.in_(ids))
        .order_by(Drive.start_date)).all()
    if len(drive_rows) != len(set(ids)):
        raise NotFound("包含不存在或未完成的行程")
    id_list = [d.id for d, _, _ in drive_rows]
    counts: dict[int, int] = {
        int(did): int(cnt) for did, cnt in session.execute(
            select(Position.drive_id, func.count())
            .where(Position.drive_id.in_(id_list))
            .group_by(Position.drive_id)).all()}
    total = sum(counts.values())
    budgets = ({did: max(MERGED_TRACK_PER_MIN,
                         round(MERGED_TRACK_BUDGET * cnt / total))
                for did, cnt in counts.items()} if total else {})
    first, last = drive_rows[0][0], drive_rows[-1][0]
    header = MergedTrack(
        ids=id_list, n=len(id_list), pts=[], ts=[], seg_starts=[],
        date=fdate(first.start_date), start=ftime(first.start_date),
        end=ftime(last.end_date) if last.end_date else None,
        km=round(sum(float(d.distance or 0) for d, _, _ in drive_rows), 2),
        min=sum(d.duration_min or 0 for d, _, _ in drive_rows),
        speed_max=max((d.speed_max or 0) for d, _, _ in drive_rows) or None,
        from_=_clean_addr(drive_rows[0][1]),
        to=_clean_addr(drive_rows[-1][2]))
    return MergedPlan(header, id_list, budgets)


def merged_track_segments(session: Session, own: Session, plan: MergedPlan
                          ) -> Iterator[tuple[list[list[float | None]], list[int]]]:
    """逐段产出 (pts, ts): ts 为跨段累计行驶秒 (行程间停驶剔除)。

    每段独立查询/下采样: 流式接口一段一段往外发, 前端拿到第一段就能
    开播, 不必等几十 MB 全下完; 断档补路已在段内拼好。
    """
    base = 0.0
    for did in plan.id_list:
        positions = session.scalars(
            select(Position).where(Position.drive_id == did)
            .order_by(Position.date)).all()
        points, fill_idx = _track_points(own, positions)
        if not points:
            continue
        # 补路点全保留 (理由同 trip_track), 只对原始点做等间隔下采样
        keep = set(_keep_indices(len(points),
                                 plan.budgets.get(did, MERGED_TRACK_PER_MIN))) \
            | fill_idx
        seg_pts: list[list[float | None]] = []
        seg_ts: list[int] = []
        t0 = _utc_seconds(points[0].date)   # 段首 (keep_indices 首点必留)
        prev_stamp = t0
        for i, tp in enumerate(points):
            if i not in keep:
                continue
            stamp = _utc_seconds(tp.date)
            prev_stamp = stamp
            seg_pts.append([tp.lng, tp.lat, tp.speed, tp.power])
            seg_ts.append(int(round(base + stamp - t0)))
        base += prev_stamp - t0    # 段行驶时长并入累计 (最后保留点 - 段首)
        if seg_pts:
            yield seg_pts, seg_ts


def closed_drive_ids_between(session: Session, first: int, last: int) -> list[int]:
    """头尾 id 区间内全部已结束行程的 id (升序; 与行程列表同口径)。

    连续行程的分享链接只记头尾 id, 服务端按区间展开成完整列表 ——
    区间里被过滤掉的未结束行程 (TeslaMate 记录中断残留) 自动跳过。"""
    rows = session.execute(
        select(Drive.id)
        .where(Drive.id >= first, Drive.id <= last,
               Drive.end_date.is_not(None))
        .order_by(Drive.id)).all()
    return [int(r[0]) for r in rows]


_EPOCH = datetime(1970, 1, 1)


def _utc_seconds(dt: datetime) -> float:
    """UTC 裸时间戳 → epoch 秒 (直接做差, 不做时区解释)。"""
    return (dt - _EPOCH).total_seconds()


# ---------------------------------------------------------------- 地图


def map_summary(session: Session, date_range: DateRange | None) -> MapSummary:
    """地图页汇总: 行程数 / 总里程 / 总时长 / 起止日期。"""
    conds: list[ColumnElement[bool]] = [Drive.distance.is_not(None)]
    conds += _range_conditions(Drive.start_date, date_range)
    count, distance, duration, first, last = session.execute(
        select(func.count(), func.coalesce(func.sum(Drive.distance), 0.0),
               func.coalesce(func.sum(Drive.duration_min), 0),
               func.min(Drive.start_date), func.max(Drive.start_date))
        .where(*conds)).one()
    return MapSummary(
        drives=int(count), distance_km=round(float(distance), 1),
        duration_min=int(duration),
        first_date=fdate(first) if first else None,
        last_date=fdate(last) if last else None)


def drive_max_id(session: Session) -> int:
    """drives 表当前最大有效行程 id (全量轨迹缓存的增量水位)。"""
    return int(session.scalar(
        select(func.max(Drive.id)).where(Drive.distance.is_not(None))) or 0)


MAP_TRACKS_PER_DRIVE = 40


def query_tracks(session: Session, after_id: int) -> list[MapTrack]:
    """全量轨迹增量查询: id > after_id 的有效行程 (distance 非空),
    每段窗口下采样到 MAP_TRACKS_PER_DRIVE 点, 按行程开始时间升序。"""
    inner = _position_window().join(
        Drive, Drive.id == Position.drive_id).where(
        Drive.distance.is_not(None), Drive.id > after_id).subquery()
    stmt = (select(inner.c.drive_id, inner.c.lng, inner.c.lat,
                   Drive.start_date, Drive.distance, Drive.duration_min)
            .join(Drive, Drive.id == inner.c.drive_id)
            .where(_window_keep(inner, MAP_TRACKS_PER_DRIVE))
            .order_by(Drive.start_date, inner.c.drive_id, inner.c.pos_date))
    return _group_map_tracks(session.execute(stmt).all())


def _position_window(
        *extra_conds: ColumnElement[bool]) -> Select[Any]:
    """位置点子查询: 每段内按时间的行号 rn 与总数 cnt (窗口函数双库都支持)。"""
    rn = func.row_number().over(
        partition_by=Position.drive_id, order_by=Position.date).label("rn")
    cnt = func.count().over(partition_by=Position.drive_id).label("cnt")
    stmt = select(
        Position.drive_id.label("drive_id"),
        Position.date.label("pos_date"),
        Position.longitude.label("lng"),
        Position.latitude.label("lat"),
        rn, cnt)
    if extra_conds:
        stmt = stmt.where(*extra_conds)
    return stmt


def _window_keep(inner: Subquery, per: int) -> ColumnElement[bool]:
    """窗口下采样保留条件: 首末点必留, 中间等间隔取点。

    步长必须整除: SA 2.0 的 ``/`` 在 Postgres 方言会 CAST 成 NUMERIC 真除,
    浮点步长让 ``%`` 永远取不到 0 → 中间点全丢 (SQLite 方言不转, 测不出来,
    用方言编译断言守住, 见 test_map)。
    """
    stride = case((inner.c.cnt < per, 1), else_=inner.c.cnt // per)
    return or_(inner.c.rn == 1, inner.c.rn == inner.c.cnt,
               (inner.c.rn - 1) % stride == 0)


def _group_map_tracks(rows: Iterable[Sequence[Any]]) -> list[MapTrack]:
    """行 → 轨迹分组; 少于 2 个点的段丢弃。

    行来自 execute(...).all() (SQLAlchemy Row), 直接按序列解包。
    """
    tracks: list[MapTrack] = []
    cur: MapTrack | None = None
    for drive_id, lng, lat, start_date, distance, duration_min in rows:
        if cur is None or cur.id != drive_id:
            if cur is not None and len(cur.pts) >= 2:
                tracks.append(cur)
            cur = MapTrack(id=drive_id, date=fdate(start_date),
                           km=round(float(distance), 1) if distance else 0.0,
                           min=duration_min, pts=[])
        cur.pts.append([round(float(lng), 5), round(float(lat), 5)])
    if cur is not None and len(cur.pts) >= 2:
        tracks.append(cur)
    return tracks


DETAIL_PER_MAX = 5000
DETAIL_PER_FLOOR = 2000
DETAIL_TOTAL_CAP = 250000
DETAIL_MAX_IDS = 150
DETAIL_WORKERS = 4


def detail_per_for(id_count: int) -> int:
    """视野框明细的每段点数预算: 段数越多预算越少, 有下限与上限。"""
    return max(DETAIL_PER_FLOOR,
               min(DETAIL_PER_MAX, DETAIL_TOTAL_CAP // id_count))


def query_detail(session: Session, id_list: Sequence[int], per: int,
                 bbox: BBox) -> list[MapDetailTrack]:
    """视野框内明细轨迹: bbox 过滤 + 窗口下采样, 按 (行程, 时间) 排序。"""
    inner = _position_window(*_detail_conditions(id_list, bbox)).subquery()
    stmt = (select(inner.c.drive_id, inner.c.lng, inner.c.lat)
            .where(_window_keep(inner, per))
            .order_by(inner.c.drive_id, inner.c.rn))
    tracks: list[MapDetailTrack] = []
    cur: MapDetailTrack | None = None
    for drive_id, lng, lat in session.execute(stmt):
        if cur is None or cur.id != drive_id:
            if cur is not None:
                tracks.append(cur)
            cur = MapDetailTrack(id=drive_id, pts=[])
        cur.pts.append([round(float(lng), 5), round(float(lat), 5)])
    if cur is not None:
        tracks.append(cur)
    return [t for t in tracks if len(t.pts) >= 2]


def _detail_conditions(
        id_list: Sequence[int], bbox: BBox
) -> tuple[ColumnElement[bool], ...]:
    """明细查询的位置点过滤: 指定行程 + 视野框内。"""
    return (Position.drive_id.in_(id_list),
            Position.longitude.between(bbox.west, bbox.east),
            Position.latitude.between(bbox.south, bbox.north))


def query_detail_parallel(factory: sessionmaker[Session],
                          id_list: Sequence[int], per: int,
                          bbox: BBox) -> list[MapDetailTrack]:
    """明细查询并行版: id 按步长切片到 DETAIL_WORKERS 个线程, 结果按 id 排序合并。"""
    chunks = [list(id_list)[i::DETAIL_WORKERS]
              for i in range(DETAIL_WORKERS)]
    chunks = [chunk for chunk in chunks if chunk]
    if len(chunks) <= 1:
        with factory() as session:
            return query_detail(session, id_list, per, bbox)
    with ThreadPoolExecutor(max_workers=len(chunks)) as pool:
        results = list(pool.map(
            _query_detail_chunk,
            [(factory, chunk, per, bbox) for chunk in chunks]))
    merged = {track.id: track for tracks in results for track in tracks}
    return [merged[drive_id] for drive_id in sorted(id_list)
            if drive_id in merged]


def _query_detail_chunk(
        args: tuple[sessionmaker[Session], list[int], int, BBox]
) -> list[MapDetailTrack]:
    factory, chunk, per, bbox = args
    with factory() as session:
        return query_detail(session, chunk, per, bbox)
