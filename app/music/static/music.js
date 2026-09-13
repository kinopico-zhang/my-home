// music.js — My Music 浏览页: 资料库 (最近添加/专辑/艺人/歌曲 + 语种筛选) +
// 搜索 (歌名/专辑/艺人/歌词) + 专辑/艺人详情。播放都交给 music-player.js。
"use strict";

const LIBRARY_SEGMENTS = [
  ["recent", "最近添加"], ["albums", "专辑"], ["artists", "艺人"], ["songs", "歌曲"],
];
const LANGUAGES = ["全部", "中文", "日文", "英文", "韩文", "俄文", "其他"];

const pageState = {
  segment: localStorage.getItem("music-segment") || "recent",
  language: localStorage.getItem("music-language") || "全部",
  searchQuery: "",
  lists: {},        // segment → {items, total, offset, done, loading}
  searchAbort: null,
  scanPollTimer: 0,
};

// ------------------------------------------------------------ 路由 (hash)

function currentRoute() {
  const hash = location.hash.replace(/^#\/?/, "");
  const [name, argument] = hash.split("/");
  if (name === "search") return { view: "search" };
  if (name === "album" && argument) return { view: "album", albumId: Number(argument) };
  if (name === "artist" && argument) return { view: "artist", artistId: Number(argument) };
  return { view: "library" };
}

function navigate(hash) {
  if (location.hash === `#${hash}`) route();
  else location.hash = hash;       // 挂进历史, iOS 返回手势能关页面
}

function route() {
  const { view, albumId, artistId } = currentRoute();
  const pushed = view === "album" || view === "artist";
  $("#back-btn").hidden = !pushed;
  $("#brand-menu").hidden = pushed;
  $("#tabbar").hidden = pushed;
  $("#back-label").textContent = "资料库";
  document.querySelectorAll("#tabbar [data-tab]").forEach((button) => {
    button.classList.toggle("on",
      (button.dataset.tab === "search") === (view === "search"));
  });
  stopScanPolling();
  if (view === "search") renderSearchView();
  else if (view === "album") renderAlbumView(albumId);
  else if (view === "artist") renderArtistView(artistId);
  else renderLibraryView();
  if (view === "library" || view === "search") checkScanStatus();
  syncPlayerIndicators();
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

/** 曲目行: 序号 + 动条 (播放中顶掉序号) + 标题 (词/不可播标) + 艺人 + 时长。 */
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

function listPlaceholderHTML(message) {
  return `<div class="list-empty">${message}</div>`;
}

/** 曲目点击 → 开播 (队列 = 所在列表; 不可播提示)。 */
function bindTrackLists(container, tracksOf) {
  container.addEventListener("click", (event) => {
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

function syncPlayerIndicators() {
  updatePlayButtons();       // 播放器模块的行高亮同步 (换视图后行是新 DOM)
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
    renderLibraryBody();
  });
  bindChips($("#lib-chips"));
  bindLibraryBody();
  renderLibraryBody();
}

/** 曲库四段共用的容器事件 (专辑/艺人跳转 + 曲目开播), 只绑一次。 */
function bindLibraryBody() {
  const body = $("#lib-body");
  body.addEventListener("click", (event) => {
    const albumCard = event.target.closest("[data-album-id]");
    if (albumCard) { navigate(`album/${albumCard.dataset.albumId}`); return; }
    const artistRow = event.target.closest("[data-artist-id]");
    if (artistRow) { navigate(`artist/${artistRow.dataset.artistId}`); return; }
  });
  bindTrackLists(body, () => {
    const list = pageState.lists[pageState.segment];
    return list ? list.items : [];
  });
}

function renderLibraryBody() {
  const body = $("#lib-body");
  const segment = pageState.segment;
  const list = pageState.lists[segment];
  body.innerHTML = "";
  if (list && list.items.length) { appendListPage(body, segment, list); return; }
  body.innerHTML = listPlaceholderHTML("加载中…");
  loadListPage(segment);
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
  const parameters = new URLSearchParams({ language: pageState.language, limit: "60" });
  if (segment === "albums") parameters.set("sort", "title");
  if (segment === "songs") parameters.set("limit", "100");
  parameters.set("offset", String(list.offset));
  try {
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
        <small>${album.year || ""} · ${describeDuration(album.duration_seconds, album.track_count)}</small>
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

// ------------------------------------------------------------ 搜索页

function renderSearchView() {
  $("#main").innerHTML = `
    <div class="search-box">
      <svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true"><circle cx="7" cy="7" r="5" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="m11 11 3.4 3.4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>
      <input id="search-input" type="search" enterkeyhint="search" autocomplete="off"
             placeholder="歌曲、专辑、艺人、歌词" maxlength="100"
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
    body.innerHTML = listPlaceholderHTML("搜歌名、艺人、专辑, 或者直接搜一句歌词");
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

function bindGlobalEvents() {
  $("#tabbar").addEventListener("click", (event) => {
    const tab = event.target.closest("[data-tab]");
    if (!tab) return;
    navigate(tab.dataset.tab === "search" ? "search" : "library");
  });
  $("#back-btn").addEventListener("click", () => {
    if (history.length > 1) history.back();
    else navigate("library");
  });
  $("#refresh-btn").addEventListener("click", () => {
    const button = $("#refresh-btn");
    button.classList.add("busy");
    resetLibraryLists();
    pageState.searchResults = null;
    route();
    setTimeout(() => button.classList.remove("busy"), 600);
  });
  $("#logout").addEventListener("click", async () => {
    try { await fetch("/music/api/logout", { method: "POST" }); }
    catch (_error) { /* 清 cookie 失败也照样走 */ }
    location.href = "/login";
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
if (!location.hash) history.replaceState(null, "", "#library");
route();
