"""My Music 播放器界面接线测试 (从 test_music.py 拆出, 该文件超 1600 行):
传输区/队列封面视图/返回手势收起/下载全部/更新日志应用内化 —— 都是
"静态文本断言"型测试 (读 html/js 源码查接线), 不碰数据库。
"""
from pathlib import Path


def test_music_controls_apple_style_wiring():
    """传输区最终形 (用户两连点名): 三键站在进度条**正上方**居中成一行,
    不是挤在进度条旁边; 三键一般大 (44×44, 播放键不再大一号);
    进度条 range 住在 flex 行里要 flex:1+min-width:0 才肯让位收缩。
    迷你气泡三键齐全 (上一首/播放/下一首)。图标包围盒中心对准按键中心的
    不变量在 player-icons.test.mjs。"""
    static = Path(__file__).parent.parent / "app" / "music" / "static"
    html = (static / "music.html").read_text(encoding="utf-8")
    common = (static / "music-common.js").read_text(encoding="utf-8")
    # 键行在进度行**上面** (markup 顺序即视觉顺序)
    assert html.index('<div class="fp-controls">') < html.index('<div class="fp-transport">')
    controls = html[html.index(".fp-controls {"):html.index(".fp-transport {")]
    assert "justify-content: center" in controls and "gap: 32px" in controls
    assert "width: 44px; height: 44px; color: #fff; padding: 0" in controls  # 三键一般大
    assert "#fp-play { width" not in html          # 播放键不再有大一号的覆盖
    transport = html[html.index(".fp-transport {"):html.index(".fp-actions {")]
    assert ".fp-scrub { flex: 1; min-width: 0; }" in transport  # range 让位收缩
    assert 'id="fp-time-cur"' in html and 'id="fp-time-total"' in html  # 时间标签还在
    assert 'width="30" height="30"' in html                       # 上下曲字形
    assert 'width="32" height="32"' in common                     # 播放/暂停只略大
    assert ".fp-times" not in html                                # 旧三行布局撤了
    assert ".fp-controls > button:active { transform: scale(.86)" in html  # 按压反馈
    assert "#fp-grab" in html                                 # 收起抓手
    # 迷你气泡三键: 上一首/播放/下一首 (用户点名"三个按键都需要")
    assert 'id="mini-prev"' in html and 'id="mini-play"' in html \
        and 'id="mini-next"' in html
    # 音量条整个撤了 (1.5.1, 用户点名): 音量交给设备音量键/系统音量
    assert "#fp-volume" not in html and ".fp-volume" not in html
    # 气泡磨砂玻璃 (用户点名): 六成底色配 blur(20), 底下划过的内容糊成
    # 影子透上来 —— 不是一块实心灰板 (88% 那种看不出磨砂)
    mini_css = html[html.index("#mini-player {"):html.index("#mini-progress")]
    assert "rgba(44,44,46,.6);" in mini_css
    assert "backdrop-filter: blur(20px) saturate(180%);" in mini_css
    # 气泡播放/暂停键大一号 (用户点名 "比上一首下一首还小"): 三角/双杠是
    # 紧凑实心形, 跟宽箭头同尺寸显得小 —— 28 对 24 才齐平; 撤掉旧补偿边距
    assert 'width="28" height="28"' in common
    assert "margin: 0 2px" not in html
    # 整个应用不画滚动条 (用户点名 "整个页面都不要"): 星规则管 Firefox,
    # 伪元素管 Chrome/Safari; iOS 本来就不画 —— 能滚, 只是不显示
    star_css = html[html.index("* {"):html.index("[hidden]")]
    assert "scrollbar-width: none;" in star_css
    assert "::-webkit-scrollbar { display: none; }" in html


