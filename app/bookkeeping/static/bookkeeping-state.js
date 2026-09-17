// bookkeeping-state — My Money 页面公共层: DOM 助手/日期工具 + 离线账本状态
// (localStorage 先落, 联网增量同步; 同步纯逻辑在 bookkeeping-merge.js)。
// 拆自 bookkeeping.js (结构化重构: 代码逐字节未动, 经典脚本按 bookkeeping.html 里的顺序加载, 跨模块引用走全局)。
"use strict";
/* exported $, esc, WEEK, entries, dirty, lastSync, month, person, catTree,
            persist, saveLS, pad, todayStr, nowTime, parseTags, uuid, catIcon,
            creatorName, fmtMoney */

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
let catTree = loadLS("bk-categories-v2", null);  // {expense: [{name,children}...], income: [...]}

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
function nowTime() {
  const d = new Date();
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
// 标签输入 → 干净数组: 空格/逗号/顿号分隔, 去井号, 去重, 最多 5 个
function parseTags(raw) {
  const out = [];
  for (let t of String(raw || "").split(/[\s,，、]+/)) {
    t = t.replace(/^#/, "").slice(0, 12);
    if (t && !out.includes(t)) out.push(t);
    if (out.length >= 5) break;
  }
  return out;
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
