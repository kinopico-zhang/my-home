"""页面品牌测试: 顶栏菜单显示当前用户, 每页品牌菜单。
拆自 test_auth.py (拆仓批次改口径: 三应用页面来自子仓, 不再扫本仓目录)。"""
from pathlib import Path

import app.main as m


def test_brand_menu_pages_show_current_user(auth):
    """每个带品牌下拉的页面都引 menu-user.js (共享层小件, 挂根 /static):
    菜单顶部显示当前登录的账号。页面本体在三个子仓里, 这里按 HTTP 口径
    验接线 —— 组合装配把它们拼在同一个源下。

    My Tesla 3.0 单壳不在此列: 账号行收进右划抽屉 (子仓 test_shell_wiring
    钉), 不引共享层小件。"""
    # 带品牌菜单的页面 (记账更新日志页 + 账号管理; 音乐主页 1.8.0 撤了菜单,
    # 记账主页 1.3.0 也撤了 —— 菜单住更新日志页)
    for path in ("/bookkeeping/changelog", "/accounts"):
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


def test_tesla_shell_has_no_brand_menu(auth):
    """My Tesla 3.0 单壳: 品牌下拉/页签菜单/顶栏退出全撤, 换右划抽屉
    (导航 + 车辆); 共享层小件 menu-user.js 不进壳。菜单圆键 2026-09-27
    退役 (任意页右划/地图左缘条呼出抽屉, 圆键成冗余入口)。"""
    html = auth.get("/tesla").text
    assert 'id="brand-menu"' not in html
    assert "/static/menu-user.js" not in html
    assert '<nav class="tabs">' not in html
    # 抽屉是新的导航位 (细节接线在子仓 test_shell_wiring)
    assert 'id="drawer"' in html and 'id="menu-key"' not in html
