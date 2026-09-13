// changelog.js — 更新日志页: 合并批次的版本条目 (新增/改进/修复, 用户视角文案)
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

const KIND_CLS = { "新增": "add", "改进": "imp", "修复": "fix" };

function render(list) {   // 行写进内层 #list, 加载/错误节点不被顶掉
  $("#list").innerHTML = list.map(v => `
    <div class="ver">
      <div class="v-head">
        <span class="v-badge">${esc(v.version)}</span>
        <span class="v-date">${esc(v.date)}</span>
      </div>
      <ul class="v-items">${v.items.map(it => `
        <li><span class="k k-${KIND_CLS[it.kind] || "imp"}">${esc(it.kind)}</span><span class="t">${esc(it.text)}</span></li>`).join("")}
      </ul>
    </div>`).join("");
}

async function load() {
  $("#error").hidden = true;
  $("#loading").hidden = false;
  try {
    const list = await getJSON("/tesla/changelog/api/entries");
    if (list.length) render(list);
    else showError("还没有版本记录");
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
