# My Home — 组合仓

家里三个自用 Web 应用的组合仓: 共享账号层 (登录/注册/账号管理 + 会话
中间件) + 三个以 git submodule 挂在 `apps/` 下的独立应用。单点登录,
同一枚会话 cookie 全站通行。

| 应用 | 子仓 | 地址 (组合部署) | 独立部署 |
|---|---|---|---|
| My Tesla | `apps/my-tesla` | `/tesla/charging` (根路径 302 进 `/music`) | `git@github.com:kinopico-zhang/my-tesla.git` |
| My Money | `apps/my-money` | `/bookkeeping` | `git@github.com:kinopico-zhang/my-money.git` |
| My Music | `apps/my-music` | `/music` | `git@github.com:kinopico-zhang/my-music.git` |

三个子仓各自可以单独 clone、单独部署 (带自己的鉴权层), 也可以像本仓
这样组合部署 —— 账号库/曲库/记账库/TeslaMate 镜像库四份数据都在本仓
`data/` 下, 单点登录。

## 装载方式

子仓的包名都叫 `app`, 与本仓自己的 `app` 并存: `app/main.py` 装载时给
每个子仓造一个合成顶级前缀 (`mymusic` / `mymoney` / `mytesla`), import
系统顺着前缀找到 `apps/<仓>/app`, 仓内的相对导入全部自洽。

子仓配置全走环境变量 (库文件路径等), 装载前 `_env_defaults()` 把默认值
指到本仓 `data/` —— 想改路径就在 `.env` 里设同名变量覆盖。

## 运行

```sh
git clone --recursive git@github.com:kinopico-zhang/my-home.git
cd my-home
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env    # 填 AUTH_PASS (首启种管理员) + 高德 Key
./run.sh                # http://NAS_IP:8500 (有 data/certs/ 证书则自动 HTTPS)
```

`run.sh` 自动加载 `.env`。首次启动会用 `AUTH_PASS` 种管理员 `admin`
(已有账号库不受影响); 足迹地图需要高德开放平台 Key
(`AMAP_KEY` + `AMAP_SECURITY_CODE`, 个人开发者免费)。

## 鉴权

- 所有页面与 API 需要登录 (cookie 会话, 默认 90 天); 各应用 scope 内
  自带登录页 (会话过期 302 不越出 scope, 全屏 App 不弹回浏览器)
- 登录接口防爆破: 单 IP 连续失败 5 次锁定 60 秒; 「退出」轮换会话密钥
- 账号管理 `/accounts` 仅管理员; 邀请注册链接一次性、限时
- 旧地址兼容: 账号体系还在 `/tesla` 下的老书签/邀请链接自动 302/307 搬家

## 结构

```
app/main.py       组合装配: 合成包装载 + 四套引擎 + 路由/挂载
app/home/         共享账号层: 登录/注册/账号管理页面 + 会话中间件
apps/my-tesla     My Tesla (submodule, 独立仓)
apps/my-money     My Money (submodule, 独立仓)
apps/my-music     My Music (submodule, 独立仓)
data/             四份 SQLite (users/music/bookkeeping/mytesla) + 轨迹缓存
deploy/           QNAP 重启脚本 / DDNS / 证书续期
```

数据源: TeslaMate 的 PostgreSQL (docker 容器自动定位, `TMDB_*` 可覆盖),
曲库根目录默认 `/share/Media/Music` (`MYTESLA_MUSIC_DIR` 可改)。

## 测试

```sh
./run_tests.sh                                  # 全部 (含容器里的前端门禁)
.venv/bin/python -m pytest tests -q             # 后端 (共享层 + 装配接线)
```

组合仓的测试只覆盖共享层与装配接线 (49 例); 三个应用的深度测试在各自
仓里 (`apps/*/tests`, 各自的 CI 也各自跑)。前端门禁 (ESLint / stylelint /
html-validate) 只管共享层页面, 同理。

## 子仓更新

```sh
git submodule update --remote apps/my-tesla   # 拉子仓最新 main
git add apps/my-tesla && git commit           # 组合仓钉住新指针
```
