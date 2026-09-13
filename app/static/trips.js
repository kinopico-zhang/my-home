// trips.js — 由 trips.html 内联脚本抽出 (位置/顺序/语义不变), 供 lint 与测试
"use strict";
/* 页签菜单: 点空白处收起。
   注意: 级联菜单钻取会在点击处理器里 innerHTML 重渲染, 事件目标被脱链
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
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g,
  c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const pad = n => String(n).padStart(2, "0");

/* "2026-09-10 08:32" → 本地 Date (服务端已转北京时间; 手动解析, 兼容 iOS Safari) */
function parseLocal(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/.exec(s || "");
  return m ? new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]) : new Date(s);
}
const WEEK = ["日", "一", "二", "三", "四", "五", "六"];
function fmtCardDate(s) {
  const d = parseLocal(s);
  return `${d.getMonth() + 1}月${d.getDate()}日 周${WEEK[d.getDay()]} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function fmtTime(s) {
  const d = parseLocal(s);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function fmtDur(min) {
  if (min == null) return "—";
  const h = Math.floor(min / 60), m = min % 60;
  /* "1时44分" 而非 "1小时44分": 统计格窄屏放不下长格式会折行 */
  return h ? `${h}时${m ? m + "分" : ""}` : `${m}分钟`;
}
const num = (v, d = 1) => v == null ? "—" : Number(v).toFixed(d).replace(/\.0+$/, "");
/* 播放中实时时长: 秒 → "m:ss" / "h:mm:ss" */
function fmtDurLive(sec) {
  sec = Math.max(0, Math.round(sec));
  const h = Math.floor(sec / 3600), m = Math.floor(sec / 60) % 60, s = sec % 60;
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

async function getJSON(url) {
  const r = await fetch(url, { cache: "no-store" });
  if (r.status === 401) { location.replace("/tesla/login"); throw new Error("未登录"); }
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

async function postJSON(url, body) {
  const r = await fetch(url, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (r.status === 401) { location.replace("/tesla/login"); throw new Error("未登录"); }
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `${r.status}`);
  return r.json();
}

/* ============================ 行程列表 (单列) ============================ */
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
const KM_BUCKETS = [   // 里程档位: URL 里存档位码, 请求时换算成 km_min/km_max
  { v: "all", lb: "全部", min: null, max: null },
  { v: "0-20", lb: "20km 内", min: 0, max: 20 },
  { v: "20-100", lb: "20–100km", min: 20, max: 100 },
  { v: "100-300", lb: "100–300km", min: 100, max: 300 },
  { v: "300+", lb: "300km 以上", min: 300, max: null },
];
// URL → 初始筛选: ?range= 快捷档; ?from=&to= 自定义区间; ?from_loc=/?to_loc=/?km= 筛选行
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const qs0 = new URLSearchParams(location.search);
let range0 = TIME_RANGES.some(r => r.v === qs0.get("range")) ? qs0.get("range") : "all";
let cFrom0 = null, cTo0 = null;
if (range0 === "all") {
  const f = qs0.get("from"), t = qs0.get("to");
  if (DATE_RE.test(f || "") && DATE_RE.test(t || "") && f <= t) { range0 = "custom"; cFrom0 = f; cTo0 = t; }
}
const locParam = k => {   // ?from_loc=省/市/区 (1~3 段, 脏参数丢弃)
  const segs = (qs0.get(k) || "").split("/").map(s => s.trim()).filter(Boolean);
  return segs.length && segs.length <= 3 && segs.every(s => s.length <= 30) ? segs.join("/") : "";
};
const state = { range: range0, cFrom: cFrom0, cTo: cTo0,
                fromLoc: locParam("from_loc"), toLoc: locParam("to_loc"),
                km: KM_BUCKETS.some(b => b.v === qs0.get("km")) ? qs0.get("km") : "all",
                drvId: /^\d+$/.test(qs0.get("driver_id") || "") ? +qs0.get("driver_id") : null,
                offset: 0, total: 0, loading: false, done: false, err: null };
const trackCache = new Map();       // id → {pts, ts} 全精度轨迹
let driversCache;   // 设置页驾驶员表 (undefined=还没拉过, null=失败, 数组=结果), 筛选行与弹层共用
const items = [];                   // 已加载卡片数据 (与 #list 子元素一一对应, 多选用)

const listEl = $("#list");

function renderCard(it) {
  const el = document.createElement("article");
  el.className = "card-t"; el.dataset.id = it.id;
  const avg = it.km != null && it.min ? Math.round(it.km / (it.min / 60)) : null;
  el.innerHTML = `
    <div class="ct-top">
      <span class="ct-date">${esc(fmtCardDate(it.start))}</span>
      ${it.driver ?   /* 有驾驶员就上卡: 显式标注正常亮, 默认兜底弱化 .def */
        `<span class="ct-drv${it.driver_id != null ? "" : " def"}">${esc(it.driver)}</span>` : ""}
      <span class="ct-arrow">→ 查看轨迹</span>
      <span class="pick" aria-hidden="true"></span>
    </div>
    <div class="ct-cells">
      <div class="ct-cell"><div class="lb">里程</div>
        <div class="val">${it.km != null ? num(it.km) + "<small>km</small>" : "—"}</div></div>
      <div class="ct-cell"><div class="lb">时长</div><div class="val">${fmtDur(it.min)}</div></div>
      ${it.kwh != null ? `<div class="ct-cell"><div class="lb">总电耗</div>
        <div class="val">${num(it.kwh)}<small>kWh</small></div></div>` : ""}
    </div>
    <div class="ct-addr">
      <div class="line from"><i class="dot"></i><span class="txt">${esc(it.from)}</span></div>
      <div class="line to"><i class="dot"></i><span class="txt">${esc(it.to)}</span></div>
    </div>
    <div class="ct-sub">${avg ? `均速 ${avg} km/h` : ""}${avg && it.wh_per_km != null ? " · " : ""}${it.wh_per_km != null ? `平均电耗 ${num(it.wh_per_km, 0)} Wh/km` : ""}</div>`;
  el.addEventListener("click", () => {
    if (document.body.classList.contains("selecting")) pickCard(el);
    else openTrip(it);
  });
  return el;
}

const tailEl = $("#tail");
function setTail() {
  tailEl.hidden = state.total === 0 && !state.loading && state.done && !state.err;
  $("#loader-spin").hidden = !state.loading;
  $("#endnote").hidden = !(state.done && state.total > 0);
  $("#empty").hidden = !(state.done && state.total === 0 && !state.err);
  $("#errbox").hidden = !state.err;
  $("#count-badge").textContent = state.total ? `共 ${state.total} 次` : "";
}

/* ---------- 刷新: 顶栏按钮 (下拉手势已按需求撤掉) ---------- */
async function refreshList() {
  if (state.loading) return;
  items.length = 0;
  listEl.innerHTML = "";
  state.offset = 0; state.total = 0; state.done = false; state.err = null;
  await loadMore();
  window.scrollTo({ top: 0 });
}

$("#refresh-btn").addEventListener("click", async () => {
  const btn = $("#refresh-btn");
  btn.classList.add("busy");
  await refreshList();
  btn.classList.remove("busy");
});

const PRELOAD_PX = 800;   // 触底前多远开始预加载 (IO rootMargin 与链式续载共用)

async function loadMore() {
  if (state.loading || state.done) return;
  state.loading = true; state.err = null; setTail();
  try {
    const p = new URLSearchParams({ offset: state.offset, limit: PAGE });
    if (state.range === "custom") {   // 自定义起止 (日历)
      p.set("from", state.cFrom); p.set("to", state.cTo);
    } else {
      const from = timeFrom(state.range);
      if (from) p.set("from", from);
    }
    if (state.fromLoc) p.set("from_loc", state.fromLoc);
    if (state.toLoc) p.set("to_loc", state.toLoc);
    const kb = KM_BUCKETS.find(b => b.v === state.km);
    if (kb && kb.min != null) p.set("km_min", kb.min);
    if (kb && kb.max != null) p.set("km_max", kb.max);
    if (state.drvId != null) p.set("driver_id", state.drvId);
    const d = await getJSON("/tesla/trips/api/sessions?" + p.toString());
    state.total = d.total; state.offset += d.items.length;
    if (state.offset >= d.total) state.done = true;
    d.items.forEach(it => { items.push(it); listEl.appendChild(renderCard(it)); });
  } catch (e) {
    state.err = "数据加载失败: " + e.message;
  }
  state.loading = false; setTail();
  /* 首页填不满"视口+预载区"时, tail 一直留在交叉区里, IntersectionObserver
     只在进出过渡时回调, 不会再触发 —— 主动续载直到 tail 滚出预载区。
     (Chrome 桌面端宽屏下 24 张卡不足一屏, 曾因此永远卡在第一页。) */
  if (!state.done && !state.err &&
      tailEl.getBoundingClientRect().top < window.innerHeight + PRELOAD_PX)
    loadMore();
}

function timeLabel() {
  if (state.range === "custom")   // 自定义显示紧凑区间, 如 01/01–03/31
    return `${state.cFrom.slice(5).replace("-", "/")}–${state.cTo.slice(5).replace("-", "/")}`;
  return TIME_RANGES.find(r => r.v === state.range).lb;
}
function filterQS() {   // 时间/起终点/里程 → 参数串 (无 ? 前缀), 地址栏与请求共用
  const p = new URLSearchParams();
  if (state.range === "custom") { p.set("from", state.cFrom); p.set("to", state.cTo); }
  else if (state.range !== "all") p.set("range", state.range);
  if (state.fromLoc) p.set("from_loc", state.fromLoc);
  if (state.toLoc) p.set("to_loc", state.toLoc);
  if (state.km !== "all") p.set("km", state.km);
  if (state.drvId != null) p.set("driver_id", state.drvId);
  return p.toString();
}
function listURL(key) {   // 行程页地址栏: 筛选参数 + 可选行程深链 (?id=/ ?ids=)
  const parts = [filterQS(),
                 key ? `${/[-,]/.test(key) ? "ids=" : "id="}${key}` : null].filter(Boolean);
  return "/tesla/trips" + (parts.length ? "?" + parts.join("&") : "");
}
function syncURL() {   // 筛选写进地址栏 (默认值不写, 保留打开中的行程深链)
  history.replaceState(history.state, "", listURL(urlTripKey()));
}
function resetList() {   // 筛选变化: 清空列表重新拉
  items.length = 0; listEl.innerHTML = "";
  state.offset = 0; state.total = 0; state.done = false; state.err = null;
  setTail();
  loadMore();
}
function setTimeRange(v, skipReload) {
  state.range = v;
  $("#time-lb").textContent = timeLabel();
  document.querySelectorAll("#time-opts button[data-v]").forEach(b =>
    b.classList.toggle("on", b.dataset.v === v));
  if (v !== "custom") $("#tm-dates").hidden = true;   // 回到快捷档, 收起日历
  syncURL();
  if (!skipReload) resetList();
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
setTimeRange(state.range, true);              // 初始化: 只同步标签/选中态, 不重拉

/* ---------- 筛选行: 起终点省市区级联 / 里程范围 ----------
   树来自 /trips/api/regions (省→市→区县, 次数降序)。点层级行钻下一级,
   顶部 "全部X" 行选中当前层 (省/市/区县任一级都能作为筛选条件), 叶子直接选中。 */
const REGIONS = { start: [], end: [] };
function bindLocMenu(menuId, optsId, key, lbId, prefix, treeKey) {
  const menuEl = $("#" + menuId), optsEl = $("#" + optsId), lbEl = $("#" + lbId);
  const stack = [];   // 当前钻取路径 (省名/市名), 空 = 省列表
  const setLoc = v => {
    state[key] = v;
    lbEl.textContent = prefix + (v ? v.split("/").pop() : "全部");   // 显示末级, title 全路径
    lbEl.parentElement.title = v;
  };
  const nodesAt = () => {   // stack 对应的节点层
    let nodes = REGIONS[treeKey];
    for (const s of stack) {
      const n = nodes.find(x => x.name === s);
      nodes = n ? n.children : [];
    }
    return nodes;
  };
  const render = () => {
    const sel = state[key], cur = stack.join("/");
    const rows = nodesAt().map(n => {
      const path = (cur ? cur + "/" : "") + n.name;
      return `<button class="loc-row${path === sel ? " on" : ""}" data-n="${esc(n.name)}">` +
        `<span class="nm">${esc(n.name)}</span>` +
        `<span class="cnt">${n.count}${n.children.length ? " ›" : ""}</span></button>`;
    }).join("");
    optsEl.innerHTML =
      (stack.length ? `<button class="loc-back" data-b="1">‹ 返回</button>` +
        `<div class="loc-crumb">${esc(stack.join(" · "))}</div>` : "") +
      `<button data-a="${esc(cur)}"${sel === cur ? ' class="on"' : ""}>` +
      `${cur ? "全部" + esc(stack[stack.length - 1]) : "全部"}</button>` + rows;
  };
  optsEl.addEventListener("click", e => {
    const b = e.target.closest("button"); if (!b) return;
    if (b.dataset.b) { stack.pop(); return render(); }   // ‹ 返回
    if (b.dataset.a !== undefined) {                     // "全部X" = 选中当前层
      menuEl.removeAttribute("open");
      setLoc(b.dataset.a);
      syncURL(); resetList();
      return;
    }
    const node = nodesAt().find(n => n.name === b.dataset.n);
    if (!node) return;
    if (node.children.length) { stack.push(node.name); return render(); }   // 钻下一级
    menuEl.removeAttribute("open");                     // 叶子 (区县) 直接选中
    setLoc([...stack, node.name].join("/"));
    syncURL(); resetList();
  });
  menuEl.addEventListener("toggle", () => {   // 关闭时把视图重置到当前所选的父层,
    if (menuEl.open) return;                  // 下次打开即所见 (toggle 异步, 开时才渲会闪旧视图)
    stack.length = 0;
    if (state[key]) stack.push(...state[key].split("/").slice(0, -1));
    render();
  });
  setLoc(state[key]);   // URL 带筛选时同步标签
  if (state[key]) stack.push(...state[key].split("/").slice(0, -1));
  render();
  return render;
}
const renderLocStart = bindLocMenu("fc-menu", "fc-opts", "fromLoc", "fc-lb", "起点: ", "start");
const renderLocEnd = bindLocMenu("tc-menu", "tc-opts", "toLoc", "tc-lb", "终点: ", "end");
$("#km-opts").addEventListener("click", e => {
  const b = e.target.closest("button"); if (!b || b.dataset.k === state.km) return;
  $("#km-menu").removeAttribute("open");
  state.km = b.dataset.k;
  $("#km-opts .on").classList.remove("on"); b.classList.add("on");
  $("#km-lb").textContent = "里程: " + KM_BUCKETS.find(x => x.v === state.km).lb;
  syncURL(); resetList();
});
$("#km-lb").textContent = "里程: " + KM_BUCKETS.find(b => b.v === state.km).lb;
if (state.km !== "all") {
  $("#km-opts .on").classList.remove("on");
  $(`#km-opts button[data-k="${state.km}"]`).classList.add("on");
}
(async () => {   // 起终点省市区树 (次数降序); 拉不到就只有"全部"
  try {
    const rg = await getJSON("/tesla/trips/api/regions");
    REGIONS.start = rg.start || [];
    REGIONS.end = rg.end || [];
  } catch (_e) { /* keep empty */ }
  renderLocStart(); renderLocEnd();
})();

