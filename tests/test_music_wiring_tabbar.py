"""My Music 底栏接线测试: 底部页签栏 (1.7.0) + iOS 独立模式顶部
安全区兜底 —— 静态文本断言, 不碰数据库。
拆自 test_music_wiring.py (结构化重构, 代码逐字节未动)。"""
from pathlib import Path

from tests.music_static_files import music_browser_js, music_page_shell


def test_music_bottom_tabbar_wiring():
    """导航搬到底部: 原顶部页签栏在独立 app (主屏图标) 竖屏里整条被 iOS 栅
    成低清 (用户实测: 钉自家合成层/撤磨砂/换状态栏样式三招全救不动; 横屏
    和浏览器里都好, 屏底的气泡一直清晰) —— 干脆把导航挪到底部, 顶上那块
    雷区整个让出去。主页/资料库/搜索/设置四键全带图标, 钉死视口底,
    磨砂配方与气泡同款; 气泡叠在页签栏上面。原品牌菜单的职能全进设置页
    (账号/退出/重扫/统计/更新日志)。顶栏相关的临时手段 (body.standalone
    撤磨砂 + header-probe 探针 + 测试条) 连前端带后端一起撤净。
    页签栏压扁一档 (51→44px); 双指缩放全禁 (body pan-y) + 文本输入框
    16px 防 iOS 聚焦自动放大 (搜索/设置/新列表名/登录页)。"""
    html = music_page_shell()
    js = music_browser_js()
    # 顶栏整个没了, 换固定壳底的页签栏
    assert "<header>" not in html and "header {" not in html
    assert ".brand-menu" not in html and "brand-menu" not in js
    assert "menu-user.js" not in html          # 菜单没了, 全站小件没落脚点
    tabbar_css = html[html.index("/* ---------- 底部页签栏"):
                      html.index("/* ---------- 扫描进度条")]
    assert "position: fixed; left: 0; right: 0; bottom: 0; z-index: 50;" \
        in tabbar_css
    assert "rgba(44,44,46,.6);" in tabbar_css            # 磨砂配方与气泡同款
    assert "backdrop-filter: blur(20px) saturate(180%);" in tabbar_css
    assert "env(safe-area-inset-bottom)" in tabbar_css   # 让开小白条
    assert "env(safe-area-inset-left)" in tabbar_css     # 横屏让开圆角
    assert "--tabbar-h: 38px;" in tabbar_css
    assert "color: var(--accent);" in tabbar_css         # 点亮页签吃苹果红
    # 双指缩放全禁: 列表行 pan-y 本来就捏不动, 页签栏/气泡原来能捏大 — body 收口
    body_css = html[html.index("body {"):html.index("button {")]
    assert "touch-action: pan-y;" in body_css
    # iOS 聚焦小于 16px 的输入框会自动放大整页: 三处文本输入框全钉 16px
    for start, end in [(".search-box input {", ".search-box input::placeholder"),
                       (".settings-field > input {", ".settings-field > input:focus"),
                       (".picker-new input {", ".picker-new input::placeholder")]:
        assert "font-size: 16px;" in html[html.index(start):html.index(end)]
    # 四键全带图标 (iconfont 素材, currentColor 吃点亮色) + 顺序
    tabbar_html = html[html.index('<nav id="tabbar">'):html.index("</nav>")]
    for name, label in [("home", "主页"), ("library", "资料库"),
                        ("search", "搜索"), ("settings", "设置")]:
        assert f'data-view-tab="{name}"><svg' in tabbar_html
        assert f"<span>{label}</span>" in tabbar_html
    assert tabbar_html.count("<svg") == 4
    assert tabbar_html.count('fill="currentColor"') >= 4
    # 气泡叠在页签栏上, 底偏移按页签栏高算 (两处共用 --tabbar-h)
    mini_css = html[html.index("#mini-player {"):html.index("#mini-progress")]
    assert "bottom: calc(var(--tabbar-h) + env(safe-area-inset-bottom) + 8px);" \
        in mini_css
    # 扫描条吊在页签栏的上沿 (absolute 往上翻, 不挤布局)
    scan_css = html[html.index("#scan-strip {"):html.index("#scan-strip .dot")]
    assert "transform: translateY(-100%);" in scan_css
    assert 'id="scan-strip"' in html[html.index('<nav id="tabbar">'):]
    # 页签点击绑在 #tabbar, 搜索页签顺手聚焦输入框
    assert '$("#tabbar").addEventListener' in js
    assert 'button.dataset.viewTab !== "search"' in js
    # 状态栏样式回到全出血: 顶栏没了, env(safe-area-inset-top) 只剩二级页
    # 顶上让位在用, black 会让独立模式报 0
    assert 'name="apple-mobile-web-app-status-bar-style"' \
           ' content="black-translucent"' in html
    # 独立模式打标/撤磨砂那套连标记一起撤 (页签栏在底部, 不再需要);
    # 文档注释里的 standalone 字样是正当说明, 断言认检测调用本身。
    # matchMedia("(display-mode: standalone)") 2026-09-16 起合法回归:
    # iOS 27 顶带兜底要用它识别主屏独立模式 (见 test_music_sys_top_fallback)
    assert "body.standalone" not in html
    assert "navigator.standalone" not in js
    assert 'classList.add("standalone")' not in js
    # 原菜单职能进设置页: 账号行 + 退出登录 + 重新扫描 + 统计/更新日志入口
    assert 'data-set-nav="stats"' in js
    assert 'data-set-nav="changelog"' in js
    assert 'id="set-logout"' in js and 'id="set-rescan"' in js
    settings_view = js[js.index("async function renderSettingsView"):
                       js.index("function monthRowHTML")]
    assert '"/music/api/logout"' in settings_view
    assert '"/music/api/rescan"' in settings_view
    assert "更多" in settings_view and "退出登录" in settings_view
    # 排查期的探针 (前端上报 + 后端接口 + 模型) 全撤净
    assert "header-probe" not in js
    assert "测试条" not in js
    webapp_dir = Path(__file__).parent.parent / "app" / "music" / "webapp"
    webapp = "".join(
        path.read_text(encoding="utf-8")
        for path in sorted(webapp_dir.glob("*.py")))
    schemas_dir = Path(__file__).parent.parent / "app" / "music" / "schemas"
    schemas = "".join(
        path.read_text(encoding="utf-8")
        for path in sorted(schemas_dir.glob("*.py")))
    assert "header-probe" not in webapp and "probe.jsonl" not in webapp
    assert "HeaderProbeReport" not in schemas and "HeaderProbeReport" not in webapp


