// changelog.js — 更新日志页: 逐提交版本条目 (x.y.z: x=架构重构, y=特性, z=修复)
"use strict";
/* 页签菜单: 点空白处收起。 */
document.addEventListener("click", e => {
  const t = e.target;
  if (!(t instanceof Element) || !t.isConnected) return;
  const inside = t.closest("details.nav-menu");
  document.querySelectorAll("details.nav-menu[open]").forEach(m => {
    if (m !== inside) m.removeAttribute("open");
  });
});
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g,
  c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));

async function getJSON(url) {
  const r = await fetch(url, { cache: "no-store" });
  if (r.status === 401) { location.replace("/tesla/login"); throw new Error("未登录"); }
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || ("HTTP " + r.status));
  return r.json();
}

function render(list) {   // 行写进内层 #list, 加载/错误节点不被顶掉
  $("#list").innerHTML = list.map(e => `
    <div class="ver">
      <span class="v-badge">${esc(e.version)}</span>
      <span class="v-chip ${esc(e.type)}">${esc(e.type_label)}</span>
      <div class="v-body">
        <div class="v-subj">${esc(e.subject)}</div>
        <div class="v-meta">${esc(e.date)} · ${esc(e.hash)}</div>
      </div>
    </div>`).join("");
}

async function load() {
  $("#error").hidden = true;
  $("#loading").hidden = false;
  try {
    const list = await getJSON("/tesla/changelog/api/entries");
    if (list.length) render(list);
    else showError("没有版本历史 (服务目录不是 git 仓库)");
  } catch (e) {
    showError(e.message);
  }
  $("#loading").hidden = true;
}
function showError(msg) {
  $("#error-text").textContent = msg || "加载失败";
  $("#error").hidden = false;
}

$("#retry").addEventListener("click", load);
$("#logout").addEventListener("click", async () => {
  try { await fetch("/tesla/api/logout", { method: "POST" }); } catch (e) {}
  location.href = "/tesla/login";
});

load();