/* 驾驶员筛选: 选项来自设置页的驾驶员表 (没配驾驶员整颗筛选藏掉); 筛选口径与
   卡片一致 —— 选默认驾驶员 = 标注它的 + 未标注的 (后端合并处理) */
(async () => {
  if (driversCache === undefined) {
    try { driversCache = await getJSON("/tesla/api/drivers"); }
    catch { driversCache = null; }
  }
  const drivers = driversCache || [];
  if (!drivers.length) return;
  const opts = $("#drv-opts");
  opts.innerHTML = `<button data-id=""${state.drvId == null ? ' class="on"' : ""}>全部</button>` +
    drivers.map(d =>
      `<button data-id="${d.id}"${state.drvId === d.id ? ' class="on"' : ""}>${esc(d.name)}</button>`).join("");
  if (state.drvId != null) {               // URL 深链带入的驾驶员要存在才算数
    const hit = drivers.find(d => d.id === state.drvId);
    if (hit) $("#drv-lb").textContent = "驾驶员: " + hit.name;
    else {
      state.drvId = null;
      opts.querySelector(".on")?.classList.remove("on");
      opts.querySelector('button[data-id=""]').classList.add("on");
    }
  }
  $("#drv-menu").hidden = false;
})();
$("#drv-opts").addEventListener("click", e => {
  const b = e.target.closest("button");
  if (!b) return;
  const v = b.dataset.id === "" ? null : +b.dataset.id;
  if (v === state.drvId) return;
  $("#drv-menu").removeAttribute("open");
  state.drvId = v;
  $("#drv-opts .on").classList.remove("on"); b.classList.add("on");
  $("#drv-lb").textContent = "驾驶员: " + b.textContent;
  syncURL(); resetList();
});

/* 懒加载: 触底前 PRELOAD_PX 预加载下一页 */
new IntersectionObserver(es => {
  if (es[0].isIntersecting) loadMore();
}, { rootMargin: PRELOAD_PX + "px" }).observe(tailEl);

$("#retry").addEventListener("click", () => { state.err = null; loadMore(); });
$("#logout").addEventListener("click", async () => {
  await fetch("/tesla/api/logout", { method: "POST" });
  location.replace("/tesla/login");
});

/* ============================ 多选: 连续行程拼成一条轨迹 ============================ */
const MERGE_MAX = 100;             // 合并接口上限 (后端 /api/merged 校验 2~100 段)
let selAnchor = -1;                 // 范围锚点 (点选的第一张卡)
let selRange = [-1, -1];            // 当前选中范围 [from, to] (闭区间, 必连续)

function applyPick() {
  const [a, b] = selRange, on = a >= 0;
  [...listEl.children].forEach((el, i) => el.classList.toggle("picked", on && i >= a && i <= b));
  const n = on ? b - a + 1 : 0;
  const km = on ? items.slice(a, b + 1).reduce((s, it) => s + (it.km || 0), 0) : 0;
  $("#sel-count").textContent = n;
  $("#sel-km").textContent = num(km);
  /* 上限提示: 划选超上限, 或全选封顶 (列表还有更多段装不进) 都亮 */
  $("#sel-cap").hidden = n < MERGE_MAX || items.length <= MERGE_MAX;
  $("#sel-go").disabled = n < 2 || n > MERGE_MAX;
  $("#gp-btn").disabled = n < 2 || n > MERGE_MAX;   // 存分组与合并播放同一上限
  $("#sel-all").textContent =             // 已选全部 → 再点一次变清空
    on && a === 0 && b === items.length - 1 ? "清空" : "全选";
}

/* 两段式点选: 点第一张卡定锚, 点另一张 → 锚点到该处的连续范围; 再点锚点清空重来 */
function pickCard(el) {
  const i = [...listEl.children].indexOf(el);
  if (i < 0) return;
  if (selAnchor < 0) { selAnchor = i; selRange = [i, i]; }
  else if (i === selAnchor) { selAnchor = -1; selRange = [-1, -1]; }
  else selRange = [Math.min(selAnchor, i), Math.max(selAnchor, i)];
  applyPick();
}

function enterSelect() {
  document.body.classList.add("selecting");
  $("#selbar").hidden = false;
  selAnchor = -1; selRange = [-1, -1];
  applyPick();
}
function exitSelect() {
  document.body.classList.remove("selecting");
  $("#selbar").hidden = true;
  $("#selbar").classList.remove("naming");
  selAnchor = -1; selRange = [-1, -1];
  applyPick();
}
/* 长按卡片进多选 (多选按钮已撤, 这是唯一入口); 触屏长按 / 桌面按住 480ms
   → 进多选并选中这张卡。移动超 10px (滚动/下拉) 即取消; 长按后紧跟的
   click 吞掉, 别又把弹层打开。 */
(function setupLongPress() {
  const HOLD_MS = 480;
  let timer = null, card = null, x0 = 0, y0 = 0, fired = false, suppress = false;
  const clear = () => {
    if (timer) clearTimeout(timer);
    timer = null; card = null; fired = false;
  };
  const start = (x, y, target) => {
    suppress = false;
    if (document.body.classList.contains("selecting")) return;
    card = target.closest(".card-t");
    if (!card) return;
    x0 = x; y0 = y;
    timer = setTimeout(() => {
      timer = null; fired = true; suppress = true;
      enterSelect(); pickCard(card);
    }, HOLD_MS);
  };
  const move = (x, y) => {
    if (timer != null && Math.hypot(x - x0, y - y0) > 10) clear();
  };
  listEl.addEventListener("touchstart", e => {
    if (e.touches.length !== 1) { clear(); return; }
    start(e.touches[0].clientX, e.touches[0].clientY, e.target);
  }, { passive: true });
  listEl.addEventListener("touchmove",
    e => move(e.touches[0].clientX, e.touches[0].clientY), { passive: true });
  listEl.addEventListener("touchend", e => {
    if (fired) { e.preventDefault(); suppress = false; }   // click 不会再产生
    clear();
  }, { passive: false });
  listEl.addEventListener("touchcancel", clear, { passive: true });
  listEl.addEventListener("mousedown", e => {   // 桌面: 按住不放同样进多选
    if (e.button === 0) start(e.clientX, e.clientY, e.target);
  });
  window.addEventListener("mousemove", e => move(e.clientX, e.clientY));
  window.addEventListener("mouseup", clear);
  listEl.addEventListener("click", e => {       // 长按紧随的 click 不开弹层
    if (suppress) { suppress = false; e.stopPropagation(); e.preventDefault(); }
  }, true);
  listEl.addEventListener("contextmenu", e => {  // iOS 长按呼系统菜单会掐掉触摸
    if (e.target.closest(".card-t")) e.preventDefault();
  });
})();
$("#sel-cancel").addEventListener("click", exitSelect);
/* 全选: 选中当前筛选下的全部行程, 没装够的页先补载; 合并接口一次最多
   MERGE_MAX 段, 超出只选最新的 (列表按时间倒序) 前 100 段。已选全部时
   按钮变"清空", 再点一次取消选择。 */
$("#sel-all").addEventListener("click", async () => {
  const isAll = selRange[0] === 0 && selRange[1] === items.length - 1;
  if (!isAll) {
    const btn = $("#sel-all");
    btn.disabled = true;
    try {
      const target = Math.min(state.total || items.length, MERGE_MAX);
      while (!state.done && !state.err && items.length < target) await loadMore();
    } finally { btn.disabled = false; }
    if (state.err) return;        // 补载失败: 列表区已有重试入口, 不动现有选择
  }
  selAnchor = -1;
  selRange = isAll || items.length < 2 ? [-1, -1]
    : [0, Math.min(MERGE_MAX, items.length) - 1];
  applyPick();
});
$("#sel-go").addEventListener("click", () => {
  const ids = items.slice(selRange[0], selRange[1] + 1).map(it => it.id);
  exitSelect();
  openMerged(ids);
});

/* ============================ 轨迹分组 ============================ */
/* 逻辑分组存自有库 (api/groups), 行程原数据不动; 管理 (打开/改名/删除) 在
   独立的分组页, 本页只留创建入口 (多选 → 存为分组)。打开分组 = 行程页
   ?ids= 深链合并播放, 关弹层自动回分组页 (见 closeTrip)。 */
let gpIds = [];         // 进入命名模式时快照的选中 ids (之后划选变动不影响本次保存)
let toastTimer = null;

function toast(msg) {
  const el = $("#toast");
  el.textContent = msg;
  el.hidden = false;
  requestAnimationFrame(() => el.classList.add("on"));
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    el.classList.remove("on");
    setTimeout(() => { el.hidden = true; }, 250);
  }, 1800);
}

// ---- 多选栏: 存为分组 (命名模式, 预填日期跨度) ----
$("#gp-btn").addEventListener("click", () => {
  gpIds = items.slice(selRange[0], selRange[1] + 1).map(it => it.id);
  const dNew = items[selRange[0]].date.slice(5);   // 列表时间倒序: [0] 最新 [末] 最旧
  const dOld = items[selRange[1]].date.slice(5);
  $("#gp-name").value = dNew === dOld ? dNew : `${dOld}~${dNew}`;   // 预填日期跨度, 可改
  $("#gp-save").disabled = false;
  $("#selbar").classList.add("naming");
  setTimeout(() => $("#gp-name").select(), 50);    // 等命名行布局稳定再全选
});

$("#gp-name-cancel").addEventListener("click", () =>
  $("#selbar").classList.remove("naming"));

$("#gp-name").addEventListener("keydown", e => {
  if (e.key === "Enter") { e.preventDefault(); $("#gp-save").click(); }
  else if (e.key === "Escape") { $("#selbar").classList.remove("naming"); }
});

$("#gp-save").addEventListener("click", async () => {
  const name = $("#gp-name").value.trim();
  if (!name) { toast("名字不能为空"); return; }
  const btn = $("#gp-save");
  btn.disabled = true;
  try {
    const r = await fetch("/tesla/trips/api/groups", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, ids: gpIds }),
    });
    if (r.status === 401) { location.replace("/tesla/login"); return; }
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `${r.status}`);
    toast(`已存分组「${name}」`);
    exitSelect();
  } catch (err) {
    toast(`存分组失败: ${err.message}`);
    btn.disabled = false;
  }
});

/* ============================ 轨迹弹层 ============================ */
let amapLoading = null;             // Promise<true>: 高德脚本就绪
let amapStyle = "amap://styles/dark";   // 地图样式 (config 下发, 设置页可换)
let tripMap = null;                 // 弹层内地图实例, 复用不销毁
let openSeq = 0;                    // 连续点开多条时, 只认最后一次
let curKey = null;                  // 弹层当前行程 key (单条 "2200" / 合并 "1836-1839"), 地址栏同步用
let sheetTrip = null;               // 弹层当前单条行程条目 (标驾驶员用; 合并 = null)
const mergedCache = new Map();      // "首-尾" → 合并轨迹整包 (流式下完后存, 重开秒开)

/* 多选的连续行程 → 一条轨迹。ids 为多选数组 (必连续 → 只记头尾 id) 或
   深链原始串 ("首-尾" / 旧版逗号)。弹层立即打开阻断其他操作, 轨迹数据
   走流式接口边下边播 (见 loadMergedStream); 整包缓存命中则直接播。 */
function openMerged(ids, fromUrl) {
  const key = typeof ids === "string" ? ids
    : `${Math.min(...ids)}-${Math.max(...ids)}`;
  return openTrip({ id: "m:" + key, merged: true, mergeKey: key }, fromUrl);   // promise 传回 (深链失败抹参靠它)
}

