"""鉴权 / 路由 / 中间件测试。"""
import hashlib
import hmac
import struct
import time
import zlib
from pathlib import Path

from fastapi.testclient import TestClient

from app import account_store, authentication, config
import app.main as m

# 全部业务页 (Tesla + 记账 + 账号管理 + 注册), 多处遍历用
ALL_PAGES = ["/tesla/login", "/tesla/register", "/tesla/charging", "/tesla/stats",
             "/tesla/chargemap", "/tesla/map", "/tesla/changelog", "/tesla/trips",
             "/tesla/groups", "/tesla/live", "/tesla/settings", "/tesla/accounts",
             "/bookkeeping"]


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
def test_all_pages_have_standalone_meta(auth):
    """全部页面 (含登录/注册/记账) 都带全屏 App meta。

    桌面图标是全屏 web app, 有独立 cookie 存储: 首次启动必然 302 到登录页。
    登录页一旦缺 meta, 整个 App 会被弹回 Safari 露地址栏, 之后再也回不去
    全屏 (2026-09-12 用户踩坑)。任何新增页面都必须带上。
    """
    for path in ALL_PAGES:
        html = auth.get(path).text
        assert 'name="apple-mobile-web-app-capable" content="yes"' in html, path
        assert 'content="black-translucent"' in html, path
        assert '<link rel="manifest" href="/tesla/static/manifest.json">' in html, path


def test_all_pages_disable_double_tap_zoom_on_controls(auth):
    """触屏双击控件不再整页放大 (2026-09-13 用户踩坑)。

    iOS 忽略 user-scalable=no, 双击按钮/链接/菜单会被 Safari 当双击缩放;
    touch-action: manipulation 只去掉双击缩放, 平移和捏合缩放保留
    (地图手势区是 div, 不受影响)。全站统一, 登录页也要有。
    """
    for path in ALL_PAGES:
        html = auth.get(path).text
        assert "button, a, summary { touch-action: manipulation; }" in html, path


def test_all_pages_have_refresh_button(auth):
    """每页顶栏都有刷新按钮 (2026-09-13 用户反馈: 不是每个页面都有)。

    行程页首倡的胶囊刷新按钮 (busy 时图标旋转) 铺到全部业务页; 每页接
    自己的重载入口 —— 列表页重拉后回顶, 地图页不带首载遮罩 (refresh(false)),
    设置页拉完设置再补司机列表; 记账页 = 立即同步, 账号页 = 重拉用户与邀请。
    """
    # 页面路径 -> (该页 JS 文件, 点击后接的重载调用)
    wiring = {
        "/tesla/charging": ("index.js", "await refetch();"),
        "/tesla/stats": ("stats.js", "await refetch();"),
        "/tesla/chargemap": ("chargemap.js", "await refresh(false);"),
        "/tesla/map": ("map.js", "await refresh(false);"),
        "/tesla/trips": ("trips.js", "await refreshList();"),
        "/tesla/groups": ("groups.js", "await load();"),
        "/tesla/live": ("live.js", "await poll();"),
        "/tesla/settings": ("settings.js", "await loadSettings();"),
        "/tesla/changelog": ("changelog.js", "await load();"),
        "/bookkeeping": ("bookkeeping.js", "await syncNow();"),
        "/tesla/accounts": ("accounts.js", "await loadAll();"),
    }
    for path, (js_file, call) in wiring.items():
        html = auth.get(path).text
        assert '<button id="refresh-btn"' in html, path        # 按钮在顶栏
        assert "refresh-spin" in html, path                    # busy 旋转动画
        js = auth.get(f"/tesla/static/{js_file}?v=1").text
        assert '$("#refresh-btn").addEventListener' in js, path
        assert call in js, f"{path} 刷新按钮没接上 {call}"
        # 刷新按钮始终顶栏最右: 有时间菜单的页菜单吃 auto 边距, 按钮跟在后面;
        # 没有的页 (分组/驾驶/设置/日志/记账/账号) 按钮自己吃 auto 边距
        if 'id="time-menu"' not in html:
            block = html[html.index("#refresh-btn {"):]
            assert "margin-left: auto" in block[:block.index("}")], path


