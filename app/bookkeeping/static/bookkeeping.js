// bookkeeping.js — My Money (家庭记账): 离线优先 (localStorage 先落, 联网增量同步)。
// 同步纯逻辑在 bookkeeping-merge.js (先于此脚本加载, 全局可用)。
"use strict";
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g,
  c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

/* 类别图标: 大类名 → emoji。类别数据本身在服务器 (挖财导入的两级树),
   图标是纯展示映射, 跟着数据走不进库; 没映射到的大类兜底 📝。 */
const CATEGORY_ICONS = {
  "餐饮": "🍜", "交通": "🚗", "购物": "🛒", "居家": "🏠", "娱乐": "🎮",
  "医教": "🎓", "人情": "🎁", "投资": "📈", "旅游": "✈️", "生意": "💼",
  "房贷": "🏦", "团队管理": "👥", "还钱钱": "💸", "虾饺": "🥟",
  "工资薪水": "💰", "奖金": "🏆", "兼职外快": "🛠️", "红包": "🧧", "利息": "🪙",
  "基金": "📊", "股票": "💹", "余额宝": "🐷", "分红": "🎉", "营业收入": "🧾",
  "工程款": "🏗️", "福利补贴": "🎀", "礼金": "💐", "赔付款": "🛡️", "顺风车": "🚕",
  "医疗": "💊", "教育": "📚",       // 旧版平铺类别 (老账目还在用)
};
const WEEK = ["日", "一", "二", "三", "四", "五", "六"];

// ---------- 本地存储 ----------
function loadLS(key, fallback) {
  try { const v = JSON.parse(localStorage.getItem(key)); return v ?? fallback; }
  catch (_e) { return fallback; }
}
function saveLS(key, val) { localStorage.setItem(key, JSON.stringify(val)); }

let entries = loadLS("bk-entries", []);       // 全量账本 (含墓碑)
let dirty = new Set(loadLS("bk-dirty", []));  // 有本地改动待上行的 id
let lastSync = loadLS("bk-last-sync", "");    // 上次同步的服务器时间 (游标)
let month = loadLS("bk-month", "");
let person = loadLS("bk-person", "");
let catTree = loadLS("bk-categories", null);   // {expense: [[大类,[子类...]],...], income: [...]}

function persist() {
  saveLS("bk-entries", entries);
  saveLS("bk-dirty", [...dirty]);
}

