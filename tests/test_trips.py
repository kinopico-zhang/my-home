"""行程轨迹页 API 测试 (列表分页 / 单条全精度轨迹 / 参数校验)。"""
from datetime import datetime, timedelta

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
def test_trip_track_full_resolution_with_speed(auth, monkeypatch):
    seen = {}

    def fake_query(sql, params=None):
        seen["sql"], seen["params"] = sql, params
        t0 = datetime(2026, 9, 10, 8, 32)
        return [
            {"longitude": 114.05, "latitude": 22.55, "speed": 30, "power": 45000, "date": t0},
            {"longitude": 114.06, "latitude": 22.56, "speed": None, "power": None,
             "date": t0 + timedelta(minutes=72, seconds=1)},
        ]

    monkeypatch.setattr(m, "query", fake_query)
    r = auth.get("/tesla/trips/api/7/track")
    assert r.status_code == 200
    # 每点 [lng, lat, speed, power_W]; 速度缺失按 0 (停车), power 可为 null;
    # ts 是相对起点的秒偏移 (播放动画里算"已行驶时长"和平均功耗)
    assert r.json() == {"id": 7,
                        "pts": [[114.05, 22.55, 30, 45000], [114.06, 22.56, 0, None]],
                        "ts": [0, 4321]}
    # 整条无视野框 + 5000 点上限 + 带速度/功耗/时间列
    assert seen["params"] == {"id": 7, "per": 5000}
    for col in ("pos.speed", "pos.power", "pos.date"):
        assert col in seen["sql"]
    assert "drive_id = %(id)s" in seen["sql"]


def test_trip_track_404_when_no_points(auth, monkeypatch):
    monkeypatch.setattr(m, "query", lambda sql, params=None: [])  # 0 点
    r = auth.get("/tesla/trips/api/999/track")
    assert r.status_code == 404
    # 只剩 1 个点画不了线, 也算没有轨迹
    monkeypatch.setattr(m, "query", lambda sql, params=None: [
        {"longitude": 114.05, "latitude": 22.55, "speed": 30, "power": 45000}])
    r = auth.get("/tesla/trips/api/999/track")
    assert r.status_code == 404
    assert "没有轨迹数据" in r.json()["detail"]


# ---------------------------------------------------------------- 页面
def test_trips_page_has_playbar_and_single_column(auth):
    """播放控制条 (暂停/进度/倍速) + 单列列表 + 断档图例 都在页面上。"""
    html = auth.get("/tesla/trips").text
    for frag in ['id="playbar"', 'id="pb-toggle"', 'id="pb-seek"', 'id="pb-speed"',
                 'id="sh-cell-pw"', 'id="sh-pw-lb"', "ICON_REPLAY",
                 'id="list"', "缺失", "最高车速"]:
        assert frag in html, f"行程页缺少 {frag}"
    # 瀑布流的列容器已删
    assert "m-col" not in html
