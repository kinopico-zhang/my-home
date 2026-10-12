"""首启引导 (/setup) 的接口与页面门: 三步配齐之前是唯一入口, 不允许跳过。

isolate autouse 种了管理员 + 高德 Key (已初始化口径), 这里用 firstboot 把
账号库清空、no_amap/no_teslamate 把配置撤掉, 拼出各缺口口径 (空库 + 无
env 的死路正是引导页要救的场景)。组合仓是三步版页面 (管理员 → 数据源 →
地图), 数据源/地图的保存走既有 /tesla/api/settings (tesla 仓已深测),
这里测引导层的接线、缺口清单与应用门 (/tesla 的 302 —— 缺口判定走
mytesla 前缀的 setup_gate, 组合仓自己的变体)。"""
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

import app.main as m
from app import account_store
from app.models import User

tesla_database = sys.modules["mytesla.app.database"]
tesla_models = sys.modules["mytesla.app.tesla.models"]

STATIC_DIR = Path(__file__).resolve().parent.parent / "app" / "home" / "static"


@pytest.fixture()
def firstboot(usersdb):
    """首启口径: 撤掉 isolate 种的管理员, 账号库回到空。"""
    usersdb.execute(delete(User))
    usersdb.commit()


@pytest.fixture()
def no_amap():
    """撤掉 conftest 种的高德两把 Key, 回到「地图步没配」口径。"""
    with tesla_database.own_session_factory()() as own:  # pylint: disable=not-callable
        row = own.get(tesla_models.AppSetting, 1)
        row.amap_key = ""
        row.amap_web_key = ""
        own.commit()


@pytest.fixture()
def no_teslamate(monkeypatch):
    """撤掉 TeslaMate 连接 (env 与 docker 定位都掐掉): 「数据源步没配」。

    docker 候选一并 patch 掉 —— 有真 docker 的机器上 inspect 一个不存在的
    容器虽然必败, 但那要起子进程, 测试里没必要。"""
    with tesla_database.own_session_factory()() as own:  # pylint: disable=not-callable
        row = own.get(tesla_models.AppSetting, 1)
        row.tmdb_host = ""
        own.commit()
    monkeypatch.delenv("TMDB_HOST")

    def _no_docker() -> str:
        raise RuntimeError("测试口径: 无 docker")

    monkeypatch.setattr(tesla_database, "resolve_db_host", _no_docker)


def test_setup_status_needed_on_firstboot(  # pylint: disable=redefined-outer-name
        firstboot, client):
    """首启: needed=true, 缺口只有账号一步 (数据源/地图 isolate 已配)。"""
    r = client.get("/api/setup-status")
    assert r.status_code == 200
    assert r.json() == {"needed": True, "missing": ["account"]}


def test_setup_status_false_when_initialized(client):
    """已初始化的部署 (isolate 的种子管理员 + 配置即此口径): 全配齐。"""
    assert client.get("/api/setup-status").json() == {"needed": False, "missing": []}


def test_setup_status_lists_config_gaps(  # pylint: disable=redefined-outer-name
        auth, no_amap, no_teslamate):
    """缺口清单 (组合仓变体走 mytesla 前缀): 数据源与地图都没配 → 两步
    都在; 配一步少一步。"""
    d = auth.get("/api/setup-status").json()
    assert d == {"needed": True, "missing": ["teslamate", "amap"]}
    with tesla_database.own_session_factory()() as own:  # pylint: disable=not-callable
        own.get(tesla_models.AppSetting, 1).tmdb_host = "10.0.0.9"
        own.commit()
    d = auth.get("/api/setup-status").json()
    assert d == {"needed": True, "missing": ["amap"]}
    r = auth.post("/tesla/api/settings",
                  json={"amap_key": "abcd1234efgh5678",
                        "amap_web_key": "wxyz9876abcd5432"})
    assert r.status_code == 200
    assert auth.get("/api/setup-status").json() == {"needed": False, "missing": []}


def test_setup_admin_creates_and_logs_in(  # pylint: disable=redefined-outer-name
        firstboot, client, usersdb):
    """建管理员: is_admin 落库, 注册即登录 (cookie 直接过 /api/me)。"""
    r = client.post("/api/setup-admin",
                    json={"name": "owner", "password": "first-boot-pass"})
    assert r.status_code == 200, r.text
    user = account_store.find_by_name(usersdb, "owner")
    assert user is not None and user.is_admin
    me = client.get("/api/me")
    assert me.status_code == 200
    assert me.json() == {"name": "owner", "is_admin": True}


def test_setup_admin_rejected_when_initialized(client, usersdb):
    """已有管理员: 409 不新建 —— 公开端点只在首启窗口开口。"""
    r = client.post("/api/setup-admin",
                    json={"name": "intruder", "password": "hacked-123"})
    assert r.status_code == 409
    assert "已初始化" in r.json()["detail"]
    assert account_store.find_by_name(usersdb, "intruder") is None


