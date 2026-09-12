"""行程轨迹页 API 测试 (列表分页 / 单条全精度轨迹 / 参数校验 / 多选合并 /
头尾区间 / 流式下载 / 断档补路自有库)。"""
import json
import re
from datetime import datetime, timedelta

from app import repository
from app.models import (Address, Drive, Driver, Position, TrackFill,
                        TripDriver, TripToll)
from tests.conftest import (seed_addresses, seed_charging, seed_drive,
                            seed_position)


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
        "driver": None, "driver_id": None,     # 没配司机 → 不显示
        "toll": None, "toll_km": None,         # 高速费还没算过
        "kwh": None, "wh_per_km": None,        # 没有充电记录 → 换算系数缺失
    }


def test_trip_session_one_404(auth):
    """不存在 / 未完成的行程 → 404 (前端抹掉地址栏参数)。"""
    assert auth.get("/tesla/trips/api/sessions/9999").status_code == 404


def test_trip_driver_mark(auth, db, owndb):
    """标/清行程驾驶员: 展示名显式标注 > 默认司机兜底; 删司机联动清标注。"""
    seed_addresses(db)
    seed_drive(db, id=1838)
    owndb.add(Driver(id=1, name="大导子", is_default=True))
    owndb.add(Driver(id=2, name="小导子"))
    owndb.commit()
    base = "/tesla/trips/api/sessions/1838"

    it = auth.get(base).json()
    assert it["driver"] == "大导子"            # 未标注 → 默认司机
    assert it["driver_id"] is None             # 但显式标注为空

    it = auth.post("/tesla/trips/api/1838/driver",
                   json={"driver_id": 2}).json()
    assert it["driver"] == "小导子" and it["driver_id"] == 2
    lst = auth.get("/tesla/trips/api/sessions").json()["items"]
    assert lst[0]["driver"] == "小导子"        # 列表同样带标注

    it = auth.post("/tesla/trips/api/1838/driver",
                   json={"driver_id": None}).json()
    assert it["driver"] == "大导子" and it["driver_id"] is None   # 清除回默认

    auth.post("/tesla/trips/api/1838/driver", json={"driver_id": 2})
    auth.delete("/tesla/api/drivers/2")       # 删司机 → 标注联动清掉
    it = auth.get(base).json()
    assert it["driver"] == "大导子" and it["driver_id"] is None


def test_trip_list_filters_by_driver(auth, db, owndb):
    """行程列表按驾驶员筛选, 与卡片展示同口径: 显式标注的 + 默认司机时
    未标注的 (未标注在卡片上就显示默认司机名)。"""
    seed_addresses(db)
    for did in (11, 12, 13):
        seed_drive(db, id=did)
    owndb.add(Driver(id=1, name="大导子", is_default=True))
    owndb.add(Driver(id=2, name="小导子"))
    owndb.add(TripDriver(drive_id=11, driver_id=2))
    owndb.commit()

    lst = auth.get("/tesla/trips/api/sessions?driver_id=2").json()
    assert [x["id"] for x in lst["items"]] == [11]
    assert lst["total"] == 1

    lst = auth.get("/tesla/trips/api/sessions?driver_id=1").json()   # 默认 → 含未标注
    assert sorted(x["id"] for x in lst["items"]) == [12, 13]
    assert lst["total"] == 2

    lst = auth.get("/tesla/trips/api/sessions?driver_id=99").json()  # 司机不存在 → 空
    assert lst["items"] == [] and lst["total"] == 0


def test_trip_consumption_from_charge_calibration(auth, db):
    """电耗 = 额定续航差 × 充电换算系数 (桩端口径): 列表/单条/合并三处同源;
    续航回弹夹 0, 里程不足 1km 不算平均。"""
    seed_addresses(db)
    # 充电记录定标: 30 kWh 换 200km 额定续航 → 0.15 kWh/km
    seed_charging(db, id=1, charge_energy_added=30.0,
                  start_rated_range_km=100.0, end_rated_range_km=300.0)
    t = datetime(2026, 9, 10, 0, 32)

    def drive(did, dist, s_rated, e_rated, with_pts=False):
        seed_drive(db, id=did, distance=dist, duration_min=60,
                   start_date=t + timedelta(hours=did),
                   end_date=t + timedelta(hours=did, minutes=60),
                   start_rated_range_km=s_rated, end_rated_range_km=e_rated)
        if with_pts:      # 合并轨迹需要位置点
            for k, lng in enumerate((114.1, 114.2)):
                seed_position(db, did, id=None,
                              date=t + timedelta(hours=did, minutes=10 * k),
                              longitude=lng, latitude=22.5, speed=10.0, power=None)

    drive(11, 80.0, 200.0, 100.0, with_pts=True)   # 15.0 kWh, 187.5 Wh/km
    drive(12, 30.0, 100.0, 80.0, with_pts=True)    # 3.0 kWh, 100 Wh/km
    drive(13, 50.0, 100.0, 110.0)                  # 续航回弹 → 夹 0
    drive(14, 0.4, 200.0, 198.0)                   # 里程 <1km → 平均 None

    by_id = {x["id"]: x
             for x in auth.get("/tesla/trips/api/sessions").json()["items"]}
    assert by_id[11]["kwh"] == 15.0 and by_id[11]["wh_per_km"] == 188.0
    assert by_id[12]["kwh"] == 3.0 and by_id[12]["wh_per_km"] == 100.0
    assert by_id[13]["kwh"] == 0.0 and by_id[13]["wh_per_km"] == 0.0
    assert by_id[14]["kwh"] == 0.3 and by_id[14]["wh_per_km"] is None

    one = auth.get("/tesla/trips/api/sessions/11").json()
    assert one["kwh"] == 15.0 and one["wh_per_km"] == 188.0

    merged = auth.get("/tesla/trips/api/merged?ids=11,12").json()
    assert merged["kwh"] == 18.0                       # 15.0 + 3.0
    assert merged["wh_per_km"] == round(18.0 / 110 * 1000)   # ≈164


