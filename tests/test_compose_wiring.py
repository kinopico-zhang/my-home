"""组合装配测试: 合成包装载, 环境默认值归一, 三应用挂载 + 全站同鉴权。
三个子仓各自的业务测试在 apps/*/tests 里, 这里只管"拼起来"这一层。"""
import os
import sys
from pathlib import Path

import app.main as m


def test_synthetic_packages_loaded():
    """三个子仓以合成顶级前缀装载: 各自的 app 包独立存在, 与本仓 app 不串名
    (三仓的包名都叫 app, 靠前缀区分)。"""
    import app  # pylint: disable=import-outside-toplevel
    for prefix, repo in (("mymusic", "my-music"), ("mymoney", "my-money"),
                         ("mytesla", "my-tesla")):
        mod = sys.modules[f"{prefix}.app"]
        assert mod.__file__ is not None, prefix   # mypy 收窄: 合成包有真实文件
        pkg_dir = Path(mod.__file__).resolve().parent
        assert pkg_dir.name == "app"
        assert pkg_dir.parent.name == repo, prefix   # 真是 apps/<repo>/app
        assert mod is not app, prefix
    # 装配用的模块句柄与 sys.modules 里的是同一份 (无重复加载)
    assert m.music_webapp is sys.modules["mymusic.app.music.webapp"]
    assert m.bookkeeping_webapp is sys.modules["mymoney.app.bookkeeping.webapp"]
    assert m.tesla_charging is sys.modules["mytesla.app.tesla.routers.charging"]


def test_env_defaults_point_at_home_data(monkeypatch):
    """子仓库文件的默认值指到本仓 data/ —— 拆仓后四份库 + 会话密钥仍归
    一处 (单点登录, 生产数据不散落到子仓目录); env 已设的用户值优先。"""
    data = m.ROOT / "data"
    expected = {
        "MYHOME_USERS_DB": str(data / "users.db"),
        "MYHOME_SECRET_FILE": str(m.ROOT / ".session_secret"),
        "MYTESLA_MUSIC_DB": f"sqlite:///{data / 'music.db'}",
        "MYTESLA_BOOKKEEPING_DB": f"sqlite:///{data / 'bookkeeping.db'}",
        "MYTESLA_DB": f"sqlite:///{data / 'mytesla.db'}",
        "MAP_CACHE_FILE": str(data / "tracks_cache.json"),
    }
    for key in expected:
        monkeypatch.delenv(key, raising=False)
    m._env_defaults()
    for key, value in expected.items():
        assert os.environ[key] == value, key
    # setdefault 语义: env 里已有的 (用户自定路径) 不被覆盖
    monkeypatch.setenv("MYTESLA_DB", "sqlite:///custom.db")
    m._env_defaults()
    assert os.environ["MYTESLA_DB"] == "sqlite:///custom.db"


def test_three_apps_mounted_and_gated(client, auth):
    """三应用都挂在组合应用下: 未登录按各自 scope 拦截, 登录后同一枚
    cookie (根 /api/login 签发) 三个应用全通行 —— 账号体系是共享的。"""
    # auth 夹具登的是 client 这同一个实例 (夹具按名共享), 匿名视角要新建
    from fastapi.testclient import TestClient  # pylint: disable=import-outside-toplevel
    anon = TestClient(m.app)
    for path in ("/tesla/charging", "/bookkeeping", "/music"):
        r = anon.get(path, follow_redirects=False)
        assert r.status_code == 302, path
        assert "/login?next=" in r.headers["location"], path
    for path, marker in (("/tesla/charging", "My Tesla"),
                         ("/bookkeeping", "My Money"),
                         ("/music", "My Music")):
        r = auth.get(path)
        assert r.status_code == 200, path
        assert marker in r.text, path
    # 静态各归各: 共享层小件挂根 /static, 三应用自己的静态在各自 scope
    for asset in ("/static/menu-user.js", "/tesla/static/js/gcj02.js",
                  "/bookkeeping/static/bookkeeping-state.js",
                  "/music/static/js/music-settings-view.js"):
        assert auth.get(asset).status_code == 200, asset


def test_app_engines_wired(auth):
    """子应用的接口真的打到 conftest 注入的临时库 —— 引擎接线到位,
    不只是页面挂上了 (库由 isolate 换成 SQLite, 免真实数据)。"""
    assert auth.get("/music/api/albums").status_code == 200
    assert auth.get("/tesla/map/api/summary").status_code == 200
    assert auth.get("/bookkeeping/changelog/api/entries").status_code == 200


def test_submodules_registered():
    """三个 submodule 都登记在 .gitmodules (clone --recursive 才能起)。"""
    gitmodules = (m.ROOT / ".gitmodules").read_text(encoding="utf-8")
    for name, url in (("my-music", "git@github.com:kinopico-zhang/my-music.git"),
                      ("my-money", "git@github.com:kinopico-zhang/my-money.git"),
                      ("my-tesla", "git@github.com:kinopico-zhang/my-tesla.git")):
        assert f"apps/{name}" in gitmodules, name
        assert url in gitmodules, name
