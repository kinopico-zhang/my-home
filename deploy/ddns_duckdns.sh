#!/bin/sh
# DuckDNS 动态域名更新: 家宽公网 IP 变了就把 kinopico.duckdns.org 指过去,
# 手机在外面 (路由器 8500 端口转发) 和在家里 (路由器回环) 都走这一个地址。
# QTS 定时任务每 5 分钟调一次 (登记在 /etc/config/crontab, 重启 NAS 也在);
# token 放 data/duckdns.token (data/ 在 gitignore, 不进仓库)。
# ip 参数留空 = DuckDNS 记录 "请求方的出口 IP" —— NAS 直连出去, 拿到的就是
# 真实家宽 IP。别从挂代理的设备上手动更新, 会把代理出口当成家宽 IP
# (域名里那个华为云 IP 就是注册时代理出口被自动记下的)。
cd "$(dirname "$0")/.." || exit 1
TOKEN=$(cat data/duckdns.token 2>/dev/null)
[ -n "$TOKEN" ] || exit 0   # 还没配 token, 静默跳过
RESULT=$(curl -s --max-time 20 \
  "https://www.duckdns.org/update?domains=kinopico&token=$TOKEN&ip=")
echo "$(date '+%F %T') $RESULT" >> data/ddns.log
# 日志只增不减, 超 4000 行砍掉前一半
if [ "$(wc -l < data/ddns.log)" -gt 4000 ]; then
  tail -n 2000 data/ddns.log > data/ddns.log.tmp && mv data/ddns.log.tmp data/ddns.log
fi
