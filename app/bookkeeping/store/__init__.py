"""记账应用的数据层门面: 库表 + 引擎 + 同步合并 (全部自持, 不依赖主应用)。

旧 store.py (235 行) 按域拆成包: models / engine / sync / categories;
调用方一律 `from app.bookkeeping import store` 后按属性取用, 拆分后
不变 (结构化重构)。同步合并的 LWW 规则见 sync.py。"""
from .categories import category_tree, seed_default_categories
from .engine import (
    DEFAULT_DB_URL,
    create_all,
    dispose_engine,
    engine,
    get_db,
    init_engine,
    migrate_columns,
    session_factory,
)
from .models import Category, Entry, EntryBase
from .sync import MAX_SYNC_UPLOAD, sync_entries

__all__ = [
    "DEFAULT_DB_URL",
    "MAX_SYNC_UPLOAD",
    "Category",
    "Entry",
    "EntryBase",
    "category_tree",
    "create_all",
    "dispose_engine",
    "engine",
    "get_db",
    "init_engine",
    "migrate_columns",
    "seed_default_categories",
    "session_factory",
    "sync_entries",
]
