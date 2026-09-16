// music.js — My Music 浏览页: 主页 (播放列表/最近播放) + 资料库
// (专辑/艺人/歌曲/已下载 + 语种筛选) + 搜索 (歌名/专辑/艺人/歌词) +
// 专辑/艺人详情 + 设置。播放交给 music-player.js, 下载管理在 downloads.js,
// 蜂窝流量记账在 cellular-usage.js。
"use strict";

const LIBRARY_SEGMENTS = [
  ["albums", "专辑"], ["artists", "艺人"], ["songs", "歌曲"], ["downloads", "已下载"],
];
const LANGUAGES = ["全部", "中文", "日文", "英文", "韩文", "俄文", "其他"];

/** 老版本存过的段名 (recent/playlists) 已收窄掉, 认不出的回落专辑。 */
function storedSegment() {
  const saved = localStorage.getItem("music-segment") || "";
  return LIBRARY_SEGMENTS.some(([key]) => key === saved) ? saved : "albums";
}

const pageState = {
  segment: storedSegment(),
  language: localStorage.getItem("music-language") || "全部",
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

/** 一级页路由: 主页/资料库/搜索/统计/设置都铺在 #root-view 根层。 */
function routeRoot(view, force) {
  const mounted = pageState.rootView === view;
  if (pushStack.length) {
    // 二级层还盖着: 点页签换根就趁盖着先铺好; 回到原根就只把层滑走
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
  if (view === "search") renderSearchView();
  else if (view === "stats") renderStatsView();
  else if (view === "settings") renderSettingsView();
  else if (view === "changelog") renderChangelogView();
  else if (view === "library") renderLibraryView();
  else renderHomeView();
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
  else renderPlaylistView(ids.playlistId, target);
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
    syncViewTabs(pageState.rootView);   // 层收尽: 页签回到根视图 (开层时全灭过)
  }
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
      if (!pushStack.length) {
        unlockRootScroll();
        syncViewTabs(pageState.rootView);         // 页签回到根视图
      }
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

// ------------------------------------------------------------ 下载 (离线)

// 离线下载要安全上下文 (HTTPS/localhost): Cache API 和 SW 在明文 HTTP
// 下浏览器不给 —— 明文环境整个功能收起来, 只留说明
const downloadsEnabled = downloadsSupported({
  secureContext: window.isSecureContext,
  cacheApi: typeof caches !== "undefined",
  serviceWorkerApi: "serviceWorker" in navigator,
});

const DOWNLOAD_CACHE = "music-downloads-v1";
const DOWNLOAD_INDEX_KEY = "music-downloads";

function browserDownloadAdapters() {
  return {
    readIndex() {
      try {
        return JSON.parse(localStorage.getItem(DOWNLOAD_INDEX_KEY) || "[]");
      } catch (_error) { return []; }
    },
    writeIndex(entries) {
      try {
        localStorage.setItem(DOWNLOAD_INDEX_KEY, JSON.stringify(entries));
      } catch (_error) { /* 存满了: 已下的字节还在缓存里, 只是列表丢了 */ }
    },
    async downloadBody(url, onProgress, signal) {
      const response = await fetch(url, { signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const contentType = response.headers.get("Content-Type")
        || "application/octet-stream";
      if (!response.body || !response.body.getReader) {
        return { body: await response.blob(), contentType };
      }
      const total = Number(response.headers.get("Content-Length")) || 0;
      const reader = response.body.getReader();
      const parts = [];
      let received = 0;
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        parts.push(value);
        received += value.byteLength;
        if (total) onProgress(received / total);
      }
      return { body: new Blob(parts), contentType };
    },
    async cachePut(url, body, contentType) {
      const cache = await caches.open(DOWNLOAD_CACHE);
      await cache.put(url, new Response(body, {
        headers: { "Content-Type": contentType },
      }));
    },
    async cacheDelete(url) {
      const cache = await caches.open(DOWNLOAD_CACHE);
      await cache.delete(url);
    },
    async cacheSize(url) {
      const cache = await caches.open(DOWNLOAD_CACHE);
      const response = await cache.match(url);
      return response ? (await response.blob()).size : 0;
    },
    now() { return Date.now() / 1000; },
  };
}

const downloads = downloadsEnabled
  ? createDownloads(browserDownloadAdapters()) : null;

if (downloadsEnabled) {
  navigator.serviceWorker.register("/music/sw.js").catch(() => {
    /* SW 注册失败: 在线照常, 只是离线放不了 */
  });
  downloads.onChange(syncDownloadIcons);
}

/** 曲目行的下载图标状态 (明文 HTTP 下整列不渲染)。 */
function downloadMarkHTML(trackId) {
  if (!downloads) return "";
  if (downloads.isDownloaded(trackId)) {
    return '<svg viewBox="0 0 24 24" width="17" height="17" aria-hidden="true"><path d="M5 12.5 10 17.5 19 7" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  }
  const state = downloads.stateOf(trackId);
  if (state) {
    return `<small class="dl-pct">${Math.round(state.progress * 100)}%</small>`;
  }
  return ICON_DOWNLOAD;
}

/** 下载状态变了 → 全站行图标刷新 (含已下载栏里的进度)。 */
function syncDownloadIcons() {
  if (!downloads) return;
  for (const mark of document.querySelectorAll("[data-download-track]")) {
    mark.innerHTML = downloadMarkHTML(Number(mark.dataset.downloadTrack));
    mark.classList.toggle("done",
      downloads.isDownloaded(Number(mark.dataset.downloadTrack)));
  }
  if (currentRoute().view === "library"
      && pageState.segment === "downloads") {
    renderDownloadsBody($("#lib-body"));       // 进度/删除即时反映
  }
}

async function downloadTrackFromUI(track) {
  if (!downloads) return;
  try {
    await downloads.downloadTrack(track);
    toast(`已下载: ${track.title}`);
    if (navigator.storage && navigator.storage.persist) {
      navigator.storage.persist().catch(() => {});   // 别让系统清缓存
    }
  } catch (error) {
    toast(`下载失败: ${error.message}`);
  }
}

let downloadAllCancelled = false;   // 下载管理「全部删除」置位, 整批叫停

/** 「下载全部」: 一首下完再下下一首 (几十个 40MB 并发请求在手机上必炸),
    已在库/正在下的跳过; 单首失败不断批, 收尾一并报数。 */
async function downloadAllFromUI(tracks) {
  if (!downloads) return;
  const pending = tracks.filter((track) => track.playable
    && !downloads.isDownloaded(track.track_id)
    && !downloads.stateOf(track.track_id));
  if (!pending.length) {
    toast("都已经在下载里了");
    return;
  }
  downloadAllCancelled = false;
  let done = 0;
  let failed = 0;
  for (const track of pending) {
    if (downloadAllCancelled) return;   // 下载管理里点了全部删除
    try {
      if (await downloads.downloadTrack(track)) done += 1;
    } catch (error) {
      failed += 1;
    }
  }
  toast(failed ? `下载完成 ${done} 首, 失败 ${failed} 首` : `已下载 ${done} 首`);
  if (done && navigator.storage && navigator.storage.persist) {
    navigator.storage.persist().catch(() => {});   // 别让系统清缓存
  }
}

// ------------------------------------------------------------ 公共渲染件

function chipsHTML() {
  return LANGUAGES.map((language) => `
    <button class="chip${language === pageState.language ? " on" : ""}"
            data-language="${language}">${language}</button>`).join("");
}

function bindChips(container) {
  container.addEventListener("click", (event) => {
    const chip = event.target.closest("[data-language]");
    if (!chip || chip.dataset.language === pageState.language) return;
    pageState.language = chip.dataset.language;
    localStorage.setItem("music-language", pageState.language);
    document.querySelectorAll("[data-language]").forEach((element) => {
      element.classList.toggle("on",
        element.dataset.language === pageState.language);
    });
    if (pageState.searchQuery) runSearch();
    else if (currentRoute().view === "library") {
      resetLibraryLists();
      renderLibraryBody();
    }
  });
}

/** 专辑卡 (网格): 封面 + 标题 + 艺人。 */
function albumCardHTML(album) {
  return `
    <button class="album-card" data-album-id="${album.album_id}">
      <span class="art-wrap">
        <img loading="lazy" decoding="async" alt=""
             src="${albumArtworkURL(album)}"
             onerror="this.onerror=null;this.src='${PLACEHOLDER_ARTWORK}'">
        ${album.has_artwork ? "" : '<span class="art-note">♪</span>'}
      </span>
      <b>${escapeHTML(album.title)}</b>
      <small>${escapeHTML(album.artist_name)}</small>
    </button>`;
}

/** 曲目行: 序号/小封面 + 动条 (播放中顶掉序号) + 标题 (不可播标) + 艺人
    + 词标 (❝, 行右侧与下载标平齐) + 下载标 + 时长。下载标不是真按钮
    (行本身是 button, 嵌套非法)。
    leadClass="art" 时引导位放宽 (44px 封面图替序号, 播放列表用)。 */
function trackRowHTML(track, leadHTML, leadClass) {
  return `
    <button class="track-row${track.playable ? "" : " disabled"}"
            data-track-row="${track.track_id}" data-track-id="${track.track_id}">
      <span class="t-lead${leadClass ? ` ${leadClass}` : ""}">${leadHTML || ""}${ICON_BARS}</span>
      <span class="t-main">
        <span class="t-title"><span class="t-title-text">${escapeHTML(track.title)}</span>
          ${track.playable ? "" : `<i class="t-format">${escapeHTML(track.file_format)}</i>`}
        </span>
        <small>${escapeHTML(track.artist)}</small>
      </span>
      ${track.lyrics_available ? `<i class="t-lyric">${ICON_LYRICS}</i>` : ""}
      ${downloadsEnabled ? `
      <span class="t-dl${downloads.isDownloaded(track.track_id) ? " done" : ""}"
            data-download-track="${track.track_id}" role="button" tabindex="-1"
            aria-label="下载">${downloadMarkHTML(track.track_id)}</span>` : ""}
      <span class="t-time">${formatPlaybackTime(track.duration_seconds)}</span>
    </button>`;
}

/** 曲目自己的小封面 (元数据内嵌图; 没有的给音符占位块)。
    接口万一抽不出图 (404) 也退回占位块, 别给用户看裂图。 */
function trackArtHTML(track) {
  return track.has_artwork
    ? `<img class="t-art" loading="lazy" decoding="async" alt=""
            src="${trackArtworkURL(track)}"
            onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'t-art',textContent:'♪'}))">`
    : '<span class="t-art">♪</span>';
}

function artistRowHTML(artist) {
  return `
    <button class="artist-row" data-artist-id="${artist.artist_id}">
      <img loading="lazy" decoding="async" alt="" class="poster"
           src="${artistArtworkURL(artist)}"
           onerror="this.onerror=null;this.src='${PLACEHOLDER_ARTWORK}'">
      <span class="a-main"><b>${escapeHTML(artist.name)}</b>
        <small>${artist.album_count} 张专辑 · ${artist.track_count} 首</small></span>
      <span class="chev">›</span>
    </button>`;
}

/** 播放列表行: 自定义封面 (传过) / 渐变音符块 + 名字 + 规模。
    外面套一层左滑删除的壳 (主页列表行专属, 别的用法没有)。 */
function playlistRowHTML(playlist) {
  const cover = playlistCoverURL(playlist);
  return `
    <div class="swipe-wrap" data-swipe-playlist="${playlist.playlist_id}">
      <button class="playlist-row" data-playlist-id="${playlist.playlist_id}">
        ${cover
          ? `<img class="pl-icon art" loading="lazy" decoding="async" alt="" src="${cover}">`
          : '<span class="pl-icon">♫</span>'}
        <span class="a-main"><b>${escapeHTML(playlist.name)}</b>
          <small>${describeDuration(playlist.duration_seconds, playlist.track_count)}</small></span>
        <span class="chev">›</span>
      </button>
      <button class="swipe-del" aria-label="删除列表">删除</button>
    </div>`;
}

function listPlaceholderHTML(message) {
  return `<div class="list-empty">${message}</div>`;
}

/** 曲目点击 → 开播 (队列 = 所在列表; 不可播提示; 下载标点按 = 下载)。 */
const trackListBindings = new WeakMap();  // 容器 → tracksOf (长按菜单按所在列表开播)
let rowForTrackMenu = null;               // 菜单正对着的那行 (播放要它的列表语境)

function bindTrackLists(container, tracksOf) {
  trackListBindings.set(container, tracksOf);   // 长按菜单按所在列表开播
  container.addEventListener("click", (event) => {
    const mark = event.target.closest("[data-download-track]");
    if (mark) {                          // 下载标优先于整行播放
      const trackId = Number(mark.dataset.downloadTrack);
      const track = (tracksOf() || []).find(
        (item) => item.track_id === trackId);
      if (track && track.playable) downloadTrackFromUI(track);
      return;
    }
    const row = event.target.closest("[data-track-row]");
    if (!row) return;
    const trackId = Number(row.dataset.trackId);
    const tracks = tracksOf();
    const index = tracks.findIndex((track) => track.track_id === trackId);
    if (index < 0) return;
    const track = tracks[index];
    if (!track.playable) {
      toast(`浏览器播不了 ${String(track.file_format).toUpperCase()}`);
      return;
    }
    playerStart(tracks, index);
  });
}

// ------------------------------------------------------------ 左滑删除
// .swipe-wrap 的行左滑露出「删除」钮 (iOS 同款): 横向拖动跟手, 竖向让给
// 滚动 (行 touch-action: pan-y); 松手过半开/不过半弹回。一次只开一行,
// 点别处/滚动/滑另一行都收起, 开着的行点一下也是收起 (不进页不开播)。
// 与长按菜单共存: 长按计时器移动超 10px 自动作废, 这里 8px 内不接管。
// 只认左移: 右移是推入层返回手势 (bindPaneSwipe) 和 iOS 系统边缘返回的
// 地盘, 这里一抢 (setPointerCapture) 层就跟到一半被掐弹回 —— 1.7.0
// 后遗症, 用户点名"返回一半就取消"。
// 尾随 click 的吞法吸取长按菜单的教训 (3f5cd5f): 标记在新按下时清,
// 松手后设备不补发 click 也不至于粘住吞掉下一次真点击。
const SWIPE_REVEAL = 72;             // 删除钮宽度 (px)
let swipeOpenWrap = null;            // 开着的行 (null = 全收)
let swipeDrag = null;                // 拖拽进行中 {wrap,row,startX,startY,base,horizontal,offset,moved}
let swipeSuppressClick = false;      // 松手前横移过: 尾随的 click 吞掉

function closeSwipeRow() {
  if (!swipeOpenWrap) return;
  if (swipeOpenWrap.isConnected && swipeOpenWrap.firstElementChild) {
    swipeOpenWrap.firstElementChild.style.transform = "";
  }
  swipeOpenWrap = null;
}

// 任何滚动 (列表/推入层/页面) 都把开着的行收起来 —— 绑在 document 捕获层,
// scroll 不冒泡, 绑容器收不到祖先 (推入层) 的滚动。
document.addEventListener("scroll", closeSwipeRow, true);

function bindSwipeDelete(container, onDelete) {
  container.addEventListener("pointerdown", (event) => {
    swipeSuppressClick = false;                  // 新按下 = 上一手势翻篇
    if (swipeDrag) {                             // 出界松手没收到 up: 兜底归位
      swipeDrag.row.classList.remove("swiping");
      swipeDrag.row.style.transform =
        swipeDrag.base ? `translateX(${swipeDrag.base}px)` : "";
      swipeDrag = null;
    }
    const wrap = event.target.closest(".swipe-wrap");
    if (!wrap || !wrap.contains(event.target)) { closeSwipeRow(); return; }
    if (event.target.closest(".swipe-del")) return;    // 删除钮: 点按即删
    if (swipeOpenWrap && swipeOpenWrap !== wrap) closeSwipeRow();
    swipeDrag = { wrap, row: wrap.firstElementChild,
                  startX: event.clientX, startY: event.clientY,
                  base: swipeOpenWrap === wrap ? -SWIPE_REVEAL : 0,
                  horizontal: null, offset: 0, moved: false };
  });
  container.addEventListener("pointermove", (event) => {
    if (!swipeDrag) return;
    const dx = event.clientX - swipeDrag.startX;
    const dy = event.clientY - swipeDrag.startY;
    if (swipeDrag.horizontal === null) {
      if (Math.abs(dx) < 8 && Math.abs(dy) < 8) return;
      // 只认左移; 右移/竖移都撒手 (右移归推入层返回手势, 竖移归滚动)
      swipeDrag.horizontal = dx < 0 && Math.abs(dx) > Math.abs(dy);
      if (!swipeDrag.horizontal) { swipeDrag = null; return; }
      swipeDrag.row.classList.add("swiping");   // 拖动跟手, 松手才交给过渡
      try {
        swipeDrag.row.setPointerCapture(event.pointerId);  // 鼠标拖出容器也能收到 up
      } catch (_error) { /* 抓不到也能拖; 出界松手由下一次按下兜底 */ }
    }
    swipeDrag.moved = true;
    // 左移露钮 (可多拖 24px 橡皮筋), 右移最多推回 0
    swipeDrag.offset = Math.min(0, Math.max(-SWIPE_REVEAL - 24,
                                            swipeDrag.base + dx));
    swipeDrag.row.style.transform =
      swipeDrag.offset ? `translateX(${swipeDrag.offset}px)` : "";
  });
  const settle = (cancelled) => {
    const drag = swipeDrag;
    swipeDrag = null;
    if (!drag || !drag.horizontal) return;
    drag.row.classList.remove("swiping");       // 回位/定住交给 CSS 过渡
    if (cancelled) {                              // 浏览器接管手势 (滚动等)
      drag.row.style.transform = drag.base ? `translateX(${drag.base}px)` : "";
      if (drag.base) swipeOpenWrap = drag.wrap;
      return;
    }
    swipeSuppressClick = drag.moved;              // 拖过的松手 click 不开播
    if (drag.offset < -SWIPE_REVEAL / 2) {
      drag.row.style.transform = `translateX(${-SWIPE_REVEAL}px)`;
      swipeOpenWrap = drag.wrap;
    } else {
      drag.row.style.transform = "";
      if (swipeOpenWrap === drag.wrap) swipeOpenWrap = null;
    }
  };
  container.addEventListener("pointerup", () => settle(false));
  container.addEventListener("pointercancel", () => settle(true));
  // 捕获层吃两类点击: 删除钮 (不再冒泡给行点击/开播) 和滑完松手/开着的行
  // 上的尾随 click; 冒泡层的 bindTrackLists/导航因此看不见这两下。
  container.addEventListener("click", async (event) => {
    if (swipeSuppressClick) {
      swipeSuppressClick = false;
      event.stopPropagation();
      event.preventDefault();
      return;
    }
    const del = event.target.closest(".swipe-del");
    if (del) {
      event.stopPropagation();
      event.preventDefault();
      const wrap = del.closest(".swipe-wrap");
      swipeOpenWrap = null;
      await onDelete(wrap);
      return;
    }
    if (swipeOpenWrap && swipeOpenWrap.contains(event.target)) {
      closeSwipeRow();                            // 开着的行点一下 = 收起
      event.stopPropagation();
      event.preventDefault();
    }
  }, true);
}

// ------------------------------------------------------------ 曲目长按菜单
// 任何界面的曲目行 (含「已下载」栏) 长按 500ms / 桌面右键, 弹出菜单:
// 播放 (在所在列表的语境里开播) / 进入艺人主页 / 添加到播放列表 / 分享。
// 全屏页 ⋯ 也走这个菜单 (对着当前曲目直接开, 没有「播放」项)。
let pickerTrack = null;                   // 正在挑列表往里加的曲目
let menuTrackDirect = null;               // 全屏页 ⋯ 直接对着曲目开时用这个

/** 行 → 曲目对象 (沿 DOM 向上找绑过列表的容器; 已下载栏查下载索引)。 */
function trackFromRow(row) {
  const trackId = Number(row.dataset.dlRow || row.dataset.trackRow);
  if (!trackId) return null;
  if (row.classList.contains("dl-row")) {
    return downloads.entries().find((entry) => entry.track_id === trackId)
      || null;
  }
  let scope = row.parentElement;
  while (scope) {
    const tracksOf = trackListBindings.get(scope);
    if (tracksOf) {
      return (tracksOf() || []).find(
        (track) => track.track_id === trackId) || null;
    }
    scope = scope.parentElement;
  }
  return null;
}

/** 菜单里的「播放」: 与点行同一条路径 (队列 = 所在列表)。 */
function playTrackFromMenu(track, row) {
  if (row?.classList.contains("dl-row")) {
    playDownloadedRow(track.track_id);
    return;
  }
  const tracks = row ? tracksOfRow(row) || [] : [];
  const index = tracks.findIndex((item) => item.track_id === track.track_id);
  if (!track.playable) {
    toast(`浏览器播不了 ${String(track.file_format).toUpperCase()}`);
    return;
  }
  if (index >= 0) playerStart(tracks, index);
  else playerStart([track], 0);           // 列表没找着 (视图已换): 单曲播
}

function tracksOfRow(row) {
  let scope = row.parentElement;
  while (scope) {
    const tracksOf = trackListBindings.get(scope);
    if (tracksOf) return tracksOf() || null;
    scope = scope.parentElement;
  }
  return null;
}

/** 分享 = 后端开一条 24 小时免登录的 uuid 链接, 有系统分享就发 URL
    (歌名 - 歌手 + 链接), 没有 (明文 HTTP) 退化为复制链接。 */
async function shareByLink(kind, id, title, text) {
  let url = "";
  try {
    const made = await fetchJSON("/music/api/shares", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind, id }),
    });
    url = `${location.origin}/music/share/${made.token}`;
  } catch (error) {
    toast(`分享链接没生成: ${error.message}`);
    return;
  }
  if (typeof navigator.share === "function") {
    try { await navigator.share({ title, text, url }); }
    catch (_error) { /* 用户取消/环境拒绝: 不算失败 */ }
    return;
  }
  let copied = false;
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(url);
      copied = true;
    } else {
      const input = document.createElement("textarea");
      input.value = url;
      document.body.appendChild(input);
      input.select();
      copied = document.execCommand("copy");
      input.remove();
    }
  } catch (_error) { /* 复制失败走下面的提示 */ }
  toast(copied ? "链接已复制, 24 小时内有效" : "这个环境分享不了");
}

