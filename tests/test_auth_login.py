"""登录会话测试: cookie 属性, 错密限速, token 往返/篡改/过期,
旧版两段 token, 退出只清本机。
拆自 test_auth.py (结构化重构, 代码逐字节未动)。"""
import hashlib
import hmac
import time

from fastapi.testclient import TestClient

from app import account_store, authentication, config
import app.main as m


def test_login_ok_sets_cookie_attributes(client):
    r = client.post("/api/login",
                    json={"user": config.AUTH_USER, "password": config.AUTH_PASS})
    assert r.status_code == 200
    # 两个 set-cookie: 删旧 path=/tesla 残留 + 签新 path=/ (门厅 + 两应用共用)
    cookies = "; ".join(c.lower() for c in r.headers.get_list("set-cookie"))
    assert "auth=" in cookies
    assert "path=/;" in cookies, cookies          # 新 cookie 挂全站 (非 /tesla 子路径)
    assert "httponly" in cookies
    assert "max-age=" in cookies                  # 90 天
    assert "samesite=lax" in cookies
    assert "path=/tesla" in cookies, cookies      # 旧 cookie 同帧删除


def test_login_wrong_password_returns_reason(client):
    r = client.post("/api/login",
                    json={"user": config.AUTH_USER, "password": "nope"})
    assert r.status_code == 401
    assert r.json()["detail"] == "账号或密码错误"


def test_login_rate_limited_after_5_failures(client):
    for _ in range(5):
        r = client.post("/api/login",
                        json={"user": config.AUTH_USER, "password": "nope"})
        assert r.status_code == 401
    r = client.post("/api/login",
                    json={"user": config.AUTH_USER, "password": "nope"})
    assert r.status_code == 429
    assert "尝试次数过多" in r.json()["detail"]
    # 锁定期间正确密码也进不去
    r = client.post("/api/login",
                    json={"user": config.AUTH_USER, "password": config.AUTH_PASS})
    assert r.status_code == 429


def test_token_roundtrip_tamper_and_expiry():
    uuid = "ab" * 16
    assert authentication.check_token(authentication.make_token(uuid)) == uuid
    assert authentication.check_token("") is None
    assert authentication.check_token("garbage") is None
    assert authentication.check_token("1.2.3") is None       # 三段但签名格式不对
    # 有效期但签名被篡改
    exp = str(int(time.time()) + 100)
    assert authentication.check_token(f"{exp}.{uuid}.deadbeef") is None
    # 已过期的合法签名
    exp = str(int(time.time()) - 1)
    secret = authentication._secret.value  # pylint: disable=protected-access
    sig = hmac.new(secret, f"{exp}.{uuid}".encode(), hashlib.sha256).hexdigest()
    assert authentication.check_token(f"{exp}.{uuid}.{sig}") is None


def test_legacy_two_part_token_maps_to_admin(usersdb, client):
    """单用户时代的两段式 cookie 仍被认 (按管理员处理, 升级不强制重登 Tesla 侧)。"""
    exp = str(int(time.time()) + 100)
    legacy = authentication._legacy_secret.value  # pylint: disable=protected-access
    sig = hmac.new(legacy, exp.encode(), hashlib.sha256).hexdigest()
    token = f"{exp}.{sig}"
    assert authentication.check_token(token) == authentication.LEGACY_ADMIN
    client.cookies.set("auth", token)
    assert client.get("/tesla/charging").status_code == 200
    me = client.get("/api/me").json()
    assert me["is_admin"] is True
    # 过期的旧 cookie 无效
    exp = str(int(time.time()) - 1)
    sig = hmac.new(legacy, exp.encode(), hashlib.sha256).hexdigest()
    assert authentication.check_token(f"{exp}.{sig}") is None


def test_logout_clears_only_this_device(client, usersdb):
    """登出只清本设备 cookie, 不再轮换会话密钥 (多用户下轮换会踢掉所有人)。"""
    other = account_store.create_user(usersdb, "二号账号", "password123")
    client.post("/api/login",
                json={"user": config.AUTH_USER, "password": config.AUTH_PASS})
    assert client.get("/tesla/charging").status_code == 200
    assert client.post("/api/logout").status_code == 200
    r = client.get("/tesla/charging", follow_redirects=False)
    assert r.status_code == 302
    # 应用页的登录跳转留在本应用 scope 内 (带原地址, 登录完回来)
    assert r.headers["location"] == "/tesla/login?next=%2Ftesla%2Fcharging"
    # 别人的会话不受影响
    client2 = TestClient(m.app)
    client2.cookies.set("auth", authentication.make_token(other.uuid))
    assert client2.get("/tesla/charging").status_code == 200
    assert client2.get("/bookkeeping").status_code == 200
