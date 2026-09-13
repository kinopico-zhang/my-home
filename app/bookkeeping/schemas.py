"""记账应用的接口模型 (与主应用的 schemas 分开, 各管各的)。"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class EntryIn(BaseModel):
    """客户端上传的一笔账 (id 由客户端生成, 离线可建)。

    不带记账人字段: 服务端按会话落 created_by / updated_by,
    谁同步的这版就记谁 (每一笔都记是谁记的)。"""

    id: str = Field(min_length=8, max_length=64)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")    # 记账日期
    amount: float = Field(gt=0, le=1e9)                 # 元 (恒正, 收支看 kind)
    kind: Literal["expense", "income"]
    category: str = Field(default="", max_length=20)
    note: str = Field(default="", max_length=200)
    deleted: bool = False
    updated_at: datetime                                # 客户端版本时间 (LWW)


class EntryOut(BaseModel):
    """下发给客户端的账目 (记账人已解析成名称)。"""

    id: str
    date: str
    amount: float
    kind: Literal["expense", "income"]
    category: str
    note: str
    deleted: bool
    updated_at: datetime
    created_by_name: str
    updated_by_name: str


class SyncRequest(BaseModel):
    """同步请求: 上行本地条目 + 上次同步游标 (空 = 全量拉)。"""

    last_sync: datetime | None = None
    entries: list[EntryIn] = Field(default_factory=list, max_length=1000)


class SyncResponse(BaseModel):
    """同步应答: 该下发的条目 + 服务端本次时间 (下次同步的游标)。"""

    server_now: datetime
    entries: list[EntryOut]
