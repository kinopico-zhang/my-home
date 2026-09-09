"""足迹地图 API 测试 (下采样 / 缓存 / 增量逻辑)。"""
import json
from datetime import datetime

import app.main as m


def pos_row(drive_id, lng, lat, start, dist=12.34, dur=25):
    """构造 TRACKS_SQL 的一行下采样结果。"""
    return {"drive_id": drive_id, "longitude": lng, "latitude": lat,
            "start_date": start, "distance": dist, "duration_min": dur}


# ---------------------------------------------------------------- 纯函数
def test_group_tracks_groups_rounds_and_drops_single_points():
    rows = [
        pos_row(1, 113.91234567, 22.65432109, datetime(2026, 8, 1, 2, 0)),
        pos_row(1, 113.92, 22.66, datetime(2026, 8, 1, 2, 0)),
        pos_row(2, 114.05, 22.55, datetime(2026, 9, 1, 6, 0), dist=30.0),
        pos_row(2, 114.06, 22.56, datetime(2026, 9, 1, 6, 0), dist=30.0),
        pos_row(3, 114.10, 22.60, datetime(2026, 9, 2, 6, 0)),  # 单点行程 → 丢弃
    ]
    ts = m._group_tracks(rows)
    assert [t["id"] for t in ts] == [1, 2]
    assert ts[0]["pts"][0] == [113.91235, 22.65432]   # 坐标取 5 位小数
    assert ts[0]["km"] == 12.3
    assert ts[1]["km"] == 30.0
    assert ts[1]["min"] == 25


def test_drive_range_clause():
    assert m.drive_range_clause({}) == "TRUE"
    assert "d.start_date >=" in m.drive_range_clause({"from": "2026-01-01"})
    assert "d.start_date <" in m.drive_range_clause({"to": "2026-01-31"})


# ---------------------------------------------------------------- config
def test_config_empty_without_env(auth, monkeypatch):
    monkeypatch.delenv("AMAP_KEY", raising=False)
    monkeypatch.delenv("AMAP_SECURITY_CODE", raising=False)
    assert auth.get("/tesla/map/api/config").json() == \
        {"amap_key": None, "security_code": None}


def test_config_returns_env_values(auth, monkeypatch):
    monkeypatch.setenv("AMAP_KEY", "abc123")
    monkeypatch.setenv("AMAP_SECURITY_CODE", "sec456")
    assert auth.get("/tesla/map/api/config").json() == \
        {"amap_key": "abc123", "security_code": "sec456"}


# ---------------------------------------------------------------- summary
def test_map_summary(auth, monkeypatch):
    monkeypatch.setattr(m, "query", lambda sql, params=None: [{
        "drives": 1770, "km": 52525.4, "duration_min": 66000,
        "first_date": datetime(2025, 3, 24), "last_date": datetime(2026, 9, 6)}])
    d = auth.get("/tesla/map/api/summary").json()
    assert d == {"drives": 1770, "distance_km": 52525.4, "duration_min": 66000,
                 "first_date": "2025-03-24", "last_date": "2026-09-06"}


# ---------------------------------------------------------------- tracks + 缓存
def test_tracks_cold_cache_queries_everything(auth, monkeypatch, tmp_path):
    seen = {}

    def qt(after):
        seen["after"] = after
        return m._group_tracks([
            pos_row(5, 114.05, 22.55, datetime(2026, 9, 1, 2, 0)),
            pos_row(5, 114.06, 22.56, datetime(2026, 9, 1, 2, 0)),
        ])

    monkeypatch.setattr(m, "_drive_max_id", lambda: 5)
    monkeypatch.setattr(m, "_query_tracks", qt)
    r = auth.get("/tesla/map/api/tracks")
    assert r.status_code == 200
    d = r.json()
    assert d["count"] == 1
    assert d["tracks"][0]["id"] == 5
    assert seen["after"] == -1               # 无缓存 → 全量
    # 结果落盘 (带算法版本号)
    cache = json.loads((tmp_path / "tracks_cache.json").read_text())
    assert cache["max_id"] == 5
    assert cache["v"] == m.TRACKS_CACHE_VERSION
    assert cache["tracks"][0]["id"] == 5


def test_tracks_warm_memory_cache_skips_query(auth, monkeypatch):
    track = {"id": 1, "date": "2026-08-01", "km": 10.0, "min": 20,
             "pts": [[114.0, 22.5], [114.1, 22.6]]}
    monkeypatch.setattr(m, "_tracks_mem", {"max_id": 10, "tracks": [track]})
    monkeypatch.setattr(m, "_drive_max_id", lambda: 10)

    def boom(after):
        raise AssertionError("缓存已最新, 不应查询数据库")

    monkeypatch.setattr(m, "_query_tracks", boom)
    assert auth.get("/tesla/map/api/tracks").json()["count"] == 1