/* WebGL 保留绘图缓冲: 导出视频要 drawImage 地图画布拿内容, 高德默认建的
   上下文没开 preserveDrawingBuffer —— 合成器取走画面后缓冲即清空,
   drawImage 只能拿到黑帧 (dbg90 实测: 无补丁全画布直画 0 像素, 有补丁
   有内容)。上下文属性建时即定, 必须在高德脚本加载前装好。 */
function patchGLKeepBuffer() {
  if (patchGLKeepBuffer.done) return;
  patchGLKeepBuffer.done = true;
  const orig = HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.getContext = function (type, attrs) {
    if (type === "webgl" || type === "webgl2" || type === "experimental-webgl")
      attrs = Object.assign({ antialias: true }, attrs, { preserveDrawingBuffer: true });
    return orig.call(this, type, attrs);
  };
}

function loadAMapScript(key, securityCode) {
  return new Promise((resolve, reject) => {
    patchGLKeepBuffer();
    if (securityCode) window._AMapSecurityConfig = { securityJsCode: securityCode };
    const s = document.createElement("script");
    s.src = "https://webapi.amap.com/maps?v=2.0&key=" + encodeURIComponent(key);
    s.onload = () => resolve(true);
    s.onerror = () => reject(new Error("高德地图脚本加载失败, 请检查网络"));
    document.head.appendChild(s);
  });
}

/* 高德脚本只加载一次 (弹层打开与后台预载共用入口; 失败可重试) */
function ensureAMap() {
  if (!amapLoading) {
    amapLoading = (async () => {
      const cfg = await getJSON("/tesla/map/api/config?_=" + Date.now());
      if (!cfg.amap_key) throw new Error("未配置高德地图 Key (.env 里设置 AMAP_KEY)");
      if (cfg.style) amapStyle = cfg.style;
      await loadAMapScript(cfg.amap_key, cfg.security_code);
      return true;
    })();
    amapLoading.catch(() => { amapLoading = null; });
  }
  return amapLoading;
}

function tripMsg(text, spin) {
  $("#trip-msg").hidden = !text && !spin;
  $("#trip-msg-text").textContent = text || "";
  $("#trip-spin").hidden = !spin;
}

/* ---------- 轨迹动画: 起点跑到终点, 视角跟随, 结束后拉远看全局 ----------
   背景: 速度色全程线 (淡); 前进: 白色亮线逐帧生长; 头部: 当前速度色圆点。 */
let animRaf = 0;
let anim = null;            // 当前播放会话 (playTrack 创建, 控制条/收尾引用)
let curSess = null;         // 当前轨迹会话: 播放结束后仍存活, 供异步路径回调判定
let rec = null;             // 录制中的导出状态 (弹层关/播完的钩子在前面就要读, 见导出视频段)

/* ---------- 播放动画期间保持亮屏 ----------
   iPhone 全屏 App 看几十秒到几分钟的回放, 中途自动锁屏/变暗很烦。双保险:
   ① Wake Lock API (iOS 16.4+) —— 但家全屏 App (standalone) 里申请成功也可能
      不生效 (已知 WebKit 问题);
   ② 再挂一个 1px 循环无声视频 (NoSleep.js 同款 mp4, MIT) —— 正在播放的
      媒体 iOS 一定不熄屏。音频轨本身无声, 不外放声音。
   开播/重播/继续播时启用, 暂停/播完/换行程/关弹层释放; 页面切后台浏览器
   会自动释放锁, 回前台若还在播重新启用。 */
const AWAKE_VIDEO_WEBM = "data:video/webm;base64,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";  // Chromium/桌面 (无 H.264 构建)
const AWAKE_VIDEO_MP4 = "data:video/mp4;base64,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";  // iOS Safari (H.264)
// 两段都来自 NoSleep.js v0.12 (MIT, richtr/NoSleep.js), 1 秒静音循环
let wakeLock = null;
let awakeVideo = null;
function holdScreenAwake() {
  if (!awakeVideo) {                    // 首次: 建 1px 隐藏循环视频并播放
    const v = document.createElement("video");
    v.setAttribute("playsinline", "");  // iOS 不弹全屏播放器
    v.loop = true;
    for (const [type, url] of [["video/webm", AWAKE_VIDEO_WEBM],
                                ["video/mp4", AWAKE_VIDEO_MP4]]) {
      const s = document.createElement("source");
      s.type = type; s.src = url;
      v.append(s);
    }
    v.style.cssText = "position:fixed;left:-9px;top:-9px;width:1px;"
      + "height:1px;opacity:0;pointer-events:none";
    document.body.appendChild(v);
    awakeVideo = v;
  }
  awakeVideo.play().catch(() => {});    // 被拒 (无手势等) 静默, 还有 Wake Lock
  if (!("wakeLock" in navigator)) return;
  if (wakeLock && !wakeLock.released) return;
  navigator.wakeLock.request("screen").then(l => {
    wakeLock = l;
    l.addEventListener("release", () => { if (wakeLock === l) wakeLock = null; });
  }).catch(() => {});       // 被拒 (低电量等) 静默: 不影响播放本身
}
function releaseScreenAwake() {
  if (wakeLock) { wakeLock.release().catch(() => {}); wakeLock = null; }
  if (awakeVideo) awakeVideo.pause();
}
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && anim && !anim.paused && !anim.finished)
    holdScreenAwake();      // 回前台且还在播: 锁已被系统释放, 重新申请
});

function stopAnim() {
  if (animRaf) cancelAnimationFrame(animRaf);
  animRaf = 0;
  anim = null;
  if (rec) stopRecExport(true);   // 关弹层/换行程: 录制中的导出一并取消
  releaseScreenAwake();     // 关弹层/换行程都走这, 一并允许熄屏
  $("#playbar").hidden = true;
}

/* 播放中点一下地图 = 跳过动画, 直接收尾 (亮线删除, 淡线变亮, 拉远全局) */
function skipAnim() {
  if (anim) anim.finish();
}

/* 断档两点间的真实道路路径 (高德驾车规划 · 距离优先/最短路程):
   返回 gcj 路径数组, 失败/没路返回 null, 调用方回退直线。 */
const routeCache = new Map();   // "driveId:aIdx-bIdx" → gcj 路径 (只缓存成功)
function routeBetween(aGcj, bGcj) {
  return new Promise(resolve => {
    AMap.plugin("AMap.Driving", () => {
      try {
        const policy = AMap.DrivingPolicy && AMap.DrivingPolicy.LEAST_DISTANCE != null
          ? AMap.DrivingPolicy.LEAST_DISTANCE : 2;
        new AMap.Driving({ policy }).search(aGcj, bGcj, (status, result) => {
          if (status !== "complete" || !result.routes || !result.routes.length)
            return resolve(null);
          const route = [];
          for (const st of result.routes[0].steps)
            for (const p of st.path) route.push([p.lng, p.lat]);
          resolve(route.length >= 2 ? route : null);
        });
      } catch (e) {
        console.warn("断档路径规划失败, 用直线", e);
        resolve(null);
      }
    });
  });
}

const toGcj = p => GCJ02.wgs84ToGcj02(p[0], p[1]);

/* 规划成功的断档补路回传服务端: 存进 app 自有库 (TeslaMate 原库只读不动),
   之后轨迹接口直接下发服务端拼好的连续轨迹, 前端不再重新规划。
   高德路线是 GCJ, 转回 WGS 上传; 端点 g.pts 本就是 WGS 采样点, 服务端按
   最近点锚定。回传失败无所谓 —— 下次播放这个断档还在, 会再规划再传。
   只回传单条轨迹; 合并轨迹的断档服务端已拼好, 根本走不到这里。 */
function postGapFill(it, g, route) {
  if (typeof it.id !== "number") return;
  fetch("/tesla/trips/api/gap_fill", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      drive_id: it.id,
      a: g.pts[0].slice(0, 2), b: g.pts[1].slice(0, 2),
      path: route.map(p => GCJ02.gcj02ToWgs84(p[0], p[1])),
    }),
  }).catch(() => {});
}

/* 断档补路的方向校验: 高德把断档端点吸附到对向车道时, 会规划出先朝反方向
   绕一大圈再回来的路 (实测 0.25km 的断档被规划成 3.6km 掉头环线, 起步方向
   与行驶方向差 176°)。判"病态": 绕行超直线 3 倍, 或起步方向背离断档前行
   驶方向 110° 以上。 */
function routeLooksWrong(route, g, pts, aIdx) {
  if (!route || route.length < 2) return true;
  const straight = TrackUtil.ptDistKm(g.pts[0], g.pts[1]);
  if (TrackUtil.cumDistKm(route)[route.length - 1] > straight * 3 + 0.15) return true;
  if (aIdx > 0) {
    const approach = TrackUtil.bearingDeg(pts[aIdx - 1], pts[aIdx]);
    const start = TrackUtil.bearingDeg(route[0], route[Math.min(2, route.length - 1)]);
    const diff = Math.abs(approach - start);
    if (Math.min(diff, 360 - diff) > 110) return true;
  }
  return false;
}

/* 病态路线的修正: 用断档前后各 3 个真实轨迹点做起终点重新规划 —— 起终点
   落在实际行驶的车道上, 不会吸附到对向; 再按最近点把结果裁剪回 a..b 段。 */
function routeGapCtx(pts, g, aIdx, bIdx) {
  const i0 = aIdx - 3, i1 = bIdx + 3;
  if (i0 < 0 || i1 >= pts.length) return Promise.resolve(null);   // 断档贴着轨迹首尾, 没有上下文
  const aG = toGcj(g.pts[0]), bG = toGcj(g.pts[1]);
  return routeBetween(toGcj(pts[i0]), toGcj(pts[i1])).then(ext => {
    if (!ext || ext.length < 2) return null;
    let s0 = 0, d0 = Infinity;                    // 先定位离 a 最近的点
    for (let i = 0; i < ext.length; i++) {
      const d = TrackUtil.ptDistKm(ext[i], aG);
      if (d < d0) { d0 = d; s0 = i; }
    }
    let s1 = s0, d1 = Infinity;                   // 再在 a 之后定位 b (顺序约束防裁剪坍缩)
    for (let i = s0; i < ext.length; i++) {
      const d = TrackUtil.ptDistKm(ext[i], bG);
      if (d < d1) { d1 = d; s1 = i; }
    }
    if (d0 > 0.15 || d1 > 0.15) return null;      // 延伸路线没贴着断档两端, 不可信
    /* 首尾用精确的断档端点, 中间只取两个最近点之间的路线点: 最近点本身
       可能落在端点后方几十米 (路线点稀疏), 带上会出现起步回头的小折返 */
    const slice = [aG, ...ext.slice(s0 + 1, s1), bG];
    if (TrackUtil.cumDistKm(slice)[slice.length - 1] > TrackUtil.ptDistKm(g.pts[0], g.pts[1]) * 3 + 0.15)
      return null;                                // 裁出来还是绕, 放弃
    return slice;
  });
}

/* 合并轨迹的分段断档识别: 每段单独跑单段行程同一套 splitGaps —— 各段
   下采样后采样密度差着量级 (短市区段步长几十米, 长途段公里级), 拼成
   一个数组用全局阈值会把整条长途段拆成孤立单点丢掉, 只剩几十条飞线。
   段与段之间的真实跳变交给 gapsBetween 按距离阈值正常补路。 */
function splitSegments(pts, starts) {
  if (!starts || !starts.length) return TrackUtil.splitGaps(pts);
  const segs = [];
  for (let k = 0; k < starts.length; k++) {
    const end = k + 1 < starts.length ? starts[k + 1] : pts.length;
    if (end > starts[k]) segs.push(...TrackUtil.splitGaps(pts.slice(starts[k], end)));
  }
  return segs.length ? segs : TrackUtil.splitGaps(pts);
}

/* 播放视角随车速缩放: 慢速拉近看细节, 高速拉远看全局。速度先过滑动窗取
   均值再喂曲线 —— 堵车走走停停时瞬时速度高频打摆, 直接喂视角跟着频繁
   拉近拉远, 看得人头晕。窗口开在播放时间轴上 (过去 2s + 预看 5s, 倍速下
   观感不漂移), 均值天然领先当前车速约 1.5s —— 减速刚起势视角就开始拉近,
   不等车停稳了才反应 (旧版墙钟回看 8s, 慢下来后还要拖好几秒才动)。
   窗口均值连续值 (46km/h 一档, 12.5~15.3 夹紧)
   目标档取整, 带 ±0.6 迟滞带 —— 档位边界的速度抖动 (等灯起步) 不至于来回
   打摆; 实际档位每帧指数缓动逼近目标 (帧率无关)。缓动必须自己做: AMap 的
   动画 setZoom 会被逐帧 setCenter 打成爬行 (实测 3s 只挪 0.1 档), 而立即档
   设小数是保真的 (逐帧 setCenter 下 set 14.12 → 读回 14.12)。用户接管见
   建图处的输入事件监听 —— 接管即视角锁定 (zoomUserLock), 换行程/重播都
   保持用户档位不再自动变焦, 播放条 +/- 基线按钮恢复自动。 */
let followZoomOn = false, followZoomCur = 0;    // 开关 / 目标档 (迟滞簿记)
let zoomUserLock = false, zoomUserZoom = 0;  // 手动视角锁定 + 用户档位 (页会话内)
let zoomShown = 0, zoomApplied = 0, zoomLastT = 0;   // 缓动值 / 已下发值 / 上帧时刻
let zoomBias = 0;   // 视角基线: 随速变焦整条曲线平移 (±2.5, 0.5 步进, localStorage 记住)
try {
  zoomBias = Math.max(-2.5, Math.min(2.5,
    Math.round((parseFloat(localStorage.getItem("trip-zoom-bias")) || 0) * 2) / 2));
} catch { /* 无痕模式等 localStorage 不可用 → 当 0 */ }
/* 滑动窗 (播放时间轴): 过去 ZOOM_PAST_MS + 预看 ZOOM_FUT_MS, 均匀
   ZOOM_SAMPLES 个采样点的插值车速取均值。窗口随播放位置现算、无状态
   —— 开播/拖进度天然干净, 不用重攒。 */