// ---------- 工具 ----------
function pad(n) { return String(n).padStart(2, "0"); }
function todayStr() {
  const d = new Date();
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}
function curMonth() {
  const d = new Date();
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}`;
}
if (!month) month = curMonth();

// HTTP 非安全上下文没有 crypto.randomUUID (安全上下文限定 API),
// 手搓 v4 —— crypto.getRandomValues 没有这个限制
function uuid() {
  if (crypto.randomUUID) return crypto.randomUUID();
  const b = crypto.getRandomValues(new Uint8Array(16));
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = [...b].map(x => x.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

function catIcon(cat) {
  return CATEGORY_ICONS[String(cat || "").split("/")[0]] || "📝";
}
// 记账人: 服务器回声带名字; 本地刚记还没同步的暂时标"我"
function creatorName(e) { return e.createdByName || "我"; }
function fmtMoney(n) { return "¥" + Number(n).toFixed(2); }

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
    .sort((a, b) => a.updatedAt < b.updatedAt ? 1 : -1);
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
      items.map(e =>
        `<div class="entry" data-id="${esc(e.id)}">` +
        `<div class="cat-dot">${catIcon(e.category)}</div>` +
        `<div class="mid"><div class="l1">${esc(e.note || e.category || (e.kind === "income" ? "收入" : "支出"))}</div>` +
        `<div class="l2">${esc(e.category || "未分类")} · ${esc(creatorName(e))}</div></div>` +
        `<div class="amt${e.kind === "income" ? " in" : ""}">${e.kind === "income" ? "+" : "-"}${Number(e.amount).toFixed(2)}</div>` +
        `</div>`).join("") +
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
      id: e.id, date: e.date, amount: e.amount, kind: e.kind,
      category: e.category, note: e.note, deleted: e.deleted,
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

// ---------- 记/改一笔 (底部弹层) ----------
let editingId = null;
let sheetKind = "expense";
let sheetCat = "";

function treeFor(kind) {          // 当前收支方向的类别树 (离线用缓存)
  return (catTree && catTree[kind]) || [];
}

function fillChips() {
  const tops = treeFor(sheetKind);
  $("#cat-tiles").innerHTML = tops.map(([name]) => {
    const on = sheetCat === name || sheetCat.startsWith(name + "/");
    return `<button class="tile${on ? " on" : ""}" data-cat="${esc(name)}">` +
      `<span class="ti">${catIcon(name)}</span><span class="tn">${esc(name)}</span></button>`;
  }).join("");
  const top = sheetCat.split("/")[0];          // "" = 没选, 子类行藏起来
  const kids = (tops.find(t => t[0] === top) || [null, []])[1];
  $("#cat-sub").hidden = !kids.length;
  $("#cat-sub").innerHTML = kids.map(name =>
    `<button data-sub="${esc(name)}"${sheetCat === top + "/" + name ? ' class="on"' : ""}>${esc(name)}</button>`).join("");
}

async function loadCategories() {   // 类别树: 缓存先用, 联网刷新 (离线优先同账目)
  try {
    const r = await fetch("/bookkeeping/api/categories", { cache: "no-store" });
    if (r.status === 401) { location.replace("/login"); return; }
    if (!r.ok) return;
    const tree = await r.json();
    if (tree && Array.isArray(tree.expense) && Array.isArray(tree.income)) {
      catTree = tree;
      saveLS("bk-categories", catTree);
      fillChips();                  // 弹层正开着也立刻换上
    }
  } catch (_e) { /* 离线/失败: 用缓存树 */ }
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
  $("#f-note").value = entry ? entry.note : "";
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
  if (!treeFor(sheetKind).some(t => t[0] === top)) sheetCat = "";
  fillChips();
});

$("#cat-tiles").addEventListener("click", e => {
  const btn = e.target.closest("button[data-cat]");
  if (!btn) return;
  sheetCat = sheetCat === btn.dataset.cat ? "" : btn.dataset.cat;
  fillChips();
});
$("#cat-sub").addEventListener("click", e => {
  const btn = e.target.closest("button[data-sub]");
  if (!btn) return;
  const val = sheetCat.split("/")[0] + "/" + btn.dataset.sub;
  sheetCat = sheetCat === val ? val.split("/")[0] : val;   // 再点收回大类
  fillChips();
});

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
  } else if (btn.dataset.k === "again") {
    // 再记: 存完不关弹层, 清空金额备注接着记 (改一笔时按它 = 存修改再开新一笔)
    if (saveEntry()) {
      editingId = null;
      $("#f-amount").value = "";
      $("#f-note").value = "";
      sheetCat = "";
      $("#sheet-title").textContent = "记一笔";
      $("#sheet-del").hidden = true;
      fillChips();
      $("#amt-eq").textContent = "已记 ✓";   // 下一个数字会把预览顶掉
    }
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

// 键盘随弹层常驻 (完成/再记就长在键盘里, 收了就没法保存了):
// 备注/日期聚焦弹系统键盘时, 靠弹层自身滚动让位, 不收键盘

function shakeAmount() {               // 金额无效: 抖一下提示 (不清空, 键盘就在手边)
  const line = $("#amt-line");
  line.classList.remove("shake");
  void line.offsetWidth;
  line.classList.add("shake");
}

// 记一笔落库 (键盘上的 完成/再记 共用): 表达式求值 → 条目进本地账本 → 待同步
function saveEntry() {
  const value = evaluateAmount($("#f-amount").value);
  const amount = value == null ? NaN : Math.round(value * 100) / 100;
  if (!isFinite(amount) || amount <= 0) { shakeAmount(); return false; }
  const date = $("#f-date").value || todayStr();
  const note = $("#f-note").value.trim().slice(0, 200);
  const now = new Date().toISOString();
  const prev = entries.find(x => x.id === editingId);
  const entry = {
    id: editingId || uuid(),
    date, amount,
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

$("#logout").addEventListener("click", async () => {
  await fetch("/bookkeeping/api/logout", { method: "POST" });
  location.replace("/login");
});

/* ---------- 启动 ---------- */
render();
loadCategories();
syncNow();
