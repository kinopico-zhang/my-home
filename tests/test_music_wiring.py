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
    播放列表"): 顶排 随机播放/循环播放 两枚胶囊 (循环再点一下切单曲循环),
    下面 upcoming 列表; 与歌词视图同住封面区互斥; 全屏页收起时跟着收。
    旧底部弹层 (queue-sheet/mask/close) 全撤。"""
    static = Path(__file__).parent.parent / "app" / "music" / "static"
    html = (static / "music.html").read_text(encoding="utf-8")
    player = (static / "music-player.js").read_text(encoding="utf-8")
    for frag in ['<div id="fp-queue" hidden>', 'class="fq-modes"',
                 'id="fp-shuffle"', 'id="fp-repeat"', 'id="queue-list"',
                 "#full-player.queue .fp-bg img"]:
        assert frag in html, f"队列视图缺 {frag}"
    assert "queue-sheet" not in html and "queue-mask" not in html \
        and "queue-close" not in html              # 旧弹层死透
    assert "queue-sheet" not in player and "queue-mask" not in player
    for frag in ["function toggleQueueView", "function closeQueueView",
                 "function renderQueueView", "let queueViewOpen = false;",
                 '$("#fp-queue-btn").addEventListener("click", toggleQueueView);',
                 "$(\"#queue-list\").innerHTML = upcoming.map"]:
        assert frag in player, f"music-player.js 缺 {frag}"
    # 互斥: 开队列先收歌词, 开歌词先收队列; 收起播放页两个都收
    assert "if (lyricsViewOpen) toggleLyricsView();" in player
    assert "if (!lyricsViewOpen && queueViewOpen) closeQueueView();" in player


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
    下载管理「全部删除」把整批叫停; action-row 会换行 (四个钮装不下单行)。"""
    static = Path(__file__).parent.parent / "app" / "music" / "static"
    html = (static / "music.html").read_text(encoding="utf-8")
    js = (static / "music.js").read_text(encoding="utf-8")
    assert 'id="album-download"' in js and "下载全部" in js
    assert 'id="playlist-download"' in js
    assert "flex-wrap: wrap" in html                # 四枚胶囊 375px 装不下
    for frag in ["function downloadAllFromUI", "let downloadAllCancelled = false;",
                 "await downloads.downloadTrack(track)",   # 顺序 (await 在循环里)
                 "downloadAllCancelled = true;"]:
        assert frag in js, f"music.js 缺 {frag}"


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