async function shareTrack(track) {
  await shareByLink("track", track.track_id, track.title,
                    `${track.title} - ${track.artist}`);
}

/** 列表页的分享钮: 分享整个播放列表 (打开的人能看能听整张)。 */
async function sharePlaylist(playlist) {
  await shareByLink("playlist", playlist.playlist_id, playlist.name,
                    `播放列表「${playlist.name}」`);
}

function openTrackMenu(row, point) {
  const track = trackFromRow(row);
  if (!track || row.classList.contains("busy")
      || row.classList.contains("disabled")) return;
  rowForTrackMenu = row;
  menuTrackDirect = null;
  $("#menu-track-title").textContent = track.title;
  $("#menu-track-artist").textContent = track.artist;
  $("#track-menu-artist").hidden = !track.artist_id;   // 老下载索引没存艺人号
  $("#track-menu").querySelector('[data-track-action="play"]').hidden = false;
  const menu = $("#track-menu");
  menu.hidden = false;
  $("#track-menu-mask").hidden = false;
  placeMenuAt(menu, point);
}

/** 全屏页 ⋯: 对着当前曲目开菜单 (没有行, 「播放」项藏掉 — 正在播呢)。 */
function openTrackMenuForTrack(track, point) {
  rowForTrackMenu = null;
  menuTrackDirect = track;
  $("#menu-track-title").textContent = track.title;
  $("#menu-track-artist").textContent = track.artist;
  $("#track-menu-artist").hidden = !track.artist_id;
  $("#track-menu").querySelector('[data-track-action="play"]').hidden = true;
  const menu = $("#track-menu");
  menu.hidden = false;
  $("#track-menu-mask").hidden = false;
  placeMenuAt(menu, point);
}

