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
from .models import (Address, Car, Charge, ChargingProcess, Drive, Driver,
                     Geofence, Position, TrackFill, TripDriver, TripGroup, TripToll)
from .schemas import (
    CarInfo,
    ChargeCurve,
    ChargeDims,
    ChargingSession,
    ChargingSessionDetail,
    ChargingSummary,
    CityCount,
    CityStat,
    CostUpdateResult,
    GapFillRequest,
    LocationStat,
    LiveStatus,
    MapDetailTrack,
    MapSummary,
    MapTrack,
    MergedTrack,
    MonthlyStat,
    RegionNode,
    TripItem,
    TripGroupInfo, TripTollIn,
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
    cost: str | None = None    # 费用记录: recorded / missing (None = 全部)


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
    if flt.cost == "recorded":   # 已记录费用 / 未记录费用 (费用记 0 也算已记录)
        rows = [row for row in rows if row.process.cost is not None]
    elif flt.cost == "missing":
        rows = [row for row in rows if row.process.cost is None]
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


def charging_dimensions(session: Session, date_range: DateRange | None) -> ChargeDims:
    """充电统计维度聚合 (快慢/时段/起充 SOC/峰值功率/城市), 与列表同源同日期口径。"""
    rows = _charge_rows(session, date_range, None)
    by_hour = [0] * 24
    by_soc = [0] * 5
    by_power = [0] * 5
    fast = slow = 0
    cities: dict[str, dict[str, float]] = {}
    for row in rows:
        cp, agg = row.process, row.agg
        if agg.is_fast:
            fast += 1
        else:
            slow += 1
        by_hour[to_local(cp.start_date).hour] += 1
        soc = cp.start_battery_level
        if soc is not None:
            by_soc[min(int(soc) // 20, 4)] += 1     # 100% 也进 80-100 档
        power = agg.power_max
        if power is not None:
            by_power[0 if power < 60 else 1 if power < 100 else
                     2 if power < 150 else 3 if power < 200 else 4] += 1
        city = row.address.city if row.address else None
        if city:      # 无地址/无城市的充电不进城市维度 (与城市筛选下拉同口径)
            c = cities.setdefault(city, {"sessions": 0, "energy": 0.0, "cost": 0.0})
            c["sessions"] += 1
            c["energy"] += (_fnum(cp.charge_energy_used)
                            or _fnum(cp.charge_energy_added) or 0.0)
            c["cost"] += _fnum(cp.cost) or 0.0
    top = sorted(cities.items(), key=lambda kv: -kv[1]["sessions"])[:10]
    return ChargeDims(
        fast_sessions=fast, slow_sessions=slow, by_hour=by_hour,
        by_soc=by_soc, by_power=by_power,
        by_city=[CityStat(city=k, sessions=int(v["sessions"]),
                          energy=round(v["energy"], 1), cost=round(v["cost"], 2))
                 for k, v in top])


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


def charge_efficiency(session: Session) -> float | None:
    """额定续航 km → 桩端 kWh 换算系数: 充电记录 Σ能量 / Σ续航增量。

    桩端口径 (含充电损耗), 与充电页对账一致 —— 同期 "充了多少" 和 "开了
    多少" 能对上。没有可用充电记录 → None, 前端不显示电耗。"""
    kwh, rng = session.execute(
        select(func.sum(ChargingProcess.charge_energy_added),
               func.sum(ChargingProcess.end_rated_range_km
                        - ChargingProcess.start_rated_range_km))
        .where(ChargingProcess.end_date.is_not(None),
               ChargingProcess.charge_energy_added > 1,
               ChargingProcess.end_rated_range_km.is_not(None),
               ChargingProcess.start_rated_range_km.is_not(None),
               ChargingProcess.end_rated_range_km
               - ChargingProcess.start_rated_range_km > 1)).one()
    if not kwh or not rng or float(rng) <= 0:
        return None
    return float(kwh) / float(rng)


def _consumption(drive: Drive, eff: float | None) -> tuple[float | None, float | None]:
    """(总电耗 kWh, 平均电耗 Wh/km): 额定续航差 × 换算系数。

    续航差为负 (行驶中续航校准回弹) 夹到 0; 里程不足 1km 时平均无意义。"""
    if eff is None or drive.start_rated_range_km is None or drive.end_rated_range_km is None:
        return None, None
    raw = max(0.0, (float(drive.start_rated_range_km)
                    - float(drive.end_rated_range_km)) * eff)
    dist = float(drive.distance) if drive.distance is not None else None
    return (round(raw, 1),
            round(raw / dist * 1000) if dist and dist >= 1 else None)


def _trip_item(drive: Drive, start_addr: str | None,
               end_addr: str | None, eff: float | None = None) -> TripItem:
    kwh, wh_per_km = _consumption(drive, eff)
    return TripItem(
        id=drive.id,
        date=fdate(drive.start_date),
        start=ftime(drive.start_date),
        end=ftime(drive.end_date) if drive.end_date else None,
        km=round(float(drive.distance), 2) if drive.distance is not None else None,
        min=drive.duration_min,
        speed_max=drive.speed_max,
        from_=_clean_addr(start_addr),
        to=_clean_addr(end_addr),
        kwh=kwh, wh_per_km=wh_per_km)


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
    driver_id: int | None = None    # 驾驶员 (own 库驾驶员 id, 空 = 全部)


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


def driver_scope(own: Session,
                 driver_id: int) -> tuple[set[int], set[int], bool] | None:
    """按驾驶员筛选的行程 id 口径: (标注它的, 任何标注过的, 是否默认驾驶员)。
    与卡片展示同口径 —— 选默认驾驶员时未标注的也算 (未标注在卡片上就显示
    默认驾驶员名)。驾驶员不存在 → None (调用方按空结果处理)。

    标注表在自有库, 与 TeslaMate 库不是同一个连接 —— 先取 id 集合再下推
    条件 (SQL 端) 或后置过滤 (轨迹缓存端), 不能跨库做子查询。"""
    driver = own.get(Driver, driver_id)
    if driver is None:
        return None
    marked = set(own.scalars(
        select(TripDriver.drive_id).where(TripDriver.driver_id == driver_id)).all())
    all_marked = set(own.scalars(select(TripDriver.drive_id)).all())
    return marked, all_marked, bool(driver.is_default)


def _driver_condition(own: Session, driver_id: int) -> ColumnElement[bool]:
    """按驾驶员筛选 (SQL 端), 口径见 driver_scope。"""
    scope = driver_scope(own, driver_id)
    if scope is None:
        return Drive.id.in_(set())   # 驾驶员不存在 → 空
    marked, all_marked, is_default = scope
    cond = Drive.id.in_(marked)
    if is_default:
        cond = cond | Drive.id.not_in(all_marked)
    return cond


def filter_map_tracks_by_driver(tracks: list[MapTrack], own: Session,
                                driver_id: int) -> list[MapTrack]:
    """缓存轨迹按驾驶员后置过滤 (口径同 _driver_condition)。

    轨迹缓存只从 TeslaMate 库构建, 标注在自有库且会随标/清变动 —— 缓存里
    不落 driver_id, 每次请求现算 id 集合过滤 (全量轨迹在内存, 代价可忽略)。"""
    scope = driver_scope(own, driver_id)
    if scope is None:
        return []
    marked, all_marked, is_default = scope
    return [t for t in tracks
            if t.id in marked or (is_default and t.id not in all_marked)]


def list_trips(session: Session, own: Session, offset: int, limit: int,
               flt: TripFilter | None = None) -> tuple[int, list[TripItem]]:
    """行程列表 (最新在前), total 为已结束行程数; 按出发时间/起终地区/里程过滤。"""
    conds = _trip_conditions(session, flt)
    if flt and flt.driver_id is not None:
        conds.append(_driver_condition(own, flt.driver_id))
    total = session.scalar(
        select(func.count()).select_from(Drive)
        .where(Drive.end_date.is_not(None), *conds)) or 0
    rows = session.execute(
        _trip_rows_stmt(aliased(Address), aliased(Address)).where(*conds)
        .order_by(Drive.start_date.desc())
        .offset(offset).limit(limit)).all()
    eff = charge_efficiency(session)   # 电耗换算: 一页行程共用一次充电记录聚合
    items = [_trip_item(d, s, e, eff) for d, s, e in rows]
    annotate_drivers(own, items)
    annotate_tolls(own, items)
    return int(total), items


def annotate_drivers(own: Session, items: list[TripItem]) -> None:
    """行程条目补驾驶员: 显式标注 > 默认驾驶员兜底 (都没配 = None 不显示)。

    标注指向的驾驶员已被删时按未标注处理 (标注行会随删驾驶员联动清掉,
    这里再兜一层, 库里残留脏行也不致显示错名字)。"""
    if not items:
        return
    drivers = {d.id: d for d in own.scalars(select(Driver)).all()}
    default = next((d for d in drivers.values() if d.is_default), None)
    marks = {m.drive_id: m.driver_id for m in own.scalars(
        select(TripDriver)
        .where(TripDriver.drive_id.in_([i.id for i in items]))).all()}
    for it in items:
        did = marks.get(it.id)
        driver = drivers.get(did) if did is not None else None
        it.driver_id = driver.id if driver is not None else None
        shown = driver or default
        it.driver = shown.name if shown is not None else None


def annotate_tolls(own: Session, items: list[TripItem]) -> None:
    """行程条目补高速费估价 (算过的才有, 没算过保持 None)。"""
    if not items:
        return
    rows = own.scalars(select(TripToll).where(
        TripToll.drive_id.in_([i.id for i in items]))).all()
    by_id = {r.drive_id: r for r in rows}
    for it in items:
        row = by_id.get(it.id)
        if row is not None:
            it.toll = row.tolls
            it.toll_km = row.toll_km


def save_trip_toll(own: Session, drive_id: int, body: TripTollIn) -> None:
    """存/更新一条行程的高速费估价 (算过重算 = 覆盖)。"""
    row = own.scalars(select(TripToll).where(TripToll.drive_id == drive_id)).first()
    if row is None:
        row = TripToll(drive_id=drive_id)
        own.add(row)
    row.tolls = body.tolls
    row.toll_km = body.toll_km
    row.distance = body.distance
    row.roads = json.dumps([r.model_dump() for r in body.roads],
                           ensure_ascii=False, separators=(",", ":"))
    own.commit()


def set_trip_driver(own: Session, drive_id: int, driver_id: int | None) -> None:
    """标/清行程驾驶员 (清 = 删标注行, 展示回默认兜底)。"""
    if driver_id is not None and own.get(Driver, driver_id) is None:
        raise NotFound("驾驶员不存在")
    own.execute(delete(TripDriver).where(TripDriver.drive_id == drive_id))
    if driver_id is not None:
        own.add(TripDriver(drive_id=drive_id, driver_id=driver_id))
    own.commit()


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


def get_trip(session: Session, own: Session, drive_id: int) -> TripItem | None:
    """单条行程 (未结束 / 不存在返回 None)。"""
    rows = session.execute(
        _trip_rows_stmt(aliased(Address), aliased(Address))
        .where(Drive.id == drive_id)).all()
    if not rows:
        return None
    item = _trip_item(rows[0][0], rows[0][1], rows[0][2],
                      charge_efficiency(session))
    annotate_drivers(own, [item])
    annotate_tolls(own, [item])
    return item


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
    """原始轨迹点 + 自有库补路点 (按日期归并, 时间序保持)。

    返回 (points, fill_indices): 补路点在 points 里的下标集合 —— 它们
    本就稀疏珍贵, 下采样时全部保留, 不能被等间隔抽掉 (抽掉等于白补)。
    """
    pts = [_TrackPoint(p.drive_id, p.date, round(float(p.longitude), 5),
                       round(float(p.latitude), 5), p.speed or 0.0, p.power)
           for p in positions]
    fills = _fill_points(own, positions)
    if not fills:
        return pts, set()
    # 补路点不能直接插到锚点后面: 锚点是客户端按它收到的 (下采样) 视图挑的,
    # a/b 两点在原始流里未必相邻 —— 锚点区间内夹着的原始点会整块落到补路点
    # 之后, 日期回退把 ts 打乱 (合并视图与单条视图的采样口径不同必踩)。
    # 按日期稳定归并 (原始点本就有序, 同刻时原始点在前), 任意视图都单调。
    extras: list[_TrackPoint] = [tp for seg in fills.values() for tp in seg]
    extra_ids = {id(tp) for tp in extras}
    pts = sorted([*pts, *extras], key=lambda tp: tp.date)
    return pts, {i for i, tp in enumerate(pts) if id(tp) in extra_ids}


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
    eff = charge_efficiency(session)
    raw_kwh = sum(_consumption(d, eff)[0] or 0.0 for d, _, _ in drive_rows)
    total_km = sum(float(d.distance or 0) for d, _, _ in drive_rows)
    header = MergedTrack(
        ids=id_list, n=len(id_list), pts=[], ts=[], seg_starts=[],
        date=fdate(first.start_date), start=ftime(first.start_date),
        end=ftime(last.end_date) if last.end_date else None,
        km=round(total_km, 2),
        min=sum(d.duration_min or 0 for d, _, _ in drive_rows),
        speed_max=max((d.speed_max or 0) for d, _, _ in drive_rows) or None,
        kwh=round(raw_kwh, 1) if eff is not None else None,
        wh_per_km=(round(raw_kwh / total_km * 1000)
                   if eff is not None and total_km >= 1 else None),
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


def _group_rows(session: Session, ids: Sequence[int]) -> list[Drive]:
    """按当前行程库取分组里的行程 (只认已结束行程, 与列表同口径)。"""
    return list(session.scalars(
        select(Drive)
        .where(Drive.id.in_(ids), Drive.end_date.is_not(None))
        .order_by(Drive.start_date)).all())


def _group_ids(group: TripGroup) -> list[int]:
    """分组存库的逗号串 → id 列表。"""
    return [int(x) for x in group.ids.split(",")]


def _group_info(session: Session, group: TripGroup) -> TripGroupInfo:
    """分组条目: 段数/里程/日期跨度按当前数据现算 (行程可能已被改动)。"""
    drives = _group_rows(session, _group_ids(group))
    km = round(sum(float(d.distance or 0) for d in drives), 1)
    dates = [fdate(d.start_date) for d in drives]
    span = dates[0] if len(set(dates)) == 1 else f"{dates[0]}~{dates[-1]}" \
        if dates else ""
    return TripGroupInfo(
        id=group.id, name=group.name, ids=_group_ids(group),
        n=len(drives), km=km, span=span)


def list_trip_groups(session: Session, own: Session) -> list[TripGroupInfo]:
    """全部分组 (最新存的前面)。"""
    groups = list(own.scalars(select(TripGroup).order_by(TripGroup.id.desc())))
    return [_group_info(session, g) for g in groups]


def save_trip_group(session: Session, own: Session,
                    name: str, ids: Sequence[int]) -> TripGroupInfo:
    """存分组: ids 升序去重后落库; 含无效行程 (不存在/未结束) 则拒绝。"""
    unique = sorted(set(ids))
    rows = _group_rows(session, unique)
    if len(rows) != len(unique):
        raise NotFound("包含不存在或未结束的行程")
    group = TripGroup(name=name, ids=",".join(str(i) for i in unique))
    own.add(group)
    own.commit()
    return _group_info(session, group)


def rename_trip_group(session: Session, own: Session,
                      group_id: int, name: str) -> TripGroupInfo:
    """分组改名 (成员不动)。"""
    group = own.get(TripGroup, group_id)
    if group is None:
        raise NotFound("分组不存在")
    group.name = name
    own.commit()
    return _group_info(session, group)


def delete_trip_group(own: Session, group_id: int) -> None:
    """删分组 (只删自有库记录, 行程原数据不动)。"""
    group = own.get(TripGroup, group_id)
    if group is None:
        raise NotFound("分组不存在")
    own.delete(group)
    own.commit()


# ---------------------------------------------------------------- 当前驾驶

LIVE_STALE_AFTER_S = 600   # 最新位置点超过 10 分钟没有 → 不算驾驶中
                           # (流式采样每秒多条, 只留短暂网络断档的余量)


def _db_now() -> datetime:
    """当前 UTC 裸时间戳 (与库内 date 同口径)。"""
    return datetime.now(dt_timezone.utc).replace(tzinfo=None)


def live_status(session: Session) -> LiveStatus:
    """当前驾驶状态: 未结束行程里位置点最新的那条, 且位置点足够新。

    判据见 LIVE_STALE_AFTER_S —— 未关闭 ≠ 在开 (库里躺着十几条
    TeslaMate 中断残留的未关闭行程)。里程 = odometer 差 (与行程页
    distance 同口径, 已在真实库逐位对齐验证); 电耗 = 额定续航差 ×
    充电定标, 续航取"首个/最新非空轮询值" (流式点位大多没有该字段)。
    """
    cand = session.execute(
        select(Drive.id, Drive.start_date, func.max(Position.date).label("last"))
        .join(Position, Position.drive_id == Drive.id)
        .where(Drive.end_date.is_(None))
        .group_by(Drive.id, Drive.start_date)
        .order_by(func.max(Position.date).desc())).first()
    if cand is None or _utc_seconds(cand.last) < _utc_seconds(_db_now()) \
            - LIVE_STALE_AFTER_S:
        return LiveStatus(driving=False, now_utc=int(_utc_seconds(_db_now())))
    drive_id, start_date, _ = cand

    last_pos = session.scalars(
        select(Position).where(Position.drive_id == drive_id)
        .order_by(Position.date.desc()).limit(1)).first()
    speed_max, odo_lo, odo_hi = session.execute(
        select(func.max(Position.speed), func.min(Position.odometer),
               func.max(Position.odometer))
        .where(Position.drive_id == drive_id)).one()
    first_rr = session.execute(
        select(Position.rated_battery_range_km)
        .where(Position.drive_id == drive_id,
               Position.rated_battery_range_km.is_not(None))
        .order_by(Position.date).limit(1)).scalar_one_or_none()
    last_rr = session.execute(
        select(Position.rated_battery_range_km)
        .where(Position.drive_id == drive_id,
               Position.rated_battery_range_km.is_not(None))
        .order_by(Position.date.desc()).limit(1)).scalar_one_or_none()

    km = (round(float(odo_hi) - float(odo_lo), 2)
          if odo_lo is not None and odo_hi is not None else None)
    kwh: float | None = None
    wh_per_km: int | None = None
    eff = charge_efficiency(session)
    if eff is not None and first_rr is not None and last_rr is not None:
        raw = max(0.0, (float(first_rr) - float(last_rr)) * eff)
        kwh = round(raw, 1)
        if km is not None and km >= 1:
            wh_per_km = int(round(raw / km * 1000))

    assert last_pos is not None   # cand 有位置点聚合, 最新行必然存在
    return LiveStatus(
        driving=True, drive_id=drive_id,
        start=ftime(start_date), started_utc=int(_utc_seconds(start_date)),
        speed=last_pos.speed, speed_max=speed_max,
        soc=last_pos.battery_level,
        rated_range_km=round(float(last_rr), 1) if last_rr is not None else None,
        km=km, kwh=kwh, wh_per_km=wh_per_km,
        lng=round(float(last_pos.longitude), 6),
        lat=round(float(last_pos.latitude), 6),
        pos_utc=int(_utc_seconds(last_pos.date)),
        now_utc=int(_utc_seconds(_db_now())))


# ---------------------------------------------------------------- 地图


def map_summary(session: Session, own: Session, date_range: DateRange | None,
                driver_id: int | None = None) -> MapSummary:
    """地图页汇总: 行程数 / 总里程 / 总时长 / 起止日期; 驾驶员同轨迹口径。"""
    conds: list[ColumnElement[bool]] = [Drive.distance.is_not(None)]
    conds += _range_conditions(Drive.start_date, date_range)
    if driver_id is not None:
        conds.append(_driver_condition(own, driver_id))
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
