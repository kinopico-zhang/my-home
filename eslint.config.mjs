// ESLint 9 扁平配置 —— 前端门禁 (与后端 pylint/mypy 对齐, 由 run_tests.sh 调用)。
// node_modules 是指向共享工具目录的软链 (见 .gitignore), node 用 /opt/bin/node。
// 注意: `...js.configs.recommended` 只带 name/rules 等键, 块内若再写 `rules:`
// 会整体覆盖展开结果 ( recommended 悄悄失效过), 必须 `...js.configs.recommended.rules`。
import js from "@eslint/js";
import globals from "globals";

// 页面脚本通用规则: recommended 全量 + 允许函数提升引用 (事件驱动组织)
const pageScript = {
  ...js.configs.recommended,
  rules: {
    ...js.configs.recommended.rules,
    "no-use-before-define": ["error", { functions: false, classes: false }],
    // 经典脚本的 catch 静默吞错是常态 (fetch 失败已有兜底展示)
    "no-unused-vars": ["error", { caughtErrors: "none" }],
    "no-empty": ["error", { allowEmptyCatch: true }],
  },
};

export default [
  // 不检查: 高德/echarts 第三方压缩包、venv、数据目录
  { ignores: ["app/tesla/static/echarts.min.js", ".venv/**", "data/**", "node_modules/**"] },

  // Tesla 应用 (app/tesla/static/js): 纯逻辑 UMD 模块 (gcj02/trackutil/
  // track-animation/format/trip-playback/lastpage) 与页面脚本都住 js/ 子目录
  // (结构化重构: 大页面脚本按逻辑拆成见名知意的小文件, 经典脚本按各自
  // html 里的顺序加载)。跨模块引用走全局, 每个文件头部自带 /* global */
  // (用到别处定义的) 与 /* exported */ (本文件定义、别处用的) 注释 ——
  // 配置里不再按文件列举。加载层级见各 html: UMD 纯逻辑 → 页面脚本;
  // 行程页 trips-list (列表/筛选) 在 trips (弹层/播放) 之前。
  {
    files: ["app/tesla/static/js/*.js"],
    ...pageScript,
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "script",
      globals: {
        ...globals.browser,
        module: "readonly",               // UMD 尾巴: node 测试路径走 module.exports
        require: "readonly",              // UMD 模块间依赖 (track-animation/trip-playback)
        AMap: "readonly",                 // 高德 JS API 全局命名空间
        _AMapSecurityConfig: "writable",  // 高德安全密钥配置 (页面赋值)
        echarts: "readonly",              // echarts.min.js (static 根, 第三方) 先于页面脚本加载
      },
    },
  },
  {
    // gcj02 参考实现的常量 (PI/EE) 本就超出 double 精度, 逐位照抄别四舍五入
    files: ["app/tesla/static/js/gcj02.js"],
    ...pageScript,
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "script",
      globals: { ...globals.browser, module: "readonly" },
    },
    rules: { ...pageScript.rules, "no-loss-of-precision": "off" },
  },

  // 记账应用 (app/bookkeeping/static): 独立应用的页面脚本
  {
    files: ["app/bookkeeping/static/amount-calculator.js",
            "app/bookkeeping/static/bookkeeping-merge.js"],
    ...pageScript,
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "script",
      globals: { ...globals.browser, module: "readonly" },
    },
  },
  {
    files: ["app/bookkeeping/static/bookkeeping.js"],
    ...pageScript,
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "script",
      globals: {
        ...globals.browser,
        // bookkeeping-merge.js / amount-calculator.js 先于 bookkeeping.js
        // 以经典脚本加载 (函数声明进全局)
        mergeEntries: "readonly", entriesToUpload: "readonly",
        remoteWins: "readonly", visibleEntries: "readonly", monthTotals: "readonly",
        evaluateAmount: "readonly", applyAmountKey: "readonly",
      },
    },
  },

  // 门厅共享层 (app/home/static): 账号体系页面 (登录/注册/账号管理) + 根路径门厅页
  {
    files: ["app/home/static/*.js"],
    ...pageScript,
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "script",
      globals: { ...globals.browser },
    },
  },

  // 音乐应用 (app/music/static): 纯逻辑模块 + 公共小件 + 播放器/浏览页模块
  // 都住 js/ 子目录 (结构化重构: music.js / music-player.js 按逻辑拆成
  // 见名知意的小文件, 经典脚本按 music.html 里的顺序加载; 分享页模块在
  // js/share/, 按 share.html 的顺序, 与应用页同名助手 ($ 等) 互不相干)。
  // 跨模块引用走全局, 每个文件头部自带 /* global */ (用到别处定义的) 与
  // /* exported */ (本文件定义、别处用的) 注释 —— 配置里不再按文件列举。
  {
    files: ["app/music/static/js/*.js", "app/music/static/js/share/*.js"],
    ...pageScript,
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "script",
      globals: {
        ...globals.browser,
        module: "readonly",        // downloads 两文件的 UMD 尾巴 (node 测试路径)
      },
    },
  },
  {
    // Service Worker: 独立线程, 全局是 self/caches (不碰页面 DOM)
    files: ["app/music/static/sw.js"],
    ...pageScript,
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "script",
      globals: { ...globals.serviceworker },
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
