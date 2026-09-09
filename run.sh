#!/bin/sh
# 启动充电记录服务, 默认端口 8500 (PORT=xxx ./run.sh 可改)
cd "$(dirname "$0")" || exit 1
exec .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8500}"
