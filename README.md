<div align="center">

# 🏠 My Home

**家庭自用 Web 应用组合仓** — 共享账号单点登录 + 三个 submodule 应用

[![CI](https://github.com/kinopico-zhang/my-home/actions/workflows/ci.yml/badge.svg)](https://github.com/kinopico-zhang/my-home/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/kinopico-zhang/my-home)](./LICENSE)
![Python](https://img.shields.io/badge/Python-3.13%20%7C%203.14-3776AB?logo=python&logoColor=white)
![Node.js](https://img.shields.io/badge/Node.js-22-339933?logo=nodedotjs&logoColor=white)
![OS](https://img.shields.io/badge/OS-Linux%20%7C%20Windows%20%7C%20macOS-0078D6)

![pylint](https://img.shields.io/badge/pylint-10.00%2F10-brightgreen)
![mypy](https://img.shields.io/badge/mypy-strict-2A6DB2)
![pytest](https://img.shields.io/badge/pytest-55%20passed-0A9EDC?logo=pytest&logoColor=white)

![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-d71f00?logo=sqlalchemy&logoColor=white)
![Pydantic](https://img.shields.io/badge/Pydantic-v2-e92063?logo=pydantic&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-3-003B57?logo=sqlite&logoColor=white)
![SSO](https://img.shields.io/badge/SSO-HMAC%20cookie-1E90FF)
![apps](https://img.shields.io/badge/apps-3%20submodules-8A2BE2)

![ESLint](https://img.shields.io/badge/ESLint-passing-4B32C3?logo=eslint&logoColor=white)
![stylelint](https://img.shields.io/badge/stylelint-passing-263238?logo=stylelint&logoColor=white)
![html-validate](https://img.shields.io/badge/html--validate-passing-brightgreen)

[![stars](https://img.shields.io/github/stars/kinopico-zhang/my-home)](https://github.com/kinopico-zhang/my-home/stargazers)
[![issues](https://img.shields.io/github/issues/kinopico-zhang/my-home)](https://github.com/kinopico-zhang/my-home/issues)
[![last commit](https://img.shields.io/github/last-commit/kinopico-zhang/my-home)](https://github.com/kinopico-zhang/my-home/commits/main)
[![repo size](https://img.shields.io/github/repo-size/kinopico-zhang/my-home)](https://github.com/kinopico-zhang/my-home)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/kinopico-zhang/my-home/pulls)

</div>

家里三个自用 Web 应用的组合仓: 共享账号层 (登录/注册/账号管理 + 会话
中间件) + 三个以 git submodule 挂在 `apps/` 下的独立应用。单点登录,
同一枚会话 cookie 全站通行。

| 应用 | 子仓 | 地址 (组合部署) | 独立部署 |
|---|---|---|---|
| 🚗 My Tesla | `apps/my-tesla` | `/tesla/charging` (根路径 302 进 `/music`) | [kinopico-zhang/my-tesla](https://github.com/kinopico-zhang/my-tesla) |
| 💰 My Money | `apps/my-money` | `/bookkeeping` | [kinopico-zhang/my-money](https://github.com/kinopico-zhang/my-money) |
| 🎵 My Music | `apps/my-music` | `/music` | [kinopico-zhang/my-music](https://github.com/kinopico-zhang/my-music) |

三个子仓各自可以单独 clone、单独部署 (带自己的鉴权层), 也可以像本仓
这样组合部署 —— 账号库/曲库/记账库/TeslaMate 镜像库四份数据都在本仓
`data/` 下, 单点登录。独立部署想共用账号也行: 让各实例的
`MYHOME_USERS_DB` / `MYHOME_SECRET_FILE` 指到同一份 `users.db` 和
`.session_secret` —— 会话 cookie 是无状态 HMAC 签名, 跨端口、跨实例都认
(HTTP 直连同样可用, cookie 不带 secure 标记)。

## ✨ 亮点

- 🔐 **共享账号层** — 登录 / 注册 / 账号管理 + 会话中间件, 一枚 cookie 全站通行
- 🛡️ **登录防爆破** — 单 IP 连续失败 5 次锁定 60 秒; 「退出」轮换会话密钥
- 💌 **邀请注册** — 链接一次性、限时
- 🔗 **旧地址兼容** — 账号体系还在 `/tesla` 下的老书签 / 邀请链接自动 302/307 搬家
- 🧩 **合成包装载** — 子仓包名都叫 `app`, 装载时造合成顶级前缀, 相对导入自洽
- 🔌 **HTTPS 可选** — 有证书双端口 (8500 TLS + 8501 明文), 没证书单明文直接用

## 🚀 快速开始

```sh
git clone --recursive git@github.com:kinopico-zhang/my-home.git
cd my-home
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env    # 填 AUTH_PASS (首启种管理员) + 高德 Key
./run.sh                # http://IP:8500 起明文服务
```

`run.sh` 自动加载 `.env`: 没证书就单进程跑明文 HTTP; 有 `data/certs/`
证书则 8500 走 HTTPS、`HTTP_PORT` (默认 8501) 并行开一个明文口给局域网
直连, `HTTP=1 ./run.sh` 可随时强制明文。

首次启动会用 `AUTH_PASS` 种管理员 `admin` (已有账号库不受影响);
足迹地图需要高德开放平台 Key (`AMAP_KEY` + `AMAP_SECURITY_CODE`,
个人开发者免费)。

生产部署在 WSL 里以 systemd 用户服务常驻, 对外经 NAS `ssh -R` 反向隧道
(`deploy/local/` 里是隧道 / 证书续期重载脚本)。

## 🔐 鉴权

- 所有页面与 API 需要登录 (cookie 会话, 默认 90 天); 各应用 scope 内
  自带登录页 (会话过期 302 不越出 scope, 全屏 App 不弹回浏览器)
- 登录接口防爆破: 单 IP 连续失败 5 次锁定 60 秒; 「退出」轮换会话密钥
- 账号管理 `/accounts` 仅管理员; 邀请注册链接一次性、限时
- 旧地址兼容: 账号体系还在 `/tesla` 下的老书签/邀请链接自动 302/307 搬家

## ⚙️ 环境变量

完整清单见 [.env.example](.env.example), 常用项:

| 变量 | 默认 | 说明 |
|---|---|---|
| `AUTH_PASS` (`AUTH_USER`) | 空 (`admin`) | 首启种子管理员 (只在空账号库时种) |
| `AMAP_KEY` / `AMAP_SECURITY_CODE` | 空 | 高德 Web端 JS API (My Tesla 足迹地图用) |
| `TMDB_*` | docker 定位 | TeslaMate PostgreSQL (My Tesla; 未在设置页填时回落) |
| `MYTESLA_MUSIC_DIR` | `/share/Media/Music` | 曲库根目录 (My Music 首扫) |
| `PORT` / `HTTP_PORT` / `HTTP` | `8500` / `8501` | 双端口; `HTTP=1` 强制明文 |
| `MYHOME_USERS_DB` / `MYHOME_SECRET_FILE` | `data/users.db` / `.session_secret` | 共享账号库与密钥 |
| `MYTESLA_MUSIC_DB` / `MYTESLA_BOOKKEEPING_DB` / `MYTESLA_DB` | `data/*.db` | 三应用数据 / 自产库 |

## 🧩 装载方式

子仓的包名都叫 `app`, 与本仓自己的 `app` 并存: `app/main.py` 装载时给
每个子仓造一个合成顶级前缀 (`mymusic` / `mymoney` / `mytesla`), import
系统顺着前缀找到 `apps/<仓>/app`, 仓内的相对导入全部自洽。

子仓配置全走环境变量 (库文件路径等), 装载前 `_env_defaults()` 把默认值
指到本仓 `data/` —— 想改路径就在 `.env` 里设同名变量覆盖。

## 🧪 测试与质量门禁

```sh
./run_tests.sh                                  # 全部 (含容器里的前端门禁)
.venv/bin/python -m pytest tests -q             # 后端 (共享层 + 装配接线)
```

门禁全绿才算过: pylint 10.00/10 (app 严检) · mypy 严格模式 · pytest
(真实 ORM + SQLite 临时库) · ESLint / stylelint / html-validate (共享层
前端)。CI 在 GitHub Actions 三平台跑同一套门禁。

组合仓的测试只覆盖共享层与装配接线; 三个应用的深度测试在各自仓里
(`apps/*/tests`, 各自的 CI 也各自跑)。前端门禁同理只管共享层页面。

## 📁 结构

```
app/main.py       组合装配: 合成包装载 + 四套引擎 + 路由/挂载
app/home/         共享账号层: 登录/注册/账号管理页面 + 会话中间件
apps/my-tesla     My Tesla (submodule, 独立仓)
apps/my-money     My Money (submodule, 独立仓)
apps/my-music     My Music (submodule, 独立仓)
data/             四份 SQLite (users/music/bookkeeping/mytesla) + 轨迹缓存
deploy/local/     WSL 部署脚本 (NAS 反向隧道 / 证书续期重载 / TeslaMate 隧道)
```

数据源: TeslaMate 的 PostgreSQL (docker 容器自动定位, `TMDB_*` 可覆盖),
曲库根目录默认 `/share/Media/Music` (`MYTESLA_MUSIC_DIR` 可改)。
家宽 DDNS (DuckDNS) 已拆成姊妹仓
[kinopico-zhang/ddns](https://github.com/kinopico-zhang/ddns)
(独立 timer 每 5 分钟报 IP, 不再挂本仓 deploy/)。

## 🔄 子仓更新

```sh
git submodule update --remote apps/my-tesla   # 拉子仓最新 main
git add apps/my-tesla && git commit           # 组合仓钉住新指针
```

## 🔗 相关项目

| 仓 | 说明 |
|---|---|
| [My Tesla](https://github.com/kinopico-zhang/my-tesla) | TeslaMate 行车数据展示 |
| [My Money](https://github.com/kinopico-zhang/my-money) | 家庭记账 (离线 LWW 同步) |
| [My Music](https://github.com/kinopico-zhang/my-music) | NAS 曲库听歌 (Service Worker 离线) |
| [ddns](https://github.com/kinopico-zhang/ddns) | 家宽 DDNS (DuckDNS, timer 报 IP) |

## 📄 许可证

[MIT](./LICENSE) © 2026 kinopico (三个子仓各自带同款 MIT)
