#!/bin/sh
# My Home 对外隧道: NAS 0.0.0.0:8500 -> 本机 127.0.0.1:8500 (ssh -R 反向转发)。
# 服务迁来 WSL (mirrored 网络) 后, Windows 双层防火墙 (主防火墙 + Hyper-V)
# 拦 LAN 入站, 本机 8500 外面摸不着 —— 借 NAS 当门面: 路由器 8500 转发指向
# NAS (内网固定 IP, 不入仓), NAS 经隧道把流量送回 WSL 里的 uvicorn (端到端 TLS
# 原样穿透, 隧道只搬 TCP 字节)。
# NAS sshd 已开 GatewayPorts clientspecified (/etc/config/ssh/sshd_config,
# QNAP 持久路径; 不开的话 -R 只肯绑 127.0.0.1, 外面进不来)。
# 断线由 systemd Restart 重连。
exec ssh -N -R 0.0.0.0:8500:127.0.0.1:8500 \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 -o ServerAliveCountMax=4 \
  -o BatchMode=yes nas