def test_music_queue_cover_view_wiring():
    """播放队列 = 封面原地翻开的视图 (用户点名"不要弹队列, 用封面区域显示
    播放列表"): 头部一行 (待播放 + N 首歌曲 左, 随机/循环两枚键 右 —— 照
    Apple Music Playing Next 排版), 下面 upcoming 列表; 与歌词视图同住封面区
    互斥; 全屏页收起时跟着收。旧底部弹层 (queue-sheet/mask/close) 全撤。"""
    static = Path(__file__).parent.parent / "app" / "music" / "static"
    html = (static / "music.html").read_text(encoding="utf-8")
    player = (static / "music-player.js").read_text(encoding="utf-8")
    for frag in ['<div id="fp-queue" hidden>', 'class="fq-head"',
                 'class="fq-head-txt"', 'id="fq-count"',
                 'class="fq-head-btns"', 'id="fp-shuffle"', 'id="fp-repeat"',
                 'id="queue-list"', "#full-player.queue .fp-bg img"]:
        assert frag in html, f"队列视图缺 {frag}"
    assert "fq-modes" not in html                    # 旧顶排胶囊撤了
    assert "queue-sheet" not in html and "queue-mask" not in html \
        and "queue-close" not in html              # 旧弹层死透
    assert "queue-sheet" not in player and "queue-mask" not in player
    for frag in ["function toggleQueueView", "function closeQueueView",
                 "function renderQueueView", "let queueViewOpen = false;",
                 '$("#fp-queue-btn").addEventListener("click", toggleQueueView);',
                 "$(\"#queue-list\").innerHTML = upcoming.map",
                 '$("#fq-count").textContent = `${upcoming.length} 首歌曲`']:
        assert frag in player, f"music-player.js 缺 {frag}"
    # 行样式: 序号等宽数字 + 拖把不触发竖向滚动劫持 (touch-action 分层)
    for frag in [".queue-row {", ".q-num {", ".q-grip {", "touch-action: pan-y;",
                 "touch-action: none;"]:
        assert frag in html, f"队列行样式缺 {frag}"
    # 互斥: 开队列先收歌词, 开歌词先收队列; 收起播放页两个都收
    assert "if (lyricsViewOpen) toggleLyricsView();" in player
    assert "if (!lyricsViewOpen && queueViewOpen) closeQueueView();" in player


def test_music_queue_drag_wiring():
    """队列内拖拽换序 (用户点名"列表里的歌单可以被拖拽更换顺序"):
    位置数学在 player-queue.js 的 queueReorder (node 直测), 这里只验接线 ——
    把手按下即捕获指针, 行跟手位移让位, 松手按落点改 order 并存档;
    换过的顺序和随机/循环开关存进 localStorage, 恢复前先验 order 是完整
    排列 (缺/重/越界的旧档弃用, 随机旗只在顺序真恢复时才点亮)。"""
    static = Path(__file__).parent.parent / "app" / "music" / "static"
    html = (static / "music.html").read_text(encoding="utf-8")
    player = (static / "music-player.js").read_text(encoding="utf-8")
    common = (static / "music-common.js").read_text(encoding="utf-8")
    queue = (static / "player-queue.js").read_text(encoding="utf-8")
    # 拖动中的行浮起来 (阴影 + 免过渡): 拖把图标进 common, music-player 引用
    assert ".queue-row.dragging" in html
    assert "ICON_GRIP" in common and "const ICON_GRIP" in common
    assert "module.exports = {" in queue and "queueReorder," in queue
    for frag in ["function bindQueueDrag", "function finishQueueDrag",
                 "queueReorder(playQueue, base + drag.fromView, base + drag.target)",
                 "grip.setPointerCapture(event.pointerId)",
                 'event.target.closest(".q-grip")']:
        assert frag in player, f"music-player.js 缺 {frag}"
    assert 'event.target.closest(".q-grip")' in player  # 拖把点击不当选曲
    assert "bindQueueDrag();" in player                 # 挂进事件绑定
    # 存档: order (截 500) + position 一起进 player state
    assert "order: playQueue.order.slice(0, 500)," in player
    assert "saved.order" in player and "orderRestored" in player
    assert "new Set(saved.order).size === saved.tracks.length" in player  # 排列校验


