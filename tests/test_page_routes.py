"""页面路由测试: 根路径重定向链, 登录后放行, 静态资源重校验,
缓存头, 登录页回头客, 账号页归属门厅, 记账/音乐自有顶栏。
拆自 test_auth.py (结构化重构, 代码逐字节未动)。"""

from fastapi.testclient import TestClient

import app.main as m

from tests.page_test_helpers import _page_with_css

def test_root_redirect_chain(auth):
    """登录后根路径就是 My Home 门厅 (不再转去充电页); /tesla 仍收口到默认页。"""
    assert auth.get("/", follow_redirects=False).status_code == 200
    r = auth.get("/tesla", follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (302, "/tesla/charging")


def test_pages_served_after_login(auth):
    for path, marker in (("/", "My Home"),                    # 门厅
                         ("/tesla/charging", "My Tesla"),
                         ("/tesla/stats", "My Tesla"),
                         ("/tesla/chargemap", "My Tesla"),
                         ("/tesla/map", "My Tesla"),
                         ("/tesla/trips", "My Tesla"),
                         ("/register", "My Home"),
                         ("/tesla/changelog", "My Tesla"),
                         ("/tesla/groups", "My Tesla"),
                         ("/tesla/live", "My Tesla"),
                         ("/tesla/settings", "My Tesla"),
                         ("/accounts", "My Home"),             # 账号管理
                         ("/bookkeeping", "My Money"),
                         ("/bookkeeping/changelog", "My Money"),
                         ("/music/changelog", "My Music")):
        r = auth.get(path)
        assert r.status_code == 200, path
        assert marker in r.text, path


def test_static_js_must_revalidate(client):
    """JS 工具文件必须 no-cache 重新校验, 否则浏览器启发式缓存用旧版 (动画曾因此冻住)。"""
    r = client.get("/tesla/static/js/trackutil.js")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache"


def test_cache_control_headers(auth):
    """API 响应禁止缓存 (配置更新要即时生效), 页面允许缓存但必须重新校验。"""
    assert auth.get("/tesla/map/api/config?_=1").headers["cache-control"] == "no-store"
    # 未登录的 401 API 响应同样禁缓存
    anon = TestClient(m.app)
    assert anon.get("/tesla/map/api/config").headers["cache-control"] == "no-store"
    for path in ("/tesla/charging", "/tesla/map", "/tesla/trips",
                 "/", "/accounts", "/bookkeeping"):
        assert auth.get(path).headers["cache-control"] == "no-cache", path
    assert auth.get("/bookkeeping/static/bookkeeping-state.js").headers["cache-control"] \
        == "no-cache"
    assert auth.get("/static/home.js").headers["cache-control"] == "no-cache"


def test_login_page_redirects_authed_visitor(auth, client):
    """已登录的人开 /login: 服务端 302 直接进门厅 (不再显示表单 ——
    旧版靠页面 JS 探测切换, 现在登录态判断在中间件)。"""
    r = auth.get("/login", follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (302, "/")
    # 未登录看到的才是登录表单 (My Home 的门, 全站唯一)
    # (client 与 auth 是同一个对象且已登录, 匿名视角要新建)
    html = TestClient(m.app).get("/login").text
    assert "<title>登录 · My Home</title>" in html
    assert 'id="form"' in html
    assert 'id="eye"' in html          # 查看密码按钮 (图标并排显示 bug 修过)


def test_accounts_page_is_home_layer(auth):
    """账号管理页属门厅层: 品牌菜单是 My Home (门厅/两应用/账号管理,
    当前项高亮), 退出收在菜单里, 刷新按钮最右。"""
    html = auth.get("/accounts").text
    assert 'class="nav-menu brand-menu" id="brand-menu"' in html
    assert "<summary>My Home" in html
    assert '<a href="/">My Home 门厅</a>' in html
    assert '<a href="/tesla/charging">My Tesla</a>' in html
    assert '<a href="/bookkeeping">My Money</a>' in html
    assert '<a class="on" href="/accounts">账号管理</a>' in html
    assert 'class="logout-row" id="logout"' in html


def test_bookkeeping_topbar_is_own_app(auth):
    """记账应用自己的顶栏: 品牌下拉 + 退出登录收菜单里, 刷新按钮最右;
    与 My Tesla 只共享账号 —— 页面里不出现任何 tesla 链接/脚本。"""
    html = _page_with_css(auth, "/bookkeeping")    # refresh-btn 样式在 css 文件里
    assert 'class="nav-menu brand-menu" id="brand-menu"' in html
    assert 'class="logout-row" id="logout"' in html
    assert '<button type="button" id="refresh-btn"' in html
    block = html[html.index("#refresh-btn {"):]
    assert "margin-left: auto" in block[:block.index("}")]
    assert "/tesla/" not in html          # 独立应用: 图标/脚本/链接全自己的
    assert 'href="/bookkeeping/static/manifest.json"' in html


def test_mymusic_topbar_is_own_app(auth):
    """音乐应用的导航 (1.8.0: 底部船坞三件套): 菜单键/播放气泡/搜索键钉死
    视口底 (磨砂), 页签栏和 ☰ 菜单整个撤了 —— 播放列表/专辑/艺人/已下载/
    设置在上弹菜单, 统计/重扫/更新日志/退出登录全进设置页 (music.js 渲染)。
    与 My Tesla 只共享账号 —— 页面里不出现任何 tesla 链接/脚本,
    图标样式全自己的。"""
    html = auth.get("/music").text
    js = auth.get("/music/static/js/music-settings-view.js").text
    assert 'class="nav-menu brand-menu" id="brand-menu"' not in html  # 菜单撤了
    assert 'id="logout"' not in html and 'id="stats-link"' not in html
    assert "重新扫描曲库" not in html          # 职能进设置页 (JS 渲染)
    assert 'id="set-logout"' in js and 'id="set-rescan"' in js
    assert '<div id="dock">' in html                    # 底部船坞三件套
    assert 'id="dock-menu"' in html and 'id="dock-search"' in html
    assert 'data-pop-nav="settings"' in html            # 设置在上弹菜单里
    assert 'id="search-btn"' not in html               # 放大镜按钮已撤
    assert 'id="sync-playlists"' not in html           # Plex 同步入口已撤 (2026-09-15)
    assert 'id="refresh-btn"' not in html
    assert "/tesla/" not in html          # 独立应用: 图标/脚本/链接全自己的
    assert 'href="/music/static/manifest.json"' in html


def test_accounts_entry_only_in_home(auth):
    """账号管理入口只在门厅且仅管理员可见 (home.js 放行); My Tesla 的页面
    不再有账号管理 —— 账号体系属于 My Home 共享层, 不属于任何一个应用。"""
    home_js = auth.get("/static/home.js?v=1").text
    assert 'fetch("/api/me"' in home_js
    assert "is_admin" in home_js
    assert "admin-show" in home_js           # is_admin 才放行
    html = _page_with_css(auth, "/")         # .admin-only 样式在 css 文件里
    assert ".admin-only" in html             # CSS 默认 display:none
    assert ".admin-only.admin-show" in html  # 放行态
    for path in ("/tesla/charging", "/tesla/map", "/tesla/trips",
                 "/tesla/settings", "/tesla/live"):
        html = auth.get(path).text
        assert "账号管理" not in html, path
        assert "me.js" not in html, path
