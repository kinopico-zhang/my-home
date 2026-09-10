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
    for path in ("/tesla", "/tesla/charging", "/tesla/map", "/tesla/trips"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 302, path
        assert r.headers["location"] == "/tesla/login", path


def test_unauthed_apis_return_401_json(client):
    for path in ("/tesla/charging/api/summary", "/tesla/charging/api/sessions",
                 "/tesla/map/api/summary", "/tesla/map/api/tracks",
                 "/tesla/map/api/tracks/detail", "/tesla/map/api/config",
                 "/tesla/trips/api/sessions", "/tesla/trips/api/1/track"):
        r = client.get(path)
        assert r.status_code == 401, path
        assert r.json() == {"detail": "未登录"}


def test_public_paths_accessible_without_login(client):
    assert client.get("/tesla/login").status_code == 200
    assert client.get("/tesla/static/echarts.min.js").status_code == 200
    assert client.get("/tesla/static/gcj02.js").status_code == 200
    assert client.get("/tesla/static/trackutil.js").status_code == 200
    assert client.get("/tesla/static/favicon.svg").status_code == 200
    # Safari 不支持 SVG favicon, 需要 PNG 版 + iOS 主屏 apple-touch-icon
    assert client.get("/tesla/static/favicon-32.png").status_code == 200
    assert client.get("/tesla/static/apple-touch-icon.png").status_code == 200


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
                         ("/tesla/trips", "My Tesla"),
                         ("/tesla/login", "My Tesla")):
        r = auth.get(path)
        assert r.status_code == 200, path
        assert marker in r.text, path


def test_static_js_must_revalidate(client):
    """JS 工具文件必须 no-cache 重新校验, 否则浏览器启发式缓存用旧版 (动画曾因此冻住)。"""
    r = client.get("/tesla/static/trackutil.js")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache"


def test_cache_control_headers(auth):
    """API 响应禁止缓存 (配置更新要即时生效), 页面允许缓存但必须重新校验。"""
    assert auth.get("/tesla/map/api/config?_=1").headers["cache-control"] == "no-store"
    # 未登录的 401 API 响应同样禁缓存
    anon = TestClient(m.app)
    assert anon.get("/tesla/map/api/config").headers["cache-control"] == "no-store"
    for path in ("/tesla/charging", "/tesla/map", "/tesla/trips", "/tesla/login"):
        assert auth.get(path).headers["cache-control"] == "no-cache", path


def test_all_pages_declare_png_and_touch_icons(client):
    """每个页面都要有 PNG favicon + apple-touch-icon (Safari/iOS 看不见 SVG)。"""
    for page in ["login", "index", "map", "trips"]:
        r = client.get(f"/tesla/{page}", follow_redirects=False)
        if r.status_code == 302:      # 未登录跳转的页面换成登录后取
            r = client.get(f"/tesla/{page}")
        body = r.text
        assert 'favicon-32.png' in body, f"{page} 缺 PNG favicon"
        assert 'apple-touch-icon.png' in body, f"{page} 缺 apple-touch-icon"


def test_all_pages_have_collapsible_nav_menu(auth):
    """页签收进 details 菜单: summary 显示当前页名, 菜单含全部三个链接。"""
    import re
    for path, cur in (("/tesla/charging", "充电"), ("/tesla/map", "足迹"),
                      ("/tesla/trips", "行程")):
        html = auth.get(path).text
        assert 'class="nav-menu"' in html, path
        assert '<nav class="tabs">' not in html, path       # 平铺页签已删
        for href in ("/tesla/charging", "/tesla/map", "/tesla/trips"):
            assert f'href="{href}"' in html, (path, href)
        m = re.search(r"<summary>(.*?)<svg", html)           # summary = 当前页名 + 折叠箭头
        assert m and m.group(1) == cur, (path, m and m.group(1))
