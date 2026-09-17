"""页面品牌测试: 顶栏菜单显示当前用户, 每页品牌菜单, 门厅页
是应用启动器。
拆自 test_auth.py (结构化重构, 代码逐字节未动)。"""
from pathlib import Path

from fastapi.testclient import TestClient

import app.main as m


def test_brand_menu_pages_show_current_user():
    """每个带品牌下拉的页面都引 menu-user.js: 菜单顶部显示当前登录的账号。"""
    root = Path(__file__).parent.parent / "app"
    pages = [page for base in ("tesla", "bookkeeping", "music", "home")
             for page in (root / base / "static").glob("*.html")
             if "brand-menu" in page.read_text(encoding="utf-8")]
    # 三应用 12 页 + 门厅账号页 (音乐主页面 1.7.0 撤了菜单, 导航挪去底部
    # 页签栏), 加页面也得跟上
    assert len(pages) >= 13
    for page in pages:
        html = page.read_text(encoding="utf-8")
        assert "/static/menu-user.js" in html, f"{page.name} 缺 menu-user.js"
    # 小件本身: 问 /api/me, 样式自带, 找不到菜单静默不装 (名字走 DOM 不进 innerHTML)
    widget = (root / "home" / "static" / "menu-user.js").read_text(encoding="utf-8")
    for frag in ('"/api/me"', ".brand-menu .menu", "menu.prepend",
                 "is_admin", ".textContent = name"):
        assert frag in widget, f"menu-user.js 缺少 {frag}"
    # 外点收回: 菜单外任意点击收起所有展开的下拉 (capture 阶段, 换菜单也顺)
    for frag in ("details.nav-menu[open]", "menu.removeAttribute(\"open\")"):
        assert frag in widget, f"menu-user.js 缺少 {frag}"


def test_all_pages_have_brand_menu(auth):
    """品牌即入口: My Tesla 是下拉按钮, 展开是三个页面 + 退出登录, 当前页高亮。"""
    for path, cur, slug in (("/tesla/charging", "充电记录", "charging"),
                            ("/tesla/map", "足迹地图", "map"),
                            ("/tesla/trips", "行程列表", "trips"),
                            ("/tesla/live", "当前驾驶", "live")):
        html = auth.get(path).text
        assert 'class="nav-menu brand-menu" id="brand-menu"' in html, path
        assert '<nav class="tabs">' not in html, path       # 平铺页签已删
        assert "<h1>My Tesla</h1>" not in html, path        # 旧标题位换成品牌下拉
        assert 'id="nav-menu"' not in html, path            # 旧页签菜单已删
        for href in ("/tesla/charging", "/tesla/map", "/tesla/trips",
                     "/tesla/live"):
            assert f'href="{href}"' in html, (path, href)
        assert f'<a class="on" href="/tesla/{slug}">{cur}</a>' in html, (path, cur)
        # 退出收进品牌菜单 (不再是顶栏独立按钮)
        assert 'class="logout-row" id="logout"' in html and "logout-btn" not in html, path
        assert "退出登录" in html, path
        # 记账是独立应用: My Tesla 的菜单不再链过去
        assert 'href="/bookkeeping"' not in html, path


def test_home_page_is_the_launcher(auth):
    """根路径 = My Home 门厅: 各应用的入口卡 + 账号管理 (管理员专属,
    home.js 按 /api/me 放行) + 退出登录。账号体系属于门厅共享层,
    不属于任何一个应用。"""
    html = auth.get("/").text
    assert "<title>My Home</title>" in html
    assert "<h1>My Home</h1>" in html
    assert '<a class="app" href="/tesla/charging">' in html   # My Tesla 卡
    assert "My Tesla" in html
    assert '<a class="app" href="/bookkeeping">' in html      # My Money 卡
    assert "My Money" in html
    assert '<a class="app" href="/music">' in html            # My Music 卡
    assert "My Music" in html
    assert 'class="admin-only" id="accounts-link" href="/accounts"' in html
    assert '<button id="logout" type="button">退出登录</button>' in html
    home_js = auth.get("/static/home.js?v=1").text
    assert 'fetch("/api/me"' in home_js
    assert "is_admin" in home_js
    assert "admin-show" in home_js            # is_admin 才放行账号管理入口
    assert "欢迎回来" in home_js               # 欢迎语带账号名
    # 登录页/注册页不是门厅 (登录页只放表单, 注册页是一次性邀请入口);
    # auth fixture 的 client 已登录, 匿名视角要用全新的 TestClient
    anon = TestClient(m.app)
    assert 'id="apps"' not in anon.get("/login").text
    assert 'id="apps"' not in anon.get("/register").text
