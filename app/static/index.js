// index.js — 由 index.html 内联脚本抽出 (位置/顺序/语义不变), 供 lint 与测试
"use strict";
/* 页签菜单: 点空白处收起。
   注意: 日历点选会在点击处理器里 innerHTML 重渲染, 事件目标被脱链
   (closest() 找不到菜单祖先) —— 脱链的点击一定发生在某个菜单里, 不能当"点外面"关闭。 */
document.addEventListener("click", e => {
  const t = e.target;
  if (!(t instanceof Element) || !t.isConnected) return;
  const inside = t.closest("details.nav-menu");
  document.querySelectorAll("details.nav-menu[open]").forEach(m => {
    if (m !== inside) m.removeAttribute("open");
  });
});
/* ============================ 工具 ============================ */
const $ = (s, el) => (el || document).querySelector(s);
const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g,
  c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const pad = n => String(n).padStart(2, "0");

/* "2026-09-07 23:50" → 本地 Date (服务端已转北京时间; 手动解析, 兼容 iOS Safari) */
function parseLocal(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/.exec(s || "");
  return m ? new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]) : new Date(s);
}
const WEEK = ["日", "一", "二", "三", "四", "五", "六"];
function fmtCardDate(s) {
  const d = parseLocal(s);
  return `${d.getMonth() + 1}月${d.getDate()}日 周${WEEK[d.getDay()]} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function fmtDur(min) {
  if (min == null) return "—";
  const h = Math.floor(min / 60), m = min % 60;
  return h ? `${h}时${m ? m + "分" : ""}` : `${m}分钟`;   // 紧凑格式, 窄屏不折行
}
function fmtMinAxis(v) {
  if (v >= 60) { const h = Math.floor(v / 60), m = Math.round(v % 60); return m ? `${h}h${m}m` : `${h}h`; }
  return `${Math.round(v)}m`;
}
const num = (v, d = 1) => v == null ? "—" : Number(v).toFixed(d).replace(/\.0+$/, "");
const money = v => v == null ? "—" : "¥" + Number(v).toFixed(2).replace(/\.?0+$/, "");
const moneyInt = v => v == null ? "—" : "¥" + Math.round(v).toLocaleString("zh-CN");
const thousands = v => Math.round(v).toLocaleString("zh-CN");

async function getJSON(url) {
  const r = await fetch(url, { cache: "no-store" });
  if (r.status === 401) { location.replace("/tesla/login"); throw new Error("未登录"); }
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

/* ============================ 状态 ============================ */
const PAGE = 24;
/* ---------- 顶栏时间筛选: 快捷档位下拉, 编码进 ?range= (分享/刷新保留) ---------- */
const TIME_RANGES = [
  { v: "24h", days: 1, lb: "24小时" },
  { v: "7d", days: 7, lb: "近一周" },
  { v: "30d", days: 30, lb: "近一月" },
  { v: "180d", days: 180, lb: "近半年" },
  { v: "1y", days: 365, lb: "近一年" },
  { v: "all", days: 0, lb: "全部" },
];
function timeFrom(v) {   // 档位 → from 本地日期 (含今天共 N 天; 24h 即"昨天起")
  const r = TIME_RANGES.find(x => x.v === v);
  if (!r || !r.days) return null;
  const d = new Date(); d.setDate(d.getDate() - (r.days - 1));
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}
// URL → 初始筛选: ?range= 快捷档; ?from=&to= 自定义区间; ?type= / ?city= 筛选行
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const qs0 = new URLSearchParams(location.search);
let range0 = TIME_RANGES.some(r => r.v === qs0.get("range")) ? qs0.get("range") : "all";
let cFrom0 = null, cTo0 = null;
if (range0 === "all") {
  const f = qs0.get("from"), t = qs0.get("to");
  if (DATE_RE.test(f || "") && DATE_RE.test(t || "") && f <= t) { range0 = "custom"; cFrom0 = f; cTo0 = t; }
}
const state = {
  type: ["fast", "slow"].includes(qs0.get("type")) ? qs0.get("type") : "all",
  city: qs0.get("city") || "",
  range: range0, cFrom: cFrom0, cTo: cTo0,
  offset: 0, total: 0, loading: false, done: false, err: null,
};
const detailCache = new Map();
const hasEcharts = typeof echarts !== "undefined";

function rangeParams() {
  if (state.range === "custom") {   // 自定义起止 (日历)
    const p = {};
    if (state.cFrom) p.from = state.cFrom;
    if (state.cTo) p.to = state.cTo;
    return p;
  }
  const from = timeFrom(state.range);
  return from ? { from } : {};
}
function sessionParams(extra) {
  const p = new URLSearchParams({ type: state.type, ...rangeParams(), ...(extra || {}) });
  if (state.city) p.set("city", state.city);
  return p.toString();
}
function syncURL() {   // 筛选写进地址栏 (默认值不写, 链接保持干净)
  const u = new URL(location.href);
  if (state.range === "custom") {
    u.searchParams.delete("range");
    u.searchParams.set("from", state.cFrom); u.searchParams.set("to", state.cTo);
  } else {
    u.searchParams.delete("from"); u.searchParams.delete("to");
    if (state.range === "all") u.searchParams.delete("range");
    else u.searchParams.set("range", state.range);
  }
  if (state.type === "all") u.searchParams.delete("type"); else u.searchParams.set("type", state.type);
  if (state.city) u.searchParams.set("city", state.city); else u.searchParams.delete("city");
  history.replaceState(null, "", u);
}

/* ============================ 统计卡片 ============================ */
async function loadSummary() {
  const s = await getJSON("/tesla/charging/api/summary?" + sessionParams());
  const months = s.first_date && s.last_date ?
    (parseLocal(s.last_date + " 00:00").getFullYear() * 12 + parseLocal(s.last_date + " 00:00").getMonth()) -
    (parseLocal(s.first_date + " 00:00").getFullYear() * 12 + parseLocal(s.first_date + " 00:00").getMonth()) + 1 : 1;
  const fastPct = s.sessions ? Math.round(s.fast_sessions / s.sessions * 100) : 0;
  const cards = [
    { lb: "充电次数", val: thousands(s.sessions), sub: months > 1 ? `月均 ${Math.round(s.sessions / months)} 次` : "" },
    { lb: "总充电量", val: thousands(s.energy_used || s.energy_added), unit: "kWh", sub: `表计口径` },
    { lb: "总费用", val: moneyInt(s.cost), sub: s.first_date ? `${s.first_date.replace(/-/g, "/")} 起` : "" },
    { lb: "平均电价", val: s.price_per_kwh == null ? "—" : "¥" + s.price_per_kwh.toFixed(3), unit: "/kWh", sub: "按表计电量" },
    { lb: "快充占比", val: fastPct + "%", sub: `快充 ${s.fast_sessions} 次` },
    { lb: "充电时长", val: num(s.duration_min / 60, 1), unit: "小时", sub: s.range_gain ? `≈ ${thousands(s.range_gain)} km 续航` : "" },
  ];
  $("#stats-row").innerHTML = cards.map(c => `
    <div class="stat">
      <div class="lb">${esc(c.lb)}</div>
      <div class="val">${c.val}${c.unit ? `<small>${c.unit}</small>` : ""}</div>
      ${c.sub ? `<div class="sub">${esc(c.sub)}</div>` : ""}
    </div>`).join("");
}

/* ============================ 图表 ============================ */
const chartText = { axis: "#898781", ink: "#c3c2b7" };
const tooltipStyle = {
  backgroundColor: "rgba(28,28,30,.95)", borderWidth: 0, padding: [7, 10],
  textStyle: { color: "#f5f5f7", fontSize: 12 },
};
const monthlyKwEl = $("#chart-monthly-kwh"), monthlyCostEl = $("#chart-monthly-cost"), locEl = $("#chart-loc");
let chMonthlyKw, chMonthlyCost, chLoc;
let monthlyData = [], locData = [];

function shortMonth(ym) { return ym.slice(2).replace("-", "/"); }
function truncateName(s, n) { return s.length > n ? s.slice(0, n) + "…" : s; }

function renderMonthly() {
  if (!hasEcharts || !monthlyData.length) return;
  const months = monthlyData.map(d => d.month);
  const kw = monthlyData.map(d => Math.round((d.energy_used || 0) * 10) / 10);
  const cost = monthlyData.map(d => d.cost == null ? 0 : d.cost);
  const total = monthlyData.reduce((a, d) => a + (d.cost || 0), 0);
  $("#monthly-sub").textContent = `共 ${months.length} 个月 · 合计 ${moneyInt(total)}`;

  if (!chMonthlyKw) {
    chMonthlyKw = echarts.init(monthlyKwEl);
    chMonthlyCost = echarts.init(monthlyCostEl);
    echarts.connect([chMonthlyKw, chMonthlyCost]);
  }
  const xBase = {
    type: "category", data: months,
    axisTick: { show: false },
    axisLine: { lineStyle: { color: "#383835" } },
  };
  chMonthlyKw.setOption({
    animationDuration: 250,
    grid: { left: 6, right: 8, top: 10, bottom: 2, containLabel: true },
    tooltip: { ...tooltipStyle, trigger: "axis", axisPointer: { type: "shadow" } },
    xAxis: { ...xBase, axisLabel: { show: false } },
    yAxis: { type: "value", splitLine: { lineStyle: { color: "#2c2c2a" } },
             axisLabel: { color: chartText.axis, fontSize: 10 } },
    series: [{ type: "bar", name: "充电量", data: kw, barMaxWidth: 16,
               itemStyle: { color: "#3987e5", borderRadius: [4, 4, 0, 0] } }],
  });
  chMonthlyCost.setOption({
    animationDuration: 250,
    grid: { left: 6, right: 8, top: 8, bottom: 0, containLabel: true },
    tooltip: { ...tooltipStyle, trigger: "axis",
               axisPointer: { type: "line", lineStyle: { color: "#898781" } } },
    xAxis: { ...xBase, axisLabel: { color: chartText.axis, fontSize: 10,
              interval: months.length > 14 ? 1 : 0, formatter: shortMonth } },
    yAxis: { type: "value", splitLine: { lineStyle: { color: "#2c2c2a" } },
             axisLabel: { color: chartText.axis, fontSize: 10,
                          formatter: v => v >= 1000 ? (v / 1000) + "k" : v } },
    series: [{ type: "line", name: "费用", data: cost, showSymbol: false,
               lineStyle: { color: "#c98500", width: 2 },
               itemStyle: { color: "#c98500" } }],
  });
  // 表格视图 (图表的 WCAG 等价物)
  $("#table-monthly").innerHTML = `<table>
    <thead><tr><th>月份</th><th>kWh</th><th>费用</th><th>次数</th></tr></thead>
    <tbody>${monthlyData.map(d => `<tr>
      <td>${esc(d.month)}</td><td>${num(d.energy_used)}</td>
      <td>${money(d.cost)}</td><td>${d.sessions}</td></tr>`).join("")}</tbody></table>`;
}

function renderLocations() {
  if (!hasEcharts || !locData.length) return;
  const top = locData.slice(0, 7);
  const rest = locData.slice(7);
  const rows = rest.length
    ? [...top, { location: "其他", sessions: rest.reduce((a, d) => a + d.sessions, 0),
                 energy_used: rest.reduce((a, d) => a + (d.energy_used || 0), 0),
                 cost: rest.reduce((a, d) => a + (d.cost || 0), 0),
                 fast_sessions: rest.reduce((a, d) => a + d.fast_sessions, 0) }] : top;
  if (!chLoc) chLoc = echarts.init(locEl);
  chLoc.setOption({
    animationDuration: 250,
    grid: { left: 6, right: 44, top: 6, bottom: 0, containLabel: true },
    tooltip: { ...tooltipStyle, trigger: "axis", axisPointer: { type: "shadow" },
      formatter: (ps) => {
        const d = locData.find(x => x.location === ps[0].name) ||
                  rows.find(x => x.location === ps[0].name);
        return `<b>${esc(ps[0].name)}</b><br/>次数 ${d.sessions} · 快充 ${d.fast_sessions}` +
               `<br/>电量 ${num(d.energy_used)} kWh<br/>费用 ${money(d.cost)}`;
      } },
    xAxis: { type: "value", splitLine: { lineStyle: { color: "#2c2c2a" } },
             axisLabel: { color: chartText.axis, fontSize: 10 } },
    yAxis: { type: "category", inverse: true,
             data: rows.map(d => truncateName(d.location, 7)),
             axisTick: { show: false }, axisLine: { lineStyle: { color: "#383835" } },
             axisLabel: { color: chartText.ink, fontSize: 10.5, width: 76,
                          overflow: "truncate" } },
    series: [{ type: "bar", data: rows.map(d => d.sessions), barMaxWidth: 14,
               itemStyle: { color: "#3987e5", borderRadius: [0, 4, 4, 0] },
               label: { show: true, position: "right", color: chartText.ink,
                        fontSize: 10.5, formatter: "{c} 次" } }],
  });
  $("#table-loc").innerHTML = `<table>
    <thead><tr><th>地点</th><th>次数</th><th>kWh</th><th>费用</th></tr></thead>
    <tbody>${locData.map(d => `<tr>
      <td>${esc(truncateName(d.location, 10))}</td><td>${d.sessions}</td>
      <td>${num(d.energy_used)}</td><td>${money(d.cost)}</td></tr>`).join("")}</tbody></table>`;
}

async function loadCharts() {
  const [monthly, locations] = await Promise.all([
    getJSON("/tesla/charging/api/monthly?" + sessionParams()),
    getJSON("/tesla/charging/api/locations?" + sessionParams()),
  ]);
  monthlyData = monthly; locData = locations;
  renderMonthly(); renderLocations();
}

/* 图表/表格切换 */
function bindViewToggle(segId, chartEls, tableEl) {
  $(segId).addEventListener("click", e => {
    const b = e.target.closest("button"); if (!b) return;
    $(segId + " .on").classList.remove("on"); b.classList.add("on");
    const table = b.dataset.v === "table";
    chartEls.forEach(el => el.hidden = table);
    tableEl.hidden = !table;
    if (!table) chartEls.forEach(el => { const c = echarts.getInstanceByDom(el); c && c.resize(); });
  });
}
bindViewToggle("#monthly-view", [monthlyKwEl, monthlyCostEl], $("#table-monthly"));
bindViewToggle("#loc-view", [locEl], $("#table-loc"));

/* ============================ 瀑布流 ============================ */
const masonryEl = $("#masonry");
const itemsById = new Map();

function clearCards() { masonryEl.innerHTML = ""; itemsById.clear(); }

function renderCard(it) {
  const el = document.createElement("article");
  el.className = "card-s"; el.dataset.id = it.id;
  const costLine = it.cost != null
    ? `<button class="cs-cost" data-cost>${money(it.cost)}${it.price_per_kwh != null
        ? `<span class="pp">¥${it.price_per_kwh.toFixed(2)}/kWh</span>` : ""}<span class="edit-ic">✎</span></button>`
    : `<button class="cs-cost none" data-cost>＋ 添加费用</button>`;
  /* 短充电 (起止差 < 15%) 两个标签钉在真实百分比会叠字: 并成一个 "起 → 终"
     标签居中钉在轨迹中点 (中点钳 15~85%, 标签再宽也不出卡) */
  const wide = it.end_soc - it.start_soc >= 15;
  const mid = Math.min(Math.max((it.start_soc + it.end_soc) / 2, 15), 85);
  const socLabels = wide
    ? `<span class="sa-lb" style="left:${Math.min(it.start_soc, 93)}%">${it.start_soc}%</span>` +
      `<span class="sa-lb" style="right:${100 - it.end_soc}%">${it.end_soc}%</span>`
    : `<span class="sa-lb" style="left:${mid}%;transform:translateX(-50%)">` +
      `${it.start_soc} → ${it.end_soc}%</span>`;
  el.innerHTML = `
    <div class="cs-top">
      <span class="cs-date">${esc(fmtCardDate(it.start))}</span>
      <span class="tag ${it.is_fast ? "tag-fast" : "tag-slow"}">${it.is_fast ? "⚡ 快充" : "🔌 慢充"}</span>
    </div>
    <h3 class="cs-loc">${esc(it.location)}</h3>
    <div class="soc-axis">
      ${socLabels}
      <span class="trk"><i style="left:${it.start_soc}%;width:${Math.max(it.end_soc - it.start_soc, 2)}%"></i></span>
    </div>
    <div class="cs-main">
      <div class="cs-energy">${num(it.energy_added ?? it.energy_used)}<small>kWh</small></div>
      ${costLine}
    </div>
    <div class="cs-sub">${fmtDur(it.duration_min)} · 峰值 ${it.power_max ?? "—"} kW${it.outside_temp != null ? ` · ${num(it.outside_temp, 0)}°C` : ""}</div>`;
  return el;
}

const tailEl = $("#tail");
function setTail() {
  tailEl.hidden = state.total === 0 && !state.loading && state.done;
  $("#loader-spin").hidden = !state.loading;
  $("#endnote").hidden = !(state.done && state.total > 0);
  $("#empty").hidden = !(state.done && state.total === 0 && !state.err);
  $("#errbox").hidden = !state.err;
  $("#count-badge").textContent = state.total ? `共 ${state.total} 次` : "";
}

const PRELOAD_PX = 800;   // 触底前多远开始预加载 (IO rootMargin 与链式续载共用)

async function loadMore(reset) {
  if (state.loading || (state.done && !reset)) return;
  state.loading = true; state.err = null; setTail();
  try {
    const d = await getJSON("/tesla/charging/api/sessions?" + sessionParams({ offset: state.offset, limit: PAGE }));
    if (reset) clearCards();
    state.total = d.total; state.offset += d.items.length;
    if (state.offset >= d.total) state.done = true;
    d.items.forEach(it => {
      itemsById.set(it.id, it);
      masonryEl.appendChild(renderCard(it));
    });
  } catch (e) {
    state.err = "数据加载失败: " + e.message;
  }
  state.loading = false; setTail();
  /* 首页填不满"视口+预载区"时, tail 一直留在交叉区里, IntersectionObserver
     只在进出过渡时回调, 不会再触发 —— 主动续载直到 tail 滚出预载区。
     (Chrome 桌面端宽屏下 24 张卡不足一屏, 曾因此永远卡在第一页。) */
  if (!state.done && !state.err &&
      tailEl.getBoundingClientRect().top < window.innerHeight + PRELOAD_PX)
    loadMore(false);
}

/* 懒加载: 触底前 PRELOAD_PX 预加载下一页 */
new IntersectionObserver(es => {
  if (es[0].isIntersecting) loadMore(false);
}, { rootMargin: PRELOAD_PX + "px" }).observe(tailEl);

/* 窗口尺寸变化: 图表重绘 (列表已单列, 无需重排) */
let resizeTimer;
new ResizeObserver(() => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    [chMonthlyKw, chMonthlyCost, chLoc].forEach(c => c && c.resize());
  }, 120);
}).observe(document.body);

/* ============================ 筛选 ============================ */
async function refetch() {
  state.offset = 0; state.total = 0; state.done = false; state.err = null;
  masonryEl.classList.add("dim");
  await Promise.allSettled([loadSummary().catch(showErr), loadCharts().catch(showErr)]);
  await loadMore(true);
  masonryEl.classList.remove("dim");
}
function showErr(e) { $("#errmsg").textContent = "数据加载失败: " + e.message; $("#errbox").hidden = false; }

const TYPE_LABELS = { all: "类型: 全部", fast: "类型: 快充", slow: "类型: 慢充" };
$("#type-opts").addEventListener("click", e => {   // 快充/慢充下拉 (与城市筛选同款, 替代占地方的分段钮)
  const b = e.target.closest("button"); if (!b || b.classList.contains("on")) return;
  $("#type-menu").removeAttribute("open");
  state.type = b.dataset.v;
  $("#type-opts .on").classList.remove("on"); b.classList.add("on");
  $("#type-lb").textContent = TYPE_LABELS[state.type];
  syncURL(); refetch();
});
function timeLabel() {
  if (state.range === "custom")   // 自定义显示紧凑区间, 如 01/01–03/31
    return `${state.cFrom.slice(5).replace("-", "/")}–${state.cTo.slice(5).replace("-", "/")}`;
  return TIME_RANGES.find(r => r.v === state.range).lb;
}
function setTimeRange(v, skipFetch) {
  state.range = v;
  $("#time-lb").textContent = timeLabel();
  document.querySelectorAll("#time-opts button[data-v]").forEach(b =>
    b.classList.toggle("on", b.dataset.v === v));
  if (v !== "custom") $("#tm-dates").hidden = true;   // 回到快捷档, 收起日历
  syncURL();
  if (!skipFetch) refetch();
}
/* ---------- 自定义日历: 同一个日历连点两次 —— 第一下起点, 第二下终点 ----------
   终点早于起点自动交换; 已有区间再点 = 重新开始选; 只点一下就确定 = 单日。 */
let calYm = "", calA = null, calB = null;    // 显示月 / 草稿起止 (ISO 日期)
const calCn = iso => { const p = iso.split("-"); return `${+p[1]}月${+p[2]}日`; };
function calRender() {
  const [y, m] = calYm.split("-").map(Number);
  $("#tm-ym").textContent = `${y}年${m}月`;
  const lead = (new Date(y, m - 1, 1).getDay() + 6) % 7;   // 周一开头
  const days = new Date(y, m, 0).getDate();
  const n = new Date();
  const today = `${n.getFullYear()}-${pad(n.getMonth() + 1)}-${pad(n.getDate())}`;
  $("#tm-next").disabled = calYm >= today.slice(0, 7);     // 未来月没有数据
  let h = "";
  for (let i = 0; i < lead; i++) h += "<i></i>";
  for (let d = 1; d <= days; d++) {
    const iso = `${calYm}-${pad(d)}`;
    const cls = iso === calA || iso === calB ? "on"
      : calA && calB && iso > calA && iso < calB ? "mid" : "";
    h += `<button class="${cls}${iso === today ? " today" : ""}"
            data-d="${iso}" aria-label="${iso}">${d}</button>`;
  }
  $("#tm-cal").innerHTML = h;   // 重渲染会脱链点击目标, "点空白处收起" 的守卫兜底
  $("#tm-sel").textContent = !calA ? "点选开始日期"
    : !calB ? `已选开始 ${calCn(calA)}, 再点结束日期`
    : `${calCn(calA)} – ${calCn(calB)}`;
}
function calShift(k) {
  const [y, m] = calYm.split("-").map(Number);
  const t = new Date(y, m - 1 + k, 1);
  calYm = `${t.getFullYear()}-${pad(t.getMonth() + 1)}`;
  calRender();
}
function calOpen() {   // 打开日历: 带出已应用的自定义区间, 没有则从当月起
  calA = state.cFrom; calB = state.cTo;
  calYm = (calA || `${new Date().getFullYear()}-${pad(new Date().getMonth() + 1)}`).slice(0, 7);
  calRender();
}
$("#tm-cal").addEventListener("click", e => {
  const b = e.target.closest("button");
  if (!b) return;
  const d = b.dataset.d;
  if (!calA || calB) { calA = d; calB = null; }   // 新一轮: 重新选起点
  else if (d < calA) { calB = calA; calA = d; }   // 反着点: 自动交换
  else calB = d;                                  // 第二下 = 终点 (同一天 = 单日)
  calRender();
});
$("#tm-prev").addEventListener("click", () => calShift(-1));
$("#tm-next").addEventListener("click", () => calShift(1));
$("#time-opts").addEventListener("click", e => {
  const b = e.target.closest("button");
  if (!b || !b.dataset.v) return;   // 日历里的按钮 (日期/翻月/确定) 不走快捷档逻辑
  if (b.dataset.v === "custom") {   // 展开/收起日历, 连点两次选好再确定生效
    const box = $("#tm-dates");
    box.hidden = !box.hidden;
    if (!box.hidden) calOpen();
    return;
  }
  if (b.dataset.v === state.range) return;
  $("#time-menu").removeAttribute("open");
  setTimeRange(b.dataset.v);
});
$("#tm-apply").addEventListener("click", () => {
  if (!calA) return;                // 一下都没点不生效
  $("#time-menu").removeAttribute("open");
  state.cFrom = calA;               // 只点了起点 = 单日
  state.cTo = calB || calA;
  setTimeRange("custom");
});
$("#time-menu").addEventListener("toggle", () => {   // 重开菜单回到已应用区间
  if ($("#time-menu").open && !$("#tm-dates").hidden) calOpen();
});
setTimeRange(state.range, true);
$("#type-lb").textContent = TYPE_LABELS[state.type] || "类型: 全部";
if (state.type !== "all") {                   // URL 带类型/城市时同步选中态
  $("#type-opts .on").classList.remove("on");
  $(`#type-opts button[data-v="${state.type}"]`).classList.add("on");
}
$("#city-lb").textContent = state.city ? "城市: " + state.city : "城市: 全部";
(async () => {   // 城市筛选选项 (按充电次数降序); 拉不到就只有"全部"
  try {
    const cs = await getJSON("/tesla/charging/api/cities");
    $("#city-opts").innerHTML =
      `<button data-c=""${state.city ? "" : ' class="on"'}>全部</button>` +
      cs.map(c => `<button data-c="${esc(c.city)}"${c.city === state.city ? ' class="on"' : ""}>` +
                  `${esc(c.city)} (${c.count})</button>`).join("");
  } catch (_e) { /* keep 全部 */ }
})();
$("#city-opts").addEventListener("click", e => {
  const b = e.target.closest("button"); if (!b) return;
  $("#city-menu").removeAttribute("open");
  state.city = b.dataset.c;
  $("#city-opts .on").classList.remove("on"); b.classList.add("on");
  $("#city-lb").textContent = state.city ? "城市: " + state.city : "城市: 全部";
  syncURL(); refetch();
});
$("#retry").addEventListener("click", () => { state.err = null; $("#errbox").hidden = true; refetch(); });

