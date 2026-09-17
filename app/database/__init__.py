"""数据库引擎门面 (组合仓共享层): 只有账号库 (SQLite, data/users.db) 一套。

三个应用各自管各自的库: 曲库在 my-music 的 library_database, 记账库在
my-money 的 bookkeeping.store, TeslaMate/自有库在 my-tesla 的 database ——
都从子仓加载 (见 main.py), 库文件由环境变量指到本仓 data/ 下。"""
from .users_engine import (dispose_users_engine, get_users_db,
                           init_users_engine, users_engine,
                           users_session_factory)

__all__ = ["dispose_users_engine", "get_users_db", "init_users_engine",
           "users_engine", "users_session_factory"]
