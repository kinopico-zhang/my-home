"""记账同步测试: 离线优先 LWW / 墓碑 / 游标 / 记账人服务端盖章 / 跨库取名。

协议要点: id 客户端生成, 记账人 (created_by / updated_by) 服务端按会话落
(客户端说了不算), synced_at 是服务端时间作为增量游标, 删除是墓碑。
"""
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app import account_store, config
import app.main as m


def _user(usersdb, name):
    """管理员直接建一个账号 + 登录态 client (不走邀请, 各用例独立)。"""
    account_store.ensure_admin(usersdb, config.AUTH_USER, config.AUTH_PASS)
    user = account_store.create_user(usersdb, name, "password123")
    client = TestClient(m.app)
    r = client.post("/api/login", json={"user": name, "password": "password123"})
    assert r.status_code == 200
    return client, user


def _entry(entry_id, updated_at, **kw):
    """一条上行账目 (客户端形状)。"""
    return {
        "id": entry_id, "date": "2026-09-13", "amount": 25.5,
        "kind": "expense", "category": "餐饮", "note": "午饭",
        "deleted": False, "updated_at": updated_at,
        **kw,
    }


def _sync(client, entries=(), last_sync=None):
    r = client.post("/bookkeeping/api/sync", json={
        "entries": list(entries), "last_sync": last_sync})
    assert r.status_code == 200, r.text
    return r.json()


def test_sync_stamps_identity_and_resolves_names(usersdb, bkdb):
    """记账人由服务端按会话落: 甲上传的账, 下行带甲的名字 (客户端没传也不算数)。"""
    jia, jia_user = _user(usersdb, "记账人甲")
    data = _sync(jia, [_entry("aaaa1111", "2026-09-13T08:00:00Z")])
    assert len(data["entries"]) == 1
    out = data["entries"][0]
    assert out["created_by_name"] == "记账人甲"
    assert out["updated_by_name"] == "记账人甲"
    # 库里落的是甲的 uuid (跨库解析), 金额取两位
    from app.bookkeeping.store import Entry  # pylint: disable=import-outside-toplevel
    row = bkdb.get(Entry, "aaaa1111")
    assert row.created_by == jia_user.uuid
    assert row.amount == 25.5


def test_sync_lww_newer_wins_older_rejected(usersdb, bkdb):
    """同 id 再传: updated_at 更新才覆盖 (更新人换成上传者), 更旧不动。"""
    jia, _ = _user(usersdb, "记账人甲")
    yi, _ = _user(usersdb, "记账人乙")
    _sync(jia, [_entry("aaaa1111", "2026-09-13T08:00:00Z", note="甲记的")])
    # 乙带着更旧版本同步: 不覆盖
    _sync(yi, [_entry("aaaa1111", "2026-09-13T07:00:00Z", note="乙的旧版")])
    data = _sync(yi)   # 全量拉 (last_sync 空)
    assert data["entries"][0]["note"] == "甲记的"
    # 乙带着更新版本: 覆盖, 更新人变乙
    _sync(yi, [_entry("aaaa1111", "2026-09-13T09:00:00Z", note="乙改的")])
    data = _sync(yi)
    out = [e for e in data["entries"] if e["id"] == "aaaa1111"][0]
    assert out["note"] == "乙改的"
    assert out["created_by_name"] == "记账人甲"      # 记账人不变
    assert out["updated_by_name"] == "记账人乙"      # 这版是乙改的


def test_sync_tombstone_not_hard_delete(usersdb, bkdb):
    """删除是墓碑: 行还在库里, 下行带 deleted=true。"""
    jia, _ = _user(usersdb, "记账人甲")
    _sync(jia, [_entry("aaaa1111", "2026-09-13T08:00:00Z")])
    _sync(jia, [_entry("aaaa1111", "2026-09-13T09:00:00Z", deleted=True)])
    from app.bookkeeping.store import Entry  # pylint: disable=import-outside-toplevel
    assert bkdb.get(Entry, "aaaa1111") is not None      # 没被物理删
    data = _sync(jia)
    assert data["entries"][0]["deleted"] is True


