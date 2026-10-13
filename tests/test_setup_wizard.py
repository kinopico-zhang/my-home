"""首启引导 (/setup) 的接口与页面门: 配齐之前是唯一入口, 不允许跳过。

isolate autouse 种了管理员 + 高德 Key (已初始化口径), 这里用 firstboot 把
账号库清空、no_amap/no_teslamate 把配置撤掉, 拼出各缺口口径 (空库 + 无
env 的死路正是引导页要救的场景)。组合仓是四页版页面 (管理员 → 数据源 →
地图 → 完成), 数据源/地图的保存走既有 /tesla/api/settings (tesla 仓已深测),
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
    assert "align-items: flex-start" in css   # 四张步页顶端对齐, 切步不跳版


def test_setup_page_wiring(  # pylint: disable=redefined-outer-name
        firstboot, client):
    """四页线性接线 (2026-10-13 用户口径: 只有上一步/下一步, 步骤条不可
    点, 末页把所填汇总过目后显式进应用; 导航钮住常驻底栏与内容分离):
    三张表单页 + 完成面板, 无跳过钮, 起步页数跟着缺口走。数据源/地图两
    页的测试闸 (测通才解锁下一步, 测试钮要必填项填全才亮) 在
    setup-gates.js; 回上页改值不重置闸 —— 只有真改输入才作废重测。"""
    html = client.get("/setup").text
    # 进应用直落状态页 (2026-10-13 口径): ?view=live 优先于壳的 lastView
    # 回放 —— 不带参数会回到上次停留过的页面 (此前指 /music)
    assert 'data-done="/tesla?view=live"' in html
    for fid in ("form1", "form2", "form3"):
        assert f'id="{fid}"' in html
    assert "skip" not in html          # 不允许跳过: 跳过钮整链退役
    assert "btn-plain" not in html
    assert re.search(r'id="tm-host"[^>]*required', html)
    # 名称下限 (placeholder 一直写着 2~20, 原来只钉了上限)
    assert re.search(r'id="su-name"[^>]*minlength="2"', html)
    # 步骤条四项只展示进度, 点击跳步接线退役 (css 手型一并撤)
    assert "<li>管理员</li><li>数据源</li><li>地图</li><li>完成</li>" in html
    # 两把高德 Key 的必填都交给测试闸 (2026-10-12 口径): 没 Key 测不过,
    # required 退役 —— 续走空框回落现值, 不再被迫重填明文。Web Key 标签
    # 用短名 (2026-10-13 用户点名: 全称太长, label 会折行)
    assert '<label for="amap-key">地图 Key</label>' in html
    assert '<label for="amap-web">Web Key</label>' in html
    for rid in ("amap-key", "amap-web"):
        m = re.search(rf'<input id="{rid}"[^>]*>', html)
        assert m and "required" not in m.group(0), rid
    # 测试钮独占一行 (全宽 ghost, 住在表单内容里); 导航钮 (下一步/上一
    # 步/进入应用) 住常驻底栏, 钉与接线在 test_setup_dock_bar
    assert ('<button type="button" class="btn ghost solo" id="tm-test" disabled>'
            "测试连接</button>") in html
    assert ('<button type="button" class="btn ghost solo" id="amap-test" disabled>'
            "测试</button>") in html
    # 末页 (完成面板): 所有设置已完成 + 所填汇总过目 (敏感信息只给掩码/
    # ****, setup.js 进门现拉) + 显式「进入应用」(自动跳转退役)
    assert "所有设置已完成" in html
    assert '<dl class="done-summary" id="done-summary" hidden></dl>' in html
    css = (STATIC_DIR / "css" / "setup-page.css").read_text(encoding="utf-8")
    assert "步骤条可点" not in css            # 跳步退役, 手型注释一并撤
    assert ".btn.ghost.solo { width: 100%; margin-top: 14px; }" in css
    assert ".btn.testing::before" in css      # 测试中转圈动效 (不像假死)
    assert ".done-summary { margin-top: 16px; text-align: left; }" in css
    # 两页的提示段 2026-10-10 撤 (用户点名「设置界面上的说明去掉」, 指导
    # 集中到 README) —— 数据源/地图页只留表单
    for gone in ("POSTGRES_PASSWORD", "docker-compose.yml", "高德开放平台",
                 "个人开发者免费", "可留空"):
        assert gone not in html, gone
    # 地图 Key 探针住适配层 (与设置页同一支): 引导页也挂上
    assert '<script src="/tesla/static/js/tesla-map-adapter.js?v=' in html


def test_setup_dock_bar(  # pylint: disable=redefined-outer-name
        firstboot, client):
    """常驻底栏 (2026-10-13 用户口径: 下一步/上一步/进入应用钉在屏幕底部,
    与上面的内容分离 —— 表单再长自己滚, 按钮恒在手边)。按钮挪出卡片是躲
    .shake 报错动画的 transform 改锚 (变换中的祖先会把 fixed 子件连锚带
    偏, 底栏会跟着卡片抖), 靠 form 属性回绑各自表单, 提交语义照旧;
    data-pages = 哪页可见, setup.js 的 showStep 切页时翻 (一步变体没有
    底栏, dock 查空即跳过)。完成页的大对勾图标同批退役 (用户点名太丑)。"""
    html = client.get("/setup").text
    assert '<div class="dock" id="dock">' in html
    assert ('<button type="submit" class="btn" id="next1" form="form1"'
            ' hidden data-pages="0" disabled>下一步</button>') in html
    assert html.count('data-pages="1"') == 2     # 页2: 上一步 + 下一步
    assert html.count('data-pages="2"') == 2     # 页3: 上一步 + 下一步
    assert ('<button type="button" class="btn" id="enter" hidden'
            ' data-pages="3">进入应用</button>') in html
    assert html.count(">上一步</button>") == 2
    assert html.count(">下一步</button>") == 3   # 页1/2/3 各一枚 (住底栏)
    assert '<div class="done-icon">✅</div>' not in html
    css = (STATIC_DIR / "css" / "setup-page.css").read_text(encoding="utf-8")
    assert ".dock {" in css and "position: fixed" in css   # 玻璃浮条钉底部
    assert ".dock .btn { flex: 1; width: auto; margin-top: 0; }" in css
    assert "calc(92px + env(safe-area-inset-bottom))" in css   # 正文让位
    assert ".btn-row" not in css and ".done-icon" not in css   # 旧规则整条退役
    js = client.get("/static/setup.js?v=12").text
    assert 'document.getElementById("dock")' in js
    assert 'b.dataset.pages.split(" ").includes(String(index))' in js
    assert 'const next1 = document.getElementById("next1");' in js
    assert 'forms[0].querySelector' not in js
    gates = client.get("/static/setup-gates.js?v=6").text
    assert 'const next2 = document.getElementById("next2");' in gates
    assert 'const next3 = document.getElementById("next3");' in gates
    assert "querySelector" not in gates


def test_setup_wizard_scripts(  # pylint: disable=redefined-outer-name
        firstboot, client):
    """两份脚本的接线钉 (与 test_setup_page_wiring 拆开): setup.js 管页序/
    线性导航/建号/完成页汇总, setup-gates.js 管两页测试闸与上一步 (含测
    试钮状态机: 填全才亮, 测进行中灰着转圈, 飞行中改输入结果作废) —— 桩
    住真连端点的行为验证另有 playwright 探针 (存好即测过: 成功分支也解
    锁, 回页不逼重测)。"""
    js = client.get("/static/setup.js?v=12").text
    assert '"/api/setup-admin"' in js
    assert "web_key_masked" in js                # 占位提示给现值掩码
    assert "tmPassSet" in js                     # 密码快拦状态 (没存过不许空着测)
    assert "amapKeySet" in js                    # 地图 Key 现值状态 (测试钮点亮用)
    # 线性版: 跳步接线退役, 自动跳转退役; 页1 闸 = 三框填全 (管理员已建则
    # noValidate + 锁框直进), 409 = 管理员步早已完成直接进下一页
    assert "li.addEventListener" not in js
    assert "setTimeout" not in js
    assert "location.replace(doneUrl)" in js       # 末页「进入应用」显式跳
    assert "noValidate" in js and "markAccountDone" in js
    assert "requestSubmit" not in js               # 真 submit 钮, 无需手动代交
    assert "next1Ready" in js
    assert "if (r.status === 409) { markAccountDone(); advance(0); return; }" in js
    assert 'data-done' in js and "dataset.done" in js
    assert ".skip" not in js and "setup-status" in js
    assert 'missing.includes("account")' in js
    # 完成页汇总 (fillDoneSummary): 三页所填过目, 密码一律 ****, Key 走设
    # 置端点半遮掩码 —— 完整值不外泄
    assert "async function fillDoneSummary() {" in js
    assert "if (index + 1 === forms.length) fillDoneSummary();" in js
    assert '"/api/me"' in js and '"****"' in js
    # 预填值退役 (2026-10-13): env/docker 现值每处部署都不一样, 框留白自
    # 己填; 占位提示与「留空=保持」的标志照旧
    assert 'fill("tm-host", t.host)' not in js
    assert "key_masked ? `现值" in js
    assert 'row(map, "Web Key"' in js            # 汇总行短名 (label 不折行)
    gates = client.get("/static/setup-gates.js?v=6").text
    assert '"/tesla/api/settings/test"' in gates     # 数据源候选实测端点
    assert '"/tesla/api/settings"' in gates          # 主按钮 = 保存 + 前进
    assert 'amap_web_key: v("amap-web")' in gates    # Web 服务 Key 随同提交
    assert "webKeySet" in gates                      # 已有现值可留空=保持
    assert '"/tesla/map/api/web-key-test"' in gates  # Web Key 服务端逆地理
    assert "/tesla/map/api/config" in gates          # 地图 Key 空框回落现值
    assert "mapLib.probeKey" in gates                # iframe 探针 (适配层)
    assert '"/tesla/map/api/roads/tick"' in gates    # 存好 Key 踢 worker 开跑
    # 上一步: 只退页不重置闸 (改值才作废重测, 输入监听在下面)
    assert ('document.getElementById("back2").addEventListener'
            '("click", () => showStep(0));') in gates
    assert ('document.getElementById("back3").addEventListener'
            '("click", () => showStep(1));') in gates
    # 存好即测过: 保存成功分支也解锁 —— 上一步退回本页闸保持开着,
    # 不逼着重测 (探针实抓过反例: 飞行锁在成功分支漏解, 回页就卡死)
    assert "if (r.ok) { next2.disabled = false; advance(1); return; }" in gates
    assert "next3.disabled = false;          // 同 next2: 存好即测过, 闸保持开" in gates
    # 闸: 输入一改作废重测, 主按钮锁着起步, 测通才开 (下一步住底栏, 取法
    # 在 test_setup_dock_bar)
    assert "next2.disabled = true;" in gates
    assert "next2.disabled = false;" in gates
    assert "next3.disabled = true;" in gates
    assert "next3.disabled = false;" in gates
    # 填错当场拦: 端口数字 / Key 32 位 / 测不过整句人话
    assert "1~65535" in gates
    assert "32 位字母数字" in gates
    assert "测试未通过" in gates
    # 密码快拦 (2026-10-12 向导验证实测: 预填密码空 + 留空回落 = 一串连接
    # 报错) + 401 统一去处 (续走会话丢了, 测试/保存全 401, 只剩「HTTP 401」
    # 没头没脑): 没管理员回第一页, 已建过 (会话丢) 去登录页续走
    assert "数据库密码还没填" in gates
    assert 'if (r.status === 401) { await noSession(forms[1]); return; }' in gates
    assert 'if (r.status === 401) { await noSession(forms[2]); return; }' in gates
    assert "请先完成「管理员」页" in gates
    assert '"/login?next=/setup"' in gates
    # 测试钮明暗 (2026-10-12 用户点名「要填写全了才亮起按钮」): 数据源要
    # 地址/用户/库名 (+ 没存过密码时的密码), 地图要两把 Key (框里或现值);
    # 进门定一遍 + 输入一改 + 测试收尾 + setup.js 预填完都重算
    assert "const tmReady = () => {" in gates
    assert "const amapReady = () => {" in gates
    assert "const refreshTestButtons = () => {" in gates
    assert "refreshTestButtons();   // 进门先按现状定" in gates
    assert 'if (typeof refreshTestButtons === "function") refreshTestButtons();' in js
    # 测试钮状态机 (2026-10-13 二轮): 填全才亮 → 测进行中灰着转圈 (飞行
    # 锁, 中途改输入也不许重新点亮) → 收尾恢复; 飞行中改输入 = 结果作废
    assert ("let tmTesting = false;" in gates
            and "let amapTesting = false;" in gates)
    assert "if (t2) t2.disabled = tmTesting || !tmReady();" in gates
    assert "if (t3) t3.disabled = amapTesting || !amapReady();" in gates
    assert 'test.textContent = "测试中…";' in gates
    assert ('classList.add("testing")' in gates
            and 'classList.remove("testing")' in gates)
    assert "tmEdits += 1;" in gates and "amapEdits += 1;" in gates
    assert ("if (tmEdits !== mark) return;" in gates
            and "if (amapEdits !== mark) return;" in gates)


def test_login_js_probes_setup(client):
    """登录页探测: login.js 进页查引导状态, 只在账号步还缺 (真正的首启)
    时让位给 /setup —— 管理员已在只差配置的部署照常登录, 由应用门接手。"""
    js = client.get("/static/login.js?v=4").text
    assert '"/api/setup-status"' in js
    assert 'missing.includes("account")' in js
    assert '"/setup"' in js
