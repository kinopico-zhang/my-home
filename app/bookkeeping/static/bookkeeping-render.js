// bookkeeping-render — My Money 渲染: 月度栏 (月份切换/记账人筛选) + 汇总卡 + 按日分组的账目列表。
// 拆自 bookkeeping.js (结构化重构: 代码逐字节未动, 经典脚本按 bookkeeping.html 里的顺序加载, 跨模块引用走全局)。
"use strict";
/* global $, esc, WEEK, entries, month: writable, person: writable, saveLS, pad,
          catIcon, creatorName, fmtMoney, renderSyncStrip,
          monthTotals, visibleEntries */
/* exported render */

// ---------- 渲染 ----------
function renderMonth() {
  const [y, m] = month.split("-");
  $("#mon-label").textContent = `${y}年${+m}月`;
}

function renderSum() {
  const t = monthTotals(entries, month);
  $("#sum-out").textContent = fmtMoney(t.expense);
  $("#sum-in").textContent = fmtMoney(t.income);
}

function renderPersons() {
  const names = [...new Set(entries.filter(e => !e.deleted && e.createdByName)
    .map(e => e.createdByName))];
  if (!names.length) {          // 还没同步过: 没有服务端名字, 不显示筛选
    $("#person-row").innerHTML = "";
    return;
  }
  const mk = (label, val) =>
    `<button data-person="${esc(val)}"${person === val ? ' class="on"' : ""}>${esc(label)}</button>`;
  $("#person-row").innerHTML = mk("全部", "") + names.map(n => mk(n, n)).join("");
}

function renderList() {
  const list = visibleEntries(entries, month, person)
    .sort((a, b) => {          // 日期新→老, 同日内时刻新→老 (旧账无时刻沉底)
      if (a.date !== b.date) return a.date < b.date ? 1 : -1;
      if ((a.time || "") !== (b.time || ""))
        return (a.time || "") < (b.time || "") ? 1 : -1;
      return a.updatedAt < b.updatedAt ? 1 : -1;
    });
  $("#list-empty").hidden = list.length > 0;
  const groups = new Map();
  for (const e of list) {
    if (!groups.has(e.date)) groups.set(e.date, []);
    groups.get(e.date).push(e);
  }
  $("#entry-list").innerHTML = [...groups.entries()].map(([date, items]) => {
    const [y, m, d] = date.split("-");
    const wd = WEEK[new Date(+y, +m - 1, +d).getDay()];
    const dayOut = items.filter(e => e.kind === "expense").reduce((s, e) => s + e.amount, 0);
    return `<div class="day-group">` +
      `<div class="day-head"><span>${+m}月${+d}日 周${wd}</span>` +
      `<span>${dayOut > 0 ? "支出 " + fmtMoney(dayOut) : ""}</span></div>` +
      `<div class="entries">` +
      items.map(e => {
        const l2 = [e.category || "未分类"];
        if (e.time) l2.push(e.time);
        for (const t of e.tags || []) l2.push("#" + t);
        l2.push(creatorName(e));
        return `<div class="entry" data-id="${esc(e.id)}">` +
        `<div class="cat-dot">${catIcon(e.category)}</div>` +
        `<div class="mid"><div class="l1">${esc(e.note || e.category || (e.kind === "income" ? "收入" : "支出"))}</div>` +
        `<div class="l2">${esc(l2.join(" · "))}</div></div>` +
        `<div class="amt${e.kind === "income" ? " in" : ""}">${e.kind === "income" ? "+" : "-"}${Number(e.amount).toFixed(2)}</div>` +
        `</div>`; }).join("") +
      `</div></div>`;
  }).join("");
}

function render() {
  renderMonth();
  renderSum();
  renderPersons();
  renderList();
  renderSyncStrip();
}

// ---------- 月份切换 ----------
function shiftMonth(delta) {
  const [y, m] = month.split("-").map(Number);
  const d = new Date(y, m - 1 + delta, 1);
  month = `${d.getFullYear()}-${pad(d.getMonth() + 1)}`;
  saveLS("bk-month", month);
  render();
}
$("#mon-prev").addEventListener("click", () => shiftMonth(-1));
$("#mon-next").addEventListener("click", () => shiftMonth(1));

$("#person-row").addEventListener("click", e => {
  const btn = e.target.closest("button[data-person]");
  if (!btn) return;
  person = btn.dataset.person;
  saveLS("bk-person", person);
  render();
});