def test_music_share_link_wiring():
    """分享改链接制 (1.7.0, 用户点名"单独生成一个 uuid 的 url, 有效期 1 天,
    不用鉴权"): 开 24 小时免登录链接, 系统分享面板优先、复制回落;
    公开页 share.html 自包含 (不引应用 JS —— 访客没有会话)。"""
    static = Path(__file__).parent.parent / "app" / "music" / "static"
    js = (static / "music.js").read_text(encoding="utf-8")
    share = (static / "share.html").read_text(encoding="utf-8")
    for frag in ["async function shareByLink",
                 'fetchJSON("/music/api/shares"',
                 "async function sharePlaylist", 'id="playlist-share"',
                 "24 小时内有效"]:
        assert frag in js, f"music.js 分享缺 {frag}"
    # 公开页: 拿 uuid 换数据 → 流地址播放, 失效态/滑进度/iOS 兜底都在
    for frag in ["/music/share/${token}/api",
                 "/music/share/${token}/stream/${track.track_id}",
                 "链接不存在或已过期", "playsinline",
                 "fmtDateTime", "playQueue", "togglePlay"]:
        assert frag in share, f"share.html 缺 {frag}"
    assert "music.js?v=" not in share      # 自包含, 不引应用脚本
    # 整页不画滚动条 (与应用同款: 星规则 + 伪元素)
    assert "scrollbar-width: none;" in share
    assert "::-webkit-scrollbar { display: none; }" in share
    # 全屏播放页 (用户点名"和 app 自己的播放界面大致一样"): 点迷你条掀开,
    # 封面点一下 ↔ 歌词 (近邻模糊同款), 传输三键 + 进度 + 毛玻璃底 +
    # 下拉收起; 歌词解析借公开的 lyrics-parser.js (纯模块, 不带会话)
    for frag in ['id="fp"', 'id="fp-play"', 'id="fp-prev"', 'id="fp-next"',
                 'id="fp-lyrics"', 'id="fp-scrub"', 'id="fp-grab"',
                 'id="fp-bg"', "toggleLyricsView", "openFullPlayer",
                 "closeFullPlayer", "bindPullClose", "updateMediaSession",
                 "/music/share/${token}/lyrics/${track.track_id}",
                 'src="/music/static/lyrics-parser.js"',
                 ".lyrics-line.near-1", ".lyrics-line.active"]:
        assert frag in share, f"share.html 缺 {frag}"
    # 微信卡片: <head> 留 og 占位注释, 服务端换掉 (占位符漏替换卡片就漏空)
    assert "<!--og-->" in share
    webapp = (Path(__file__).parent.parent / "app" / "music"
              / "webapp.py").read_text(encoding="utf-8")
    assert '_OG_MARK = "<!--og-->"' in webapp
    assert '"/share/{token}/lyrics/{track_id}"' in webapp
    # 分享页对整站是公开前缀 (中间件只认这个面, 过期由路由自己验)
    main_py = (Path(__file__).parent.parent / "app" / "main.py").read_text(
        encoding="utf-8")
    assert '_PUBLIC_PREFIXES = ("/music/share/",)' in main_py