masonryEl.addEventListener("click", e => {
  const costBtn = e.target.closest("[data-cost]");
  if (costBtn) {
    editCost(itemsById.get(+costBtn.closest(".card-s").dataset.id));
    return;
  }
  const card = e.target.closest(".card-s");
  if (card) openSheet(+card.dataset.id);
});

/* ============================ 详情 Sheet ============================ */
const sheet = $("#sheet"), backdrop = $("#backdrop"), sheetBody = $("#sheet-body");
const alertBd = $("#alert-bd"), alInput = $("#al-input");
let chSoc, chPw, pwMode = "kw", sheetOpen = false, currentDetailId = null;
const PW_SERIES = {
  kw:       { name: "功率", color: "#3987e5", unit: "kW", key: "kw" },
  voltage:  { name: "电压", color: "#9085e9", unit: "V",  key: "voltage" },
  current:  { name: "电流", color: "#d95926", unit: "A",  key: "current" },
};

function openSheet(id) {
  sheetOpen = true;
  sheet.classList.add("on"); backdrop.classList.add("on");
  sheetBody.innerHTML = `<div class="spin"></div>`;
  loadDetail(id);
}
function closeSheet() {
  sheetOpen = false; currentDetailId = null;
  sheet.classList.remove("on"); backdrop.classList.remove("on");
  [chSoc, chPw].forEach(c => { c && echarts.dispose(c); }); chSoc = chPw = null;
}
backdrop.addEventListener("click", closeSheet);
$("#sheet-close").addEventListener("click", closeSheet);
document.addEventListener("keydown", e => {
  if (e.key !== "Escape") return;
  if (!alertBd.hidden) closeAlert();
  else if (sheetOpen) closeSheet();
});

