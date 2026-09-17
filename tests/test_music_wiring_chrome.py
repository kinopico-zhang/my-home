"""My Music 页面骨架接线测试: 三页签固定 chrome + 1.7.1/1.7.2
打磨批次回归 —— 静态文本断言, 不碰数据库。
拆自 test_music_wiring.py (结构化重构, 代码逐字节未动)。"""

from tests.music_static_files import MUSIC_STATIC, music_browser_js, music_page_shell


def test_music_pane_fixed_chrome_wiring():
    """船坞三件套/气泡在滚动和切页全程钉死 (用户点名两轮: 切页时不在一个图层 +
    滑动过程中也保持不动)。两层手段: ① 固定壳 —— html/body 锁高锁滚,
    文档永不滚 (iPhone 工具栏只跟文档滚动收放, 文档不滚视口恒定,
    钉视口的船坞/气泡物理上无从移动), main 变内部滚动器; ② 全高推入层
    (z44) 从毛玻璃船坞 (z50)/气泡底下扫过, 内容顶上用
    env(safe-area-inset-top) 让位 (顶栏撤了, 不再要 JS 量高度)。
    层铺满全高 (设计一致, 用户点名: 气泡底下要有内容, 和主页
    一样) —— 重影对策挪到运动期: body.pane-anim 暂撤船坞三件磨砂换实底
    (fixed+backdrop-filter 底下有扫动的变换层是 WebKit 的重影配方)。
    根视图渲染目标 #root-view (main 是滚动器, 直写会抹掉内容)。"""
    html = music_page_shell()
    js = music_browser_js()
    # 壳: 文档不滚, main 是唯一一级滚动器
    assert "height: 100%; overflow: hidden;" in html            # html
    assert "height: 100dvh;" in html and "overflow: hidden;" in html  # body
    main_css = html[html.index("main {"):html.index("#root-view {")]
    assert "min-height: 0;" in main_css and "overflow-y: auto;" in main_css
    assert "-webkit-overflow-scrolling: touch;" in main_css
    # 顶部雷区让位: main 整个下移, 滚动内容永远进不了那条带子 —— 只给内容
    # 加 padding 的话, 一滚字就又钻进去。1.8.0 起纯 env (用户点名「任凭
    # 模糊, 不做处理」: iOS 26.1+ env 谎报 0 的系统里让位失效, 认了)
    assert "margin-top: env(safe-area-inset-top);" in main_css
    root_css = html[html.index("#root-view {"):html.index(".push-pane {")]
    assert "max-width: 860px; margin: 0 auto;" in root_css
    assert "var(--dock-clear)" in root_css                # 底部让位一套账
    assert "max(16px, env(safe-area-inset-right))" in root_css  # 横屏让开侧刘海
    assert "max(16px, env(safe-area-inset-left))" in root_css
    assert html.index('<main id="main">') < html.index('<div id="root-view">') \
        < html.index("</main>") < html.index('<div id="dock">')
    # 一级页滚动/渲染都走 main/#root-view, 文档滚动彻底退出
    assert '$("#main").scrollTop = pageState.rootScroll;' in js
    assert 'pageState.rootScroll = $("#main").scrollTop;' in js
    assert "window.scrollY" not in js
    assert '$("#root-view").innerHTML' in js
    assert "window.scrollTo" not in js
    # 推入层铺满全高: 顶上一直铺到屏顶 (顶栏撤了, env 让开刘海), 底下从磨砂
    # 船坞/气泡底下过 (设计一致, 用户点名"气泡下面要有内容")
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
    # 船坞两颗圆键同款护甲 (和气泡一样是 fixed 常驻件, 邻居层动起来时防复印)
    keys_css = html[html.index("#dock-menu, #dock-search {"):html.index("#dock-menu:active")]
    assert "transform: translateZ(0);" in keys_css
    # 泳道撤了 (层铺满全高, 没有夹缝可露); 重影对策 = 运动期暂撤磨砂:
    # CSS 挂 body.pane-anim 实底 (船坞三件一起), JS 的 paneMotion()
    # 在每段层运动前打标 (拖动中每下续期), 停稳 500ms 恢复
    assert "#push-stack::after" not in html
    assert "body.pane-anim #mini-player," in html
    assert "body.pane-anim #dock-menu," in html
    assert "body.pane-anim #dock-search {" in html
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
                      html.index(".sticky-head")]
    # 顶上让位纯 CSS (顶栏撤了, env 直读; 独立模式 black-translucent 下拿
    # 得到真实刘海高度), 底下让开船坞 —— JS 量高度那套 (syncPaneTop/
    # --pane-top/headerBottom) 整个退役
    assert "calc(env(safe-area-inset-top) + 14px)" in scroll_css
    assert "var(--dock-clear)" in scroll_css
    assert "function syncPaneTop" not in js
    assert '"--pane-top"' not in js
    assert "headerBottom" not in js
    assert 'pane.innerHTML = \'<div class="pane-scroll"></div>\'' in open_pane


