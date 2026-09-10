"""行程轨迹页 API 测试 (列表分页 / 单条全精度轨迹 / 参数校验)。"""
from datetime import datetime

import app.main as m


def drive_row(id=1, start=datetime(2026, 9, 10, 0, 32), end=datetime(2026, 9, 10, 1, 44),
              dist=42.5, dur=72, spd=118, frm="广东省深圳市南山区", to="广东省东莞市长安镇"):
    return {"id": id, "start_date": start, "end_date": end, "distance": dist,
            "duration_min": dur, "speed_max": spd,
            "start_addr": frm, "end_addr": to}


# ---------------------------------------------------------------- 列表
def test_trips_sessions_paginates(auth, monkeypatch):
    seen = {}

    def fake_query(sql, params=None):
        seen.setdefault("calls", []).append((sql, params))
        if "count(*)" in sql:
            return [{"n": 60}]
        return [drive_row(id=i, frm="广东省深圳市南山区, ") for i in range(24)]

    monkeypatch.setattr(m, "query", fake_query)
    r = auth.get("/tesla/trips/api/sessions?offset=24&limit=24")
    assert r.status_code == 200
    d = r.json()
    assert d["total"] == 60
    assert len(d["items"]) == 24
    it = d["items"][0]
    assert it["id"] == 0
    assert it["date"] == "2026-09-10"          # UTC 00:32 → 北京 08:32
    assert it["start"] == "2026-09-10 08:32"
    assert it["end"] == "2026-09-10 09:44"
    assert it["km"] == 42.5
    assert it["min"] == 72
    assert it["speed_max"] == 118
    assert it["from"] == "广东省深圳市南山区"   # 尾部悬挂逗号被清掉
    assert it["to"] == "广东省东莞市长安镇"
    # SQL 按日期倒序 + 分页参数透传
    list_sql = seen["calls"][1][0]
    assert "ORDER BY d.start_date DESC" in list_sql
    assert seen["calls"][1][1] == {"limit": 24, "offset": 24}


def test_trips_sessions_tolerates_missing_fields(auth, monkeypatch):
    """end/duration/speed 为空时不炸, 前端显示 —。"""
    monkeypatch.setattr(m, "query", lambda sql, params=None: [
        {"n": 1}] if "count" in sql else
        [drive_row(end=None, dur=None, spd=None, dist=None, frm=None, to=None)])
    d = auth.get("/tesla/trips/api/sessions").json()
    it = d["items"][0]
    assert it["end"] is None and it["min"] is None and it["km"] is None
    assert it["from"] == "未知位置" and it["to"] == "未知位置"


def test_trips_sessions_rejects_bad_pagination(auth, monkeypatch):
    def boom(sql, params=None):
        raise AssertionError("参数非法不应查库")

    monkeypatch.setattr(m, "query", boom)
    base = "/tesla/trips/api/sessions"
    assert auth.get(base, params={"offset": -1}).status_code == 400
    assert auth.get(base, params={"limit": 0}).status_code == 400
    assert auth.get(base, params={"limit": 101}).status_code == 400


# ---------------------------------------------------------------- 轨迹
def test_trip_track_full_resolution(auth, monkeypatch):
    seen = {}

    def fake_query(sql, params=None):
        seen["sql"], seen["params"] = sql, params
        return [{"drive_id": 7, "longitude": 114.05, "latitude": 22.55},
                {"drive_id": 7, "longitude": 114.06, "latitude": 22.56}]

    monkeypatch.setattr(m, "query", fake_query)
    r = auth.get("/tesla/trips/api/7/track")
    assert r.status_code == 200
    assert r.json() == {"id": 7, "pts": [[114.05, 22.55], [114.06, 22.56]]}
    # 与地图页点选同规格: 全球框 + 每条 5000 点
    assert seen["params"]["ids"] == [7]
    assert seen["params"]["per"] == 5000
    assert seen["params"]["w"] == -180 and seen["params"]["n"] == 90


def test_trip_track_404_when_no_points(auth, monkeypatch):
    monkeypatch.setattr(m, "query", lambda sql, params=None: [])
    r = auth.get("/tesla/trips/api/999/track")
    assert r.status_code == 404
    assert "没有轨迹数据" in r.json()["detail"]
