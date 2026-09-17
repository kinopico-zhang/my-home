"""My Music 底部船坞接线测试 (1.8.0): 页签栏撤掉换三件套 (菜单键/气泡/
搜索键) + 上弹菜单 + 跑马灯, 以及顶栏黑罩/机型兜底的「全撤」回归 ——
静态文本断言, 不碰数据库。"""
import re
from pathlib import Path

from tests.music_static_files import (MUSIC_STATIC, music_browser_js,
                                      music_page_shell, music_player_js)


def test_music_dock_wiring():
    """底部船坞 (用户点名「整个底栏从左到右: 菜单按钮, 气泡, 搜索」): 原四页签
    栏整个撤掉, 换一行三件 —— 左右两颗圆键 (磨砂, 与气泡同配方) 夹着中间
    变窄的气泡。气泡上只有封面/歌名/播放暂停 (上下曲撤了, 全屏页里都有);
    歌名/作者放不下改跑马灯来回滚。菜单键点开从键上方弹出一列纵向菜单
    (播放列表/专辑/艺人/最近播放/已下载/设置), 带缩放上弹动画; 搜索键直进
    搜索页顺手聚焦输入框。船坞本体透明: 只管定位, 点击穿到内容上。"""
    html = music_page_shell()
    js = music_browser_js()
    player = music_player_js()
    # 旧页签栏死透
    assert "<nav id=\"tabbar\">" not in html and "data-view-tab" not in html
    assert "--tabbar-h" not in html and "tab-row" not in html
    assert "syncViewTabs" not in js
    # 三件套从左到右: 菜单键 / 气泡 / 搜索键 (markup 顺序即视觉顺序)
    dock_html = html[html.index('<div id="dock">'):html.index("<!-- 菜单键的上弹菜单")]
    assert dock_html.index('id="dock-menu"') < dock_html.index('id="mini-player"') \
        < dock_html.index('id="dock-search"')
    # 船坞本体透明 (点击穿到内容), 三件各自磨砂; 让位账收进 --dock-clear
    dock_css = html[html.index("#dock {"):html.index(".dock-row {")]
    assert "pointer-events: none;" in dock_css
    assert "--dock-h: 46px;" in html
    # 1.8.1 撤掉页签栏时代多记的那层 46px 空带: 内容铺到三件套底下, 只留呼吸缝
    assert "--dock-clear: calc(var(--dock-h) + 14px + env(safe-area-inset-bottom));" in html
    assert "calc(4px + env(safe-area-inset-bottom))" in dock_css   # 三件套贴屏底
    assert "env(safe-area-inset-bottom)" in dock_css       # 让开小白条
    keys_css = html[html.index("#dock-menu, #dock-search {"):html.index("#dock-menu:active")]
    assert "border-radius: 50%;" in keys_css               # 圆键
    assert "rgba(44,44,46,.78);" in keys_css               # 磨砂配方与气泡同款 (1.8.3 调实一档)
    assert "backdrop-filter: blur(20px) saturate(180%);" in keys_css
    assert "transform: translateZ(0);" in keys_css         # 自家合成层防复印
    # 气泡变窄: flex:1 占中间, 圆角胶囊; 上下曲没了, 只留播放/暂停
    mini_css = html[html.index("#mini-player {"):html.index("#mini-progress")]
    assert "flex: 1; min-width: 0;" in mini_css and "border-radius: 23px;" in mini_css
    assert 'id="mini-play"' in html
    assert 'id="mini-prev"' not in html and 'id="mini-next"' not in html
    # 跑马灯: 文字比行宽长才滚 (JS 量过), 两端各停一拍再往回走
    assert 'class="mq-line"' in html and 'class="mq-run"' in html
    assert ".mq-run.marquee {" in html and "@keyframes mq-scroll" in html
    assert "animation: mq-scroll var(--mq-dur, 12s) linear infinite alternate;" in html
    for frag in ["function setMarqueeLine", "run.scrollWidth - line.clientWidth",
                 "if (overflow <= 2) return;",              # 放得下不滚
                 'run.style.setProperty("--mq-dx", `${-overflow}px`)',
                 'run.style.setProperty("--mq-dur", `${Math.max(8, overflow / 18)}s`)',
                 'run.classList.add("marquee")']:
        assert frag in player, f"跑马灯缺 {frag}"
    # 量跑马灯前先显形 (display:none 量出 0 宽), 窗口变了重量
    chrome = player[player.index("function renderPlayerChrome"):]
    assert '$("#mini-player").hidden = !track;' in chrome
    assert "setMarqueeLine($(\"#mini-title\")" in chrome
    assert "addEventListener(\"resize\"" in player[player.index("let marqueeResizeTimer"):]
    # 上弹菜单: 六项带图标, 从键上方弹出 (缩放+上移入场动画)
    for entry, label in [("playlists", "播放列表"), ("albums", "专辑"),
                         ("artists", "艺人"), ("recent", "最近播放"),
                         ("downloads", "已下载"), ("settings", "设置")]:
        assert f'data-pop-nav="{entry}"><svg' in html
        assert f"{label}</button>" in html
    assert '<div id="pop-mask" hidden></div>' in html
    assert '<nav id="pop-menu" hidden>' in html
    pop_css = html[html.index("#pop-menu {"):html.index("@keyframes pop-in")]
    assert "bottom: calc(var(--dock-h) + 16px + env(safe-area-inset-bottom));" in pop_css
    assert "transform-origin: 23px calc(100% + 18px);" in pop_css   # 长在菜单键上
    assert "animation: pop-in .22s cubic-bezier(.3, 1.3, .4, 1);" in pop_css
    assert "from { opacity: 0; transform: translateY(10px) scale(.88); }" in html
    # 开关与导航: 遮罩点击/Esc 收, 选完条目先收菜单再进层
    for frag in ['$("#dock-menu").addEventListener("click"',
                 '$("#pop-mask").addEventListener("click", closeDockMenu)',
                 "closeDockMenu();", "navigate(button.dataset.popNav)",
                 "function closeDockMenu"]:
        assert frag in js, f"菜单接线缺 {frag}"
    assert 'if (!$("#pop-menu").hidden) closeDockMenu();' in js   # Esc 先收菜单
    # 搜索键: 直进搜索页 + 聚焦输入框
    assert '$("#dock-search").addEventListener("click"' in js
    assert 'navigate("search");' in js and 'input.focus();' in js
    # iOS 聚焦小于 16px 的输入框会自动放大整页: 文本输入框全钉 16px
    for start, end in [(".search-box input {", ".search-box input::placeholder"),
                       (".settings-field > input {", ".settings-field > input:focus"),
                       (".picker-new input {", ".picker-new input::placeholder")]:
        assert "font-size: 16px;" in html[html.index(start):html.index(end)]
    # 扫描条照旧吊在船坞行上沿 (absolute 往上翻, 不挤布局)
    scan_css = html[html.index("#scan-strip {"):html.index("#scan-strip .dot")]
    assert "transform: translateY(-100%);" in scan_css
    assert 'id="scan-strip"' in html[html.index('<div id="dock">'):]
    # 一级页/推入层/提示的底部让位全走 --dock-clear (船坞一套账)
    assert "padding: 14px max(16px, env(safe-area-inset-right))\n           var(--dock-clear)" \
        in html
    assert "bottom: calc(var(--dock-h) + 22px + env(safe-area-inset-bottom));" \
        in html[html.index("#toast {"):]
    # 层动画期的重影对策罩住三件套 (透明船坞不罩, 罩磨砂子件); 实底是
    # 磨砂等效色 (1.8.1 立的规矩: 动画前后深浅一致; 1.8.3 底色调实一档,
    # 等效实底跟着重算)
    assert "body.pane-anim #mini-player," in html
    assert "body.pane-anim #dock-menu," in html
    assert "body.pane-anim #dock-search {" in html
    assert "background: rgb(34,34,36);" in html[
        html.index("body.pane-anim #mini-player"):html.index(".push-pane {")]


