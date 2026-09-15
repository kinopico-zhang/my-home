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

// ------------------------------------------------------------ 路由 (hash)

function currentRoute() {
  const hash = location.hash.replace(/^#\/?/, "");
  const [name, argument] = hash.split("/");
  if (name === "search") return { view: "search" };
  if (name === "stats") return { view: "stats" };
  if (name === "settings") return { view: "settings" };
  if (name === "library") return { view: "library" };
  if (name === "album" && argument) return { view: "album", albumId: Number(argument) };
  if (name === "artist" && argument) return { view: "artist", artistId: Number(argument) };
  if (name === "playlist" && argument) return { view: "playlist", playlistId: Number(argument) };
  return { view: "home" };
}

function navigate(hash) {
  if (location.hash === `#${hash}`) route(true);   // 同页再点 = 刷新
  else location.hash = hash;       // 挂进历史, iOS 返回手势能关页面
}

function route(force) {
  const { view, albumId, artistId, playlistId } = currentRoute();
  const pushed = view === "album" || view === "artist" || view === "playlist";
  const pushId = view === "album" ? albumId
    : view === "artist" ? artistId : playlistId;
  // 主页/资料库页签常驻 (顶栏每个页面都一致, 搜索/统计/详情也能一键切回;
  // 二级页不换顶栏, 返回一律右划或浏览器回退)
  for (const button of document.querySelectorAll("[data-view-tab]")) {
    button.classList.toggle("on", button.dataset.viewTab === view);
  }
  stopScanPolling();
  if (pushed) routePushed(view, pushId, { albumId, artistId, playlistId }, force);
  else routeRoot(view, force);
  if (!pushed) checkScanStatus();
  syncPlayerIndicators();
  syncDownloadIcons();
}

// ------------------------------------------------------------ 二级页推入层
// 专辑/艺人/播放列表走 iOS 设置式二级页: 从右滑入盖住一级, 右划 (左缘起手)
// 或返回键/历史回退滑出。层叠各层保住自己的滚动; 一级页留在底下不动,
// 滚动位置推入时存档、滑出后还原。

const pushStack = [];   // [{view, id, pane}]

function headerBottom() {
  return document.querySelector("header").getBoundingClientRect().bottom;
}

// 教训: 别用 html{overflow:hidden} 锁一级页滚动 —— iOS Safari 里它会把
// sticky 顶栏打回原位跟着页面滚走 (顶栏整条消失), 而且根本锁不住触摸滚动。
// 改成只记位置: 面板自身 overscroll-behavior:none 挡住链式滚动, 滑走时归位。
function lockRootScroll() {
  if (!pushStack.length) pageState.rootScroll = window.scrollY;
}

function unlockRootScroll() {
  window.scrollTo(0, pageState.rootScroll);
}

/** 一级页路由: 主页/资料库/搜索/统计/设置都铺在 #main 根层。 */
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
  return (top && top.pane.querySelector(".pane-scroll")) || $("#main");
}

function openPushPane(view, id) {
  lockRootScroll();
  const pane = document.createElement("div");
  pane.className = "push-pane";
  pane.style.top = `${headerBottom()}px`;
  pane.innerHTML = '<div class="pane-scroll"></div>';
  $("#push-stack").appendChild(pane);
  pushStack.push({ view, id, pane });
  bindPaneSwipe(pane);
  void pane.offsetWidth;   // 起点样式落地再放滑入 (rAF 在安静页会饿死, 不用它)
  pane.classList.add("open");
  return pane.querySelector(".pane-scroll");
}

/** 滑出若干层 (栈里保留 keep 层以下); 动画完移除 DOM。 */
function closePushStack(keep = 0) {
  while (pushStack.length > keep) {
    const item = pushStack.pop();
    item.pane.classList.remove("open");
    setTimeout(() => item.pane.remove(), 420);
  }
  if (!pushStack.length) unlockRootScroll();
}