const ZOOM_PAST_MS = 2000, ZOOM_FUT_MS = 5000, ZOOM_SAMPLES = 8;
const speedZoom = v => Math.max(10.5, Math.min(18.5,
  Math.max(12.5, Math.min(15.3, 15.3 - v / 46)) + zoomBias));

/* 开播/重播: 视角中心与档位都直接到位, 开场不做缓动过渡 (只限最开始,
   之后速度档变化仍逐帧缓动)。档位取整 —— AMap 对小数档会在设置后
   1~2s 自动吸附到最近整数, 开场静止期最容易踩中。
   用户手动缩放过 (zoomUserLock) 则保持用户档位: 只把中心跟到新车头。 */
function zoomEaseStart(zoom) {
  if (zoomUserLock) {
    const z = Math.round(zoomUserZoom || tripMap.getZoom());
    followZoomOn = false;
    followZoomCur = z;
    tripMap.setZoom(z, true);
    zoomShown = zoomApplied = z;
    zoomLastT = performance.now();
    return;
  }
  zoom = Math.round(zoom);
  followZoomOn = true;
  followZoomCur = zoom;
  tripMap.setZoom(zoom, true);
  zoomShown = zoomApplied = zoom;
  zoomLastT = performance.now();
}

/* 视角基线加减: 整条慢近快远曲线跟着平移 (不动曲线形状)。手动缩放接管过
   (followZoomOn=false, 视角锁定) 时按它 = 恢复自动变焦 (锁定解除), 从当前
   档缓动到新目标。播放结束后按无效果 (缓动循环已停), 重播照常。 */
function bumpZoomBias(d) {
  const next = Math.max(-2.5, Math.min(2.5, Math.round((zoomBias + d) * 2) / 2));
  if (next === zoomBias) return;
  zoomBias = next;
  try { localStorage.setItem("trip-zoom-bias", String(zoomBias)); } catch { /* 同上 */ }
  $("#pb-zval").textContent = zoomBias > 0 ? `+${zoomBias}` : String(zoomBias);
  if (!followZoomOn) {
    followZoomOn = true;                     // 重新接管: 从当前档缓动到新目标
    zoomUserLock = false;                    // 手动锁定解除, 恢复随速变焦
    zoomShown = zoomApplied = tripMap.getZoom();
    zoomLastT = performance.now();
  }
  followZoomCur = Math.round(speedZoom(curSess ? curSess.lastV : 0));
}
$("#pb-zout").addEventListener("click", () => bumpZoomBias(-0.5));
$("#pb-zin").addEventListener("click", () => bumpZoomBias(0.5));
$("#pb-zval").textContent = zoomBias > 0 ? `+${zoomBias}` : String(zoomBias);

/* ---------- 矢量模式预载 (扫路) ---------- */
/* 栅格抄 URL 预热那套对矢量无效: 瓦片数据走 POST 鉴权 + 每次新签名的 URL,
   缓存又在地图实例内部 (隐藏第二张图拉过了也不认, dbg70 实测)。改在预载
   遮罩下把主图相机沿路线扫一遍 —— 引擎按视图拉瓦灌进 TileCache (500 条,
   一条走廊绰绰有余)。播放中的连续前瞻由环形前瞻容器负责 (见 CSS #trip-map),
   扫路只管开场到位 + 慢网兜底: 每步档位 = 播放同口径滑窗均速档
   (±0.6 迟滞带同款, 镜头自动拉远拉近都覆盖; 视角锁定时整条按用户档);
   开场档 (followZoom) 在起点补一步; 收尾补一步整轨拉远视野 (直跳, 动画
   式会被开播抢镜)。步距 ~85% 容器宽 (扩边后很宽, 视图并集连续覆盖走廊),
   400ms/步 (鉴权请求随视角变更即时发, 停留只为错开相邻访问), 上限 4s
   —— 城市行程 (z15 慢段步距 1.3km) 10km 内全走廊扫完, 更长的尾部交给
   环形前瞻, 不挡播放。 */
const VECTOR_PRELOAD_STEP_MS = 400, VECTOR_PRELOAD_CAP_MS = 4000,
      VECTOR_PRELOAD_STEP_FRAC = 0.85, VECTOR_PRELOAD_BRACKET_MS = 150;
/* 环形前瞻 (CSS #trip-map 四周扩边) 负责播放中的连续前瞻 (领先 4~13s),
   扫路只负责: 开场几秒 (视角/瓦片到位再起跑) + 沿途保险 (慢网兜底) +
   收尾整轨拉远。setFitView 的避让边距补上环宽, 整轨恰好收进可视区
   (finish() 与扫路收尾步共用)。注意 avoid 顺序是 [上,下,右,左] (引擎
   源码: 高=容器高−a[0]−a[1], 宽=容器宽−a[2]−a[3], 不对称还会平移中心),
   不是直觉的 [上,右,下,左]。 */
const MAP_RING_X = 160, MAP_RING_Y = 320;
const FIT_AVOID = [46 + MAP_RING_Y, 46 + MAP_RING_Y, 46 + MAP_RING_X, 46 + MAP_RING_X];

const pbToggle = $("#pb-toggle"), pbSeek = $("#pb-seek"), pbSpeed = $("#pb-speed"),
      pbRec = $("#pb-rec");
const PB_SPEEDS = [0.5, 1, 2, 4, 8];
const ICON_PLAY = '<svg viewBox="0 0 24 24" width="13" height="13"><path d="M7.5 4.6v14.8L20 12z" fill="currentColor"/></svg>';
const ICON_PAUSE = '<svg viewBox="0 0 24 24" width="13" height="13"><path d="M6.6 4.8h4.1v14.4H6.6zM13.3 4.8h4.1v14.4h-4.1z" fill="currentColor"/></svg>';
const ICON_REPLAY = '<svg viewBox="0 0 24 24" width="14" height="14"><path d="M12 5V1.8L7 6l5 4.2V7a5.5 5.5 0 1 1-5.5 5.5H4.5A7.5 7.5 0 1 0 12 5z" fill="currentColor"/></svg>';

/* 播放轨迹动画。more=true 表示轨迹还会通过 append 追加 (合并轨迹流式
   下载边下边播): 播到当前末尾时停在原地等数据, 全部到齐后调用方关掉 more。 */
/* 播放时长 (1× 基准, ms): 点数与里程取大, 3~300s。只看点数会亏待被下采样的
   超长轨迹 (260km 也被压到 12 秒放完, 根本看不清路), 里程分量让长途慢下来;
   系数 1.4s/km ≈ 镜头以 0.7km/s 扫过 —— 再快肉眼跟不上 (超长封顶 300s,
   嫌慢有倍速按钮)。矢量预载扫路也用它换算窗口时刻 (口径必须一致)。 */
const animDurMs = (n, km) => Math.min(Math.max(n / 300, 3 + km * 1.4), 300) * 1000;