/** 菜单定位: 触点下方, 出屏就翻到上方/收边 (fixed 元素, 坐标即视口)。 */
function placeMenuAt(menu, point) {
  menu.style.left = "0px";
  menu.style.top = "0px";
  const rect = menu.getBoundingClientRect();
  const margin = 10;
  const width = document.documentElement.clientWidth;
  const height = document.documentElement.clientHeight;
  const x = Math.min(Math.max(point.x - rect.width / 2, margin),
                     width - rect.width - margin);
  let y = point.y + 14;
  if (y + rect.height > height - margin) y = point.y - rect.height - 14;
  menu.style.left = `${Math.max(margin, Math.round(x))}px`;
  menu.style.top = `${Math.max(margin, Math.round(y))}px`;
}

function closeTrackMenu() {
  $("#track-menu").hidden = true;
  $("#track-menu-mask").hidden = true;
  rowForTrackMenu = null;
  menuTrackDirect = null;
}

// 封面菜单: 长按/右键播放列表大封面弹「换封面 / 移除封面」(共用曲目菜单的遮罩)。
// 长按开过菜单的那个元素 (行/封面): 它随后补发的尾随 click 要吞。
// 按元素吞而不是一次性吞: 有的设备补发得晚 (能落到下一次点击之后),
// 一次性的标记会被先到的正常点击清掉, 迟到的那下就砸回长按的行上,
// 表现成"菜单没点到, 却播了别的歌"。落点离开这个元素的手势都放行
// (长按着滑到菜单项上松手 = 选它, 天经地义)。
let suppressTrailingTarget = null;
let coverMenuPlaylistId = 0;
let coverMenuPlaylistName = "";

function openCoverMenu(playlistId, name, hasCover, point) {
  coverMenuPlaylistId = playlistId;
  coverMenuPlaylistName = name;
  $("#menu-cover-title").textContent = name;
  $("#cover-menu-remove").hidden = !hasCover;   // 没有自定义封面就没得移除
  const menu = $("#cover-menu");
  menu.hidden = false;
  $("#track-menu-mask").hidden = false;
  placeMenuAt(menu, point);
}

function closeCoverMenu() {
  $("#cover-menu").hidden = true;
  $("#track-menu-mask").hidden = true;
}

/** 大封面的手势: 点按 = 直接换封面; 长按 500ms / 电脑右键 = 封面菜单。
    吞尾随 click 的标记绑在"开菜单的那次按压"上, 新按下即清 (同曲目行长按)。 */
function bindCoverPress(playlistId, name, hasCover) {
  const tap = $("#cover-tap");
  let pressTimer = 0;
  let pressPoint = null;
  let pressPointerId = null;
  const cancelPress = (event) => {
    if (event && event.pointerId !== undefined
        && event.pointerId !== pressPointerId) return;
    clearTimeout(pressTimer);
    pressTimer = 0;
    pressPoint = null;
  };
  tap.addEventListener("pointerdown", (event) => {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    pressPoint = { x: event.clientX, y: event.clientY };
    pressPointerId = event.pointerId;
    clearTimeout(pressTimer);
    pressTimer = setTimeout(() => {
      pressTimer = 0;
      suppressTrailingTarget = tap;    // 抬手补发的 click 不许触发换封面
      openCoverMenu(playlistId, name, hasCover, pressPoint);
    }, 500);
  });
  tap.addEventListener("pointermove", (event) => {
    if (!pressTimer || !pressPoint) return;
    if (Math.hypot(event.clientX - pressPoint.x,
                   event.clientY - pressPoint.y) > 10) cancelPress(event);
  });
  tap.addEventListener("pointerup", cancelPress);
  tap.addEventListener("pointercancel", cancelPress);
  tap.addEventListener("contextmenu", (event) => {
    event.preventDefault();              // 封面上的长按/右键归菜单管
    cancelPress();
    if (!$("#cover-menu").hidden) return;    // 安卓长按: 计时器可能已经开了
    openCoverMenu(playlistId, name, hasCover,
                  { x: event.clientX, y: event.clientY });
  });
  tap.addEventListener("click", () => {
    $("#cover-file").click();            // 点大封面直接换 (隐藏的文件选择器)
  });
}

$("#track-menu-mask").addEventListener("click", () => {
  closeTrackMenu();
  closeCoverMenu();
});

$("#cover-menu").addEventListener("click", async (event) => {
  const action = event.target.closest("[data-cover-action]");
  if (!action) return;
  closeCoverMenu();
  if (action.dataset.coverAction === "change") {
    $("#cover-file").click();
    return;
  }
  if (action.dataset.coverAction === "remove") {
    if (!window.confirm(`移除「${coverMenuPlaylistName}」的自定义封面?`)) return;
    try {
      await fetchJSON(`/music/api/playlists/${coverMenuPlaylistId}/cover`,
                      { method: "DELETE" });
      toast("封面已移除");
      renderPlaylistView(coverMenuPlaylistId);
    } catch (error) {
      toast(`没移除掉: ${error.message}`);
    }
  }
});

$("#track-menu").addEventListener("click", async (event) => {
  const action = event.target.closest("[data-track-action]");
  if (!action) return;
  const row = rowForTrackMenu;             // closeTrackMenu 会清, 先抓住
  const directTrack = menuTrackDirect;
  const track = row ? trackFromRow(row) : directTrack;
  closeTrackMenu();
  if (!track) return;
  if (action.dataset.trackAction === "play") playTrackFromMenu(track, row);
  else if (action.dataset.trackAction === "artist") navigate(`artist/${track.artist_id}`);
  else if (action.dataset.trackAction === "share") shareTrack(track);
  else if (action.dataset.trackAction === "playlist") openPlaylistPicker(track);
});

// 全屏页 ⋯ / ♥: ⋯ 开长按菜单 (没有"播放"项), ♥ 直接开加歌选择单。
// 当前曲目跟着换曲走 (恢复现场那首也接得上)。
let fpCurrentTrack = null;
onTrackChange((track) => { fpCurrentTrack = track; });
fpCurrentTrack = playerCurrentTrack();

$("#fp-menu-btn").addEventListener("click", (event) => {
  if (!fpCurrentTrack) return;
  openTrackMenuForTrack(fpCurrentTrack, { x: event.clientX, y: event.clientY });
});
$("#fp-like-btn").addEventListener("click", () => {
  if (fpCurrentTrack) openPlaylistPicker(fpCurrentTrack);
});

// 长按检测: 指针按下起 500ms 计时, 移动超 10px / 抬起 / 取消都作废;
// contextmenu (桌面右键 + 安卓长按) 直接开 (计时器先开过就不重复)。
let trackPressTimer = 0;
let trackPressPoint = null;
let trackPressPointerId = null;

function cancelTrackPress(event) {
  if (event && event.pointerId !== undefined
      && event.pointerId !== trackPressPointerId) return;
  clearTimeout(trackPressTimer);
  trackPressTimer = 0;
  trackPressPoint = null;
}