def test_music_swipe_delete_wiring():
    """左滑删除 (用户点名两处: 列表内曲目移出 + 主页列表整列删): iOS 同款
    红色删除钮。与长按菜单共存 (阈值分家), 滚动让位 (touch-action pan-y +
    捕获 scroll 即收), 尾随 click 吞掉, 同一时间只开一行。"""
    static = Path(__file__).parent.parent / "app" / "music" / "static"
    html = (static / "music.html").read_text(encoding="utf-8")
    js = (static / "music.js").read_text(encoding="utf-8")
    for frag in [".swipe-wrap {", ".swipe-del {", "touch-action: pan-y;"]:
        assert frag in html, f"左滑样式缺 {frag}"
    assert "#e5484d" in html                          # 删除钮红底
    for frag in ["const SWIPE_REVEAL = 72;",
                 "function closeSwipeRow", "function bindSwipeDelete",
                 'document.addEventListener("scroll", closeSwipeRow, true)',
                 'data-swipe-track=', 'data-swipe-playlist=',
                 "swipeSuppressClick",
                 '`/music/api/playlists/${playlistId}/tracks/${trackId}`']:
        assert frag in js, f"music.js 缺 {frag}"
    # 两处挂载: 列表详情的曲目行 + 主页的列表行
    assert 'bindSwipeDelete(target.querySelector("#playlist-tracks")' in js
    assert 'bindSwipeDelete($("#home-playlists")' in js
    # 手势地盘分家 (1.7.0 后遗症修): 左滑只认左移 (右移归推入层返回手势,
    # 抢了会被 pointercancel 掐弹回); 左缘 24px 让给 iOS 系统边缘返回
    assert "swipeDrag.horizontal = dx < 0 && Math.abs(dx) > Math.abs(dy);" in js
    # 左缘返回的归属 (用户点名两轮 preventDefault 拦截, iPhone Safari 实测
    # 都掐不住系统手势, 终版撤净): 苹果把屏幕最边一条握在系统手里, 网页
    # 收不到那片触摸 (Navigation API 的 traverse 取消也未实现) —— 应用
    # 自己的右滑从页面任意位置起手; 别再往 document 挂 touchstart 拦截,
    # 那只剩左缘一小条不能起手滚动的副作用
    assert "standaloneLaunch" not in js
    assert "EDGE_STRIP_PX" not in js
    assert 'document.addEventListener("touchstart"' not in js
    assert 'document.addEventListener("touchend"' not in js
    # 拖动跟手: 行上挂 .swiping 撤掉 transform 过渡, 松手回位才交给过渡
    # (不撤的话每帧都在重定 250ms 补间, 手指拖着行像皮筋 —— 队列拖拽同款)
    assert 'swipeDrag.row.classList.add("swiping")' in js
    assert ".swipe-wrap > button:first-child.swiping { transition: none; }" in html
    # 删除钮的点击走捕获层 (}, true); 行自己的冒泡 click 处理器看不到它
    assert 'container.addEventListener("click", async (event) => {' in js
    assert "}, true);" in js


