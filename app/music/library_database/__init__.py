"""My Music 的库引擎 + 表结构 (data/music.db, 独立 SQLite 文件)。

表结构在 library_models, 引擎/路径状态在 library_engine, 老库补列在
library_migrations; 这里聚合对外名面 (调用方统一 from ..library_database
import …, 不感知内部分层)。
"""
from .library_engine import (DEFAULT_DATABASE_URL, DEFAULT_MUSIC_DIRECTORY,
                             PROJECT_DIR, artwork_cache_directory,
                             artwork_cache_directory_for, create_all,
                             database_url, dispose_engine, engine, get_db,
                             init_engine, music_directory, session_factory)
from .library_migrations import ensure_columns
from .library_models import (AUDIO_EXTENSION_FORMATS,
                             BROWSER_PLAYABLE_FORMATS, Album, Artist,
                             CellularUsage, MusicLibraryBase, MusicSetting,
                             PlayStat, Playlist, PlaylistItem, ShareLink,
                             Track)

__all__ = [
    "AUDIO_EXTENSION_FORMATS", "BROWSER_PLAYABLE_FORMATS",
    "DEFAULT_DATABASE_URL", "DEFAULT_MUSIC_DIRECTORY", "PROJECT_DIR",
    "Album", "Artist", "CellularUsage", "MusicLibraryBase", "MusicSetting",
    "PlayStat", "Playlist", "PlaylistItem", "ShareLink", "Track",
    "artwork_cache_directory", "artwork_cache_directory_for", "create_all",
    "database_url", "dispose_engine", "engine", "ensure_columns", "get_db",
    "init_engine", "music_directory", "session_factory",
]
