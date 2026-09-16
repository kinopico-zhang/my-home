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
    """顶栏/气泡在滚动和切页全程钉死 (用户点名两轮: 切页时不在一个图层 +
    滑动过程中也保持不动)。两层手段: ① 固定壳 —— html/body 锁高锁滚,
    文档永不滚 (iPhone 工具栏只跟文档滚动收放, 文档不滚视口恒定,
    钉视口的顶栏/气泡物理上无从移动), main 变内部滚动器, 顶栏 (sticky
    z50) 住进 main 钉在滚动器口; ② 全高推入层 (z44) 从毛玻璃顶栏
    (z50)/气泡 (z45) 底下扫过, 内容用 --pane-top (JS 量 headerBottom)
    让位。层铺满全高 (设计一致, 用户点名: 气泡底下要有内容, 和主页
    一样) —— 重影对策挪到运动期: body.pane-anim 暂撤气泡磨砂换实底
    (fixed+backdrop-filter 底下有扫动的变换层是 WebKit 的重影配方)。
    根视图渲染目标 #root-view (main 是滚动器, 直写会抹掉顶栏)。"""
    static = Path(__file__).parent.parent / "app" / "music" / "static"
    html = (static / "music.html").read_text(encoding="utf-8")
    js = (static / "music.js").read_text(encoding="utf-8")
    # 壳: 文档不滚, main 是唯一一级滚动器, 顶栏住 main 里
    assert "height: 100%; overflow: hidden;" in html            # html
    assert "height: 100dvh;" in html and "overflow: hidden;" in html  # body
    main_css = html[html.index("main {"):html.index("#root-view {")]
    assert "min-height: 0;" in main_css and "overflow-y: auto;" in main_css
    assert "-webkit-overflow-scrolling: touch;" in main_css
    root_css = html[html.index("#root-view {"):html.index(".push-pane {")]
    assert "max-width: 860px; margin: 0 auto;" in root_css
    assert "calc(90px + env(safe-area-inset-bottom))" in root_css
    assert html.index('<main id="main">') < html.index("<header>") \
        < html.index('<div id="root-view">') < html.index("</main>")
    # 一级页滚动/渲染都走 main/#root-view, 文档滚动彻底退出
    assert '$("#main").scrollTop = pageState.rootScroll;' in js
    assert 'pageState.rootScroll = $("#main").scrollTop;' in js
    assert "window.scrollY" not in js
    assert '$("#root-view").innerHTML' in js
    assert "window.scrollTo" not in js
    # 推入层铺满全高: 顶上从 sticky 顶栏底下过, 底下从磨砂气泡底下过
    # (设计一致, 用户点名"气泡下面要有内容"); 底衬让位 90px+safe 同主页
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
    # 顶栏同款护甲 (用户反馈: 顶栏像盖了层很模糊的涂层): sticky 住在滚动的
    # main 里, 不给自家合成层就会被栅格进邻居层 (main 的滚动光栅 / 全高
    # 推入层), 字跟着邻居的分辨率糊掉 —— 气泡有护甲没事, 顶栏要一样
    header_css = html[html.index("header {"):html.index(".nav-row {")]
    assert "transform: translateZ(0);" in header_css
    # 泳道撤了 (层铺满全高, 没有夹缝可露); 重影对策 = 运动期暂撤磨砂:
    # CSS 挂 body.pane-anim 实底, JS 的 paneMotion() 在每段层运动前打标
    # (拖动中每下续期), 停稳 500ms 恢复
    assert "#push-stack::after" not in html
    assert "body.pane-anim #mini-player" in html
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
    assert "calc(var(--pane-top, 64px) + 14px) 16px" in scroll_css
    assert "calc(90px + env(safe-area-inset-bottom));" in scroll_css
    assert "function syncPaneTop" in js
    assert '"--pane-top"' in js                       # 量出的高度写进 CSS 变量
    assert 'window.addEventListener("resize", syncPaneTop)' in js
    assert 'pane.innerHTML = \'<div class="pane-scroll"></div>\'' in open_pane


def test_music_standalone_header_frost_wiring():
    """独立 app (主屏图标) 模式顶栏撤磨砂 (用户实测截图: 竖屏独立模式整条
    顶栏连页签被栅成低清, 横屏清晰/浏览器清晰/气泡清晰 —— 触发点只在
    竖屏带刘海的磨砂顶栏, translateZ 护甲在浏览器里够用、独立模式救不动):
    ① 状态栏样式 black-translucent → black, 页面退到状态栏下面, 顶栏不再
    叠在刘海区; ② JS 开局打 body.standalone 标 (display-mode 查询 +
    navigator.standalone 双保险, iPhone 只认后者), CSS 撤 backdrop-filter
    换近实底 —— 连吊在顶栏下沿的扫描条一起 (同样磨砂贴屏顶)。"""
    static = Path(__file__).parent.parent / "app" / "music" / "static"
    html = (static / "music.html").read_text(encoding="utf-8")
    js = (static / "music.js").read_text(encoding="utf-8")
    # ① 页面不再伸进刘海区 (黑底应用看不出区别)
    assert 'name="apple-mobile-web-app-status-bar-style" content="black"' in html
    assert 'content="black-translucent"' not in html
    # ② 独立模式撤磨砂: 前缀属性两条一起撤, 顶栏/扫描条各自保底色
    standalone_css = html[html.index("body.standalone header"):
                          html.index("/* ---------- 页签")]
    assert "-webkit-backdrop-filter: none;" in standalone_css
    assert "backdrop-filter: none;" in standalone_css
    assert "body.standalone #scan-strip" in standalone_css
    assert "rgba(10,10,12,.97)" in standalone_css
    # 打标双保险住文件顶 (body 末尾脚本, 首帧前就位不闪磨砂)
    assert 'matchMedia("(display-mode: standalone)")' in js
    assert "navigator.standalone" in js
    assert 'document.body.classList.add("standalone")' in js
    # 一次性探针 (顶栏发糊排查, 查完连后端接口带断言一起撤): 前端启动上报
    # 真实现场 (检测/几何/磨砂计算值), /api/header-probe 落 data/probe.jsonl
    assert "header-blur-probe-1" in js
    assert "/music/api/header-probe" in js
    webapp = (Path(__file__).parent.parent / "app" / "music"
              / "webapp.py").read_text(encoding="utf-8")
    assert '@api.post("/header-probe"' in webapp
    assert "probe.jsonl" in webapp


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
                     js.index("syncPaneTop();")]
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
    播放气泡常驻。独立日志页保留 (直达链接仍可用)。"""
    static = Path(__file__).parent.parent / "app" / "music" / "static"
    html = (static / "music.html").read_text(encoding="utf-8")
    js = (static / "music.js").read_text(encoding="utf-8")
    assert '<button id="changelog-link">更新日志</button>' in html
    assert 'href="/music/changelog"' not in html    # 菜单不再整页跳走
    assert ('if (["home", "library", "search", "stats", "settings", "changelog"]'
            '.includes(name)) {') in js
    assert "function renderChangelogView()" in js
    assert 'fetchJSON("/music/changelog/api/entries")' in js
    assert "#changelog-entries" in html and ".v-badge" in html  # 版本卡片样式
    assert "$(\"#changelog-link\").addEventListener" in js