def test_trip_toll_store_and_readback(auth, db, owndb):
    """高速费估价回传: 存自有库, 列表/单条回读; 重传覆盖; ¥0 也算有效结果。"""
    seed_addresses(db)
    seed_drive(db, id=1838)
    base = "/tesla/trips/api"

    r = auth.post(f"{base}/1838/toll", json={
        "tolls": 29.0, "toll_km": 40.2, "distance": 77863,
        "roads": [{"road": "G4京港澳高速", "tolls": 14.0},
                  {"road": "S15沈海高速广州支线", "tolls": 7.0}]})
    assert r.status_code == 200 and r.json()["ok"] is True
    it = auth.get(f"{base}/sessions/1838").json()
    assert it["toll"] == 29.0 and it["toll_km"] == 40.2
    lst = auth.get(f"{base}/sessions").json()["items"]
    assert lst[0]["toll"] == 29.0            # 列表同样带估价

    # 跨省长途: 规划里程 178km 也要收 (上限 1000km)
    r = auth.post(f"{base}/1838/toll", json={
        "tolls": 69.0, "toll_km": 114.4, "distance": 178478,
        "roads": [{"road": "G4京港澳高速", "tolls": 69.0}]})
    assert r.status_code == 200

    auth.post(f"{base}/1838/toll", json={
        "tolls": 0, "toll_km": 0, "distance": 12000, "roads": []})   # 重算覆盖
    it = auth.get(f"{base}/sessions/1838").json()
    assert it["toll"] == 0                   # ¥0 = 算过没走收费路, 不是没算

    row = owndb.query(TripToll).filter_by(drive_id=1838).one()   # 只存自有库一行
    assert row.distance == 12000 and "G4" in row.roads or row.roads == "[]"


def test_trip_toll_errors(auth, db):
    """行程不存在 → 404; 负数/越界估价 → 422 (pydantic 校验)。"""
    seed_addresses(db)
    seed_drive(db, id=1838)
    assert auth.post("/tesla/trips/api/9999/toll", json={
        "tolls": 1, "toll_km": 1, "distance": 1, "roads": []}).status_code == 404
    assert auth.post("/tesla/trips/api/1838/toll", json={
        "tolls": -5, "toll_km": 1, "distance": 1, "roads": []}).status_code == 422


def test_trip_driver_mark_errors(auth, db):
    """行程不存在 / 司机不存在 → 404。"""
    assert auth.post("/tesla/trips/api/9999/driver",
                     json={"driver_id": 1}).status_code == 404
    seed_addresses(db)
    seed_drive(db, id=1838)
    r = auth.post("/tesla/trips/api/1838/driver", json={"driver_id": 77})
    assert r.status_code == 404
    assert "司机不存在" in r.json()["detail"]


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


def test_parse_region_osm_and_legacy_formats():
    """display_name → (省, 市, 区县): OSM 逗号链 / 旧连写 / 各种真实脏数据。

    真库 547 条地址全量验证过的样本: 街道邮编中国大陆尾巴、区县重复
    ("…, 顺德区, 佛山市, 顺德区, 广东省")、POI 名带区字样、省直辖县、自治州。
    """
    p = repository.parse_region
    assert p("竹村, 福城街道, 龙华区, 深圳市, 广东省, 518110, 中国") == \
        ("广东省", "深圳市", "龙华区")
    # 尾巴带 "中国大陆" + 邮编
    assert p("广百新一城, 宝岗大道, 龙凤街道, 海珠区, 广州市, 广东省, "
             "中国大陆, 510250, 中国") == ("广东省", "广州市", "海珠区")
    # 区县重复: 从省向左先找到市 (佛山市), 再向左找到区 (顺德区)
    assert p("容山路, 食品厂, 容桂街道, 顺德区, 佛山市, 顺德区, 广东省, "
             "528300, 中国") == ("广东省", "佛山市", "顺德区")
    # POI 名带 "区" 字样 (A区/园区) 不会误当行政区
    assert p("华为溪流背坡村A区, 松山湖园区, 大朗镇, 东莞市, 广东省, "
             "523003, 中国") == ("广东省", "东莞市", "大朗镇")
    # 省直辖县: 没有市级, 区县提升到市层 (与级联菜单的第二级对齐)
    assert p("曼旦村, 勐腊县, 云南省, 666300, 中国") == ("云南省", "勐腊县", None)
    # 自治州作市层, 县级市作区县层
    assert p("广场大道, 曼景兰, 允景洪街道, 景洪市, 西双版纳傣族自治州, "
             "云南省, 666100, 中国") == ("云南省", "西双版纳傣族自治州", "景洪市")
    # 旧版连写格式 (conftest 种子 / 老数据)
    assert p("广东省深圳市龙岗区坂田街道") == ("广东省", "深圳市", "龙岗区")
    assert p("广东省东莞市长安镇") == ("广东省", "东莞市", "长安镇")
    # 解析不出省 = 无地区信息
    assert p("某处") == (None, None, None)
    assert p("") == (None, None, None)


def test_trips_sessions_filters_by_region_and_km(auth, db):
    """from_loc/to_loc 按省/市/区县路径过滤 (段数即精确度), km 按里程; 可叠加。"""
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

    assert ids(from_loc="广东省") == [1, 2, 3]        # 省级: 整省
    assert ids(from_loc="广东省/深圳市") == [1, 3]    # 市级
    assert ids(from_loc="广东省/深圳市/龙岗区") == [1, 3]   # 区县级
    assert ids(to_loc="广东省/东莞市") == [1]
    assert ids(to_loc="广东省/东莞市/长安镇") == [1]
    assert ids(from_loc="广东省/深圳市", to_loc="广东省/东莞市") == [1]
    assert ids(km_min=20, km_max=100) == [1]          # 42.5km
    assert ids(km_min=300) == [2]
    assert ids(km_max=20) == [3]                      # 里程档 "20km 内"
    assert ids(from_loc="广东省/深圳市", km_min=300) == []  # 叠加无交集 → 空
    assert ids(from_loc="不存在的省") == []
    # 路径超过 3 段 → 400
    assert auth.get(base, params={"from_loc": "广东省/深圳市/龙岗区/坂田街道"}
                    ).status_code == 400


