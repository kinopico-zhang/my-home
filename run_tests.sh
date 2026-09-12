#!/bin/sh
# 运行全部测试与检查 (提交前全绿):
#   后端: pytest (覆盖率门禁 95%, 见 pyproject.toml [tool.coverage])
#   前端: ESLint (页面脚本+测试) / tsc --checkJs (纯逻辑模块) /
#         node --test + c8 覆盖率门禁 95% (gcj02 / trackutil / lastpage)
# ESLint/tsc 在调试容器里跑: 宿主 node (QNAP 自带) 缺 ICU 数据, 连
# eslint 9 内部的 unicode 属性正则都编译不了; 容器 node 22 没问题。
# 工具链装在共享目录 (.tmp-pptr/node_modules), 仓库内 node_modules 是指向
# 它的软链, 容器里通过同名路径镜像挂载让软链两边都能解析 (见容器 run 参数)。
cd "$(dirname "$0")" || exit 1
rc=0

.venv/bin/python -m pytest tests -q --cov=app || rc=1

DOCKER=/share/CACHEDEV1_DATA/.qpkg/container-station/bin/docker
if ! $DOCKER exec mytesla-debug sh -c \
  "cd /repo && node node_modules/eslint/bin/eslint.js app/static tests/js \
   && node node_modules/typescript/bin/tsc -p tsconfig.json"; then
  echo "前端静态检查失败 (或调试容器 mytesla-debug 未运行)" >&2
  rc=1
fi

# 单元测试 + 覆盖率门禁: 只统计三个纯逻辑模块 (页面脚本由 E2E 覆盖)
node node_modules/c8/bin/c8.js \
  --include 'app/static/gcj02.js' --include 'app/static/trackutil.js' \
  --include 'app/static/lastpage.js' \
  --check-coverage --lines 95 --branches 95 --functions 95 \
  --reporter text node --test tests/js/ || rc=1

exit $rc