def test_music_pane_fixed_chrome_wiring():
    """页签栏/气泡在滚动和切页全程钉死 (用户点名两轮: 切页时不在一个图层 +
    滑动过程中也保持不动)。两层手段: ① 固定壳 —— html/body 锁高锁滚,
    文档永不滚 (iPhone 工具栏只跟文档滚动收放, 文档不滚视口恒定,
    钉视口的页签栏/气泡物理上无从移动), main 变内部滚动器; ② 全高推入层
    (z44) 从毛玻璃页签栏 (z50)/气泡 (z45) 底下扫过, 内容顶上用
    env(safe-area-inset-top) 让位 (顶栏撤了, 不再要 JS 量高度)。
    层铺满全高 (设计一致, 用户点名: 气泡底下要有内容, 和主页
    一样) —— 重影对策挪到运动期: body.pane-anim 暂撤气泡/页签栏磨砂换实底
    (fixed+backdrop-filter 底下有扫动的变换层是 WebKit 的重影配方)。
    根视图渲染目标 #root-view (main 是滚动器, 直写会抹掉内容)。"""
    static = Path(__file__).parent.parent / "app" / "music" / "static"
    html = (static / "music.html").read_text(encoding="utf-8")
    js = (static / "music.js").read_text(encoding="utf-8")
    # 壳: 文档不滚, main 是唯一一级滚动器
    assert "height: 100%; overflow: hidden;" in html            # html
    assert "height: 100dvh;" in html and "overflow: hidden;" in html  # body
    main_css = html[html.index("main {"):html.index("#root-view {")]
    assert "min-height: 0;" in main_css and "overflow-y: auto;" in main_css
    assert "-webkit-overflow-scrolling: touch;" in main_css
    # 顶部雷区让位 (顶栏发糊同源): main 整个下移, 滚动内容永远进不了那条带子
    # —— 只给内容加 padding 的话, 一滚字就又钻进去 (2026-09-16 用户复测四个
    # 一级页页顶全被栅糊+切出屏幕, 就是因为 root-view 顶衬是写死的 14px)。
    # max(env, 兜底): iOS 26.1+ 系统 bug (WebKit 301994, 用户已升 iOS 27)
    # 把 env 误报 0, music.js 的 --sys-top-inset 按机型兜底
    assert "margin-top: max(env(safe-area-inset-top), var(--sys-top-inset, 0px));" \
        in main_css
    root_css = html[html.index("#root-view {"):html.index(".push-pane {")]
    assert "max-width: 860px; margin: 0 auto;" in root_css
    assert "calc(var(--tabbar-h) + 90px + env(safe-area-inset-bottom))" in root_css
    assert "max(16px, env(safe-area-inset-right))" in root_css  # 横屏让开侧刘海
    assert "max(16px, env(safe-area-inset-left))" in root_css
    assert html.index('<main id="main">') < html.index('<div id="root-view">') \
        < html.index("</main>") < html.index('<nav id="tabbar">')
    # 一级页滚动/渲染都走 main/#root-view, 文档滚动彻底退出
    assert '$("#main").scrollTop = pageState.rootScroll;' in js
    assert 'pageState.rootScroll = $("#main").scrollTop;' in js
    assert "window.scrollY" not in js
    assert '$("#root-view").innerHTML' in js
    assert "window.scrollTo" not in js
    # 推入层铺满全高: 顶上一直铺到屏顶 (顶栏撤了, env 让开刘海), 底下从磨砂
    # 气泡/页签栏底下过 (设计一致, 用户点名"气泡下面要有内容")
    pane_css = html[html.index(".push-pane {"):html.index(".push-pane .pane-scroll")]
    assert "top: 0;" in pane_css
    assert "bottom: 0;" in pane_css
    # 收层方向的加固 (用户回访: 进层不重影了, 返回时气泡跟着二级页跑):
    # ① 层终身常驻不降级 —— 动画结束的合并瞬间 WebKit 会把旁边固定元素
    #    复印进合并层; ② 投影收紧竖向渗出 —— 磨砂取样区比气泡本体外扩
    #    blur(20), 投影渗进取样区也是重影引子
    assert "will-change: transform;" in pane_css
    assert "box-shadow: -10px 0 26px -8px" in pane_css
    # ③ 气泡自家合成层: 任何邻居的变换/合并都复印不到它
    mini_css = html[html.index("#mini-player {"):html.index("#mini-progress")]
    assert "transform: translateZ(0);" in mini_css
    # 页签栏同款护甲 (和气泡一样是 fixed 常驻件, 邻居层动起来时防复印)
    tabbar_css = html[html.index("#tabbar {"):html.index("#tabbar .tab-row")]
    assert "transform: translateZ(0);" in tabbar_css
    # 泳道撤了 (层铺满全高, 没有夹缝可露); 重影对策 = 运动期暂撤磨砂:
    # CSS 挂 body.pane-anim 实底 (气泡和页签栏两条一起), JS 的 paneMotion()
    # 在每段层运动前打标 (拖动中每下续期), 停稳 500ms 恢复
    assert "#push-stack::after" not in html
    assert "body.pane-anim #mini-player, body.pane-anim #tabbar" in html
    assert "backdrop-filter: none;" in html
    assert "function paneMotion" in js
    open_pane = js[js.index("function openPushPane"):js.index("function closePushStack")]
    assert "paneMotion();" in open_pane
    assert "lockRootScroll()" in open_pane
    close_stack = js[js.index("function closePushStack"):
                     js.index("function bindPaneSwipe")]
    assert "paneMotion();" in close_stack
    swipe = js[js.index("function bindPaneSwipe"):
               js.index("// ------------------------------------------------------------ 下载 (离线)")]
    assert swipe.count("paneMotion();") >= 4   # 拖动续期/滑出/弹回/取消
    scroll_css = html[html.index(".push-pane .pane-scroll"):
                      html.index(".seg {")]
    # 顶上让位纯 CSS (顶栏撤了, env 直读; 独立模式 black-translucent 下拿
    # 得到真实刘海高度), 底下让开气泡+页签栏 —— JS 量高度那套 (syncPaneTop/
    # --pane-top/headerBottom) 整个退役。env 被 iOS 26.1+/27 系统 bug 报 0 的
    # 场合由 --sys-top-inset 兜底 (见 test_music_sys_top_fallback)
    assert "calc(max(env(safe-area-inset-top), var(--sys-top-inset, 0px)) + 14px)" \
        in scroll_css
    assert "calc(var(--tabbar-h) + 90px + env(safe-area-inset-bottom))" in scroll_css
    assert "function syncPaneTop" not in js
    assert '"--pane-top"' not in js
    assert "headerBottom" not in js
    assert 'pane.innerHTML = \'<div class="pane-scroll"></div>\'' in open_pane


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
    static = Path(__file__).parent.parent / "app" / "music" / "static"
    html = (static / "music.html").read_text(encoding="utf-8")
    js = (static / "music.js").read_text(encoding="utf-8")
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
    assert "--tabbar-h: 44px;" in tabbar_css
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
    webapp = (Path(__file__).parent.parent / "app" / "music"
              / "webapp.py").read_text(encoding="utf-8")
    schemas = (Path(__file__).parent.parent / "app" / "music"
               / "schemas.py").read_text(encoding="utf-8")
    assert "header-probe" not in webapp and "probe.jsonl" not in webapp
    assert "HeaderProbeReport" not in schemas and "HeaderProbeReport" not in webapp