def test_trips_sessions_rejects_bad_km(auth):
    assert auth.get("/tesla/trips/api/sessions",
                    params={"km_min": -1}).status_code == 400
    assert auth.get("/tesla/trips/api/sessions",
                    params={"km_min": 100, "km_max": 20}).status_code == 400
    assert auth.get("/tesla/trips/api/sessions",
                    params={"km_max": 1e7}).status_code == 400


def test_trips_regions_endpoint(auth, db):
    """起终点省市区树: 三级嵌套 + 计数 (次数降序); 未结束行程不计,
    解析不出省的地址不进树。"""
    db.add(Address(id=3, name="花城广场", city="广州市",
                   display_name="广东省广州市天河区"))
    db.add(Address(id=6, name="曼旦村", city=None,
                   display_name="曼旦村, 勐腊县, 云南省, 666300, 中国"))
    db.add(Address(id=7, name="无名地", city=None, display_name="某处"))
    db.commit()
    seed_addresses(db)
    # 1: 深圳→东莞; 2: 东莞→广州; 3: 深圳→东莞; 5: 云南→东莞;
    # 4: 起点"某处"且未结束 → 两边都不计
    seed_drive(db, id=1, distance=10.0, start_address_id=1, end_address_id=2)
    seed_drive(db, id=2, distance=10.0, start_address_id=2, end_address_id=3)
    seed_drive(db, id=3, distance=10.0, start_address_id=1, end_address_id=2)
    seed_drive(db, id=5, distance=10.0, start_address_id=6, end_address_id=2)
    seed_drive(db, id=4, distance=10.0, start_address_id=7, end_address_id=2,
               end_date=None)
    d = auth.get("/tesla/trips/api/regions").json()
    assert d == {"start": [
        {"name": "广东省", "count": 3, "children": [
            {"name": "深圳市", "count": 2, "children": [
                {"name": "龙岗区", "count": 2, "children": []}]},
            {"name": "东莞市", "count": 1, "children": [
                {"name": "长安镇", "count": 1, "children": []}]}]},
        {"name": "云南省", "count": 1, "children": [
            {"name": "勐腊县", "count": 1, "children": []}]},
    ], "end": [
        {"name": "广东省", "count": 4, "children": [
            {"name": "东莞市", "count": 3, "children": [
                {"name": "长安镇", "count": 3, "children": []}]},
            {"name": "广州市", "count": 1, "children": [
                {"name": "天河区", "count": 1, "children": []}]}]},
    ]}


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
    # 每段起点下标 (前端按段做断档识别, 不混用全局阈值)
    assert d["seg_starts"] == [0, 2]
    # 汇总: 首段起 / 末段终, 里程/时长求和, 最高速取 max
    assert d["km"] == 52.54 and d["min"] == 82 and d["speed_max"] == 118
    assert d["date"] == "2026-09-10"
    assert d["start"] == "2026-09-10 08:32" and d["end"] == "2026-09-10 11:42"
    assert d["from"] == "广东省深圳市龙岗区坂田街道"
    assert d["to"] == "广东省东莞市长安镇"


def test_merged_track_downsamples_each_segment(auth, db):
    """每段预算按原始点数占比分配 (总预算 12000), 短段仍有 200 保底。"""
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
                    ",".join(str(i) for i in range(101))).status_code == 400
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


# ---------------------------------------------------------------- 头尾区间 (连续行程只记首尾 id)
def _seed_pair(db):
    """两段各 2 点的行程 (11 在前 12 在后), 供合并/流式用例复用。"""
    seed_addresses(db)
    t = datetime(2026, 9, 10, 0, 32)
    for drive_id in (11, 12):
        seed_drive(db, id=drive_id, start_date=t + timedelta(hours=drive_id),
                   end_date=t + timedelta(hours=drive_id, minutes=10))
        seed_position(db, drive_id, id=None,
                      date=t + timedelta(hours=drive_id),
                      longitude=114.0 + drive_id * 0.01, latitude=22.5,
                      speed=10.0, power=None)
        seed_position(db, drive_id, id=None,
                      date=t + timedelta(hours=drive_id, minutes=10),
                      longitude=114.1 + drive_id * 0.01, latitude=22.5,
                      speed=10.0, power=None)


def test_merged_range_form_expands_closed_drives(auth, db):
    """ids=首-尾: 展开成区间内全部已结束行程 (未结束的自动跳过), 与逗号形式等价。"""
    _seed_pair(db)
    seed_drive(db, id=13, start_date=datetime(2026, 9, 10, 13, 0),
               end_date=datetime(2026, 9, 10, 13, 10))
    seed_position(db, 13, id=None, date=datetime(2026, 9, 10, 13, 0),
                  longitude=114.3, latitude=22.5, speed=10.0, power=None)
    seed_position(db, 13, id=None, date=datetime(2026, 9, 10, 13, 10),
                  longitude=114.4, latitude=22.5, speed=10.0, power=None)
    seed_drive(db, id=14, start_date=datetime(2026, 9, 10, 13, 0),
               end_date=None)                      # 未结束: 区间内但不该出现
    by_range = auth.get("/tesla/trips/api/merged?ids=11-14").json()
    assert by_range["ids"] == [11, 12, 13]
    by_list = auth.get("/tesla/trips/api/merged?ids=11,12,13").json()
    assert by_range["pts"] == by_list["pts"]
    assert by_range["ts"] == by_list["ts"]
    # 坏区间 (头大于尾 / 非数字) → 400
    assert auth.get("/tesla/trips/api/merged?ids=14-11").status_code == 400
    assert auth.get("/tesla/trips/api/merged?ids=a-b").status_code == 400