function playTrack(pts, ts, it, zoom = 14, more = false) {
  stopAnim();
  if (curSess) curSess.alive = false;
  const gcj = p => GCJ02.wgs84ToGcj02(p[0], p[1]);
  const path = pts.map(gcj);                    // 全量坐标转换一次, 逐帧只切片
  let N = path.length;                          // 流式追加会变长
  const cum = TrackUtil.cumDistKm(pts);         // 播放中的实时里程
  /* 逐点能耗权重: 每公里 = 滚阻 + 风阻·v² (v 为 km/h), 全程定标到整体 kWh。
    没有逐点功耗数据, 播放中的动态电耗/平均电耗按它累积 —— 快段每公里
    贵一点, 停车不走就不耗, 收尾自然落回整体值 */
  const ekW = v => 1 + 3 * Math.pow(v / 100, 2);   // 每公里相对能耗
  const enerStep = i => (cum[i] - cum[i - 1])
    * ekW(((pts[i - 1][2] || 0) + (pts[i][2] || 0)) / 2);
  const ecum = [0];                              // 播放中的实时 (模型) 能耗
  for (let i = 1; i < pts.length; i++) ecum.push(ecum[i - 1] + enerStep(i));
  const vt = TrackUtil.animTimes(pts, ts);      // 播放节拍: 每点累计行驶秒
  let dur = animDurMs(N, cum[N - 1]);
  let growStep = Math.max(1, Math.floor(N / 200));   // 白线分块生长: 每帧全量重建太卡

  // 背景全程速度线 (淡) —— 拉远后就是完整的速度色全局图
  // 合并轨迹按段识别断档 (见 splitSegments), 单段照旧全局一套
  const speedLineOverlays = slice => TrackUtil.speedLines(slice).map(b => new AMap.Polyline({
    path: b.pts.map(p => GCJ02.wgs84ToGcj02(p[0], p[1])),
    strokeColor: b.color, strokeOpacity: 0.28, strokeWeight: 4,
    // 换色处两段共享端点, 但 lineCap 默认 butt 在转角各留一个楔形缺口
    // (定格后的速度色轨迹一节节断开) —— 圆头端帽补上, 段间无缝
    lineJoin: "round", lineCap: "round", zIndex: 50,
  }));
  const segs = splitSegments(pts, it.seg_starts);
  const bgLines = [];
  for (const seg of segs) bgLines.push(...speedLineOverlays(seg));
  const allLines = [...bgLines];   // 断档虚线随时加进来 (见 addGap), 收尾拉远用
  tripMap.add(bgLines);

  const progress = new AMap.Polyline({
    path: [path[0]], strokeColor: "#f5f5f7", strokeWeight: 4.5,
    lineJoin: "round", lineCap: "round", zIndex: 80,
  });
  const head = new AMap.CircleMarker({
    center: path[0], radius: 7, strokeColor: "#fff", strokeWeight: 2.5,
    fillColor: "#e5484d", fillOpacity: 1, zIndex: 100,
  });
  tripMap.add([progress, head]);

  /* 播放中: 里程/时长/车速/功耗实时跳动; 收尾停在整体值, 标签换回整体口径 */
  $("#sh-spd-lb").textContent = "车速";
  $("#sh-pw-lb").textContent = "功耗";
  // 这辆车的 API 上报的 power 常年 ~0 (实测全库 -94~254W, 真开车至少上万瓦),
  // 只有出现真实量级的数据才亮出功耗格, 不然一直显示 0.0kW 像是坏了
  let hasPower = pts.some(p => Math.abs(p[3] || 0) > 500);   // 追加段可能点亮
  $("#sh-cell-pw").hidden = !hasPower;          // 没有可用的功耗数据就不占格子
  const setLive = (idx, frac) => {              // frac: 该步内进度 (断档中也在走)
    const last = idx + 1 >= N;
    const stepKm = last ? 0 : cum[idx + 1] - cum[idx];
    const va = pts[idx][2] || 0, vb = last ? va : (pts[idx + 1][2] || 0);
    const v = va + (vb - va) * frac;            // 车速两端线性插值 (断档推算模型)
    $("#sh-km").innerHTML = '<span class="n">' + (cum[idx] + stepKm * frac).toFixed(1) + "</span><small>km</small>";
    /* 总电耗/平均电耗按能耗模型随轨迹累积 (快段每公里贵, 停车不耗),
       收尾 setOfficial 定格回整体值 */
    if (it.kwh != null && ecum[N - 1] > 0) {
      const eNow = last ? ecum[N - 1] : ecum[idx] + (ecum[idx + 1] - ecum[idx]) * frac;
      const kwhNow = it.kwh * eNow / ecum[N - 1];
      $("#sh-kwh").innerHTML = '<span class="n">' + num(kwhNow) + "</span><small>kWh</small>";
      const kmNow = cum[idx] + stepKm * frac;
      if (it.wh_per_km != null && kmNow > 0)
        $("#sh-avg").innerHTML = '<span class="n">' + num(kwhNow / kmNow * 1000, 0) + "</span><small>Wh/km</small>";
    }
    const ta = ts[idx] || 0, tb = last ? ta : (ts[idx + 1] || ta);
    $("#sh-dur").innerHTML = '<span class="n">' + fmtDurLive(ta + (tb - ta) * frac) + "</span>";
    $("#sh-spd").innerHTML = '<span class="n">' + Math.round(v) + "</span><small>km/h</small>";
    const pa = pts[idx][3], pb = last ? pa : pts[idx + 1][3];   // W: 正=放电 负=回收
    const pw = pa == null && pb == null ? null :
      pa == null ? pb : pb == null ? pa : pa + (pb - pa) * frac;
    $("#sh-pw").innerHTML = '<span class="n">' + (pw == null ? "—" :
      (pw / 1000).toFixed(1).replace(/\.0$/, "")) + "</span><small>kW</small>";
  };
  const setOfficial = () => {
    $("#sh-km").innerHTML = '<span class="n">' + num(it.km) + "</span><small>km</small>";
    if (it.kwh != null) $("#sh-kwh").innerHTML = '<span class="n">' + num(it.kwh) + "</span><small>kWh</small>";
    if (it.wh_per_km != null)
      $("#sh-avg").innerHTML = '<span class="n">' + num(it.wh_per_km, 0) + "</span><small>Wh/km</small>";
    $("#sh-dur").innerHTML = '<span class="n">' + fmtDur(it.min) + "</span>";
    $("#sh-spd-lb").textContent = "最高车速";
    $("#sh-spd").innerHTML = '<span class="n">' + (it.speed_max != null ? it.speed_max : "—") + "</span><small>km/h</small>";
    $("#sh-pw-lb").textContent = "平均功耗";
    const mp = hasPower ? TrackUtil.meanPowerW(pts, ts) : null;
    $("#sh-pw").innerHTML = '<span class="n">' + (mp == null ? "—" :
      (mp / 1000).toFixed(1).replace(/\.0$/, "")) + "</span><small>kW</small>";
  };

  const splices = [];   // 已解析的断档路由 [{aIdx, bIdx, route, rcum}] 按 aIdx 升序

  /* 断档步的头部位置: 有道路路径沿道路走 (rcum 是它的累计里程), 没有则
     两端直线插值 —— 车按插值速度驶过, 不瞬移到对岸。 */
  function headPos(idx, frac) {
    const sp = splices.find(g => g.aIdx === idx);
    if (sp) return TrackUtil.pathPointAt(sp.route, sp.rcum, frac);
    const a = path[idx], b = path[idx + 1];
    return b ? [a[0] + (b[0] - a[0]) * frac, a[1] + (b[1] - a[1]) * frac] : a;
  }
  /* 断档步内白线跟着头部往对岸长: 道路路径从头到当前进度处的一段 */
  function routePrefix(sp, frac) {
    const q = frac * sp.rcum[sp.rcum.length - 1];
    let i = 0;
    while (i < sp.route.length && sp.rcum[i] < q) i++;
    return sp.route.slice(0, i).concat([headPos(sp.aIdx, frac)]);
  }

  const s = {
    pts, N, dur, vt, playT: 0, speed: 1, paused: false, seeking: false,
    finished: false, alive: true, lastIdx: -1, lastFrac: -1, drawn: 0,
    lineBase: null, gapDrawAt: 0,   // 白线末次重建快照 / 断档步内延伸节流
    more, waiting: false, lastV: 0,   // more/waiting: 流式状态; lastV: 当前车速
    /* 随速变焦缓动: 每帧推进 (暂停也要把当前滑变走完, 不然卡在半路) */
    zoomTick() {
      if (!followZoomOn) return;              // 手动缩放即停 (锁定, 见 zoomUserLock)
      // dt 用 performance.now() 差 (不回退), 上限 500ms: 低帧率下钳 100ms
      // 会把缓动拖成爬行 (测试容器 ~2.5fps 实测), 真机 60fps 则恒为步进
      const now = performance.now();
      const dt = Math.min(Math.max(now - zoomLastT, 0), 500);
      zoomLastT = now;
      // 滑窗均值 (播放时间轴, 过去2s+预看5s): 领先当前车速 ~1.5s, 减速
      // 刚起势就开始拉近; animAt 自带钳制, 窗口两端出界取首/尾车速
      let vSum = 0;
      for (let k = 0; k < ZOOM_SAMPLES; k++) {
        const t = s.playT - ZOOM_PAST_MS
          + (ZOOM_PAST_MS + ZOOM_FUT_MS) * k / (ZOOM_SAMPLES - 1);
        const p = TrackUtil.animAt(vt, t, dur);
        const va = pts[p.idx][2] || 0,
              vb = p.idx + 1 < N ? (pts[p.idx + 1][2] || 0) : va;
        vSum += va + (vb - va) * p.frac;
      }
      const zt = speedZoom(vSum / ZOOM_SAMPLES);   // 慢速拉近 / 高速拉远
      if (Math.abs(zt - followZoomCur) > 0.6)   // 出迟滞带才换目标档
        followZoomCur = Math.round(zt);
      // 指数趋近 + 速率上限 (1.5 档/s): 低帧率下单帧也不会跳档 (纯指数在
      // 2.5fps 下一帧能挪半档), 高帧率下恒为平滑缓动
      const step = (followZoomCur - zoomShown) * (1 - Math.exp(-dt / 600));
      const cap = 1.5 * dt / 1000;
      zoomShown += Math.max(-cap, Math.min(cap, step));
      if (Math.abs(followZoomCur - zoomShown) < 0.01) zoomShown = followZoomCur;
      if (Math.abs(zoomShown - zoomApplied) > 0.005) {   // 值变了才下发
        zoomApplied = zoomShown;
        tripMap.setZoom(zoomShown, true);
      }
    },
    apply(idx, frac = 0) {       // 播放头落到 idx 步内 frac 进度 (拖进度条也走这里)
      if (idx === s.lastIdx && frac === s.lastFrac) return;
      const idxNew = idx !== s.lastIdx;
      s.lastIdx = idx; s.lastFrac = frac;
      const pos = headPos(idx, frac);          // 断档步沿道路/直线插值走过去
      const va = pts[idx][2] || 0, vb = idx + 1 < N ? (pts[idx + 1][2] || 0) : va;
      const v = va + (vb - va) * frac;         // 断档中车速两端线性插值
      head.setCenter(pos);
      head.setOptions({ fillColor: TrackUtil.SPEED_COLORS[TrackUtil.speedBucket(v)] });
      tripMap.setCenter(pos, true);            // 视角紧贴头部 (immediately=不排队动画)
      s.lastV = v;                             // 当前车速 (视角基线按钮重锚用)
      if (idxNew) {
        if (idx < s.drawn) s.drawn = 0;         // 拖进度条回退: 白线从头重建
        if (idx - s.drawn >= growStep || idx === N - 1) {
          s.drawn = idx;
          // 断档跳变段替换成道路路径后, 白线也跟着沿道路走
          s.lineBase = TrackUtil.splicePath(path, splices, idx);
          progress.setPath(s.lineBase);
        }
      } else if (frac > 0 && cum[idx + 1] - cum[idx] >= TrackUtil.MIN_GAP_KM) {
        // 断档步内推进: 白线跟着头部往对岸长 (有道路沿道路), 节流 ~8fps
        if (Date.now() - s.gapDrawAt > 120) {
          s.gapDrawAt = Date.now();
          const sp = splices.find(g => g.aIdx === idx);
          progress.setPath(TrackUtil.splicePath(path, splices, idx)
            .concat(sp ? routePrefix(sp, frac) : [pos]));
        }
      }
      setLive(idx, frac);
    },
    seek(frac) {                // 0..1: 拖进度条/外部跳转统一入口, 立即生效
      s.playT = Math.min(Math.max(frac, 0), 1) * dur;
      const p = TrackUtil.animAt(vt, s.playT, dur);   // 滑窗无状态, 跳完即就位
      s.apply(p.idx, p.frac);
    },
    /* 流式追加一段 (见 loadMergedStream): 索引只增不改, 速度线/断档/里程
       全部延伸; 播放头按当前 idx 重新锚定, 避免按新总量比例重算导致倒跳 */
    append(segPts, segTs) {
      if (!s.alive || s.finished || !segPts.length) return;
      const startIdx = pts.length;
      for (const p of segPts) { pts.push(p); path.push(gcj(p)); }
      for (const t of segTs) ts.push(t);
      for (let i = startIdx; i < pts.length; i++)
        cum.push(cum[i - 1] + TrackUtil.ptDistKm(pts[i - 1], pts[i]));
      for (let i = startIdx; i < pts.length; i++)
        ecum.push(ecum[i - 1] + enerStep(i));
      for (let i = startIdx; i < pts.length; i++)   // 节拍同步延伸 (含段间边界步)
        vt.push(vt[i - 1] + TrackUtil.animStepSec(pts[i - 1], pts[i],
                 ts.length >= pts.length ? Math.max(0, ts[i] - ts[i - 1]) : 1));
      N = pts.length;
      dur = animDurMs(N, cum[N - 1]);
      growStep = Math.max(1, Math.floor(N / 200));
      s.dur = dur; s.N = N;             // 进度条 seek 用的是对象上的快照
      // 新段速度线 + 段内断档 (段内补路服务端已拼好, 这里只剩稀疏采样断档)
      const segSegs = TrackUtil.splitGaps(segPts);
      for (const seg of segSegs) {
        const lines = speedLineOverlays(seg);
        bgLines.push(...lines);
        allLines.push(...lines);
        tripMap.add(lines);
      }
      for (const g of TrackUtil.gapsBetween(segSegs))
        addGap(g, startIdx + segPts.indexOf(g.pts[0]),
               startIdx + segPts.indexOf(g.pts[1]));
      // 段间边界 (上一段尾 → 本段头, 停车挪位): 距离阈值同 gapsBetween
      for (const g of TrackUtil.gapsBetween([[pts[startIdx - 1]], segPts]))
        addGap(g, startIdx - 1, startIdx);
      // 新段可能带来真实量级的功耗数据
      if (!hasPower && segPts.some(p => Math.abs(p[3] || 0) > 500)) {
        hasPower = true;
        $("#sh-cell-pw").hidden = false;
      }
      if (s.waiting) { s.waiting = false; tripMsg(null, false); }
      // 播放头按行驶秒比例重锚 (不是下标比例), 头部在屏幕上原地不动
      if (s.lastIdx >= 0) s.playT = vt[N - 1] > 0 ? dur * vt[s.lastIdx] / vt[N - 1] : 0;
    },
    /* 收尾: 停表+拉远, 但控制条留着 (重播/拖进度仍可用);
       stopAnim 只在关弹层/换轨迹时调用。 */
    finish() {
      if (s.finished) return;
      s.finished = true;
      if (animRaf) cancelAnimationFrame(animRaf);
      animRaf = 0;
      releaseScreenAwake();               // 播完收尾, 允许熄屏
      tripMsg(null, false);
      followZoomOn = false;              // 播放结束, 随速变焦停用 (重播恢复)
      tripMap.remove([progress, head]);
      allLines.forEach(l => l.setOptions({ strokeOpacity: 1 }));  // 淡线变亮
      tripMap.setFitView(allLines, false, FIT_AVOID);      // 拉远 → 全局视角 (避让补环宽, 整轨收进可视区)
      setOfficial();
      pbToggle.innerHTML = ICON_REPLAY;
      pbToggle.setAttribute("aria-label", "重播");
      pbSeek.value = 1000;
      pbSeek.style.setProperty("--pb", "100%");
      if (rec) {   // 导出中: 拉远定格入镜后自动收片 (期间重开录制则别误杀)
        const r = rec;
        setTimeout(() => { if (rec === r) stopRecExport(false); }, 1200);
      }
    },
    replay() {                   // 重播: 从头再放 (播完点按钮 / 播完拖进度都会走这)
      if (!s.finished) return;
      s.finished = false;
      s.playT = 0; s.paused = false; s.lastIdx = -1; s.lastFrac = -1; s.drawn = 0;
      s.waiting = false; s.lineBase = null;
      allLines.forEach(l => l.setOptions({ strokeOpacity: 0.28 }));
      progress.setPath([path[0]]);
      head.setCenter(path[0]);
      head.setOptions({ fillColor: TrackUtil.SPEED_COLORS[TrackUtil.speedBucket(pts[0][2] || 0)] });
      tripMap.add([progress, head]);
      tripMap.setCenter(path[0], true);        // 中心与档位都直接到位 (开场不缓动)
      zoomEaseStart(zoom);
      $("#sh-spd-lb").textContent = "车速";
      $("#sh-pw-lb").textContent = "功耗";
      resetPlaybar();
      holdScreenAwake();                  // 重播继续保活
      frameLoop();
    },
    restart() {             // 导出视频要整段: 播放中/暂停中也从头重放
      if (!s.finished) {    // replay 只认播完 —— 强过门槛, 且跳过 finish 的拉远定格
        if (animRaf) cancelAnimationFrame(animRaf);   // 停旧帧循环 (replay 再起新的, 别双跑)
        animRaf = 0;
        s.finished = true;
      }
      s.replay();
    },
  };
  anim = s;
  curSess = s;
  /* GPS 断档处 (隧道/信号丢失) 没有真实采样: 蓝色虚线沿真实道路连接,
     先画直线占位, 规划路径回来后整段替换; 规划成功的还会回传服务端存档
     (存自有库, 之后服务端直接下发拼好的连续轨迹)。 */
  function addGap(g, aIdx, bIdx) {
    const line = new AMap.Polyline({
      path: g.pts.map(gcj), strokeColor: "#3987e5", strokeOpacity: 0.28,
      strokeWeight: 4, strokeStyle: "dashed", strokeDasharray: [8, 8],
      // 圆头端帽: 虚线与两侧实线在断档岸边转角处衔接无缝 (同速度色线)
      lineJoin: "round", lineCap: "round", zIndex: 50,
    });
    allLines.push(line);
    tripMap.add(line);
    // 断档路径规划: 缓存命中立即换成道路线, 否则请求回来后替换 (失败保持直线);
    // 规划病态 (吸附到对向车道绕回头路) 时改用上下文重规划 (同样有缓存)
    const key = `${it.id}:${aIdx}-${bIdx}`, ctxKey = key + ":ctx";
    const applyRoute = route => {
      if (!s.alive || !route || route.length < 2) return;
      line.setPath(route);
      splices.push({ aIdx, bIdx, route, rcum: TrackUtil.cumDistKm(route) });
      splices.sort((x, y) => x.aIdx - y.aIdx);
      s.drawn = 0;      // 白线下帧重建: 跳变段改为沿道路
      postGapFill(it, g, route);   // 规划成功 → 回传存档 (只单条; 合并的服务端已拼好)
    };
    const settle = plain => {
      if (!routeLooksWrong(plain, g, pts, aIdx)) return applyRoute(plain);
      const hit = routeCache.get(ctxKey);
      if (hit) return applyRoute(hit);
      routeGapCtx(pts, g, aIdx, bIdx).then(r => {
        if (r) { routeCache.set(ctxKey, r); return applyRoute(r); }
        /* 失败重试一次: ctx 请求紧跟 3 个常规请求, 高德规划接口偶发限流 */
        setTimeout(() => {
          routeGapCtx(pts, g, aIdx, bIdx).then(r2 => {
            if (!r2) return;   // 两次都失败: 保持直线弦。绝不能放行已知病态的
                               // plain —— 1385 曾把 0.5km 隧道断档画成 37km 掉头环线
            routeCache.set(ctxKey, r2);
            applyRoute(r2);
          });
        }, 900);
      });
    };
    const hit = routeCache.get(key);
    if (hit) settle(hit);
    else routeBetween(gcj(g.pts[0]), gcj(g.pts[1]))
      .then(r => { if (r) routeCache.set(key, r); settle(r); });
  }

  function resetPlaybar() {
    pbSeek.value = 0;
    pbSeek.style.setProperty("--pb", "0%");
    pbToggle.innerHTML = ICON_PAUSE;
    pbToggle.setAttribute("aria-label", "暂停");
    $("#playbar").hidden = false;
  }
  function frameLoop() {
    let lastNow = 0;
    (function frame(now) {
      if (anim !== s || s.finished) return;    // 会话已停止/替换, 或已收尾
      // 帧间隔钳制 [0, 100ms]: Chrome 的 rAF 时间戳可能比上一帧还早 (见
      // trackutil.animAt 注释); 切后台回来会有超大间隔 —— 都不该让播放头跳跃
      const dt = Math.max(0, Math.min(now - lastNow, 100));
      lastNow = now;
      if (!s.paused && !s.seeking)
        s.playT = Math.min(s.playT + dt * s.speed, dur);
      const p = TrackUtil.animAt(vt, s.playT, dur);   // 按行驶秒 → 步 + 步内进度
      s.apply(p.idx, p.frac);
      s.zoomTick();                           // 随速变焦缓动 (暂停也推进)
      pbSeek.value = Math.round(s.playT / dur * 1000);
      pbSeek.style.setProperty("--pb", (s.playT / dur * 100).toFixed(1) + "%");
      if (s.playT >= dur) {
        if (!s.more) { s.finish(); return; }   // 播完自动收尾 (控制条留着重播)
        if (!s.waiting) {                      // 流式还没下完: 停在末尾等追加
          s.waiting = true;
          tripMsg("等待后续轨迹…", true);
        }
      }
      animRaf = requestAnimationFrame(frame);
    })(performance.now());
  }

  for (const g of TrackUtil.gapsBetween(segs))
    addGap(g, pts.indexOf(g.pts[0]), pts.indexOf(g.pts[1]));

  resetPlaybar();
  pbSpeed.textContent = "1×";
  tripMap.setCenter(path[0], true);            // 中心与档位都直接到位 (开场不缓动)
  zoomEaseStart(zoom);
  holdScreenAwake();                           // 开播保活 (禁止熄屏)
  frameLoop();
  return s;
}

