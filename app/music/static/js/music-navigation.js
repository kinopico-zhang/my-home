// music-navigation — My Music 全局状态 (pageState/pushStack) + 应用内导航: 地址不动的路由, 同页刷新。
// 拆自 music.js (结构化重构), 1.8.0 重排: 页签栏撤掉, 主页独占根层,
// 其余视图 (播放列表/专辑/艺人/最近播放/已下载/搜索/设置/统计/更新日志) 全是推入层。
"use strict";
/* global checkScanStatus, routePushed, routeRoot, stopScanPolling, syncDownloadIcons,
          syncPlayerIndicators */
/* exported clearLastRoute, coverUploadPlaylistId, currentRoute, navigate, pageState,
            parseRoute, pushStack, readLastRoute, route, routeKey, saveLastRoute,
            userRescanPending */

const pageState = {
  lists: {},        // segment → {items, total, offset, done, loading}
  homeRecent: null,      // 主页最近播放段曲目 (队列用)
  recentPane: null,      // 最近播放页曲目 (1.8.1, 队列用)
  searchAbort: null,
  scanPollTimer: 0,
  lastScanSignature: "", // 已消化的一轮扫描 (finished_at+changed): 重复的不再响应
  sawScanRunning: false, // 这轮扫描是不是在本页眼皮底下跑的 (首见的旧结果不惊动)
  rootView: "",          // 根层挂的是哪个视图 (1.8.0 起只有 home; 二级层盖着时它仍在底下)
  rootScroll: 0,         // 推入二级层那一刻一级页的滚动位置 (滑出后还原)
};

// 手动「重新扫描曲库」按下后置位: 那一轮收尾要出提示 (后台自动扫的不打扰)
let userRescanPending = false;

// 文件选择器是全局单例, 记住现在改封面的是哪个列表
let coverUploadPlaylistId = 0;

// 二级推入层栈 (声明在顶部: 导航一节的 currentRoute 要读它,
// no-use-before-define 不放行函数住后段的状态)
const pushStack = [];   // [{view, id, pane}]

// ------------------------------------------------------------ 导航 (应用内状态)

// 一个地址走全程 (用户点名: 列表和主页就是一个页面, 进播放列表只是内容
// 变化, 不存在网页切换): 导航目标只活在内存里 —— 根视图 pageState.rootView,
// 二级层 pushStack —— 全程不碰 location.hash / pushState / history.back,
// 浏览器返回/前进和系统侧滑在应用里没有条目可退, 整页截图滑走 (气泡跟着
// 跑) 的毛病连根拔掉。旧深链 (#playlist/5) 只在开局消化一次, URL 随即
// 洗成光杆 /music。

// 无参推入层 (菜单「播放列表/专辑/艺人/最近播放/已下载」+ 搜索键 + 设置页
// 里的统计/更新日志): 布局与详情层 (专辑/艺人/播放列表) 一模一样, 从右滑入。
const PANE_VIEWS = ["playlists", "albums", "artists", "recent", "downloads",
                    "search", "settings", "stats", "changelog"];

function parseRoute(target) {
  const [name, argument] = String(target).split("/");
  if (name === "album" && argument) return { view: "album", albumId: Number(argument) };
  if (name === "artist" && argument) return { view: "artist", artistId: Number(argument) };
  if (name === "playlist" && argument) return { view: "playlist", playlistId: Number(argument) };
  if (name === "home") return { view: "home" };
  if (PANE_VIEWS.includes(name)) return { view: name };
  return null;                     // 认不得的目标当没点
}

/** 当前导航目标 (从状态派生): 有层看顶层, 没层看根视图。 */
function currentRoute() {
  const top = pushStack[pushStack.length - 1];
  if (top) {
    return top.view === "album" ? { view: "album", albumId: top.id }
      : top.view === "artist" ? { view: "artist", artistId: top.id }
      : top.view === "playlist" ? { view: "playlist", playlistId: top.id }
      : { view: top.view };
  }
  return { view: pageState.rootView };
}

function navigate(target) {
  const parsed = parseRoute(target);
  if (!parsed) return;
  if (String(target) === routeKey(currentRoute())) {
    route(true);                     // 同页再点 = 刷新
    return;
  }
  routeTo(parsed);
}

// ------------------------------------------------------------ 上次停的页 (1.8.3)
// 用户点名「打开 app 自动回最后一个页面」: 导航/收层后各存一次, 开局读档
// 回去 (没记过 = 头一回, 回主页播放列表); 退出登录清档, 下个人别落进
// 我上次停的页。隐私模式 localStorage 会抛, 存读都兜住。

const LAST_ROUTE_KEY = "music.lastRoute";

/** 路由 → 档案键 (与 parseRoute 认的目标同一个写法)。 */
function routeKey(route) {
  if (route.view === "album") return `album/${route.albumId}`;
  if (route.view === "artist") return `artist/${route.artistId}`;
  if (route.view === "playlist") return `playlist/${route.playlistId}`;
  return route.view;
}

function saveLastRoute() {
  try { localStorage.setItem(LAST_ROUTE_KEY, routeKey(currentRoute())); }
  catch (_error) { /* 隐私模式存不进就算了 */ }
}

/** 开局回跳用: 上次停的页 (没有/读不了回空串, 调用方自己兜 "home")。 */
function readLastRoute() {
  try { return localStorage.getItem(LAST_ROUTE_KEY) || ""; }
  catch (_error) { return ""; }
}

/** 退出登录清档 (设置页调)。 */
function clearLastRoute() {
  try { localStorage.removeItem(LAST_ROUTE_KEY); } catch (_error) { /* 没档可清 */ }
}

/** 按目标渲染: 除主页外全部进层栈 (菜单/搜索键进的就是这些层),
    主页铺根视图 (route 的带参版)。 */
function routeTo(parsed, force) {
  const view = parsed.view;
  const pushed = view !== "home";
  const pushId = parsed.albumId ?? parsed.artistId ?? parsed.playlistId ?? 0;
  stopScanPolling();
  if (pushed) routePushed(view, pushId, parsed, force);
  else routeRoot(view, force);
  if (!pushed) checkScanStatus();
  syncPlayerIndicators();
  syncDownloadIcons();
  saveLastRoute();   // 停在哪页记下来 (开局回跳用)
}

/** 重铺当前状态 (扫描收尾/同页刷新用): 目标从状态里派生。 */
function route(force) {
  routeTo(currentRoute(), force);
}