document.addEventListener("pointerdown", (event) => {
  if (event.pointerType === "mouse" && event.button !== 0) return;  // 右键走 contextmenu
  const row = event.target.closest("[data-track-row], .dl-row");
  if (!row || row.classList.contains("disabled")) return;
  trackPressPoint = { x: event.clientX, y: event.clientY };
  trackPressPointerId = event.pointerId;
  clearTimeout(trackPressTimer);
  trackPressTimer = setTimeout(() => {
    trackPressTimer = 0;
    suppressTrailingTarget = row;
    openTrackMenu(row, trackPressPoint);
  }, 500);
});
document.addEventListener("pointermove", (event) => {
  if (!trackPressTimer || !trackPressPoint) return;
  if (Math.hypot(event.clientX - trackPressPoint.x,
                 event.clientY - trackPressPoint.y) > 10) cancelTrackPress(event);
});
document.addEventListener("pointerup", cancelTrackPress);
document.addEventListener("pointercancel", cancelTrackPress);
document.addEventListener("contextmenu", (event) => {
  const row = event.target.closest("[data-track-row], .dl-row");
  if (!row) return;                      // 别处的右键 (选歌词等) 不拦
  event.preventDefault();
  cancelTrackPress();
  if (!$("#track-menu").hidden) return;  // 安卓长按: 计时器可能已经开了
  suppressTrailingTarget = row;
  openTrackMenu(row, { x: event.clientX, y: event.clientY });
});
// 长按开了菜单, 抬手补发的 click 会落回长按的那个元素上 —— 吞掉;
// 点了别处 (菜单项/遮罩) 就翻篇。见 suppressTrailingTarget 的说明。
document.addEventListener("click", (event) => {
  if (!suppressTrailingTarget) return;
  if (suppressTrailingTarget.contains(event.target)) {
    event.stopPropagation();
    event.preventDefault();
    return;
  }
  suppressTrailingTarget = null;
}, true);

// ------------------------------------------------ 添加到播放列表 (选择单)

function closePlaylistPicker() {
  $("#picker-mask").hidden = true;
  $("#picker-sheet").hidden = true;
  pickerTrack = null;
}

function openPlaylistPicker(track) {
  pickerTrack = track;
  $("#picker-track-title").textContent = track.title;
  $("#picker-name").value = "";
  $("#picker-mask").hidden = false;
  $("#picker-sheet").hidden = false;
  renderPlaylistPicker();
}

/** 列表清单 (纯加歌的选择单, 列表删除在各自的详情页; 新建的排前面);
 * 空态给新建引导。 */
async function renderPlaylistPicker() {
  const list = $("#picker-list");
  list.innerHTML = listPlaceholderHTML("加载中…");
  let playlists = [];
  try {
    playlists = (await fetchJSON("/music/api/playlists")).playlists;
  } catch (error) {
    list.innerHTML = listPlaceholderHTML(`列表没拉到: ${error.message}`);
    return;
  }
  if (!playlists.length) {
    list.innerHTML = listPlaceholderHTML("还没有播放列表; 起个名字新建一个");
    return;
  }
  list.innerHTML = playlists.map((playlist) => {
    const cover = playlistCoverURL(playlist);
    return `
    <button class="picker-row" data-picker-playlist="${playlist.playlist_id}">
      ${cover
        ? `<img class="pl-icon art" loading="lazy" decoding="async" alt="" src="${cover}">`
        : '<span class="pl-icon">♫</span>'}
      <span class="a-main"><b>${escapeHTML(playlist.name)}</b>
        <small>${describeDuration(playlist.duration_seconds, playlist.track_count)}</small></span>
    </button>`;
  }).join("");
}

async function addTrackToPlaylist(playlistId, playlistName) {
  if (!pickerTrack) return;
  try {
    await fetchJSON(`/music/api/playlists/${playlistId}/tracks`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ track_id: pickerTrack.track_id }),
    });
    toast(`已加入「${playlistName}」`);
    renderPlaylistPicker();               // 刷新计数, 也能接着加别的列表
  } catch (error) {
    if (error.status === 409) {           // 已在列表里: 直说原因, 不算没加成
      toast(error.message);
    } else {
      toast(`没加进去: ${error.message}`);
    }
  }
}

$("#picker-list").addEventListener("click", async (event) => {
  const pick = event.target.closest("[data-picker-playlist]");
  if (pick) await addTrackToPlaylist(Number(pick.dataset.pickerPlaylist),
                                     pick.querySelector("b").textContent);
});

