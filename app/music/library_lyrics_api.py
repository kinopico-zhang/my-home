"""联网补歌词: 内嵌标签和同名 .lrc 都没有时, 向 LRCLIB 兼容的歌词 API 求一遍。

求到就写回索引 (tracks.lyrics) —— 之后离线也能看, 搜索歌词也搜得到;
求不到 (曲库没这首 / 断网 / 超时) 保持空, 前端照旧显示「没有歌词」。
"""
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

_TIMEOUT_SECONDS = 4.0
_MAX_LYRICS_BYTES = 20000      # 与扫描入库同一截断 (库里 lyrics 就存这么长)


def fetch_lyrics(api_base: str, title: str, artist: str,
                 album_title: str) -> str:
    """求一首的歌词 (优先带时间轴的); 任何失败都返回空串 (不抛, 不挡听歌)。"""
    query = urlencode({"artist_name": artist, "track_name": title,
                       "album_name": album_title})
    url = f"{api_base.rstrip('/')}/get?{query}"
    try:
        with urlopen(Request(url, headers={"User-Agent": "MyMusic/1.4"}),
                     timeout=_TIMEOUT_SECONDS) as response:
            if response.status != 200:
                return ""
            payload = json.loads(response.read().decode("utf-8", "replace"))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        return ""            # 404 / 断网 / 超时 / 坏 JSON: 都当求不到
    if not isinstance(payload, dict):
        return ""
    lyrics = payload.get("syncedLyrics") or payload.get("plainLyrics") or ""
    return str(lyrics)[:_MAX_LYRICS_BYTES]
