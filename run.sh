#!/bin/sh
# 启动服务, 默认端口 8500 (PORT=xxx ./run.sh 可改)。
# 存在 .env 时自动加载 (AMAP_KEY / AMAP_SECURITY_CODE 等, 见 .env.example)。
# data/certs/ 下有证书时自动以 HTTPS 起服务 (Let's Encrypt, DNS-01 签发与续期
# 见 deploy/ 下脚本); HTTP=1 ./run.sh 可临时回明文调试。
cd "$(dirname "$0")" || exit 1
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi
if [ -f data/certs/fullchain.pem ] && [ "${HTTP:-0}" != "1" ]; then
  exec .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8500}" \
    --ssl-keyfile data/certs/privkey.pem --ssl-certfile data/certs/fullchain.pem
fi
exec .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8500}"
