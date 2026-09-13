// home.js — My Home 门厅: 欢迎语 + 管理员专属的账号管理入口 + 退出登录
// (账号体系属于门厅这个共享层, 不属于任何一个应用)
"use strict";

(async () => {
  try {
    const r = await fetch("/api/me", { cache: "no-store" });
    if (r.status === 401) { location.replace("/login"); return; }
    const me = await r.json();
    document.getElementById("sub").textContent = "欢迎回来 · " + me.name;
    if (me.is_admin) {          // 账号管理只有管理员可见 (默认 display:none)
      document.getElementById("accounts-link").classList.add("admin-show");
      document.getElementById("accounts-sep").classList.add("admin-show");
    }
  } catch (_e) { /* 网络错误: 卡片照常可点, 不挡门厅 */ }
})();

document.getElementById("logout").addEventListener("click", async () => {
  await fetch("/api/logout", { method: "POST" });
  location.replace("/login");
});