/* 下滑关闭 */
(() => {
  const zone = $("#grab-zone");
  let y0 = null, dy = 0;
  zone.addEventListener("touchstart", e => { y0 = e.touches[0].clientY; dy = 0; }, { passive: true });
  zone.addEventListener("touchmove", e => {
    if (y0 == null) return;
    dy = Math.max(0, e.touches[0].clientY - y0);
    sheet.style.transition = "none";
    sheet.style.transform = `translateY(${dy}px)`;
  }, { passive: true });
  zone.addEventListener("touchend", () => {
    sheet.style.transition = ""; sheet.style.transform = "";
    if (dy > 110) closeSheet();
    y0 = null;
  });
})();

async function loadDetail(id) {
  let d;
  try {
    d = detailCache.get(id) || await getJSON(`/tesla/charging/api/sessions/${id}`);
    detailCache.set(id, d);
  } catch (e) {
    sheetBody.innerHTML = `<div class="err-box"><p>加载失败: ${esc(e.message)}</p></div>`;
    return;
  }
  if (!sheetOpen) return;
  currentDetailId = id;
  const rangeGain = d.end_rated_range != null && d.start_rated_range != null
    ? d.end_rated_range - d.start_rated_range : null;
  $("#sh-date").textContent = fmtCardDate(d.start);
  $("#sh-loc").textContent = d.city ? `${d.location} · ${d.city}` : d.location;
  $("#sh-row").innerHTML = `
    <span class="tag ${d.is_fast ? "tag-fast" : "tag-slow"}">${d.is_fast ? "⚡ 快充" : "🔌 慢充"}</span>
    <span class="tag tag-slow" style="color:var(--ink-2);background:var(--surface-2)">${esc(d.cable || "—")}</span>
    ${d.charger_type ? `<span class="tag tag-slow" style="color:var(--ink-2);background:var(--surface-2)">${esc(d.charger_type)}</span>` : ""}`;
  sheetBody.innerHTML = `
    <div class="st-grid">
      <div class="st"><div class="lb">充入电量</div><div class="val">${num(d.energy_added)}<small> kWh</small></div></div>
      <div class="st"><div class="lb">表计电量</div><div class="val">${num(d.energy_used)}<small> kWh</small></div></div>
      <div class="st st-cost" id="st-cost-tile"><div class="lb">费用</div><div class="val${d.cost == null ? " red" : ""}" id="st-cost-val">${d.cost != null ? money(d.cost) : "未记费用"}</div></div>
      <div class="st"><div class="lb">电价</div><div class="val" id="st-price-val">${d.price_per_kwh != null ? "¥" + d.price_per_kwh.toFixed(3) + "<small>/kWh</small>" : "—"}</div></div>
      <div class="st"><div class="lb">时长</div><div class="val">${fmtDur(d.duration_min)}</div></div>
      <div class="st"><div class="lb">电量变化</div><div class="val">${d.start_soc}<small>%</small> → ${d.end_soc}<small>%</small></div></div>
      <div class="st"><div class="lb">峰值功率</div><div class="val">${d.power_max ?? "—"}<small> kW</small></div></div>
      <div class="st"><div class="lb">续航增加</div><div class="val">${rangeGain != null ? "+" + num(rangeGain, 0) : "—"}<small> km</small></div></div>
    </div>
    <div class="sh-chart-title">电量 %</div>
    <div id="chart-soc"></div>
    <div class="sh-chart-title">
      <span>充电曲线</span>
      <div class="mini-seg" id="pw-seg">
        <button data-v="kw" class="on">功率</button>
        <button data-v="voltage">电压</button>
        <button data-v="current">电流</button>
      </div>
    </div>
    <div id="chart-pw"></div>
    <div class="sh-addr">${esc(d.address || "")}${d.outside_temp != null ? ` · 平均气温 ${num(d.outside_temp, 0)}°C` : ""}</div>`;

  $("#pw-seg").addEventListener("click", e => {
    const b = e.target.closest("button"); if (!b) return;
    $("#pw-seg .on").classList.remove("on"); b.classList.add("on");
    pwMode = b.dataset.v; renderPwChart(d);
  });

  requestAnimationFrame(() => {
    if (!hasEcharts) return;
    chSoc = echarts.init($("#chart-soc"));
    chPw = echarts.init($("#chart-pw"));
    echarts.connect([chSoc, chPw]);
    const cv = d.curve, xBase = {
      type: "value", min: 0,
      axisLine: { show: false }, axisTick: { show: false },
      axisLabel: { color: chartText.axis, fontSize: 10, formatter: fmtMinAxis },
      splitLine: { lineStyle: { color: "#2c2c2a" } },
    };
    chSoc.setOption({
      animationDuration: 250,
      grid: { left: 6, right: 8, top: 10, bottom: 0, containLabel: true },
      tooltip: { ...tooltipStyle, trigger: "axis",
                 axisPointer: { type: "cross", lineStyle: { color: "#898781" },
                                crossStyle: { color: "#5a5a5e" } },
                 formatter: ps => `${fmtMinAxis(ps[0].axisValue)} · 电量 <b>${ps[0].value}%</b>` },
      xAxis: xBase,
      yAxis: { type: "value", min: 0, max: 100,
               splitLine: { lineStyle: { color: "#2c2c2a" } },
               axisLabel: { color: chartText.axis, fontSize: 10, formatter: "{value}%" } },
      series: [{ type: "line", data: cv.minutes.map((t, i) => [t, cv.soc[i]]),
                 showSymbol: false, sampling: "lttb",
                 lineStyle: { color: "#1fa349", width: 2 },
                 itemStyle: { color: "#1fa349" },
                 areaStyle: { color: "rgba(31,163,73,.10)" } }],
    });
    renderPwChart(d);
  });
}

