"""My Music 搜索页接线测试 (1.8.3 重排, 用户点名): 输入框钉页底船坞上方 +
回车收起键盘 + 结果四子页左右滑切换 + 打开 app 回上次停的页 —— 静态文本
断言, 不碰数据库。拆自 test_music_page_wiring.py (文件超 200 行按域再拆)。"""

from tests.music_static_files import music_browser_js, music_page_shell


def test_music_183_search_restore_batch():
    """1.8.3 批 (用户点名): 打开 app 自动回上次停的页 (默认主页播放列表,
    退出登录清档); 搜索页重排 —— 输入框钉页底船坞上方 (顶端不再有钉死的
    内容) + 回车收起 iOS 键盘; 结果分 歌曲/艺人/专辑/歌词 四子页左右滑
    切换 (scroll-snap + 页签指示互相同步), 歌曲行带封面; 气泡/圆键
    透明度调实一档 (太透时底下内容忽明忽暗)。"""
    html = music_page_shell()
    js = music_browser_js()
    # 回跳: 导航/收层/手势收层各存一次档, 开局读档 (旧深链优先, 没记过
    # 回主页); localStorage 抛异常 (隐私模式) 存读全兜住
    assert 'const LAST_ROUTE_KEY = "music.lastRoute";' in js
    for frag in ["function routeKey(", "function saveLastRoute(",
                 "function readLastRoute(", "function clearLastRoute("]:
        assert frag in js, f"回跳缺 {frag}"
    assert js.count("saveLastRoute();") == 3       # 导航/收层/手势收层
    assert "// 手势收层也记停在哪页 (开局回跳)" in js
    assert "const lastRoute = readLastRoute();" in js
    assert '? lastRoute : "home");' in js          # 没记过回主页播放列表
    assert "clearLastRoute();         // 上次停的页清档" in js   # 退出登录清档
    # 搜索页: 页底一条 (页签 + 输入框), 顶端全给滚动内容
    assert '<div class="search-foot">' in js and 'id="search-tabs"' in js
    assert ".search-shell {" in html           # 页壳抵掉层衬
    assert "interactive-widget=resizes-content" in html   # 安卓键盘自己缩布局
    assert "visualViewport" in js and '"--kb-h"' in js    # iOS 键盘高度 → 抬输入框
    assert "margin-bottom: var(--kb-h, 0);" in html
    # 回车收起 iOS 键盘 (搜索是边打边搜的, 回车没有别的活)
    assert 'if (event.key === "Enter") { event.preventDefault(); input.blur(); }' in js
    # 四子页: 横向 snap 容器 + 各自竖滚的页, 页签指示跟手滑同步
    assert 'data-search-page="tracks"' in js and 'data-search-page="lyrics"' in js
    assert "scroll-snap-type: x mandatory;" in html
    assert "#search-body.paged + .search-foot .search-tabs { display: flex; }" in html
    assert "function bindSearchTabs()" in js
    assert 'body.scrollTo({ left: index * body.clientWidth, behavior: "smooth" });' in js
    # 两条横手势分家: 起手在四子页里的横拖归切页, 不归推入层右划返回;
    # touch-action 是链式约束, .push-pane 放行 pan-x 后容器才滑得动
    assert 'if (event.target.closest("#search-body.paged")) return;' in js
    assert "touch-action: pan-x pan-y;" in html
    # 搜索歌曲行带封面 (与播放列表行同款 trackArtHTML)
    search_render = js[js.index("function renderSearchResults"):]
    assert 'trackRowHTML(track, trackArtHTML(track), "art")' in search_render
    # 透明度调实: 三件套六成底 → 八成底, 动画期等效实底跟着重算
    assert "rgba(44,44,46,.78);" in html
    assert "background: rgb(34,34,36);" in html