def test_sync_cursor_incremental(usersdb):
    """游标 = 上次 server_now: 只下发这之后动的行 (别人的新账)。"""
    jia, _ = _user(usersdb, "记账人甲")
    yi, _ = _user(usersdb, "记账人乙")
    first = _sync(jia, [_entry("aaaa1111", "2026-09-13T08:00:00Z")])
    # 乙首同步 (游标空): 全量, 拿到甲的账
    yi_first = _sync(yi)
    assert {e["id"] for e in yi_first["entries"]} == {"aaaa1111"}
    # 甲又记了一笔, 乙带着游标来: 只拿到新的这笔
    _sync(jia, [_entry("bbbb2222", "2026-09-13T09:00:00Z")],
          last_sync=first["server_now"])
    yi_second = _sync(yi, last_sync=yi_first["server_now"])
    assert {e["id"] for e in yi_second["entries"]} == {"bbbb2222"}


def test_sync_echoes_own_upload(usersdb):
    """上传后按游标再拉: 自己刚传的也在下行里 (回声), 客户端按 LWW 自合并。"""
    jia, _ = _user(usersdb, "记账人甲")
    first = _sync(jia)
    second = _sync(jia, [_entry("aaaa1111", "2026-09-13T08:00:00Z")],
                   last_sync=first["server_now"])
    assert {e["id"] for e in second["entries"]} == {"aaaa1111"}


def test_sync_amount_rounding_and_ordering(usersdb):
    """金额取两位 (12.345 → 12.35); 下行按日期倒序。"""
    jia, _ = _user(usersdb, "记账人甲")
    _sync(jia, [_entry("aaaa1111", "2026-09-13T08:00:00Z", amount=12.345),
                _entry("bbbb2222", "2026-09-12T08:00:00Z", amount=8)])
    data = _sync(jia)
    assert [e["id"] for e in data["entries"]] == ["aaaa1111", "bbbb2222"]
    assert data["entries"][0]["amount"] == 12.35


def test_sync_upload_limit(usersdb):
    """单次上行上限 1000 (防脏客户端灌爆): schema 层先拒 (422),
    bookkeeping_store.MAX_SYNC_UPLOAD 是第二道防线。"""
    jia, _ = _user(usersdb, "记账人甲")
    flood = [_entry(f"id{i:04d}", "2026-09-13T08:00:00Z") for i in range(1001)]
    r = jia.post("/bookkeeping/api/sync", json={"entries": flood})
    assert r.status_code == 422


def test_sync_input_validation(usersdb):
    """坏条目 422: 日期格式 / 金额非正 / kind 非法 / id 太短。"""
    jia, _ = _user(usersdb, "记账人甲")
    bad_cases = [
        _entry("aaaa1111", "2026-09-13T08:00:00Z", date="2026/09/13"),
        _entry("aaaa1111", "2026-09-13T08:00:00Z", amount=0),
        _entry("aaaa1111", "2026-09-13T08:00:00Z", amount=-5),
        _entry("aaaa1111", "2026-09-13T08:00:00Z", kind="transfer"),
        _entry("short", "2026-09-13T08:00:00Z"),
        _entry("aaaa1111", "2026-09-13T08:00:00Z", note="x" * 201),
    ]
    for i, entry in enumerate(bad_cases):
        r = jia.post("/bookkeeping/api/sync", json={"entries": [entry]})
        assert r.status_code == 422, f"case {i} 应被拒"


def test_sync_edit_propagates_to_other_user(usersdb):
    """端到端: 甲记 → 乙收 → 乙改 → 甲收到乙的版本 (记账人还是甲, 改的人是乙)。"""
    jia, _ = _user(usersdb, "记账人甲")
    yi, _ = _user(usersdb, "记账人乙")
    jia_first = _sync(jia, [_entry("aaaa1111", "2026-09-13T08:00:00Z")])
    yi_first = _sync(yi)               # 乙首同步: 全量, 拿到甲的账
    got = yi_first["entries"][0]
    assert got["created_by_name"] == "记账人甲"
    yi_last = _sync(yi, [_entry("aaaa1111", "2026-09-13T10:00:00Z",
                                amount=30, note="乙改的金额")],
                    last_sync=yi_first["server_now"])
    jia_second = _sync(jia, last_sync=jia_first["server_now"])   # 甲用自己的游标
    out = [e for e in jia_second["entries"] if e["id"] == "aaaa1111"][0]
    assert out["amount"] == 30
    assert out["created_by_name"] == "记账人甲"
    assert out["updated_by_name"] == "记账人乙"


def test_sync_two_databases_separate(usersdb, tmp_path):
    """记账库与账号库是两个独立 SQLite 文件 (用户要求分开)。"""
    _user(usersdb, "记账人甲")
    users_file = tmp_path / "users.db"
    bookkeeping_file = tmp_path / "bookkeeping.db"
    assert users_file.exists() and bookkeeping_file.exists()
    assert users_file.read_bytes() != bookkeeping_file.read_bytes()
