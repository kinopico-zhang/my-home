#!/bin/sh
# 运行全部测试与检查 (提交前全绿):
#   后端: pylint (app 严检 / tests 放宽仪式代码) / mypy / pytest
#         (组合仓只查共享层 + 装配接线; 三个应用的深度测试在各自仓里)
#   前端: ESLint / stylelint (3 个 CSS) / html-validate (3 个页面) ——
#         只管共享层 app/home/static; 三个应用的前端门禁在各自仓
# ESLint/stylelint/html-validate 在调试容器里跑: 宿主 node (QNAP 自带) 缺
# ICU 数据, 连 eslint 9 内部的 unicode 属性正则都编译不了; 容器 node 22 没问题。
# 工具链版本锁在 package.json, node_modules 是实体目录; 容器重建后在容器里
# `cd /repo && npm install --no-package-lock` 重装 —— 千万别在仓库里
# `npm install <包名>` (无锁文件语境会把没列进命令行的包当无主树修剪掉)。
cd "$(dirname "$0")" || exit 1
rc=0

# pytest 的 tmp_path 优先放内存 (/dev/shm 3.8G tmpfs): 测试的 SQLite 种子库
# 全在内存里跑, 不用跟机械盘上的媒体服务抢 IO —— 那是全量测试最大的拖累。
# /tmp 只有 64M 不够一轮 (会 ENOSPC); /dev/shm 重启即清, 没有就退回仓库目录。
if [ -d /dev/shm ] && [ -w /dev/shm ]; then
  mkdir -p /dev/shm/myhome-pytest
  export TMPDIR=/dev/shm/myhome-pytest
else
  mkdir -p .pytest-tmp
  export TMPDIR="$PWD/.pytest-tmp"
fi

# 静态检查: app 严检; tests 是 pytest 仪式代码 (fixture 形参/保护访问/
# 模块内导入), 单独放宽这几类 —— 4.0 没有 per-path-ignores, 只好两次调用
.venv/bin/python -m pylint app || rc=1
.venv/bin/python -m pylint tests --disable=W0613,W0212,R0801,C0415 || rc=1
.venv/bin/python -m mypy || rc=1

.venv/bin/python -m pytest tests -q || rc=1

DOCKER=/share/CACHEDEV1_DATA/.qpkg/container-station/bin/docker
if ! $DOCKER exec mytesla-debug sh -c \
  "cd /repo && node node_modules/eslint/bin/eslint.js app/home/static \
   && node node_modules/stylelint/bin/stylelint.mjs 'app/home/static/css/*.css' \
   && node node_modules/html-validate/bin/html-validate.mjs 'app/home/static/*.html'"; then
  echo "前端静态检查失败 (或调试容器 mytesla-debug 未运行)" >&2
  rc=1
fi

exit $rc
