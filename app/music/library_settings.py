"""运行时设置 (曲库路径 / 歌词 API) + 蜂窝流量月账。

设置恒单行 id=1, 空字段回落 env 默认; 改曲库路径由服务层
(service.apply_music_directory) 换扫描根目录并起全量重扫, 这里只管
存取与校验。蜂窝流量是客户端能认出蜂窝网络时按月上报的账, 一月一行。
"""
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from .library_database import (DEFAULT_MUSIC_DIRECTORY, CellularUsage,
                               MusicSetting)
from .schemas import CellularMonth, MusicSettingsState

# 歌词 API 的默认地址 (LRCLIB: 免费, 兼容 /get?artist_name=…&track_name=…)
LYRICS_API_DEFAULT = "https://lrclib.net/api"
_MONTHS_SHOWN = 12        # 设置页流量账看最近这几个月


def settings_row(session: Session) -> MusicSetting:
    """取设置行 (没有就建, 恒单行 id=1)。"""
    row = session.get(MusicSetting, 1)
    if row is None:
        row = MusicSetting(id=1)
        session.add(row)
        session.commit()
    return row


def effective_music_directory(session: Session) -> Path:
    """曲库根目录现值: 设置行 > env 默认。"""
    configured = settings_row(session).music_directory.strip()
    return Path(configured or DEFAULT_MUSIC_DIRECTORY)


def effective_lyrics_api(session: Session) -> tuple[bool, str]:
    """歌词 API 现值: (开不开, 地址); 地址空 = 默认 LRCLIB。"""
    row = settings_row(session)
    return (row.lyrics_api_enabled,
            row.lyrics_api_base.strip() or LYRICS_API_DEFAULT)


def settings_state(session: Session) -> MusicSettingsState:
    """设置页状态 (现值 + 默认值参照 + 流量月账)。"""
    row = settings_row(session)
    return MusicSettingsState(
        music_directory=row.music_directory,
        music_directory_default=DEFAULT_MUSIC_DIRECTORY,
        lyrics_api_enabled=row.lyrics_api_enabled,
        lyrics_api_base=row.lyrics_api_base,
        lyrics_api_default=LYRICS_API_DEFAULT,
        cellular_months=cellular_months(session))


def save_settings(session: Session, music_directory: str | None,
                  lyrics_api_enabled: bool | None,
                  lyrics_api_base: str | None) -> Path | None:
    """保存设置 (None 字段不动); 返回新生效的曲库目录 (路径没变才为 None)。

    曲库路径要求目录真的存在 (连不上的路径扫不了); 歌词 API 地址要带协议头。"""
    row = settings_row(session)
    if lyrics_api_base is not None:
        cleaned = lyrics_api_base.strip()
        if cleaned and not cleaned.startswith(("http://", "https://")):
            raise ValueError(f"歌词 API 地址要以 http:// 或 https:// 开头: {cleaned}")
        row.lyrics_api_base = cleaned
    if lyrics_api_enabled is not None:
        row.lyrics_api_enabled = lyrics_api_enabled
    new_directory: Path | None = None
    if music_directory is not None:
        cleaned = music_directory.strip()
        if cleaned != row.music_directory:
            if cleaned and not Path(cleaned).is_dir():
                raise ValueError(f"曲库目录不存在: {cleaned}")
            row.music_directory = cleaned
            new_directory = effective_music_directory(session)
    session.commit()
    return new_directory


def record_cellular_bytes(session: Session, amount: int) -> str:
    """往当月账上记一笔 (月份按本地时区); 返回记进的月份。"""
    month = datetime.now(config.LOCAL_TZ).strftime("%Y-%m")
    row = session.get(CellularUsage, month)
    if row is None:
        session.add(CellularUsage(month=month, bytes=amount))
    else:
        row.bytes += amount
    session.commit()
    return month


def cellular_months(session: Session,
                    limit: int = _MONTHS_SHOWN) -> list[CellularMonth]:
    """流量月账 (新→老, 最多这几个月)。"""
    return [CellularMonth(month=month, bytes=bytes_amount)
            for month, bytes_amount in session.execute(
                select(CellularUsage.month, CellularUsage.bytes)
                .order_by(CellularUsage.month.desc()).limit(limit))]
