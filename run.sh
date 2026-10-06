#!/bin/sh
# 启动服务, 默认端口 8500 (PORT=xxx ./run.sh 可改)。
#   HTTPS → PORT      (默认 8500, Let's Encrypt 证书, acme.sh DNS-01 签发
#                      续期, 续完 reloadcmd 调 deploy/local/reload-cert.sh)
#   HTTP  → HTTP_PORT (默认 8501, 局域网 IP 直连明文访问)
# HTTPS 是可选的: 没证书时单进程明文 (裸 http://IP:8500 就能用),
# HTTP=1 ./run.sh 强制明文 (跳过 TLS, 单进程, 调试/内网部署用)。
# 存在 .env 时自动加载 (AMAP_KEY / HTTP_PORT 等, 见 .env.example)。
cd "$(dirname "$0")" || exit 1
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi
# --timeout-keep-alive 75: uvicorn 默认 5 秒就掐空闲连接, 手机公网每次翻页
#   都要重付 TCP+TLS 握手 (多两个往返) —— 放宽到一分多钟, 连着点页不再
#   重握手 (2026-10-03 「点设置/统计很久才响应」的配套, 重启后生效)

PY=.venv/bin/python
HOST=0.0.0.0
PORT="${PORT:-8500}"

# 没证书 (或显式 HTTP=1): 单明文进程, exec 顶替 shell
if [ ! -f data/certs/fullchain.pem ] || [ "${HTTP:-0}" = "1" ]; then
  exec $PY -m uvicorn app.main:app --host "$HOST" --port "$PORT" \
    --timeout-keep-alive 75
fi

# 有证书: HTTPS (主入口) + HTTP (局域网明文) 双开。会话 cookie 是无状态
# HMAC 签名, 两个进程通用 (登录一次两边都认); systemd 停服务时整个组一起收。
HTTP_PORT="${HTTP_PORT:-8501}"
$PY -m uvicorn app.main:app --host "$HOST" --port "$PORT" \
  --timeout-keep-alive 75 \
  --ssl-keyfile data/certs/privkey.pem --ssl-certfile data/certs/fullchain.pem &
TLS_PID=$!
$PY -m uvicorn app.main:app --host "$HOST" --port "$HTTP_PORT" \
  --timeout-keep-alive 75 &
PLAIN_PID=$!
trap 'kill $TLS_PID $PLAIN_PID 2>/dev/null' TERM INT
wait $TLS_PID $PLAIN_PID
