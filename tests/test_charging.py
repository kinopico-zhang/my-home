"""充电记录 API 测试 (数据库用替身, 不依赖真实 TeslaMate 库)。"""
from datetime import datetime

import app.main as m


def cp_row(**kw):
    """构造一条 charging_process 查询结果行 (与 SESSION_SELECT 列对齐)。"""
    base = dict(
        id=1, start_date=datetime(2026, 9, 7, 15, 50),
        end_date=datetime(2026, 9, 7, 23, 2),
        start_battery_level=20, end_battery_level=80,
        charge_energy_added=45.0, charge_energy_used=48.0,
        duration_min=432, cost=25.5, outside_temp_avg=28.5,
        start_rated_range_km=120.0, end_rated_range_km=330.0,
        power_max=90.0, is_fast=True,
        geofence_name=None, address_name="华为立体车库",
        city="深圳市", display_name="广东省深圳市龙岗区坂田街道",
    )
    base.update(kw)
    return base


# ---------------------------------------------------------------- 纯函数
def test_session_row_fields_and_price():
    d = m.session_row(cp_row())
    assert d["id"] == 1
    assert d["start"] == "2026-09-07 23:50"   # UTC 15:50 → 北京时间
    assert d["date"] == "2026-09-07"
    assert d["location"] == "华为立体车库"      # 无 geofence 时退回 address
    assert d["price_per_kwh"] == round(25.5 / 48.0, 3)
    assert d["is_fast"] is True
    assert d["outside_temp"] == 28.5


def test_session_row_geofence_preferred():
    d = m.session_row(cp_row(geofence_name="公司"))
    assert d["location"] == "公司"


def test_session_row_without_cost():
    d = m.session_row(cp_row(cost=None))
    assert d["cost"] is None
    assert d["price_per_kwh"] is None


def test_range_clause():
    assert m.range_clause({}) == "TRUE"
    assert "cp.start_date >=" in m.range_clause({"from": "2026-01-01"})
    assert "cp.start_date <" in m.range_clause({"to": "2026-01-31"})
    both = m.range_clause({"from": "2026-01-01", "to": "2026-01-31"})
    assert ">=" in both and "<" in both and " AND " in both


# ---------------------------------------------------------------- 接口
def test_car_endpoint(auth, monkeypatch):
    monkeypatch.setattr(m, "query", lambda sql, params=None: [
        {"id": 1, "name": "臭哈子", "model": "Y", "trim_badging": "50", "vin": "LRW1"}])
    r = auth.get("/tesla/charging/api/car")
    assert r.status_code == 200
    assert r.json() == [{"id": 1, "name": "臭哈子", "model": "Y",
                         "trim_badging": "50", "vin": "LRW1"}]


def test_summary_endpoint(auth, monkeypatch):
    monkeypatch.setattr(m, "query", lambda sql, params=None: [{
        "sessions": 10, "fast_sessions": 4, "energy_added": 400.0,
        "energy_used": 430.0, "cost": 215.0, "duration_min": 2000,
        "soc_gain": 300, "range_gain": 1500.0,
        "first_date": datetime(2026, 1, 1), "last_date": datetime(2026, 9, 1)}])
    d = auth.get("/tesla/charging/api/summary").json()
    assert d["sessions"] == 10
    assert d["fast_sessions"] == 4
    assert d["price_per_kwh"] == round(215.0 / 430.0, 3)
    assert d["first_date"] == "2026-01-01"
    assert d["last_date"] == "2026-09-01"


def test_sessions_list(auth, monkeypatch):
    def q(sql, params=None):
        return [{"n": 279}] if "count(*)" in sql else [cp_row(id=332)]
    monkeypatch.setattr(m, "query", q)
    d = auth.get("/tesla/charging/api/sessions?limit=1").json()
    assert d["total"] == 279
    assert len(d["items"]) == 1
    assert d["items"][0]["id"] == 332


def test_sessions_rejects_unknown_sort(auth):
    r = auth.get("/tesla/charging/api/sessions?sort=hack")
    assert r.status_code == 400
    assert "不支持的排序" in r.json()["detail"]


def test_sessions_type_filter_adds_condition(auth, monkeypatch):
    calls = []

    def q(sql, params=None):
        calls.append(sql)
        return [{"n": 0}] if "count(*)" in sql else []

    monkeypatch.setattr(m, "query", q)
    assert auth.get("/tesla/charging/api/sessions?type=fast").status_code == 200
    assert any("agg.is_fast" in c and "NOT" not in c for c in calls)
    assert auth.get("/tesla/charging/api/sessions?type=slow").status_code == 200
    assert any("NOT agg.is_fast" in c for c in calls)


