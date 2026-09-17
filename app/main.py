"""My Home 主应用装配: 门厅 + 三个应用 (My Tesla / My Money / My Music)。

数据源: teslamate_cn (PostgreSQL, TeslaMate 标准表结构), 查询全部在
repository 层 (SQLAlchemy, 方言中立); 测试通过 database.init_engine()
注入 SQLite, 不碰真实库。
时间处理: 库内为 UTC 裸时间戳, 对外输出本地时间 (默认 Asia/Shanghai)。
鉴权: 登录后签发 HMAC 签名的会话 cookie (默认 90 天), 未登录页面跳各应用
scope 内自己的登录页 (门厅层跳 /login), API 回 401; 中间件在 app/home/
middleware, 页面与账号接口在 app/home/。
"""
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError

from . import account_store, config, database
from .bookkeeping import store as bookkeeping_store, webapp as bookkeeping_webapp
from .home import STATIC_DIR as HOME_STATIC_DIR
from .home import accounts_api, middleware as home_middleware
from .home import pages as home_pages, session_api
from .models import UsersBase
from .music import service as music_service, webapp as music_webapp
from .tesla import settings_store, tracks_cache
from .tesla.models import OwnBase
from .tesla.routers import (charging as charging_routes,
                            changelog as changelog_routes,
                            live as live_routes,
                            map as map_routes, pages,
                            settings as settings_routes,
                            trips as trips_routes)


def _migrate_own_db() -> None:
    """create_all 只建新表不改旧表: 已有生产库要补的列写在这里 (幂等)。"""
    with database.own_engine().begin() as conn:
        cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(app_settings)")}
        if "amap_style" not in cols:   # v: 高德地图样式 (设置页可换, 三页地图共用)
            conn.exec_driver_sql(
                "ALTER TABLE app_settings ADD COLUMN amap_style TEXT NOT NULL DEFAULT ''")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """启动时建引擎 + 后台预热缓存, 关闭时释放连接池。

    自有库 (SQLite) 的表由应用自己建 (create_all), 与 TeslaMate
    原库 (迁移建的表, 只读) 完全隔离。"""
    # 先建自有库再读设置: TeslaMate 连接可被设置页覆盖 (未设回落 env 定位)
    database.init_own_engine()
    OwnBase.metadata.create_all(database.own_engine())
    _migrate_own_db()
    # 账号库 (独立文件): 首启种管理员 (env 账密, 之后走界面改);
    # 记账库 (独立文件) 只建表
    database.init_users_engine()
    UsersBase.metadata.create_all(database.users_engine())
    with database.users_session_factory()() as users:
        account_store.ensure_admin(users, config.AUTH_USER, config.AUTH_PASS)
    bookkeeping_store.init_engine()      # 记账库 (独立文件, 独立应用)
    bookkeeping_store.create_all()
    bookkeeping_store.migrate_columns()           # 旧库补 time/tags 列 (幂等)
    bookkeeping_store.seed_default_categories()   # 类别树 (空库才种, 挖财导入)
    music_service.start_service()      # 曲库索引 (独立文件) + 后台首扫
    with database.own_session_factory()() as own:   # pylint: disable=not-callable
        url = settings_store.engine_url(own)
    database.init_engine(url)
    # 后台预热轨迹缓存 (全量下采样 ~15s, 不阻塞启动)
    threading.Thread(target=tracks_cache.warm,
                     args=(database.session_factory(),), daemon=True).start()
    yield
    database.dispose_engine()
    database.dispose_own_engine()
    database.dispose_users_engine()
    bookkeeping_store.dispose_engine()
    music_service.stop_service()


app = FastAPI(title="My Tesla", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=2048)   # 轨迹 JSON 压缩 ~5x
app.middleware("http")(home_middleware.auth_middleware)


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_error_handler(
        _: Request, exc: SQLAlchemyError) -> JSONResponse:
    """数据库异常统一 503 (与旧版 query() 包装行为一致)。"""
    return JSONResponse({"detail": f"数据库查询失败: {exc}"}, status_code=503)


# My Home 共享层: 门厅页面 + 账号会话接口 + 账号管理
app.include_router(home_pages.router)
app.include_router(session_api.api)
app.include_router(accounts_api.accounts)
# My Tesla: 路由全在 tesla 包 (URL 前缀与旧版一致)
app.include_router(pages.router)
app.include_router(charging_routes.charging)
app.include_router(map_routes.mapapi)
app.include_router(trips_routes.trips)
app.include_router(live_routes.live)
app.include_router(settings_routes.settingsapi)
app.include_router(changelog_routes.changelogapi)
app.mount("/static", StaticFiles(directory=HOME_STATIC_DIR), name="home-static")
app.mount("/tesla/static", StaticFiles(directory=config.STATIC_DIR), name="static")
# My Money (家庭记账) / My Music: 独立应用, 只共享账号体系 (会话 cookie + 账号库)
app.mount("/bookkeeping", bookkeeping_webapp.bk_app)
app.mount("/music", music_webapp.music_app)
