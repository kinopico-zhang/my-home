"""My Music 页面静态接线测试: 统计页/主页/下载面/长按菜单/
设置页/蜂窝流量的静态文件断言。"""
import re


from tests.music_static_files import MUSIC_STATIC, music_browser_js, music_page_shell


def test_music_stats_page_wiring():
    """统计页接线: 设置页「更多」段入口 + 推入层路由 + 渲染函数 (E2E 再验真数据)。"""
    html = music_page_shell()
    assert "stat-grid" in html and "format-bar" in html   # 统计卡片 + 比例条
    js = music_browser_js()
    assert '"search", "settings", "stats", "changelog"];' in js
    assert "async function renderStatsView(" in js
    assert '"/music/api/stats"' in js
    assert 'data-set-nav="stats"' in js                  # 设置页入口直通统计页


def test_music_home_page_wiring():
    """主页接线 (1.8.0: 主页是唯一根视图, 其余全是推入层): 上弹菜单六项 +
    播放列表/最近播放两段 + 播放列表详情路由 + 最近播放独立页 (1.8.1,
    E2E 再验真数据)。"""
    html = music_page_shell()
    assert '<div id="dock">' in html                     # 船坞三件套在场
    assert 'data-pop-nav="playlists"' in html           # 菜单进播放列表
    assert 'data-pop-nav="recent"' in html              # 菜单进最近播放页
    assert 'id="dock-search"' in html                   # 搜索键直进搜索页
    assert 'id="search-btn"' not in html    # 放大镜按钮已撤
    assert 'id="sync-playlists"' not in html     # Plex 同步入口已撤
    assert "playlist-row" in html                  # 行样式在
    js = music_browser_js()
    assert "function renderHomeView()" in js
    assert '"/music/api/plays/recent?limit=20"' in js
    assert '"/music/api/playlists"' in js          # 主页播放列表段
    assert 'if (name === "playlist" && argument)' in js
    assert "function renderPlaylistView(" in js
    assert "playlistRowHTML" in js
    # 播放列表独立成层 (原主页列表段上头的入口, 1.8.0 进上弹菜单)
    assert "function renderPlaylistsPane(" in js
    # 最近播放独立成层 (1.8.1): LRU 整页 + 次数替时长 (词标/下载标照旧)
    assert "function renderRecentPane(" in js
    assert '"recent", "downloads",' in js                 # PANE_VIEWS 收录
    assert 'else if (view === "recent") renderRecentPane(target);' in js
    assert '"/music/api/plays/recent?limit=100"' in js
    assert "pageState.recentPane" in js                   # 点行开播的队列语境
    assert "`×${track.play_count}`" in js                 # 行右缘 = 播过几次
    # 默认进主页 (单地址批: 旧深链开局消化一次, URL 洗成光杆 /music)
    assert 'history.replaceState(null, "", location.pathname + location.search);' in js
    assert 'navigate(legacyTarget);' in js


