"""行程轨迹页 API 测试 (列表分页 / 单条全精度轨迹 / 参数校验 / 多选合并)。"""
from datetime import datetime, timedelta

from app import repository
from app.models import Address
from tests.conftest import seed_addresses, seed_drive, seed_position


# ---------------------------------------------------------------- 列表
def test_trips_sessions_paginates(auth, db):
    seed_addresses(db)
    for i in range(3):
        seed_drive(db, id=i + 1, distance=42.5, duration_min=72, speed_max=118,
                   start_date=datetime(2026, 9, 10 - i, 0, 32),
                   end_date=datetime(2026, 9, 10 - i, 1, 44))
    r = auth.get("/tesla/trips/api/sessions?offset=0&limit=2")
    assert r.status_code == 200
    d = r.json()
    assert d["total"] == 3
    assert len(d["items"]) == 2
    it = d["items"][0]
    assert it["id"] == 1
    assert it["date"] == "2026-09-10"          # UTC 00:32 → 北京 08:32
    assert it["start"] == "2026-09-10 08:32"
    assert it["end"] == "2026-09-10 09:44"
    assert it["km"] == 42.5
    assert it["min"] == 72
    assert it["speed_max"] == 118
    assert it["from"] == "广东省深圳市龙岗区坂田街道"   # 地址用 display_name
    assert it["to"] == "广东省东莞市长安镇"


def test_trips_sessions_address_cleanup(auth, db):
    """反向地理编码带来的尾部悬挂逗号/空白要清掉, 空地址兜底 未知位置。"""
    db.add(Address(id=1, name="a", city="c", display_name="广东省深圳市南山区, "))
    db.add(Address(id=2, name="b", city="c", display_name=None))
    db.commit()
    seed_drive(db, id=1)
    it = auth.get("/tesla/trips/api/sessions").json()["items"][0]
    assert it["from"] == "广东省深圳市南山区"    # 尾部 ", " 已清
    assert it["to"] == "未知位置"


def test_trips_sessions_tolerates_missing_fields(auth, db):
    """distance/duration/speed 为空时不炸, 前端显示 —。"""
    seed_drive(db, id=1, distance=None, duration_min=None, speed_max=None,
               start_address_id=None, end_address_id=None)
    it = auth.get("/tesla/trips/api/sessions").json()["items"][0]
    assert it["end"] is not None
    assert it["min"] is None and it["km"] is None and it["speed_max"] is None
    assert it["from"] == "未知位置" and it["to"] == "未知位置"


def test_trips_sessions_rejects_bad_pagination(auth, monkeypatch):
    def boom(*_args):
        raise AssertionError("参数非法不应查库")

    monkeypatch.setattr(repository, "list_trips", boom)
    base = "/tesla/trips/api/sessions"
    assert auth.get(base, params={"offset": -1}).status_code == 400
    assert auth.get(base, params={"limit": 0}).status_code == 400
    assert auth.get(base, params={"limit": 101}).status_code == 400


def test_trips_sessions_excludes_unfinished(auth, db):
    """未关闭行程 (TeslaMate 记录中断留下的 end_date 空行) 不进列表/单条,
    口径与 Grafana 行程面板 / 地图页全量轨迹一致。"""
    seed_addresses(db)
    seed_drive(db, id=1)
    seed_drive(db, id=1838, start_date=datetime(2026, 8, 21, 9, 7),
               end_date=None, distance=None, duration_min=None,
               speed_max=None, start_address_id=None, end_address_id=None)
    d = auth.get("/tesla/trips/api/sessions").json()
    assert d["total"] == 1
    assert [i["id"] for i in d["items"]] == [1]
    assert auth.get("/tesla/trips/api/sessions/1838").status_code == 404


def test_trip_session_one(auth, db):
    """单条行程接口: 分享链接 /tesla/trips?id=X 直开弹层时前端拉取。"""
    seed_addresses(db)
    seed_drive(db, id=1838)
    r = auth.get("/tesla/trips/api/sessions/1838")
    assert r.status_code == 200
    assert r.json() == {
        "id": 1838, "date": "2026-09-10",
        "start": "2026-09-10 08:32", "end": "2026-09-10 09:44",
        "km": 42.5, "min": 72, "speed_max": 118,
        "from": "广东省深圳市龙岗区坂田街道", "to": "广东省东莞市长安镇",
    }


def test_trip_session_one_404(auth):
    """不存在 / 未完成的行程 → 404 (前端抹掉地址栏参数)。"""
    assert auth.get("/tesla/trips/api/sessions/9999").status_code == 404