def test_music_sys_top_fallback():
    """iOS 26.1+/27 顶带 bug 的兜底 (2026-09-16): 苹果系统在主屏应用顶部盖
    一条 DOM 够不着的磨砂带, 且 env(safe-area-inset-top) 被误报成 0
    (WebKit 301994, 26.5.2/27 复发; 用户手机已升 iOS 27)。env 失效后所有
    CSS 顶部让位全废 —— JS 在独立模式+竖屏+iPhone+系统没代推 (innerHeight
    没被吃) 的场合, 按机型屏幕尺寸表把近似刘海高度写进 --sys-top-inset,
    CSS 三处让位 (main/二级页顶衬/播放页抓手) 全部 max(env, 兜底)。
    顺带一条排查期读数条 (#sys-debug), 拿到用户真值就撤。"""
    static = Path(__file__).parent.parent / "app" / "music" / "static"
    html = (static / "music.html").read_text(encoding="utf-8")
    js = (static / "music.js").read_text(encoding="utf-8")
    # 三处让位都收兜底变量 (缺一处 = 那个界面照钻磨砂带)
    main_css = html[html.index("main {"):html.index("#root-view {")]
    assert "margin-top: max(env(safe-area-inset-top), var(--sys-top-inset, 0px));" \
        in main_css
    scroll_css = html[html.index(".push-pane .pane-scroll"):html.index(".seg {")]
    assert "calc(max(env(safe-area-inset-top), var(--sys-top-inset, 0px)) + 14px)" \
        in scroll_css
    grab_css = html[html.index("#fp-grab {"):html.index("#fp-grab div")]
    assert "calc(max(env(safe-area-inset-top, 0px), var(--sys-top-inset, 0px)) + 3px)" \
        in grab_css
    # 兜底只在「独立模式 + 竖屏 + iPhone + env 报 0 + 系统没代推」时启动:
    # 浏览器/健康 iOS 里 --sys-top-inset 恒 0, env 原样生效
    block = js[js.index("const SYS_TOP_INSETS"):js.index("bindGlobalEvents();")]
    assert "375x812" in block and "440x956" in block      # 机型表覆盖两代刘海
    assert 'matchMedia("(display-mode: standalone)").matches' in block
    assert 'matchMedia("(orientation: portrait)").matches' in block
    assert "screen.height - innerHeight > 40" in block     # 系统代推的场合不兜
    assert "document.documentElement.style.setProperty" in block
    assert '"--sys-top-inset"' in block
    # env 用 DOM 探针量 (fixed 元素高 = env 值), 量完即撤
    assert "height:env(safe-area-inset-top)" in block and "probe.remove();" in block
    # 冷启动 env 可能晚到: 启动即算, +800ms/+2500ms 再算 (晚到的真值经
    # max() 无缝接手), 旋转/resize 也重算
    assert "syncSysTopInset();" in block
    assert block.count("setTimeout(syncSysTopInset") == 2
    assert "addEventListener(\"orientationchange\", syncSysTopInset);" in block
    # 排查期读数条: 挂在 body 上, 独立/浏览器、env/兜底、屏幕尺寸都报
    assert 'chip.id = "sys-debug"' in block
    assert "envT=" in block and "屏${screen.width}x${screen.height}" in block
    debug_css = html[html.index("#sys-debug {"):html.index("}\n", html.index("#sys-debug {"))]
    assert "pointer-events: none;" in debug_css   # 只读不挡