/** 右划返回: 面板任意位置起手, 横竖先分家 (竖向交还滚动); 拖过三分之一
    或带甩劲松手就收层, 否则弹回。收层自己滑完再 history.back 对齐地址栏
    (路由一看那层已就位, 只做收尾不动画第二遍)。 */
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
      pane.style.transform = `translateX(${Math.max(0, dx)}px)`;
      lastX = ev.clientX;
      lastT = ev.timeStamp;
    };
    const end = (ev) => {
      cleanup();
      if (!horizontal) return;
      const dx = Math.max(0, ev.clientX - startX);
      const width = pane.offsetWidth || 1;
      const flick = ev.timeStamp - lastT < 100 && lastX - startX > 40;
      pane.style.transition = "";
      pane.style.transform = "";
      if (dx <= width / 3 && !flick) return;      // 没拖够: 弹回 (.open 的 0)
      pane.classList.remove("open");              // 从当前位置滑出
      pushStack.pop();
      setTimeout(() => pane.remove(), 420);
      if (!pushStack.length) unlockRootScroll();
      if (history.length > 1) history.back();     // 地址栏跟上 (与返回键同款兜底)
      else navigate("home");
    };
    const cancel = () => {
      cleanup();
      if (horizontal) {
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

/** 播放列表行: 自定义封面 (传过) / 渐变音符块 + 名字 + 规模。 */
function playlistRowHTML(playlist) {
  const cover = playlistCoverURL(playlist);
  return `
    <button class="playlist-row" data-playlist-id="${playlist.playlist_id}">
      ${cover
        ? `<img class="pl-icon art" loading="lazy" decoding="async" alt="" src="${cover}">`
        : '<span class="pl-icon">♫</span>'}
      <span class="a-main"><b>${escapeHTML(playlist.name)}</b>
        <small>${describeDuration(playlist.duration_seconds, playlist.track_count)}</small></span>
      <span class="chev">›</span>
    </button>`;
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

/** 分享: 有系统分享就发文字 (歌名 - 歌手); 没有 (明文 HTTP) 退化为复制。 */
async function shareTrack(track) {
  const text = `${track.title} - ${track.artist}`;
  if (typeof navigator.share === "function") {
    try { await navigator.share({ title: track.title, text }); }
    catch (_error) { /* 用户取消/环境拒绝: 不算失败 */ }
    return;
  }
  let copied = false;
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      copied = true;
    } else {
      const input = document.createElement("textarea");
      input.value = text;
      document.body.appendChild(input);
      input.select();
      copied = document.execCommand("copy");
      input.remove();
    }
  } catch (_error) { /* 复制失败走下面的提示 */ }
  toast(copied ? "已复制歌名和歌手" : "这个环境分享不了");
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
  $("#main").innerHTML = `
    <div class="section-head">播放列表</div>
    <div id="home-playlists">${listPlaceholderHTML("加载中…")}</div>
    <div class="section-head">最近播放</div>
    <div id="home-recent">${listPlaceholderHTML("加载中…")}</div>`;
  // 事件绑在容器上 (内容是异步重铺的, 绑内容会重复累加)
  $("#home-playlists").addEventListener("click", (event) => {
    const row = event.target.closest("[data-playlist-id]");
    if (row) navigate(`playlist/${row.dataset.playlistId}`);
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
  $("#main").innerHTML = `
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
      <button class="action primary" id="playlist-play" ${playable.length ? "" : "disabled"}>
        ${ICON_ACTION_PLAY} 播放</button>
      <button class="action" id="playlist-shuffle" ${playable.length ? "" : "disabled"}>
        ${ICON_ACTION_SHUFFLE} 随机</button>
      <button class="action" id="playlist-delete">${ICON_ACTION_TRASH} 删除列表</button>
    </div>
    <div class="track-list" id="playlist-tracks">
      ${page.tracks.map((track) => trackRowHTML(track, trackArtHTML(track), "art")).join("")}
    </div>`;
  target.querySelector("#playlist-play").addEventListener("click", () => {
    playerStart(page.tracks, page.tracks.indexOf(playable[0]));
  });
  target.querySelector("#playlist-shuffle").addEventListener("click", () => {
    playerStart(page.tracks, page.tracks.indexOf(playable[0]), true);
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
  $("#main").innerHTML = `
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
  $("#main").innerHTML = '<div id="stats-body">'
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
// 曲库路径 / 联网补歌词开关与地址 / 蜂窝流量月账。谁登录都能看;
// 改 (路径/开关/地址/保存) 只有管理员 —— 普通账号进来是只读的。
// 曲库路径改了服务器会立刻重新扫描整个曲库。

async function renderSettingsView() {
  $("#main").innerHTML = '<div id="settings-body">'
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
      <div class="settings-title">音乐库</div>
      <div class="settings-field">
        <label for="set-dir">曲库路径</label>
        <input id="set-dir" spellcheck="false" autocomplete="off"${lock}
               placeholder="${escapeHTML(settings.music_directory_default)}"
               value="${escapeHTML(settings.music_directory)}">
        <small>服务器上存放音乐的目录 (留空用默认); 改了会立刻重新扫描整个曲库</small>
      </div>
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
    </div>`;
  const toggle = $("#set-lyrics-on");
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

/** 收起品牌下拉 (菜单里点了会跳转的按钮后调用)。 */
function closeBrandMenu() {
  $("#brand-menu").removeAttribute("open");
}

function bindGlobalEvents() {
  $("#view-tabs").addEventListener("click", (event) => {
    const button = event.target.closest("[data-view-tab]");
    if (!button) return;
    navigate(button.dataset.viewTab);
    if (button.dataset.viewTab !== "search") return;
    // 进搜索页签顺手聚焦输入框 (老放大镜按钮的手感)
    const input = $("#search-input");
    if (input) input.focus();     // 同页 route() 已同步跑完, 直接聚焦
    else setTimeout(() => {       // 跨页要等 hashchange 渲染好
      const pending = $("#search-input");
      if (pending) pending.focus();
    }, 50);
  });
  $("#stats-link").addEventListener("click", () => {
    closeBrandMenu();
    navigate("stats");
  });
  $("#settings-link").addEventListener("click", () => {
    closeBrandMenu();
    navigate("settings");
  });
  $("#cover-file").addEventListener("change", () => {
    if (coverUploadPlaylistId) uploadPlaylistCover(coverUploadPlaylistId);
  });
  $("#logout").addEventListener("click", async () => {
    try { await fetch("/music/api/logout", { method: "POST" }); }
    catch (_error) { /* 清 cookie 失败也照样走 */ }
    location.href = "/music/login";
  });
  $("#rescan").addEventListener("click", async () => {
    try {
      await fetchJSON("/music/api/rescan", { method: "POST" });
      userRescanPending = true;      // 这轮收尾要出提示 (后台自动扫的不出)
      toast("开始扫描曲库");
      checkScanStatus();
    } catch (error) {
      toast(error.message);
    }
  });
  // 后台自动增量重扫的探针: 页面可见时每 30 秒问一次状态
  setInterval(() => {
    if (!document.hidden) checkScanStatus();
  }, SCAN_POLL_INTERVAL_MS);
  window.addEventListener("hashchange", route);
  window.addEventListener("resize", () => {
    for (const item of pushStack) item.pane.style.top = `${headerBottom()}px`;
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

bindGlobalEvents();
if (!location.hash) history.replaceState(null, "", "#home");
route();