def test_setup_admin_validation(  # pylint: disable=redefined-outer-name
        firstboot, client):
    """名称/密码不合规矩: 400 带中文原因。"""
    r = client.post("/api/setup-admin",
                    json={"name": "x", "password": "123456"})
    assert r.status_code == 400
    assert "名称" in r.json()["detail"]
    r = client.post("/api/setup-admin",
                    json={"name": "owner", "password": "12345"})
    assert r.status_code == 400
    assert "密码" in r.json()["detail"]


def test_setup_page_gate_opens_only_on_firstboot(  # pylint: disable=redefined-outer-name
        firstboot, client):
    """页面门: 首启 /setup 200; 建完管理员且配置齐 (isolate 口径) 再访
    302 回登录页。"""
    r = client.get("/setup", follow_redirects=False)
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert (client.post("/api/setup-admin",
                        json={"name": "owner",
                              "password": "first-boot-pass"}).status_code == 200)
    r = client.get("/setup", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/login"


def test_setup_page_redirects_when_initialized(client):
    """已初始化: /setup 一律 302 登录页, 不再出现引导面。"""
    r = client.get("/setup", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/login"


def test_setup_page_resume_requires_login(  # pylint: disable=redefined-outer-name
        auth, no_amap):
    """中途退出的续走: 管理员已在但配置缺 → 匿名访客先去登录页拿会话
    (带 next 回来), 已登录的直接进引导页接着配。"""
    anon = TestClient(m.app)   # auth 与本用例共享同一个 client, 匿名视角另开
    r = anon.get("/setup", follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (302, "/login?next=/setup")
    r = auth.get("/setup", follow_redirects=False)
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_tesla_shell_gated_until_wizard_done(  # pylint: disable=redefined-outer-name
        auth, no_amap):
    """应用门 (子仓的路由, 组合仓原样继承): 引导没走完 (还差高德 Key),
    /tesla 一律 302 回 /setup; 补齐最后一步立刻放行。"""
    r = auth.get("/tesla", follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (302, "/setup")
    assert auth.post("/tesla/api/settings",
                     json={"amap_key": "abcd1234efgh5678",
                           "amap_web_key": "wxyz9876abcd5432"}).status_code == 200
    r = auth.get("/tesla", follow_redirects=False)
    assert r.status_code == 200
    assert "html" in r.headers["content-type"]


def test_setup_page_standards(  # pylint: disable=redefined-outer-name
        firstboot, client):
    """引导页面标准: 禁缩放 viewport / 独立 App meta / manifest / no-zoom /
    无刷新跳转 / js+css 引用一律版本化 (与 test_page_standards 同口径)。"""
    html = client.get("/setup").text
    assert "maximum-scale=1, user-scalable=no" in html
    assert 'name="apple-mobile-web-app-capable"' in html
    assert 'href="/static/manifest.json"' in html
    assert '<script src="/static/no-zoom.js?v=' in html
    assert "http-equiv" not in html
    for m2 in re.finditer(r'(?:src|href)="(/static/[^"]+\.(?:js|css)(?:\?[^"]*)?)"',
                          html):
        assert "?v=" in m2.group(1), m2.group(1)
    css = (STATIC_DIR / "css" / "setup-page.css").read_text(encoding="utf-8")
    assert "[hidden] { display: none !important; }" in css
    assert "touch-action: manipulation" in css
    assert "touch-action: pan-y" in css
    assert "align-items: flex-start" in css   # 三张步页顶端对齐, 切步不跳版


def test_setup_page_wiring(  # pylint: disable=redefined-outer-name
        firstboot, client):
    """三步版接线: 三张表单 + 完成跳转 data-done + 脚本接口指向; 不允许
    跳过 (无跳过钮), 起步步数跟着缺口走。步骤条三项可点任意跳步回改,
    数据源/地图两步的测试闸 (测通才解锁主按钮) 在 setup-gates.js
    (2026-10-12 用户口径「要测试, 测试好之后才能下一步」; 同日再点名
    「测试」钮也要必填项填全才亮, 灰着点不动)。"""
    html = client.get("/setup").text
    assert 'data-done="/music"' in html
    for fid in ("form1", "form2", "form3"):
        assert f'id="{fid}"' in html
    assert "skip" not in html          # 不允许跳过: 跳过钮整链退役
    assert "btn-plain" not in html
    assert re.search(r'id="tm-host"[^>]*required', html)
    # 名称下限 (placeholder 一直写着 2~20, 原来只钉了上限)
    assert re.search(r'id="su-name"[^>]*minlength="2"', html)
    # 第三步是收尾步: 按钮写明存完即进应用 (2026-10-09 用户口径)
    assert "进入应用" in html
    # 两把高德 Key 的必填都交给测试闸 (2026-10-12 口径): 没 Key 测不过,
    # required 退役 —— 续走空框回落现值, 不再被迫重填明文
    assert '<label for="amap-key">地图 Key</label>' in html
    assert '<label for="amap-web">Web 服务 Key</label>' in html
    for rid in ("amap-key", "amap-web"):
        m = re.search(rf'<input id="{rid}"[^>]*>', html)
        assert m and "required" not in m.group(0), rid
    # 测试闸按钮行: 次级「测试」+ 锁着起步的主按钮 (测通才解锁); 测试钮
    # 自己也是灰的起步 —— 必填项填全 (setup-gates 现算) 才亮
    assert ('<button type="button" class="btn ghost" id="tm-test" disabled>'
            "测试连接</button>") in html
    assert ('<button type="button" class="btn ghost" id="amap-test" disabled>'
            "测试</button>") in html
    assert html.count('<button class="btn" type="submit" disabled>') == 2
    assert "back2" not in html          # 「上一步」方案 (同日早版) 整链退役
    assert "三步配齐才能进入" not in html
    # 两步的提示段 2026-10-10 撤 (用户点名「设置界面上的说明去掉」, 指导
    # 集中到 README) —— 数据源/地图步骤只留表单
    for gone in ("POSTGRES_PASSWORD", "docker-compose.yml", "高德开放平台",
                 "个人开发者免费", "可留空"):
        assert gone not in html, gone
    # 地图 Key 探针住适配层 (与设置页同一支): 引导页也挂上
    assert '<script src="/tesla/static/js/tesla-map-adapter.js?v=' in html
    js = client.get("/static/setup.js?v=9").text
    assert '"/api/setup-admin"' in js
    assert "web_key_masked" in js                # 预填时给现值掩码
    assert "tmPassSet" in js                     # 密码快拦状态 (没存过不许空着测)
    assert "amapKeySet" in js                    # 地图 Key 现值状态 (测试钮点亮用)
    # 步骤条可点 + 409 = 管理员步早已完成直接进下一步 (步骤可回跳后,
    # 不再是「别的设备抢跑」赶去登录页)
    assert 'li.addEventListener("click", () => showStep(i))' in js
    assert "if (r.status === 409) { advance(0); return; }" in js
    assert 'data-done' in js and "dataset.done" in js
    assert ".skip" not in js and "setup-status" in js
    assert 'missing.includes("account")' in js
    gates = client.get("/static/setup-gates.js?v=3").text
    assert '"/tesla/api/settings/test"' in gates     # 数据源候选实测端点
    assert '"/tesla/api/settings"' in gates          # 主按钮 = 保存 + 前进
    assert 'amap_web_key: v("amap-web")' in gates    # Web 服务 Key 随同提交
    assert "webKeySet" in gates                      # 已有现值可留空=保持
    assert '"/tesla/map/api/web-key-test"' in gates  # Web Key 服务端逆地理
    assert "/tesla/map/api/config" in gates          # 地图 Key 空框回落现值
    assert "mapLib.probeKey" in gates                # iframe 探针 (适配层)
    assert '"/tesla/map/api/roads/tick"' in gates    # 存好 Key 踢 worker 开跑
    # 闸: 输入一改作废重测, 主按钮锁着起步, 测通才开
    assert "next2.disabled = true;" in gates
    assert "next2.disabled = false;" in gates
    assert "next3.disabled = true;" in gates
    assert "next3.disabled = false;" in gates
    # 填错当场拦: 端口数字 / Key 32 位 / 测不过整句人话
    assert "1~65535" in gates
    assert "32 位字母数字" in gates
    assert "测试未通过" in gates
    # 密码快拦 (2026-10-12 向导验证实测: 预填密码空 + 留空回落 = 一串连接
    # 报错) + 401 统一去处 (没建管理员跳步进来测/存全 401, 只剩「HTTP 401」
    # 没头没脑): 没管理员回第一步, 已建过 (会话丢) 去登录页续走
    assert "数据库密码还没填" in gates
    assert 'if (r.status === 401) { await noSession(forms[1]); return; }' in gates
    assert 'if (r.status === 401) { await noSession(forms[2]); return; }' in gates
    assert "请先完成第一步「建立管理员」" in gates
    assert '"/login?next=/setup"' in gates
    # 测试钮明暗 (2026-10-12 用户点名「要填写全了才亮起按钮」): 数据源要
    # 地址/用户/库名 (+ 没存过密码时的密码), 地图要两把 Key (框里或现值);
    # 进门定一遍 + 输入一改 + 测试收尾 + setup.js 预填完都重算
    assert "const tmReady = () => {" in gates
    assert "const amapReady = () => {" in gates
    assert "const refreshTestButtons = () => {" in gates
    assert "refreshTestButtons();   // 进门先按现状定" in gates
    assert 'if (typeof refreshTestButtons === "function") refreshTestButtons();' in js


def test_login_js_probes_setup(client):
    """登录页探测: login.js 进页查引导状态, 只在账号步还缺 (真正的首启)
    时让位给 /setup —— 管理员已在只差配置的部署照常登录, 由应用门接手。"""
    js = client.get("/static/login.js?v=4").text
    assert '"/api/setup-status"' in js
    assert 'missing.includes("account")' in js
    assert '"/setup"' in js
