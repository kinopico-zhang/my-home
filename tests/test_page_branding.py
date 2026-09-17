"""页面品牌测试: 顶栏菜单显示当前用户, 每页品牌菜单。
拆自 test_auth.py (拆仓批次改口径: 三应用页面来自子仓, 不再扫本仓目录)。"""
from pathlib import Path

import app.main as m


def test_brand_menu_pages_show_current_user(auth):
    """每个带品牌下拉的页面都引 menu-user.js (共享层小件, 挂根 /static):
    菜单顶部显示当前登录的账号。页面本体在三个子仓里, 这里按 HTTP 口径
    验接线 —— 组合装配把它们拼在同一个源下。"""
    # 带品牌菜单的页面 (My Tesla 各业务页 + 记账 + 账号管理;
    # 音乐主页 1.8.0 撤了菜单, 不在此列)
    for path in ("/tesla/charging", "/tesla/stats", "/tesla/map",
                 "/tesla/trips", "/tesla/live", "/tesla/settings",
                 "/bookkeeping", "/accounts"):
        html = auth.get(path).text
        assert 'class="nav-menu brand-menu" id="brand-menu"' in html, path
        assert "/static/menu-user.js" in html, f"{path} 缺 menu-user.js"
    # 小件本身: 问 /api/me, 样式自带, 找不到菜单静默不装 (名字走 DOM 不进 innerHTML)
    widget = (Path(m.__file__).parent / "home" / "static"
              / "menu-user.js").read_text(encoding="utf-8")
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
