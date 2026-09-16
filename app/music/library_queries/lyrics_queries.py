"""歌词与来源查询: 单曲歌词 (可联网补) + 作词/作曲标签 (现读文件)。"""
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..library_database import Album, Track, music_directory
from ..library_lyrics_api import fetch_lyrics
from ..library_tags import looks_like_synced_lyrics, read_track_credits
from ..schemas import LyricsResponse, TrackCredits

# 求而不得的负缓存: track_id → 上次外网尝试的时刻。换曲预取 (歌词键置灰)
# 会频繁问没词的曲子, 不拦着就每换一曲打一次 LRCLIB。
_lyrics_fetch_misses: dict[int, float] = {}
_LYRICS_MISS_TTL = 24 * 3600


def lyrics_for_track(session: Session, track_id: int,
                     lyrics_api: tuple[bool, str] | None = None
                     ) -> LyricsResponse | None:
    """单曲歌词原文 (前端解析时间轴)。

    库里没有且给了歌词 API 配置时, 联网求一遍并写回索引 —— 下次离线也有,
    搜索歌词也搜得到; 求不到保持空 (24 小时内不再为同一首打外网)。"""
    track = session.get(Track, track_id)
    if track is None:
        return None
    if not track.lyrics and lyrics_api and lyrics_api[0]:
        if time.monotonic() - _lyrics_fetch_misses.get(track.id, 0.0) \
                > _LYRICS_MISS_TTL:
            album_title = session.scalar(
                select(Album.title).where(Album.id == track.album_id)) or ""
            fetched = fetch_lyrics(lyrics_api[1], track.title, track.artist,
                                   album_title)
            if fetched:
                track.lyrics = fetched
                track.lyrics_synced = looks_like_synced_lyrics(fetched)
                session.commit()
                _lyrics_fetch_misses.pop(track.id, None)
            else:
                _lyrics_fetch_misses[track.id] = time.monotonic()
    return LyricsResponse(track_id=track.id, lyrics=track.lyrics,
                          lyrics_synced=track.lyrics_synced)


def credits_for_track(session: Session, track_id: int) -> TrackCredits | None:
    """单曲 作词/作曲 标签 (现读文件, 只有部分歌带; 没标签 = 空串)。"""
    track = session.get(Track, track_id)
    if track is None:
        return None
    lyricist, composer = read_track_credits(
        music_directory() / track.file_path)
    return TrackCredits(lyricist=lyricist, composer=composer)