def test_trips_sessions_filters_by_date(auth, db):
    """from/to 按出发日 (本地日期) 过滤; 快捷档与自定义日历共用这两个参数。"""
    seed_addresses(db)
    for i, day in enumerate((10, 20, 25)):
        seed_drive(db, id=i + 1, distance=10.0, duration_min=10, speed_max=50,
                   start_date=datetime(2026, 8, day, 4, 0),
                   end_date=datetime(2026, 8, day, 5, 0))
    base = "/tesla/trips/api/sessions"

    def ids(qs):
        return [i["id"] for i in auth.get(base + qs).json()["items"]]

    assert ids("?from=2026-08-21") == [3]           # 只剩 8/25
    assert ids("?from=2026-08-11&to=2026-08-24") == [2]   # 自定义区间
    assert ids("?to=2026-08-24") == [2, 1]
    assert auth.get(base, params={"from": "abc"}).status_code == 400
    assert auth.get(base, params={"to": "2026-13-99"}).status_code == 400


def test_trips_sessions_filters_by_city_and_km(auth, db):
    """from_city/to_city 按起终城市, km_min/km_max 按里程; 可叠加。"""
    db.add(Address(id=3, name="花城广场", city="广州市",
                   display_name="广东省广州市天河区"))
    db.commit()
    seed_addresses(db)
    # 1: 深圳→东莞 42.5km; 2: 东莞→广州 350km; 3: 深圳→深圳 15km
    seed_drive(db, id=1, distance=42.5, start_address_id=1, end_address_id=2)
    seed_drive(db, id=2, distance=350.0, start_address_id=2, end_address_id=3)
    seed_drive(db, id=3, distance=15.0, start_address_id=1, end_address_id=1)
    base = "/tesla/trips/api/sessions"

    def ids(**params):
        return [i["id"] for i in auth.get(base, params=params).json()["items"]]

    assert ids(from_city="深圳市") == [1, 3]
    assert ids(to_city="东莞市") == [1]
    assert ids(from_city="深圳市", to_city="东莞市") == [1]
    assert ids(km_min=20, km_max=100) == [1]        # 42.5km
    assert ids(km_min=300) == [2]
    assert ids(km_max=20) == [3]                    # 里程档 "20km 内"
    assert ids(from_city="深圳市", km_min=300) == []  # 叠加无交集 → 空列表, 不报错
    assert ids(from_city="不存在的城市") == []


def test_trips_sessions_rejects_bad_km(auth):
    assert auth.get("/tesla/trips/api/sessions",
                    params={"km_min": -1}).status_code == 400
    assert auth.get("/tesla/trips/api/sessions",
                    params={"km_min": 100, "km_max": 20}).status_code == 400
    assert auth.get("/tesla/trips/api/sessions",
                    params={"km_max": 1e7}).status_code == 400


def test_trips_cities_endpoint(auth, db):
    """起终点城市列表 (次数降序): 未结束行程不计, 无城市地址不参与筛选。"""
    db.add(Address(id=3, name="花城广场", city="广州市",
                   display_name="广东省广州市天河区"))
    db.add(Address(id=4, name="无名地", city=None, display_name="某处"))
    db.commit()
    seed_addresses(db)
    # 1: 深圳→东莞; 2: 东莞→广州; 3: 深圳→东莞; 4: (无城市起) 未结束不计数
    seed_drive(db, id=1, distance=10.0, start_address_id=1, end_address_id=2)
    seed_drive(db, id=2, distance=10.0, start_address_id=2, end_address_id=3)
    seed_drive(db, id=3, distance=10.0, start_address_id=1, end_address_id=2)
    seed_drive(db, id=4, distance=10.0, start_address_id=4, end_address_id=2,
               end_date=None)
    d = auth.get("/tesla/trips/api/cities").json()
    assert d == {"start": [{"city": "深圳市", "count": 2},
                           {"city": "东莞市", "count": 1}],
                 "end": [{"city": "东莞市", "count": 2},
                         {"city": "广州市", "count": 1}]}


# ---------------------------------------------------------------- 轨迹
def test_trip_track_full_resolution_with_speed(auth, db):
    seed_addresses(db)
    seed_drive(db, id=7)
    t0 = datetime(2026, 9, 10, 0, 32)
    seed_position(db, 7, id=None, date=t0, longitude=114.05, latitude=22.55,
                  speed=30.0, power=45000.0)
    seed_position(db, 7, id=None,
                  date=t0 + timedelta(minutes=72, seconds=1),
                  longitude=114.06, latitude=22.56, speed=None, power=None)
    r = auth.get("/tesla/trips/api/7/track")
    assert r.status_code == 200
    # 每点 [lng, lat, speed, power_W]; 速度缺失按 0 (停车), power 可为 null;
    # ts 是相对起点的秒偏移 (播放动画里算"已行驶时长"和平均功耗)
    assert r.json() == {"id": 7,
                        "pts": [[114.05, 22.55, 30.0, 45000.0],
                                [114.06, 22.56, 0, None]],
                        "ts": [0, 4321]}