function renderPwChart(d) {
  if (!chPw) return;
  const s = PW_SERIES[pwMode], cv = d.curve, vals = cv[s.key];
  const yMax = Math.max(...vals, 1);
  chPw.setOption({
    animationDuration: 250,
    grid: { left: 6, right: 8, top: 10, bottom: 0, containLabel: true },
    tooltip: { ...tooltipStyle, trigger: "axis",
               axisPointer: { type: "cross", lineStyle: { color: "#898781" },
                              crossStyle: { color: "#5a5a5e" } },
               formatter: ps => {
                 const i = ps[0].dataIndex;
                 return `${fmtMinAxis(ps[0].axisValue)} · ${s.name} <b>${ps[0].value} ${s.unit}</b>` +
                        (cv.energy[i] != null ? `<br/>累计 ${num(cv.energy[i])} kWh` : "");
               } },
    xAxis: { type: "value", min: 0,
             axisLine: { show: false }, axisTick: { show: false },
             axisLabel: { color: chartText.axis, fontSize: 10, formatter: fmtMinAxis },
             splitLine: { lineStyle: { color: "#2c2c2a" } } },
    yAxis: { type: "value", min: 0, max: Math.ceil(yMax * 1.08),
             splitLine: { lineStyle: { color: "#2c2c2a" } },
             axisLabel: { color: chartText.axis, fontSize: 10 } },
    series: [{ type: "line", data: cv.minutes.map((t, i) => [t, vals[i]]),
               showSymbol: false, sampling: "lttb",
               lineStyle: { color: s.color, width: 2 },
               itemStyle: { color: s.color },
               areaStyle: { color: s.color + "1a" } }],
  }, { replaceMerge: ["series"] });
}

