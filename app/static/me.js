// me.js — 会话账号信息 (各页共享): 管理员才显示 .admin-only 元素 (账号管理入口)。
// 拉不到 (未登录/网络) 保持隐藏 —— 账号管理宁可少露不能错露。
"use strict";
(() => {
  const style = document.createElement("style");
  style.textContent = ".admin-only{display:none}.admin-only.admin-show{display:block}";
  document.head.appendChild(style);
  fetch("/tesla/api/me").then(r => (r.ok ? r.json() : null)).then(me => {
    if (!me || !me.is_admin) return;
    document.querySelectorAll(".admin-only").forEach(el =>
      el.classList.add("admin-show"));
  }).catch(() => { /* 保持隐藏 */ });
})();
