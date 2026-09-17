"""My Music 页面静态接线测试: 统计页/主页/下载面/长按菜单/
设置页/蜂窝流量的静态文件断言。"""
import re


from tests.music_static_files import MUSIC_STATIC, music_browser_js, music_page_shell


def test_music_stats_page_wiring():
    """统计页接线: 设置页「更多」段入口 + hash 路由 + 渲染函数 (E2E 再验真数据)。"""
    html = music_page_shell()
    assert "stat-grid" in html and "format-bar" in html   # 统计卡片 + 比例条
    js = music_browser_js()
    assert ('if (["home", "library", "search", "stats", "settings", "changelog"]'
            '.includes(name)) {') in js
    assert "function renderStatsView()" in js
    assert '"/music/api/stats"' in js
    assert 'data-set-nav="stats"' in js                  # 设置页入口直通统计页


def test_music_home_page_wiring():
    """主页接线: 底部页签栏主页/资料库/搜索/设置 + 播放列表/最近播放两段 +
    播放列表详情路由 (E2E 再验真数据)。"""
    html = music_page_shell()
    assert '<nav id="tabbar">' in html
    assert ('data-view-tab="home"' in html and 'data-view-tab="library"' in html
            and 'data-view-tab="search"' in html
            and 'data-view-tab="settings"' in html)   # 搜索/设置都收进页签
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
    # 默认进主页 (单地址批: 旧深链开局消化一次, URL 洗成光杆 /music)
    assert 'history.replaceState(null, "", location.pathname + location.search);' in js
    assert 'navigate(legacyTarget);' in js
    assert '["albums", "专辑"], ["artists", "艺人"], ["downloads", "已下载"]' in js


def test_music_downloads_wiring():
    """下载接线: 纯逻辑模块 (node 直测) + SW 拦流 + 已下载段 + 能力门控 + 下载管理。"""
    js = music_browser_js()
    assert "downloadsSupported" in js and "createDownloads" in js
    assert '"/music/sw.js"' in js                  # SW 注册
    assert "isSecureContext" in js                 # 明文 HTTP 整个功能收起
    assert 'segment === "downloads"' in js         # 已下载段不走接口分页
    assert "data-download-track" in js             # 曲目行下载标
    assert "storageUsage" in js and "formatBytes" in js    # 下载管理: 量大小并显示
    assert "dl-clear-all" in js and "removeAll" in js      # 一键清空 (confirm 后)
    assert "navigator.storage.estimate" in js      # 手机存储占用
    # 已下载行也带封面: 曲目封面接口 + 裂图退音符 (和播放列表行同款)
    assert 'src="/music/media/tracks/${entry.track_id}/artwork"' in js
    downloads_js = (MUSIC_STATIC / "js" / "downloads.js").read_text(encoding="utf-8")
    assert "/music/media/stream/" in downloads_js  # 缓存键 = 音频流地址
    assert "AbortController" in downloads_js       # 下载中的删除 = 取消下载
    html = music_page_shell()
    assert ".dl-stats" in html and ".dl-clear" in html    # 统计行样式
    scripts = re.findall(r'<script src="([^"]+)"', html)
    # 结构化重构后 39 个独立脚本, 引用一律带版本参数 (改哪个 bump 哪个)
    assert len(scripts) == 39 and all("?v=" in src for src in scripts)
    assert "js/downloads.js?v=" in html and "js/music-app-boot.js?v=" in html
    sw = (MUSIC_STATIC / "sw.js").read_text(encoding="utf-8")
    assert "TRACK_URL_PATTERN" in sw               # 曲目流: 缓存回源 + Range 切片
    assert "caches.open" in sw and "206" in sw
    assert "music-shell" in sw                     # 应用壳也进缓存 (断网打得开)
    assert "clients.claim" in sw                   # 装完立刻接管已开的页面


def test_music_track_context_menu_wiring():
    """长按菜单接线: 检测 (500ms/右键/移动作废)、菜单四项、选择单、
    分享回落都在页面上; 行样式禁掉 iOS 长按气泡。"""
    html = music_page_shell()
    js = music_browser_js()
    for frag in ['id="track-menu"', 'id="track-menu-mask"',
                 'data-track-action="play"', 'data-track-action="artist"',
                 'data-track-action="playlist"', 'data-track-action="share"',
                 'id="track-menu-artist"', 'id="picker-sheet"',
                 'id="picker-list"', 'id="picker-create"', 'id="picker-name"',
                 'id="picker-close"', 'id="picker-mask"',
                 "-webkit-touch-callout: none"]:
        assert frag in html, f"播放页缺少 {frag}"
    for frag in ["function openTrackMenu", "function cancelTrackPress",
                 "function trackFromRow", "function shareTrack",
                 "function openPlaylistPicker", "trackListBindings",
                 "trackPressTimer = setTimeout",            # 500ms 长按计时
                 'document.addEventListener("contextmenu"',
                 "navigator.share", "execCommand",          # 分享 + 复制回落
                 "suppressTrailingTarget",                 # 长按尾随点击按元素吞
                 "navigate(`artist/${track.artist_id}`)",
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
    """设置页接线: 底部页签栏「设置」入口 + 表单三件 (曲库路径/歌词开关/
    API 地址) + 流量月账 + 原菜单职能 (账号/退出/重扫/统计/更新日志入口);
    普通账号只读 (开关/输入框锁着, 保存钮不出)。"""
    html = music_page_shell()
    js = music_browser_js()
    assert 'data-view-tab="settings"' in html            # 页签直通设置页
    assert ".settings-block" in html and ".switch" in html and ".month-row" in html
    assert ('if (["home", "library", "search", "stats", "settings", "changelog"]'
            '.includes(name)) {') in js
    assert "function renderSettingsView()" in js
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
    assert "cellular-usage.js?v=1" in html                     # 模块加载
    assert "createCellularMonitor" in js
    assert 'connection.type === "cellular"' in js              # 只有认得出的才记
    assert '"/music/api/cellular-usage"' in js and "keepalive: true" in js
    assert "pagehide" in js and "visibilitychange" in js       # 离页/切后台兜底
