// ESLint 9 扁平配置 —— 前端门禁 (与后端 pylint/mypy 对齐, 由 run_tests.sh 调用)。
// node_modules 是指向共享工具目录的软链 (见 .gitignore), node 用 /opt/bin/node。
import js from "@eslint/js";
import globals from "globals";

export default [
  // 不检查: 高德/echarts 第三方压缩包、venv、数据目录
  { ignores: ["app/static/echarts.min.js", ".venv/**", "data/**", "node_modules/**"] },

  // 页面脚本 (script 而非 module): 浏览器全局 + 高德/echarts 注入的宿主对象
  {
    files: ["app/static/*.js"],
    ...js.configs.recommended,
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "script",
      globals: {
        ...globals.browser,
        AMap: "readonly",          // 高德 JS API 全局命名空间
        _AMapSecurityConfig: "writable",  // 高德安全密钥配置 (HTML 内联或页面赋值)
        echarts: "readonly",       // echarts.min.js 先于页面脚本加载
      },
    },
    rules: {
      // 页面脚本按事件驱动自然组织, 场景函数间互相调用是常态
      "no-use-before-define": ["error", { functions: false, classes: false }],
    },
  },

  // 记账应用 (app/bookkeeping/static): 独立应用的页面脚本, 与主应用同规则
  {
    files: ["app/bookkeeping/static/*.js"],
    ...js.configs.recommended,
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "script",
      globals: {
        ...globals.browser,
        // bookkeeping-merge.js 先于 bookkeeping.js 以经典脚本加载 (函数声明进全局)
        mergeEntries: "readonly", entriesToUpload: "readonly",
        remoteWins: "readonly", visibleEntries: "readonly", monthTotals: "readonly",
      },
    },
    rules: {
      "no-use-before-define": ["error", { functions: false, classes: false }],
    },
  },

  // 门厅共享层 (app/home/static): 账号体系页面 (登录/注册/账号管理) + 根路径门厅页
  {
    files: ["app/home/static/*.js"],
    ...js.configs.recommended,
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "script",
      globals: { ...globals.browser },
    },
    rules: {
      "no-use-before-define": ["error", { functions: false, classes: false }],
    },
  },

  // 前端单元测试 (node:test, ESM)
  {
    files: ["tests/js/*.mjs"],
    ...js.configs.recommended,
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: { ...globals.node },
    },
  },
];