def test_tracks_disk_cache_used_without_query(auth, monkeypatch, tmp_path):
    track = {"id": 3, "date": "2026-07-01", "km": 1.0, "min": 5,
             "pts": [[114.0, 22.5], [114.1, 22.6]]}
    (tmp_path / "tracks_cache.json").write_text(json.dumps(
        {"v": m.TRACKS_CACHE_VERSION, "max_id": 3, "tracks": [track]}))
    monkeypatch.setattr(m, "_drive_max_id", lambda: 3)   # 无新行程

    def boom(after):
        raise AssertionError("磁盘缓存已最新, 不应查询数据库")

    monkeypatch.setattr(m, "_query_tracks", boom)
    d = auth.get("/tesla/map/api/tracks").json()
    assert d["count"] == 1
    assert d["tracks"][0]["id"] == 3


def test_tracks_old_cache_version_triggers_full_rebuild(auth, monkeypatch, tmp_path):
    """旧版本缓存 (无 v 字段) 必须作废全量重建, 不能直接复用旧采样。"""
    track = {"id": 1, "date": "2026-01-01", "km": 5.0, "min": 10,
             "pts": [[114.0, 22.5], [114.1, 22.6]]}
    (tmp_path / "tracks_cache.json").write_text(
        json.dumps({"max_id": 3, "tracks": [track]}))    # 无 v → 版本不符
    monkeypatch.setattr(m, "_drive_max_id", lambda: 3)
    seen = {}

    def qt(after):
        seen["after"] = after
        return [track]

    monkeypatch.setattr(m, "_query_tracks", qt)
    assert auth.get("/tesla/map/api/tracks").json()["count"] == 1
    assert seen["after"] == -1                    # 无视磁盘 max_id, 全量重建
    cache = json.loads((tmp_path / "tracks_cache.json").read_text())
    assert cache["v"] == m.TRACKS_CACHE_VERSION   # 重建后写入新版本号


def test_tracks_incremental_append(auth, monkeypatch, tmp_path):
    old = {"id": 5, "date": "2026-08-01", "km": 10.0, "min": 20,
           "pts": [[114.0, 22.5], [114.1, 22.6]]}
    monkeypatch.setattr(m, "_tracks_mem", {"max_id": 5, "tracks": [old]})
    monkeypatch.setattr(m, "_drive_max_id", lambda: 8)
    seen = {}

    def qt(after):
        seen["after"] = after
        return [{"id": 8, "date": "2026-09-01", "km": 8.0, "min": 15,
                 "pts": [[114.2, 22.7], [114.3, 22.8]]}]

    monkeypatch.setattr(m, "_query_tracks", qt)
    d = auth.get("/tesla/map/api/tracks").json()
    assert seen["after"] == 5                    # 只查 id > 5 的新行程
    assert [t["id"] for t in d["tracks"]] == [5, 8]   # 按日期排序
    cache = json.loads((tmp_path / "tracks_cache.json").read_text())
    assert cache["max_id"] == 8
    assert len(cache["tracks"]) == 2


def test_diag_endpoint_logs_and_requires_auth(auth, capsys):
    r = auth.post("/tesla/map/api/diag", json={"stage": "map_complete", "ua": "test"})
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert "MAPDIAG" in capsys.readouterr().out
    # 未登录 401
    from fastapi.testclient import TestClient
    assert TestClient(m.app).post(
        "/tesla/map/api/diag", json={"stage": "x"}).status_code == 401


# ---------------------------------------------------------------- 视野内高精度轨迹
def detail_row(drive_id, lng, lat):
    return {"drive_id": drive_id, "longitude": lng, "latitude": lat}


def test_group_detail_groups_and_drops_single_points():
    rows = [
        detail_row(7, 114.05, 22.55), detail_row(7, 114.06, 22.56),
        detail_row(9, 114.10, 22.60),  # 单点 → 丢弃
    ]
    ts = m._group_detail(rows)
    assert ts == [{"id": 7, "pts": [[114.05, 22.55], [114.06, 22.56]]}]


