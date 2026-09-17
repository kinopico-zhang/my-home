"""My Home 组合仓装配: 共享账号层 + 三个子仓应用 (submodule)。

三个应用 (My Tesla / My Money / My Music) 各自独立成仓挂在 apps/ 下
(git submodule), 本仓只保留共享层 (登录/注册/账号管理 + 会话中间件)。
子仓的包名都叫 app —— 与本仓自己的 app 并存: 装载时给每个子仓造一个
合成顶级前缀 (mymusic / mymoney / mytesla), import 系统顺着前缀找到
apps/<仓>/app, 仓内的相对导入 (from ... import x) 就都在仓内自洽,
不与本仓的 app 串。

数据布局: 子仓的配置全走环境变量 (MYTESLA_MUSIC_DB / MYTESLA_BOOKKEEPING_DB /
MYTESLA_DB / MYHOME_USERS_DB / MYHOME_SECRET_FILE…), 装载前由 _env_defaults
把默认值指到本仓 data/ 下 —— 四份库文件、一枚会话密钥, 单点登录。
"""
import importlib.machinery
import importlib.util
import os
import sys
import threading
import types
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError

from . import account_store, config, database
from .home import STATIC_DIR as HOME_STATIC_DIR
from .home import accounts_api, middleware as home_middleware
from .home import pages as home_pages, session_api
from .models import UsersBase

ROOT = Path(__file__).resolve().parent.parent
APPS_DIR = ROOT / "apps"


def _env_defaults() -> None:
    """三个子仓的库文件默认值指到本仓 data/ (env 已设的不再动)。

    子仓配置在 import 时读 env, 这一步必须先于装载; 路径全用绝对值 ——
    子仓的裸路径默认是相对它们自己的仓根, 会落到 apps/<仓>/data/ 去。"""
    data = ROOT / "data"
    defaults = {
        "MYHOME_USERS_DB": str(data / "users.db"),
        "MYHOME_SECRET_FILE": str(ROOT / ".session_secret"),
        "MYTESLA_MUSIC_DB": f"sqlite:///{data / 'music.db'}",
        "MYTESLA_BOOKKEEPING_DB": f"sqlite:///{data / 'bookkeeping.db'}",
        "MYTESLA_DB": f"sqlite:///{data / 'mytesla.db'}",
        "MAP_CACHE_FILE": str(data / "tracks_cache.json"),
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)


def _load_repo(prefix: str, repo_dir: str) -> types.ModuleType:
    """把 apps/<repo_dir> 注册成合成顶级包 <prefix>, 导入其 app 包。

    包名都叫 app, 直接 import 会与本仓的 app 撞名: 借一个无加载器的
    父包 (submodule_search_locations 指向子仓目录), 子包 app 顺着前缀
    落进 sys.modules["<prefix>.app"], 仓内相对导入全部自洽。"""
    spec = importlib.machinery.ModuleSpec(prefix, None, is_package=True)
    spec.submodule_search_locations = [str(APPS_DIR / repo_dir)]
    sys.modules[prefix] = importlib.util.module_from_spec(spec)
    return importlib.import_module(f"{prefix}.app")


_env_defaults()
_load_repo("mymusic", "my-music")   # 三仓互不依赖, 装载顺序无所谓
_load_repo("mymoney", "my-money")
_load_repo("mytesla", "my-tesla")

# 子仓内部模块 (装载后才能引用; 相对导入在各自仓内解析)
music_service = importlib.import_module("mymusic.app.music.service")
music_webapp = importlib.import_module("mymusic.app.music.webapp")
music_database = importlib.import_module("mymusic.app.database")
bookkeeping_store = importlib.import_module("mymoney.app.bookkeeping.store")
bookkeeping_webapp = importlib.import_module("mymoney.app.bookkeeping.webapp")
money_database = importlib.import_module("mymoney.app.database")
tesla_config = importlib.import_module("mytesla.app.config")
tesla_database = importlib.import_module("mytesla.app.database")
tesla_settings_store = importlib.import_module("mytesla.app.tesla.settings_store")
tesla_tracks_cache = importlib.import_module("mytesla.app.tesla.tracks_cache")
tesla_own_models = importlib.import_module("mytesla.app.tesla.models")
tesla_pages = importlib.import_module("mytesla.app.tesla.routers.pages")
tesla_charging = importlib.import_module("mytesla.app.tesla.routers.charging")
tesla_map = importlib.import_module("mytesla.app.tesla.routers.map")
tesla_trips = importlib.import_module("mytesla.app.tesla.routers.trips")
tesla_live = importlib.import_module("mytesla.app.tesla.routers.live")
tesla_settings = importlib.import_module("mytesla.app.tesla.routers.settings")
tesla_changelog = importlib.import_module("mytesla.app.tesla.routers.changelog")


