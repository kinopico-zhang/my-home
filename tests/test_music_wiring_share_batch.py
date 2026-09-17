"""My Music 分享页 1.8.6 批接线测试: 点句定位 + 禁双击/两指缩放 +
红键自动掀全屏页 + 全屏页封面 —— 静态文本断言, 不碰数据库。"""

from tests.music_static_files import share_page_js, share_page_shell


def test_music_186_share_batch():
    """1.8.6 分享页批 (用户点名): 歌词点一句跳到那句的进度 (app 同款
    data-time); 页面双击/两指捏不再放大 (viewport 收口 + body pan-y 双
    保险); 点大红播放键顺势掀开整页播放页; 整页播放页看不到封面修好
    (此前 setArt 错用在 <img> 上 —— 往 img 里塞子 img 永不渲染)。"""
    share = share_page_shell()               # markup + css
    share_all = share + share_page_js()      # 再拼脚本, 拆分前整页口径
    # 禁缩放: viewport meta 双保险 + 页面级 touch-action (app 同款收口)
    assert 'content="width=device-width, initial-scale=1, maximum-scale=1,' \
           ' user-scalable=no, viewport-fit=cover"' in share
    assert "touch-action: pan-y;" in share
    # 滑杆是手势区, 自带 touch-action 不被 body 的 pan-y 抢走
    assert 'input[type="range"] { touch-action: none; }' in share
    # 点句定位: 行带 data-time (解析器的时间轴, 纯文本词恒 -1), 点击跳
    # 进度并退出"暂停跟唱", 紧跟的 timeupdate 把新当前句滚回中央
    assert 'data-time="${line.timeSeconds}"' in share_all
    assert 'const line = event.target.closest(".lyrics-line");' in share_all
    assert "if (time >= 0) audio.currentTime = time;" in share_all
    assert "lyricsFollowPaused = false;" in share_all
    # 红键一按掀全屏页 (迷你条的播键不掀)
    assert '$("#hero-play").addEventListener("click", () => {' in share_all
    assert "togglePlay();\n  openFullPlayer();" in share_all
    # 封面修复: #fp-art 本尊是 <img>, 直接挂 src (app 同款), 不再走
    # 给容器 div 用的 setArt
    assert '$("#fp-art").src = artURL(track);' in share_all
