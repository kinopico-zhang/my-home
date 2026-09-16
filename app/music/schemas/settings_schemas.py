"""设置与流量域的接口模型: 设置页状态/更新 + 蜂窝流量月账与上报。"""
from pydantic import BaseModel, Field


class MusicSettingsState(BaseModel):
    """设置页状态: 各字段现值 + 默认值参照 (空 = 用默认)。"""

    music_directory: str = ""
    music_directory_default: str = ""
    lyrics_api_enabled: bool = True
    lyrics_api_base: str = ""
    lyrics_api_default: str = ""
    cellular_months: list["CellularMonth"] = Field(default_factory=list)


class MusicSettingsUpdate(BaseModel):
    """POST /api/settings 的请求体 (缺字段 = 不动那项)。"""

    music_directory: str | None = None
    lyrics_api_enabled: bool | None = None
    lyrics_api_base: str | None = None


class CellularMonth(BaseModel):
    """一个月的蜂窝流量账。"""

    month: str               # "2026-09"
    bytes: int = 0


class CellularUsageReport(BaseModel):
    """POST /api/cellular-usage 的请求体 (一次上报的字节量)。"""

    bytes: int = Field(ge=0, le=1_073_741_824)   # 单次上限 1 GB, 灌水也灌不爆
