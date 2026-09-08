# myteslamate — Tesla 充电记录展示

读取 QNAP 上 `teslamate_cn` (TeslaMate) 的 PostgreSQL 数据, 用手机友好的
iOS 风格页面展示充电记录: 瀑布流卡片 + 懒加载, 点击卡片查看充电曲线。

## 运行

```sh
./run.sh                 # http://NAS_IP:8080
PORT=9000 ./run.sh       # 换端口
```

依赖装在 `.venv` (Python 3.13, 由 `../python-env` 的 uv 创建):

```sh
export UV_CACHE_DIR=../python-env/uv-cache UV_PYTHON_INSTALL_DIR=../python-env/uv-python
../python-env/bin/uv pip install --python .venv/bin/python -r requirements.txt
```

## 结构

```
app/main.py          FastAPI: API + 静态页面
app/db.py            定位 teslamate_cn 的 postgres 容器 (docker inspect), 连接池
app/static/index.html  单页前端 (iOS 暗色风格, ECharts 本地化)
app/static/echarts.min.js
```

## 数据源

- 容器 `teslamate_cn_database_1` (postgres 17), 表: `charging_processes` /
  `charges` / `addresses` / `geofences` / `cars`
- 容器 IP 不固定, `db.py` 启动时用 docker inspect 自动解析;
  也可用环境变量 `TMDB_HOST` 直接指定
- 库内时间戳为 UTC, API 输出统一转为北京时间 (`TZ_NAME` 可改)
- 快充判定: `fast_charger_present` 或峰值功率 ≥ 20 kW

## API

| 路径 | 说明 |
|---|---|
| `GET /api/car` | 车辆信息 |
| `GET /api/summary?from&to` | 汇总统计 (次数/电量/费用/均价/快充占比…) |
| `GET /api/sessions?offset&limit&type&from&to&q&sort` | 充电记录分页列表 |
| `GET /api/sessions/{id}` | 详情 + 充电曲线采样 (SOC/功率/电压/电流) |
| `GET /api/monthly?from&to` | 按月聚合 |
| `GET /api/locations?from&to` | 按地点聚合 |

`from`/`to` 为北京时间日期 (`YYYY-MM-DD`); `type` = fast / slow。

## 配色

图表系列色 `#1fa349 #3987e5 #c98500 #9085e9 #d95926` (绿=SOC, 蓝=功率·电量,
黄=费用, 紫=电压, 橙=电流), 已通过 dataviz 六项校验 (暗色表面 `#1c1c1e`)。
单系列图表不带图例, 无双轴, 文本一律用文本色。