def test_music_player_dismiss_wiring():
    """播放页的收起路径 (1.7.0 单地址批): 下拉/Esc 向下收, 抓手条横拖右甩
    向右收 —— 全是纯视图开关, 不再挂历史条目 (一个地址批后浏览器里没有
    可退的条目, 播放页也跟着撤了 pushState/popstate 那套)。
    电脑上的"返回"是 Esc: 先收播放页, 没开就收顶层二级页。"""
    static = Path(__file__).parent.parent / "app" / "music" / "static"
    html = (static / "music.html").read_text(encoding="utf-8")
    player = (static / "music-player.js").read_text(encoding="utf-8")
    js = (static / "music.js").read_text(encoding="utf-8")
    assert "#full-player.dismiss-right { transform: translateX(100%); }" in html
    # 历史耦合撤净: 播放页开关不再碰 pushState/back/popstate
    assert "pushState" not in player and "history.back" not in player
    assert "popstate" not in player and "poppingPlayerEntry" not in player
    assert 'closeFullPlayer("right")' in player    # 抓手横拖的甩出收起
    assert 'if (direction === "right") fullPlayer.classList.add("dismiss-right")' \
        in player
    # 抓手条横拖收起: bindDismissDrag 第三个参数开启, 拖整页不是拖封面
    assert "horizontalClose = false" in player
    assert 'player.style.transform = dx > 0 ? `translateX(${dx * 0.92}px)` : "";' \
        in player
    assert 'bindDismissDrag($("#fp-grab"), false, true);' in player
    assert 'bindDismissDrag($("#fp-art-wrap"), true);' in player   # 封面照旧划切歌
    # Esc = 电脑上的返回: 先收播放页, 没开收顶层二级页
    esc_handler = js[js.index('event.key !== "Escape"'):
                     js.index("// ------------------------------------------------------------ 蜂窝流量")]
    assert "if (playerOpen) closeFullPlayer();" in esc_handler
    assert "closePushStack(pushStack.length - 1)" in esc_handler