def test_music_top_fallback_removed():
    """顶栏黑罩/机型兜底全撤 (1.8.0 用户点名「任凭模糊, 不做处理」): iOS 26.1+
    系统磨砂带 bug (WebKit 301994, env 谎报 0) 的整套对策 —— JS 机型表/
    会话锁/探测, CSS --sys-top-inset 三处 max() 让位, 不透明黑罩
    #top-shield, 首帧 147px 兜底 —— 连脚本带样式一起撤净。
    1.8.1 折中回一小步: 常驻控件 (播放页抓手/搜索页输入框) 吃 --top-floor
    静态下限 (独立模式竖屏 96px, 其余恒 0 —— 不是机型探测, 滚动内容照旧
    纯 env「任凭糊」)。"""
    html = music_page_shell()
    js = music_browser_js()
    assert "top-shield" not in html
    assert "--sys-top-inset" not in html
    assert "SYS_TOP_INSETS" not in js and "sysTopLocked" not in js
    assert "syncSysTopInset" not in js
    assert "music-system-top-fallback" not in html
    assert not (MUSIC_STATIC / "js" / "music-system-top-fallback.js").exists()
    # 三处让位分两档 (1.8.1): 滚动内容 (main / 二级页顶衬) 仍是纯 env;
    # 常驻控件 (播放页抓手 / 搜索页输入框) 吃 --top-floor 下限 —— 独立
    # 模式系统磨砂带比安全区深一截 (env 谎报 0), 贴顶控件会被栅糊,
    # 96px 静态下限躲开强糊带 (不是机型探测, 浏览器/横屏/桌面恒 0)
    main_css = html[html.index("main {"):html.index("#root-view {")]
    assert "margin-top: env(safe-area-inset-top);" in main_css
    scroll_css = html[html.index(".push-pane .pane-scroll"):html.index(".album-hero")]
    assert "calc(env(safe-area-inset-top) + 14px)" in scroll_css
    assert "--top-floor: 0px;" in html \
        and "@media (display-mode: standalone) and (orientation: portrait)" in html
    grab_css = html[html.index("#fp-grab {"):html.index("#fp-grab span")]
    assert "margin-top: max(env(safe-area-inset-top, 0px), var(--top-floor));" in grab_css
    # 首帧兜底的独立模式媒体查询也撤了 (147px 黑罩那套, 别回来)
    assert "147px" not in html
    # 脚本清单随行: 42 个模块全带版本参数 (1.8.1: +recent-pane; 1.8.3: +search-pages)
    scripts = re.findall(r'<script src="([^"]+)"', html)
    assert len(scripts) == 42 and all("?v=" in src for src in scripts)
    assert "js/music-dock-menu.js?v=" in html
    assert "js/music-playlists-pane.js?v=" in html
    webapp_dir = Path(__file__).parent.parent / "app" / "music" / "webapp"
    webapp = "".join(path.read_text(encoding="utf-8")
                     for path in sorted(webapp_dir.glob("*.py")))
    assert "header-probe" not in webapp and "probe.jsonl" not in webapp