def test_music_sys_top_fallback():
    """iOS 26.1+/27 顶带 bug 的兜底 (2026-09-16): 苹果系统在主屏应用顶部盖
    一条 DOM 够不着的磨砂带, 且 env(safe-area-inset-top) 被误报成 0
    (WebKit 301994, 26.5.2/27 复发; 用户手机已升 iOS 27)。env 失效后所有
    CSS 顶部让位全废 —— JS 在独立模式+竖屏+iPhone 的场合按变体兜高度写进
    --sys-top-inset (盖磨砂型: 机型表+磨砂深度; 推下型: 推下量+渗边),
    CSS 三处让位 (main/二级页顶衬/播放页抓手) 全部 max(env, 兜底)。
    让位区再铺一块不透明黑罩 (#top-shield): 磨砂盖纯黑 = 隐形, 滚进顶部
    的内容只会被罩子干净遮住; 推下型里系统抓拍条里也只剩黑罩, 残影隐形。"""
    html = music_page_shell()
    js = music_browser_js()
    # 三处让位都收兜底变量 (缺一处 = 那个界面照钻磨砂带)
    main_css = html[html.index("main {"):html.index("#root-view {")]
    assert "margin-top: max(env(safe-area-inset-top), var(--sys-top-inset, 0px));" \
        in main_css
    scroll_css = html[html.index(".push-pane .pane-scroll"):html.index(".seg {")]
    assert "calc(max(env(safe-area-inset-top), var(--sys-top-inset, 0px)) + 14px)" \
        in scroll_css
    grab_css = html[html.index("#fp-grab {"):html.index("#fp-grab span")]
    assert "calc(max(env(safe-area-inset-top, 0px), var(--sys-top-inset, 0px)) + 3px)" \
        in grab_css
    # 兜底分变体 (只在「独立模式 + 竖屏 + iPhone」里启动, 浏览器/健康
    # iOS 里 --sys-top-inset 恒 0, env 原样生效):
    #   盖磨砂型 (env=0): 机型表 + SYS_FROST_EXTRA;
    #   推下型 (push>40): 推下量 + SYS_PUSH_BLEED, 让黑罩盖过整条系统带
    #     (带子里是系统从网页顶部抓拍的画面, 罩子够高 = 抓拍条只剩纯黑)。
    # 会话锁只锁在中招变体里: env 抖回真值不撤兜底; 横屏/浏览器立即清零
    # (锁着进横屏会把竖屏兜底高度带过去, 顶部凭空让出一大截)。
    block = js[js.index("const SYS_TOP_INSETS"):js.index("bindGlobalEvents();")]
    assert "SYS_FROST_EXTRA = 88" in block
    assert "SYS_PUSH_BLEED = 16" in block
    assert "return inset + SYS_FROST_EXTRA;" in block
    assert "375x812" in block and "440x956" in block      # 机型表覆盖两代刘海
    assert 'matchMedia("(display-mode: standalone)").matches' in block
    assert 'matchMedia("(orientation: portrait)").matches' in block
    assert "const push = screen.height - innerHeight;" in block
    assert "if (push > 40) {" in block
    assert "target = push + SYS_PUSH_BLEED;" in block
    assert "if (target) sysTopLocked = target;" in block
    assert "else if (!eligible) sysTopLocked = 0;" in block
    assert "document.documentElement.style.setProperty" in block
    assert '"--sys-top-inset"' in block
    # env 用 DOM 探针量 (fixed 元素高 = env 值), 量完即撤
    assert "height:env(safe-area-inset-top)" in block and "probe.remove();" in block
    # 冷启动 env 可能晚到: 启动即算, +800ms/+2500ms 再算 (晚到的真值经
    # max() 无缝接手), 旋转/resize/回前台也重算
    assert "syncSysTopInset();" in block
    assert block.count("setTimeout(syncSysTopInset") == 2
    assert "addEventListener(\"orientationchange\", syncSysTopInset);" in block
    assert "visibilitychange" in block
    # 会话锁声明还在 (锁语义的断言在变体块里)
    assert "let sysTopLocked = 0;" in block
    # 排查期读数条 (#sys-debug) 已撤 (用户点名): 拿到真值收工, 别再挂绿字
    assert "sys-debug" not in js and "#sys-debug" not in html
    # 不透明黑罩: 高度与三处让位同源 (max(env, 兜底)), 盖在一切内容之上、
    # 菜单之下; 健康设备里只到状态栏下缘, 桌面上恒 0 不渲染
    shield_css = html[html.index("#top-shield {"):html.index("}\n", html.index("#top-shield {"))]
    assert "position: fixed; top: 0; left: 0; right: 0;" in shield_css
    assert "height: max(env(safe-area-inset-top), var(--sys-top-inset, 0px));" in shield_css
    assert "background: #000;" in shield_css
    assert "z-index: 96;" in shield_css
    assert '<div id="top-shield" aria-hidden="true"></div>' in html