def test_music_single_url_navigation_wiring():
    """单地址导航 (用户点名: 列表和主页就是一个页面, 进播放列表只是内容
    变化, 不存在网页切换): 导航目标只活在内存里 (根视图 + 层栈), 全程
    不碰 location.hash / pushState / history.back —— 浏览器返回/前进和
    iOS 系统侧滑在应用里没有条目可退, 整页截图滑走 (气泡跟着跑) 绝迹。
    旧深链开局消化一次, URL 随即洗成光杆 /music。"""
    static = Path(__file__).parent.parent / "app" / "music" / "static"
    js = (static / "music.js").read_text(encoding="utf-8")
    player = (static / "music-player.js").read_text(encoding="utf-8")
    # 不写 hash、不挂 hashchange、不加/弹历史条目 (认调用形式 —— 文件头
    # 注释里提到这些词是说明, 不算数)
    assert "location.hash =" not in js
    assert "hashchange" not in js
    assert "pushState(" not in js and "history.back(" not in js
    assert "pushState(" not in player and "history.back(" not in player
    # 目标从状态派生: 有层看顶层, 没层看根视图
    assert "function parseRoute" in js and "function currentRoute" in js
    assert "function syncViewTabs" in js
    # 开局: 旧深链消化一次 → replaceState 洗 URL (不加条目) → 状态开局
    assert 'const legacyHash = location.hash.replace(/^#\\/?/, "");' in js
    assert 'history.replaceState(null, "", location.pathname + location.search);' \
        in js
    assert "navigate(legacyTarget);" in js
    # 页签点亮同步: 进层全灭; 层收尽 (按钮收/右划收都要) 回到根视图
    assert "syncViewTabs(pageState.rootView);" in js
    downloads_header = "// ------------------------------------------------------------ 下载 (离线)"
    close_stack = js[js.index("function closePushStack"):js.index(downloads_header)]
    assert "syncViewTabs(pageState.rootView);" in close_stack
    assert "syncViewTabs(view);" in js[js.index("function routeTo"):]


def test_music_download_all_wiring():
    """「下载全部」(用户点名: 播放列表/专辑详情页): 顺序一首首下
    (几十个 40MB 并发请求在手机上必炸), 已在库/正在下的跳过,
    下载管理「全部删除」把整批叫停。列表页操作行 1.7.0 起改纯图标
    (播放/随机/下载/分享/删除 五枚一般大, 一行装下不再换行)。"""
    static = Path(__file__).parent.parent / "app" / "music" / "static"
    html = (static / "music.html").read_text(encoding="utf-8")
    js = (static / "music.js").read_text(encoding="utf-8")
    assert 'id="album-download"' in js and "下载全部" in js
    assert 'id="playlist-download"' in js
    for frag in ["function downloadAllFromUI", "let downloadAllCancelled = false;",
                 "await downloads.downloadTrack(track)",   # 顺序 (await 在循环里)
                 "downloadAllCancelled = true;"]:
        assert frag in js, f"music.js 缺 {frag}"
    # 操作行纯图标: 五枚 .action.icon 齐全 (有 title 无文字), 单行居中
    for frag in ['class="action icon primary" id="playlist-play"',
                 'id="playlist-shuffle"', 'id="playlist-download"',
                 'id="playlist-share"', 'id="playlist-delete"']:
        assert frag in js, f"操作行缺 {frag}"
    assert ".action.icon {" in html and ".action.icon svg {" in html


def test_music_changelog_in_app_wiring():
    """更新日志改应用内视图 (用户点名"看日志别断歌"): 原来是整页跳转
    /music/changelog, 卸载 SPA 音频就停; 改 hash 路由铺在 #main,
    播放气泡常驻。入口在设置页「更多」段 (顶栏菜单撤了)。独立日志页
    保留 (直达链接仍可用)。"""
    static = Path(__file__).parent.parent / "app" / "music" / "static"
    html = (static / "music.html").read_text(encoding="utf-8")
    js = (static / "music.js").read_text(encoding="utf-8")
    assert 'data-set-nav="changelog"' in js          # 设置页「更多」段的入口
    assert 'href="/music/changelog"' not in html    # 不再整页跳走
    assert ('if (["home", "library", "search", "stats", "settings", "changelog"]'
            '.includes(name)) {') in js
    assert "function renderChangelogView()" in js
    assert 'fetchJSON("/music/changelog/api/entries")' in js
    assert "#changelog-entries" in html and ".v-badge" in html  # 版本卡片样式
    assert 'navigate(row.dataset.setNav)' in js     # 更多段的行都是导航入口