def test_merged_range_form_requires_enough_drives(auth, db):
    """区间展开后不足 2 段或超 100 段 → 400 (与逗号形式同口径)。"""
    _seed_pair(db)
    assert auth.get("/tesla/trips/api/merged?ids=11-11").status_code == 400
    assert auth.get("/tesla/trips/api/merged?ids=99-100").status_code == 400
    # 展开后 101 段 → 400 (上限与逗号形式一致, 区间跨度本身不设限)
    t = datetime(2026, 9, 10, 0, 32)
    for drive_id in range(13, 112):       # 已有 11,12 → 共 101 段
        seed_drive(db, id=drive_id, start_date=t + timedelta(hours=drive_id),
                   end_date=t + timedelta(hours=drive_id, minutes=5))
    assert auth.get("/tesla/trips/api/merged?ids=11-111").status_code == 400
    # 恰 100 段 (空轨迹段只进 ids 不进 pts) → 放行, 边界不差一
    r = auth.get("/tesla/trips/api/merged?ids=11-110")
    assert r.status_code == 200
    assert r.json()["n"] == 100


# ---------------------------------------------------------------- 流式下载 (边下边播)
def test_merged_stream_ndjson_summary_then_segments(auth, db):
    """NDJSON 流: 首行汇总 (含 segs=有数据的段数), 之后每行一段; 拼起来与整包一致。"""
    _seed_pair(db)
    r = auth.get("/tesla/trips/api/merged_stream?ids=11-12")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/x-ndjson")
    lines = [json.loads(x) for x in r.text.splitlines() if x.strip()]
    assert lines[0]["summary"]["ids"] == [11, 12]
    assert lines[0]["summary"]["n"] == 2
    assert lines[0]["segs"] == 2
    segs = lines[1:]
    assert len(segs) == 2
    assert all(len(s["pts"]) == 2 for s in segs)
    # 流式拼接 == 整包接口 (前端两种消费方式数据同源)
    full = auth.get("/tesla/trips/api/merged?ids=11-12").json()
    assert [p for s in segs for p in s["pts"]] == full["pts"]
    assert [t for s in segs for t in s["ts"]] == full["ts"]


def test_merged_stream_404_before_first_line(auth, db):
    """行程不存在/未结束 → 流开始前就 404 (JSON, 不是断在半路的流)。
    区间形式会跳过不存在的 id, 这里用逗号形式触发 404。"""
    _seed_pair(db)
    r = auth.get("/tesla/trips/api/merged_stream?ids=11,99")
    assert r.status_code == 404
    assert "不存在或未完成" in r.json()["detail"]


def test_merged_budget_proportional_to_segment_size(auth, db):
    """预算按各段原始点数占比分配: 长段多分 (真实下采样), 短段 200 保底全留。"""
    seed_addresses(db)
    t = datetime(2026, 9, 10, 0, 32)
    raw = {11: 30000, 12: 3000, 13: 50}
    for drive_id, cnt in raw.items():
        seed_drive(db, id=drive_id, start_date=t + timedelta(hours=drive_id * 5),
                   end_date=t + timedelta(hours=drive_id * 5, minutes=30))
        db.add_all(Position(drive_id=drive_id,
                            date=t + timedelta(hours=drive_id * 5, seconds=i),
                            longitude=114.0 + i * 1e-6, latitude=22.5,
                            speed=50.0, power=None)
                   for i in range(cnt))
    db.commit()
    r = auth.get("/tesla/trips/api/merged_stream?ids=11-13")
    assert r.status_code == 200
    seg_sizes = [len(json.loads(x)["pts"])
                 for x in r.text.splitlines()[1:] if x.strip()]
    # 长段 30000 原始点 → 预算 10909 → stride 2 → ~15001 (不再是平均主义的 200)
    assert 10900 < seg_sizes[0] <= 15002
    # 中段 3000 → 预算 1091 → stride 2 → ~1501
    assert 1090 < seg_sizes[1] <= 1502
    # 短段 50 → 200 保底 → 全留
    assert seg_sizes[2] == 50


# ---------------------------------------------------------------- 断档补路 (自有库)
def _seed_gap_drive(db, drive_id=7):
    """一段有 ~2km 断档的行程: 前后各 2 个密集采样点, 中间跳变。"""
    seed_addresses(db)
    seed_drive(db, id=drive_id)
    t0 = datetime(2026, 9, 10, 0, 32)
    seed_position(db, drive_id, id=None, date=t0,
                  longitude=114.000, latitude=22.50, speed=30.0, power=45000.0)
    seed_position(db, drive_id, id=None, date=t0 + timedelta(seconds=10),
                  longitude=114.001, latitude=22.50, speed=30.0, power=45000.0)
    # 2km 断档 (隧道): 10s → 80s
    seed_position(db, drive_id, id=None, date=t0 + timedelta(seconds=80),
                  longitude=114.021, latitude=22.50, speed=60.0, power=45000.0)
    seed_position(db, drive_id, id=None, date=t0 + timedelta(seconds=90),
                  longitude=114.022, latitude=22.50, speed=60.0, power=45000.0)
    return t0


FILL_BODY = {
    "drive_id": 7,
    "a": [114.001, 22.50], "b": [114.021, 22.50],
    "path": [[114.001, 22.50], [114.011, 22.50], [114.021, 22.50]],
}


