"""全站页面标准测试: 独立模式 meta, 双击缩放禁用, 刷新按钮退役,
记住最后页面, manifest 各用各的。
拆自 test_auth.py (结构化重构, 代码逐字节未动)。"""



from tests.page_test_helpers import (
    ALL_PAGES,
    _page_client,
    _page_with_css,
)

def test_all_pages_have_standalone_meta(auth):
    """全部页面 (含登录/注册/记账) 都带全屏 App meta。

    桌面图标是全屏 web app, 有独立 cookie 存储: 首次启动必然 302 到登录页。
    登录页一旦缺 meta, 整个 App 会被弹回 Safari 露地址栏, 之后再也回不去
    全屏 (2026-09-12 用户踩坑)。任何新增页面都必须带上。
    """
    for path in ALL_PAGES:
        html = _page_client(auth, path).get(path).text
        assert 'name="apple-mobile-web-app-capable" content="yes"' in html, path
        # 状态栏样式跟各应用底色走, 不再全站钉死 black-translucent (深底白字
        # 时代的值): My Money 1.4.0 翻浅青底改 default (浅底深字), 深底应用
        # (Tesla/音乐/门厅) 仍 black-translucent —— 只要求 meta 在且值是
        # 有意识选的两种之一, 不许缺 (缺了会被弹回 Safari 露地址栏)
        assert ('name="apple-mobile-web-app-status-bar-style"'
                ' content="default"' in html
                or 'content="black-translucent"' in html), path
        # manifest 各用各的: 门厅层一份, Tesla / 记账 / 音乐各一份
        manifest = ("/bookkeeping/static/manifest.json" if path == "/bookkeeping"
                    else "/music/static/manifest.json" if path == "/music"
                    else "/static/manifest.json" if not path.startswith("/tesla")
                    else "/tesla/static/manifest.json")
        assert f'<link rel="manifest" href="{manifest}">' in html, path
def test_all_pages_disable_double_tap_zoom_on_controls(auth):
    """触屏双击控件不再整页放大 (2026-09-13 用户踩坑)。

    iOS 忽略 user-scalable=no, 双击按钮/链接/菜单会被 Safari 当双击缩放;
    touch-action: manipulation 只去掉双击缩放, 平移和捏合缩放保留
    (地图手势区是 div, 不受影响)。全站统一, 登录页也要有。
    """
    for path in ALL_PAGES:
        page = _page_with_css(auth, path)
        assert "button, a, summary { touch-action: manipulation; }" in page, path


def test_no_page_has_refresh_button(auth):
    """刷新按钮全站退役 (用户点名: 导航菜单不需要刷新按钮)。

    曾经的形态: 记账/账号/各应用日志页顶栏胶囊刷新按钮 (busy 时图标旋转),
    Tesla 2.x 每页顶栏也有。现在一个不留 —— 页面数据都是打开即拉, 记账的
    同步更是定时+回前台自动跑, 按钮是冗余入口; Tesla 3.0 单壳每视图下拉
    刷新 (见子仓 test_shell_wiring)。"""
    paths = [*ALL_PAGES, "/music/changelog", "/bookkeeping/changelog"]
    for path in paths:
        page = _page_with_css(auth, path)
        assert 'id="refresh-btn"' not in page, path
        assert "refresh-spin" not in page, path


def test_tesla_shell_remembers_last_view(auth):
    """My Tesla 的"记住停留页": 3.0 起壳自己记 (localStorage tesla.lastView,
    冷启回放上次视图), lastpage.js 随旧页退役 —— 任何页面都不再挂它。

    登录页这边剩兼容账: 老版本存下的 mytesla-last-page 是旧页路径, 登录后
    照跳 —— 旧地址 302 回壳带 ?view=, 落点不丢; 站外/坏值回落 My Music
    (门厅撤了, 默认进音乐), 不再写死充电页。"""
    # lastpage.js 已删: 全站页面 (含 Tesla 壳) 与登录/注册都不再挂它
    for path in ALL_PAGES:
        html = _page_client(auth, path).get(path).text
        assert "lastpage.js" not in html, path
    # 壳: 上次视图记在 localStorage, boot 冷启回放 (?view= 深链优先, 洗成裸壳)
    shell_js = auth.get("/tesla/static/js/tesla-shell.js?v=1").text
    assert 'localStorage.setItem("tesla.lastView", key)' in shell_js
    assert "function readLastView()" in shell_js
    boot_js = auth.get("/tesla/static/js/tesla-app-boot.js?v=1").text
    # 3.3.0 起冷启默认落地状态页 (原先充电记录; 详见子仓 tesla-app-boot)
    assert '(VIEWS[lastView] ? lastView : "live")' in boot_js
    assert 'history.replaceState(null, "", "/tesla");' in boot_js
    # 登录成功去哪: 逻辑在 login.js —— 应用内的登录页回该应用 (或 next 参数
    # 带来的原地址, 只认本应用 scope), 根登录页回上次停留页 (白名单正则,
    # 站外/坏值回落 My Music —— 门厅撤了, 默认进音乐), 不再写死充电页
    login_html = auth.get("/static/login.js?v=4").text
    assert 'localStorage.getItem("mytesla-last-page")' in login_html
    assert ("/^\\/(tesla\\/(charging|stats|chargemap|map|trips|groups|live|settings"
            "|changelog))(\\?|$)/.test(last)") in login_html
    assert '? last : "/music"' in login_html
    assert 'function pickNext()' in login_html
    assert 'const APP_TITLES = { "/tesla": "My Tesla", "/music": "My Music",' in login_html


def test_webapp_manifests_scoped_per_app(auth):
    """Web App Manifest: 各入口一份 (门厅 / Tesla / 记账 / 音乐), 名字和启动页
    互不相同, scope 各归各 —— 同源四张 manifest 都圈 "/" 时, iOS 锁屏点播放
    封面会归给先装的 My Tesla (2026-09-14 用户实测跳错应用)。scope 收窄后
    会话过期 302 /login 越界的旧坑 (2026-09-12) 由各应用 scope 内自带登录页
    解决 (见 test_app_login_pages_in_scope)。图标各用各的, 加主屏互不干扰。"""
    for url, name, scope, start in (
            ("/tesla/static/manifest.json", "My Tesla", "/tesla", "/tesla"),
            ("/bookkeeping/static/manifest.json", "My Money", "/bookkeeping", "/bookkeeping"),
            ("/music/static/manifest.json", "My Music", "/music", "/music"),
            ("/static/manifest.json", "My Home", "/", "/")):
        r = auth.get(url)
        assert r.status_code == 200, url
        manifest = r.json()
        assert manifest["name"] == name
        assert manifest["scope"] == scope
        assert manifest["display"] == "standalone"
        assert manifest["start_url"] == start
        assert any(i["sizes"] == "192x192" for i in manifest["icons"])
        assert any(i["sizes"] == "512x512" for i in manifest["icons"])
    for icon in ("/tesla/static/icon-192.png", "/tesla/static/icon-512.png",
                 "/bookkeeping/static/icon-192.png",
                 "/bookkeeping/static/icon-512.png",
                 "/static/icon-192.png", "/static/icon-512.png"):
        assert auth.get(icon).status_code == 200, icon
