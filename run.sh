#!/bin/sh
# 启动服务, 默认端口 8500 (PORT=xxx ./run.sh 可改)。
# 存在 .env 时自动加载 (AMAP_KEY / AMAP_SECURITY_CODE 等, 见 .env.example)。
cd "$(dirname "$0")" || exit 1
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi
exec .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8500}"
