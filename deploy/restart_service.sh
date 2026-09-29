#!/bin/sh
# 重启 My Home 服务 (走仓库根的 run.sh: 自动带 .env 与 HTTPS 证书;
# admin 身份、后台运行、日志 data/mytesla.log)。
# 手动重启用; acme.sh 续完证书的 reloadcmd 也是它 —— root 调时先把
# 证书属主交给 admin (服务以 admin 跑, 读不了 root 600)。
# acme.sh 家在 data/.acme.sh (2026-09-19 从 /root 迁来, /root 重启会丢;
# 每日 04:17 续期见 /etc/config/crontab)。
# 2026-09-23 日志从 /tmp/mytesla.log 挪来 data/: /tmp 是 64MB 内存盘,
# 听歌的流媒体请求一行行刷日志, 一两天就撑满 —— 满了 sqlite 临时空间
# 跟着 ENOSPC, 接口成片 503 (新建播放列表实报), 测试也报 database or
# disk is full。启动时翻一代旧的 (data/mytesla.log.1), 硬盘 9TB 随便长。
# 2026-09-28 服务的临时文件也钉离 /tmp: TMPDIR/SQLITE_TMPDIR 指
# data/service-tmp (大盘) —— /tmp 连 QNAP 系统自己都会占满 (当天被
# Music Station 缓存占到 98%, 测试排序溢出实报 database or disk is full),
# 服务的 sqlite 溢出与 python 临时文件从此不指望它。
cd "$(dirname "$0")/.." || exit 1
if [ "$(id -u)" = "0" ] && [ -f data/certs/privkey.pem ]; then
  chown admin data/certs/privkey.pem data/certs/fullchain.pem 2>/dev/null
  chmod 600 data/certs/privkey.pem
fi
# QNAP 没有 pkill (静默失败会端口冲突), 用 ps+kill 找 pid
PIDS=$(ps | grep 'uvicorn app.main:app' | grep -v grep | awk '{print $1}')
[ -n "$PIDS" ] && kill $PIDS 2>/dev/null
sleep 2
[ -f data/mytesla.log.1 ] && rm -f data/mytesla.log.1
[ -f data/mytesla.log ] && mv data/mytesla.log data/mytesla.log.1
if [ "$(id -u)" = "0" ]; then
  chown admin data/mytesla.log.1 2>/dev/null
fi
/usr/bin/sudo -u admin sh -c 'mkdir -p /share/CACHEDEV1_DATA/Public/my-home/data/service-tmp && exec /bin/setsid env TMPDIR=/share/CACHEDEV1_DATA/Public/my-home/data/service-tmp SQLITE_TMPDIR=/share/CACHEDEV1_DATA/Public/my-home/data/service-tmp /share/CACHEDEV1_DATA/Public/my-home/run.sh >> /share/CACHEDEV1_DATA/Public/my-home/data/mytesla.log 2>&1 < /dev/null &'
