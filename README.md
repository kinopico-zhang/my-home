# myteslamate — My Tesla

读取 QNAP 上 `teslamate_cn` (TeslaMate) 的 PostgreSQL 数据, 用手机友好的
iOS 风格页面展示充电记录与行驶足迹: 充电页瀑布流卡片 + 懒加载 + 充电曲线,
足迹页高德地图轨迹回放。App 名称: **My Tesla**。

所有页面挂在 `/tesla` 前缀下: `/tesla/charging` (充电记录) 和
`/tesla/map` (足迹地图), 各页面 API 独立子路径 (`/tesla/charging/api/*`、
`/tesla/map/api/*`)。


## 鉴权

所有页面和 API 需要登录 (cookie 会话, 默认 90 天有效):

- 默认账号 `admin` / `daozi1994`, 可用环境变量 `AUTH_USER` / `AUTH_PASS` 覆盖
- `AUTH_USER=admin AUTH_PASS=xxx ./run.sh` 即可改账号密码 (改密码会踢掉所有旧会话)
- 登录接口有防爆破: 单 IP 连续失败 5 次锁定 60 秒
- 「退出」会轮换会话密钥, 所有设备都需要重新登录
- 注意: 服务走明文 HTTP, 密码与数据在公网传输时可被截获; 建议后续上 HTTPS
  (或改为只在家庭网络/VPN 内访问)

## 运行

```sh
./run.sh                 # http://NAS_IP:8500/tesla
PORT=9000 ./run.sh       # 换端口
```

`run.sh` 会自动加载同目录 `.env` (见 `.env.example`): 足迹地图需要高德
开放平台的 Key (`AMAP_KEY` + `AMAP_SECURITY_CODE`, 服务平台选「Web端 JS API」,
个人开发者免费)。未配置时地图页会显示申请指引。

依赖装在 `.venv` (Python 3.13, 由 `../python-env` 的 uv 创建):

```sh
export UV_CACHE_DIR=../python-env/uv-cache UV_PYTHON_INSTALL_DIR=../python-env/uv-python
../python-env/bin/uv pip install --python .venv/bin/python -r requirements.txt
```

## 结构

```
app/main.py             FastAPI: API + 静态页面 (/tesla 路由)
app/db.py               定位 teslamate_cn 的 postgres 容器 (docker inspect), 连接池
app/static/index.html   充电记录页 (iOS 暗色风格, ECharts 本地化)
app/static/login.html   登录页 (iOS 弹窗风格, 支持查看密码 / 失败原因)
app/static/map.html     足迹地图页 (高德地图 JS API 2.0)
app/static/gcj02.js     WGS-84 → GCJ-02 坐标转换 (高德火星坐标)
app/static/echarts.min.js
tests/                  pytest 后端测试 + node 坐标转换测试
data/tracks_cache.json  轨迹下采样缓存 (自动生成, git 忽略)
```

## 数据源

- 容器 `teslamate_cn_database_1` (postgres 17), 表: `charging_processes` /
  `charges` / `addresses` / `geofences` / `cars`
- 容器 IP 不固定, `db.py` 启动时用 docker inspect 自动解析;
  也可用环境变量 `TMDB_HOST` 直接指定
- 库内时间戳为 UTC, API 输出统一转为北京时间 (`TZ_NAME` 可改)
- 快充判定: `fast_charger_present` 或峰值功率 ≥ 20 kW

## API

登录接口 (无需鉴权): `POST /tesla/api/login` / `POST /tesla/api/logout`。

充电记录 API (前缀 `/tesla/charging/api`):

| 路径 | 说明 |
|---|---|
| `GET /car` | 车辆信息 |
| `GET /summary?from&to` | 汇总统计 (次数/电量/费用/均价/快充占比…) |
| `GET /sessions?offset&limit&type&from&to&q&sort` | 充电记录分页列表 |
| `GET /sessions/{id}` | 详情 + 充电曲线采样 (SOC/功率/电压/电流) |
| `PATCH /sessions/{id}/cost` | 更新/添加/清除费用 (`{"cost": 25.5}`, `null` 为清除), 写回 TeslaMate 库 |
| `GET /monthly?from&to` | 按月聚合 |
| `GET /locations?from&to` | 按地点聚合 |

足迹地图 API (前缀 `/tesla/map/api`):

| 路径 | 说明 |
|---|---|
| `GET /config` | 高德 Key 配置状态 (来自环境变量) |
| `GET /summary?from&to` | 行程数 / 总里程 / 总时长 |
| `GET /tracks?from&to` | 全部轨迹 (服务端下采样, 每行程 ≤26 点, WGS-84 坐标) |

`from`/`to` 为北京时间日期 (`YYYY-MM-DD`); `type` = fast / slow。

轨迹性能: positions 表千万行, 全量下采样 ~15s, 结果落盘 `data/` 并按
新行程 id 增量追加 (常态毫秒级); 启动时后台线程自动预热。

## 测试

```sh
./run_tests.sh                                  # 全部
.venv/bin/python -m pytest tests -q             # 后端 (pytest)
node --test tests/js/gcj02.test.mjs             # 前端坐标转换纯函数
```

后端测试不依赖真实数据库 (FakePool + patch `query`), 覆盖鉴权/限速/登出
轮换/中间件/充电 API/费用校验/轨迹缓存增量逻辑。

## 配色

图表系列色 `#1fa349 #3987e5 #c98500 #9085e9 #d95926` (绿=SOC, 蓝=功率·电量,
黄=费用, 紫=电压, 橙=电流), 已通过 dataviz 六项校验 (暗色表面 `#1c1c1e`)。
单系列图表不带图例, 无双轴, 文本一律用文本色。
