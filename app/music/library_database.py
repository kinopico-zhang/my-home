"""My Music 的库引擎 + 表结构 (data/music.db, 独立 SQLite 文件)。

曲库本体 (/share/Media/Music) 始终只读 —— 这里只存扫描出来的索引:
艺人 / 专辑 / 曲目三级, 附歌词全文 (服务端 LIKE 搜歌词) 与 script 语言标记
(MusicBrainz 刮削自带, 没有就按标题文字检测); 另有每人自己的播放记录
(play_stats, 最近播放的原料)。默认路径可用环境变量覆盖。
"""
import os
from pathlib import Path
from typing import Final, Iterator

from sqlalchemy import (ForeignKey, String, UniqueConstraint, create_engine,
                        text)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import (DeclarativeBase, Mapped, Session, mapped_column,
                            sessionmaker)

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_DATABASE_URL = (os.environ.get("MYTESLA_MUSIC_DB")
                        or f"sqlite:///{PROJECT_DIR / 'data' / 'music.db'}")
DEFAULT_MUSIC_DIRECTORY = (os.environ.get("MYTESLA_MUSIC_DIR")
                           or "/share/Media/Music")

# 能扫进索引的音频扩展名 → 格式名; 浏览器播不了的 (tak/dsf/ape) 也进索引
AUDIO_EXTENSION_FORMATS = {
    ".flac": "flac", ".mp3": "mp3", ".m4a": "m4a", ".ogg": "ogg",
    ".opus": "opus", ".wav": "wav", ".aac": "aac",
    ".tak": "tak", ".dsf": "dsf", ".ape": "ape",
}
# <audio> 能直接播的 (其余格式前端置灰; 转码以后再说)
BROWSER_PLAYABLE_FORMATS = frozenset({
    "flac", "mp3", "m4a", "ogg", "opus", "wav", "aac",
})


class MusicLibraryBase(DeclarativeBase):
    """曲库索引库基类 (data/music.db, 独立文件)。"""


class Artist(MusicLibraryBase):
    """艺人 = 曲库的一级目录 (目录名是归并键, 名字取 albumartist 标签)。"""

    __tablename__ = "artists"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(default="")
    sort_name: Mapped[str] = mapped_column(default="", index=True)  # artistsort 标签
    directory: Mapped[str] = mapped_column(String, unique=True)     # 相对曲库根
    poster_file: Mapped[str] = mapped_column(default="")            # 目录里的 poster.*
    search_keys: Mapped[str] = mapped_column(default="")            # 拼音/简繁检索键


class Album(MusicLibraryBase):
    """专辑 = 艺人下的二级目录 (目录名含刮削器的 [hex] 尾巴, 标题取标签)。"""

    __tablename__ = "albums"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(default="")
    artist_id: Mapped[int] = mapped_column(ForeignKey("artists.id"),
                                           index=True)
    year: Mapped[int] = mapped_column(default=0)
    directory: Mapped[str] = mapped_column(String, unique=True)     # 相对曲库根
    added_at: Mapped[float] = mapped_column(default=0.0)            # 旗下曲目入库最晚时刻
    track_count: Mapped[int] = mapped_column(default=0)
    duration_seconds: Mapped[float] = mapped_column(default=0.0)
    has_artwork: Mapped[bool] = mapped_column(default=False)        # 曲目内嵌封面
    search_keys: Mapped[str] = mapped_column(default="")            # 拼音/简繁检索键


class Track(MusicLibraryBase):
    """一首歌: 文件路径是唯一键, mtime/size 变了才重读标签 (增量重扫)。"""

    __tablename__ = "tracks"

    id: Mapped[int] = mapped_column(primary_key=True)
    album_id: Mapped[int] = mapped_column(ForeignKey("albums.id"),
                                          index=True)
    title: Mapped[str] = mapped_column(default="")
    artist: Mapped[str] = mapped_column(default="")      # 这一首的演唱者
    track_number: Mapped[int] = mapped_column(default=0)
    disc_number: Mapped[int] = mapped_column(default=1)
    duration_seconds: Mapped[float] = mapped_column(default=0.0)
    file_path: Mapped[str] = mapped_column(String, unique=True)     # 相对曲库根
    file_size: Mapped[int] = mapped_column(default=0)
    file_mtime: Mapped[float] = mapped_column(default=0.0)
    file_format: Mapped[str] = mapped_column(default="")
    script: Mapped[str] = mapped_column(default="")      # Latn/Jpan/Hant/Hans/Kore…
    lyrics: Mapped[str] = mapped_column(default="")      # lrc 原文或纯文本
    lyrics_synced: Mapped[bool] = mapped_column(default=False)
    has_artwork: Mapped[bool] = mapped_column(default=False)  # 内嵌封面 (专辑封面取材)
    added_at: Mapped[float] = mapped_column(default=0.0)      # 入库时刻 (首插记, 重扫不改)
    search_keys: Mapped[str] = mapped_column(default="")      # 拼音/简繁检索键


class Playlist(MusicLibraryBase):
    """播放列表: Plex 同步的 (is_local=False, 全量替换) + 应用内自建的
    (is_local=True, 同步不动它们, 只有接口能增删)。"""

    __tablename__ = "playlists"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    position: Mapped[int] = mapped_column(default=0)      # 列表内成员的排序档
    track_count: Mapped[int] = mapped_column(default=0)
    duration_seconds: Mapped[float] = mapped_column(default=0.0)
    plex_playlist_id: Mapped[int] = mapped_column(default=0)   # 源库 id (溯源/幂等)
    is_local: Mapped[bool] = mapped_column(default=False)  # 应用内自建 (同步保留)


