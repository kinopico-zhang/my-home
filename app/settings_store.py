"""运行时设置与司机 (自有库): 设置页可改, 未设字段回落 env/.env 默认值。

TeslaMate 连接改动会换引擎重连 (database.rebuild_engine) 并实测 SELECT 1,
连不上整体回滚 (设置与引擎都退回旧值); 高德 Key 即时生效 (map config
端点每次现读)。密码/Key 只存不回显: GET 打码, 前端留空 = 保持现值。
"""
import os

from sqlalchemy import select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from . import database
from .models import AppSetting, Driver
from .schemas import (AmapSettings, DriverInfo, SettingsState,
                      SettingsUpdate, TeslaMateSettings)
from .repository import NotFound

_FIELDS = ("tmdb_host", "tmdb_port", "tmdb_user", "tmdb_password", "tmdb_name",
           "amap_key", "amap_security_code")


class EngineError(RuntimeError):
    """新 TeslaMate 连接验证失败 (调用方转 400; 已整体回滚, 服务未中断)。"""


def _row(own: Session) -> AppSetting:
    """取设置行 (没有就建, 恒单行 id=1)。"""
    row = own.get(AppSetting, 1)
    if row is None:
        row = AppSetting(id=1)
        own.add(row)
        own.commit()
    return row


def _masked(value: str) -> str:
    """半遮回显 (ab12****yz89): 识别够了, 完整值不外泄。"""
    if not value:
        return ""
    return f"{value[:4]}****{value[-4:]}" if len(value) > 8 else "****"


def effective_tmdb(own: Session) -> dict[str, str]:
    """TeslaMate 连接各字段现值: 设置行 > env (host 再回落 docker 容器定位)。

    docker 定位失败不炸 GET (host 留空展示), URL 拼接时才真正报错。"""
    row = _row(own)
    host = row.tmdb_host or os.environ.get("TMDB_HOST", "")
    if not host:
        try:
            host = database.resolve_db_host()
        except RuntimeError:
            host = ""
    return {
        "host": host,
        "port": row.tmdb_port or os.environ.get("TMDB_PORT", "5432"),
        "user": row.tmdb_user or os.environ.get("TMDB_USER", "teslamate"),
        "password": row.tmdb_password or os.environ.get("TMDB_PASS", ""),
        "name": row.tmdb_name or os.environ.get("TMDB_NAME", "teslamate"),
    }


def engine_url(own: Session) -> str:
    """TeslaMate 连接串 (设置行 > env): 启动建引擎用。"""
    return database.build_db_url(effective_tmdb(own))


def amap_values(own: Session) -> tuple[str | None, str | None]:
    """高德 Key 现值 (设置行 > env): map config 端点每次现读, 改完即生效。"""
    row = _row(own)
    return (row.amap_key or os.environ.get("AMAP_KEY") or None,
            row.amap_security_code or os.environ.get("AMAP_SECURITY_CODE") or None)


def settings_state(own: Session) -> SettingsState:
    """设置页状态: 各字段现值 (回落 env 后的效果), 秘密只报在用/打码。"""
    eff = effective_tmdb(own)
    row = _row(own)
    key = row.amap_key or os.environ.get("AMAP_KEY", "")
    code = row.amap_security_code or os.environ.get("AMAP_SECURITY_CODE", "")
    return SettingsState(
        tmdb=TeslaMateSettings(
            host=eff["host"], port=eff["port"], user=eff["user"],
            name=eff["name"], password_set=bool(eff["password"])),
        amap=AmapSettings(key_masked=_masked(key), security_code_set=bool(code)))


def save_settings(own: Session, body: SettingsUpdate) -> tuple[SettingsState, bool]:
    """保存设置 (留空字段不动)。

    TeslaMate 连接串变了 → 换引擎并实测 SELECT 1; 连不上抛 EngineError,
    设置行与引擎都回滚到旧值 (服务不断)。返回 (新状态, 是否换了引擎)。"""
    row = _row(own)
    old_url = database.build_db_url(effective_tmdb(own))
    old_values = {f: getattr(row, f) for f in _FIELDS}
    for field in _FIELDS:
        value = getattr(body, field).strip()
        if value:
            setattr(row, field, value)
    own.commit()
    new_url = database.build_db_url(effective_tmdb(own))
    if new_url == old_url:
        return settings_state(own), False
    database.rebuild_engine(new_url)
    try:
        with database.session_factory()() as session:   # pylint: disable=not-callable
            session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        for field, value in old_values.items():
            setattr(row, field, value)
        own.commit()
        database.rebuild_engine(old_url)
        detail = str(getattr(exc, "orig", None) or exc)[:200]
        raise EngineError(f"新连接连不上: {detail}") from exc
    return settings_state(own), True


# ---------------------------------------------------------------- 司机

def _info(driver: Driver) -> DriverInfo:
    """ORM 行 → API 条目。"""
    return DriverInfo(id=driver.id, name=driver.name,
                      is_default=driver.is_default)


def list_drivers(own: Session) -> list[DriverInfo]:
    """全部司机 (添加顺序)。"""
    return [_info(d) for d in
            own.scalars(select(Driver).order_by(Driver.id)).all()]


def create_driver(own: Session, name: str) -> DriverInfo:
    """添加司机。"""
    driver = Driver(name=name)
    own.add(driver)
    own.commit()
    return _info(driver)


def update_driver(own: Session, driver_id: int,
                  name: str | None, is_default: bool | None) -> DriverInfo:
    """改司机: 改名 / 设默认 (设默认会把其他人的默认清掉, 全库至多一个)。"""
    driver = own.get(Driver, driver_id)
    if driver is None:
        raise NotFound("司机不存在")
    if name is not None:
        driver.name = name
    if is_default is True:
        own.execute(update(Driver).values(is_default=False))
        driver.is_default = True
    elif is_default is False:
        driver.is_default = False
    own.commit()
    return _info(driver)


def delete_driver(own: Session, driver_id: int) -> None:
    """删司机 (默认被删后全库暂时无默认, 行程标注兜底显示留空)。"""
    driver = own.get(Driver, driver_id)
    if driver is None:
        raise NotFound("司机不存在")
    own.delete(driver)
    own.commit()
