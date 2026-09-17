// bookkeeping-entry-sheet — My Money 记/改一笔 (底部弹层): 开合 + 把手下拉关闭
// + 类别格子 + 标签胶囊 + 收支切换 + 删除/点行改账。
// 拆自 bookkeeping.js (结构化重构: 代码逐字节未动, 经典脚本按 bookkeeping.html 里的顺序加载, 跨模块引用走全局)。
"use strict";
/* global $, esc, entries, dirty, persist, render, scheduleSync,
          parseTags, todayStr, nowTime, catIcon, catTree,
          refreshAmountPreview */
/* exported closeSheet, fillChips */

// ---------- 记/改一笔 (底部弹层) ----------
let editingId = null;
let sheetKind = "expense";
let sheetCat = "";

function treeFor(kind) {          // 当前收支方向的类别树 (离线用缓存)
  return (catTree && catTree[kind]) || [];
}

// 用过的标签 → 一排可点胶囊 (点一下加/去掉, 不想打的标签不用手输)
function renderTagChips() {
  const used = [...new Set(entries.filter(e => !e.deleted)
    .flatMap(e => e.tags || []))];
  const row = $("#tag-chips");
  row.hidden = !used.length;
  const cur = parseTags($("#f-tags").value);
  row.innerHTML = used.map(t =>
    `<button data-tag="${esc(t)}"${cur.includes(t) ? ' class="on"' : ""}>${esc(t)}</button>`).join("");
}

function fillChips() {
  const tiles = [];                 // [组合名, 显示名, 大类(取图标)]
  for (const {name: top, children: kids} of treeFor(sheetKind)) {
    if (kids.length) for (const kid of kids) tiles.push([top + "/" + kid, kid, top]);
    else tiles.push([top, top, top]);   // 没子类的大类自己就是可选类别
  }
  $("#cat-tiles").innerHTML = tiles.map(([val, name, top]) =>
    `<button class="tile${sheetCat === val ? " on" : ""}" data-cat="${esc(val)}">` +
      `<span class="ti">${catIcon(top)}</span><span class="tn">${esc(name)}</span></button>`).join("");
}

function openSheet(entry) {
  editingId = entry ? entry.id : null;
  sheetKind = entry ? entry.kind : "expense";
  sheetCat = entry ? entry.category : "";
  $("#sheet-title").textContent = entry ? "改一笔" : "记一笔";
  $("#kind-seg").querySelectorAll("button").forEach(b =>
    b.classList.toggle("on", b.dataset.kind === sheetKind));
  $("#f-amount").value = entry ? entry.amount : "";
  $("#f-date").value = entry ? entry.date : todayStr();
  $("#f-time").value = entry ? (entry.time || "") : nowTime();
  $("#f-note").value = entry ? entry.note : "";
  $("#f-tags").value = entry ? (entry.tags || []).join(" ") : "";
  renderTagChips();
  $("#sheet-del").hidden = !entry;
  fillChips();
  const mask = $("#sheet-mask"), sheet = $("#sheet");
  mask.hidden = false; sheet.hidden = false;
  requestAnimationFrame(() => { mask.classList.add("on"); sheet.classList.add("on"); });
  document.body.style.overflow = "hidden";
  $("#amt-pad").classList.add("on");      // 金额是第一件事, 键盘直接展开
  refreshAmountPreview();
  setTimeout(() => $("#f-amount").focus(), 260);
}

function closeSheet() {
  const mask = $("#sheet-mask"), sheet = $("#sheet");
  mask.classList.remove("on"); sheet.classList.remove("on");
  setTimeout(() => { mask.hidden = true; sheet.hidden = true; }, 250);
  document.body.style.overflow = "";
  $("#amt-pad").classList.remove("on");
  editingId = null;
}

/* 下滑关闭 (与充电详情/轨迹弹层同一手法)。不用 setPointerCapture:
   iOS Safari 对 touch 指针 capture 会当场 pointercancel (手指一动事件
   就被系统收走), move/up 挂 window 级 —— 不捕获手指出界照样收。 */
(() => {
  const sheet = $("#sheet"), zone = $("#grab-zone");
  let y0 = null, dy = 0;
  const move = e => {
    dy = Math.max(0, e.clientY - y0);      // 只往下拖有效, 往上顶不抬层
    sheet.style.transition = "none";       // 拖动跟手, 不吃 .25s 缓动
    sheet.style.transform = `translateY(${dy}px)`;
  };
  const release = () => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", release);
    window.removeEventListener("pointercancel", release);
    if (y0 == null) return;
    sheet.style.transition = ""; sheet.style.transform = "";
    if (dy > 90) closeSheet();             // 拉过 90px = 明确想关; 否则弹回
    y0 = null;
  };
  zone.addEventListener("pointerdown", e => {
    y0 = e.clientY; dy = 0;
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", release);
    window.addEventListener("pointercancel", release);
  });
  zone.addEventListener("click", () => {   // 点一下把手也关 (拖过 8px 不算点)
    if (dy > 8) { dy = 0; return; }
    closeSheet();
  });
})();

$("#fab").addEventListener("click", () => openSheet(null));
$("#sheet-mask").addEventListener("click", closeSheet);
$("#sheet-close").addEventListener("click", closeSheet);

$("#kind-seg").addEventListener("click", e => {
  const btn = e.target.closest("button[data-kind]");
  if (!btn || btn.dataset.kind === sheetKind) return;
  sheetKind = btn.dataset.kind;
  $("#kind-seg").querySelectorAll("button").forEach(b =>
    b.classList.toggle("on", b === btn));
  const top = sheetCat.split("/")[0];      // 支出↔收入树不同, 原大类不在就清空重选
  if (!treeFor(sheetKind).some(t => t.name === top)) sheetCat = "";
  fillChips();
});

$("#cat-tiles").addEventListener("click", e => {
  const btn = e.target.closest("button[data-cat]");
  if (!btn) return;
  sheetCat = sheetCat === btn.dataset.cat ? "" : btn.dataset.cat;
  fillChips();
});
$("#tag-chips").addEventListener("click", e => {
  const btn = e.target.closest("button[data-tag]");
  if (!btn) return;
  const tag = btn.dataset.tag;
  const cur = parseTags($("#f-tags").value);
  $("#f-tags").value = (cur.includes(tag) ? cur.filter(t => t !== tag)
    : [...cur, tag]).join(" ");
  renderTagChips();
});
$("#f-tags").addEventListener("input", renderTagChips);

$("#sheet-del").addEventListener("click", () => {
  const prev = entries.find(x => x.id === editingId);
  if (prev) {          // 墓碑: 本地也留着, 才能把删除同步给别人
    prev.deleted = true;
    prev.updatedAt = new Date().toISOString();
    dirty.add(prev.id);
    persist();
  }
  closeSheet();
  render();
  scheduleSync();
});

$("#entry-list").addEventListener("click", e => {
  const t = e.target;
  if (!(t instanceof Element) || !t.isConnected) return;   // 重渲染脱链防误触
  const row = t.closest(".entry");
  if (!row) return;
  const entry = entries.find(x => x.id === row.dataset.id);
  if (entry) openSheet(entry);
});
