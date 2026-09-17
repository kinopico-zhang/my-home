"""账号管理测试: 管理员边界, 用户列表不漏 uuid, 自助改名改密,
邀请链接送达兜底, 徽章位置。
拆自 test_accounts.py (结构化重构, 代码逐字节未动)。"""
from pathlib import Path

from fastapi.testclient import TestClient

from app import config
import app.main as m

from tests.account_test_helpers import _register, _admin


def test_accounts_admin_only(usersdb):
    other, _ = _register(usersdb)
    # 普通账号: 列表/签发/撤销全部 403
    assert other.get("/accounts/api/users").status_code == 403
    assert other.post("/accounts/api/invitations",
                      json={"days": 7}).status_code == 403
    assert other.get("/accounts/api/invitations").status_code == 403
    assert other.delete("/accounts/api/invitations/x").status_code == 403
    # 未登录: 401
    anon = TestClient(m.app)
    assert anon.get("/accounts/api/users").status_code == 401


def test_accounts_user_list_no_uuid_leak(usersdb, client):
    _admin(client)
    _register(usersdb, "家里那位")
    users = client.get("/accounts/api/users").json()
    assert len(users) == 2
    assert users[0]["is_admin"] is True                    # 管理员在前
    assert users[1] == {"name": "家里那位", "is_admin": False,
                        "created_at": users[1]["created_at"]}
    assert "uuid" not in users[1] and "uuid" not in users[0]


# ---------------------------------------------------------------- 自助账号
def test_rename_keeps_session_and_uuid(usersdb):
    other, _ = _register(usersdb)
    before = other.get("/api/me").json()
    assert before["name"] == "二号账号"
    r = other.post("/api/account/name", json={"name": "新名字"})
    assert r.status_code == 200
    assert r.json() == {"name": "新名字", "is_admin": False}
    # 会话不掉线 (uuid 没变)
    assert other.get("/api/me").json()["name"] == "新名字"
    assert other.get("/bookkeeping").status_code == 200
    # 改成管理员的名字 → 占用
    r = other.post("/api/account/name", json={"name": config.AUTH_USER})
    assert r.status_code == 400
    # 改回自己的名字 → 允许 (no-op)
    assert other.post("/api/account/name",
                      json={"name": "新名字"}).status_code == 200


def test_password_change(usersdb):
    other, _ = _register(usersdb, "家里那位", "password123")
    # 旧密码错 → 400
    r = other.post("/api/account/password",
                   json={"old_password": "wrong-old", "new_password": "newpass456"})
    assert r.status_code == 400
    assert "旧密码" in r.json()["detail"]
    # 改成功: 会话不掉线, 新密码能登录, 旧密码不行
    r = other.post("/api/account/password",
                   json={"old_password": "password123",
                         "new_password": "newpass456"})
    assert r.status_code == 200
    assert other.get("/api/me").status_code == 200
    fresh = TestClient(m.app)
    assert fresh.post("/api/login",
                      json={"user": "家里那位", "password": "newpass456"}
                      ).status_code == 200
    assert fresh.post("/api/login",
                      json={"user": "家里那位", "password": "password123"}
                      ).status_code == 401


def test_me_requires_login(client):
    assert client.get("/api/me").status_code == 401


# ---------------------------------------------------------------- 邀请链接分发
def test_invite_copy_ios_safari_fallbacks():
    """iOS Safari 在 HTTP 站点没有异步剪贴板 API (isSecureContext=false),
    execCommand 退化路必须先 focus 再选中再同步拷贝 (2026-09-13 用户实测
    复制落空: 旧版对 textarea 用 Range 选 —— 它没有 DOM 子节点选不中,
    还没 focus、元素移出视口); 拷贝整条路被拒时拉系统分享面板兜底,
    链接一定送得出去。"""
    js = (Path(m.__file__).parent / "home" / "static"
          / "link-delivery.js").read_text(encoding="utf-8")
    assert "navigator.clipboard && window.isSecureContext" in js
    assert "ta.focus({ preventScroll: true })" in js   # iOS: 聚焦后选区才建立
    assert "ta.setSelectionRange(0, text.length)" in js
    assert "ta.readOnly = true" in js                  # 只读聚焦不弹键盘
    assert "navigator.share" in js                     # 兜底: 分享面板 (含「拷贝」)
    # 不许再犯: textarea 没有 DOM 子节点, Range 选不中它
    assert "selectNodeContents(ta)" not in js


def test_admin_badge_outside_name_cell():
    """管理员徽章是 .usr-row 的 flex 子元素, 不能在 .usr-name 里 —— 那格有
    overflow:hidden (长名省略号), inline 徽章的下半 (含下边框) 会伸出行盒
    被裁掉 (2026-09-13 用户抓到「椭圆框只有上半」)。"""
    base = Path(m.__file__).parent / "home" / "static"
    js = (base / "accounts.js").read_text(encoding="utf-8")
    assert '<div class="usr-name">${esc(u.name)}</div>' in js   # 名字格先闭合
    assert 'usr-badge">管理员</span>` : "")' in js              # 徽章是行级片段
    assert "${esc(u.name)}<span" not in js                      # 不许塞回名字格
    css = (base / "css" / "accounts-page.css").read_text(encoding="utf-8")   # 样式拆去了 css/
    assert "flex: none; font-size: 10.5px; line-height: 1" in css  # 自立行高
