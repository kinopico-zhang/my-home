"""鉴权 / 路由 / 中间件测试。"""
import hashlib
import hmac
import re
import struct
import time
import zlib
from pathlib import Path

from fastapi.testclient import TestClient

from app import authentication, config
import app.main as m


def _unfilter_png(raw: bytes, w: int, ch: int) -> list[bytearray]:
    """逆 PNG 行滤镜 (8-bit, 滤镜 0-4), 返回每行的 RGB(A) 字节 (不引 Pillow)。"""
    stride = w * ch + 1
    rows: list[bytearray] = []
    for y in range(len(raw) // stride):
        f = raw[y * stride]
        row = bytearray(raw[y*stride+1:(y+1)*stride])
        up = rows[y - 1] if y else None
        for x in range(w * ch):
            a = row[x - ch] if x >= ch else 0
            b = up[x] if up is not None else 0
            c = up[x - ch] if up is not None and x >= ch else 0
            if f == 1:
                row[x] = (row[x] + a) & 255
            elif f == 2:
                row[x] = (row[x] + b) & 255
            elif f == 3:
                row[x] = (row[x] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                row[x] = (row[x] + (a if pa <= pb and pa <= pc
                                    else b if pb <= pc else c)) & 255
        rows.append(row)
    return rows


# ---------------------------------------------------------------- 登录
def test_login_ok_sets_cookie_attributes(client):
    r = client.post("/tesla/api/login",
                    json={"user": config.AUTH_USER, "password": config.AUTH_PASS})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "auth=" in cookie
    assert "path=/tesla" in cookie       # cookie 只挂在 /tesla 下
    assert "httponly" in cookie
    assert "max-age=" in cookie          # 90 天
    assert "samesite=lax" in cookie


def test_login_wrong_password_returns_reason(client):
    r = client.post("/tesla/api/login",
                    json={"user": config.AUTH_USER, "password": "nope"})
    assert r.status_code == 401
    assert r.json()["detail"] == "账号或密码错误"


def test_login_rate_limited_after_5_failures(client):
    for _ in range(5):
        r = client.post("/tesla/api/login",
                        json={"user": config.AUTH_USER, "password": "nope"})
        assert r.status_code == 401
    r = client.post("/tesla/api/login",
                    json={"user": config.AUTH_USER, "password": "nope"})
    assert r.status_code == 429
    assert "尝试次数过多" in r.json()["detail"]
    # 锁定期间正确密码也进不去
    r = client.post("/tesla/api/login",
                    json={"user": config.AUTH_USER, "password": config.AUTH_PASS})
    assert r.status_code == 429


def test_token_roundtrip_tamper_and_expiry():
    assert authentication.check_token(authentication.make_token())
    assert not authentication.check_token("")
    assert not authentication.check_token("garbage")
    assert not authentication.check_token("1.2.3")
    # 有效期但签名被篡改
    exp = str(int(time.time()) + 100)
    assert not authentication.check_token(f"{exp}.deadbeef")
    # 已过期的合法签名
    exp = str(int(time.time()) - 1)
    secret = authentication._secret.value  # pylint: disable=protected-access
    sig = hmac.new(secret, exp.encode(), hashlib.sha256).hexdigest()
    assert not authentication.check_token(f"{exp}.{sig}")


def test_logout_rotates_secret_and_revokes(client):
    client.post("/tesla/api/login",
                json={"user": config.AUTH_USER, "password": config.AUTH_PASS})
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


def test_apple_touch_icon_opaque_with_padding():
    """iOS 主屏图标: 不透明纯白底 (透明底被 iOS 合成纯黑) + Tesla 红 T 居中留边。
    旧版 T 铺满整个画布还带 Alpha → 添加到主屏幕后 logo 过大且黑底。"""
    path = Path(m.__file__).parent / "static" / "apple-touch-icon.png"
    with path.open("rb") as fh:
        d = fh.read()
    w, h = struct.unpack(">II", d[16:24])
    ctype = d[25]
    assert (w, h) == (180, 180)
    assert ctype in (2, 6), f"应是 RGB/RGBA, 实际类型 {ctype}"

    # 纯 Python 解码 (无 Pillow 依赖): 拼出 IDAT 后逆滤镜
    ch = {2: 3, 6: 4}[ctype]
    pos, idat = 8, b""
    while pos < len(d):
        ln, typ = struct.unpack(">I4s", d[pos:pos+8])
        if typ == b"IDAT":
            idat += d[pos+8:pos+8+ln]
        pos += 12 + ln
    rows = _unfilter_png(zlib.decompress(idat), w, ch)

    def px(x, y):
        return tuple(rows[y][x*ch:x*ch+3])

    if ch == 4:   # 带 Alpha 则必须全不透明 (透明像素在主屏上变黑)
        assert all(rows[y][x*4+3] == 255
                   for y in range(h) for x in range(0, w, 9))
    # 满出血白底, 四角纯白 (iOS 自己切圆角, 不能预切)
    for x, y in [(0, 0), (w-1, 0), (0, h-1), (w-1, h-1)]:
        assert px(x, y) == (255, 255, 255)
    # T 标居中, 是 Tesla 红
    assert px(w//2, h//2) == (232, 33, 39)
    # 上下左右各留 ≥18px (10%) 白边: logo 不再铺满画布
    assert px(18, h//2) == (255, 255, 255)
    assert px(w-1-18, h//2) == (255, 255, 255)
    assert px(w//2, 18) == (255, 255, 255)
    assert px(w//2, h-1-18) == (255, 255, 255)


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
    for path, cur in (("/tesla/charging", "充电"), ("/tesla/map", "足迹"),
                      ("/tesla/trips", "行程")):
        html = auth.get(path).text
        assert 'class="nav-menu"' in html, path
        assert '<nav class="tabs">' not in html, path       # 平铺页签已删
        for href in ("/tesla/charging", "/tesla/map", "/tesla/trips"):
            assert f'href="{href}"' in html, (path, href)
        mt = re.search(r"<summary>(.*?)<svg", html)         # summary = 当前页名 + 折叠箭头
        assert mt and mt.group(1) == cur, (path, mt and mt.group(1))