$("#picker-create").addEventListener("click", async () => {
  const input = $("#picker-name");
  const name = input.value.trim();
  if (!name) { toast("先给新列表起个名字"); input.focus(); return; }
  if (!pickerTrack) return;
  try {
    const playlist = await fetchJSON("/music/api/playlists", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    input.value = "";
    await addTrackToPlaylist(playlist.playlist_id, playlist.name);
  } catch (error) {
    toast(`没建起来: ${error.message}`);
  }
});

$("#picker-close").addEventListener("click", closePlaylistPicker);
$("#picker-mask").addEventListener("click", closePlaylistPicker);

function syncPlayerIndicators() {
  updatePlayButtons();       // 播放器模块的行高亮同步 (换视图后行是新 DOM)
}

// ------------------------------------------------------------ 主页

function renderHomeView() {
  $("#root-view").innerHTML = `
    <div class="section-head">播放列表</div>
    <div id="home-playlists">${listPlaceholderHTML("加载中…")}</div>
    <div class="section-head">最近播放</div>
    <div id="home-recent">${listPlaceholderHTML("加载中…")}</div>`;
  // 事件绑在容器上 (内容是异步重铺的, 绑内容会重复累加)
  $("#home-playlists").addEventListener("click", (event) => {
    const row = event.target.closest("[data-playlist-id]");
    if (row) navigate(`playlist/${row.dataset.playlistId}`);
  });
  // 列表行左滑露出删除: 删掉后就地抽行, 不整页重铺
  bindSwipeDelete($("#home-playlists"), async (wrap) => {
    const playlistId = Number(wrap.dataset.swipePlaylist);
    try {
      await fetchJSON(`/music/api/playlists/${playlistId}`, { method: "DELETE" });
      wrap.remove();
      toast("已删除");
    } catch (error) {
      toast(`没删掉: ${error.message}`);
    }
  });
  bindTrackLists($("#home-recent"), () => pageState.homeRecent || []);
  loadHomePlaylists();
  loadHomeRecent();
}

async function loadHomePlaylists() {
  let playlists = null;
  try {
    playlists = (await fetchJSON("/music/api/playlists")).playlists;
  } catch (_error) { /* 下面占位文案兜底 */ }
  const element = $("#home-playlists");
  if (!element || !element.isConnected) return;   // 已被换掉 (二级层下重铺也一样保护)
  element.innerHTML = playlists && playlists.length
    ? playlists.map(playlistRowHTML).join("")
    : listPlaceholderHTML("还没有播放列表; 长按任意歌曲就能新建一个");
}

async function loadHomeRecent() {
  let tracks = null;
  try {
    tracks = (await fetchJSON("/music/api/plays/recent?limit=20")).tracks;
  } catch (_error) { /* 下面占位文案兜底 */ }
  const element = $("#home-recent");
  if (!element || !element.isConnected) return;   // 已被换掉 (二级层下重铺也一样保护)
  pageState.homeRecent = tracks || [];
  element.innerHTML = pageState.homeRecent.length
    ? pageState.homeRecent.map(
        (track) => trackRowHTML(track, trackArtHTML(track), "art")).join("")
    : listPlaceholderHTML("听过歌就会出现在这里, 各账号各记各的");
}

// ------------------------------------------------------------ 资料库页

function resetLibraryLists() {
  pageState.lists = {};
}

function renderLibraryView() {
  $("#root-view").innerHTML = `
    <div class="seg" id="lib-seg">
      ${LIBRARY_SEGMENTS.map(([key, label]) => `
        <button data-segment="${key}"${key === pageState.segment ? ' class="on"' : ""}>${label}</button>`).join("")}
    </div>
    <div class="chips" id="lib-chips">${chipsHTML()}</div>
    <div id="lib-body"></div>`;
  $("#lib-seg").addEventListener("click", (event) => {
    const button = event.target.closest("[data-segment]");
    if (!button || button.dataset.segment === pageState.segment) return;
    pageState.segment = button.dataset.segment;
    localStorage.setItem("music-segment", pageState.segment);
    document.querySelectorAll("#lib-seg [data-segment]")
      .forEach((item) => item.classList.toggle("on",
        item.dataset.segment === pageState.segment));
    syncChipsVisibility();
    renderLibraryBody();
  });
  bindChips($("#lib-chips"));
  bindLibraryBody();
  syncChipsVisibility();
  renderLibraryBody();
}

/** 语种筛选只对专辑/歌曲有意义; 艺人/已下载段把筛选行收起来。 */
function syncChipsVisibility() {
  $("#lib-chips").hidden = pageState.segment === "downloads";
}

/** 资料库容器事件 (专辑/艺人跳转 + 曲目开播 + 下载管理), 只绑一次。 */
function bindLibraryBody() {
  const body = $("#lib-body");
  body.addEventListener("click", (event) => {
    const albumCard = event.target.closest("[data-album-id]");
    if (albumCard) { navigate(`album/${albumCard.dataset.albumId}`); return; }
    const artistRow = event.target.closest("[data-artist-id]");
    if (artistRow) { navigate(`artist/${artistRow.dataset.artistId}`); return; }
    const clearButton = event.target.closest("#dl-clear-all");
    if (clearButton) {
      const count = downloads.entries().filter((entry) => !entry.state).length;
      if (window.confirm(`删除全部 ${count} 首已下载歌曲?`)) {
        downloadAllCancelled = true;   // 若有「下载全部」在跑, 整批叫停
        downloads.removeAll()
          .then(() => toast("已清空下载"))
          .catch((error) => toast(`清空失败: ${error.message}`));
      }
      return;
    }
    const removeButton = event.target.closest("[data-dl-remove]");
    if (removeButton) {
      const cancelling = removeButton.textContent.trim() === "取消";
      downloads.removeDownload(Number(removeButton.dataset.dlRemove))
        .then(() => toast(cancelling ? "已取消下载" : "已删除下载"))
        .catch((error) => toast(`删除失败: ${error.message}`));
      return;
    }
    const downloadRow = event.target.closest("[data-dl-row]");
    if (downloadRow) { playDownloadedRow(Number(downloadRow.dataset.dlRow)); }
  });
  bindTrackLists(body, () => {
    const list = pageState.lists[pageState.segment];
    return list ? list.items : [];
  });
}

/** 已下载栏点行开播 (队列 = 已下载列表, 下载中的除外)。 */
function playDownloadedRow(trackId) {
  const tracks = downloads.entries().filter((entry) => !entry.state)
    .map((entry) => ({ ...entry, playable: true, lyrics_available: false,
                       file_format: "flac" }));
  const index = tracks.findIndex((track) => track.track_id === trackId);
  if (index >= 0) playerStart(tracks, index);
}

function renderLibraryBody() {
  const body = $("#lib-body");
  const segment = pageState.segment;
  body.innerHTML = "";
  if (segment === "downloads") { renderDownloadsBody(body); return; }
  const list = pageState.lists[segment];
  if (list && list.items.length) { appendListPage(body, segment, list); return; }
  body.innerHTML = listPlaceholderHTML("加载中…");
  loadListPage(segment);
}

let downloadsRenderToken = 0;   // 重铺计数: 让在途的异步统计结果作废

/** "已下载"段 = 下载管理: 合计大小/每首大小/删除与取消/一键清空
 *  (明文 HTTP 下没有这一套, 说清楚)。 */
async function renderDownloadsBody(body) {
  if (!downloadsEnabled) {
    body.innerHTML = listPlaceholderHTML(
      "离线下载需要 HTTPS 环境 (当前是明文 HTTP); 局域网在线听不受影响");
    return;
  }
  const entries = downloads.entries();
  if (!entries.length) {
    body.innerHTML = listPlaceholderHTML(
      "还没有下载的歌曲; 曲目行右侧的下载标就是下载");
    return;
  }
  const token = ++downloadsRenderToken;
  body.innerHTML = `
    <div class="dl-stats">
      <span class="dl-stats-main">
        <strong id="dl-total">统计中…</strong>
        <small id="dl-quota"></small>
      </span>
      <button class="dl-clear" id="dl-clear-all">全部删除</button>
    </div>
    ${entries.map((entry) => `
    <div class="dl-row${entry.state ? " busy" : ""}" data-dl-row="${entry.track_id}">
      ${entry.state
        ? '<span class="t-art">♪</span>'
        : `<img class="t-art" loading="lazy" decoding="async" alt=""
                src="/music/media/tracks/${entry.track_id}/artwork"
                onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'t-art',textContent:'♪'}))">`}
      <span class="t-main">
        <span class="t-title"><span class="t-title-text">${escapeHTML(entry.title || `曲目 ${entry.track_id}`)}</span></span>
        <small>${escapeHTML(entry.artist || "下载中…")}</small>
      </span>
      ${entry.state
        ? `<span class="dl-state">${Math.round(entry.state.progress * 100)}%</span>`
        : `<span class="dl-state" data-dl-size="${entry.track_id}">…</span>`}
      <button class="dl-remove" data-dl-remove="${entry.track_id}"
              aria-label="${entry.state ? "取消下载" : "删除下载"}">${entry.state ? "取消" : "删除"}</button>
    </div>`).join("")}`;
  if (entries.some((entry) => entry.state)) return;   // 有下载在跑: 等完成再量, 免得白量
  const usage = await downloads.storageUsage();
  if (token !== downloadsRenderToken) return;         // 期间又重铺了, 结果作废
  const total = $("#dl-total");
  if (total) {
    total.textContent = `${usage.entries.length} 首 · ${formatBytes(usage.totalBytes)}`;
  }
  for (const row of usage.entries) {
    const size = body.querySelector(`[data-dl-size="${row.track_id}"]`);
    if (size) size.textContent = formatBytes(row.bytes);
  }
  if (navigator.storage && navigator.storage.estimate) {
    navigator.storage.estimate().then((estimate) => {
      if (token !== downloadsRenderToken) return;
      const quota = $("#dl-quota");
      if (quota && estimate && estimate.quota) {
        quota.textContent = `占手机存储 ${formatBytes(estimate.usage || 0)}`;
      }
    }).catch(() => {});
  }
}

async function loadListPage(segment) {
  if (pageState.lists[segment]) return;
  const list = { items: [], total: 0, offset: 0, renderedCount: 0,
                 done: false, loading: true };
  pageState.lists[segment] = list;
  await fetchListPage(segment, list);
  const body = $("#lib-body");
  if (!body || !body.isConnected) return;      // 已被换掉
  body.innerHTML = "";
  appendListPage(body, segment, list);
  syncPlayerIndicators();
}

async function fetchListPage(segment, list) {
  try {
    const parameters = new URLSearchParams({ language: pageState.language, limit: "60" });
    if (segment === "albums") parameters.set("sort", "title");
    if (segment === "songs") parameters.set("limit", "100");
    parameters.set("offset", String(list.offset));
    const endpoint = segment === "artists" ? "/music/api/artists"
      : segment === "songs" ? "/music/api/tracks" : "/music/api/albums";
    const data = await fetchJSON(`${endpoint}?${parameters}`);
    list.items.push(...(segment === "artists" ? data.artists
      : segment === "songs" ? data.tracks : data.albums));
    list.total = data.total_count;
    list.offset = list.items.length;
    list.done = list.offset >= list.total;
  } catch (error) {
    toast(`加载失败: ${error.message}`);
  } finally {
    list.loading = false;
  }
}

/** 把新到的一页铺进容器 + 哨兵; 哨兵还在屏内就续载 (IO 只在进出时回调)。
    追加而不重铺: 图片已经加载的格子不闪。 */
function appendListPage(body, segment, list) {
  const firstRender = !body.querySelector(".list-sentinel")
    && !body.querySelector(".album-grid") && !body.querySelector(".track-row")
    && !body.querySelector(".artist-row");
  if (firstRender && !list.items.length) {
    body.innerHTML = listPlaceholderHTML(
      pageState.language === "全部" ? "曲库还是空的" : "这个语种下没有内容");
    return;
  }
  const existingSentinel = body.querySelector(".list-sentinel");
  if (existingSentinel) existingSentinel.remove();
  const added = list.items.slice(list.renderedCount || 0);
  if (segment === "artists") {
    body.insertAdjacentHTML("beforeend", added.map(artistRowHTML).join(""));
  } else if (segment === "songs") {
    body.insertAdjacentHTML("beforeend", added.map((track, offset) => trackRowHTML(
      track, `<span class="t-index">${(list.renderedCount || 0) + offset + 1}</span>`)).join(""));
  } else {
    let grid = body.querySelector(".album-grid");
    if (!grid) {
      body.insertAdjacentHTML("beforeend", '<div class="album-grid"></div>');
      grid = body.querySelector(".album-grid");
    }
    grid.insertAdjacentHTML("beforeend", added.map(albumCardHTML).join(""));
  }
  list.renderedCount = list.items.length;
  if (!list.done) {
    body.insertAdjacentHTML("beforeend",
      '<div class="list-sentinel" aria-hidden="true"></div>');
    observeSentinel(body, segment, list);
  }
}

function observeSentinel(body, segment, list) {
  const sentinel = body.querySelector(".list-sentinel");
  if (!sentinel) return;
  const continueLoading = async () => {
    if (list.loading || list.done) return;
    list.loading = true;
    await fetchListPage(segment, list);
    appendListPage(body, segment, list);    // 哨兵重挂, 下一轮续命
    syncPlayerIndicators();
  };
  const observer = new IntersectionObserver((entries) => {
    if (entries.some((entry) => entry.isIntersecting)) continueLoading();
  }, { rootMargin: "300px" });
  observer.observe(sentinel);
  // 列表不满一屏时 IO 不会再回调 → 主动续载 (IO 只在进出过渡时回调)
  if (sentinel.getBoundingClientRect().top < window.innerHeight) continueLoading();
}

// ------------------------------------------------------------ 专辑页

async function renderAlbumView(albumId, target) {
  target = target || pushPaneTarget();    // 二级层薄层; 兜底 #main (无层时)
  target.innerHTML = listPlaceholderHTML("加载中…");
  let page = null;
  try {
    page = await fetchJSON(`/music/api/albums/${albumId}`);
  } catch (error) {
    target.innerHTML = listPlaceholderHTML(`加载失败: ${error.message}`);
    return;
  }
  const album = page.album;
  const playable = page.tracks.filter((track) => track.playable);
  target.innerHTML = `
    <div class="album-hero">
      <img alt="" src="${albumArtworkURL(album)}"
           onerror="this.onerror=null;this.src='${PLACEHOLDER_ARTWORK}'">
      <div class="hero-txt">
        <h2>${escapeHTML(album.title)}</h2>
        <button class="hero-artist" data-artist-id="${album.artist_id}">${escapeHTML(album.artist_name)}</button>
        <small>${escapeHTML([album.year || "",
          describeDuration(album.duration_seconds, album.track_count),
          formatAddedDate(album.added_at) && `入库 ${formatAddedDate(album.added_at)}`]
          .filter(Boolean).join(" · "))}</small>
      </div>
    </div>
    <div class="action-row">
      <button class="action primary" id="album-play" ${playable.length ? "" : "disabled"}>
        ${ICON_ACTION_PLAY} 播放</button>
      <button class="action" id="album-shuffle" ${playable.length ? "" : "disabled"}>
        ${ICON_ACTION_SHUFFLE} 随机</button>
      ${downloadsEnabled ? `
      <button class="action" id="album-download" ${playable.length ? "" : "disabled"}>
        ${ICON_DOWNLOAD} 下载全部</button>` : ""}
    </div>
    <div class="track-list" id="album-tracks">
      ${page.tracks.map((track, index) => trackRowHTML(track,
        `<span class="t-index">${track.track_number || index + 1}</span>`)).join("")}
    </div>`;
  target.querySelector(".hero-artist").addEventListener("click", (event) => {
    navigate(`artist/${event.currentTarget.dataset.artistId}`);
  });
  target.querySelector("#album-play").addEventListener("click", () => {
    playerStart(page.tracks, page.tracks.indexOf(playable[0]));
  });
  target.querySelector("#album-shuffle").addEventListener("click", () => {
    playerStart(page.tracks, page.tracks.indexOf(playable[0]), true);
  });
  const albumDownload = target.querySelector("#album-download");
  if (albumDownload) {
    albumDownload.addEventListener("click", () => downloadAllFromUI(page.tracks));
  }
  bindTrackLists(target.querySelector("#album-tracks"), () => page.tracks);
  syncPlayerIndicators();
}

// ------------------------------------------------------------ 艺人页

async function renderArtistView(artistId, target) {
  target = target || pushPaneTarget();    // 二级层薄层; 兜底 #main (无层时)
  target.innerHTML = listPlaceholderHTML("加载中…");
  let page = null;
  try {
    page = await fetchJSON(`/music/api/artists/${artistId}`);
  } catch (error) {
    target.innerHTML = listPlaceholderHTML(`加载失败: ${error.message}`);
    return;
  }
  const artist = page.artist;
  target.innerHTML = `
    <div class="artist-hero">
      <img alt="" src="${artistArtworkURL(artist)}"
           onerror="this.onerror=null;this.src='${PLACEHOLDER_ARTWORK}'">
      <h2>${escapeHTML(artist.name)}</h2>
      <small>${artist.album_count} 张专辑 · ${artist.track_count} 首</small>
    </div>
    <div class="action-row">
      <button class="action primary" id="artist-play">${ICON_ACTION_PLAY} 播放</button>
      <button class="action" id="artist-shuffle">${ICON_ACTION_SHUFFLE} 随机</button>
    </div>
    <div class="section-head">专辑</div>
    <div class="album-grid" id="artist-albums">
      ${page.albums.map(albumCardHTML).join("")}
    </div>`;
  const playArtist = async (shuffle) => {
    try {
      const albumPages = await Promise.all(page.albums.map(
        (album) => fetchJSON(`/music/api/albums/${album.album_id}`)));
      const tracks = albumPages.flatMap((albumPage) => albumPage.tracks);
      if (!tracks.length) { toast("这位艺人还没有能播的曲目"); return; }
      playerStart(tracks, 0, shuffle);
    } catch (error) {
      toast(`加载失败: ${error.message}`);
    }
  };
  target.querySelector("#artist-play").addEventListener("click", () => playArtist(false));
  target.querySelector("#artist-shuffle").addEventListener("click", () => playArtist(true));
  target.querySelector("#artist-albums").addEventListener("click", (event) => {
    const card = event.target.closest("[data-album-id]");
    if (card) navigate(`album/${card.dataset.albumId}`);
  });
}

// ------------------------------------------------------------ 播放列表页

async function renderPlaylistView(playlistId, target) {
  target = target || pushPaneTarget();    // 二级层薄层; 兜底 #main (无层时)
  target.innerHTML = listPlaceholderHTML("加载中…");
  let page = null;
  try {
    page = await fetchJSON(`/music/api/playlists/${playlistId}`);
  } catch (error) {
    target.innerHTML = listPlaceholderHTML(`加载失败: ${error.message}`);
    return;
  }
  const playlist = page.playlist;
  const playable = page.tracks.filter((track) => track.playable);
  const cover = playlistCoverURL(playlist);
  const coverLabel = cover ? "换封面" : "设置封面";
  target.innerHTML = `
    <div class="album-hero">
      <button class="pl-cover-btn" id="cover-tap" aria-label="${coverLabel}"
              title="${coverLabel}">
        ${cover
          ? `<img class="pl-icon big art" alt="" src="${cover}">`
          : '<div class="pl-icon big">♫</div>'}
        <span class="cover-hint" aria-hidden="true">${ICON_ACTION_IMAGE}</span>
      </button>
      <div class="hero-txt">
        <h2>${escapeHTML(playlist.name)}</h2>
        <small>${escapeHTML(describeDuration(
          playlist.duration_seconds, playlist.track_count))}</small>
      </div>
    </div>
    <div class="action-row">
      <button class="action icon primary" id="playlist-play" title="播放"
              aria-label="播放" ${playable.length ? "" : "disabled"}>
        ${ICON_ACTION_PLAY}</button>
      <button class="action icon" id="playlist-shuffle" title="随机播放"
              aria-label="随机播放" ${playable.length ? "" : "disabled"}>
        ${ICON_ACTION_SHUFFLE}</button>
      ${downloadsEnabled ? `
      <button class="action icon" id="playlist-download" title="下载全部"
              aria-label="下载全部" ${playable.length ? "" : "disabled"}>
        ${ICON_DOWNLOAD}</button>` : ""}
      <button class="action icon" id="playlist-share" title="分享"
              aria-label="分享">${ICON_ACTION_SHARE}</button>
      <button class="action icon" id="playlist-delete" title="删除列表"
              aria-label="删除列表">${ICON_ACTION_TRASH}</button>
    </div>
    <div class="track-list" id="playlist-tracks">
      ${page.tracks.map((track) => `
        <div class="swipe-wrap" data-swipe-track="${track.track_id}">
          ${trackRowHTML(track, trackArtHTML(track), "art")}
          <button class="swipe-del" aria-label="从列表移除">删除</button>
        </div>`).join("")}
    </div>`;
  target.querySelector("#playlist-play").addEventListener("click", () => {
    playerStart(page.tracks, page.tracks.indexOf(playable[0]));
  });
  target.querySelector("#playlist-shuffle").addEventListener("click", () => {
    playerStart(page.tracks, page.tracks.indexOf(playable[0]), true);
  });
  const playlistDownload = target.querySelector("#playlist-download");
  if (playlistDownload) {
    playlistDownload.addEventListener("click", () => downloadAllFromUI(page.tracks));
  }
  target.querySelector("#playlist-share").addEventListener("click", () => {
    sharePlaylist(playlist);
  });
  bindCoverPress(playlistId, playlist.name, !!cover);
  target.querySelector("#playlist-delete").addEventListener("click", async () => {
    if (!window.confirm(`删除播放列表「${playlist.name}」?`)) return;
    try {
      await fetchJSON(`/music/api/playlists/${playlistId}`, { method: "DELETE" });
      toast("已删除");
      navigate("home");                  // 回主页, 列表段重铺自然不再有它
      if (pushStack.length) renderRootView("home");   // 一级页就在层底下, 趁滑走前重铺
    } catch (error) {
      toast(`没删掉: ${error.message}`);
    }
  });
  bindTrackLists(target.querySelector("#playlist-tracks"), () => page.tracks);
  // 曲目行左滑露出删除: 移出列表后就地抽掉那行 (不整页重铺, 滚动位置保住),
  // 头上的 规模/时长 文案顺手重算。
  bindSwipeDelete(target.querySelector("#playlist-tracks"), async (wrap) => {
    const trackId = Number(wrap.dataset.swipeTrack);
    try {
      await fetchJSON(`/music/api/playlists/${playlistId}/tracks/${trackId}`,
                      { method: "DELETE" });
      wrap.remove();
      page.tracks = page.tracks.filter((track) => track.track_id !== trackId);
      const heroSmall = target.querySelector(".hero-txt small");
      if (heroSmall) {
        heroSmall.textContent = describeDuration(
          page.tracks.reduce((sum, track) => sum + (track.duration_seconds || 0), 0),
          page.tracks.length);
      }
      toast("已从列表移除");
    } catch (error) {
      toast(`没移除掉: ${error.message}`);
    }
  });
  coverUploadPlaylistId = playlistId;
  syncPlayerIndicators();
}

/** 隐藏文件选择器选中图片 → 直接把字节 PUT 上去 (原图直存, 不压缩)。 */
async function uploadPlaylistCover(playlistId) {
  const input = $("#cover-file");
  const file = input.files && input.files[0];
  input.value = "";                     // 同一张图重选也要触发 change
  if (!file) return;
  if (file.size > 10 * 1024 * 1024) {
    toast("封面太大了 (上限 10 MB)");
    return;
  }
  try {
    await fetchJSON(`/music/api/playlists/${playlistId}/cover`, {
      method: "PUT",
      headers: { "Content-Type": file.type || "application/octet-stream" },
      body: file,
    });
    toast("封面已更新");
    renderPlaylistView(playlistId);
  } catch (error) {
    toast(`封面没传上去: ${error.message}`);
  }
}

// ------------------------------------------------------------ 搜索页

function renderSearchView() {
  $("#root-view").innerHTML = `
    <div class="search-box">
      <svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true"><circle cx="7" cy="7" r="5" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="m11 11 3.4 3.4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>
      <input id="search-input" type="search" enterkeyhint="search" autocomplete="off"
             placeholder="歌曲、专辑、艺人、歌词 (拼音简繁都行)" maxlength="100"
             value="${escapeHTML(pageState.searchQuery)}">
      <button id="search-clear" hidden aria-label="清空">✕</button>
    </div>
    <div id="search-body"></div>`;
  const input = $("#search-input");
  const clearButton = $("#search-clear");
  let debounceTimer = 0;
  input.addEventListener("input", () => {
    pageState.searchQuery = input.value.trim();
    clearButton.hidden = !input.value;
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(runSearch, 300);
  });
  clearButton.addEventListener("click", () => {
    input.value = "";
    pageState.searchQuery = "";
    clearButton.hidden = true;
    runSearch();
  });
  bindSearchBody();
  runSearch();
}

function bindSearchBody() {
  const body = $("#search-body");
  body.addEventListener("click", (event) => {
    const albumCard = event.target.closest("[data-album-id]");
    if (albumCard) { navigate(`album/${albumCard.dataset.albumId}`); return; }
    const artistRow = event.target.closest("[data-artist-id]");
    if (artistRow) { navigate(`artist/${artistRow.dataset.artistId}`); return; }
  });
  bindTrackLists(body, () => {
    const results = pageState.searchResults;
    return results ? results.tracks : [];
  });
  body.addEventListener("click", (event) => {
    const lyricRow = event.target.closest("[data-lyric-track]");
    if (!lyricRow) return;
    const results = pageState.searchResults;
    const track = results && results.lyric_hits.find(
      (hit) => hit.track.track_id === Number(lyricRow.dataset.lyricTrack));
    if (!track || !track.track.playable) {
      toast("这首浏览器播不了");
      return;
    }
    const tracks = results.lyric_hits.map((hit) => hit.track);
    playerStart(tracks, tracks.findIndex((item) => item.track_id === track.track.track_id));
    openFullPlayer();
    openLyricsView();
  });
}

async function runSearch() {
  const body = $("#search-body");
  if (!body) return;
  if (pageState.searchAbort) pageState.searchAbort.abort();
  if (!pageState.searchQuery) {
    pageState.searchResults = null;
    body.innerHTML = listPlaceholderHTML("搜歌名、艺人、专辑或一句歌词, 拼音简繁都行");
    return;
  }
  const controller = new AbortController();
  pageState.searchAbort = controller;
  body.innerHTML = listPlaceholderHTML("搜索中…");
  try {
    const results = await fetchJSON(
      `/music/api/search?q=${encodeURIComponent(pageState.searchQuery)}`,
      { signal: controller.signal });
    if (controller.signal.aborted) return;
    pageState.searchResults = results;
    renderSearchResults(body, results);
  } catch (error) {
    if (error.name === "AbortError") return;
    body.innerHTML = listPlaceholderHTML(`搜索失败: ${error.message}`);
  }
}

function renderSearchResults(body, results) {
  const hasAny = results.tracks.length || results.albums.length
    || results.artists.length || results.lyric_hits.length;
  if (!hasAny) {
    body.innerHTML = listPlaceholderHTML("没有找到相关内容");
    return;
  }
  body.innerHTML = `
    ${results.tracks.length ? `
      <div class="section-head">歌曲 · ${results.tracks.length}</div>
      <div class="track-list">${results.tracks.map((track) => trackRowHTML(track)).join("")}</div>` : ""}
    ${results.albums.length ? `
      <div class="section-head">专辑 · ${results.albums.length}</div>
      <div class="album-grid">${results.albums.map(albumCardHTML).join("")}</div>` : ""}
    ${results.artists.length ? `
      <div class="section-head">艺人 · ${results.artists.length}</div>
      ${results.artists.map(artistRowHTML).join("")}` : ""}
    ${results.lyric_hits.length ? `
      <div class="section-head">歌词 · ${results.lyric_hits.length}</div>
      ${results.lyric_hits.map((hit) => `
        <button class="lyric-hit" data-lyric-track="${hit.track.track_id}">
          <span class="t-lead">${ICON_BARS}</span>
          <span class="t-main">
            <span class="t-title"><span class="t-title-text">${escapeHTML(hit.track.title)}</span></span>
            <small>${escapeHTML(hit.line_text)}</small>
          </span>
          <i class="t-lyric">${ICON_LYRICS}</i>
          <span class="t-time">${escapeHTML(hit.track.artist)}</span>
        </button>`).join("")}` : ""}`;
  syncPlayerIndicators();
}

// ------------------------------------------------------------ 统计页

async function renderStatsView() {
  $("#root-view").innerHTML = '<div id="stats-body">'
    + '<p class="stat-empty">正在统计…</p></div>';
  const body = $("#stats-body");
  let stats;
  try {
    stats = await fetchJSON("/music/api/stats");
  } catch (error) {
    body.innerHTML = `<p class="stat-empty">统计拿不到: ${escapeHTML(error.message)}</p>`;
    return;
  }
  const [durationValue, durationUnit] =
    describeDuration(stats.total_duration_seconds).split(" ");
  body.innerHTML = `
    <div class="stat-grid">
      <div class="stat-card"><b>${stats.artist_count}</b><small>艺人</small></div>
      <div class="stat-card"><b>${stats.album_count}</b><small>专辑</small></div>
      <div class="stat-card"><b>${stats.track_count}</b><small>曲目</small></div>
      <div class="stat-card"><b>${durationValue}<small>${durationUnit}</small></b><small>总时长</small></div>
    </div>
    <h3 class="stats-title">各格式曲目数</h3>
    ${stats.formats.length
      ? stats.formats.map((row) => formatRowHTML(row, stats.track_count)).join("")
      : '<p class="stat-empty">曲库还是空的, 扫描完成后这里就有数了</p>'}`;
}

/** 格式分布行: 名字 + 比例条 + 数量; 浏览器播不了的置灰注明。 */
function formatRowHTML(row, totalCount) {
  const percent = totalCount ? Math.round(row.count / totalCount * 100) : 0;
  return `
    <div class="format-row${row.playable ? "" : " disabled"}">
      <span class="format-name">${escapeHTML(row.format)}${row.playable
        ? "" : "<i> 播不了</i>"}</span>
      <span class="format-bar"><i style="width:${Math.max(percent, 2)}%"></i></span>
      <span class="format-count">${row.count}</span>
    </div>`;
}

// ------------------------------------------------------------ 设置页
// 账号 (谁登录/退出) + 曲库路径 / 联网补歌词开关与地址 / 蜂窝流量月账 +
// 统计和更新日志入口 + 重新扫描曲库 —— 原品牌菜单的职能全搬进了这页
// (导航挪去底部页签栏以后菜单没地方挂了)。谁登录都能看;
// 改 (路径/开关/地址/保存) 只有管理员 —— 普通账号进来是只读的。
// 曲库路径改了服务器会立刻重新扫描整个曲库。

async function renderSettingsView() {
  $("#root-view").innerHTML = '<div id="settings-body">'
    + '<p class="stat-empty">加载中…</p></div>';
  const body = $("#settings-body");
  let settings;
  try {
    settings = await fetchJSON("/music/api/settings");
  } catch (error) {
    body.innerHTML = `<p class="stat-empty">设置拿不到: ${escapeHTML(error.message)}</p>`;
    return;
  }
  const me = await fetchJSON("/api/me").catch(() => null);
  const editable = !!(me && me.is_admin);        // 管理员才出得起保存钮
  const lock = editable ? "" : " disabled";
  body.innerHTML = `
    <div class="settings-block">
      <div class="settings-title">账号</div>
      ${me && me.name ? `<div class="settings-user"><svg viewBox="0 0 24 24" width="17" height="17" aria-hidden="true"><path d="M12 11.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM5.5 20a6.5 6.5 0 0 1 13 0" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg><span>${escapeHTML(me.name)}</span>${me.is_admin ? "<em>管理员</em>" : ""}</div>` : ""}
      <button class="settings-row logout" id="set-logout">退出登录</button>
    </div>
    <div class="settings-block">
      <div class="settings-title">音乐库</div>
      <div class="settings-field">
        <label for="set-dir">曲库路径</label>
        <input id="set-dir" spellcheck="false" autocomplete="off"${lock}
               placeholder="${escapeHTML(settings.music_directory_default)}"
               value="${escapeHTML(settings.music_directory)}">
        <small>服务器上存放音乐的目录 (留空用默认); 改了会立刻重新扫描整个曲库</small>
      </div>
      <button class="settings-row" id="set-rescan"
              title="增量重扫曲库 (没变的文件只 stat 不读标签)">重新扫描曲库</button>
    </div>
    <div class="settings-block">
      <div class="settings-title">联网补歌词</div>
      <div class="settings-field switch-row">
        <label>库里没歌词时上网求一遍</label>
        <button class="switch${settings.lyrics_api_enabled ? " on" : ""}"
                id="set-lyrics-on" role="switch"${lock}
                aria-checked="${settings.lyrics_api_enabled}"><i></i></button>
      </div>
      <div class="settings-field">
        <label for="set-lyrics-base">歌词 API 地址</label>
        <input id="set-lyrics-base" spellcheck="false" autocomplete="off" inputmode="url"${lock}
               placeholder="${escapeHTML(settings.lyrics_api_default)}"
               value="${escapeHTML(settings.lyrics_api_base)}">
        <small>LRCLIB 兼容接口; 求到的歌词会写回曲库, 离线也能看</small>
      </div>
    </div>
    ${editable
      ? `<div class="set-save-row"><button class="action primary" id="set-save">保存设置</button></div>`
      : '<p class="settings-note">仅管理员可修改设置, 普通账号只读。</p>'}
    <div class="settings-block">
      <div class="settings-title">蜂窝流量 · 听歌消耗</div>
      ${settings.cellular_months.length
        ? settings.cellular_months.map(monthRowHTML).join("")
        : '<p class="stat-empty">还没有记录</p>'}
      <small class="settings-note">能认出蜂窝网络的浏览器 (如安卓 Chrome) 会自动按月上报;
        iPhone 的 Safari 认不出网络类型, 那部分记不上。</small>
    </div>
    <div class="settings-block">
      <div class="settings-title">更多</div>
      <button class="settings-row" data-set-nav="stats">统计</button>
      <button class="settings-row" data-set-nav="changelog">更新日志</button>
    </div>`;
  const toggle = $("#set-lyrics-on");
  for (const row of body.querySelectorAll("[data-set-nav]")) {
    row.addEventListener("click", () => navigate(row.dataset.setNav));
  }
  $("#set-rescan").addEventListener("click", async () => {
    try {
      await fetchJSON("/music/api/rescan", { method: "POST" });
      userRescanPending = true;      // 这轮收尾要出提示 (后台自动扫的不出)
      toast("开始扫描曲库");
      checkScanStatus();
    } catch (error) {
      toast(error.message);
    }
  });
  $("#set-logout").addEventListener("click", async () => {
    try { await fetch("/music/api/logout", { method: "POST" }); }
    catch (_error) { /* 清 cookie 失败也照样走 */ }
    location.href = "/music/login";
  });
  if (editable) {
    toggle.addEventListener("click", () => {
      const on = toggle.getAttribute("aria-checked") !== "true";
      toggle.setAttribute("aria-checked", String(on));
      toggle.classList.toggle("on", on);
    });
    $("#set-save").addEventListener("click", async () => {
      const button = $("#set-save");
      button.disabled = true;
      try {
        await fetchJSON("/music/api/settings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            music_directory: $("#set-dir").value.trim(),
            lyrics_api_enabled: toggle.getAttribute("aria-checked") === "true",
            lyrics_api_base: $("#set-lyrics-base").value.trim(),
          }),
        });
        toast("设置已保存");
        checkScanStatus();      // 曲库路径换过的话, 扫描已起: 进度条接上
      } catch (error) {
        toast(`没保存上: ${error.message}`);
      } finally {
        button.disabled = false;
      }
    });
  }
}