def test_pages_remember_last_page(auth):
    """上次停留页: 业务页 head 挂 lastpage.js (冷启动在任何渲染前跳转,
    不闪启动页), 登录页/注册页不挂 (不是停留目标); 登录成功回上次页而非
    写死充电页。

    iOS 主屏图标每次都从添加时定格的 start_url 启动, 不记得停在哪页 ——
    localStorage 记 path+search, 冷启动 (sessionStorage 无标记) 且 standalone
    才 replace 过去; 行程弹层开合只动 URL 不重载, 靠 visibilitychange 补记。"""
    for path in [p for p in ALL_PAGES
                 if p not in ("/tesla/login", "/tesla/register")]:
        html = auth.get(path).text
        tag = '<script src="/tesla/static/lastpage.js?v=1"></script>'
        assert tag in html, path
        assert html.index(tag) < html.index("<title>"), "要放 <title> 前 (首渲染前执行)"
    assert "lastpage.js" not in auth.get("/tesla/login").text
    assert "lastpage.js" not in auth.get("/tesla/register").text
    # 登录成功: 回上次停留页 (白名单正则, 站外/坏值回落充电页) —— 逻辑在 login.js
    login_html = auth.get("/tesla/static/login.js?v=1").text
    assert 'localStorage.getItem("mytesla-last-page")' in login_html
    assert ("/^\\/(tesla\\/(charging|stats|chargemap|map|trips|groups|live|settings"
            "|changelog)|bookkeeping)(\\?|$)/.test(last)") in login_html

    r = auth.get("/tesla/static/lastpage.js")
    assert r.status_code == 200
    js = r.text
    for frag in [
        '"/tesla/charging", "/tesla/stats", "/tesla/chargemap",',   # 白名单业务页
        '"/bookkeeping"]',                                     # 记账页也记
        "PAGES.indexOf(path) === -1) return",                  # login/静态不记不跳
        "sessionStorage.getItem(LAUNCH)",                      # 冷启动判据 (会话标记)
        "catch (e) { return; }",                               # 隐私模式防回弹循环
        "navigator.standalone === true",                       # 只在主屏全屏 App 里跳
        'location.replace(saved)',                             # 目标过白名单才跳
        'if (document.hidden) record()',                       # 后台时补记 (弹层开合)
    ]:
        assert frag in js, f"lastpage.js 缺少 {frag}"


def test_webapp_manifest_scope_covers_all_apps(auth):
    """Web App Manifest: scope 放宽到 / 圈住 Tesla + 记账两个应用 —— 没有它,
    iOS 全屏 App 只认添加图标时的那个启动 URL, 跳到其他页面就当地址栏处理
    (2026-09-12 用户实测: 行程页加的图标, 切充电/足迹出 Safari 菜单, 切回行程
    又正常)。记账是 /bookkeeping 下的平行应用, 必须 +1 圈进来。"""
    r = auth.get("/tesla/static/manifest.json")
    assert r.status_code == 200
    manifest = r.json()
    assert manifest["scope"] == "/"
    assert manifest["display"] == "standalone"
    assert manifest["start_url"].startswith("/tesla/")
    assert any(i["sizes"] == "192x192" for i in manifest["icons"])
    assert any(i["sizes"] == "512x512" for i in manifest["icons"])
    for icon in ("/tesla/static/icon-192.png", "/tesla/static/icon-512.png"):
        assert auth.get(icon).status_code == 200, icon


def test_login_ok_sets_cookie_attributes(client):
    r = client.post("/tesla/api/login",
                    json={"user": config.AUTH_USER, "password": config.AUTH_PASS})
    assert r.status_code == 200
    # 两个 set-cookie: 删旧 path=/tesla 残留 + 签新 path=/ (Tesla + 记账共用)
    cookies = "; ".join(c.lower() for c in r.headers.get_list("set-cookie"))
    assert "auth=" in cookies
    assert "path=/;" in cookies, cookies          # 新 cookie 挂全站 (非 /tesla 子路径)
    assert "httponly" in cookies
    assert "max-age=" in cookies                  # 90 天
    assert "samesite=lax" in cookies
    assert "path=/tesla" in cookies, cookies      # 旧 cookie 同帧删除


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
    me = client.get("/tesla/api/me").json()
    assert me["is_admin"] is True
    # 过期的旧 cookie 无效
    exp = str(int(time.time()) - 1)
    sig = hmac.new(legacy, exp.encode(), hashlib.sha256).hexdigest()
    assert authentication.check_token(f"{exp}.{sig}") is None


