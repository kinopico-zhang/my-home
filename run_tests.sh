#!/bin/sh
# 运行全部测试: 后端 pytest + 前端坐标转换 node --test
cd "$(dirname "$0")" || exit 1
rc=0
.venv/bin/python -m pytest tests -q || rc=1
node --test tests/js/gcj02.test.mjs || rc=1
exit $rc