def test_gap_fill_post_then_track_spliced(auth, db, owndb):
    """回传补路 → 存自有库 (TeslaMate 库零写入) → 轨迹接口服务端拼好。"""
    _seed_gap_drive(db)
    r = auth.post("/tesla/trips/api/gap_fill", json=FILL_BODY)
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True and 2.0 < d["km"] < 2.1    # 服务端实算里程 (加密不改长度)
    # 自有库一行; 原库 positions 还是 4 个 (只读不动)
    fills = owndb.query(TrackFill).all()
    assert len(fills) == 1
    assert fills[0].drive_id == 7 and fills[0].source == "amap"
    assert db.query(Position).count() == 4
    # 存库路径已按 80m 加密: 2km 断档 3 顶点 → 每条边 12 个插值点 = 27 点
    assert len(json.loads(fills[0].path)) == 27
    # 轨迹接口: 断档被插值点铺满 (时间按弧长, 速度两端插值, power 不造假)
    track = auth.get("/tesla/trips/api/7/track").json()
    assert track["pts"][0][:2] == [114.0, 22.5]
    assert track["pts"][-1][:2] == [114.022, 22.5]
    assert track["ts"] == sorted(track["ts"])        # 时间单调
    assert track["ts"][0] == 0 and track["ts"][-1] == 90
    assert [114.011, 22.5, 45.0, None] in track["pts"]   # 弧长中点: 速度 30→60 插值
    # 相邻点距恒 < 160m (断档识别最低阈值) —— 不再被前端二次识别成断档
    gaps = [abs(b[0] - a[0]) * 102.87 for a, b in zip(track["pts"], track["pts"][1:])]
    assert max(gaps) < 0.16


def test_gap_fill_rejects_far_or_misordered_anchors(auth, db):
    """端点离轨迹超 150m / 顺序颠倒 / 不存在的行程 → 4xx, 不落库。"""
    _seed_gap_drive(db)
    far = dict(FILL_BODY, a=[116.0, 24.0])
    assert auth.post("/tesla/trips/api/gap_fill", json=far).status_code == 400
    reversed_ = dict(FILL_BODY, a=FILL_BODY["b"], b=FILL_BODY["a"])
    assert auth.post("/tesla/trips/api/gap_fill", json=reversed_).status_code == 400
    assert auth.post("/tesla/trips/api/gap_fill",
                     json=dict(FILL_BODY, drive_id=99)).status_code == 404
    short = dict(FILL_BODY, path=[[114.001, 22.5]])
    assert auth.post("/tesla/trips/api/gap_fill", json=short).status_code == 400


def test_gap_fill_overwrites_same_gap(auth, db, owndb):
    """同一断档重复回传 = 覆盖 (按锚点唯一), 轨迹用最新路径。"""
    _seed_gap_drive(db)
    auth.post("/tesla/trips/api/gap_fill", json=FILL_BODY)
    better = dict(FILL_BODY, path=[[114.001, 22.50], [114.006, 22.50],
                                   [114.016, 22.50], [114.021, 22.50]])
    r = auth.post("/tesla/trips/api/gap_fill", json=better)
    assert r.status_code == 200
    assert len(owndb.query(TrackFill).all()) == 1     # 覆盖不是追加
    track = auth.get("/tesla/trips/api/7/track").json()
    # 4 原始 + 新路径的插值点 (4 顶点 / 3 边, 各边 80m 加密共 24 点, 去掉
    # 与锚点重合的首尾 = 26): 新顶点 114.006 在弧长 1/4 处, 速度 30→60 插值 37.5
    assert [114.006, 22.5, 37.5, None] in track["pts"]
    assert len(track["pts"]) == 30


def test_gap_fill_anchors_with_inbetween_points_keep_ts_monotonic(auth, db):
    """锚点区间内夹着原始点 (客户端按下采样视图挑锚点) → 按日期归并, ts 单调。

    实锤场景: 合并轨迹按段下采样, 客户端在它收到的序列里看到断档, 回传的
    锚点在原始流里中间还夹着未被抽掉的点 —— 旧实现把补路点整块插到锚点后,
    中间的原始点日期回退, 合并轨迹 ts 出现 12 秒乱序 (播放节拍错乱)。"""
    seed_addresses(db)
    seed_drive(db, id=8)
    t0 = datetime(2026, 9, 10, 0, 32)
    rows = [(0, 114.000, 22.50, 30.0),
            (10, 114.001, 22.50, 30.0),    # ← 锚点 a
            (11, 114.0015, 22.50, 30.0),   # 区间内原始点 (客户端视图抽掉的)
            (79, 114.0205, 22.50, 60.0),   # 区间内原始点
            (80, 114.021, 22.50, 60.0),    # ← 锚点 b
            (90, 114.022, 22.50, 60.0)]
    for sec, lng, lat, spd in rows:
        seed_position(db, 8, id=None, date=t0 + timedelta(seconds=sec),
                      longitude=lng, latitude=lat, speed=spd, power=45000.0)
    r = auth.post("/tesla/trips/api/gap_fill", json=dict(FILL_BODY, drive_id=8))
    assert r.status_code == 200 and r.json()["ok"] is True
    track = auth.get("/tesla/trips/api/8/track").json()
    assert track["ts"] == sorted(track["ts"])    # 修复前: 补路点块后 ts 回退
    assert track["ts"][0] == 0 and track["ts"][-1] == 90
    assert track["pts"][0][:2] == [114.0, 22.5]
    assert track["pts"][-1][:2] == [114.022, 22.5]
    assert len(track["pts"]) == 6 + 25           # 原始 6 + 补路 25 (27 加密点
    # 去掉与锚点重合的首尾), 区间内两个原始点一个不丢 —— 归并后按日期穿插
    assert [114.0015, 22.5, 30.0, 45000.0] in track["pts"]
    assert [114.0205, 22.5, 60.0, 45000.0] in track["pts"]