class PlaylistItem(MusicLibraryBase):
    """播放列表成员 (position 是 Plex 的千分步序号; added_locally =
    应用内长按加进来的 —— 同步时这些成员保留, 其余以 Plex 为准)。"""

    __tablename__ = "playlist_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    playlist_id: Mapped[int] = mapped_column(ForeignKey("playlists.id"),
                                             index=True)
    track_id: Mapped[int] = mapped_column(ForeignKey("tracks.id"),
                                          index=True)
    position: Mapped[int] = mapped_column(default=0)
    added_locally: Mapped[bool] = mapped_column(default=False)


class PlayStat(MusicLibraryBase):
    """一个人的播放记录 (user+track 一行, 重播只推进时刻/次数)。

    最近播放按人算 —— 账号体系全站共享, 这里只存 uuid 不建外键
    (账号库是另一个文件, 跨库不 JOIN)。"""

    __tablename__ = "play_stats"
    __table_args__ = (UniqueConstraint("user_uuid", "track_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_uuid: Mapped[str] = mapped_column(index=True)
    track_id: Mapped[int] = mapped_column(ForeignKey("tracks.id"), index=True)
    last_played_at: Mapped[float] = mapped_column(default=0.0)  # epoch 秒
    play_count: Mapped[int] = mapped_column(default=1)


class _EngineState:
    """进程级引擎持有者 (避免 global 语句)。"""

    engine: Engine | None = None
    session_factory: sessionmaker[Session] | None = None
    music_directory: Path | None = None
    artwork_cache_directory: Path | None = None


_engine = _EngineState()


def artwork_cache_directory_for(url: str) -> Path:
    """库 URL → 封面缓存目录: SQLite 放库文件旁的 music-art/, 其他库落 data/。"""
    if url.startswith("sqlite:///"):
        return Path(url.removeprefix("sqlite:///")).parent / "music-art"
    return Path("data") / "music-art"


def init_engine(url: str | None = None,
                library_directory: Path | None = None) -> None:
    """创建引擎 (缺省 data/music.db + /share/Media/Music)。

    曲库目录 / 封面缓存目录跟着引擎走 (测试注入临时目录, 不碰真曲库);
    封面缓存 = 库文件同目录下的 music-art/。"""
    if url is None:
        url = DEFAULT_DATABASE_URL
    if url.startswith("sqlite:///"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(
            parents=True, exist_ok=True)
    _engine.artwork_cache_directory = artwork_cache_directory_for(url)
    _engine.music_directory = library_directory or Path(DEFAULT_MUSIC_DIRECTORY)
    _engine.engine = create_engine(url, connect_args={"check_same_thread": False})
    _engine.session_factory = sessionmaker(_engine.engine,
                                           expire_on_commit=False)


def dispose_engine() -> None:
    """释放连接池 (测试隔离也用它)。"""
    if _engine.engine is not None:
        _engine.engine.dispose()
    _engine.engine = None
    _engine.session_factory = None
    _engine.music_directory = None
    _engine.artwork_cache_directory = None


def engine() -> Engine:
    """曲库索引引擎 (启动时建表用)。"""
    if _engine.engine is None:
        raise RuntimeError("曲库引擎未初始化 (init_engine 未调用)")
    return _engine.engine


def music_directory() -> Path:
    """曲库根目录 (音频/封面文件都从这里找)。"""
    if _engine.music_directory is None:
        raise RuntimeError("曲库引擎未初始化 (init_engine 未调用)")
    return _engine.music_directory


def artwork_cache_directory() -> Path:
    """封面缓存目录 (库文件同目录的 music-art/)。"""
    if _engine.artwork_cache_directory is None:
        raise RuntimeError("曲库引擎未初始化 (init_engine 未调用)")
    return _engine.artwork_cache_directory


def session_factory() -> sessionmaker[Session]:
    """曲库索引会话工厂。"""
    if _engine.session_factory is None:
        raise RuntimeError("曲库引擎未初始化 (init_engine 未调用)")
    return _engine.session_factory


def get_db() -> Iterator[Session]:
    """FastAPI 依赖: 每请求一个曲库会话, 请求结束自动关闭。"""
    with session_factory()() as session:  # pylint: disable=not-callable
        yield session


def create_all() -> None:
    """建表 (启动时调用)。"""
    MusicLibraryBase.metadata.create_all(engine())


# 老库升级要补的列: 列名 → 列定义 (create_all 只建新表, 不 ALTER 旧表)
_COLUMN_MIGRATIONS: Final[dict[str, dict[str, str]]] = {
    "tracks": {"added_at": "REAL NOT NULL DEFAULT 0",
               "search_keys": "TEXT NOT NULL DEFAULT ''"},
    "albums": {"search_keys": "TEXT NOT NULL DEFAULT ''"},
    "artists": {"search_keys": "TEXT NOT NULL DEFAULT ''"},
    "playlists": {"is_local": "BOOLEAN NOT NULL DEFAULT 0"},
    "playlist_items": {"added_locally": "BOOLEAN NOT NULL DEFAULT 0"},
}


def ensure_columns() -> None:
    """给已存在的老表补缺失的列 (SQLite ADD COLUMN, 带默认值不重写行)。"""
    with engine().begin() as connection:
        for table_name, columns in _COLUMN_MIGRATIONS.items():
            present = {row[1] for row in
                       connection.execute(text(f"PRAGMA table_info({table_name})"))}
            for column_name, column_definition in columns.items():
                if column_name not in present:
                    connection.execute(text(
                        f"ALTER TABLE {table_name} ADD COLUMN "
                        f"{column_name} {column_definition}"))
