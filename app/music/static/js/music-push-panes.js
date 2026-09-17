// music-push-panes — My Music 二级页推入层: 专辑/艺人/播放列表/资料库各页从右滑入, 层栈/滚动存档/右划滑回。
// 拆自 music.js (结构化重构), 1.8.0 重排: 无参页 (播放列表/专辑/艺人/最近播放/
// 已下载/搜索/设置/统计/更新日志) 也走同一套层, 与详情页布局一致 (用户点名)。
"use strict";
/* global $, pageState, pushStack, renderAlbumView, renderAlbumsPane, renderArtistView,
          renderArtistsPane, renderChangelogView, renderDownloadsPane, renderHomeView,
          renderPlaylistsPane, renderPlaylistView, renderRecentPane, renderSearchView,
          renderSettingsView, renderStatsView, saveLastRoute */
/* exported closePushStack, pushPaneTarget, renderRootView, routePushed, routeRoot */

// ------------------------------------------------------------ 二级页推入层
// 专辑/艺人/播放列表走 iOS 设置式二级页: 从右滑入盖住一级, 右划 (左缘起手)
// 或返回键/历史回退滑出。层叠各层保住自己的滚动; 一级页留在底下不动,
// 滚动位置推入时存档、滑出后还原。(层栈 pushStack 声明在文件顶部。)

// 一级页滚动状态: 文档本身永不滚 (固定壳, iOS 工具栏只跟文档滚动收放 ——
// 文档不滚视口就恒定, 页签栏/气泡钉死), 滚的是 main 这层内部滚动器。
// 层盖着时 main 摸不到 (点不到), 记/还原位置纯是兜底 (聚焦跳转等程序滚动)。
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

/** 层运动期标记 (body.pane-anim): 层铺满全高后会从磨砂气泡/页签栏底下扫过,
    fixed+backdrop-filter 遇上扫动的变换层是 WebKit 的重影配方 ——
    运动期 CSS 把它们换成实底 (暂撤磨砂取样), 停稳 500ms 后恢复磨砂。
    拖动中每下都续期, 手不松标记不撤。 */
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
  void pane.offsetWidth;   // 起点样式落地再放滑入 (rAF 在安静页会饿死, 不用它)
  pane.classList.add("open");
  return pane.querySelector(".pane-scroll");
}

/** 滑出若干层 (栈里保留 keep 层以下); 动画完移除 DOM。 */
function closePushStack(keep = 0) {
  paneMotion();                     // 滑出途中气泡暂撤磨砂 (重影对策)
  while (pushStack.length > keep) {
    const item = pushStack.pop();
    item.pane.classList.remove("open");
    setTimeout(() => item.pane.remove(), 420);
  }
  if (!pushStack.length) {
    unlockRootScroll();
  }
  saveLastRoute();                  // 收层后停在哪页也记下 (开局回跳)
}

/** 右划返回: 面板任意位置起手, 横竖先分家 (竖向交还滚动); 拖过三分之一
    或带甩劲松手就收层, 否则弹回。收层是纯视图收层, 不碰浏览器历史
    (一个地址走全程, 见文件头导航一节)。
    左缘的归属按环境各安其位: 主屏图标打开 (standalone) 没有系统手势,
    整条左缘 (含屏幕最边) 都是这里的; 浏览器里苹果把最边上一小条握在
    系统手里 (整页截图滑走, 网页收不到触摸, preventDefault/Navigation
    API 都掐不动 —— 试过两轮, 别再试), 那一条之外的左缘归这里。 */
function bindPaneSwipe(pane) {
  pane.addEventListener("pointerdown", (event) => {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    // 搜索结果四子页 (1.8.3) 自己是横向 snap 滚动器: 起手在页里的横拖
    // 归切页, 不归右划返回 (两条横手势分家)
    if (event.target.closest("#search-body.paged")) return;
    const startX = event.clientX;
    const startY = event.clientY;
    let horizontal = false;
    let decided = false;
    let lastX = startX;
    let lastT = event.timeStamp;
    const signals = new AbortController();        // 拆掉 cleanup ↔ 手柄的互相引用
    const cleanup = () => signals.abort();
    const move = (ev) => {
      const dx = ev.clientX - startX;
      const dy = ev.clientY - startY;
      if (!decided) {
        if (Math.abs(dx) < 8 && Math.abs(dy) < 8) return;
        decided = true;
        horizontal = dx > 0 && Math.abs(dx) > Math.abs(dy);
        if (!horizontal) { cleanup(); return; }   // 竖向: 交还滚动
        pane.setPointerCapture(ev.pointerId);
        pane.style.transition = "none";
      }
      paneMotion();                 // 拖动中: 气泡磨砂持续暂撤 (每下续期)
      pane.style.transform = `translateX(${Math.max(0, dx)}px)`;
      lastX = ev.clientX;
      lastT = ev.timeStamp;
    };
    const end = (ev) => {
      cleanup();
      if (!horizontal) return;      // 点按/竖向: 不归这里管
      const dx = Math.max(0, ev.clientX - startX);
      const width = pane.offsetWidth || 1;
      const flick = ev.timeStamp - lastT < 100 && lastX - startX > 40;
      pane.style.transition = "";
      pane.style.transform = "";
      if (dx <= width / 3 && !flick) {
        paneMotion();               // 弹回也是一段运动, 磨砂照旧暂撤
        return;                     // 没拖够: 弹回 (.open 的 0)
      }
      paneMotion();                 // 滑出途中气泡暂撤磨砂 (重影对策)
      pane.classList.remove("open");              // 从当前位置滑出
      pushStack.pop();
      setTimeout(() => pane.remove(), 420);
      if (!pushStack.length) unlockRootScroll();
      saveLastRoute();              // 手势收层也记停在哪页 (开局回跳)
    };
    const cancel = () => {
      cleanup();
      if (horizontal) {
        paneMotion();               // 弹回也是一段运动, 磨砂照旧暂撤
        pane.style.transition = "";
        pane.style.transform = "";
      }
    };
    pane.addEventListener("pointermove", move, { signal: signals.signal });
    pane.addEventListener("pointerup", end, { signal: signals.signal });
    pane.addEventListener("pointercancel", cancel, { signal: signals.signal });
  });
}

