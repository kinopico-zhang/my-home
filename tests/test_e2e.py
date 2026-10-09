"""E2E 冒烟: 起真 uvicorn 子进程打真 HTTP —— CI 三平台矩阵跑的就是这套。

不走 TestClient: 完整过一遍 组合装配启动 → lifespan 建库种管理员 → 登录
→ 三个应用页面 / 账号管理页 / 静态资源, 与 ./run.sh 生产路径同构
(uvicorn app.main:app)。四份数据库全部落在 pytest 临时目录, 不碰仓库
data/ 里的真实库; TeslaMate 指到必拒连的本地口 (引擎懒连接 + 预热线程
自兜底), e2e 不依赖真实数据源。
"""
import os
import re
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
APP_PATHS = ("/tesla", "/music", "/bookkeeping")    # 组合仓: 三个应用全验
E2E_USER = "admin"
E2E_PASS = "e2e-smoke-pass"


def _free_port() -> int:
    """让系统分一个空闲口 (bind 0 后立刻放手, 给 uvicorn 用)。"""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def server(tmp_path_factory) -> Iterator[str]:
    """起一个真服务, 就绪后返回 base_url; 整模块共享, 收尾硬收进程。"""
    tmp = tmp_path_factory.mktemp("e2e")
    (tmp / "musicdir").mkdir()
    log = open(tmp / "server.log", "w+b")           # pylint: disable=consider-using-with
    env = {
        **os.environ,
        "AUTH_USER": E2E_USER,
        "AUTH_PASS": E2E_PASS,
        "MYHOME_USERS_DB": str(tmp / "users.db"),
        "MYHOME_SECRET_FILE": str(tmp / "session_secret"),
        "MYTESLA_DB": f"sqlite:///{(tmp / 'mytesla.db').as_posix()}",
        "MYTESLA_BOOKKEEPING_DB": f"sqlite:///{(tmp / 'bookkeeping.db').as_posix()}",
        "MYTESLA_MUSIC_DB": f"sqlite:///{(tmp / 'music.db').as_posix()}",
        "MYTESLA_MUSIC_DIR": str(tmp / "musicdir"),
        # TeslaMate 指到必拒连的本地口: 不探 docker, 永不碰真实库
        "TMDB_HOST": "127.0.0.1", "TMDB_PORT": "1",
        "TMDB_USER": "e2e", "TMDB_PASS": "e2e", "TMDB_NAME": "e2e",
    }
    port = _free_port()
    proc = subprocess.Popen(  # pylint: disable=consider-using-with
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 30.0
    try:
        while time.monotonic() < deadline:
            assert proc.poll() is None, "服务启动即退出:\n" + _tail(log)
            try:
                httpx.get(base + "/login", timeout=1.0, follow_redirects=True)
                break
            except httpx.HTTPError:
                time.sleep(0.2)
        else:
            raise AssertionError("服务 30s 未就绪:\n" + _tail(log))
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()


def _tail(log) -> str:
    """服务日志尾 (失败诊断用)。"""
    log.flush()
    log.seek(0)
    return b"".join(log.readlines()[-30:]).decode("utf-8", "replace")


@pytest.fixture(scope="module")
def client(server) -> Iterator[httpx.Client]:  # pylint: disable=redefined-outer-name
    """带自动 cookie 的客户端 (base_url 已设, 重定向默认跟随)。"""
    with httpx.Client(base_url=server, timeout=10.0, follow_redirects=True) as c:
        yield c


def test_app_pages_require_login(client):  # pylint: disable=redefined-outer-name
    """未登录进三个应用页: 一律 302 到登录页 (不越出 scope)。"""
    for path in APP_PATHS:
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 302, f"{path}: {r.text[:200]}"
        assert "/login" in r.headers["location"], path


def test_login_page_renders(client):  # pylint: disable=redefined-outer-name
    """登录页本身可渲染。"""
    r = client.get("/login")
    assert r.status_code == 200
    assert "html" in r.headers["content-type"]


def test_wrong_password_rejected(client):  # pylint: disable=redefined-outer-name
    """错密码 401 (单次失败, 不触 5 次锁 60s)。"""
    r = client.post("/api/login", json={"user": E2E_USER, "password": "wrong"})
    assert r.status_code in (401, 403), r.text[:200]


def test_login_session_and_all_apps(client):  # pylint: disable=redefined-outer-name
    """登录一次 cookie 全站通行: 三个应用页 + /api/me。

    引导没走完 (还差高德 Key) 时 Tesla 应用页被应用门拦回 /setup ——
    另两个应用不依赖数据源照常可用; 补上 Key (引导最后一步) 后全放行。"""
    r = client.post("/api/login", json={"user": E2E_USER, "password": E2E_PASS})
    assert r.status_code == 200, r.text[:200]
    gate = client.get("/tesla", follow_redirects=False)
    assert (gate.status_code, gate.headers["location"]) == (302, "/setup")
    assert client.post("/tesla/api/settings",
                       json={"amap_key": "e2e-amap-key"}).status_code == 200
    for path in APP_PATHS:
        r = client.get(path)
        assert r.status_code == 200, path
        assert "html" in r.headers["content-type"], path
    me = client.get("/api/me")
    assert me.status_code == 200
    assert me.json()["name"] == E2E_USER


def test_accounts_admin_page(client):  # pylint: disable=redefined-outer-name
    """账号管理页 (仅管理员) 可开。"""
    client.post("/api/login", json={"user": E2E_USER, "password": E2E_PASS})
    r = client.get("/accounts")
    assert r.status_code == 200
    assert "html" in r.headers["content-type"]


def test_tesla_settings_api_after_login(client):  # pylint: disable=redefined-outer-name
    """Tesla 设置接口走自有库 (不依赖 TeslaMate 连通)。"""
    client.post("/api/login", json={"user": E2E_USER, "password": E2E_PASS})
    r = client.get("/tesla/api/settings")
    assert r.status_code == 200
    assert isinstance(r.json(), dict)


def test_static_assets_serve(client):  # pylint: disable=redefined-outer-name
    """登录页引用的静态资源可取 (静态挂载 + 不可变缓存链路通)。"""
    client.post("/api/login", json={"user": E2E_USER, "password": E2E_PASS})
    html = client.get("/login").text
    m = re.search(r'(?:src|href)="(/[^"]+\.(?:js|css)(?:\?[^"]*)?)"', html)
    assert m, "登录页里没抓到静态资源地址"
    r = client.get(m.group(1))
    assert r.status_code == 200, m.group(1)
