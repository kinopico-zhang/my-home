// bookkeeping-boot — My Money 开局: 退出登录 + 进页渲染/拉类别树/首同步。
// 拆自 bookkeeping.js (结构化重构: 代码逐字节未动, 经典脚本按 bookkeeping.html 里的顺序加载, 跨模块引用走全局)。
"use strict";
/* global $, render, loadCategories, syncNow */

$("#logout").addEventListener("click", async () => {
  await fetch("/bookkeeping/api/logout", { method: "POST" });
  location.replace("/login");
});

/* ---------- 启动 ---------- */
render();
loadCategories();
syncNow();