/* ---------- 播放前预载沿途瓦片 ----------
   跟随播放时瓦片按需拉取, 长途一路白屏补图。先用 Image() 把沿途瓦片刷进
   HTTP 缓存 (与地图自身请求同 URL 直接命中); 高德若是矢量渲染 (DOM 里没有
   瓦片 img) 抄不到模板, 或瓦片请求超时, 都静默跳过, 照常播放。 */
const TILE_HOSTS = ["webrd01", "webrd02", "webrd03", "webrd04"];

/* 跟随倍率按里程: 260km 的路线跟 15 级视口基本"没在动", 放到 12 级看得出走线。
   基线平移同步生效 (预载瓦片的倍率跟实际开播档一致) */
function followZoom(km) {
  return Math.max(10.5, Math.min(18.5,
    (km < 20 ? 14 : km < 80 ? 13 : km < 200 ? 12 : 11) + zoomBias));
}

/* 从地图 DOM 抄一张真实瓦片 URL 当模板 (lang/style/scale 跟实际渲染走, 高德改版不用跟)。
   首次建图时初始瓦片还没进 DOM, 轮询等一小会儿; 矢量渲染是 canvas 没有瓦片
   img (请求走另一套接口), 预载无意义 → 放弃, 不浪费请求。
   抄到一次就缓存 (流式逐段预载共用, 风格/倍率不会变)。 */
let tileTplCache = null;
async function tileTemplate() {
  if (tileTplCache) return tileTplCache;
  for (let i = 0; i < 12; i++) {
    const img = document.querySelector("#trip-map img[src*='appmaptile']");
    if (img) return tileTplCache = img.src;
    if (document.querySelector("#trip-map canvas")) return null;
    await new Promise(r => setTimeout(r, 250));
  }
  return null;
}

function tileUrl(tpl, x, y, z) {
  return tpl
    .replace(/([?&]x=)\d+/, "$1" + x)
    .replace(/([?&]y=)\d+/, "$1" + y)
    .replace(/([?&]z=)\d+/, "$1" + z)
    .replace(/webrd0\d/, TILE_HOSTS[(x + y) % 4]);   // 轮换子域, 不打爆单台
}

/* 沿途每点的头瓦片 ±1 圈 (跟随视口约 2×3 张), 去重后上限 360 张 */
function preloadTiles(pts, z, tpl, onProgress) {
  const tiles = new Set();
  const step = Math.max(1, Math.floor(pts.length / 1500));
  for (let i = 0; i < pts.length; i += step) {
    const g = toGcj(pts[i]);
    const t = TrackUtil.lngLatToTile(g[0], g[1], z);
    for (let dx = -1; dx <= 1; dx++)
      for (let dy = -1; dy <= 1; dy++) tiles.add((t[0] + dx) + "," + (t[1] + dy));
  }
  const urls = [...tiles].slice(0, 360).map(k => {
    const [x, y] = k.split(",").map(Number);
    return tileUrl(tpl, x, y, z);
  });
  if (!urls.length) return Promise.resolve();
  let done = 0;
  return new Promise(resolve => {
    const timer = setTimeout(resolve, 8000);   // 最多等 8s, 没到的照常按需补
    const tick = () => {
      done++;
      onProgress(Math.round(done / urls.length * 100));
      if (done >= urls.length) { clearTimeout(timer); resolve(); }
    };
    urls.forEach(u => { const im = new Image(); im.onload = im.onerror = tick; im.src = u; });
  });
}

async function preloadVectorTrack(pts, ts, openZoom, onProgress, seq) {
  const N = pts.length;
  if (N < 2 || !tripMap) return;
  let cv = null;   // 首次建图 WebGL 就绪有延迟 (流式路径没等过): 轮询一小会儿
  for (let i = 0; i < 6 && !(cv = document.querySelector("#trip-map canvas")); i++)
    await new Promise(r => setTimeout(r, 250));
  if (!cv) return;   // 栅格 (有自己的抄 URL 预载) 或未就绪: 放弃, 播放照常
  const vt = TrackUtil.animTimes(pts, ts);
  const vtTotal = vt[vt.length - 1] || 0;
  if (vtTotal <= 0) return;
  const cum = TrackUtil.cumDistKm(pts);
  const dur = animDurMs(N, cum[N - 1]);
  /* 该点处播放会用的档位: 与 zoomTick 同口径 (过去2s+预看5s 滑窗均速);
     视角锁定时播放全程一个档, 扫路也整条按用户档 */
  let hystZoom = Math.round(openZoom);   // 迟滞状态机初值 = 开场档 (zoomTick 同款)
  /* 曲线档 (无迟滞): 播放缓动的终点原料, 也是跨界预取的目标档 */
  const curveZoomAt = i => {
    if (zoomUserLock) return Math.round(zoomUserZoom || tripMap.getZoom());
    const t = dur * vt[i] / vtTotal;
    let vSum = 0;
    for (let k = 0; k < ZOOM_SAMPLES; k++) {
      const tw = t - ZOOM_PAST_MS
        + (ZOOM_PAST_MS + ZOOM_FUT_MS) * k / (ZOOM_SAMPLES - 1);
      const p = TrackUtil.animAt(vt, tw, dur);
      const va = pts[p.idx][2] || 0,
            vb = p.idx + 1 < N ? pts[p.idx + 1][2] || 0 : va;
      vSum += va + (vb - va) * p.frac;
    }
    return speedZoom(vSum / ZOOM_SAMPLES);
  };
  const zoomAt = i => {   // 迟滞档 (zoomTick 同款 ±0.6 带: 纯 round 会在档位
    const zt = curveZoomAt(i);   // 边界与播放分道, 过渡带的瓦片谁都没拉过)
    if (Math.abs(zt - hystZoom) > 0.6) hystZoom = Math.round(zt);
    return hystZoom;
  };
  const alive = () => seq === openSeq;
  const dwell = () => new Promise(r => setTimeout(r, VECTOR_PRELOAD_STEP_MS));
  const visit = async (z, p) => {
    tripMap.setZoomAndCenter(z, p, true);
    await dwell();
  };
  /* 跨界预取: 矢量瓦片只在偶数档取数 (dbg83 实测全程只有 z10/12/14), 播放
     缓动跨过档位边界那刻要整层换瓦片 —— 新档没缓存时底图拿旧档数据兜底,
     地名却要等新档数据到 (真机上 = 变焦时文字消失)。迟滞端着旧档、曲线已
     漂向新档的过渡步, 把曲线档也顺带扫一眼 (瓦片请求随相机事件即发, 不等
     渲染, 短驻留就够), 翻转点两侧两带瓦片都提前在手 */
  const visitBracket = async (z, p) => {
    tripMap.setZoomAndCenter(z, p, true);
    await new Promise(r => setTimeout(r, VECTOR_PRELOAD_BRACKET_MS));
  };
  const mapW = document.getElementById("trip-map").clientWidth || 390;
  const t0 = performance.now();
  await visit(Math.round(openZoom), toGcj(pts[0]));   // 开场档先到位 (zoomEaseStart 同款)
  if (alive()) onProgress(5);
  let idx = 0, km = 0;
  while (idx < N - 1 && performance.now() - t0 < VECTOR_PRELOAD_CAP_MS && alive()) {
    await visit(zoomAt(idx), toGcj(pts[idx]));
    const zTarget = Math.round(curveZoomAt(idx));   // 曲线正漂向的档
    if (zTarget !== hystZoom) await visitBracket(zTarget, toGcj(pts[idx]));
    if (!alive()) return;
    onProgress(Math.min(95, 5 + Math.round(km / (cum[N - 1] || 1) * 90)));   // 单调 5→95
    let mpp = 200;   // 米/px 回落值: 步距偏大 = 少扫几步, 不致命
    try { mpp = tripMap.getResolution() || 200; } catch { /* 老版本缺这个接口 */ }
    km += VECTOR_PRELOAD_STEP_FRAC * mapW * mpp / 1000;   // 步距 ~85% 容器宽
    while (idx < N - 1 && cum[idx] < km) idx++;
  }
  /* 收尾一步: 整轨拉远视野 (finish() 同款避让边距, 补环宽), 定格时
     整张全局图的数据也已在手。隐形折线只为供出范围, 用完即删 */
  if (alive()) {
    const stride = Math.max(1, Math.floor(N / 4000));
    const path = [];
    for (let i = 0; i < N; i += stride) path.push(toGcj(pts[i]));
    const whole = new AMap.Polyline({ path, strokeOpacity: 0, zIndex: 1 });
    tripMap.add(whole);
    /* 直跳 (immediately): 动画式会被紧随的开播抢镜, 收尾档瓦片 (含
       contain_range 低层父级) 拉不满, 播完拉远时还得现场补 */
    tripMap.setFitView([whole], true, FIT_AVOID);
    await dwell();
    tripMap.remove(whole);
    onProgress(100);
  }
}

/* ---------- 地址栏深链: 打开变 /tesla/trips?id=X 或 ?ids=a,b, 方便分享/回退 ---------- */
/* listURL(): 筛选参数 + 行程深链 共同组成地址栏 (时间菜单/筛选行/深链共用) */
function urlTripKey() {
  /* ids= 逗号串经分享渠道常被再编码成 %2C (微信/备忘录都会), 先解一遍再配 */
  const m = /[?&](?:id|ids)=([\d,%-]+)/.exec(location.search);
  return m ? decodeURIComponent(m[1]) : null;
}

async function openByKey(key) {
  /* 分享直开 / 后退再前进: 手里没有卡片数据, 单条走单条接口, 合并走合并
     接口 (404 → 抹掉参数)。合并键两种形式: "首-尾" (现行) / 逗号 (旧链) */
  try {
    if (/[-,]/.test(key)) await openMerged(key, true);   // 必须 await: 流式失败要
    else openTrip(await getJSON(`/tesla/trips/api/sessions/${key}`), true);  // rethrow 到这抹参
  } catch (e) {
    hideSheet();
    history.replaceState(null, "", listURL());   // 坏链接 → 抹掉行程参数, 保留筛选
  }
}

function hideSheet() {
  stopAnim();
  if (curSess) { curSess.alive = false; curSess = null; }
  $("#sheet").classList.remove("show");
  $("#backdrop").classList.remove("show");
  $("#sh-drv").hidden = true;
  sheetTrip = null;
}

/* 分组页跳来的深链 (?ids=): 关弹层要回分组页。referrer 是整页导航留下的,
   页内后续 push/replace 不影响它; 直开的分享链没有这个 referrer, 照旧抹参。 */
