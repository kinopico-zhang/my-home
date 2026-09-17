"""记账库引擎: 独立文件 data/bookkeeping.db (与 My Tesla 业务库 / 账号库
分开), 默认路径可用 MYTESLA_BOOKKEEPING_DB 覆盖。

create_all 只建新表; 已有生产库要补的列写在 migrate_columns (幂等)。"""
import os
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import EntryBase

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_DB_URL = (os.environ.get("MYTESLA_BOOKKEEPING_DB")
                  or f"sqlite:///{PROJECT_DIR / 'data' / 'bookkeeping.db'}")


# 引擎持有者 (与主应用各自的库同构: 启动 init, 关闭 dispose, 测试注入别的 SQLite)
class _EngineState:
    """进程级引擎持有者 (避免 global 语句)。"""

    engine: Engine | None = None
    factory: sessionmaker[Session] | None = None


_state = _EngineState()


def init_engine(url: str | None = None) -> None:
    """创建引擎 (缺省 data/bookkeeping.db)。"""
    if url is None:
        url = DEFAULT_DB_URL
    if url.startswith("sqlite:///"):
        parent = Path(url.removeprefix("sqlite:///")).parent
        if str(parent):
            parent.mkdir(parents=True, exist_ok=True)
    _state.engine = create_engine(url, connect_args={"check_same_thread": False})
    _state.factory = sessionmaker(_state.engine, expire_on_commit=False)


def dispose_engine() -> None:
    """释放连接池 (测试隔离也用它)。"""
    if _state.engine is not None:
        _state.engine.dispose()
    _state.engine = None
    _state.factory = None


def engine() -> Engine:
    """记账库引擎 (启动时建表用)。"""
    if _state.engine is None:
        raise RuntimeError("记账库引擎未初始化 (init_engine 未调用)")
    return _state.engine


def session_factory() -> sessionmaker[Session]:
    """记账库会话工厂。"""
    if _state.factory is None:
        raise RuntimeError("记账库引擎未初始化 (init_engine 未调用)")
    return _state.factory


def get_db() -> Iterator[Session]:
    """FastAPI 依赖: 每请求一个记账库会话, 请求结束自动关闭。"""
    with session_factory()() as session:  # pylint: disable=not-callable
        yield session


def create_all() -> None:
    """建表 (启动时调用)。"""
    EntryBase.metadata.create_all(engine())


def migrate_columns(eng: Engine | None = None) -> None:
    """create_all 只建新表不改旧表: 已有生产库要补的列写在这里 (幂等)。"""
    if eng is None:
        eng = engine()
    with eng.begin() as conn:
        cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(entries)")}
        if "time" not in cols:     # v2.5: 记账时刻 HH:MM
            conn.exec_driver_sql(
                "ALTER TABLE entries ADD COLUMN time TEXT NOT NULL DEFAULT ''")
        if "tags" not in cols:     # v2.5: 标签 (逗号连接)
            conn.exec_driver_sql(
                "ALTER TABLE entries ADD COLUMN tags TEXT NOT NULL DEFAULT ''")
