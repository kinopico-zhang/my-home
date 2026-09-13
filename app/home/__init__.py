"""My Home 门厅 —— 共享层: 根路径的应用入口 + 账号体系 (登录/注册/账号管理)。

账号是所有应用共享的, 不属于任何一个应用 (My Tesla / My Money), 所以
这些页面和接口都挂在根路径下, 静态资源也在本包自己的目录里。
"""
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent / "static"
