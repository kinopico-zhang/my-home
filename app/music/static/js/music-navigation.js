// music-navigation — My Music 全局状态 (pageState/pushStack) + 应用内导航: 地址不动的路由, 同页刷新, 页签点亮。
// 拆自 music.js (结构化重构: 代码逐字节未动, 经典脚本按 music.html 里的顺序加载, 跨模块引用走全局)。
"use strict";
/* global checkScanStatus, routePushed, routeRoot, stopScanPolling, syncDownloadIcons,
          syncPlayerIndicators */
/* exported LIBRARY_SEGMENTS, coverUploadPlaylistId, currentRoute, navigate, pageState,
            parseRoute, pushStack, route, syncViewTabs, userRescanPending */


const LIBRARY_SEGMENTS = [
  ["albums", "专辑"], ["artists", "艺人"], ["downloads", "已下载"],
];

/** 老版本存过的段名 (recent/playlists) 已收窄掉, 认不出的回落专辑。 */
function storedSegment() {
  const saved = localStorage.getItem("music-segment") || "";
  return LIBRARY_SEGMENTS.some(([key]) => key === saved) ? saved : "albums";
}

const pageState = {
  segment: storedSegment(),
  searchQuery: "",
  lists: {},        // segment → {items, total, offset, done, loading}
  homeRecent: null,      // 主页最近播放段曲目 (队列用)
  searchAbort: null,
  scanPollTimer: 0,
  lastScanSignature: "", // 已消化的一轮扫描 (finished_at+changed): 重复的不再响应
  sawScanRunning: false, // 这轮扫描是不是在本页眼皮底下跑的 (首见的旧结果不惊动)
  rootView: "",          // 根层挂的是哪个视图 (二级层盖着时它仍在底下)
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

function parseRoute(target) {
  const [name, argument] = String(target).split("/");
  if (name === "album" && argument) return { view: "album", albumId: Number(argument) };
  if (name === "artist" && argument) return { view: "artist", artistId: Number(argument) };
  if (name === "playlist" && argument) return { view: "playlist", playlistId: Number(argument) };
  if (["home", "library", "search", "stats", "settings", "changelog"].includes(name)) {
    return { view: name };
  }
  return null;                     // 认不得的目标当没点
}

/** 当前导航目标 (从状态派生): 有层看顶层, 没层看根视图。 */
function currentRoute() {
  const top = pushStack[pushStack.length - 1];
  if (top) {
    return top.view === "album" ? { view: "album", albumId: top.id }
      : top.view === "artist" ? { view: "artist", artistId: top.id }
      : { view: "playlist", playlistId: top.id };
  }
  return { view: pageState.rootView };
}

/** 页签栏点亮同步 (进二级层时全灭 —— 层不算任何页签; 统计/更新日志也不算,
    它们是设置页里点进去的子页, 回头还按设置页签)。 */
function syncViewTabs(view) {
  for (const button of document.querySelectorAll("[data-view-tab]")) {
    button.classList.toggle("on", button.dataset.viewTab === view);
  }
}

function navigate(target) {
  const parsed = parseRoute(target);
  if (!parsed) return;
  const current = currentRoute();
  const currentKey = current.view === "album" ? `album/${current.albumId}`
    : current.view === "artist" ? `artist/${current.artistId}`
    : current.view === "playlist" ? `playlist/${current.playlistId}`
    : current.view;
  if (String(target) === currentKey) { route(true); return; }   // 同页再点 = 刷新
  routeTo(parsed);
}

/** 按目标渲染: 二级目标进层栈, 根目标铺根视图 (route 的带参版)。 */
function routeTo(parsed, force) {
  const view = parsed.view;
  const pushed = view === "album" || view === "artist" || view === "playlist";
  const pushId = parsed.albumId ?? parsed.artistId ?? parsed.playlistId;
  // 主页/资料库/搜索/设置页签常驻 (页签栏每个页面都一致, 详情页也能一键切回;
  // 二级页不换页签栏, 返回一律右划)
  syncViewTabs(view);
  stopScanPolling();
  if (pushed) routePushed(view, pushId, parsed, force);
  else routeRoot(view, force);
  if (!pushed) checkScanStatus();
  syncPlayerIndicators();
  syncDownloadIcons();
}

/** 重铺当前状态 (扫描收尾/同页刷新用): 目标从状态里派生。 */
function route(force) {
  routeTo(currentRoute(), force);
}

