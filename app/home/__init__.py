"""共享账号层: 登录/注册/账号管理 + 会话中间件 (静态文件在 app/home/static)。

拆仓后 My Home 只剩这一层是"自己的"应用代码 —— 三个应用 (My Tesla /
My Money / My Music) 都在 apps/ 下的子仓里, 由 main.py 以合成包名装载;
账号体系与门厅时代完全同一套 (/api/*, 同一枚会话 cookie, path=/)。"""
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent / "static"