def test_logout_clears_only_this_device(client, usersdb):
    """登出只清本设备 cookie, 不再轮换会话密钥 (多用户下轮换会踢掉所有人)。"""
    other = account_store.create_user(usersdb, "二号账号", "password123")
    client.post("/tesla/api/login",
                json={"user": config.AUTH_USER, "password": config.AUTH_PASS})
    assert client.get("/tesla/charging").status_code == 200
    assert client.post("/tesla/api/logout").status_code == 200
    r = client.get("/tesla/charging", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/tesla/login"
    # 别人的会话不受影响
    client2 = TestClient(m.app)
    client2.cookies.set("auth", authentication.make_token(other.uuid))
    assert client2.get("/tesla/charging").status_code == 200
    assert client2.get("/bookkeeping").status_code == 200


# ---------------------------------------------------------------- 中间件
def test_unauthed_pages_redirect_to_login(client):
    for path in ("/tesla", "/tesla/charging", "/tesla/stats", "/tesla/chargemap",
                 "/tesla/map", "/tesla/changelog", "/tesla/trips",
                 "/tesla/groups", "/tesla/live", "/tesla/settings",
                 "/tesla/accounts", "/bookkeeping"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 302, path
        assert r.headers["location"] == "/tesla/login", path


def test_unauthed_apis_return_401_json(client):
    for path in ("/tesla/charging/api/summary", "/tesla/charging/api/sessions",
                 "/tesla/map/api/summary", "/tesla/map/api/tracks",
                 "/tesla/map/api/tracks/detail", "/tesla/map/api/config",
                 "/tesla/trips/api/sessions", "/tesla/trips/api/1/track",
                 "/tesla/live/api/status",
                 "/tesla/changelog/api/entries",
                 "/tesla/api/me", "/tesla/accounts/api/users"):
        r = client.get(path)
        assert r.status_code == 401, path
        assert r.json() == {"detail": "未登录"}
    r = client.post("/bookkeeping/api/sync", json={"entries": []})
    assert r.status_code == 401
    assert r.json() == {"detail": "未登录"}


def test_public_paths_accessible_without_login(client):
    assert client.get("/tesla/login").status_code == 200
    assert client.get("/tesla/register").status_code == 200    # 注册页公开
    for asset in ("/tesla/static/echarts.min.js", "/tesla/static/gcj02.js",
                  "/tesla/static/trackutil.js", "/tesla/static/favicon.svg",
                  "/tesla/static/register.js", "/tesla/static/login.js",
                  "/bookkeeping/static/bookkeeping.js",      # 记账静态也放行
                  "/bookkeeping/static/bookkeeping-merge.js"):
        assert client.get(asset).status_code == 200, asset
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
                         ("/tesla/stats", "My Tesla"),
                         ("/tesla/chargemap", "My Tesla"),
                         ("/tesla/map", "My Tesla"),
                         ("/tesla/trips", "My Tesla"),
                         ("/tesla/login", "My Home"),
                         ("/tesla/register", "My Home"),
                         ("/tesla/changelog", "My Tesla"),
                         ("/tesla/groups", "My Tesla"),
                         ("/tesla/live", "My Tesla"),
                         ("/tesla/settings", "My Tesla"),
                         ("/tesla/accounts", "My Tesla"),
                         ("/bookkeeping", "家庭记账")):
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


def test_all_pages_declare_png_and_touch_icons(auth):
    """每个页面都要有 PNG favicon + apple-touch-icon (Safari/iOS 看不见 SVG)。"""
    for path in ALL_PAGES:
        body = auth.get(path).text
        assert "favicon-32.png" in body, f"{path} 缺 PNG favicon"
        assert "apple-touch-icon.png" in body, f"{path} 缺 apple-touch-icon"


def test_all_pages_have_brand_menu(auth):
    """品牌即入口: My Tesla 是下拉按钮, 展开是三个页面 + 退出登录, 当前页高亮。"""
    for path, cur, slug in (("/tesla/charging", "充电记录", "charging"),
                            ("/tesla/map", "足迹地图", "map"),
                            ("/tesla/trips", "行程列表", "trips"),
                            ("/tesla/live", "当前驾驶", "live"),
                            ("/bookkeeping", "家庭记账", None),
                            ("/tesla/accounts", "账号管理", "accounts")):
        html = auth.get(path).text
        assert 'class="nav-menu brand-menu" id="brand-menu"' in html, path
        assert '<nav class="tabs">' not in html, path       # 平铺页签已删
        assert "<h1>My Tesla</h1>" not in html, path        # 旧标题位换成品牌下拉
        assert 'id="nav-menu"' not in html, path            # 旧页签菜单已删
        for href in ("/tesla/charging", "/tesla/map", "/tesla/trips",
                     "/tesla/live", "/bookkeeping"):
            assert f'href="{href}"' in html, (path, href)
        if slug:
            assert f'<a class="on" href="/tesla/{slug}">{cur}</a>' in html, (path, cur)
        else:   # 记账页
            assert '<a class="on" href="/bookkeeping">家庭记账</a>' in html, path
        # 退出收进品牌菜单 (不再是顶栏独立按钮)
        assert 'class="logout-row" id="logout"' in html and "logout-btn" not in html, path
        assert "退出登录" in html, path


def test_brand_menu_admin_gate(auth):
    """账号管理入口只有管理员可见: me.js 按 /tesla/api/me 的 is_admin 放行。"""
    me_js = auth.get("/tesla/static/me.js?v=1").text
    assert 'fetch("/tesla/api/me")' in me_js
    assert "is_admin" in me_js
    assert ".admin-only" in me_js          # 非管理员保持 display:none
    for path in ("/tesla/charging", "/tesla/map", "/tesla/trips", "/bookkeeping"):
        html = auth.get(path).text
        assert '<a class="admin-only" href="/tesla/accounts">账号管理</a>' in html, path
        assert '<script src="/tesla/static/me.js?v=1"></script>' in html, path