/** 流量月账一行: "2026年9月" + 友好字节数。 */
function monthRowHTML(month) {
  const [year, monthNumber] = month.month.split("-");
  return `
    <div class="month-row">
      <span>${year}年${Number(monthNumber)}月</span>
      <b>${formatBytes(month.bytes)}</b>
    </div>`;
}

// ------------------------------------------------------------ 更新日志
// 应用内视图 (原来是整页跳转 /music/changelog, 会卸载音频断歌):
// 拉同一个条目接口铺在 #main, 播放气泡常驻, 听歌不断。
const CHANGELOG_KIND_CLS = { "新增": "add", "改进": "imp", "修复": "fix" };

async function renderChangelogView() {
  $("#root-view").innerHTML = '<div class="list-empty">正在读取版本历史…</div>';
  let versions = null;
  try {
    versions = await fetchJSON("/music/changelog/api/entries");
  } catch (error) {
    $("#root-view").innerHTML = `<div class="list-empty">加载失败: ${escapeHTML(error.message)}</div>`;
    return;
  }
  if (!versions.length) {
    $("#root-view").innerHTML = '<div class="list-empty">还没有版本记录</div>';
    return;
  }
  $("#root-view").innerHTML = `
    <div id="changelog-entries">
      ${versions.map((version) => `
        <div class="ver">
          <div class="v-head">
            <span class="v-badge">${escapeHTML(version.version)}</span>
            <span class="v-date">${escapeHTML(version.date)}</span>
          </div>
          <ul class="v-items">${version.items.map((item) => `
            <li><span class="k k-${CHANGELOG_KIND_CLS[item.kind] || "imp"}">${escapeHTML(item.kind)}</span>
                <span class="t">${escapeHTML(item.text)}</span></li>`).join("")}
          </ul>
        </div>`).join("")}
    </div>`;
}

