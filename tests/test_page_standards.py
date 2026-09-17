"""全站页面标准测试: 独立模式 meta, 双击缩放禁用, 刷新按钮接线,
记住最后页面, manifest 各用各的。
拆自 test_auth.py (结构化重构, 代码逐字节未动)。"""



from tests.page_test_helpers import ALL_PAGES, _page_with_css

def test_all_pages_have_standalone_meta(auth):
    """全部页面 (含登录/注册/记账) 都带全屏 App meta。

    桌面图标是全屏 web app, 有独立 cookie 存储: 首次启动必然 302 到登录页。
    登录页一旦缺 meta, 整个 App 会被弹回 Safari 露地址栏, 之后再也回不去
    全屏 (2026-09-12 用户踩坑)。任何新增页面都必须带上。
    """
    for path in ALL_PAGES:
        html = auth.get(path).text
        assert 'name="apple-mobile-web-app-capable" content="yes"' in html, path
        assert 'content="black-translucent"' in html, path
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


def test_all_pages_have_refresh_button(auth):
    """每页顶栏都有刷新按钮 (2026-09-13 用户反馈: 不是每个页面都有)。

    行程页首倡的胶囊刷新按钮 (busy 时图标旋转) 铺到全部业务页; 每页接
    自己的重载入口 —— 列表页重拉后回顶, 地图页不带首载遮罩 (refresh(false)),
    设置页拉完设置再补司机列表; 记账页 = 立即同步, 账号页 = 重拉用户与邀请。
    """
    # 页面路径 -> (该页 JS 文件, 点击后接的重载调用)
    wiring = {
        "/tesla/charging": ("js/charging-cards.js", "await refetch();"),
        "/tesla/stats": ("js/stats-time-filters.js", "await refetch();"),
        "/tesla/chargemap": ("js/chargemap-time-filters.js", "await refresh(false);"),
        "/tesla/map": ("js/map-filters.js", "await refresh(false);"),
        "/tesla/trips": ("js/trips-list-page.js", "await refreshList();"),
        "/tesla/groups": ("js/groups.js", "await load();"),
        "/tesla/live": ("js/live-driving.js", "await poll();"),
        "/tesla/settings": ("js/settings-account.js", "await loadSettings();"),
        "/tesla/changelog": ("/static/changelog-page.js", "await load();"),
        "/music/changelog": ("/static/changelog-page.js", "await load();"),
        "/bookkeeping/changelog": ("/static/changelog-page.js", "await load();"),
        "/bookkeeping": ("bookkeeping-sync.js", "await syncNow();"),
        "/accounts": ("accounts.js", "await loadAll();"),
    }
    for path, (js_file, call) in wiring.items():
        page = _page_with_css(auth, path)   # refresh-spin/#refresh-btn 样式在 css 文件里
        assert '<button type="button" id="refresh-btn"' in page, path  # 按钮在顶栏
        assert "refresh-spin" in page, path                   # busy 旋转动画
        prefix = ("/bookkeeping/static" if path.startswith("/bookkeeping")
                  else "/music/static" if path == "/music"
                  else "/static" if path == "/accounts"
                  else "/tesla/static")
        js_path = js_file if js_file.startswith("/") else f"{prefix}/{js_file}"
        js = auth.get(f"{js_path}?v=1").text
        assert '$("#refresh-btn").addEventListener' in js, path
        assert call in js, f"{path} 刷新按钮没接上 {call}"
        # 刷新按钮始终顶栏最右: 有时间菜单的页菜单吃 auto 边距, 按钮跟在后面;
        # 没有的页 (分组/驾驶/设置/日志/记账/账号) 按钮自己吃 auto 边距
        if 'id="time-menu"' not in page:
            block = page[page.index("#refresh-btn {"):]
            assert "margin-left: auto" in block[:block.index("}")], path


def test_pages_remember_last_page(auth):
    """上次停留页: 业务页 head 挂 lastpage.js (冷启动在任何渲染前跳转,
    不闪启动页), 登录页/注册页不挂 (不是停留目标); 登录成功回上次页而非
    写死充电页。

    iOS 主屏图标每次都从添加时定格的 start_url 启动, 不记得停在哪页 ——
    localStorage 记 path+search, 冷启动 (sessionStorage 无标记) 且 standalone
    才 replace 过去; 行程弹层开合只动 URL 不重载, 靠 visibilitychange 补记。"""
    # lastpage 是 Tesla 应用内的概念: 门厅/登录/注册/账号管理/记账/音乐都不挂
    home_layer = ("/", "/login", "/register", "/accounts", "/bookkeeping", "/music")
    for path in [p for p in ALL_PAGES if p not in home_layer]:
        html = auth.get(path).text
        tag = '<script src="/tesla/static/js/lastpage.js?v=1"></script>'
        assert tag in html, path
        assert html.index(tag) < html.index("<title>"), "要放 <title> 前 (首渲染前执行)"
    assert "lastpage.js" not in auth.get("/login").text
    assert "lastpage.js" not in auth.get("/register").text
    # 登录成功去哪: 逻辑在 login.js —— 应用内的登录页回该应用 (或 next 参数
    # 带来的原地址, 只认本应用 scope), 门厅的回上次停留页 (白名单正则,
    # 站外/坏值回落门厅), 不再写死充电页
    login_html = auth.get("/static/login.js?v=1").text
    assert 'localStorage.getItem("mytesla-last-page")' in login_html
    assert ("/^\\/(tesla\\/(charging|stats|chargemap|map|trips|groups|live|settings"
            "|changelog))(\\?|$)/.test(last)") in login_html
    assert '? last : "/"' in login_html
    assert 'function pickNext()' in login_html
    assert 'const APP_TITLES = { "/tesla": "My Tesla", "/music": "My Music",' in login_html

    r = auth.get("/tesla/static/js/lastpage.js")
    assert r.status_code == 200
    js = r.text
    for frag in [
        '"/tesla/charging", "/tesla/stats", "/tesla/chargemap",',   # 白名单业务页
        '"/tesla/changelog"]',
        "PAGES.indexOf(path) === -1) return",                  # login/静态不记不跳
        "sessionStorage.getItem(LAUNCH)",                      # 冷启动判据 (会话标记)
        "catch (e) { return; }",                               # 隐私模式防回弹循环
        "navigator.standalone === true",                       # 只在主屏全屏 App 里跳
        'location.replace(saved)',                             # 目标过白名单才跳
        'if (document.hidden) record()',                       # 后台时补记 (弹层开合)
    ]:
        assert frag in js, f"lastpage.js 缺少 {frag}"


def test_webapp_manifests_scoped_per_app(auth):
    """Web App Manifest: 各入口一份 (门厅 / Tesla / 记账 / 音乐), 名字和启动页
    互不相同, scope 各归各 —— 同源四张 manifest 都圈 "/" 时, iOS 锁屏点播放
    封面会归给先装的 My Tesla (2026-09-14 用户实测跳错应用)。scope 收窄后
    会话过期 302 /login 越界的旧坑 (2026-09-12) 由各应用 scope 内自带登录页
    解决 (见 test_app_login_pages_in_scope)。图标各用各的, 加主屏互不干扰。"""
    for url, name, scope, start in (
            ("/tesla/static/manifest.json", "My Tesla", "/tesla", "/tesla/charging"),
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
