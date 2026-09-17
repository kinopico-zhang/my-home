"""记账库表 (data/bookkeeping.db, 独立文件): 一笔账 + 类别树。

一笔账的 id 由客户端生成 (crypto.randomUUID), 上行按 id 幂等 —— 新建/
修改同一协议; 删除是墓碑 (deleted=True), 不真删行 (离线删除也要能同步
给别人); 记账人不由客户端声称: 服务端按会话落 created_by / updated_by
(uuid)。其余同步语义见 sync.py。"""
from datetime import datetime
from typing import Literal

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


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
