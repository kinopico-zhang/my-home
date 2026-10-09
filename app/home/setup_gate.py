"""首启引导的缺口判定 (组合仓变体): Tesla 应用的两步走 mytesla 前缀。

home 层先于子仓装载 (app.main 的 import 顺序), 这里必须懒加载 —— 请求
到达时 mytesla.* 早已在 sys.modules。组合仓的 /setup 是三步版 (管理员 →
TeslaMate → 高德 Key), 缺口跟着 Tesla 应用走; 独立仓的变体直连自己的
设置, 非 Tesla 子应用仓则恒空 (它们只有账号一步)。"""
import importlib


def wizard_missing() -> list[str]:
    """还差的配置步 ("teslamate" / "amap", 全配齐 = 空表)。"""
    tesla_database = importlib.import_module("mytesla.app.database")
    tesla_settings_store = importlib.import_module(
        "mytesla.app.tesla.settings_store")
    with tesla_database.own_session_factory()() as own:  # pylint: disable=not-callable
        return tesla_settings_store.wizard_missing(own)  # type: ignore[no-any-return]
