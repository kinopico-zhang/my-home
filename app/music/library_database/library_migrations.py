"""老库升级: 给已存在的旧表补缺失的列 (SQLite ADD COLUMN, 带默认值不重写行)。

create_all 只建新表不 ALTER 旧表; 整张新表 (music_settings /
cellular_usage) create_all 自己会补建, 这里只管旧表的新列。
"""
from typing import Final

from sqlalchemy import text

from .library_engine import engine

# 列名 → 列定义
_COLUMN_MIGRATIONS: Final[dict[str, dict[str, str]]] = {
    "tracks": {"added_at": "REAL NOT NULL DEFAULT 0",
               "search_keys": "TEXT NOT NULL DEFAULT ''"},
    "albums": {"search_keys": "TEXT NOT NULL DEFAULT ''"},
    "artists": {"search_keys": "TEXT NOT NULL DEFAULT ''"},
    "playlists": {"is_local": "BOOLEAN NOT NULL DEFAULT 0",
                  "cover_version": "INTEGER NOT NULL DEFAULT 0"},
    "playlist_items": {"added_locally": "BOOLEAN NOT NULL DEFAULT 0"},
}


def ensure_columns() -> None:
    """给已存在的老表补缺失的列。"""
    with engine().begin() as connection:
        for table_name, columns in _COLUMN_MIGRATIONS.items():
            present = {row[1] for row in
                       connection.execute(text(f"PRAGMA table_info({table_name})"))}
            for column_name, column_definition in columns.items():
                if column_name not in present:
                    connection.execute(text(
                        f"ALTER TABLE {table_name} ADD COLUMN "
                        f"{column_name} {column_definition}"))
