#!/bin/sh
# TeslaMate PostgreSQL SSH 隧道: 本机 127.0.0.1:15432 -> NAS docker 容器 :5432。
# PG 容器在 NAS 上没映射宿主端口, 局域网直连不了, 借已配好的 nas SSH 通道。
# 容器 IP 每次启动现查 (容器重建后 IP 会漂); 断线由 systemd Restart 重连重解析。
set -eu
NAS_DOCKER=/share/CACHEDEV1_DATA/.qpkg/container-station/bin/docker
IP=$(ssh -o BatchMode=yes nas \
  "$NAS_DOCKER inspect teslamate_cn_database_1 --format \
   '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'")
if [ -z "$IP" ]; then
  echo "teslamate-tunnel: 无法解析容器 IP" >&2
  exit 1
fi
echo "teslamate-tunnel: 127.0.0.1:15432 -> $IP:5432"
exec ssh -N -L 127.0.0.1:15432:"$IP":5432 \
  -o ServerAliveInterval=30 -o ServerAliveCountMax=4 -o ExitOnForwardFailure=yes nas