def test_music_downloads_wiring():
    """下载接线: 纯逻辑模块 (node 直测) + SW 拦流 + 已下载独立页 + 能力门控 + 下载管理。"""
    js = music_browser_js()
    assert "downloadsSupported" in js and "createDownloads" in js
    assert '"/music/sw.js"' in js                  # SW 注册
    assert "isSecureContext" in js                 # 明文 HTTP 整个功能收起
    assert "function renderDownloadsPane(" in js   # 已下载独立页 (1.8.0)
    assert "$(\"#dl-pane-body\")" in js            # 页容器独占 id, 进度刷新认得准
    assert "data-download-track" in js             # 曲目行下载标
    assert "storageUsage" in js and "formatBytes" in js    # 下载管理: 量大小并显示
    assert "dl-clear-all" in js and "removeAll" in js      # 一键清空 (confirm 后)
    assert "navigator.storage.estimate" in js      # 手机存储占用
    # 1.8.2: 下载中的进度从百分比文字换成圆环 (r=8.5 周长切 dashoffset,
    # 正上方顺时针画满; 已下载照旧是勾)
    assert "function downloadRingHTML" in js
    assert "stroke-dasharray" in js and "stroke-dashoffset" in js
    # 1.8.5 修「下载中已下载页封面闪烁」: 进度回调不再整页重铺 —— 行级
    # 就地补 (同一行只换圆环, 状态翻转才换行), 全清了才补统计行
    assert "function refreshDownloadsBody" in js
    assert "function downloadRowHTML" in js
    assert 'body.querySelectorAll("[data-dl-row]")' in js
    assert "ring.outerHTML = downloadRingHTML" in js
    # 已下载行也带封面: 曲目封面接口 + 裂图退音符 (和播放列表行同款)
    assert 'src="/music/media/tracks/${entry.track_id}/artwork"' in js
    downloads_js = (MUSIC_STATIC / "js" / "downloads.js").read_text(encoding="utf-8")
    assert "/music/media/stream/" in downloads_js  # 缓存键 = 音频流地址
    assert "AbortController" in downloads_js       # 下载中的删除 = 取消下载
    html = music_page_shell()
    assert ".dl-stats" in html and ".dl-clear" in html    # 统计行样式
    # 1.8.6 多选删除 (用户点名): 「多选」进选择模式, capture 阶段截下点行
    # 改勾选 (不再开播), 统计条换「删除 N 首」, 删完/「完成」退出;
    # 状态住模块, 整页重铺后 syncDownloadsSelect 按 state 补圈补勾
    assert "music-downloads-select.css?v=" in html        # 选择圈样式
    select_js = (MUSIC_STATIC / "js" / "music-downloads-select.js").read_text(
        encoding="utf-8")
    for frag in ["function bindDownloadsSelect", "function syncDownloadsSelect",
                 "function deleteSelected", "const dlSelected = new Set();",
                 "event.stopPropagation();",          # capture 截下: 不走开播
                 "删除选中的 ${dlSelected.size} 首?",
                 "await downloads.removeDownload(trackId);"]:
        assert frag in select_js, f"多选删除缺 {frag}"
    assert "bindDownloadsSelect(target);" in js          # 挂 pane 层 (重铺不丢)
    assert 'id="dl-select-toggle"' in js and 'id="dl-select-delete"' in js
    assert "#dl-pane-body.selecting .dl-row.sel::after" in html  # 勾样式
    scripts = re.findall(r'<script src="([^"]+)"', html)
    # 结构化重构后 45 个独立脚本 (1.8.1: +recent-pane; 1.8.3: +search-pages;
    # 1.8.5: +bubble-swipe; 1.8.6: +downloads-select, push-panes 拆出 pane-swipe),
    # 引用一律带版本参数 (改哪个 bump 哪个)
    assert len(scripts) == 45 and all("?v=" in src for src in scripts)
    assert "js/downloads.js?v=" in html and "js/music-app-boot.js?v=" in html
    assert "js/music-downloads-select.js?v=" in html   # 1.8.6 已下载多选删除
    sw = (MUSIC_STATIC / "sw.js").read_text(encoding="utf-8")
    assert "TRACK_URL_PATTERN" in sw               # 曲目流: 缓存回源 + Range 切片
    assert "caches.open" in sw and "206" in sw
    assert "music-shell-v8" in sw                  # 应用壳也进缓存 (断网打得开)
    assert "clients.claim" in sw                   # 装完立刻接管已开的页面


