// music-search-view — My Music 搜索页 (1.8.3 重排, 用户点名): 输入框钉在
// 页底船坞上方 (顶端不再有钉死的内容), 回车收起 iOS 键盘; 有查询时结果
// 分四子页左右滑切换 (骨架/页签/铺页在 music-search-pages.js)。
// 搜索本身还是边打边搜 (防抖 300ms)。拆自 music.js (结构化重构)。
"use strict";
/* global $, bindSearchTabs, bindTrackLists, buildSearchPages, escapeHTML, fetchJSON,
          listPlaceholderHTML, navigate, openFullPlayer, openLyricsView, pageState,
          playerStart, renderSearchResults, toast */
/* exported renderSearchView */

// ------------------------------------------------------------ 搜索页

function renderSearchView(target) {
  target.innerHTML = `
    <div class="search-shell">
      <div id="search-body"></div>
      <div class="search-foot">
        <div class="search-tabs" id="search-tabs">
          <button type="button" class="on" data-search-tab="tracks">歌曲<small></small></button>
          <button type="button" data-search-tab="artists">艺人<small></small></button>
          <button type="button" data-search-tab="albums">专辑<small></small></button>
          <button type="button" data-search-tab="lyrics">歌词<small></small></button>
        </div>
        <div class="search-box">
          <svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true"><circle cx="7" cy="7" r="5" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="m11 11 3.4 3.4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>
          <input id="search-input" type="search" enterkeyhint="search" autocomplete="off"
                 placeholder="歌曲、专辑、艺人、歌词 (拼音简繁都行)" maxlength="100"
                 value="${escapeHTML(pageState.searchQuery)}">
          <button id="search-clear" hidden aria-label="清空">✕</button>
        </div>
      </div>
    </div>`;
  const input = $("#search-input");
  const clearButton = $("#search-clear");
  let debounceTimer = 0;
  input.addEventListener("input", () => {
    pageState.searchQuery = input.value.trim();
    clearButton.hidden = !input.value;
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(runSearch, 300);
  });
  // 回车 = 收起 iOS 键盘 (搜索是边打边搜的, 回车没有别的活; 键盘一收
  // 结果区立刻多出一截 —— 用户点名)
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); input.blur(); }
  });
  clearButton.addEventListener("click", () => {
    input.value = "";
    pageState.searchQuery = "";
    clearButton.hidden = true;
    runSearch();
  });
  bindSearchBody();
  bindSearchTabs();
  runSearch();
}

/** 结果区事件 (专辑/艺人跳转 + 行开播 + 歌词命中连播): 绑在容器上 ——
    容器跨查询常驻, 绑内容会重复累加。 */
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
    body.classList.remove("paged");
    body.innerHTML = '<div class="pane-title">搜索</div>'
      + listPlaceholderHTML("搜歌名、艺人、专辑或一句歌词, 拼音简繁都行");
    return;
  }
  const controller = new AbortController();
  pageState.searchAbort = controller;
  if (!body.classList.contains("paged")) {
    body.classList.add("paged");
    buildSearchPages(body);        // 四子页骨架 (music-search-pages.js)
  }   // 换词不重建容器: 旧结果留到新结果到, 页序与滚动位置不动
  try {
    const results = await fetchJSON(
      `/music/api/search?q=${encodeURIComponent(pageState.searchQuery)}`,
      { signal: controller.signal });
    if (controller.signal.aborted) return;
    pageState.searchResults = results;
    renderSearchResults(body, results);
  } catch (error) {
    if (error.name === "AbortError") return;
    for (const page of body.children) {
      page.innerHTML = listPlaceholderHTML(`搜索失败: ${error.message}`);
    }
  }
}
