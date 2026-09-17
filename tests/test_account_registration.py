"""账号注册流程测试: 管理员种子只种一次, 注册全生命周期, 名称/
密码/邀请校验, 邀请状态。
拆自 test_accounts.py (结构化重构, 代码逐字节未动)。"""
from datetime import datetime, timedelta


from app import account_store, config

from tests.account_test_helpers import _admin


def test_ensure_admin_seeds_once(usersdb):
    """isolate 已种过管理员: 再调 ensure_admin 不重复种 (只种一次)。"""
    account_store.ensure_admin(usersdb, "管理员", "password123")
    users = account_store.list_users(usersdb)
    assert len(users) == 1                    # 没有第二个
    assert users[0].is_admin is True
    assert users[0].name == config.AUTH_USER  # 保持 env 种入的名字
    assert len(users[0].uuid) == 32           # uuid4().hex


# ---------------------------------------------------------------- 注册流程
def test_register_full_lifecycle(client, usersdb):
    invitation = account_store.create_invitation(usersdb, 1)
    # 进页先查状态: 可用
    r = client.get("/api/invite-status",
                   params={"invite": invitation.token})
    assert r.status_code == 200
    # 注册成功 = 自动登录 (新 cookie 落在 path=/)
    r = client.post("/api/register",
                    json={"invite": invitation.token, "name": "家里那位",
                          "password": "password123"})
    assert r.status_code == 200
    me = client.get("/api/me").json()
    assert me == {"name": "家里那位", "is_admin": False}   # 不含 uuid
    # 邀请一次一用: 状态与再注册都不行
    assert client.get("/api/invite-status",
                      params={"invite": invitation.token}).status_code == 400
    r = client.post("/api/register",
                    json={"invite": invitation.token, "name": "第三位",
                          "password": "password123"})
    assert r.status_code == 400
    assert "已被使用" in r.json()["detail"]


def test_register_validates_name_password_invite(client, usersdb):
    invitation = account_store.create_invitation(usersdb, 7)
    for name, password in (("", "password123"),       # 名字太短
                           ("a", "password123"),      # 名字 1 字符
                           ("带 空格", "password123"),  # 内部空白
                           ("名字", "12345")):        # 密码太短
        r = client.post("/api/register",
                        json={"invite": invitation.token, "name": name,
                              "password": password})
        assert r.status_code == 400, name
    # 名字重名 (管理员已种)
    r = client.post("/api/register",
                    json={"invite": invitation.token, "name": config.AUTH_USER,
                          "password": "password123"})
    assert r.status_code == 400
    assert "已被占用" in r.json()["detail"]
    # 环令牌
    r = client.post("/api/register",
                    json={"invite": "no-such-token", "name": "家里那位",
                          "password": "password123"})
    assert r.status_code == 400
    assert "无效" in r.json()["detail"]


def test_invitation_states(usersdb, client):
    _admin(client)
    # 签发档位: 只有 1/7/30
    assert client.post("/accounts/api/invitations",
                       json={"days": 5}).status_code == 400
    made = client.post("/accounts/api/invitations",
                       json={"days": 30}).json()
    assert made["token"] and made["expires_at"]
    # 撤销后不可用
    assert client.delete(f"/accounts/api/invitations/{made['token']}"
                         ).status_code == 200
    r = client.get("/api/invite-status", params={"invite": made["token"]})
    assert r.status_code == 400
    assert "撤销" in r.json()["detail"]
    # 已撤销的不能再撤销
    assert client.delete(f"/accounts/api/invitations/{made['token']}"
                         ).status_code == 400
    # 过期不可用 (直接把库里的截止时间改到过去)
    invitation = account_store.create_invitation(usersdb, 1)
    invitation.expires_at = datetime.utcnow() - timedelta(seconds=1)
    usersdb.commit()
    r = client.get("/api/invite-status", params={"invite": invitation.token})
    assert r.status_code == 400
    assert "过期" in r.json()["detail"]
    # 列表带全部状态字段 (前端现算有效/已注册/过期/已撤销)
    items = client.get("/accounts/api/invitations").json()
    assert {i["token"] for i in items} >= {made["token"], invitation.token}
    fields = {"token", "created_at", "expires_at", "used_at", "revoked"}
    assert fields <= set(items[0])
