#!/bin/sh
# acme.sh 续期后的 Le_ReloadCmd: 新证书已由 --install-cert 落到 data/certs/,
# 重启服务加载 (NAS 时代是 deploy/restart_service.sh, 换成 systemd --user)。
exec /usr/bin/systemctl --user restart my-home.service
