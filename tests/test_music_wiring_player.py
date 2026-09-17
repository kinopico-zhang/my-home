"""My Music 播放器接线测试: 控制钮样式, 队列封面视图, 队列拖拽,
返回手势收起, 单 URL 导航 —— 静态文本断言, 不碰数据库。
拆自 test_music_wiring.py (结构化重构, 代码逐字节未动)。"""

from tests.music_static_files import (MUSIC_STATIC, music_browser_js,
                                      music_page_shell, music_player_js)


def test_music_controls_apple_style_wiring():
    """传输区最终形 (用户两连点名): 三键站在进度条**正上方**居中成一行,
    不是挤在进度条旁边; 三键一般大 (44×44, 播放键不再大一号);
    进度条 range 住在 flex 行里要 flex:1+min-width:0 才肯让位收缩。
    迷你气泡 1.8.0 起只留播放/暂停 (上下曲撤了, 全屏页里都有,
    气泡收窄让位给歌名跑马灯)。图标包围盒中心对准按键中心的
    不变量在 player-icons.test.mjs。"""
    html = music_page_shell()
    common = (MUSIC_STATIC / "js" / "music-common.js").read_text(encoding="utf-8")
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
    # 迷你气泡 1.8.0 只留播放/暂停 (上下曲撤了); 歌名/作者改跑马灯
    assert 'id="mini-play"' in html
    assert 'id="mini-prev"' not in html and 'id="mini-next"' not in html
    assert 'class="mq-line"' in html and 'class="mq-run"' in html
    # 音量条整个撤了 (1.5.1, 用户点名): 音量交给设备音量键/系统音量
    assert "#fp-volume" not in html and ".fp-volume" not in html
    # 气泡磨砂玻璃 (用户点名): 八成底色配 blur(20), 底下划过的内容糊成
    # 影子透上来 —— 不是一块实心灰板 (88% 那种看不出磨砂); 1.8.3 从
    # 六成调实一档 (太透时底下内容深浅透进来, 三件套忽明忽暗)
    mini_css = html[html.index("#mini-player {"):html.index("#mini-progress")]
    assert "rgba(44,44,46,.78);" in mini_css
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
    html = music_page_shell()
    player = music_player_js()
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
    html = music_page_shell()
    player = music_player_js()
    common = (MUSIC_STATIC / "js" / "music-common.js").read_text(encoding="utf-8")
    queue = (MUSIC_STATIC / "js" / "player-queue.js").read_text(encoding="utf-8")
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


def test_music_player_dismiss_wiring():
    """播放页的收起路径 (1.7.0 单地址批): 下拉/Esc 向下收, 抓手条横拖右甩
    向右收 —— 全是纯视图开关, 不再挂历史条目 (一个地址批后浏览器里没有
    可退的条目, 播放页也跟着撤了 pushState/popstate 那套)。
    电脑上的"返回"是 Esc: 先收播放页, 没开就收顶层二级页。"""
    html = music_page_shell()
    player = music_player_js()
    js = music_browser_js()
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
    # 1.8.2 整页下拉收起 (用户点名「任何一点都能拖」): .fp-sheet/.fp-bg 也绑
    # 一份, 第四参数让路自带手势/滚动/按钮的起手点 (歌词/队列要滚,
    # 抓手/封面自带拖动, 按钮滑杆各有语义)
    assert 'bindDismissDrag($(".fp-sheet"), false, false, true);' in player
    assert 'bindDismissDrag($(".fp-bg"), false, false, true);' in player
    assert "#fp-grab, #fp-art-wrap, #fp-lyrics, #fp-queue, .fp-scrub," in player
    # Esc = 电脑上的返回: 先收播放页, 没开收顶层二级页
    esc_handler = js[js.index('event.key !== "Escape"'):
                     js.index("// ------------------------------------------------------------"
                              " 蜂窝流量")]
    assert "if (playerOpen) closeFullPlayer();" in esc_handler
    assert "closePushStack(pushStack.length - 1)" in esc_handler


def test_music_single_url_navigation_wiring():
    """单地址导航 (用户点名: 列表和主页就是一个页面, 进播放列表只是内容
    变化, 不存在网页切换): 导航目标只活在内存里 (根视图 + 层栈), 全程
    不碰 location.hash / pushState / history.back —— 浏览器返回/前进和
    iOS 系统侧滑在应用里没有条目可退, 整页截图滑走 (气泡跟着跑) 绝迹。
    旧深链开局消化一次, URL 随即洗成光杆 /music。"""
    js = music_browser_js()
    player = music_player_js()
    # 不写 hash、不挂 hashchange、不加/弹历史条目 (认调用形式 —— 文件头
    # 注释里提到这些词是说明, 不算数)
    assert "location.hash =" not in js
    assert "hashchange" not in js
    assert "pushState(" not in js and "history.back(" not in js
    assert "pushState(" not in player and "history.back(" not in player
    # 目标从状态派生: 有层看顶层, 没层看根视图 (1.8.0: 主页独占根层,
    # 播放列表/专辑/艺人/最近播放/已下载/搜索/设置/统计/更新日志全是推入层)
    assert "function parseRoute" in js and "function currentRoute" in js
    assert 'const PANE_VIEWS = ["playlists", "albums", "artists", "recent", "downloads",' in js
    assert '"search", "settings", "stats", "changelog"];' in js
    assert "PANE_VIEWS.includes(name)" in js
    assert 'const pushed = view !== "home";' in js
    assert "function routeRoot" in js and "function routePushed" in js
    # 开局: 旧深链消化一次 → replaceState 洗 URL (不加条目) → 状态开局
    assert 'const legacyHash = location.hash.replace(/^#\\/?/, "");' in js
    assert 'history.replaceState(null, "", location.pathname + location.search);' \
        in js
    assert "navigate(legacyTarget);" in js
    # 层收尽 (按钮收/右划收) 回到根视图 = 主页; 页签点亮同步那套随页签栏撤了
    assert "syncViewTabs" not in js


def test_music_182_player_interaction_batch():
    """1.8.2 播放页交互批 (用户点名): 专辑名并进艺人行 (来源行只留
    作词/作曲标签, 没有整行收掉); 弹出菜单加「进入专辑主页」;
    修「进艺人主页点了没反应」—— 页面其实开了, 但 z90 的全屏播放页
    盖着 z44 的推入层, 开了也看不见: 跳转前先把播放页收起来。"""
    html = music_page_shell()
    player = music_player_js()
    js = music_browser_js()
    # 专辑名并到艺人后 (| 隔开), 底下那一行省出来
    assert "[track.artist, track.album_title]" in player
    assert '.filter(Boolean).join(" | ");' in player
    assert "function renderSourceLine" in player     # 来源行只留 词/曲 标签
    assert 'id="fp-source" hidden' in html           # 没标签时整行收掉
    # 菜单新条目: 进入专辑主页 (这首歌有专辑才亮)
    assert 'data-track-action="album" id="track-menu-album"' in html
    assert '进入专辑主页' in html
    assert '$("#track-menu-album").hidden = !track.album_id;' in js
    # 修: 跳艺人/专辑前先收播放页 (盖在底下 = 看着没反应)
    assert "if (playerOpen) closeFullPlayer();" in js
    assert "`album/${track.album_id}`" in js
