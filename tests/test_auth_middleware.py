"""中间件测试: 未登录页面 302 / 接口 401, 公开路径放行,
旧账号路径搬家重定向。
拆自 test_auth.py (结构化重构, 代码逐字节未动)。"""

from fastapi.testclient import TestClient

from app import config
import app.main as m


def test_unauthed_pages_redirect_to_login(client):
    """页面未登录 302 登录页: 应用页跳自己 scope 内的登录页 (带上原地址,
    登录完回去), 门厅层 (/, /accounts) 跳根路径 /login。"""
    from urllib.parse import quote
    for path, login in (("/", "/login"), ("/accounts", "/login"),
                        ("/tesla", "/tesla/login"),
                        ("/tesla/charging", "/tesla/login"),
                        ("/tesla/stats", "/tesla/login"),
                        ("/tesla/chargemap", "/tesla/login"),
                        ("/tesla/map", "/tesla/login"),
                        ("/tesla/changelog", "/tesla/login"),
                        ("/tesla/trips", "/tesla/login"),
                        ("/tesla/groups", "/tesla/login"),
                        ("/tesla/live", "/tesla/login"),
                        ("/tesla/settings", "/tesla/login"),
                        ("/bookkeeping", "/bookkeeping/login"),
                        ("/bookkeeping/changelog", "/bookkeeping/login"),
                        ("/music", "/music/login"),
                        ("/music/changelog", "/music/login")):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 302, path
        expected = login if path == login else login + "?next=" + quote(path, safe="")
        assert r.headers["location"] == expected, path


def test_app_login_pages_in_scope(client):
    """各应用 scope 内的登录页: 未登录直接可开 (不再 302 到根路径 /login
    越出 scope), 内容就是门厅那张登录页; 已登录访问直接回该应用主页
    (独立 client, 不带上面的未登录态)。"""
    for path in ("/tesla/login", "/music/login", "/bookkeeping/login"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 200, path
        assert 'src="/static/login.js?v=1"' in r.text, path
    authed = TestClient(m.app)
    assert authed.post("/api/login", json={"user": config.AUTH_USER,
                                           "password": config.AUTH_PASS}
                       ).status_code == 200
    for path, root in (("/tesla/login", "/tesla/charging"),
                       ("/music/login", "/music"),
                       ("/bookkeeping/login", "/bookkeeping")):
        r = authed.get(path, follow_redirects=False)
        assert (r.status_code, r.headers["location"]) == (302, root), path


def test_unauthed_apis_return_401_json(client):
    for path in ("/tesla/charging/api/summary", "/tesla/charging/api/sessions",
                 "/tesla/map/api/summary", "/tesla/map/api/tracks",
                 "/tesla/map/api/tracks/detail", "/tesla/map/api/config",
                 "/tesla/trips/api/sessions", "/tesla/trips/api/1/track",
                 "/tesla/live/api/status",
                 "/tesla/changelog/api/entries",
                 "/music/api/albums", "/music/api/status",
                 "/music/api/playlists", "/music/api/playlists/1",
                 "/music/api/plays/recent",
                 "/music/changelog/api/entries",
                 "/bookkeeping/changelog/api/entries",
                 "/api/me", "/api/account/name", "/accounts/api/users"):
        r = client.get(path)
        assert r.status_code == 401, path
        assert r.json() == {"detail": "未登录"}
    for method, path in ((client.post, "/music/api/playlists"),
                         (client.post, "/music/api/plays"),
                         (client.post, "/bookkeeping/api/sync")):
        r = method(path, json={"entries": []})
        assert r.status_code == 401
        assert r.json() == {"detail": "未登录"}


def test_public_paths_accessible_without_login(client):
    assert client.get("/login").status_code == 200
    assert client.get("/register").status_code == 200    # 注册页公开
    for asset in ("/tesla/static/echarts.min.js", "/tesla/static/js/gcj02.js",
                  "/tesla/static/js/trackutil.js", "/tesla/static/favicon.svg",
                  "/static/login.js", "/static/register.js", "/static/home.js",
                  "/static/favicon.svg",               # 门厅层静态放行
                  "/bookkeeping/static/bookkeeping-state.js",
                  "/bookkeeping/static/bookkeeping-merge.js"):
        assert client.get(asset).status_code == 200, asset
    # Safari 不支持 SVG favicon, 需要 PNG 版 + iOS 主屏 apple-touch-icon
    for icon in ("/tesla/static/favicon-32.png",
                 "/tesla/static/apple-touch-icon.png",
                 "/static/favicon-32.png", "/static/apple-touch-icon.png"):
        assert client.get(icon).status_code == 200, icon


def test_moved_account_paths_redirect(client):
    """账号体系搬到根路径 (门厅共享层), 旧地址 302/307 兼容 —— 已经发出去的
    邀请链接和手机上的老书签不能断: 页面 302, 接口 307 (保方法与请求体),
    查询串 (invite=) 原样带上。"""
    for old, new in (("/tesla/register?invite=tok", "/register?invite=tok"),
                     ("/tesla/accounts", "/accounts")):
        r = client.get(old, follow_redirects=False)
        assert (r.status_code, r.headers["location"]) == (302, new), old
    for verb, old, new in (
            ("post", "/tesla/api/login", "/api/login"),
            ("post", "/tesla/api/logout", "/api/logout"),
            ("post", "/tesla/api/register", "/api/register"),
            ("get", "/tesla/api/invite-status?invite=tok",
             "/api/invite-status?invite=tok"),
            ("get", "/tesla/api/me", "/api/me"),
            ("post", "/tesla/api/account/name", "/api/account/name"),
            ("post", "/tesla/api/account/password", "/api/account/password"),
            ("get", "/tesla/accounts/api/users", "/accounts/api/users"),
            ("delete", "/tesla/accounts/api/invitations/tok",
             "/accounts/api/invitations/tok")):
        r = getattr(client, verb)(old, follow_redirects=False)
        assert (r.status_code, r.headers["location"]) == (307, new), old
    # 老书签真的能用: 307 转过去登录成功
    r = client.post("/tesla/api/login", json={"user": config.AUTH_USER,
                                              "password": config.AUTH_PASS})
    assert r.status_code == 200
    # Tesla 业务接口没有平移到根路径 (不与门厅账号接口混住)
    assert client.get("/api/summary").status_code == 404
    assert client.get("/api/charging").status_code == 404