// ------------------------------------------------------------ 扫描状态
// 服务器每几分钟自动增量重扫一轮 (新专辑自动冒出来), 这里 30 秒问一次:
// 在扫 → 进度条; 收尾 → 动过库 (changed) 才静默刷新, 手动触发的才出提示。

const SCAN_POLL_INTERVAL_MS = 30000;

async function checkScanStatus() {
  try {
    const scan = (await fetchJSON("/music/api/status")).scan;
    if (scan.running) {
      pageState.sawScanRunning = true;
      showScanStrip(scan);
    } else {
      const watched = pageState.sawScanRunning;
      pageState.sawScanRunning = false;
      digestScanSettled(scan, watched);
    }
  } catch (_error) { /* 状态条失败不影响浏览 */ }
}

/** 一轮扫描收尾的消化: 同一轮不重复响应; 启动首见的旧结果只记账不惊动;
    动过库就静默重铺, 手动按过「重新扫描」的再补一句提示。 */
function digestScanSettled(scan, watched) {
  $("#scan-strip").hidden = true;
  const signature = `${scan.finished_at || 0}:${scan.changed ? 1 : 0}`;
  if (signature === pageState.lastScanSignature) return;
  const firstSighting = !pageState.lastScanSignature && !watched;
  pageState.lastScanSignature = signature;
  if (firstSighting) return;              // 上次关页前就扫完的旧结果
  const manual = userRescanPending;
  userRescanPending = false;
  if (!manual && !scan.changed) return;   // 后台自动扫, 什么都没变: 不打扰
  resetLibraryLists();
  route(true);                            // 曲目/专辑列表重铺 (当前页自动刷新)
  if (pushStack.length) renderRootView(pageState.rootView);   // 层底下的一级页也重铺
  if (manual) toast("曲库扫描完成");
}