/* ============================ 费用编辑 ============================ */
let editing = null, saving = false;

function editCost(it) {
  if (!it) return;
  editing = it;
  $("#al-msg").textContent = `${it.date} · ${it.location}`;
  $("#al-err").textContent = "";
  $("#al-clear").hidden = it.cost == null;
  alertBd.hidden = false;
  requestAnimationFrame(() => {
    alertBd.classList.add("on");
    alInput.value = it.cost != null ? it.cost : "";
    setTimeout(() => { alInput.focus(); alInput.select(); }, 80);
  });
}

function closeAlert() {
  alertBd.classList.remove("on");
  setTimeout(() => { alertBd.hidden = true; }, 230);
  editing = null; saving = false;
}

async function saveCost() {
  if (!editing || saving) return;
  const raw = alInput.value.trim().replace(/[¥￥,，\s]/g, "");
  let cost = null;
  if (raw !== "") {
    cost = parseFloat(raw);
    if (!isFinite(cost) || cost < 0 || cost > 100000) {
      $("#al-err").textContent = "请输入 0 ~ 100000 之间的金额";
      alInput.classList.remove("shake");
      void alInput.offsetWidth;
      alInput.classList.add("shake");
      return;
    }
  }
  saving = true;
  try {
    const r = await fetch(`/tesla/charging/api/sessions/${editing.id}/cost`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cost }),
    });
    if (r.status === 401) { location.replace("/tesla/login"); return; }
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.status);
    const d = await r.json();
    applyCostUpdate(editing.id, d.cost, d.price_per_kwh);
    closeAlert();
  } catch (e) {
    $("#al-err").textContent = "保存失败: " + e.message;
    saving = false;
  }
}

