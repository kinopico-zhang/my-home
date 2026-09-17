// bookkeeping-amount-pad — My Money 金额键盘: 表达式实时预览 + ⌫ 长按清空
// + 完成 (saveEntry 求值落本地账本, 待同步)。纯计算在 amount-calculator.js。
// 拆自 bookkeeping.js (结构化重构: 代码逐字节未动, 经典脚本按 bookkeeping.html 里的顺序加载, 跨模块引用走全局)。
"use strict";
/* global $, entries, dirty, persist, render, scheduleSync, todayStr, parseTags,
          uuid, sheetKind, sheetCat, editingId, closeSheet,
          evaluateAmount, applyAmountKey */
/* exported refreshAmountPreview, saveEntry */

function refreshAmountPreview() {      // 表达式 (含运算符) 的实时结果, 裸数字不打扰
  const expr = $("#f-amount").value;
  const hasOp = /[+\-*/]/.test(expr);
  const value = hasOp ? evaluateAmount(expr) : null;
  $("#amt-eq").textContent = value == null ? "" : "= " + Math.round(value * 100) / 100;
}

$("#amt-pad").addEventListener("click", e => {
  const btn = e.target.closest("button[data-k]");
  if (!btn || btn.dataset.k === "back") return;   // ⌫ 在 pointerdown 处理 (要区分长按)
  if (btn.dataset.k === "done") {
    if (saveEntry()) closeSheet();
  } else {
    const input = $("#f-amount");
    input.value = applyAmountKey(input.value, btn.dataset.k);
    refreshAmountPreview();
  }
});

// ⌫: 按下即回删; 按住半秒整串清空 (iOS 键盘习惯), 抬手/移开就停
(function wireBackspace() {
  const btn = $("#amt-pad button[data-k=back]");
  let holdTimer = null;
  btn.addEventListener("pointerdown", () => {
    const input = $("#f-amount");
    input.value = applyAmountKey(input.value, "back");
    refreshAmountPreview();
    holdTimer = setTimeout(() => {
      input.value = applyAmountKey(input.value, "clear");
      refreshAmountPreview();
    }, 550);
  });
  for (const ev of ["pointerup", "pointercancel", "pointerleave"])
    btn.addEventListener(ev, () => clearTimeout(holdTimer));
})();

$("#f-amount").addEventListener("input", () => {   // 粘贴/残存输入法兜底: 只留键盘字符
  const input = $("#f-amount");
  const clean = input.value.replace(/[^0-9+\-*/.]/g, "");
  if (clean !== input.value) input.value = clean;
  refreshAmountPreview();
});

// 键盘随弹层常驻 (完成就长在键盘里, 收了就没法保存了):
// 备注/日期聚焦弹系统键盘时, 靠弹层自身滚动让位, 不收键盘

function shakeAmount() {               // 金额无效: 抖一下提示 (不清空, 键盘就在手边)
  const line = $("#amt-line");
  line.classList.remove("shake");
  void line.offsetWidth;
  line.classList.add("shake");
}

// 记一笔落库 (键盘上的 完成): 表达式求值 → 条目进本地账本 → 待同步
function saveEntry() {
  const value = evaluateAmount($("#f-amount").value);
  const amount = value == null ? NaN : Math.round(value * 100) / 100;
  if (!isFinite(amount) || amount <= 0) { shakeAmount(); return false; }
  const date = $("#f-date").value || todayStr();
  const time = /^\d{2}:\d{2}$/.test($("#f-time").value) ? $("#f-time").value : "";
  const note = $("#f-note").value.trim().slice(0, 200);
  const tags = parseTags($("#f-tags").value);
  const now = new Date().toISOString();
  const prev = entries.find(x => x.id === editingId);
  const entry = {
    id: editingId || uuid(),
    date, time, amount, tags,
    kind: sheetKind, category: sheetCat, note,
    deleted: false, updatedAt: now,
    createdByName: prev ? prev.createdByName : "",
    updatedByName: prev ? prev.updatedByName : "",
  };
  if (prev) entries[entries.indexOf(prev)] = entry;
  else entries.push(entry);
  dirty.add(entry.id);
  persist();
  render();
  scheduleSync();
  return true;
}