const cameFromGroups = document.referrer.endsWith("/tesla/groups");

function closeTrip() {
  const key = curKey;
  hideSheet();
  curKey = null;
  if (key == null) return;
  if (history.state && history.state.k === key)
    history.back();   // 弹层是本页推入的 → 回退 (popstate 会再走一遍 hideSheet, 无害)
  else if (urlTripKey() != null) {
    if (cameFromGroups) { history.back(); return; }    // 分组页跳来 → 回分组页
    history.replaceState(null, "", listURL());         // 分享直开 → 只抹行程参数
  }
}

/* 弹层头部汇总 (日期/时长/里程/最高速/功耗): 单条来自卡片数据, 合并来自
   流式首行或整包缓存; 合并数据没到时先用占位, 到了再填 */
function fillSheetHeader(it) {
  if (it.merged) {    // 合并多段: 跨天给日期区间, 同天照常; 时间列前缀段数
    const d1 = parseLocal(it.start), d2 = parseLocal(it.end);
    $("#sh-date").textContent = d1.toDateString() === d2.toDateString()
      ? fmtCardDate(it.start).replace(/ \d\d:\d\d$/, "")
      : (d1.getMonth() + 1) + "月" + d1.getDate() + "日 – " + (d2.getMonth() + 1) + "月" + d2.getDate() + "日";
    $("#sh-time").textContent = it.n + " 段行程 · " + fmtTime(it.start) + " – " + fmtTime(it.end);
  } else {
    $("#sh-date").textContent = fmtCardDate(it.start).replace(/ \d\d:\d\d$/, "");
    $("#sh-time").textContent = (it.end ? fmtTime(it.start) + " – " + fmtTime(it.end) : "");
  }
  $("#sh-km").innerHTML = '<span class="n">' + num(it.km) + "</span><small>km</small>";
  $("#sh-dur").innerHTML = '<span class="n">' + fmtDur(it.min) + "</span>";
  $("#sh-spd-lb").textContent = "最高车速";
  $("#sh-spd").innerHTML = '<span class="n">' + (it.speed_max != null ? it.speed_max : "—") + "</span><small>km/h</small>";
  $("#sh-cell-kwh").hidden = it.kwh == null;
  $("#sh-kwh").innerHTML = it.kwh == null ? "—" : '<span class="n">' + num(it.kwh) + "</span><small>kWh</small>";
  $("#sh-cell-avg").hidden = it.wh_per_km == null;
  $("#sh-avg").innerHTML = it.wh_per_km == null
    ? "—" : '<span class="n">' + num(it.wh_per_km, 0) + "</span><small>Wh/km</small>";
  $("#sh-pw-lb").textContent = "平均功耗";
  $("#sh-pw").textContent = "—";
}

/* 合并数据在路上: 弹层先开 (阻断其他操作), 头部占位 */
function fillSheetHeaderPending() {
  $("#sh-date").textContent = "连续轨迹";
  $("#sh-time").textContent = "正在下载…";
  $("#sh-km").textContent = "—";
  $("#sh-dur").textContent = "—";
  $("#sh-spd").textContent = "—";
  $("#sh-cell-kwh").hidden = true;
  $("#sh-cell-avg").hidden = true;
  $("#sh-pw").textContent = "—";
}

/* ---------- 弹层驾驶员标注: 未标 = 默认驾驶员兜底, 没配驾驶员整行不显示 ---------- */
async function setupDriverPicker(it, seq) {
  const pick = $("#sh-drv-pick");
  pick.hidden = true;                             // 先藏, 数据到位再亮
  if (!it.merged) {                               // 合并多段: 驾驶员标注不适用
    if (driversCache === undefined) {
      try { driversCache = await getJSON("/tesla/api/drivers"); }
      catch { driversCache = null; }
    }
    if (seq !== openSeq) return;                  // 弹层已切走, 结果作废
    if (driversCache && driversCache.length > 0) {
      const def = driversCache.find(d => d.is_default);
      $("#sh-drv-sel").innerHTML =
        `<option value="">${def ? `未指定 · 默认${esc(def.name)}` : "未指定"}</option>` +
        driversCache.map(d => `<option value="${d.id}">${esc(d.name)}</option>`).join("");
      $("#sh-drv-sel").value = it.driver_id != null ? String(it.driver_id) : "";
      pick.hidden = false;
    }
  }
  fillTollChip(it);
  metaRowSync();
}

/* 高速费 chip: 算过的才显示 (¥0 也是"算过" = 没走收费路) */
function fillTollChip(it) {
  const chip = $("#sh-toll");
  if (it.merged || it.toll == null) { chip.hidden = true; return; }
  chip.hidden = false;
  chip.textContent = it.toll > 0
    ? `高速 ¥${Number.isInteger(it.toll) ? it.toll : it.toll.toFixed(1)}` +
      (it.toll_km ? ` · ${Math.round(it.toll_km)}km` : "")
    : "无高速费";
}

function metaRowSync() {   // 驾驶员选择和高速费 chip 都藏了才整行藏
  $("#sh-drv").hidden = $("#sh-drv-pick").hidden && $("#sh-toll").hidden;
}

/* ---------- 高速费估价: 沿轨迹途经点驾车规划, 高德返回 tolls ---------- */
const TOLL_WAYPOINTS = 14;   // 途经点数 (高德单次驾车规划限 16, 留裕量)

/* 起终点 + 等距途经点把规划钉在实际走过的路上, 否则估的是"高德以为你
   会走的路"。tolls=0 也是有效结果 (没走收费路); 规划失败返回 null。 */
function calcTripToll(pts) {
  return new Promise(resolve => {
    if (!pts || pts.length < 2) return resolve(null);
    const n = pts.length;
    const gcj = i => toGcj([pts[i][0], pts[i][1]]);
    const wps = [];
    for (let k = 1; k <= TOLL_WAYPOINTS; k++)
      wps.push(gcj(Math.round(k * (n - 1) / (TOLL_WAYPOINTS + 1))));
    AMap.plugin("AMap.Driving", () => {
      try {
        const policy = AMap.DrivingPolicy && AMap.DrivingPolicy.LEAST_DISTANCE != null
          ? AMap.DrivingPolicy.LEAST_DISTANCE : 2;
        new AMap.Driving({ policy }).search(gcj(0), gcj(n - 1), wps, (status, result) => {
          if (status !== "complete" || !result.routes || !result.routes.length)
            return resolve(null);
          const r = result.routes[0];
          const roads = {};   // 同名收费路段合并 (按路名)
          for (const st of r.steps)
            if (st.tolls > 0 && st.toll_road)
              roads[st.toll_road] = (roads[st.toll_road] || 0) + st.tolls;
          resolve({
            tolls: r.tolls || 0,
            toll_km: Math.round((r.tolls_distance || 0) / 100) / 10,
            distance: r.distance || 0,
            roads: Object.keys(roads).map(rd => ({ road: rd, tolls: roads[rd] })),
          });
        });
      } catch { resolve(null); }
    });
  });
}

/* 打开还没算过的行程时顺手估一次, 成功即回传存库 (以后打开不再算)。 */
async function autoCalcToll(it, pts, seq) {
  const est = await calcTripToll(pts);
  if (!est || seq !== openSeq) return;
  it.toll = est.tolls;
  it.toll_km = est.toll_km;
  fillTollChip(it);
  metaRowSync();
  try {
    await postJSON(`/tesla/trips/api/${it.id}/toll`, {
      tolls: est.tolls, toll_km: est.toll_km,
      distance: est.distance, roads: est.roads,
    });
    const card = items.find(x => x.id === it.id);
    if (card && card !== it) { card.toll = est.tolls; card.toll_km = est.toll_km; }
  } catch { /* 存失败无所谓: 下次打开再估 */ }
}

$("#sh-drv-sel").addEventListener("change", async () => {
  const it = sheetTrip;
  if (!it) return;
  const sel = $("#sh-drv-sel");
  const driverId = sel.value === "" ? null : +sel.value;
  try {
    const upd = await postJSON(`/tesla/trips/api/${it.id}/driver`,
                               { driver_id: driverId });
    Object.assign(it, upd);                       // 弹层条目就地更新
    const card = items.find(x => x.id === upd.id);   // 列表条目 (分享直开时可能还没加载)
    if (card && card !== it) Object.assign(card, upd);
    const el = listEl.querySelector(`.card-t[data-id="${upd.id}"]`);
    if (el && card) el.replaceWith(renderCard(card));
    toast(driverId == null ? "已清除标注" : `已标注为 ${upd.driver}`);
  } catch (err) {
    toast(`标注失败: ${err.message}`);
    sel.value = it.driver_id != null ? String(it.driver_id) : "";
  }
});

async function openTrip(it, fromUrl) {
  curKey = it.merged ? (it.mergeKey || it.ids.join(",")) : String(it.id);
  if (!fromUrl && urlTripKey() !== curKey)
    history.pushState({ k: curKey }, "", listURL(curKey));
  const seq = ++openSeq;
  sheetTrip = it.merged ? null : it;   // 驾驶员标注只对单条行程有意义
  const cached = it.merged ? mergedCache.get(it.mergeKey) : null;
  if (cached) Object.assign(it, cached);   // 合并整包缓存命中: 数据齐了直接播
  if (it.pts || !it.merged) fillSheetHeader(it);   // 单条: 字段随卡片/接口齐, 直接填
  else fillSheetHeaderPending();                   // 合并流式: 数据在路上, 占位
  setupDriverPicker(it, seq);
  $("#sheet").classList.add("show");
  $("#backdrop").classList.add("show");
  tripMsg("正在加载轨迹…", true);

  try {
    await ensureAMap();
    if (seq !== openSeq) return;

    if (!tripMap) {
      tripMap = new AMap.Map("trip-map", { mapStyle: amapStyle, zoom: 11 });
      // iOS Safari 双指缩放劫持成页面缩放: 拦掉, 手势只给地图
      for (const ev of ["gesturestart", "gesturechange"])
        document.getElementById("trip-map").addEventListener(ev, e => e.preventDefault());
      tripMap.on("click", skipAnim);   // 播放中点一下 = 跳过, 直接收尾拉远
      /* 播放中按车速自动变焦 (慢速拉近/高速拉远) 的用户接管: 听地图容器上的
         缩放类输入 (滚轮/双击/双指)。不用 zoomend 数值比对 —— 变焦改成动画
         过渡后, 动画期间 getZoom 一直是中间值, 自己的 zoomend 和用户的
         分不开; 而程序化 setZoom 不会触发这些输入事件, 听输入是确定性的 */
      const zoomTakeover = () => {
        followZoomOn = false;
        zoomUserLock = true;                 // 手动接管 = 视角锁定, 换行程也保持
        zoomUserZoom = tripMap.getZoom();
      };
      // 锁定期间自动变焦已停, 播放中缩放只来自用户手势 —— 持续记录用户档位
      tripMap.on("zoomend", () => {
        if (zoomUserLock && anim && !anim.finished) zoomUserZoom = tripMap.getZoom();
      });
      const mapEl = document.getElementById("trip-map");
      mapEl.addEventListener("wheel", zoomTakeover, { passive: true });
      mapEl.addEventListener("dblclick", zoomTakeover);
      mapEl.addEventListener("touchstart", e => {
        if (e.touches.length >= 2) zoomTakeover();   // 双指 = 捏合缩放
      }, { passive: true });
    }
    /* 高德矢量样式数据是异步加载的: 首帧渲染时标注规则还没到, 地名不画;
       数据到货后要一次重渲染才补画 (同一轨迹第二次进入就有地名的原因)。
       开弹层后延时补几拍 —— setFeatures 同值重设 = 只触发重渲染, 不动视角 */
    const nudgeLabels = () => {
      if (tripMap && tripMap.getFeatures) tripMap.setFeatures(tripMap.getFeatures());
    };
    setTimeout(nudgeLabels, 1500);
    setTimeout(nudgeLabels, 5000);
    setTimeout(nudgeLabels, 12000);
    tripMap.clearMap();

    if (it.merged && !it.pts) {   // 合并轨迹流式: 汇总 → 首段开播 → 逐段追加
      await loadMergedStream(it, seq);
      return;
    }
    let c = it.pts ? it : trackCache.get(it.id);   // 合并整包: 数据随 it 一起来
    if (!c) {
      c = await getJSON(`/tesla/trips/api/${it.id}/track`);
      trackCache.set(it.id, c);
    }
    if (seq !== openSeq) return;
    if (!it.merged && it.toll == null)
      autoCalcToll(it, c.pts, seq);   // 不 await: 估价不挡播放

    /* 播放前把沿途瓦片刷进缓存 (跟随倍率按里程), 播放不再一路补图白屏;
       矢量模式没有可抄的瓦片 URL, 改扫路预取 (见 preloadVectorTrack) */
    const zoom = followZoom(TrackUtil.cumDistKm(c.pts).pop() || 0);
    const tpl = await tileTemplate();
    if (tpl) await preloadTiles(c.pts, zoom, tpl,
      p => tripMsg(`正在预载地图 ${p}%`, true));
    else await preloadVectorTrack(c.pts, c.ts || [], zoom,
      p => tripMsg(`正在预载地图 ${p}%`, true), seq);
    if (seq !== openSeq) return;
    tripMsg(null, false);
    playTrack(c.pts, c.ts || [], it, zoom);   // 动态播放: 起点跑向终点, 视角跟随, 结束后拉远全局
  } catch (e) {
    if (seq !== openSeq) return;
    if (fromUrl && it.merged) { hideSheet(); throw e; }   // 坏合并深链: 让 openByKey 抹参回列表
    tripMsg(String(e.message || e), false);   // 卡片打开等: 弹层里亮出错误
  }
}