def test_gap_fill_points_survive_downsampling(auth, db):
    """大行程 (原始点 3 倍于预算, stride=3) 的补路点全保留不被抽掉。

    补路点相距 ~78m, 若被 stride 抽掉 2/3, 间距飙到 ~235m —— 超过断档
    识别阈值 160m, 会被前端再次当断档无限重规划 (1385 号行程的实发问题)。"""
    seed_addresses(db)
    seed_drive(db, id=9)
    t0 = datetime(2026, 9, 10, 0, 32)
    rows = [Position(drive_id=9, date=t0 + timedelta(seconds=i),
                     longitude=round(114.0 + i * 0.000002
                                     + (0.033 if i >= 5000 else 0), 6),
                     latitude=22.5, speed=30.0, power=45000.0)
            for i in range(15001)]
    db.add_all(rows)
    db.commit()                                       # i=4999 → 114.009998, i=5000 → 114.043
    r = auth.post("/tesla/trips/api/gap_fill", json={
        "drive_id": 9,
        "a": [114.009998, 22.5], "b": [114.043, 22.5],
        "path": [[114.009998, 22.5], [114.0265, 22.5], [114.043, 22.5]]})
    assert r.status_code == 200 and 3.3 < r.json()["km"] < 3.4
    track = auth.get("/tesla/trips/api/9/track").json()
    # 断档区 (114.01~114.043 之间没有原始点) 的补路点一个不少:
    # 2 边各 21 个插值点 + 中间顶点, 去掉与锚点重合的首尾 = 43
    gap_pts = [p for p in track["pts"] if 114.01 < p[0] < 114.043]
    assert len(gap_pts) == 43
    gaps = [abs(b[0] - a[0]) * 102.87 for a, b in zip(track["pts"], track["pts"][1:])]
    assert max(gaps) < 0.16                           # 全程无一处超断档阈值


def test_gap_fill_spliced_into_merged_stream_too(auth, db):
    """合并/流式接口同样吃到补路点 (所有轨迹消费方一个口径)。"""
    _seed_gap_drive(db, 7)
    t = datetime(2026, 9, 10, 3, 0)
    seed_drive(db, id=8, start_date=t, end_date=t + timedelta(minutes=10))
    seed_position(db, 8, id=None, date=t, longitude=115.0, latitude=23.0,
                  speed=20.0, power=None)
    seed_position(db, 8, id=None, date=t + timedelta(minutes=10),
                  longitude=115.1, latitude=23.0, speed=20.0, power=None)
    auth.post("/tesla/trips/api/gap_fill", json=FILL_BODY)
    r = auth.get("/tesla/trips/api/merged_stream?ids=7-8")
    lines = [json.loads(x) for x in r.text.splitlines() if x.strip()]
    segs = lines[1:]
    assert len(segs[0]["pts"]) == 29                  # 4 原始 + 25 加密插值
    assert segs[0]["ts"][0] == 0 and segs[0]["ts"][-1] == 90
    assert [114.011, 22.5, 45.0, None] in segs[0]["pts"]
    assert len(segs[1]["pts"]) == 2


def test_trips_page_streams_speed_zoom_and_gap_fill_post(auth):
    """页面片段: 流式边下边播 / 随速变焦 / 断档回传一应俱全。"""
    html = auth.get("/tesla/trips").text
    for frag in ["function loadMergedStream(", "sess.append(d.pts, d.ts)",
                 "sess.more = false", "正在下载轨迹", "等待后续轨迹",
                 "const speedZoom =", "followZoomOn", "zoomEaseStart(zoom)",
                 "tripMap.setZoom(zoomShown, true)",
                 'addEventListener("wheel", zoomTakeover,',

                 "postGapFill(it, g, route)", "gcj02ToWgs84"]:
        assert frag in html, f"行程页缺少片段 {frag}"


# ---------------------------------------------------------------- 页面
def test_trips_page_time_menu_and_filter_row(auth):
    """顶栏时间下拉 (快捷档 + 自定义日历) + 筛选行 (起终点省市区级联, 里程档),
    全部编码进 URL, 且与 ?id=/ ?ids= 深链共存。"""
    html = auth.get("/tesla/trips").text
    for frag in ['id="time-menu"', 'data-v="24h"', 'data-v="7d"', 'data-v="30d"',
                 'data-v="180d"', 'data-v="1y"', 'data-v="all"',
                 'data-v="custom"', 'id="tm-cal"', 'id="tm-prev"', 'id="tm-next"',
                 'id="tm-ym"', 'id="tm-sel"', 'id="tm-apply"', 'function calRender()',
                 '再点结束日期', 'id="fc-menu"', 'id="tc-menu"', 'id="km-menu"',
                 'data-k="0-20"', 'data-k="20-100"', 'data-k="100-300"',
                 'data-k="300+"', "/tesla/trips/api/regions",
                 "function filterQS()", "function listURL(", "function syncURL()",
                 "function bindLocMenu(", 'class="menu loc-menu"',
                 'p.set("from_loc", state.fromLoc)', 'p.set("km_min", kb.min)',
                 # 手机: 下拉面板锚全宽 header (日历行 ~300px, 挂胶囊右缘必出屏)
                 '@media (max-width: 479px)', '.nav-menu { position: static; }']:
        assert frag in html, f"行程页缺少 {frag}"
    assert "chips-range" not in html and "/tesla/trips/api/cities" not in html
    assert 'id="tm-from"' not in html
    for i in ('time-menu', 'time-lb', 'time-opts', 'tm-dates', 'tm-cal', 'tm-prev',
              'tm-next', 'tm-ym', 'tm-sel', 'brand-menu', 'logout',
              'fc-opts', 'tc-opts', 'km-opts'):
        assert html.count(f'id="{i}"') == 1, f"页面 {i} 重复"


