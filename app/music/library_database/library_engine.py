"""My Music 的库引擎与路径状态 (进程级单例, 测试可整体重置)。

曲库目录 / 封面缓存目录跟着引擎走 (测试注入临时目录, 不碰真曲库);
封面缓存 = 库文件同目录下的 music-art/。默认路径可用环境变量覆盖。
"""
import os
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .library_models import MusicLibraryBase

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_DATABASE_URL = (os.environ.get("MYTESLA_MUSIC_DB")
                        or f"sqlite:///{PROJECT_DIR / 'data' / 'music.db'}")
DEFAULT_MUSIC_DIRECTORY = (os.environ.get("MYTESLA_MUSIC_DIR")
                           or "/share/Media/Music")


class _EngineState:
    """进程级引擎持有者 (避免 global 语句)。"""

    engine: Engine | None = None
    session_factory: sessionmaker[Session] | None = None
    database_url: str = ""
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
    """创建引擎 (缺省 data/music.db + /share/Media/Music)。"""
    if url is None:
        url = DEFAULT_DATABASE_URL
    if url.startswith("sqlite:///"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(
            parents=True, exist_ok=True)
    _engine.artwork_cache_directory = artwork_cache_directory_for(url)
    _engine.database_url = url
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
    _engine.database_url = ""
    _engine.music_directory = None
    _engine.artwork_cache_directory = None


def engine() -> Engine:
    """曲库索引引擎 (启动时建表用)。"""
    if _engine.engine is None:
        raise RuntimeError("曲库引擎未初始化 (init_engine 未调用)")
    return _engine.engine


def database_url() -> str:
    """当前库 URL (换曲库目录时同库重装配用)。"""
    if _engine.engine is None:
        raise RuntimeError("曲库引擎未初始化 (init_engine 未调用)")
    return _engine.database_url


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