/* 合并轨迹流式加载 (NDJSON): 首行汇总填弹层头, 之后每行一段 —— 第一段
   到了就开播, 后续段到了追加, 不等整包下完 (38 段的轨迹要好几秒)。首段
   未到时显示已耗时/已收字节; 全部到齐存 mergedCache, 重开同一条秒开。 */
async function loadMergedStream(it, seq) {
  const key = it.mergeKey;
  const res = await fetch(`/tesla/trips/api/merged_stream?ids=${key}`);
  if (res.status === 401) { location.replace("/tesla/login"); throw new Error("未登录"); }
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  const reader = res.body.getReader(), dec = new TextDecoder();
  const t0 = performance.now();
  const allPts = [], allTs = [], segStarts = [];
  let buf = "", got = 0, msgAt = 0, sess = null, segsGot = 0, segsTotal = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    got += value.length;
    buf += dec.decode(value, { stream: true });
    let nl;
    while ((nl = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (!line) continue;
      const d = JSON.parse(line);
      if (d.summary) {                    // 首行: 汇总 → 弹层头 (segs = 有点数的段数)
        Object.assign(it, d.summary);
        segsTotal = d.segs || it.n;
        fillSheetHeader(it);
      } else if (d.pts && d.pts.length) {
        if (seq !== openSeq) { reader.cancel().catch(() => {}); return; }   // 弹层已换
        segsGot++;
        if (!sess) {
          /* 首段开播前扫路预取 (矢量; 栅格走下面的后台抄 URL 预载):
             环形前瞻容器管播放中的连续前瞻, 这里把开场几秒 + 首段走廊
             先灌进缓存, 后续段边播边由环带覆盖 */
          await preloadVectorTrack(d.pts, d.ts, followZoom(it.km || 0),
            p => tripMsg(`正在预载地图 ${p}%`, true), seq);
          if (seq !== openSeq) { reader.cancel().catch(() => {}); return; }   // 扫路中弹层已换
          tripMsg(null, false);
          sess = playTrack(d.pts, d.ts, it, followZoom(it.km || 0), true);
        } else {
          sess.append(d.pts, d.ts);
        }
        segStarts.push(allPts.length);
        allPts.push(...d.pts);
        allTs.push(...d.ts);
        // 新一段的沿途瓦片后台预载 (不挡播放)
        tileTemplate().then(tpl => {
          if (tpl) preloadTiles(d.pts, followZoom(it.km || 0), tpl, () => {});
        });
      }
    }
    if (!sess && performance.now() - msgAt > 300) {   // 首段未到: 已耗时 + 已收字节
      msgAt = performance.now();
      tripMsg(`正在下载轨迹 · ${((performance.now() - t0) / 1000).toFixed(0)}s · ${(got / 1048576).toFixed(1)}MB`, true);
    }
  }
  if (seq !== openSeq) return;
  if (sess) sess.more = false;            // 流结束: 播到头就收尾
  if (allPts.length >= 2)
    mergedCache.set(key, { n: it.n, ids: it.ids, date: it.date, start: it.start,
      end: it.end, km: it.km, min: it.min, speed_max: it.speed_max,
      from: it.from, to: it.to, pts: allPts, ts: allTs, seg_starts: segStarts });
  if (!sess) throw new Error("这些行程没有轨迹数据");
  if (segsGot < segsTotal) tripMsg(`轨迹下载中断, 已播 ${segsGot}/${segsTotal} 段`, false);
}

/* ---------- 播放控制条: 只绑定一次, 操作当前 anim 会话 ---------- */

pbToggle.addEventListener("click", () => {
  if (!anim) return;
  if (anim.finished) { anim.replay(); return; }   // 播完 → 重播
  anim.paused = !anim.paused;
  pbToggle.innerHTML = anim.paused ? ICON_PLAY : ICON_PAUSE;
  pbToggle.setAttribute("aria-label", anim.paused ? "播放" : "暂停");
  if (anim.paused) releaseScreenAwake();   // 暂停允许熄屏, 继续播重新保活
  else holdScreenAwake();
});
pbSeek.addEventListener("input", () => {         // 拖动进度: 立即生效 (暂停/播完都生效)
  if (!anim) return;
  if (anim.finished) anim.replay();              // 播完拖进度 = 从该处重播
  anim.seek(pbSeek.value / 1000);
});
pbSeek.addEventListener("pointerdown", () => { if (anim) anim.seeking = true; });
for (const ev of ["pointerup", "pointercancel"])
  pbSeek.addEventListener(ev, () => { if (anim) anim.seeking = false; });
pbSpeed.addEventListener("click", () => {        // 倍速循环 1×→2×→4×→8×
  if (!anim) return;
  anim.speed = PB_SPEEDS[(PB_SPEEDS.indexOf(anim.speed) + 1) % PB_SPEEDS.length];
  pbSpeed.textContent = anim.speed + "×";
});

/* ---------- 导出视频: 播放地图录成视频存相册 ---------- */
/* 链路: 逐帧把地图各画布与可视区的相交子矩形合成到录制画布 →
   captureStream(30) + MediaRecorder (mp4 优先) → 从头整段重播, 播完自动
   收片 → 预览弹层 → 有系统分享 (secure context 限定, 即 HTTPS) 走
   navigator.share({files}) 拉起分享单选「存储视频」入相册; 没有 (NAS 常
   是 HTTP, iPhone 的 Safari 里 share 压根不存在) 退化为 <a download>
   存「文件」App, 用户在文件里长按 → 共享 → 存储视频 也能入相册。播放条
   等覆盖层是 DOM, 不入镜 —— 视频里只有地图本体。 */
let recFile = null, recURL = null;   // 上次成片 (分享用 / 预览 src 用)

function recMime() {    // Safari 与新版 Chrome 都能直出 mp4, 老内核退 webm
  for (const t of ["video/mp4;codecs=avc1", "video/mp4", "video/webm;codecs=vp9", "video/webm"])
    if (window.MediaRecorder && MediaRecorder.isTypeSupported(t)) return t;
  return "";
}

function recCompose() {    // 每帧合成: 环形容器比可视区大, 各画布取相交子
  const wrap = document.querySelector(".trip-map-wrap");   // 矩形映射过来 (dbg90 教训: 目的原点要先减可视区原点)
  if (!wrap || !rec) return;
  const wr = wrap.getBoundingClientRect();
  const { ctx, out } = rec;
  ctx.fillStyle = "#0b0d10";
  ctx.fillRect(0, 0, out.width, out.height);
  for (const c of wrap.querySelectorAll("canvas")) {
    if (!c.width || !c.height) continue;
    const r = c.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    const kx = c.width / r.width, ky = c.height / r.height;
    const wx0 = (wr.left - r.left) * kx, wy0 = (wr.top - r.top) * ky;   // 可视区原点 (画布坐标)
    const sx0 = Math.max(0, wx0), sy0 = Math.max(0, wy0);
    const sx1 = Math.min(c.width, wx0 + wr.width * kx);
    const sy1 = Math.min(c.height, wy0 + wr.height * ky);
    if (sx1 <= sx0 || sy1 <= sy0) continue;
    ctx.drawImage(c, sx0, sy0, sx1 - sx0, sy1 - sy0,
      (sx0 - wx0) / (wr.width * kx) * out.width,
      (sy0 - wy0) / (wr.height * ky) * out.height,
      (sx1 - sx0) / (wr.width * kx) * out.width,
      (sy1 - sy0) / (wr.height * ky) * out.height);
  }
  rec.raf = requestAnimationFrame(recCompose);
}

function startRecExport() {
  if (!anim) { toast("轨迹还没开始播放"); return; }
  const mime = recMime();
  if (!mime || !HTMLCanvasElement.prototype.captureStream) { toast("此浏览器不支持录制视频"); return; }
  const wr = document.querySelector(".trip-map-wrap").getBoundingClientRect();
  const k = Math.min(devicePixelRatio || 1, 2);   // dpr 3 的手机也只录 2 倍: 够清晰省码率
  const out = document.createElement("canvas");
  out.width = Math.round(wr.width * k); out.height = Math.round(wr.height * k);
  rec = { out, ctx: out.getContext("2d"), chunks: [], mime, raf: 0, mr: null,
          name: "MyTesla轨迹-" + $("#sh-date").textContent.trim() };
  try {
    rec.mr = new MediaRecorder(out.captureStream(30), { mimeType: mime, videoBitsPerSecond: 6e6 });
  } catch {
    rec = null; toast("此浏览器不支持录制视频"); return;
  }
  const r = rec;   // ondataavailable 回调里 rec 可能已被清空, 捕获本体
  r.mr.ondataavailable = e => { if (e.data && e.data.size) r.chunks.push(e.data); };
  r.mr.start(500);
  pbRec.classList.add("rec");
  recCompose();
  toast("开始录制, 播完自动生成");
  anim.restart();     // 整段从头重播 (倍速沿用当前档)
}

function stopRecExport(cancel) {
  const r = rec;
  if (!r) return;
  rec = null;
  cancelAnimationFrame(r.raf);
  pbRec.classList.remove("rec");
  if (!r.mr || r.mr.state === "inactive") return;
  r.mr.onstop = () => { if (!cancel) recShowResult(r); };
  r.mr.stop();
}

function recShowResult(r) {
  const blob = new Blob(r.chunks, { type: r.mime });
  if (blob.size < 8192) { toast("录制失败 (没有内容)"); return; }   // 全黑/没帧
  const ext = r.mime.includes("mp4") ? "mp4" : "webm";
  recFile = new File([blob], r.name + "." + ext, { type: r.mime });
  if (recURL) URL.revokeObjectURL(recURL);
  recURL = URL.createObjectURL(blob);
  $("#rec-video").src = recURL;
  // 存储按钮: 录完一定给 (2026-09-13 二连修: 先按 canShare 门控藏了按钮 ——
  // iOS Safari 没实现 canShare; 改按 share 存在性仍藏 —— share 是 secure
  // context 限定, HTTP 部署里同样不存在)。有 share = 分享单存相册; 没有 =
  // 下载存「文件」, 按钮文案随路径切换 (提示行按用户要求撤掉)。
  const shareOK = typeof navigator.share === "function";
  $("#rec-save").hidden = false;
  $("#rec-save").textContent = shareOK ? "存到相册" : "保存视频";
  $("#rec-modal").hidden = false;
}

function recCloseModal() {
  $("#rec-modal").hidden = true;
  $("#rec-video").removeAttribute("src");
  $("#rec-video").load();    // 释放解码资源 (iOS 上 blob 视频挂着会占内存)
  if (recURL) { URL.revokeObjectURL(recURL); recURL = null; }
  recFile = null;
}

pbRec.addEventListener("click", () => {
  if (rec) { stopRecExport(true); toast("已取消录制"); }
  else startRecExport();
});
function saveVideoFile() {   // 下载兜底: iOS 存「文件」App (经共享再入相册), 桌面浏览器直接落盘
  const a = document.createElement("a");
  a.href = recURL; a.download = recFile.name;
  document.body.appendChild(a); a.click(); a.remove();
}

$("#rec-save").addEventListener("click", async () => {
  if (!recFile) return;
  if (typeof navigator.share !== "function") { saveVideoFile(); return; }
  try { await navigator.share({ files: [recFile], title: recFile.name }); }
  catch (e) { if (e.name !== "AbortError") saveVideoFile(); }   // 分享失败 (如不支持文件) 也别让视频白录
});
$("#rec-close").addEventListener("click", recCloseModal);
$("#rec-modal").addEventListener("click", e => { if (e.target.id === "rec-modal") recCloseModal(); });

$("#backdrop").addEventListener("click", closeTrip);
/* 手柄: 点一下关, 也能拖着往下拉关 (跟手 + 松手回弹; 拖过 8px 就不算点击,
   否则回弹动画结束瞬间跟着来的 click 会把刚弹回的弹层又关掉) */
(() => {
  const sheetEl = $("#sheet");
  let y0 = null, dy = 0;
  const grab = $("#grab");
  grab.addEventListener("pointerdown", e => {
    y0 = e.clientY; dy = 0;
    grab.setPointerCapture(e.pointerId);   // 手指滑出区域也能继续收事件
  });
  grab.addEventListener("pointermove", e => {
    if (y0 == null) return;
    dy = Math.max(0, e.clientY - y0);      // 只往下拖有效, 往上顶不抬层
    sheetEl.style.transition = "none";
    sheetEl.style.transform = `translateY(${dy}px)`;
  });
  const release = () => {
    if (y0 == null) return;
    sheetEl.style.transition = ""; sheetEl.style.transform = "";
    if (dy > 90) closeTrip();              // 拉过 90px = 明确想关; 否则弹回
    y0 = null;
  };
  grab.addEventListener("pointerup", release);
  grab.addEventListener("pointercancel", release);
  grab.addEventListener("click", e => {
    if (dy > 8) { e.stopImmediatePropagation(); dy = 0; return; }
    closeTrip();
  });
})();

/* 浏览器后退/前进: 只切界面不动历史, 与地址栏保持同步 */
addEventListener("popstate", () => {
  const key = urlTripKey();
  if (key == null) {
    if (curKey != null) { hideSheet(); curKey = null; }
  } else if (key !== curKey) {
    openByKey(key);
  }
});

/* 首页列表加载完后, 后台预载高德脚本 (首次点开更快); 分享链接 (?id=X) 直开弹层 */
loadMore().then(() => { ensureAMap().catch(() => {}); });
if (urlTripKey() != null) openByKey(urlTripKey());
