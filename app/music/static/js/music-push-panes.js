// music-push-panes — My Music 二级页推入层: 专辑/艺人/播放列表/资料库/搜索/
// 设置等各页从右滑入, 层栈/滚动存档 (1.8.0 起无参页同款, 用户点名)。
// 右划返回手势拆在 music-pane-swipe.js (1.8.6 按域再拆)。
"use strict";
/* global $, bindPaneSwipe, pageState, pushStack, renderAlbumView, renderAlbumsPane,
          renderArtistView, renderArtistsPane, renderChangelogView, renderDownloadsPane,
          renderHomeView, renderPlaylistsPane, renderPlaylistView, renderRecentPane,
          renderSearchView, renderSettingsView, renderStatsView, saveLastRoute */
/* exported closePushStack, paneMotion, pushPaneTarget, renderRootView, routePushed,
            routeRoot, syncSearchDock, unlockRootScroll */

// ------------------------------------------------------------ 二级页推入层
// 专辑/艺人/播放列表走 iOS 设置式二级页: 从右滑入盖住一级, 右划/返回键滑出。
// 层叠各层保住自己的滚动; 一级页留在底下不动, 位置推入时存档、滑出后还原。

// 一级页滚动状态: 文档永不滚 (固定壳, iOS 工具栏只跟文档滚动收放), 滚的是
// main 内部滚动器; 层盖着时 main 摸不到, 记/还原位置纯是兜底 (程序滚动)。
function lockRootScroll() {
  if (!pushStack.length) pageState.rootScroll = $("#main").scrollTop;
}

function unlockRootScroll() {
  $("#main").scrollTop = pageState.rootScroll;
}

/** 一级页路由: 主页独占根层 (1.8.0 页签栏撤后其余视图全是推入层)。 */
function routeRoot(view, force) {
  const mounted = pageState.rootView === view;
  if (pushStack.length) {
    // 二级层还盖着: 菜单/回主页就趁盖着先铺好; 回到原根就只把层滑走
    if (!mounted) renderRootView(view);
    closePushStack();
    return;
  }
  if (mounted && !force) {
    unlockRootScroll();     // 层已被手势收走: 一级页原样躺着, 解锁回位即可
    return;
  }
  renderRootView(view);
}

function renderRootView(view) {
  pageState.rootView = view;
  renderHomeView();
}

/** 二级页路由: 新目标推一层; 回退到栈里已有的层只滑走压它的; 同层同页不重开。 */
function routePushed(view, id, ids, force) {
  const top = pushStack[pushStack.length - 1];
  if (force && top && top.view === view && top.id === id) {
    renderPushedView(view, ids, top.pane.querySelector(".pane-scroll"));
    return;
  }
  const existing = pushStack.findIndex((p) => p.view === view && p.id === id);
  if (existing >= 0) { closePushStack(existing + 1); return; }
  renderPushedView(view, ids, openPushPane(view, id));
}

function renderPushedView(view, ids, target) {
  if (view === "album") renderAlbumView(ids.albumId, target);
  else if (view === "artist") renderArtistView(ids.artistId, target);
  else if (view === "playlist") renderPlaylistView(ids.playlistId, target);
  else if (view === "playlists") renderPlaylistsPane(target);
  else if (view === "albums") renderAlbumsPane(target);
  else if (view === "artists") renderArtistsPane(target);
  else if (view === "recent") renderRecentPane(target);
  else if (view === "downloads") renderDownloadsPane(target);
  else if (view === "search") renderSearchView(target);
  else if (view === "settings") renderSettingsView(target);
  else if (view === "stats") renderStatsView(target);
  else renderChangelogView(target);
}

/** 二级层薄层当前该写内容的地方 (换封面等就地重铺用; 没层时兜底 #main)。 */
function pushPaneTarget() {
  const top = pushStack[pushStack.length - 1];
  return (top && top.pane.querySelector(".pane-scroll")) || $("#root-view");
}

/** 层运动期标记 (body.pane-anim): 层铺满全高后会从磨砂气泡/船坞键底下扫过,
    fixed+backdrop-filter 遇上扫动的变换层是 WebKit 的重影配方 —— 运动期
    CSS 换实底 (暂撤磨砂取样), 停稳 500ms 恢复磨砂; 拖动中每下都续期。 */
let paneAnimTimer = 0;
function paneMotion() {
  document.body.classList.add("pane-anim");
  clearTimeout(paneAnimTimer);
  paneAnimTimer = setTimeout(
    () => document.body.classList.remove("pane-anim"), 500);
}

function openPushPane(view, id) {
  lockRootScroll();
  const pane = document.createElement("div");
  pane.className = "push-pane";
  pane.innerHTML = '<div class="pane-scroll"></div>';
  $("#push-stack").appendChild(pane);
  pushStack.push({ view, id, pane });
  bindPaneSwipe(pane);
  paneMotion();                     // 滑入途中气泡暂撤磨砂 (重影对策)
  syncSearchDock();                 // 搜索层到顶: 船坞让位给搜索框 (1.8.5)
  void pane.offsetWidth;   // 起点样式落地再放滑入 (rAF 在安静页会饿死, 不用它)
  pane.classList.add("open");
  return pane.querySelector(".pane-scroll");
}

/** 滑出若干层 (栈里保留 keep 层以下); 动画完移除 DOM。 */
function closePushStack(keep = 0) {
  paneMotion();                     // 滑出途中气泡暂撤磨砂 (重影对策)
  while (pushStack.length > keep) {
    const item = pushStack.pop();
    // 焦点还落在收走的层里 (如搜索输入框): 先摘走 —— 键盘确定性收下,
    // --kb-h 随 resize 归零, 别等 420ms 后元素被移除才被动失焦 (1.8.6)
    if (item.pane.contains(document.activeElement)) document.activeElement.blur();
    item.pane.classList.remove("open");
    setTimeout(() => item.pane.remove(), 420);
  }
  if (!pushStack.length) {
    unlockRootScroll();
  }
  syncSearchDock();                 // 换了顶层: 船坞/搜索框谁站岗重排 (1.8.5)
  saveLastRoute();                  // 收层后停在哪页也记下 (开局回跳)
}

/** 搜索层在不在栈顶 (1.8.5 用户点名「三个控件消失, 换成搜索框」): 在 —
    船坞三件套让位 (CSS body.search-top), 搜索页的 .search-foot 钉到船坞位;
    不在 — 船坞回来。 */
function syncSearchDock() {
  const top = pushStack[pushStack.length - 1];
  document.body.classList.toggle("search-top",
    Boolean(top) && top.view === "search");
}

