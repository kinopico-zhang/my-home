"""pytest 共享 fixtures: SQLite 测试库 (免真实数据库) + 全局状态隔离。

组合仓口径: 共享账号库 (本仓) + 三个子仓的库 (曲库 / 记账库 / TeslaMate
镜像 + 自有库), 引擎由 isolate 注入 —— TestClient 不触发 lifespan, 不会
碰真实库。各应用的深度测试在它们自己的仓里 (apps/*/tests), 这里只管
组合装配那一层的接线与回归。
"""
import hashlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# sys.path 注入必须先于 app 导入 (import 位置告警属预期, 按需豁免)
from app import account_store, authentication, config, database  # pylint: disable=wrong-import-position
from app.models import UsersBase  # pylint: disable=wrong-import-position
import app.main as m  # pylint: disable=wrong-import-position

# 子仓模块 (main.py 装载后即可引用; 引擎隔离用, 深度测试在子仓里)
music_service = sys.modules["mymusic.app.music.service"]
music_database = sys.modules["mymusic.app.database"]
music_authentication = sys.modules["mymusic.app.authentication"]
bookkeeping_store = sys.modules["mymoney.app.bookkeeping.store"]
money_database = sys.modules["mymoney.app.database"]
money_authentication = sys.modules["mymoney.app.authentication"]
tesla_database = sys.modules["mytesla.app.database"]
tesla_models = sys.modules["mytesla.app.tesla.models"]
tesla_tracks_cache = sys.modules["mytesla.app.tesla.tracks_cache"]

# 测试口径的账密 (isolate 里种进账号库, auth 夹具按它登录;
# 生产首启种管理员读 .env 的 AUTH_PASS, 测试不依赖环境)
TEST_USER = "admin"
TEST_PASS = "unit-test-pass"


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    """每个用例独立: 账号库 / 曲库 / 记账库 / TeslaMate 镜像库与自有库 /
    会话密钥 / 登录限速 / 轨迹缓存互不串扰。"""
    # 共享账号库 (本仓): 用户 + 邀请; 挂载的两个应用各带一份账号引擎模块
    # (拆仓后同名不同物), 指到同一个临时库 —— 单点登录不分层
    database.init_users_engine(f"sqlite:///{tmp_path / 'users.db'}")
    UsersBase.metadata.create_all(database.users_engine())
    music_database.init_users_engine(f"sqlite:///{tmp_path / 'users.db'}")
    money_database.init_users_engine(f"sqlite:///{tmp_path / 'users.db'}")
    # 记账库 (my-money 子仓): 表 + 旧库补列 + 类别树
    bookkeeping_store.init_engine(f"sqlite:///{tmp_path / 'bookkeeping.db'}")
    bookkeeping_store.create_all()
    bookkeeping_store.seed_default_categories()
    # 曲库 (my-music 子仓): 临时库 + 临时曲库目录 (只装配不扫)
    music_service.start_service(f"sqlite:///{tmp_path / 'music.db'}",
                                tmp_path / "music-library",
                                scan_immediately=False)
    # TeslaMate 镜像库 + 自有库 (my-tesla 子仓)
    tesla_database.init_engine(f"sqlite:///{tmp_path / 'test.db'}")
    tesla_models.Base.metadata.create_all(tesla_database.engine())
    tesla_database.init_own_engine(f"sqlite:///{tmp_path / 'mytesla.db'}")
    tesla_models.OwnBase.metadata.create_all(tesla_database.own_engine())
    # 管理员种子 (生产在 lifespan 里做, TestClient 不触发 lifespan);
    # config 上的账密同步换成测试口径 (个别用例按 config.AUTH_* 登录)
    monkeypatch.setattr(config, "AUTH_USER", TEST_USER)
    monkeypatch.setattr(config, "AUTH_PASS", TEST_PASS)
    with database.users_session_factory()() as users:  # pylint: disable=not-callable
        account_store.ensure_admin(users, TEST_USER, TEST_PASS)
    secret = b"unit-test-secret-0123456789abcdef"
    secret_file = tmp_path / "secret"
    secret_file.write_bytes(secret)
    monkeypatch.setattr(config, "SECRET_FILE", secret_file)
    # 测试直接替换内部密钥持有者 (与生产同构, 走真实签名路径) —— 本仓的
    # 和两个挂载应用自带的副本都要换 (子仓路由用它们自己的那份验 cookie)
    for auth_mod in (authentication, music_authentication, money_authentication):
        monkeypatch.setattr(auth_mod, "_secret",  # pylint: disable=protected-access
                            auth_mod._SecretHolder(  # pylint: disable=protected-access
                                hashlib.sha256(secret).digest()))
        monkeypatch.setattr(auth_mod, "_legacy_secret",  # pylint: disable=protected-access
                            auth_mod._SecretHolder(  # pylint: disable=protected-access
                                auth_mod._compute_legacy_secret(secret)))  # pylint: disable=protected-access
        monkeypatch.setattr(auth_mod, "_login_fails", {})
    tesla_tracks_cache.reset()
    monkeypatch.setenv("MAP_CACHE_FILE", str(tmp_path / "tracks_cache.json"))
    # TeslaMate 地址固定走环境变量短路: build_db_url 永不落到 docker inspect
    monkeypatch.setenv("TMDB_HOST", "127.0.0.1")
    yield
    tesla_database.dispose_engine()
    tesla_database.dispose_own_engine()
    database.dispose_users_engine()
    music_database.dispose_users_engine()
    money_database.dispose_users_engine()
    bookkeeping_store.dispose_engine()
    music_service.stop_service()


@pytest.fixture()
def client():
    """未登录的 client (不触发 lifespan, 引擎由 isolate 注入的 SQLite)。"""
    return TestClient(m.app)


@pytest.fixture()
def auth(client):  # pylint: disable=redefined-outer-name
    """已登录的 client (正确账密, 走真实签名 cookie)。"""
    r = client.post("/api/login",
                    json={"user": TEST_USER, "password": TEST_PASS})
    assert r.status_code == 200
    return client


@pytest.fixture()
def usersdb():
    """直连账号库的会话 (种子用户 / 邀请 / 回读断言)。"""
    with database.users_session_factory()() as session:  # pylint: disable=not-callable
        yield session
