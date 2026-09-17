"""My Music 断网数据缓存接线测试 (1.8.4, 用户点名「断网之后播放列表都
打不开? 这些不都应该缓存到本地吗」) —— 静态文本断言, 不碰数据库。
拆自 test_music_page_wiring.py (文件超 200 行按域再拆)。"""

from tests.music_static_files import MUSIC_STATIC, music_browser_js


def test_music_184_offline_data_cache_batch():
    """1.8.4 批: SW 给 /music/api/ 的 GET (search 除外) 加数据档 ——
    网络优先断网回档, 401/403 清档防串账号, 退出登录也清。壳/封面/
    已下载音频本来就有各自的缓存, 数据这一环补上后联网打开过的页
    离线全能翻。"""
    sw = (MUSIC_STATIC / "sw.js").read_text(encoding="utf-8")
    js = music_browser_js()
    assert 'const DATA_CACHE = "music-data-v1";' in sw
    # search 除外: 词组合无限多, 缓存不值
    assert 'const DATA_PATTERN = /^\\/music\\/api\\/(?!search\\b)/;' in sw
    assert "serveApiData(request)" in sw and "trimDataCache(cache);" in sw
    assert "response.status === 401 || response.status === 403" in sw  # 换人清档
    assert "联网打开过一次就能离线看" in sw     # 断网没档的落地面
    assert 'name.startsWith("music-data-")' in sw    # 换版本号清旧档
    assert 'caches.delete("music-data-v1")' in js    # 退出登录也清 (换人不串号)