def test_session_detail(auth, monkeypatch):
    samples = [
        dict(date=datetime(2026, 9, 7, 16, 0), battery_level=20, charger_power=90.0,
             charger_voltage=400.0, charger_actual_current=220.0,
             charge_energy_added=0.0, outside_temp=28.0, conn_charge_cable="CCS",
             fast_charger_brand="<invalid>", fast_charger_type="Tesla"),
        dict(date=datetime(2026, 9, 7, 16, 10), battery_level=30, charger_power=80.0,
             charger_voltage=400.0, charger_actual_current=200.0,
             charge_energy_added=10.0, outside_temp=28.0, conn_charge_cable=None,
             fast_charger_brand=None, fast_charger_type=None),
    ]
    monkeypatch.setattr(m, "query", lambda sql, params=None:
                        samples if "ORDER BY date" in sql else [cp_row()])
    d = auth.get("/tesla/charging/api/sessions/1").json()
    assert d["curve"]["minutes"] == [10.0, 20.0]      # 距 start (15:50) 的分钟数
    assert d["curve"]["soc"] == [20, 30]
    assert d["cable"] == "CCS"
    assert d["charger_brand"] is None                  # <invalid> 已过滤
    assert d["charger_type"] == "Tesla"


def test_session_detail_404(auth, monkeypatch):
    monkeypatch.setattr(m, "query", lambda sql, params=None: [])
    assert auth.get("/tesla/charging/api/sessions/99999").status_code == 404


def test_monthly_endpoint(auth, monkeypatch):
    monkeypatch.setattr(m, "query", lambda sql, params=None: [
        {"month": "2026-08", "sessions": 12, "energy_used": 300.0,
         "cost": 150.0, "fast_sessions": 5}])
    d = auth.get("/tesla/charging/api/monthly").json()
    assert d[0] == {"month": "2026-08", "sessions": 12, "energy_used": 300.0,
                    "cost": 150.0, "fast_sessions": 5}


def test_locations_endpoint(auth, monkeypatch):
    monkeypatch.setattr(m, "query", lambda sql, params=None: [
        {"loc": "华为立体车库", "city": "深圳市", "sessions": 20,
         "energy_used": 900.0, "cost": 450.0, "fast_sessions": 2}])
    d = auth.get("/tesla/charging/api/locations").json()
    assert d[0]["location"] == "华为立体车库"
    assert d[0]["sessions"] == 20


# ---------------------------------------------------------------- 费用编辑
def test_cost_patch_rejects_out_of_range(auth):
    for bad in (-1, 100001):
        r = auth.patch("/tesla/charging/api/sessions/1/cost", json={"cost": bad})
        assert r.status_code == 400, bad
        assert "金额" in r.json()["detail"]


def test_cost_patch_unknown_session(auth, monkeypatch):
    monkeypatch.setattr(m, "query", lambda sql, params=None: [])
    r = auth.patch("/tesla/charging/api/sessions/99999/cost", json={"cost": 10})
    assert r.status_code == 404


def test_cost_patch_updates_db(auth, monkeypatch):
    monkeypatch.setattr(m, "query", lambda sql, params=None: [
        {"charge_energy_added": 45.0, "charge_energy_used": 48.0}])
    r = auth.patch("/tesla/charging/api/sessions/332/cost", json={"cost": 30})
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True
    assert d["cost"] == 30.0
    assert d["price_per_kwh"] == round(30.0 / 48.0, 3)
    # FakePool 记录到真实的 UPDATE 语句
    cur = m.pool.conn.cur
    assert "UPDATE charging_processes SET cost" in cur.sql
    assert cur.params == {"cost": 30.0, "id": 332}


def test_cost_patch_clear_with_null(auth, monkeypatch):
    monkeypatch.setattr(m, "query", lambda sql, params=None: [
        {"charge_energy_added": 45.0, "charge_energy_used": 48.0}])
    r = auth.patch("/tesla/charging/api/sessions/332/cost", json={"cost": None})
    assert r.status_code == 200
    assert r.json()["cost"] is None
    assert m.pool.conn.cur.params == {"cost": None, "id": 332}