def test_trip_track_downsamples_beyond_5000(auth, db):
    """5000 点上限: 超长轨迹等间隔抽取 (首末点必留)。"""
    seed_addresses(db)
    seed_drive(db, id=7, start_date=datetime(2026, 9, 10, 0, 32),
               end_date=datetime(2026, 9, 10, 3, 0))
    t0 = datetime(2026, 9, 10, 0, 32)
    for i in range(10001):
        seed_position(db, 7, id=None, date=t0 + timedelta(seconds=i),
                      longitude=114.0 + i * 1e-5, latitude=22.5)
    d = auth.get("/tesla/trips/api/7/track").json()
    assert 5000 <= len(d["pts"]) <= 5002     # stride=2 → ~5001 点
    assert d["pts"][0][0] == 114.0
    assert d["pts"][-1][0] == round(114.0 + 10000 * 1e-5, 5)
    assert d["ts"][0] == 0 and d["ts"][-1] == 10000


def test_trip_track_404_when_no_points(auth, db):
    seed_addresses(db)
    seed_drive(db, id=999)                       # 0 点
    r = auth.get("/tesla/trips/api/999/track")
    assert r.status_code == 404
    seed_position(db, 999, id=None)              # 只剩 1 个点画不了线, 也算没有
    r = auth.get("/tesla/trips/api/999/track")
    assert r.status_code == 404
    assert "没有轨迹数据" in r.json()["detail"]


# ---------------------------------------------------------------- 合并轨迹 (多选连续行程)
def test_merged_track_stitches_and_skips_parking(auth, db):
    """多段行程拼一条轨迹: pts 按时间串联, ts 是"累计行驶秒" (行程间停驶剔除),
    汇总 = 首段起/末段终 + 各项求和 (前端弹层播放/统计照常)。"""
    db.add(Address(id=3, name="m", city="c", display_name="中途点"))
    db.commit()
    seed_addresses(db)
    t = datetime(2026, 9, 10, 0, 32)             # 北京时间 08:32
    seed_drive(db, id=11, distance=42.5, duration_min=72, speed_max=118,
               start_address_id=1, end_address_id=3, start_date=t,
               end_date=t + timedelta(minutes=72))
    seed_position(db, 11, id=None, date=t, longitude=114.05, latitude=22.55,
                  speed=30.0, power=45000.0)
    seed_position(db, 11, id=None, date=t + timedelta(minutes=10),
                  longitude=114.06, latitude=22.56, speed=40.0, power=None)
    # 停驶 2h50m 后的第二段 (这段间隔不应计入 ts)
    seed_drive(db, id=12, distance=10.04, duration_min=10, speed_max=96,
               start_address_id=3, end_address_id=2,
               start_date=t + timedelta(hours=3),
               end_date=t + timedelta(hours=3, minutes=10))
    seed_position(db, 12, id=None, date=t + timedelta(hours=3),
                  longitude=114.07, latitude=22.57, speed=50.0, power=30000.0)
    seed_position(db, 12, id=None, date=t + timedelta(hours=3, minutes=10),
                  longitude=114.08, latitude=22.58, speed=None, power=None)
    r = auth.get("/tesla/trips/api/merged?ids=12,11")   # 乱序传入
    assert r.status_code == 200
    d = r.json()
    assert d["ids"] == [11, 12] and d["n"] == 2
    assert d["pts"] == [[114.05, 22.55, 30.0, 45000.0],
                        [114.06, 22.56, 40.0, None],
                        [114.07, 22.57, 50.0, 30000.0],
                        [114.08, 22.58, 0, None]]
    # 第二段从上一段末尾继续累计: 中间 2h50m 停驶不进 ts
    assert d["ts"] == [0, 600, 600, 1200]
    # 汇总: 首段起 / 末段终, 里程/时长求和, 最高速取 max
    assert d["km"] == 52.54 and d["min"] == 82 and d["speed_max"] == 118
    assert d["date"] == "2026-09-10"
    assert d["start"] == "2026-09-10 08:32" and d["end"] == "2026-09-10 11:42"
    assert d["from"] == "广东省深圳市龙岗区坂田街道"
    assert d["to"] == "广东省东莞市长安镇"