def test_trips_page_has_playbar_and_single_column(auth):
    """播放控制条 + 单列列表 都在页面上; 信息层不占地图高度。"""
    html = auth.get("/tesla/trips").text
    for frag in ['id="playbar"', 'id="pb-toggle"', 'id="pb-seek"', 'id="pb-speed"',
                 'id="sh-cell-pw"', 'id="sh-pw-lb"', "ICON_REPLAY",
                 # 让位地图: 播放条是浮在地图上的玻璃胶囊 (不占一整行),
                 # 统计格单行横滑 (不折 2×3 网格), 弹层整体加高
                 "position: absolute; left: 14px; right: 14px;",
                 "backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px);",
                 "overflow-x: auto; scrollbar-width: none;",
                 "height: 82vh; height: 82dvh;",
                 "flex: none; background: var(--surface); border-radius: 12px; padding: 8px 12px;",
                 # 视角基线: 播放条上加减按钮, 随速变焦整条平移
                 'id="pb-zout"', 'id="pb-zin"', 'id="pb-zval"',
                 "bumpZoomBias", "trip-zoom-bias",
                 # 开场视角直接到位 (不缓动), 档位取整避开 AMap 小数吸附
                 "zoom = Math.round(zoom);", "tripMap.setZoom(zoom, true)",
                 'id="list"', "最高车速"]:
        assert frag in html, f"行程页缺少 {frag}"
    assert "spd-legend" not in html   # 速度图例已按需求移除
    # 刷新: 顶栏按钮 (下拉手势已按需求撤掉)
    for frag in ['id="refresh-btn"', "function refreshList(",
                 "refresh-spin", 'body.selecting #refresh-btn']:
        assert frag in html, f"行程页缺少刷新片段 {frag}"
    assert 'id="ptr"' not in html and "setupPullRefresh" not in html
    # 瀑布流的列容器已删
    assert "m-col" not in html


def test_trips_page_consumption_and_driver_filter(auth):
    """卡片与弹层显示总电耗/平均电耗; 筛选行有驾驶员菜单且请求带司机参数。"""
    html = auth.get("/tesla/trips").text
    for frag in [
        'id="sh-cell-kwh"', 'id="sh-cell-avg"',       # 弹层: 总电耗/平均电耗格
        'class="ct-cells"',                            # 卡片统计瓷砖 (量): 里程/时长/总电耗
        "总电耗", "平均电耗 ${num(it.wh_per_km, 0)}",     # 率 (均速/平均电耗) 收进子行
        'id="drv-menu"', 'id="drv-opts"', 'id="drv-lb"',   # 司机筛选菜单
        'p.set("driver_id", state.drvId)',            # 列表请求/地址栏都带司机
        "function fillSheetHeader(",                  # 弹层填充电耗格
    ]:
        assert frag in html, f"行程页缺少 {frag}"
    # 电耗格初始隐藏, 有数据才亮 (充电换算系数缺失时整块不出)
    assert 'id="sh-cell-kwh" hidden' in html
    # 司机菜单没配司机时整颗藏掉
    assert 'id="drv-menu" hidden' in html


def test_trips_page_playback_pacing_and_nowrap(auth):
    """超长轨迹不再 12 秒放完: 时长含里程分量 + 0.5× 慢速档; 统计值不折行。"""
    html = auth.get("/tesla/trips").text
    for frag in ["Math.min(Math.max(N / 300, 3 + cum[N - 1] * 1.4), 300)",
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
                 '/[-,]/.test(key) ? "ids=" : "id="',
                 # 单条行程头部立即填 (字段随卡片/接口齐), 占位只留给合并流式
                 "if (it.pts || !it.merged) fillSheetHeader(it)",
                 # 坏合并深链: 关弹层 + 抹参回列表 (单条卡片打开的错留在弹层里)
                 "hideSheet(); throw e"]:
        assert frag in html, f"行程页缺少深链片段 {frag}"


def test_trips_page_preloads_tiles(auth):
    """播放前预载沿途瓦片: 倍率按里程 + DOM 抄模板 + Image() 刷缓存, 失败静默。"""
    html = auth.get("/tesla/trips").text
    for frag in ["function followZoom(", "async function tileTemplate(", "function tileUrl(",
                 "function preloadTiles(", "正在预载地图", "TrackUtil.lngLatToTile",
                 "appmaptile", "playTrack(c.pts, c.ts || [], it, zoom)",
                 "setTimeout(resolve, 8000)", "trackutil.js?v=8"]:
        assert frag in html, f"行程页缺少瓦片预载片段 {frag}"


def test_trips_page_style_block_balanced(auth):
    """样式块花括号必须配平: 少一个 } 会让 CSS 错误恢复把其后全部规则
    吞进未闭合的规则 (ct-drv 接缝曾丢 }, 弹层/底栏/选中态全体裸奔,
    且控制台无任何报错, 只有页面悄悄变丑)。"""
    html = auth.get("/tesla/trips").text
    style = re.search(r"<style>(.*?)</style>", html, re.S).group(1)
    assert style.count("{") == style.count("}"), "样式块花括号不配平, 后半规则全被吞"


def test_trips_page_has_multiselect(auth):
    """多选连续行程: 长按卡片进选择模式 + 底栏 (全选/上限提示) + 合并接口直开。"""
    html = auth.get("/tesla/trips").text
    for frag in ['id="selbar"', 'id="sel-go"', 'id="sel-cancel"',
                 'id="sel-count"', 'id="sel-all"', 'id="sel-cap"', "MERGE_MAX = 100",
                 "body.selecting", "pickCard", "enterSelect", "exitSelect",
                 "openMerged", "/tesla/trips/api/merged_stream?ids=",
                 "mergedCache", "loadMergedStream(", "sess.append(d.pts, d.ts)",
                 "setupLongPress", "HOLD_MS = 480",
                 'addEventListener("contextmenu"']:
        assert frag in html, f"行程页缺少多选片段 {frag}"
    # 多选按钮已撤: 长按卡片是唯一入口 (触屏长按/桌面按住)
    assert 'id="merge-btn"' not in html
    # 合并弹层复用播放: pts 随 it 一起传入 (不走单条轨迹接口)
    assert "it.pts ? it : trackCache.get(it.id)" in html
    # 合并轨迹按段做断档识别 (各段采样密度不同), 单段照旧全局一套
    assert "function splitSegments(" in html
    assert "splitSegments(pts, it.seg_starts)" in html
    assert "TrackUtil.splitGaps(pts)" in html


# ---------------------------------------------------------------- 轨迹分组

