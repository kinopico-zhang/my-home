"""My Music 播放交互接线测试: 搜索页/锁屏进度, 歌词动画,
点播从头, 音量 UI 撤除, 词标行平齐, 歌词行匹配纯逻辑。"""


from app.music.library_tags import extract_album_artwork
from tests.music_audio_seed import _write_audio
from tests.music_static_files import (
    MUSIC_STATIC, music_browser_js, music_page_shell, music_player_js,
)


def test_music_search_page_and_lockscreen_wiring():
    """1.4.1 后半批接线: 搜索页语种筛选撤掉 (2026-09-16 资料库也撤了) +
    页面不许横向溢出 (标题/右列文字收口, 长艺人名撑不宽) +
    锁屏进度随暂停/跳句/变速重报真实位置。"""
    html = music_page_shell()
    js = music_browser_js()
    player = music_player_js()
    # 语种筛选两处都撤净 (1.4.1 撤搜索页, 2026-09-16 再撤资料库):
    # chips 行/常量/接口参数全不该再出现
    assert "search-chips" not in js and "search-chips" not in html
    assert "lib-chips" not in js and "chipsHTML" not in js
    assert "&language=" not in js and "language:" not in js
    # 横向溢出: html 兜底禁横滑 + 行内标题包收缩层 + 右列可省略
    assert "overflow: hidden" in html   # 固定壳 (2026-09-16): 连 x 带 y 一起锁
    assert ".t-title-text" in html and "t-title-text" in js
    t_time_block = html.split(".t-time {", 1)[1].split("}", 1)[0]
    assert "min-width: 0" in t_time_block and "ellipsis" in t_time_block
    # 锁屏进度: 暂停 (速率报 0) / 跳句 / 变速 / timeupdate 都重报
    assert "function syncPositionState" in player
    assert '"play", "pause", "seeked", "ratechange"' in player
    assert "audio.paused ? 0 : audio.playbackRate" in player
    assert "setPositionState" in player
    assert "syncPositionState();" in player       # timeupdate 里也在报


def test_music_lyrics_animation_wiring():
    """歌词滚动动画接线: 当前行放大清晰/其余模糊退后 (CSS 缓动) +
    rAF 逐帧缓动滚动, 手指一按就让位 (JS)。"""
    html = music_page_shell()
    player = music_player_js()
    assert ".lyrics-line {" in html and "filter: blur(3px)" in html   # 其余模糊
    assert ".lyrics-line.active" in html and "font-size: 26px" in html \
        and "blur(0)" in html                                          # 当前行放大清晰
    assert "transition: filter .5s" in html                            # 状态切换也缓动
    for frag in ["function scrollLyricsTo", "function lyricsScrollFrame",
                 "function cancelLyricsScroll", "lyricsScrollRaf",
                 '"pointerdown", cancelLyricsScroll']:   # 手动滚动优先于动画
        assert frag in player, f"music-player.js 缺少 {frag}"


def test_music_click_play_starts_from_beginning():
    """点播一律从头 (用户报"有时点一首歌从一半播起, 怀疑存了每首的进度"):
    并没有按曲存进度 —— 冷启动恢复在 preload=none 的 audio 上写
    currentTime 是"待生效进度", Safari 会把它漏到之后点开的歌上。
    loadTrack 换源后显式归零兜底; 冷启动续听 (playerRestore) 不走
    loadTrack, 特性照旧。"""
    player = music_player_js()
    html = music_page_shell()
    load_track = player[player.index("function loadTrack"):
                        player.index("function prefetchNextTrack")]
    assert "audio.currentTime = 0;" in load_track  # 点播归零, 待生效进度不外漏
    assert 'preload="none"' in html          # 恢复态不拉元数据 (待生效进度的温床)
    restore = player[player.index("function playerRestore"):
                     player.index("function renderPlayerChrome")]
    assert "if (saved.time) audio.currentTime = saved.time;" in restore  # 续听保留


def test_music_volume_ui_removed():
    """音量条全平台撤除 (用户点名"音量条去掉吧"): iOS 的 audio.volume
    写了也白写, 1.5.0 的 WebAudio 增益又拖不动还脱开音量键 —— 桌面也
    不留了, 音量统一设备自己的键。回归: 旧的音量代码不许再爬回来。"""
    html = music_page_shell()
    player = music_player_js()
    for gone in ["AudioContext", "createGain", "createMediaElementSource",
                 "ensureVolumeRouting", "loadSavedVolume", "nativeVolumeWorks",
                 "applyVolume", "music-volume", "volume-off", "fp-volume"]:
        assert gone not in player, f"音量残留: {gone}"
        assert gone not in html, f"音量残留 (html): {gone}"


def test_music_lyrics_mark_row_badge():
    """词标 ❝: 行右侧图标簇的一员 (下载标前面), 17×17 与下载标同大、
    同 26px 高度框里垂直居中 —— 两个图标同一水平线, 不再像小上标;
    颜色同一档, 行右侧图标簇没有色差 (用户点名)。"""
    html = music_page_shell()
    js = music_browser_js()
    common = (MUSIC_STATIC / "js" / "music-common.js").read_text(encoding="utf-8")
    assert 'width="17" height="17"' in common              # 与下载标同大
    assert ".t-lyric" in html and "height: 26px" in html   # 与 .t-dl 同框高
    # 同色: 词标和下载标都是 ink-2 (下载完的勾加深到 ink-1 是另一态)
    lyric_block = html[html.index(".t-lyric {"):]
    assert "color: var(--ink-2)" in lyric_block[:lyric_block.index("}")]
    dl_block = html[html.index(".t-dl {"):]
    assert "color: var(--ink-2)" in dl_block[:dl_block.index("}")]
    # 挪出 .t-title: 行级元素, 排在下载标前面 (❝ 在前, 下载标在它后面)
    assert '${track.lyrics_available ? `<i class="t-lyric">' in js
    t_title_pos = js.index('<span class="t-title">')
    lyric_pos = js.index('<i class="t-lyric">${ICON_LYRICS}')
    dl_pos = js.index('<span class="t-dl${downloads.isDownloaded')
    assert t_title_pos < lyric_pos < dl_pos, "词标应排在标题之后、下载标之前"


def test_matching_lyric_line_pure():
    """歌词命中行: 剥时间轴/大小写不敏感; 全文没命中返回空串。"""
    from app.music.library_queries import _matching_lyric_line  # noqa: SLF001
    lyrics = "[00:01.00]Hello World\n[00:02.00]再见"
    assert _matching_lyric_line(lyrics, "hello") == "Hello World"
    assert _matching_lyric_line(lyrics, "再见") == "再见"
    assert _matching_lyric_line(lyrics, "不存在") == ""


def test_extract_artwork_empty_picture(tmp_path):
    """FLAC 带空 PICTURE 块 (data 为空) → 没有可用封面。"""
    path = _write_audio(tmp_path, "A/a.flac", picture=b"")
    assert extract_album_artwork(path) is None
