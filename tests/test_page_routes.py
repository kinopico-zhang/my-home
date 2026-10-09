"""页面路由测试: 根路径重定向链, 登录后放行, 静态资源重校验,
缓存头, 登录页回头客, 账号页属共享层, 记账/音乐自有顶栏。
拆自 test_auth.py (拆仓批次随门厅撤除一并改口径)。"""

from fastapi.testclient import TestClient

import app.main as m

from tests.page_test_helpers import _page_with_css

def test_root_redirect_chain(auth):
    """门厅已撤: 根路径无条件 302 进 My Music (未登录会在音乐 scope 里
    被再拦一次登录页)。"""
    r = auth.get("/", follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (302, "/music")


def test_tesla_legacy_routes_redirect_to_shell(auth):
    """My Tesla 3.0 单壳: /tesla 直出壳, 9 个旧页地址全部 302 回壳并带
    ?view= 落到对应视图 (老书签/分享链接不丢目标); query 原样跟走,
    充电地图旧页的度量参数 ?view= 换名 ?metric= (?view= 让给视图选择)。"""
    r = auth.get("/tesla", follow_redirects=False)
    assert r.status_code == 200 and "My Tesla" in r.text
    r = auth.get("/tesla/charging", follow_redirects=False)
    # 2026-09-25 my-tesla 3.2.5 (未合入): /tesla/charging 回裸壳不再指
    # view=charging —— 2.x PWA 安装档把 start_url 烙死在这里, 指了 view=
    # 永远压过壳的「记住上次视图」(用户报每次冷启都是充电页)
    assert (r.status_code, r.headers["location"]) == (302, "/tesla")
    r = auth.get("/tesla/settings", follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (302, "/tesla?view=settings-db")
    # 行程分享深链: ?id= 原样跟到壳 (boot 消费后直开弹层)
    r = auth.get("/tesla/trips?id=42&range=30d", follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == \
        (302, "/tesla?id=42&range=30d&view=trips")
    # 充电地图度量参数换名; P2-P6 开发地址洗成裸壳
    r = auth.get("/tesla/chargemap?view=energy", follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == \
        (302, "/tesla?metric=energy&view=chargemap")
    r = auth.get("/tesla/app", follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (302, "/tesla")


def test_pages_served_after_login(auth):
    for path, marker in (("/tesla", "My Tesla"),
                         ("/register", "My Home"),
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
    """API 响应禁止缓存 (配置更新要即时生效), 页面允许缓存但必须重新校验;
    接口自带 Cache-Control 的例外 (2026-09-25 轨迹类接口 ETag/304) 不被
    no-store 盖掉 —— 那套在 my-tesla 测试仓验, 这里盖中间件自己的默认。"""
    assert auth.get("/tesla/map/api/config?_=1").headers["cache-control"] == "no-store"
    # 未登录的 401 API 响应同样禁缓存
    anon = TestClient(m.app)
    assert anon.get("/tesla/map/api/config").headers["cache-control"] == "no-store"
    for path in ("/tesla", "/accounts", "/bookkeeping"):
        assert auth.get(path).headers["cache-control"] == "no-cache", path
    assert auth.get("/bookkeeping/static/bookkeeping-state.js").headers["cache-control"] \
        == "no-cache"
    assert auth.get("/static/login.js").headers["cache-control"] == "no-cache"
    # 带版本参数 (?v=N) 的静态资源: 版本号一改 URL 就换, 同 URL 内容永不
    # 回头 (三个应用的门禁都钉着 HTML 里的版本串) → immutable 长缓存,
    # 重开页面不再整排 304 校验; 参数名要精确是 v
    assert auth.get("/static/login.js?v=4").headers["cache-control"] \
        == "public, max-age=31536000, immutable"
    assert auth.get("/static/login.js?x=1").headers["cache-control"] == "no-cache"


def test_login_page_redirects_authed_visitor(auth, client):
    """已登录的人开 /login: 服务端 302 直接进默认应用 My Music (不再显示
    表单 —— 旧版靠页面 JS 探测切换, 现在登录态判断在中间件)。"""
    r = auth.get("/login", follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (302, "/music")
    # 未登录看到的才是登录表单 (My Home 的门, 全站唯一)
    # (client 与 auth 是同一个对象且已登录, 匿名视角要新建)
    html = TestClient(m.app).get("/login").text
    assert "<title>登录 · My Home</title>" in html
    assert 'id="form"' in html
    assert 'id="eye"' in html          # 查看密码按钮 (图标并排显示 bug 修过)


def test_accounts_page_is_home_layer(auth):
    """账号管理页属共享层: 品牌菜单是 My Home (三应用 + 账号管理,
    当前项高亮), 退出收在菜单里, 刷新按钮最右。"""
    html = auth.get("/accounts").text
    assert 'class="nav-menu brand-menu" id="brand-menu"' in html
    assert "<summary>My Home" in html
    assert '<a href="/music">My Music</a>' in html
    assert '<a href="/tesla">My Tesla</a>' in html
    assert '<a href="/bookkeeping">My Money</a>' in html
    assert '<a class="on" href="/accounts">账号管理</a>' in html
    assert 'class="logout-row" id="logout"' in html


def test_bookkeeping_topbar_is_own_app(auth):
    """记账应用自己的导航 (1.3.0: 主页顶栏菜单整个撤了 — 更新日志/退出登录
    搬进更新日志页的菜单, 页面从同步状态条开始; 菜单在那边由
    test_page_branding 盯); 与 My Tesla 只共享账号 —— 页面里不出现任何
    tesla 链接/脚本。"""
    html = _page_with_css(auth, "/bookkeeping")
    assert 'class="nav-menu brand-menu" id="brand-menu"' not in html   # 主页菜单撤了
    assert 'id="logout"' not in html          # 退出登录住更新日志页
    assert 'id="refresh-btn"' not in html
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
    # 重扫在设置页本体; 退出登录随 1.8.57 账号自助进设置页的账号子模块
    # (music-settings-account.js), 不在设置页视图 js 里
    account_js = auth.get("/music/static/js/music-settings-account.js").text
    assert 'id="set-rescan"' in js
    assert 'id="set-logout"' in account_js
    assert '<div id="dock">' in html                    # 底部船坞三件套
    assert 'id="dock-menu"' in html and 'id="dock-search"' in html
    assert 'data-pop-nav="settings"' in html            # 设置在上弹菜单里
    assert 'id="search-btn"' not in html               # 放大镜按钮已撤
    assert 'id="sync-playlists"' not in html           # Plex 同步入口已撤 (2026-09-15)
    assert 'id="refresh-btn"' not in html
    assert "/tesla/" not in html          # 独立应用: 图标/脚本/链接全自己的
    assert 'href="/music/static/manifest.json"' in html


def test_accounts_not_in_app_pages(auth):
    """账号管理属于共享层, 不属于任何一个应用: My Tesla 的壳不出现
    账号管理入口, 也不引共享层的 me.js (门厅撤了, 入口只有直达 /accounts)。"""
    html = auth.get("/tesla").text
    assert "账号管理" not in html
    assert "me.js" not in html