def test_trip_group_save_list_rename_delete(auth, db):
    """存分组: ids 排序去重落库; 列表段数/里程/日期跨度按当前数据现算;
    改名只动名字; 删除只删自有库记录 (行程原数据不动)。"""
    t = datetime(2026, 5, 1, 0, 32)
    seed_drive(db, id=11, start_date=t, end_date=t + timedelta(hours=1),
               distance=42.5)
    seed_drive(db, id=12, start_date=t + timedelta(days=2),
               end_date=t + timedelta(days=2, hours=1), distance=10.04)
    seed_drive(db, id=13, start_date=t + timedelta(days=2, hours=3),
               end_date=t + timedelta(days=2, hours=4), distance=8.0)

    r = auth.post("/tesla/trips/api/groups",
                  json={"name": "五一小长途", "ids": [13, 11, 12, 11]})  # 乱序 + 重复
    assert r.status_code == 200
    g = r.json()
    assert g["ids"] == [11, 12, 13]           # 升序去重
    assert g["n"] == 3 and g["km"] == 60.5
    assert g["span"] == "2026-05-01~2026-05-03"   # 最早~最晚出发日

    r = auth.get("/tesla/trips/api/groups")
    assert [x["name"] for x in r.json()] == ["五一小长途"]

    assert auth.patch(f"/tesla/trips/api/groups/{g['id']}",
                      json={"name": "改名了"}).json()["name"] == "改名了"
    # 行程原数据没被动过
    assert db.get(Drive, 11).distance == 42.5

    assert auth.delete(f"/tesla/trips/api/groups/{g['id']}").json() == {"ok": True}
    assert auth.get("/tesla/trips/api/groups").json() == []
    assert auth.delete(f"/tesla/trips/api/groups/{g['id']}").status_code == 404


def test_trip_group_span_single_date_and_km_rounding(auth, db):
    """同一天的分组 span 就是那一天; 里程按现算求和。"""
    t = datetime(2026, 5, 1, 8, 0)
    seed_drive(db, id=21, start_date=t, end_date=t + timedelta(hours=1),
               distance=1.11)
    seed_drive(db, id=22, start_date=t + timedelta(hours=2),
               end_date=t + timedelta(hours=3), distance=2.22)
    r = auth.post("/tesla/trips/api/groups", json={"name": "同城", "ids": [21, 22]})
    assert r.json()["span"] == "2026-05-01"
    assert r.json()["km"] == 3.3


def test_trip_group_validation(auth, db):
    """校验: 无效行程 (不存在/未结束) 404; 名字/段数越界 422;
    去重后不足 2 段 / 名字 strip 后为空 400。"""
    t = datetime(2026, 5, 1, 0, 32)
    seed_drive(db, id=31, start_date=t, end_date=t + timedelta(hours=1))
    seed_drive(db, id=32, start_date=t, end_date=None)          # 未结束行程
    post = "/tesla/trips/api/groups"

    assert auth.post(post, json={"name": "x", "ids": [31, 99]}).status_code == 404
    assert auth.post(post, json={"name": "x", "ids": [31, 32]}).status_code == 404
    assert auth.post(post, json={"name": "x", "ids": [31, 31]}).status_code == 400
    assert auth.post(post, json={"name": "   ", "ids": [31, 32]}).status_code == 400
    assert auth.post(post, json={"name": "x" * 31, "ids": [31, 99]}).status_code == 422
    assert auth.post(post, json={"name": "x", "ids": [31]}).status_code == 422

    # 改名: 未知分组 404
    assert auth.patch("/tesla/trips/api/groups/999",
                      json={"name": "y"}).status_code == 404


def test_trips_page_has_toll_tools(auth):
    """高速费: 头部批量入口 + 面板 + 弹层 chip + 估价函数都挂在页面上。"""
    html = auth.get("/tesla/trips").text
    for frag in ['id="toll-btn"', 'id="tollpanel"', 'id="toll-go"', 'id="toll-stop"',
                 'id="toll-fill"', 'id="toll-stat"', 'id="sh-toll"',
                 "function calcTripToll(", "function autoCalcToll(",
                 "TOLL_WAYPOINTS", "/toll`", "无高速费"]:
        assert frag in html, f"行程页缺少高速费片段 {frag}"
    # 限速 + 连败自动停 (个人配额保护)
    assert "await sleep(420)" in html
    assert "streak >= 8" in html


def test_trips_page_has_driver_picker(auth):
    """行程页司机标注: 弹层选择行 + 卡片 pill + 标注接口都挂在页面上。"""
    html = auth.get("/tesla/trips").text
    for frag in ['id="sh-drv"', 'id="sh-drv-sel"', "setupDriverPicker",
                 'class="ct-drv${it.driver_id != null ? "" : " def"}"',
                 ".ct-drv.def", "/tesla/api/drivers",
                 "function postJSON(", "已标注为", "已清除标注"]:
        assert frag in html, f"行程页缺少司机标注片段 {frag}"
    # 卡片 pill 默认司机兜底也显示 (弱化 .def 与显式标注区分)
    # 没配司机时选择器藏 (兜底, 不会闪一个空下拉); 选择器和高速费 chip 都藏才整行藏
    assert "driversCache.length > 0) {" in html
    assert "function metaRowSync()" in html


def test_trips_page_has_group_panel(auth):
    """轨迹分组: 头部入口 + 全屏面板 + 存分组命名模式 + 轻提示都挂在页面上。"""
    html = auth.get("/tesla/trips").text
    for frag in ['id="groups-btn"', 'id="gpanel"', '轨迹分组', 'id="gp-list"',
                 'id="gp-btn"', "存为分组", 'id="gp-name"', 'id="gp-save"',
                 'id="gp-close"', "api/groups", "function toast(", 'id="toast"',
                 "openMerged(item.dataset.ids)"]:
        assert frag in html, f"行程页缺少分组片段 {frag}"
    # 面板条目渲染 + 改名/删除两段式委托 (isConnected 防脱链)
    assert "function gpRowHTML(" in html
    assert 'gp-list").addEventListener("click"' in html
    assert "!t.isConnected" in html
    # 存分组按钮与查看连续轨迹同一上限联动
    assert '$("#gp-btn").disabled = n < 2 || n > MERGE_MAX' in html
