"""账号测试共享助手: 凭邀请注册普通账号 / 管理员登录态。
拆自 test_accounts.py (结构化重构, 代码逐字节未动)。"""
from fastapi.testclient import TestClient

from app import account_store, config
import app.main as m


def _register(usersdb, name="二号账号", password="password123"):
    """凭邀请注册一个普通账号, 返回 (该账号登录态的 client, 邀请令牌)。"""
    invitation = account_store.create_invitation(usersdb, 7)
    client = TestClient(m.app)
    r = client.post("/api/register",
                    json={"invite": invitation.token, "name": name,
                          "password": password})
    assert r.status_code == 200, r.text
    return client, invitation.token


def _admin(client):
    """管理员登录态的 client (env 账密 = 种入的管理员)。"""
    r = client.post("/api/login",
                    json={"user": config.AUTH_USER, "password": config.AUTH_PASS})
    assert r.status_code == 200
    return client
