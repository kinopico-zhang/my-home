"""同步合并 (多人各持离线副本, 同步时 LWW):

- id 由客户端生成 (crypto.randomUUID), 上行按 id 幂等 —— 新建/修改同一协议;
- updated_at 是客户端版本时间, 谁的更新谁覆盖 (同秒冲突几乎不发生于家庭账本);
- synced_at 是服务端接收时间, 作为增量下发游标 (只用服务端时钟, 免客户端
  时钟漂移导致"永远收不到");
- 删除是墓碑 (deleted=True), 不真删行 —— 离线删除也要能同步给别人。"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..schemas import EntryIn
from .models import Entry

MAX_SYNC_UPLOAD = 1000   # 单次上行上限 (防脏客户端一次灌爆)


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
