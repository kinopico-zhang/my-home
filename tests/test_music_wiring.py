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
    # 删除钮的点击走捕获层 (}, true); 行自己的冒泡 click 处理器看不到它
    assert 'container.addEventListener("click", async (event) => {' in js
    assert "}, true);" in js


def test_music_player_back_gesture_wiring():
    """iOS 返回手势收播放页 (用户点名: 下拉向下收, 返回手势向右收,
    收起后露出被挡的页面而不是退一级): 开全屏页挂一条同址历史
    (pushState {fp:1}), popstate 弹到非 fp 条目 → 向右滑出收起;
    按钮收起自己 back() 弹掉占位条目 (那记 popstate 别当返回手势)。"""
    static = Path(__file__).parent.parent / "app" / "music" / "static"
    html = (static / "music.html").read_text(encoding="utf-8")
    player = (static / "music-player.js").read_text(encoding="utf-8")
    assert "#full-player.dismiss-right { transform: translateX(100%); }" in html
    open_player = player[player.index("function openFullPlayer"):
                         player.index("下拉收起 / 横划切歌")]
    assert 'history.pushState({ fp: 1 }, "", location.href)' in open_player
    close_player = player[player.index("function closeFullPlayer"):
                          player.index("window.addEventListener(\"popstate\"")]
    assert 'if (direction === "right") fullPlayer.classList.add("dismiss-right")' \
        in close_player
    assert "history.back()" in close_player      # 按钮收起弹占位条目
    assert "poppingPlayerEntry" in player        # 自己的 back 不当返回手势
    assert 'window.addEventListener("popstate", () => {' in player
    assert 'closeFullPlayer("right")' in player


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
    assert 'if (name === "changelog") return { view: "changelog" };' in js
    assert "function renderChangelogView()" in js
    assert 'fetchJSON("/music/changelog/api/entries")' in js
    assert "#changelog-entries" in html and ".v-badge" in html  # 版本卡片样式
    assert "$(\"#changelog-link\").addEventListener" in js