function applyCostUpdate(id, cost, ppk) {
  const it = itemsById.get(id);
  if (it) {
    it.cost = cost; it.price_per_kwh = ppk;
    const old = masonryEl.querySelector(`.card-s[data-id="${id}"]`);
    if (old) old.replaceWith(renderCard(it));
  }
  const det = detailCache.get(id);
  if (det) { det.cost = cost; det.price_per_kwh = ppk; }
  if (sheetOpen && currentDetailId === id) {
    const cv = $("#st-cost-val"), pv = $("#st-price-val");
    if (cv) {
      cv.textContent = cost != null ? money(cost) : "未记费用";
      cv.classList.toggle("red", cost == null);
    }
    if (pv) pv.textContent = ppk != null ? "¥" + ppk.toFixed(3) : "—";
  }
  loadSummary().catch(() => {});   // 统计与图表静默刷新
  loadCharts().catch(() => {});
}

$("#al-cancel").addEventListener("click", closeAlert);
$("#al-save").addEventListener("click", saveCost);
$("#al-clear").addEventListener("click", () => { alInput.value = ""; saveCost(); });
alertBd.addEventListener("click", e => { if (e.target === alertBd) closeAlert(); });
alInput.addEventListener("keydown", e => {
  e.stopPropagation();
  if (e.key === "Enter") saveCost();
});
sheetBody.addEventListener("click", e => {
  if (e.target.closest("#st-cost-tile") && currentDetailId != null)
    editCost(detailCache.get(currentDetailId));
});


$("#logout").addEventListener("click", async () => {
  try { await fetch("/tesla/api/logout", { method: "POST" }); } catch (e) {}
  location.href = "/tesla/login";
});
(async () => {
  try {
    const cars = await getJSON("/tesla/charging/api/car");
    if (cars[0]) $("#car-pill").textContent = `${cars[0].model} · ${cars[0].name}`;
  } catch (e) { /* 车辆信息失败不阻塞 */ }
  if (!hasEcharts) $("#charts-grid").style.display = "none";
  await refetch();
})();
