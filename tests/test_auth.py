"""鉴权 / 路由 / 中间件测试。"""
import hashlib
import hmac
import time

from fastapi.testclient import TestClient

import app.main as m


# ---------------------------------------------------------------- 登录
def test_login_ok_sets_cookie_attributes(client):
    r = client.post("/tesla/api/login",
                    json={"user": m.AUTH_USER, "password": m.AUTH_PASS})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "auth=" in cookie
    assert "path=/tesla" in cookie       # cookie 只挂在 /tesla 下
    assert "httponly" in cookie
    assert "max-age=" in cookie          # 90 天
    assert "samesite=lax" in cookie


def test_login_wrong_password_returns_reason(client):
    r = client.post("/tesla/api/login",
                    json={"user": m.AUTH_USER, "password": "nope"})
    assert r.status_code == 401
    assert r.json()["detail"] == "账号或密码错误"


def test_login_rate_limited_after_5_failures(client):
    for _ in range(5):
        r = client.post("/tesla/api/login",
                        json={"user": m.AUTH_USER, "password": "nope"})
        assert r.status_code == 401
    r = client.post("/tesla/api/login",
                    json={"user": m.AUTH_USER, "password": "nope"})
    assert r.status_code == 429
    assert "尝试次数过多" in r.json()["detail"]
    # 锁定期间正确密码也进不去
    r = client.post("/tesla/api/login",
                    json={"user": m.AUTH_USER, "password": m.AUTH_PASS})
    assert r.status_code == 429


def test_token_roundtrip_tamper_and_expiry():
    assert m._check_token(m._make_token())
    assert not m._check_token("")
    assert not m._check_token("garbage")
    assert not m._check_token("1.2.3")
    # 有效期但签名被篡改
    exp = str(int(time.time()) + 100)
    assert not m._check_token(f"{exp}.deadbeef")
    # 已过期的合法签名
    exp = str(int(time.time()) - 1)
    sig = hmac.new(m.SECRET, exp.encode(), hashlib.sha256).hexdigest()
    assert not m._check_token(f"{exp}.{sig}")


def test_logout_rotates_secret_and_revokes(client):
    client.post("/tesla/api/login",
                json={"user": m.AUTH_USER, "password": m.AUTH_PASS})
    assert client.get("/tesla/charging").status_code == 200
    assert client.post("/tesla/api/logout").status_code == 200
    r = client.get("/tesla/charging", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/tesla/login"


# ---------------------------------------------------------------- 中间件
def test_unauthed_pages_redirect_to_login(client):
    for path in ("/tesla", "/tesla/charging", "/tesla/map"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 302, path
        assert r.headers["location"] == "/tesla/login", path


def test_unauthed_apis_return_401_json(client):
    for path in ("/tesla/charging/api/summary", "/tesla/charging/api/sessions",
                 "/tesla/map/api/summary", "/tesla/map/api/tracks",
                 "/tesla/map/api/config"):
        r = client.get(path)
        assert r.status_code == 401, path
        assert r.json() == {"detail": "未登录"}


def test_public_paths_accessible_without_login(client):
    assert client.get("/tesla/login").status_code == 200
    assert client.get("/tesla/static/echarts.min.js").status_code == 200
    assert client.get("/tesla/static/gcj02.js").status_code == 200


def test_old_paths_are_gone(client):
    assert client.get("/login").status_code == 404
    assert client.get("/api/summary").status_code == 404
    assert client.post("/api/login", json={}).status_code == 404


# ---------------------------------------------------------------- 页面路由
def test_root_redirect_chain(auth):
    r = auth.get("/", follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (302, "/tesla")
    r = auth.get("/tesla", follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (302, "/tesla/charging")


def test_pages_served_after_login(auth):
    for path, marker in (("/tesla/charging", "My Tesla"),
                         ("/tesla/map", "My Tesla"),
                         ("/tesla/login", "My Tesla")):
        r = auth.get(path)
        assert r.status_code == 200, path
        assert marker in r.text, path


def test_cache_control_headers(auth):
    """API 响应禁止缓存 (配置更新要即时生效), 页面允许缓存但必须重新校验。"""
    assert auth.get("/tesla/map/api/config?_=1").headers["cache-control"] == "no-store"
    # 未登录的 401 API 响应同样禁缓存
    anon = TestClient(m.app)
    assert anon.get("/tesla/map/api/config").headers["cache-control"] == "no-store"
    for path in ("/tesla/charging", "/tesla/map", "/tesla/login"):
        assert auth.get(path).headers["cache-control"] == "no-cache", path