def _migrate_own_db() -> None:
    """create_all 只建新表不改旧表: 已有生产库要补的列写在这里 (幂等)。

    与 my-tesla 子仓 standalone main.py 里那份是同一配方 —— 自有库在
    两边都要能开 (组合部署 / 单仓部署共用同一个 data/mytesla.db)。"""
    with tesla_database.own_engine().begin() as conn:
        cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(app_settings)")}
        if "amap_style" not in cols:   # v: 高德地图样式 (设置页可换, 三页地图共用)
            conn.exec_driver_sql(
                "ALTER TABLE app_settings ADD COLUMN amap_style TEXT NOT NULL DEFAULT ''")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """启动时建齐四套引擎 + 后台预热, 关闭时全部释放。

    账号库 (本仓) 首启种管理员; 三个应用的库各自建表 (曲库/记账库/
    Tesla 自有库), TeslaMate 连接可被设置页覆盖 (未设回落 env 定位)。"""
    # 共享账号库: 单点登录的全站账号
    database.init_users_engine()
    UsersBase.metadata.create_all(database.users_engine())
    # 两个挂载的应用 (My Music / My Money) 各带一份账号引擎模块 (拆仓后
    # 同名不同物, 它们的 Depends(get_users_db) 解析到各自那份), 都指到
    # 同一个 users.db —— 会话/账号还是一套, 不分层
    music_database.init_users_engine(config.USERS_DB_URL)
    money_database.init_users_engine(config.USERS_DB_URL)
    if config.AUTH_PASS:
        with database.users_session_factory()() as users:  # pylint: disable=not-callable
            account_store.ensure_admin(users, config.AUTH_USER, config.AUTH_PASS)
    else:
        print("AUTH_PASS 未设置: 首启不种管理员 —— 在 .env 里设 AUTH_PASS 后重启",
              file=sys.stderr)
    # My Money: 记账库建表 + 旧库补列 + 类别树
    bookkeeping_store.init_engine()
    bookkeeping_store.create_all()
    bookkeeping_store.migrate_columns()
    bookkeeping_store.seed_default_categories()
    # My Music: 曲库索引 + 后台首扫
    music_service.start_service()
    # My Tesla: 自有库建表 + 补列, 再读设置定 TeslaMate 连接
    tesla_database.init_own_engine()
    tesla_own_models.OwnBase.metadata.create_all(tesla_database.own_engine())
    _migrate_own_db()
    with tesla_database.own_session_factory()() as own:  # pylint: disable=not-callable
        url = tesla_settings_store.engine_url(own)
    tesla_database.init_engine(url)
    # 后台预热轨迹缓存 (全量下采样 ~15s, 不阻塞启动)
    threading.Thread(target=tesla_tracks_cache.warm,
                     args=(tesla_database.session_factory(),), daemon=True).start()
    yield
    tesla_database.dispose_engine()
    tesla_database.dispose_own_engine()
    database.dispose_users_engine()
    music_database.dispose_users_engine()
    money_database.dispose_users_engine()
    bookkeeping_store.dispose_engine()
    music_service.stop_service()


app = FastAPI(title="My Home", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=2048)   # 轨迹 JSON 压缩 ~5x
app.middleware("http")(home_middleware.auth_middleware)


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_error_handler(
        _: Request, exc: SQLAlchemyError) -> JSONResponse:
    """数据库异常统一 503 (与旧版 query() 包装行为一致)。"""
    return JSONResponse({"detail": f"数据库查询失败: {exc}"}, status_code=503)


# 共享层: 登录/注册页面 + 会话接口 + 账号管理 (门厅主页已撤, 根路径 302 进应用)
app.include_router(home_pages.router)
app.include_router(session_api.api)
app.include_router(accounts_api.accounts)
# My Tesla: 路由在子仓 tesla 包 (URL 前缀与拆仓前一致, 老书签不动)
app.include_router(tesla_pages.router)
app.include_router(tesla_charging.charging)
app.include_router(tesla_map.mapapi)
app.include_router(tesla_trips.trips)
app.include_router(tesla_live.live)
app.include_router(tesla_settings.settingsapi)
app.include_router(tesla_changelog.changelogapi)
app.mount("/static", StaticFiles(directory=HOME_STATIC_DIR), name="home-static")
app.mount("/tesla/static", StaticFiles(directory=tesla_config.STATIC_DIR),
          name="static")
# My Money / My Music: 独立应用, 只共享账号体系 (会话 cookie + 账号库)
app.mount("/bookkeeping", bookkeeping_webapp.bk_app)
app.mount("/music", music_webapp.music_app)