def test_tracks_detail_endpoint(auth, monkeypatch):
    seen = {}

    def fake_query(sql, params=None):
        seen["sql"], seen["params"] = sql, params
        return [detail_row(7, 114.05, 22.55), detail_row(7, 114.06, 22.56)]

    monkeypatch.setattr(m, "query", fake_query)
    r = auth.get("/tesla/map/api/tracks/detail",
                 params={"ids": "7,8", "zoom": 13,
                         "w": 113.9, "s": 22.4, "e": 114.2, "n": 22.7})
    assert r.status_code == 200
    assert r.json() == {"count": 1, "tracks": [
        {"id": 7, "pts": [[114.05, 22.55], [114.06, 22.56]]}]}
    assert "ANY(%(ids)s)" in seen["sql"]      # 走 drive_id 索引
    assert "BETWEEN %(w)s AND %(e)s" in seen["sql"]   # 视野框过滤
    assert seen["params"]["ids"] == [7, 8]
    # 只有 2 条轨迹: 预算均摊后不设限 (全精度)
    assert seen["params"]["per"] == 5000
    assert seen["params"]["w"] == 113.9


def test_tracks_detail_zoom15_is_full_resolution(auth, monkeypatch):
    seen = {}

    def fake_query(sql, params=None):
        seen.update(params)
        return []

    monkeypatch.setattr(m, "query", fake_query)
    r = auth.get("/tesla/map/api/tracks/detail",
                 params={"ids": "1", "zoom": 15,
                         "w": 113, "s": 22, "e": 115, "n": 24})
    assert r.status_code == 200
    assert seen["per"] == 5000                # 轨迹稀少时接近全精度


def test_tracks_detail_caps_ids_and_spreads_budget(auth, monkeypatch):
    """id 上限 150; 密集时总点数预算均摊到每条轨迹 (200 条走 4 路并行)。"""
    seen = {}

    def fake_query(sql, params=None):
        seen.setdefault("ids", []).extend(params["ids"])
        seen["per"] = params["per"]
        seen.setdefault("sizes", []).append(len(params["ids"]))
        return []

    monkeypatch.setattr(m, "query", fake_query)
    ids = ",".join(str(i) for i in range(200))
    r = auth.get("/tesla/map/api/tracks/detail",
                 params={"ids": ids, "zoom": 12,
                         "w": 113, "s": 22, "e": 115, "n": 24})
    assert r.status_code == 200
    assert len(seen["ids"]) == m.DETAIL_MAX_IDS == 150   # 4 份合计仍是 150
    assert sorted(seen["sizes"]) == [37, 37, 38, 38]     # 均匀拆 4 份
    # 12 级预算 20000 均摊给 150 条 → 每条 133 点
    assert seen["per"] == m.DETAIL_BUDGET[12] // 150


def test_tracks_detail_rejects_bad_input(auth, monkeypatch):
    def boom(sql, params=None):
        raise AssertionError("参数非法不应查询数据库")

    monkeypatch.setattr(m, "query", boom)
    base = "/tesla/map/api/tracks/detail"
    # ids 非数字 → 400
    assert auth.get(base, params={"ids": "abc", "zoom": 13,
                                  "w": 113, "s": 22, "e": 115, "n": 24}).status_code == 400
    # bbox 非法 (w >= e) → 400
    assert auth.get(base, params={"ids": "1", "zoom": 13,
                                  "w": 115, "s": 22, "e": 113, "n": 24}).status_code == 400
    # 空 ids → 200 空结果, 不查库
    r = auth.get(base, params={"ids": "", "zoom": 13,
                               "w": 113, "s": 22, "e": 115, "n": 24})
    assert r.status_code == 200 and r.json()["count"] == 0


def test_tracks_date_filtering(auth, monkeypatch):
    tracks = [
        {"id": 1, "date": "2026-01-15", "km": 1, "min": 5, "pts": [[114, 22], [114.1, 22.1]]},
        {"id": 2, "date": "2026-08-01", "km": 1, "min": 5, "pts": [[114, 22], [114.1, 22.1]]},
        {"id": 3, "date": "2026-09-01", "km": 1, "min": 5, "pts": [[114, 22], [114.1, 22.1]]},
    ]
    monkeypatch.setattr(m, "_tracks_mem", {"max_id": 3, "tracks": tracks})
    monkeypatch.setattr(m, "_drive_max_id", lambda: 3)
    base = "/tesla/map/api/tracks"
    assert [t["id"] for t in auth.get(base).json()["tracks"]] == [1, 2, 3]
    ids = lambda qs: [t["id"] for t in auth.get(base + qs).json()["tracks"]]
    assert ids("?from=2026-07-01") == [2, 3]
    assert ids("?to=2026-08-31") == [1, 2]
    assert ids("?from=2026-07-01&to=2026-08-31") == [2]
