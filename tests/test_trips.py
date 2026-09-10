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


def test_trips_sessions_excludes_unfinished(auth, monkeypatch):
    """未关闭行程 (TeslaMate 记录中断留下的 end_date 空行) 不进列表,
    口径与 Grafana 行程面板 / 地图页 TRACKS_SQL 一致。"""
    seen = {}

    def fake_query(sql, params=None):
        seen.setdefault("calls", []).append(sql)
        return [{"n": 1}] if "count(*)" in sql else [drive_row()]

    monkeypatch.setattr(m, "query", fake_query)
    assert auth.get("/tesla/trips/api/sessions").status_code == 200
    count_sql, list_sql = seen["calls"]
    assert "end_date IS NOT NULL" in count_sql
    assert "end_date IS NOT NULL" in list_sql
    assert "end_date IS NOT NULL" in m.TRIPS_ONE_SQL
    assert "AND d.id = %(id)s" in m.TRIPS_ONE_SQL


def test_trip_session_one(auth, monkeypatch):
    """单条行程接口: 分享链接 /tesla/trips?id=X 直开弹层时前端拉取。"""
    seen = {}

    def fake_query(sql, params=None):
        seen["sql"], seen["params"] = sql, params
        return [drive_row(id=1838)]

    monkeypatch.setattr(m, "query", fake_query)
    r = auth.get("/tesla/trips/api/sessions/1838")
    assert r.status_code == 200
    assert seen["params"] == {"id": 1838}
    assert r.json() == {
        "id": 1838, "date": "2026-09-10",
        "start": "2026-09-10 08:32", "end": "2026-09-10 09:44",
        "km": 42.5, "min": 72, "speed_max": 118,
        "from": "广东省深圳市南山区", "to": "广东省东莞市长安镇",
    }


def test_trip_session_one_404(auth, monkeypatch):
    """不存在 / 未完成的行程 → 404 (前端抹掉地址栏参数)。"""
    monkeypatch.setattr(m, "query", lambda sql, params=None: [])
    assert auth.get("/tesla/trips/api/sessions/9999").status_code == 404


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


# ---------------------------------------------------------------- 合并轨迹 (多选连续行程)
def test_merged_track_stitches_and_skips_parking(auth, monkeypatch):
    """多段行程拼一条轨迹: pts 按时间串联, ts 是"累计行驶秒" (行程间停驶剔除),
    汇总 = 首段起/末段终 + 各项求和 (前端弹层播放/统计照常)。"""
    seen = {}

    def fake_query(sql, params=None):
        seen.setdefault("calls", []).append((sql, params))
        if "FROM positions" in sql:          # 轨迹行 (含 drive_id)
            t = datetime(2026, 9, 10, 8, 32)
            return [
                {"drive_id": 11, "longitude": 114.05, "latitude": 22.55,
                 "speed": 30, "power": 45000, "date": t},
                {"drive_id": 11, "longitude": 114.06, "latitude": 22.56,
                 "speed": 40, "power": None, "date": t + timedelta(minutes=10)},
                # 停驶 2h50m 后的第二段 (这段间隔不应计入 ts)
                {"drive_id": 12, "longitude": 114.07, "latitude": 22.57,
                 "speed": 50, "power": 30000, "date": t + timedelta(hours=3)},
                {"drive_id": 12, "longitude": 114.08, "latitude": 22.58,
                 "speed": None, "power": None, "date": t + timedelta(hours=3, minutes=10)},
            ]
        # 行程汇总行 (TRIPS_IDS_SQL: 按 start_date 排序返回)
        return [drive_row(id=11, dist=42.5, dur=72, spd=118,
                          frm="广东省深圳市南山区, ", to="中途点"),
                drive_row(id=12, start=datetime(2026, 9, 10, 11, 32),
                          end=datetime(2026, 9, 10, 12, 42),
                          dist=10.04, dur=10, spd=96, frm="中途点", to="广东省东莞市长安镇")]

    monkeypatch.setattr(m, "query", fake_query)
    r = auth.get("/tesla/trips/api/merged?ids=12,11")   # 乱序传入
    assert r.status_code == 200
    d = r.json()
    assert d["ids"] == [11, 12] and d["n"] == 2
    assert d["pts"] == [[114.05, 22.55, 30, 45000], [114.06, 22.56, 40, None],
                        [114.07, 22.57, 50, 30000], [114.08, 22.58, 0, None]]
    # 第二段从上一段末尾继续累计: 中间 2h50m 停驶不进 ts
    assert d["ts"] == [0, 600, 600, 1200]
    # 汇总: 首段起 / 末段终, 里程/时长求和, 最高速取 max
    assert d["km"] == 52.54 and d["min"] == 82 and d["speed_max"] == 118
    assert d["date"] == "2026-09-10"
    assert d["start"] == "2026-09-10 08:32" and d["end"] == "2026-09-10 20:42"
    assert d["from"] == "广东省深圳市南山区" and d["to"] == "广东省东莞市长安镇"
    # SQL 按行程分区下采样 (保首末点), 预算 per = 4000/段数 (下限 200)
    track_sql, track_params = seen["calls"][1]
    assert "PARTITION BY pos.drive_id" in track_sql
    assert "rn = 1 OR rn = cnt" in track_sql
    assert track_params == {"ids": [12, 11], "per": 2000}


