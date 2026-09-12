"""设置页 API: TeslaMate 连接/高德 Key 存自有库 + 驾驶员管理。

引擎重建在测试里 monkeypatch 成记录器 (真重建会把注入的测试引擎换掉);
验证查询走当前工厂 —— 注入引擎是 SQLite, SELECT 1 必通。
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import database


@pytest.fixture()
def rebuild_recorder(monkeypatch):
    """记录 rebuild_engine 调用但不真换引擎 (保住测试注入的 SQLite)。"""
    calls: list[str] = []
    monkeypatch.setattr(database, "rebuild_engine", calls.append)
    return calls


def test_settings_get_defaults_from_env(auth, monkeypatch):
    """未保存过: 现值回落 env; 秘密不回显 (Key 打码, 密码只报在用)。"""
    monkeypatch.setenv("TMDB_HOST", "10.0.0.8")
    monkeypatch.setenv("TMDB_USER", "tmuser")
    monkeypatch.setenv("AMAP_KEY", "test-amap-key-123456")
    d = auth.get("/tesla/api/settings").json()
    assert d["tmdb"] == {"host": "10.0.0.8", "port": "5432", "user": "tmuser",
                         "name": "teslamate", "password_set": False}
    assert d["amap"]["key_masked"] == "test****3456"
    assert d["amap"]["security_code_set"] is False


def test_settings_save_amap_and_map_config_reflects(auth, monkeypatch):
    """高德 Key 存自有库, map config 端点即时反映 (改完即生效, 无需重启)。"""
    monkeypatch.delenv("AMAP_KEY", raising=False)
    monkeypatch.delenv("AMAP_SECURITY_CODE", raising=False)
    r = auth.post("/tesla/api/settings",
                  json={"amap_key": "abcd1234efgh5678", "amap_security_code": "9182ac3b"})
    assert r.status_code == 200
    assert r.json()["amap"]["key_masked"] == "abcd****5678"
    assert auth.get("/tesla/map/api/config").json() == {
        "amap_key": "abcd1234efgh5678", "security_code": "9182ac3b"}
    # 留空 = 保持现值
    auth.post("/tesla/api/settings", json={"amap_key": "", "amap_security_code": ""})
    assert auth.get("/tesla/map/api/config").json()["amap_key"] == "abcd1234efgh5678"


def test_settings_save_tmdb_rebuilds_only_on_change(  # pylint: disable=redefined-outer-name
        auth, rebuild_recorder, monkeypatch):
    """TeslaMate 连接: 保存落库; URL 变了才换引擎, 原值重存不换 (幂等)。"""
    monkeypatch.setenv("TMDB_HOST", "10.0.0.1")   # 固定 host, 别走 docker 定位
    body = {"tmdb_host": "10.0.0.1", "tmdb_user": "u", "tmdb_password": "p",
            "tmdb_port": "5433", "tmdb_name": "n"}
    d = auth.post("/tesla/api/settings", json=body).json()["tmdb"]
    assert (d["host"], d["port"], d["user"], d["name"], d["password_set"]) == \
        ("10.0.0.1", "5433", "u", "n", True)
    assert rebuild_recorder == ["postgresql+psycopg://u:p@10.0.0.1:5433/n"]
    # 原值再存: URL 没变, 不换引擎
    auth.post("/tesla/api/settings", json=body)
    assert len(rebuild_recorder) == 1


def test_settings_tmdb_rollback_when_verify_fails(  # pylint: disable=redefined-outer-name
        auth, rebuild_recorder, monkeypatch):
    """新连接实测失败: 设置行回滚 + 引擎换回旧 URL + 400 (服务不断)。"""
    monkeypatch.setenv("TMDB_HOST", "10.0.0.1")
    auth.post("/tesla/api/settings",
              json={"tmdb_host": "10.0.0.1", "tmdb_user": "u", "tmdb_password": "p"})
    rebuild_recorder.clear()
    # 验证查询指向连不上的库 (目录不存在, SQLite 直接 OperationalError)
    bad = sessionmaker(create_engine("sqlite:////nonexistent-dir/x.db"))
    monkeypatch.setattr(database, "session_factory", lambda: bad)

    r = auth.post("/tesla/api/settings", json={"tmdb_host": "10.0.0.2"})
    assert r.status_code == 400 and "连不上" in r.json()["detail"]
    assert rebuild_recorder == [
        "postgresql+psycopg://u:p@10.0.0.2:5432/teslamate",   # 先换新
        "postgresql+psycopg://u:p@10.0.0.1:5432/teslamate"]    # 失败换回
    d = auth.get("/tesla/api/settings").json()["tmdb"]
    assert d["host"] == "10.0.0.1"   # 设置行已回滚


def test_drivers_crud_and_single_default(auth):
    """驾驶员: 添加/列表/改名/删除; 设默认互斥 (全库至多一个)。"""
    d1 = auth.post("/tesla/api/drivers", json={"name": "爸爸"}).json()
    d2 = auth.post("/tesla/api/drivers", json={"name": " 妈妈 "}).json()
    assert d2["name"] == "妈妈"                       # 名字 strip
    assert [x["name"] for x in auth.get("/tesla/api/drivers").json()] == ["爸爸", "妈妈"]

    assert auth.patch(f"/tesla/api/drivers/{d2['id']}",
                      json={"is_default": True}).json()["is_default"] is True
    flags = [x["is_default"] for x in auth.get("/tesla/api/drivers").json()]
    assert flags == [False, True]                     # 设新的清掉旧的

    assert auth.patch(f"/tesla/api/drivers/{d1['id']}",
                      json={"name": "老王"}).json()["name"] == "老王"
    assert auth.patch("/tesla/api/drivers/99",
                      json={"name": "x"}).status_code == 404

    assert auth.delete(f"/tesla/api/drivers/{d2['id']}").json() == {"ok": True}
    assert auth.get("/tesla/api/drivers").json() == [
        {"id": d1["id"], "name": "老王", "is_default": False}]
    assert auth.delete(f"/tesla/api/drivers/{d2['id']}").status_code == 404

    assert auth.post("/tesla/api/drivers", json={"name": "  "}).status_code == 400
    assert auth.post("/tesla/api/drivers", json={"name": "x" * 31}).status_code == 422


def test_settings_page_and_nav_entries(auth):
    """设置页挂全 (表单/驾驶员/轻提示); 三个页面品牌菜单都有设置入口。"""
    html = auth.get("/tesla/settings").text
    for frag in ['id="tm-host"', 'id="tm-save"', "保存并连接", 'id="amap-key"',
                 'id="drv-list"', "/tesla/api/settings", "/tesla/api/drivers",
                 'id="toast"', "设为默认", "留空 = 保持现值"]:
        assert frag in html, f"设置页缺少片段 {frag}"
    for page in ("/tesla/charging", "/tesla/map", "/tesla/trips"):
        assert '<a href="/tesla/settings">设置</a>' in auth.get(page).text, page
