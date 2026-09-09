"""pytest 共享 fixtures: 全局状态隔离 + 免真实数据库的 TestClient。"""
import hashlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app.main as m  # noqa: E402


class FakeCursor:
    def __init__(self):
        self.sql = None
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.sql, self.params = sql, params


class FakeConn:
    def __init__(self):
        self.cur = FakeCursor()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self, row_factory=None):
        return self.cur


class FakePool:
    """替身连接池: 记录写入语句 (UPDATE) 供断言, 读操作由各用例 patch m.query。"""

    def __init__(self):
        self.conn = FakeConn()

    def connection(self):
        return self.conn

    def close(self):
        pass


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    """每个用例独立: 会话密钥文件 / 登录限速 / 轨迹缓存互不串扰。"""
    secret = b"unit-test-secret-0123456789abcdef"
    (tmp_path / "secret").write_bytes(secret)
    monkeypatch.setattr(m, "SECRET_FILE", str(tmp_path / "secret"))
    monkeypatch.setattr(m, "SECRET", hashlib.sha256(
        secret + b"|" + m.AUTH_USER.encode() + b"|" + m.AUTH_PASS.encode()).digest())
    monkeypatch.setattr(m, "_login_fails", {})
    monkeypatch.setattr(m, "_tracks_mem", None)
    monkeypatch.setattr(m, "pool", FakePool())
    monkeypatch.setenv("MAP_CACHE_FILE", str(tmp_path / "tracks_cache.json"))
    yield


@pytest.fixture()
def client():
    # 不用 with: 不触发 lifespan, 避免连接真实数据库
    return TestClient(m.app)


@pytest.fixture()
def auth(client):
    """已登录的 client (正确账密, 走真实签名 cookie)。"""
    r = client.post("/tesla/api/login",
                    json={"user": m.AUTH_USER, "password": m.AUTH_PASS})
    assert r.status_code == 200
    return client
