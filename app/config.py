"""环境变量配置 (见 .env.example), 集中读取避免散落各处。

组合仓口径: 这里只管共享层 (账号库 / 会话密钥 / 登录限速); 三个应用的
配置在各自子仓里 (apps/*/app/config.py), 由本仓 main.py 用环境变量把
库文件指到同一份 data/ 下。密码不设默认值 —— 仓库公开, 不带默认口令,
首启种子管理员只认 .env 里设过的 AUTH_PASS。
"""
import os
from pathlib import Path
from zoneinfo import ZoneInfo

APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent


def _sqlite_url(value: str) -> str:
    """env 值 → SQLAlchemy URL: 裸路径当仓内 SQLite 文件 (相对仓根),
    带协议 (sqlite:///…) 的原样 —— .env 里两种写法都认。"""
    if "://" in value:
        return value
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_DIR / path
    return f"sqlite:///{path}"


# 时间: 库内为 UTC 裸时间戳, 对外输出本地时间 (默认北京时间)
LOCAL_TZ = ZoneInfo(os.environ.get("TZ_NAME", "Asia/Shanghai"))

# 鉴权 (env 可覆盖; AUTH_PASS 不设默认值, 首启不种管理员)
AUTH_USER = os.environ.get("AUTH_USER", "admin")
AUTH_PASS = os.environ.get("AUTH_PASS", "")
SESSION_DAYS = int(os.environ.get("SESSION_DAYS", "90"))
SECRET_FILE = Path(os.environ.get("MYHOME_SECRET_FILE")
                   or PROJECT_DIR / ".session_secret")

# 登录限速: 单 IP 连续失败 5 次锁定 60 秒
LOGIN_MAX_FAILS = 5
LOGIN_LOCK_S = 60

# 账号库 (SQLite, 与业务库分开的独立文件): 用户 + 注册邀请
# (裸路径相对仓根; 旧名 MYTESLA_USERS_DB 也认, 三个子仓读同名变量)
USERS_DB_URL = _sqlite_url(
    os.environ.get("MYHOME_USERS_DB")
    or os.environ.get("MYTESLA_USERS_DB")
    or str(PROJECT_DIR / "data" / "users.db"))
