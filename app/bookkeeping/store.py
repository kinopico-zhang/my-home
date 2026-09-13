"""记账应用的数据层: 库表 + 引擎 + 同步合并 (全部自持, 不依赖主应用)。

库是独立文件 (data/bookkeeping.db, 与 My Tesla 业务库 / 账号库分开),
默认路径可用 MYTESLA_BOOKKEEPING_DB 覆盖。

合并规则 (多人各持离线副本, 同步时 LWW):
- id 由客户端生成 (crypto.randomUUID), 上行按 id 幂等 —— 新建/修改同一协议;
- updated_at 是客户端版本时间, 谁的更新谁覆盖 (同秒冲突几乎不发生于家庭账本);
- synced_at 是服务端接收时间, 作为增量下发游标 (只用服务端时钟, 免客户端
  时钟漂移导致"永远收不到");
- 删除是墓碑 (deleted=True), 不真删行 —— 离线删除也要能同步给别人;
- 记账人不由客户端声称: 服务端按会话落 created_by / updated_by (uuid)。
"""
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Literal

from sqlalchemy import String, UniqueConstraint, create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import (DeclarativeBase, Mapped, Session, mapped_column,
                            sessionmaker)

from .default_categories import EXPENSE_CATEGORIES, INCOME_CATEGORIES
from .schemas import CategoryGroup, CategoryTree, EntryIn

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB_URL = (os.environ.get("MYTESLA_BOOKKEEPING_DB")
                  or f"sqlite:///{PROJECT_DIR / 'data' / 'bookkeeping.db'}")

MAX_SYNC_UPLOAD = 1000   # 单次上行上限 (防脏客户端一次灌爆)


class EntryBase(DeclarativeBase):
    """记账库基类 (data/bookkeeping.db, 独立文件)。"""


class Entry(EntryBase):
    """一笔账: id 由客户端生成 (离线可建), 同步上来按 id 幂等合并。

    created_by / updated_by 是账号 uuid (记账人: 每一笔都记是谁记的,
    展示时由账号库解析成名称); updated_at 是客户端版本时间 (LWW 合并),
    synced_at 是服务端接收时间 (增量下发的游标)。

    deleted 是墓碑: 离线删除也要能同步给其他人, 不真删行。"""

    __tablename__ = "entries"

    id: Mapped[str] = mapped_column(primary_key=True)     # 客户端 uuid
    date: Mapped[str] = mapped_column(String)             # 记账日期 YYYY-MM-DD
    time: Mapped[str] = mapped_column(String, default="") # 时刻 HH:MM (可空)
    amount: Mapped[float]                                 # 元 (恒正, 收支看 kind)
    kind: Mapped[Literal["expense", "income"]] = mapped_column(String)
    category: Mapped[str] = mapped_column(String, default="")
    tags: Mapped[str] = mapped_column(String, default="") # 标签, 逗号连接 (≤5 个)
    note: Mapped[str] = mapped_column(String, default="")
    created_by: Mapped[str]                                # 记账人 (账号 uuid)
    created_at: Mapped[datetime]
    updated_by: Mapped[str]
    updated_at: Mapped[datetime]                          # 客户端版本时间
    synced_at: Mapped[datetime]                           # 服务端接收时间
    deleted: Mapped[bool] = mapped_column(default=False)


class Category(EntryBase):
    """类别树 (大类 + 子类), 种子数据来自挖财账本导出 (default_categories)。

    条目 (entries.category) 不建外键, 存组合名: 大类 "餐饮" 或
    "大类/子类" ("餐饮/早餐") —— 自明、离线可造、旧平铺值兼容。"""

    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("kind", "parent", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, index=True)
    kind: Mapped[Literal["expense", "income"]] = mapped_column(String)
    parent: Mapped[str] = mapped_column(String, default="")   # "" = 大类
    sort: Mapped[int] = mapped_column(default=0)          # 同层展示顺序


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


def _naive_utc(value: datetime) -> datetime:
    """统一成库里的裸 UTC (pydantic 解析出的 Z/+00:00 都剥掉 tzinfo)。"""
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def sync_entries(session: Session, user_uuid: str, entries: list[EntryIn],
                 last_sync: datetime | None) -> tuple[list[Entry], datetime]:
    """上行合并 + 增量下发, 返回 (该下发的行, 服务端本次时间)。

    last_sync 为 None (首同步) 时全量下发; 否则只给 synced_at 更晚的行
    (含本次刚收下的 —— 客户端按 LWW 自合并, 回声无害)。
    """
    if len(entries) > MAX_SYNC_UPLOAD:
        raise ValueError(f"单次最多同步 {MAX_SYNC_UPLOAD} 条")
    now = datetime.utcnow()
    for entry in entries:
        updated_at = _naive_utc(entry.updated_at)
        stored = session.get(Entry, entry.id)
        if stored is None:
            session.add(Entry(
                id=entry.id, date=entry.date, time=entry.time,
                amount=round(entry.amount, 2),
                kind=entry.kind, category=entry.category, note=entry.note,
                tags=",".join(entry.tags),
                deleted=entry.deleted,
                created_by=user_uuid, created_at=now,
                updated_by=user_uuid, updated_at=updated_at, synced_at=now))
        elif updated_at > stored.updated_at:      # LWW: 客户端版本更新才覆盖
            stored.date = entry.date
            stored.time = entry.time
            stored.amount = round(entry.amount, 2)
            stored.kind = entry.kind
            stored.category = entry.category
            stored.note = entry.note
            stored.tags = ",".join(entry.tags)
            stored.deleted = entry.deleted
            stored.updated_by = user_uuid
            stored.updated_at = updated_at
            stored.synced_at = now
    session.commit()
    query = select(Entry).order_by(Entry.date.desc(), Entry.created_at)
    if last_sync is not None:
        query = query.where(Entry.synced_at > _naive_utc(last_sync))
    rows = list(session.execute(query).scalars().all())
    return rows, now


def seed_default_categories() -> None:
    """类别表为空时种入默认树 (挖财导出内容); 非空不动 —— 以库为准。"""
    with session_factory()() as session:  # pylint: disable=not-callable
        if session.execute(select(Category.id).limit(1)).scalar() is not None:
            return
        rows: list[Category] = []
        for kind, tree in (("expense", EXPENSE_CATEGORIES),
                           ("income", INCOME_CATEGORIES)):
            for top, children in tree:
                rows.append(Category(name=top, kind=kind, parent="",
                                     sort=len(rows)))
                rows.extend(Category(name=child, kind=kind, parent=top,
                                     sort=len(rows)) for child in children)
        session.add_all(rows)
        session.commit()


def category_tree(session: Session) -> CategoryTree:
    """类别树 → 支出/收入各自的大类 + 子类, 按种子的 sort 保序
    (给前端弹层画两级胶囊用)。"""
    rows = session.execute(select(Category).order_by(Category.sort, Category.id)
                           ).scalars().all()
    children: dict[str, list[str]] = {}
    for row in rows:
        if row.parent:
            children.setdefault(row.parent, []).append(row.name)
    tree = CategoryTree(expense=[], income=[])
    for row in rows:
        if not row.parent:
            group = CategoryGroup(name=row.name,
                                  children=children.get(row.name, []))
            if row.kind == "expense":
                tree.expense.append(group)
            else:
                tree.income.append(group)
    return tree
