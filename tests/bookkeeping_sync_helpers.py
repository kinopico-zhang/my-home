"""记账测试共享助手: 建账号 / 上行账目形状 / 同步请求。
拆自 test_bookkeeping.py (结构化重构, 代码逐字节未动)。"""
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
