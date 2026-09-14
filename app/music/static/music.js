// music.js — My Music 浏览页: 主页 (播放列表/最近播放) + 资料库
// (专辑/艺人/歌曲/已下载 + 语种筛选) + 搜索 (歌名/专辑/艺人/歌词) +
// 专辑/艺人详情。播放交给 music-player.js, 下载管理在 downloads.js。
"use strict";

const LIBRARY_SEGMENTS = [
  ["albums", "专辑"], ["artists", "艺人"], ["songs", "歌曲"], ["downloads", "已下载"],
];
const LANGUAGES = ["全部", "中文", "日文", "英文", "韩文", "俄文", "其他"];

// 主页/资料库两个根视图在页头切换; 详情页/搜索/统计都是压在上面的
const ROOT_VIEWS = new Set(["home", "library"]);

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
};

// ------------------------------------------------------------ 路由 (hash)

function currentRoute() {
  const hash = location.hash.replace(/^#\/?/, "");
  const [name, argument] = hash.split("/");
  if (name === "search") return { view: "search" };
  if (name === "stats") return { view: "stats" };
  if (name === "library") return { view: "library" };
  if (name === "album" && argument) return { view: "album", albumId: Number(argument) };
  if (name === "artist" && argument) return { view: "artist", artistId: Number(argument) };
  if (name === "playlist" && argument) return { view: "playlist", playlistId: Number(argument) };
  return { view: "home" };
}

function navigate(hash) {
  if (location.hash === `#${hash}`) route();
  else location.hash = hash;       // 挂进历史, iOS 返回手势能关页面
}

function route() {
  const { view, albumId, artistId, playlistId } = currentRoute();
  const pushed = view === "album" || view === "artist" || view === "playlist";
  $("#back-btn").hidden = !pushed;
  $("#brand-menu").hidden = pushed;
  $("#back-label").textContent = "返回";
  // 主页/资料库页签只在这两个根视图亮 (搜索/统计/详情回到各自入口)
  $("#view-tabs").hidden = !ROOT_VIEWS.has(view);
  for (const button of document.querySelectorAll("[data-view-tab]")) {
    button.classList.toggle("on", button.dataset.viewTab === view);
  }
  stopScanPolling();
  if (view === "search") renderSearchView();
  else if (view === "stats") renderStatsView();
  else if (view === "album") renderAlbumView(albumId);
  else if (view === "artist") renderArtistView(artistId);
  else if (view === "playlist") renderPlaylistView(playlistId);
  else if (view === "library") renderLibraryView();
  else renderHomeView();
  if (!pushed) checkScanStatus();
  syncPlayerIndicators();
  syncDownloadIcons();
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

/** 曲目行: 序号 + 动条 (播放中顶掉序号) + 标题 (词/不可播标) + 艺人
    + 下载标 + 时长。下载标不是真按钮 (行本身是 button, 嵌套非法)。 */
function trackRowHTML(track, leadHTML) {
  return `
    <button class="track-row${track.playable ? "" : " disabled"}"
            data-track-row="${track.track_id}" data-track-id="${track.track_id}">
      <span class="t-lead">${leadHTML || ""}${ICON_BARS}</span>
      <span class="t-main">
        <span class="t-title">${escapeHTML(track.title)}
          ${track.lyrics_available ? '<i class="t-lyric">词</i>' : ""}
          ${track.playable ? "" : `<i class="t-format">${escapeHTML(track.file_format)}</i>`}
        </span>
        <small>${escapeHTML(track.artist)}</small>
      </span>
      ${downloadsEnabled ? `
      <span class="t-dl${downloads.isDownloaded(track.track_id) ? " done" : ""}"
            data-download-track="${track.track_id}" role="button" tabindex="-1"
            aria-label="下载">${downloadMarkHTML(track.track_id)}</span>` : ""}
      <span class="t-time">${formatPlaybackTime(track.duration_seconds)}</span>
    </button>`;
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

/** 播放列表行: 渐变音符块 + 名字 + 规模。 */
function playlistRowHTML(playlist) {
  return `
    <button class="playlist-row" data-playlist-id="${playlist.playlist_id}">
      <span class="pl-icon">♫</span>
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
let trackMenuOpenedAt = 0;                // 弹出时刻: 350ms 内的点击当误触吞掉
let suppressTrackClick = false;           // 长按弹菜单后, 抬手的那次 click 不当播放
let pickerTrack = null;                   // 正在挑列表往里加的曲目

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
  trackMenuOpenedAt = Date.now();
  suppressTrackClick = true;
  $("#menu-track-title").textContent = track.title;
  $("#menu-track-artist").textContent = track.artist;
  $("#track-menu-artist").hidden = !track.artist_id;   // 老下载索引没存艺人号
  const menu = $("#track-menu");
  menu.hidden = false;
  $("#track-menu-mask").hidden = false;
  // 定位: 触点下方, 出屏就翻到上方/收边 (fixed 元素, 坐标即视口)
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
}

$("#track-menu-mask").addEventListener("click", closeTrackMenu);

$("#track-menu").addEventListener("click", async (event) => {
  const action = event.target.closest("[data-track-action]");
  if (!action) return;
  if (Date.now() - trackMenuOpenedAt < 350) return;   // 弹出瞬间的抬手误触
  const row = rowForTrackMenu;             // closeTrackMenu 会清, 先抓住
  const track = row && trackFromRow(row);
  closeTrackMenu();
  if (!track) return;
  if (action.dataset.trackAction === "play") playTrackFromMenu(track, row);
  else if (action.dataset.trackAction === "artist") navigate(`artist/${track.artist_id}`);
  else if (action.dataset.trackAction === "share") shareTrack(track);
  else if (action.dataset.trackAction === "playlist") openPlaylistPicker(track);
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
  openTrackMenu(row, { x: event.clientX, y: event.clientY });
});
// 长按开了菜单, 手指抬起补发的 click 会落在行/菜单上 —— 吞掉
document.addEventListener("click", (event) => {
  if (!suppressTrackClick) return;
  suppressTrackClick = false;
  event.stopPropagation();
  event.preventDefault();
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
  list.innerHTML = playlists.map((playlist) => `
    <button class="picker-row" data-picker-playlist="${playlist.playlist_id}">
      <span class="pl-icon">♫</span>
      <span class="a-main"><b>${escapeHTML(playlist.name)}</b>
        <small>${describeDuration(playlist.duration_seconds, playlist.track_count)}</small></span>
    </button>`).join("");
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
    toast(`没加进去: ${error.message}`);
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
  if (!element || currentRoute().view !== "home") return;   // 已切走
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
  if (!element || currentRoute().view !== "home") return;   // 已切走
  pageState.homeRecent = tracks || [];
  element.innerHTML = pageState.homeRecent.length
    ? pageState.homeRecent.map((track) => trackRowHTML(track)).join("")
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
      <span class="pl-icon sm">♫</span>
      <span class="t-main">
        <span class="t-title">${escapeHTML(entry.title || `曲目 ${entry.track_id}`)}</span>
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
  if (!body || currentRoute().view !== "library") return;      // 视图已切走
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

async function renderAlbumView(albumId) {
  $("#main").innerHTML = listPlaceholderHTML("加载中…");
  let page = null;
  try {
    page = await fetchJSON(`/music/api/albums/${albumId}`);
  } catch (error) {
    $("#main").innerHTML = listPlaceholderHTML(`加载失败: ${error.message}`);
    return;
  }
  const album = page.album;
  const playable = page.tracks.filter((track) => track.playable);
  $("#main").innerHTML = `
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
  $("#main .hero-artist").addEventListener("click", (event) => {
    navigate(`artist/${event.currentTarget.dataset.artistId}`);
  });
  $("#album-play").addEventListener("click", () => {
    playerStart(page.tracks, page.tracks.indexOf(playable[0]));
  });
  $("#album-shuffle").addEventListener("click", () => {
    playerStart(page.tracks, page.tracks.indexOf(playable[0]), true);
  });
  bindTrackLists($("#album-tracks"), () => page.tracks);
  syncPlayerIndicators();
}

// ------------------------------------------------------------ 艺人页

async function renderArtistView(artistId) {
  $("#main").innerHTML = listPlaceholderHTML("加载中…");
  let page = null;
  try {
    page = await fetchJSON(`/music/api/artists/${artistId}`);
  } catch (error) {
    $("#main").innerHTML = listPlaceholderHTML(`加载失败: ${error.message}`);
    return;
  }
  const artist = page.artist;
  $("#main").innerHTML = `
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
  $("#artist-play").addEventListener("click", () => playArtist(false));
  $("#artist-shuffle").addEventListener("click", () => playArtist(true));
  $("#artist-albums").addEventListener("click", (event) => {
    const card = event.target.closest("[data-album-id]");
    if (card) navigate(`album/${card.dataset.albumId}`);
  });
}

// ------------------------------------------------------------ 播放列表页

async function renderPlaylistView(playlistId) {
  $("#main").innerHTML = listPlaceholderHTML("加载中…");
  let page = null;
  try {
    page = await fetchJSON(`/music/api/playlists/${playlistId}`);
  } catch (error) {
    $("#main").innerHTML = listPlaceholderHTML(`加载失败: ${error.message}`);
    return;
  }
  const playlist = page.playlist;
  const playable = page.tracks.filter((track) => track.playable);
  $("#main").innerHTML = `
    <div class="album-hero">
      <div class="pl-icon big">♫</div>
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
      ${page.tracks.map((track, index) => trackRowHTML(track,
        `<span class="t-index">${index + 1}</span>`)).join("")}
    </div>`;
  $("#playlist-play").addEventListener("click", () => {
    playerStart(page.tracks, page.tracks.indexOf(playable[0]));
  });
  $("#playlist-shuffle").addEventListener("click", () => {
    playerStart(page.tracks, page.tracks.indexOf(playable[0]), true);
  });
  $("#playlist-delete").addEventListener("click", async () => {
    if (!window.confirm(`删除播放列表「${playlist.name}」?`)) return;
    try {
      await fetchJSON(`/music/api/playlists/${playlistId}`, { method: "DELETE" });
      toast("已删除");
      navigate("home");                  // 回主页, 列表段重铺自然不再有它
    } catch (error) {
      toast(`没删掉: ${error.message}`);
    }
  });
  bindTrackLists($("#playlist-tracks"), () => page.tracks);
  syncPlayerIndicators();
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
    <div class="chips" id="search-chips">${chipsHTML()}</div>
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
  bindChips($("#search-chips"));
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
      `/music/api/search?q=${encodeURIComponent(pageState.searchQuery)}`
      + `&language=${encodeURIComponent(pageState.language)}`,
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
            <span class="t-title">${escapeHTML(hit.track.title)}
              <i class="t-lyric">词</i></span>
            <small>${escapeHTML(hit.line_text)}</small>
          </span>
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

// ------------------------------------------------------------ 扫描状态条

async function checkScanStatus() {
  try {
    const status = await fetchJSON("/music/api/status");
    const scan = status.scan;
    if (scan.running) {
      showScanStrip(scan);
    } else {
      $("#scan-strip").hidden = true;
    }
  } catch (_error) { /* 状态条失败不影响浏览 */ }
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
      else {
        strip.hidden = true;
        resetLibraryLists();
        route();                   // 扫完自动刷新当前页
        toast("曲库扫描完成");
      }
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
  $("#back-btn").addEventListener("click", () => {
    if (history.length > 1) history.back();
    else navigate("home");
  });
  $("#view-tabs").addEventListener("click", (event) => {
    const button = event.target.closest("[data-view-tab]");
    if (button) navigate(button.dataset.viewTab);
  });
  $("#search-btn").addEventListener("click", () => {
    navigate("search");
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
  $("#logout").addEventListener("click", async () => {
    try { await fetch("/music/api/logout", { method: "POST" }); }
    catch (_error) { /* 清 cookie 失败也照样走 */ }
    location.href = "/music/login";
  });
  $("#rescan").addEventListener("click", async () => {
    try {
      await fetchJSON("/music/api/rescan", { method: "POST" });
      toast("开始扫描曲库");
      checkScanStatus();
    } catch (error) {
      toast(error.message);
    }
  });
  window.addEventListener("hashchange", route);
}

bindGlobalEvents();
if (!location.hash) history.replaceState(null, "", "#home");
route();