function showScanStrip(scan) {
  const strip = $("#scan-strip");
  strip.hidden = false;
  const total = scan.files_total || 0;
  const done = scan.files_done || 0;
  $("#scan-text").textContent = scan.phase === "commit" ? "扫描结果入库中…"
    : `曲库扫描中 ${total ? `${done}/${total}` : ""}`;
  clearTimeout(pageState.scanPollTimer);
  pageState.scanPollTimer = setTimeout(async () => {
    try {
      const status = await fetchJSON("/music/api/status");
      if (status.scan.running) showScanStrip(status.scan);
      else digestScanSettled(status.scan, true);
    } catch (_error) { /* 下轮再问 */ }
  }, 2000);
}

function stopScanPolling() {
  clearTimeout(pageState.scanPollTimer);
}

// ------------------------------------------------------------ 启动

function bindGlobalEvents() {
  // 底部页签栏: 主页/资料库/搜索/设置 (设置 = 原品牌菜单的职能进设置页)
  $("#tabbar").addEventListener("click", (event) => {
    const button = event.target.closest("[data-view-tab]");
    if (!button) return;
    navigate(button.dataset.viewTab);
    if (button.dataset.viewTab !== "search") return;
    // 进搜索页签顺手聚焦输入框 (老放大镜按钮的手感); 导航是同步渲染,
    // 走到这儿输入框已经在页面上了
    const input = $("#search-input");
    if (input) input.focus();
  });
  $("#cover-file").addEventListener("change", () => {
    if (coverUploadPlaylistId) uploadPlaylistCover(coverUploadPlaylistId);
  });
  // 后台自动增量重扫的探针: 页面可见时每 30 秒问一次状态
  setInterval(() => {
    if (!document.hidden) checkScanStatus();
  }, SCAN_POLL_INTERVAL_MS);
  // 电脑上的"返回": Esc 收播放页, 没开播放页就收顶层二级页 (手机上有右划,
  // 电脑总不能指望鼠标拖页面; 浏览器返回键在应用里已没有可退的条目)
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || event.repeat) return;
    if (playerOpen) closeFullPlayer();
    else if (pushStack.length) closePushStack(pushStack.length - 1);
  });
}

// ------------------------------------------------------------ 蜂窝流量
// 只有能认出蜂窝网络的浏览器 (安卓 Chrome 的 navigator.connection) 才上报,
// iPhone 的 Safari 认不出网络类型, 记不上 (设置页有说明)。收口/上报的
// 节奏在 cellular-usage.js, 这里只给浏览器适配器。
if (window.performance && performance.getEntriesByType
    && typeof createCellularMonitor === "function") {
  createCellularMonitor({
    isCellular: () => {
      const connection = navigator.connection
        || navigator.mozConnection || navigator.webkitConnection;
      return !!connection && connection.type === "cellular";
    },
    takeEntries: () => performance.getEntriesByType("resource"),
    report: async (bytes) => {
      const response = await fetch("/music/api/cellular-usage", {
        method: "POST", keepalive: true,      // 离开页面那一笔也要送到
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bytes }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
    },
    onHide: (flush) => {
      window.addEventListener("pagehide", flush);
      document.addEventListener("visibilitychange", () => {
        if (document.hidden) flush();     // 切后台就报, 别等系统杀页
      });
    },
    now: () => Date.now(),
  }).start();
}

// ------------------------------------------------------------ iOS 系统顶带兜底
// 苹果的系统 bug (WebKit 301994): iOS 26.1 起主屏独立模式里, 系统在屏幕
// 顶部盖一条磨砂带 (画在网页层外面, DOM/CSS 都够不着), 同时把
// env(safe-area-inset-top) 误报成 0 —— 26.2 修过一次, 26.5.2 和 iOS 27
// 又复发了。env 一报 0, 页面里所有顶部让位全部失效, 内容照样钻进磨砂带
// 被糊掉、还顶出屏幕外。
// 对策: 独立模式 + 竖屏 + iPhone 上, 用探针量 env; 报 0 且系统没有自己
// 把网页层往下推 (innerHeight 没被吃掉一截) 时, 按机型屏幕尺寸表兜一个
// 「刘海高 + 磨砂深度」写进 --sys-top-inset, CSS 一律 max(env, 兜底) 取值 ——
// 健康 iOS 和浏览器里 env 正常, 兜底恒 0, 一切照旧。
const SYS_TOP_INSETS = {  // 机型屏幕 (短边x长边, CSS px) → 刘海/灵动岛高度
  "375x812": 47, "390x844": 47, "393x852": 59, "414x896": 47,
  "428x926": 47, "430x932": 59, "440x956": 62,
};
// 系统磨砂带比安全区还深一截: 用户 iOS 27.2 实测 (2026-09-16, 393x852),
// 兜底 59 时第一排内容 (CSS 60-88) 仍被栅糊 (边缘强度只有下面几排的
// 1/4), 到 CSS 116 才完全锐利 —— 带子实际 ≈115px ≈ 刘海高 + 56。
// 兜底值在刘海高度上再垫这 56, 内容从带子底下干净开始 (只在 env 谎报
// 0 的中招系统上生效, 多让的这截不影响健康设备)。
const SYS_FROST_EXTRA = 56;
function sysTopInsetFor(w, h) {
  const exact = SYS_TOP_INSETS[`${Math.min(w, h)}x${Math.max(w, h)}`];
  const inset = exact || (h >= 940 ? 62 : h >= 850 ? 59 : 47);  // 表外新机型按高度估
  return inset + SYS_FROST_EXTRA;
}
function envTopPx() {
  const probe = document.createElement("div");
  probe.style.cssText = "position:fixed;top:0;left:0;"
    + "height:env(safe-area-inset-top);visibility:hidden;pointer-events:none;";
  document.body.appendChild(probe);
  const px = probe.offsetHeight;
  probe.remove();
  return px;
}
function updateSysDebug(state) {
  let chip = document.getElementById("sys-debug");
  if (!chip) {
    chip = document.createElement("div");
    chip.id = "sys-debug";
    document.body.appendChild(chip);
  }
  chip.textContent = `调试 ${state.os} envT=${state.envTop} `
    + `兜底=${state.sysTop} 屏${screen.width}x${screen.height} 视口${innerHeight} `
    + `${state.standalone ? "独立" : "浏览器"}${state.portrait ? "竖" : "横"}`
    + (state.pushed ? " 系统推下" : "");
}
function syncSysTopInset() {
  const state = {
    os: (navigator.userAgent.match(/OS \d+_\d+/) || ["OS?"])[0],
    envTop: envTopPx(),
    standalone: matchMedia("(display-mode: standalone)").matches,
    portrait: matchMedia("(orientation: portrait)").matches,
    // 系统自己把网页层往下推也是这个 bug 的一个变种: innerHeight 已被
    // 吃掉一截, 再兜底就双重让位了
    pushed: screen.height - innerHeight > 40,
  };
  const phone = /iPhone|iPod/.test(navigator.userAgent);
  const tall = Math.max(screen.width, screen.height) >= 800;  // SE 这类无刘海机除外
  const need = state.standalone && state.portrait && phone && tall
    && !state.pushed && state.envTop === 0;
  state.sysTop = need ? sysTopInsetFor(screen.width, screen.height) : 0;
  document.documentElement.style.setProperty(
    "--sys-top-inset", `${state.sysTop}px`);
  updateSysDebug(state);   // 排查期读数条, 拿到用户真值就撤
}
addEventListener("resize", syncSysTopInset);
addEventListener("orientationchange", syncSysTopInset);
syncSysTopInset();
setTimeout(syncSysTopInset, 800);    // 冷启动 env 可能晚到 (短暂报 0),
setTimeout(syncSysTopInset, 2500);   // 稳定后自会翻回真值, max() 无缝接手

bindGlobalEvents();
// 旧深链只消化一次 (#playlist/5 之类 → 按它开局), 随即把 URL 洗成光杆
// /music —— 之后全程一个地址, 应用内导航不再碰浏览器历史 (系统侧滑/
// 返回键没有可退的条目, 整页截图滑走绝迹; 用户点名)。
const legacyHash = location.hash.replace(/^#\/?/, "");
const legacyTarget = legacyHash && parseRoute(legacyHash) ? legacyHash : "home";
history.replaceState(null, "", location.pathname + location.search);
navigate(legacyTarget);
