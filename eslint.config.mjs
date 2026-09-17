// ESLint 9 扁平配置 —— 共享层前端门禁 (组合仓只管 app/home/static 的
// 账号页面脚本; 三个应用的前端门禁在各自仓里, 见 apps/*/eslint.config.mjs)。
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
  // 不检查: venv / 数据目录 / node_modules / 三个子仓 (各有各的门禁)
  { ignores: [".venv/**", "data/**", "node_modules/**", "apps/**"] },

  // 共享账号层 (app/home/static): 登录/注册/账号管理页面脚本 + 全站小件
  // (menu-user.js 被 Tesla 的页面引用 —— 组合部署时挂在根 /static 下)
  {
    files: ["app/home/static/*.js"],
    ...pageScript,
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "script",
      globals: {
        ...globals.browser,
      },
    },
  },
];
