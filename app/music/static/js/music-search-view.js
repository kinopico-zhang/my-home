// music-search-view — My Music 搜索视图: 搜索框常驻顶端, 防抖搜索/结果铺页。
// 拆自 music.js (结构化重构), 1.8.0 起住推入层 (搜索键进来), 渲染目标由调用方给。
"use strict";
/* global $, ICON_BARS, ICON_LYRICS, albumCardHTML, artistRowHTML, bindTrackLists,
          escapeHTML, fetchJSON, listPlaceholderHTML, navigate, openFullPlayer,
          openLyricsView, pageState, playerStart, syncPlayerIndicators, toast, trackRowHTML */
/* exported renderSearchView */

// ------------------------------------------------------------ 搜索页

function renderSearchView(target) {
  target.innerHTML = `
    <div class="sticky-head">
      <div class="search-box">
        <svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true"><circle cx="7" cy="7" r="5" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="m11 11 3.4 3.4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>
        <input id="search-input" type="search" enterkeyhint="search" autocomplete="off"
               placeholder="歌曲、专辑、艺人、歌词 (拼音简繁都行)" maxlength="100"
               value="${escapeHTML(pageState.searchQuery)}">
        <button id="search-clear" hidden aria-label="清空">✕</button>
      </div>
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

