"""TeslaMate 数据库连接：定位 teslamate_cn 的 postgres 容器并建立连接池。"""
import os
import shutil
import subprocess

import psycopg
from psycopg_pool import ConnectionPool

DB_CONTAINER = os.environ.get("TMDB_CONTAINER", "teslamate_cn_database_1")

# QNAP Container Station 的 docker 不在 PATH 里，按顺序尝试
DOCKER_BIN_CANDIDATES = [
    os.environ.get("DOCKER_BIN", ""),
    "/share/CACHEDEV1_DATA/.qpkg/container-station/bin/docker",
    shutil.which("docker") or "",
]


def resolve_db_host() -> str:
    """解析数据库容器 IP：环境变量 > docker inspect。"""
    host = os.environ.get("TMDB_HOST")
    if host:
        return host
    for bin_path in filter(None, DOCKER_BIN_CANDIDATES):
        try:
            out = subprocess.check_output(
                [bin_path, "inspect", DB_CONTAINER, "--format",
                 "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}"],
                text=True, timeout=10, stderr=subprocess.DEVNULL).strip()
        except (OSError, subprocess.SubprocessError):
            continue
        if out:
            return out
    raise RuntimeError(
        f"无法定位数据库容器 {DB_CONTAINER}，请设置 TMDB_HOST 环境变量指向 PostgreSQL 地址")


def make_pool() -> ConnectionPool:
    conninfo = " ".join([
        f"host={os.environ.get('TMDB_HOST') or resolve_db_host()}",
        f"port={os.environ.get('TMDB_PORT', 5432)}",
        f"user={os.environ.get('TMDB_USER', 'teslamate')}",
        f"password={os.environ.get('TMDB_PASS', '123456')}",
        f"dbname={os.environ.get('TMDB_NAME', 'teslamate')}",
        "connect_timeout=10",
    ])
    return ConnectionPool(conninfo, min_size=1, max_size=5,
                          check=ConnectionPool.check_connection, open=True)