def test_merged_track_dedupes_ids(auth, monkeypatch):
    """重复 id 去重, 仍然只算一段。"""
    seen = []

    def fake_query(sql, params=None):
        seen.append(params)
        if "FROM positions" in sql:
            return [{"drive_id": i, "longitude": 114.0, "latitude": 22.5,
                     "speed": 10, "power": None,
                     "date": datetime(2026, 9, 10, 8) + timedelta(minutes=i)}
                    for i in (11, 12)]
        return [drive_row(id=11), drive_row(id=12, start=datetime(2026, 9, 10, 9))]

    monkeypatch.setattr(m, "query", fake_query)
    r = auth.get("/tesla/trips/api/merged?ids=11,12,11,12")
    assert r.status_code == 200
    assert seen[0] == {"ids": [11, 12]}                # 去重后 2 个 (汇总查询)
    assert seen[1]["per"] == 2000                      # 轨迹查询: 4000/2 段


def test_merged_track_validation_and_404(auth, monkeypatch):
    """参数校验 + 行程缺失/无轨迹 → 404, 前端抹掉地址栏参数。"""
    def never(sql, params=None):
        raise AssertionError("参数非法不应查库")

    monkeypatch.setattr(m, "query", never)
    assert auth.get("/tesla/trips/api/merged?ids=abc").status_code == 400
    assert auth.get("/tesla/trips/api/merged?ids=1").status_code == 400
    assert auth.get("/tesla/trips/api/merged?ids=" +
                    ",".join(str(i) for i in range(51))).status_code == 400
    # 任一行程不存在/未完成 (返回行数对不上) → 404
    monkeypatch.setattr(m, "query", lambda sql, p=None: [])
    r = auth.get("/tesla/trips/api/merged?ids=1,2")
    assert r.status_code == 404
    assert "不存在或未完成" in r.json()["detail"]
    # 行程都在但没有轨迹点 → 404
    monkeypatch.setattr(m, "query", lambda sql, p=None: (
        [{"drive_id": 1, "longitude": 114.0, "latitude": 22.5, "speed": 1, "power": None,
          "date": datetime(2026, 9, 10, 8)}]
        if "FROM positions" in sql else [drive_row(id=1), drive_row(id=2)]))
    r = auth.get("/tesla/trips/api/merged?ids=1,2")
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


def test_trips_page_playback_pacing_and_nowrap(auth):
    """超长轨迹不再 12 秒放完: 时长含里程分量 + 0.5× 慢速档; 统计值不折行。"""
    html = auth.get("/tesla/trips").text
    for frag in ["Math.min(Math.max(N / 300, 3 + cum[N - 1] * 0.35), 90)",
                 "PB_SPEEDS = [0.5, 1, 2, 4, 8]",
                 "white-space: nowrap"]:
        assert frag in html, f"行程页缺少 {frag}"
    # 时长紧凑格式 (两个页面统一)
    assert "`${h}时${m ? m + \"分\" : \"\"}`" in html


def test_trips_page_has_url_deeplink(auth):
    """打开行程地址栏变 ?id=X / 合并 ?ids=a,b: pushState/popstate 同步 + 分享直开。"""
    html = auth.get("/tesla/trips").text
    for frag in ["urlTripKey", "openByKey", "history.pushState", "addEventListener(\"popstate\"",
                 "/tesla/trips/api/sessions/${", "history.replaceState(null, \"\", \"/tesla/trips\")",
                 "it.merged ? \"ids=\" : \"id=\""]:
        assert frag in html, f"行程页缺少深链片段 {frag}"


def test_trips_page_preloads_tiles(auth):
    """播放前预载沿途瓦片: 倍率按里程 + DOM 抄模板 + Image() 刷缓存, 失败静默。"""
    html = auth.get("/tesla/trips").text
    for frag in ["function followZoom(", "async function tileTemplate(", "function tileUrl(",
                 "function preloadTiles(", "正在预载地图", "TrackUtil.lngLatToTile",
                 "appmaptile", "playTrack(c.pts, c.ts || [], it, zoom)",
                 "setTimeout(resolve, 8000)", "trackutil.js?v=8"]:
        assert frag in html, f"行程页缺少瓦片预载片段 {frag}"


def test_trips_page_has_multiselect(auth):
    """多选连续行程: 选择模式 + 底栏 + 合并接口直开都挂在页面上。"""
    html = auth.get("/tesla/trips").text
    for frag in ['id="merge-btn"', 'id="selbar"', 'id="sel-go"', 'id="sel-cancel"',
                 'id="sel-count"', "body.selecting", "pickCard", "enterSelect", "exitSelect",
                 "openMerged", "/tesla/trips/api/merged?ids=", "mergedCache"]:
        assert frag in html, f"行程页缺少多选片段 {frag}"
    # 合并弹层复用播放: pts 随 it 一起传入 (不走单条轨迹接口)
    assert "it.pts ? it : trackCache.get(it.id)" in html