def test_music_track_context_menu_wiring():
    """长按菜单接线: 检测 (500ms/右键/移动作废)、菜单四项、选择单、
    分享回落都在页面上; 行样式禁掉 iOS 长按气泡。"""
    html = music_page_shell()
    js = music_browser_js()
    for frag in ['id="track-menu"', 'id="track-menu-mask"',
                 'data-track-action="play"', 'data-track-action="artist"',
                 'data-track-action="playlist"', 'data-track-action="share"',
                 'data-track-action="download" id="track-menu-download"',
                 'id="track-menu-artist"', 'id="picker-sheet"',
                 'id="picker-list"', 'id="picker-create"', 'id="picker-name"',
                 'id="picker-close"', 'id="picker-mask"',
                 "-webkit-touch-callout: none"]:
        assert frag in html, f"播放页缺少 {frag}"
    # 1.8.6: 播放页 ⋯ 菜单加「下载」—— 已下过的/下载不可用时藏掉,
    # 派发走 downloadTrackFromUI (与曲目行长按菜单同一颗)
    assert 'hideDownloadMenuItem(track)' in js
    assert '$("#track-menu-download").hidden' in js
    assert 'downloadTrackFromUI(track);' in js
    for frag in ["function openTrackMenu", "function cancelTrackPress",
                 "function trackFromRow", "function shareTrack",
                 "function openPlaylistPicker", "trackListBindings",
                 "trackPressTimer = setTimeout",            # 500ms 长按计时
                 'document.addEventListener("contextmenu"',
                 "navigator.share", "execCommand",          # 分享 + 复制回落
                 "suppressTrailingTarget",                 # 长按尾随点击按元素吞
                 # 1.8.2: 艺人/专辑两项并一路跳转 —— 先收全屏播放页
                 # (z90 盖着 z44 的推入层, 不收 = 看着没反应), 再按项分目标
                 "if (playerOpen) closeFullPlayer();",
                 '? `artist/${track.artist_id}` : `album/${track.album_id}`);',
                 'fetchJSON("/music/api/playlists"',
                 '`/music/api/playlists/${playlistId}/tracks`',
                 "error.status === 409",            # 已在列表里: 直说原因不算失败
                 '`/music/api/playlists/${playlistId}`, { method: "DELETE" }',
                 'id="playlist-delete"',           # 列表删除在详情页 (选择单只加歌)
        ]:
        assert frag in js, f"music.js 缺少 {frag}"
    # 新版图标/脚本地址随行; Plex 同步全撤了
    assert "js/music-app-boot.js?v=" in html   # 浏览页模块链以 boot 收尾
    # 长歌名不许把菜单撑超宽 (用户报"菜单非常宽, 建议截断"): 固定定位菜单
    # 收缩到内容, 不封顶会一路撑到视口; 320px 封顶后 nowrap 截断才接管
    assert "max-width: min(320px, calc(100vw - 24px))" in html
    # fetchJSON 把 HTTP 状态码挂上错误对象 (加歌 409 分叉靠它)
    common = (MUSIC_STATIC / "js" / "music-common.js").read_text(encoding="utf-8")
    assert "status: response.status" in common
    assert "picker-sync" not in html and "picker-sync" not in js
    assert "picker-del" not in html and "picker-del" not in js
    assert "sync-playlists" not in html and "/playlists/sync" not in js


def test_music_settings_view_wiring():
    """设置页接线 (1.8.0: 上弹菜单「设置」进, 推入层铺开) + 表单三件
    (曲库路径/歌词开关/API 地址) + 流量月账 + 原菜单职能 (账号/退出/重扫/
    统计/更新日志入口); 普通账号只读 (开关/输入框锁着, 保存钮不出)。"""
    html = music_page_shell()
    js = music_browser_js()
    assert 'data-pop-nav="settings"' in html             # 菜单直通设置页
    assert ".settings-block" in html and ".switch" in html and ".month-row" in html
    assert '"search", "settings", "stats", "changelog"];' in js
    assert "async function renderSettingsView(" in js
    assert 'fetchJSON("/music/api/settings")' in js
    assert 'fetchJSON("/api/me")' in js and "editable" in js   # 按管理员分叉
    assert "music_directory" in js and "lyrics_api_enabled" in js \
        and "lyrics_api_base" in js
    assert "monthRowHTML" in js and "cellular_months" in js   # 月账一段
    assert 'const lock = editable ? "" : " disabled"' in js    # 只读锁
    assert "仅管理员可修改" in js                              # 非管理员的落地面


def test_music_cellular_wiring():
    """蜂窝流量接线: 纯逻辑模块 (node 直测) + 安卓 connection.type 判定 +
    keepalive 上报 + onHide 兜底 (切后台/离页都报)。"""
    html = music_page_shell()
    js = music_browser_js()
    assert "cellular-usage.js?v=2" in html                     # 模块加载
    assert "createCellularMonitor" in js
    assert 'connection.type === "cellular"' in js              # 只有认得出的才记
    assert '"/music/api/cellular-usage"' in js and "keepalive: true" in js
    assert "pagehide" in js and "visibilitychange" in js       # 离页/切后台兜底