def test_music_171_polish_batch():
    """1.7.1 打磨批接线 (2026-09-16, 全是用户点名): 待播放列表四边留白
    对齐大封面; 专辑名过长单行截断 (原来换行把网格顶得参差); 资料库
    歌曲行/专辑页曲目行的编号换成封面缩略图 (序号没用还常从 101 起 ——
    多碟专辑的音轨标签); 封面图加 SW Cache API 一层缓存 (iOS 的 HTTP
    缓存容易被系统清掉, 大库一刷列表几百张图全回源)。"""
    html = music_page_shell()
    js = music_browser_js()
    sw = (MUSIC_STATIC / "sw.js").read_text(encoding="utf-8")
    # 队列视图: inset:0 罩到 .fp-body 边, 自己衬回和大封面同款的 24px
    queue_css = html[html.index("#fp-queue {"):html.index(".fq-head {")]
    assert "padding: 6px 24px 30px;" in queue_css
    # 专辑名单行截断 (line-clamp 1), 排版不再被长名换行顶乱
    album_css = html[html.index(".album-card b {"):html.index(".album-card small")]
    assert "-webkit-line-clamp: 1;" in album_css
    # 曲目行的编号位全下岗: 资料库歌曲段和专辑页都换成封面缩略图
    assert "t-index" not in js and "track_number" not in js
    assert 'trackRowHTML(track, trackArtHTML(track), "art"))' in js
    # SW 封面缓存: 封面族缓存优先, 没缓存才回源; 条数封顶防膨胀
    assert 'const ARTWORK_CACHE = "music-artwork-v1";' in sw
    assert "serveArtwork(request)" in sw
    assert "trimArtworkCache(cache);" in sw
    assert "/artwork$|^\\/music\\/media\\/playlists" in sw   # 封面族正则 (含列表封面)


def test_music_172_fix_batch():
    """1.7.2 修复批接线 (2026-09-16, 用户手机实测反馈; 1.8.0 相关的随界面
    重构更新):
    - 资料库分页串台/空列表竞态: 换页签后在途旧分页回来灌进新页签
      (顺序看着随机), 切回来时 renderedCount 没归零只渲染「下一页」
      (艺人 218 首全加载完的段直接空白) —— 段守卫 + 缓存重铺归零;
      首页没拉到不再缓存空单 (切回来会重试);
    - 搜索框 sticky 钉在顶端, 不随列表滚走 (1.8.0: 段选择条随资料库
      拆页撤掉, sticky 只剩搜索页一处);
    - 歌曲页签撤掉 (找歌用搜索), 旧存的段名自动回落专辑。"""
    html = music_page_shell()
    js = music_browser_js()
    # 段守卫三件套: 装配时打标 / 追加对不上就丢 / 缓存重铺归零
    assert "body.dataset.segment = segment;" in js
    assert js.count("body.dataset.segment !== segment") == 2   # 追加 + 装载
    assert "list.renderedCount = 0;" in js
    assert "delete pageState.lists[segment];" in js        # 空单不缓存
    # 歌曲段撤掉: 分页链只剩 albums/artists, fetchListPage 不再有 songs 分支
    assert '["songs", "歌曲"]' not in js
    assert 'segment === "songs"' not in js
    # 资料库体里没有 bindTrackLists 了 (曲目行没了, 专辑/艺人/下载各有各的)
    library_bind = js[js.index("function bindLibraryBody")
                      :js.index("function playDownloadedRow")]
    assert "bindTrackLists" not in library_bind
    # 搜索框: sticky 包裹 + 不透明底衬, 钉层顶 (1.8.0: 只剩搜索页一处)
    sticky_css = html[html.index(".sticky-head {"):html.index(".album-hero")]
    assert "position: sticky; top: 0; z-index: 5;" in sticky_css
    assert "background: var(--bg);" in sticky_css
    assert js.count('<div class="sticky-head">') == 1      # 搜索页
    # 资料库段选择条 (.seg) 与语种 chips 随拆页撤掉: markup 不再产出, 样式一并清场
    assert 'class="seg"' not in js and ".seg {" not in html
    assert ".chip {" not in html and "chipsHTML" not in js
    # 1.8.0 界面重构的「全撤」: 顶罩首帧兜底 (独立竖屏 147px) 不在了
    assert "--sys-top-inset: 147px;" not in html
