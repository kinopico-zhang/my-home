// bookkeeping-sync — My Money 同步: 状态条 + 上行/增量下行 (LWW 纯逻辑在 bookkeeping-merge.js)
// + 触发点 (进页/联网/回前台/每分钟/记完一笔) + 类别树拉取 (缓存先用, 联网刷新)。
// 拆自 bookkeeping.js (结构化重构: 代码逐字节未动, 经典脚本按 bookkeeping.html 里的顺序加载, 跨模块引用走全局)。
"use strict";
/* global $, entries: writable, dirty: writable, lastSync: writable,
          catTree: writable, persist, saveLS, pad, render, fillChips,
          mergeEntries, entriesToUpload */
/* exported renderSyncStrip, syncNow, scheduleSync, loadCategories */

// ---------- 同步 ----------
let syncing = false;

function renderSyncStrip() {
  const strip = $("#sync-strip");
  const text = $("#sync-text");
  strip.classList.remove("pending", "off");
  if (!navigator.onLine) {
    strip.classList.add("off");
    text.textContent = "离线 · 账存本机, 联网后自动同步";
  } else if (syncing) {
    text.textContent = "同步中…";
  } else if (dirty.size > 0) {
    strip.classList.add("pending");
    text.textContent = `${dirty.size} 条待同步`;
  } else {
    const t = lastSync ? new Date(lastSync) : null;
    text.textContent = t && !isNaN(t)
      ? `已同步 · ${pad(t.getHours())}:${pad(t.getMinutes())}` : "本地账本";
  }
}

async function syncNow() {
  if (syncing || !navigator.onLine) { renderSyncStrip(); return; }
  syncing = true;
  renderSyncStrip();
  try {
    const r = await fetch("/bookkeeping/api/sync", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        last_sync: lastSync || null,
        entries: entriesToUpload(entries, [...dirty]),
      }),
    });
    if (r.status === 401) { location.replace("/login"); return; }
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    // EntryOut (snake_case) → 本地条目形状 (camelCase)
    const remote = data.entries.map(e => ({
      id: e.id, date: e.date, time: e.time || "", amount: e.amount, kind: e.kind,
      category: e.category, tags: e.tags || [], note: e.note, deleted: e.deleted,
      updatedAt: e.updated_at,
      createdByName: e.created_by_name, updatedByName: e.updated_by_name,
    }));
    entries = mergeEntries(entries, remote);
    dirty = new Set();        // 服务器收下了, 脏名单清空 (失败不清, 下次重传)
    lastSync = data.server_now;
    saveLS("bk-last-sync", lastSync);
    persist();
    render();
  } catch (_e) {
    renderSyncStrip();        // 离线/失败: 脏名单还在, 下个触发点再试
  } finally {
    syncing = false;
    renderSyncStrip();
  }
}

let syncTimer = null;
function scheduleSync() {      // 记完一笔不急着打接口, 稍聚一下
  clearTimeout(syncTimer);
  syncTimer = setTimeout(syncNow, 1200);
}

// 触发点: 进页 / 恢复联网 / 回到前台 / 每分钟 / 记完一笔
addEventListener("online", syncNow);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) syncNow();
});
setInterval(syncNow, 60000);

// 顶栏刷新 = 立即同步 (全站刷新按钮最右的统一位)
$("#refresh-btn").addEventListener("click", async () => {
  $("#refresh-btn").classList.add("busy");
  await syncNow();
  $("#refresh-btn").classList.remove("busy");
});

async function loadCategories() {   // 类别树: 缓存先用, 联网刷新 (离线优先同账目)
  try {
    const r = await fetch("/bookkeeping/api/categories", { cache: "no-store" });
    if (r.status === 401) { location.replace("/login"); return; }
    if (!r.ok) return;
    const tree = await r.json();
    if (tree && Array.isArray(tree.expense) && Array.isArray(tree.income)) {
      catTree = tree;
      saveLS("bk-categories-v2", catTree);
      fillChips();                  // 弹层正开着也立刻换上
    }
  } catch (_e) { /* 离线/失败: 用缓存树 */ }
}