def test_merged_track_downsamples_each_segment(auth, db):
    """每段下采样预算 per = max(200, 4000/段数): 段多时每段仍有保底点数。"""
    seed_addresses(db)
    t = datetime(2026, 9, 10, 0, 32)
    for drive_id in (11, 12):
        seed_drive(db, id=drive_id, distance=5.0, duration_min=5, speed_max=50,
                   start_date=t + timedelta(hours=drive_id * 3),
                   end_date=t + timedelta(hours=drive_id * 3, minutes=10))
        for i in range(400):
            seed_position(db, drive_id, id=None,
                          date=t + timedelta(hours=drive_id * 3, seconds=i),
                          longitude=114.0 + i * 1e-5, latitude=22.5)
    d = auth.get("/tesla/trips/api/merged?ids=11,12").json()
    # 4000/2 = 2000/段 → stride=1 → 全保留
    assert len(d["pts"]) == 800


def test_merged_track_dedupes_ids(auth, db):
    """重复 id 去重, 仍然只算一段。"""
    seed_addresses(db)
    t = datetime(2026, 9, 10, 0, 32)
    for drive_id in (11, 12):
        seed_drive(db, id=drive_id, start_date=t + timedelta(hours=drive_id),
                   end_date=t + timedelta(hours=drive_id, minutes=10))
        seed_position(db, drive_id, id=None,
                      date=t + timedelta(hours=drive_id), longitude=114.0,
                      latitude=22.5, speed=10.0, power=None)
        seed_position(db, drive_id, id=None,
                      date=t + timedelta(hours=drive_id, minutes=10),
                      longitude=114.1, latitude=22.5, speed=10.0, power=None)
    r = auth.get("/tesla/trips/api/merged?ids=11,12,11,12")
    assert r.status_code == 200
    assert r.json()["ids"] == [11, 12]        # 去重后 2 个
    assert r.json()["n"] == 2


def test_merged_track_validation_and_404(auth, monkeypatch):
    def never(*_args):
        raise AssertionError("参数非法不应查库")

    monkeypatch.setattr(repository, "merged_track", never)
    assert auth.get("/tesla/trips/api/merged?ids=abc").status_code == 400
    assert auth.get("/tesla/trips/api/merged?ids=1").status_code == 400
    assert auth.get("/tesla/trips/api/merged?ids=" +
                    ",".join(str(i) for i in range(51))).status_code == 400
    # 任一行程不存在/未完成 → 404
    def raise_not_found(*_args):
        raise repository.NotFound("包含不存在或未完成的行程")

    monkeypatch.setattr(repository, "merged_track", raise_not_found)
    r = auth.get("/tesla/trips/api/merged?ids=1,2")
    assert r.status_code == 404
    assert "不存在或未完成" in r.json()["detail"]


def test_merged_track_404_when_no_points(auth, db):
    """行程都在但没有轨迹点 → 404, 前端抹掉地址栏参数。"""
    seed_addresses(db)
    t = datetime(2026, 9, 10, 0, 32)
    seed_drive(db, id=1, start_date=t, end_date=t + timedelta(minutes=10))
    seed_drive(db, id=2, start_date=t + timedelta(hours=1),
               end_date=t + timedelta(hours=1, minutes=10))
    r = auth.get("/tesla/trips/api/merged?ids=1,2")
    assert r.status_code == 404
    assert "没有轨迹数据" in r.json()["detail"]


# ---------------------------------------------------------------- 页面
def test_trips_page_time_menu_and_filter_row(auth):
    """顶栏时间下拉 (快捷档 + 自定义日历) + 筛选行 (起点/终点城市, 里程档),
    全部编码进 URL, 且与 ?id=/ ?ids= 深链共存。"""
    html = auth.get("/tesla/trips").text
    for frag in ['id="time-menu"', 'data-v="24h"', 'data-v="7d"', 'data-v="30d"',
                 'data-v="180d"', 'data-v="1y"', 'data-v="all"',
                 'data-v="custom"', 'id="tm-from"', 'id="tm-to"', 'id="tm-apply"',
                 'id="fc-menu"', 'id="tc-menu"', 'id="km-menu"',
                 'data-k="0-20"', 'data-k="20-100"', 'data-k="100-300"',
                 'data-k="300+"', "/tesla/trips/api/cities",
                 "function filterQS()", "function listURL(", "function syncURL()",
                 'p.set("from_city", state.fromCity)', 'p.set("km_min", kb.min)']:
        assert frag in html, f"行程页缺少 {frag}"
    assert "chips-range" not in html
    for i in ('time-menu', 'time-lb', 'time-opts', 'tm-dates', 'nav-menu',
              'fc-opts', 'tc-opts', 'km-opts'):
        assert html.count(f'id="{i}"') == 1, f"页面 {i} 重复"


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
    for frag in ["urlTripKey", "openByKey", "history.pushState",
                 "addEventListener(\"popstate\"",
                 "/tesla/trips/api/sessions/${",
                 "history.pushState({ k: curKey }, \"\", listURL(curKey))",
                 "history.replaceState(null, \"\", listURL())",
                 'key.includes(",") ? "ids=" : "id="']:
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
