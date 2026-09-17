// music-search-pages — My Music 搜索结果四子页 (1.8.3, 用户点名): 歌词/
// 艺人/专辑/歌曲各自一页, 左右滑动切换 (横向 scroll-snap), 页签指示器
// 点击跳页; 歌曲行带封面 (与播放列表行同款)。拆自 music-search-view.js。
"use strict";
/* global $, ICON_BARS, ICON_LYRICS, albumCardHTML, artistRowHTML, escapeHTML,
          listPlaceholderHTML, syncPlayerIndicators, trackArtHTML, trackRowHTML */
/* exported bindSearchTabs, buildSearchPages, renderSearchResults */

/** 四子页骨架: 横向 snap 容器 + 四个各自竖滚的页 (顺序用户点名:
    歌曲/艺人/专辑/歌词)。容器只建一次, 换词只换各页内容。 */
function buildSearchPages(body) {
  body.innerHTML = `
    <div class="search-page" data-search-page="tracks">${listPlaceholderHTML("搜索中…")}</div>
    <div class="search-page" data-search-page="artists">${listPlaceholderHTML("搜索中…")}</div>
    <div class="search-page" data-search-page="albums">${listPlaceholderHTML("搜索中…")}</div>
    <div class="search-page" data-search-page="lyrics">${listPlaceholderHTML("搜索中…")}</div>`;
}

/** 页签 ↔ 滑动互切: 点页签滑过去; 手滑到哪页点亮哪页 (切页顺手收起
    键盘, 结果区立刻多一截)。 */
function bindSearchTabs() {
  const body = $("#search-body");
  const tabs = $("#search-tabs");
  const highlight = (index) => {
    const input = $("#search-input");
    if (input && document.activeElement === input) input.blur();
    tabs.querySelector(".on").classList.remove("on");
    if (tabs.children[index]) tabs.children[index].classList.add("on");
  };
  tabs.addEventListener("click", (event) => {
    const button = event.target.closest("[data-search-tab]");
    if (!button) return;
    const index = [...tabs.children].indexOf(button);
    highlight(index);
    body.scrollTo({ left: index * body.clientWidth, behavior: "smooth" });
  });
  body.addEventListener("scroll", () => {
    const index = Math.round(body.scrollLeft / (body.clientWidth || 1));
    if (!tabs.children[index] || tabs.children[index].classList.contains("on")) return;
    highlight(index);
  }, { passive: true });
}

/** 结果按板块铺进四页 + 页签挂命中数 (换词不重建容器, 页序不动)。 */
function renderSearchResults(body, results) {
  const page = (name) => body.querySelector(`[data-search-page="${name}"]`);
  page("tracks").innerHTML = `
    <div class="section-head">歌曲 · ${results.tracks.length}</div>
    ${results.tracks.length
      ? `<div class="track-list">${results.tracks.map(
          (track) => trackRowHTML(track, trackArtHTML(track), "art")).join("")}</div>`
      : listPlaceholderHTML("没有命中的歌曲")}`;
  page("artists").innerHTML = `
    <div class="section-head">艺人 · ${results.artists.length}</div>
    ${results.artists.length ? results.artists.map(artistRowHTML).join("")
      : listPlaceholderHTML("没有命中的艺人")}`;
  page("albums").innerHTML = `
    <div class="section-head">专辑 · ${results.albums.length}</div>
    ${results.albums.length
      ? `<div class="album-grid">${results.albums.map(albumCardHTML).join("")}</div>`
      : listPlaceholderHTML("没有命中的专辑")}`;
  page("lyrics").innerHTML = `
    <div class="section-head">歌词 · ${results.lyric_hits.length}</div>
    ${results.lyric_hits.length ? results.lyric_hits.map(lyricHitHTML).join("")
      : listPlaceholderHTML("没有命中的歌词")}`;
  const counts = [results.tracks.length, results.artists.length,
                  results.albums.length, results.lyric_hits.length];
  for (const [index, button] of [...$("#search-tabs").children].entries()) {
    button.querySelector("small").textContent = counts[index] || "";
  }
  syncPlayerIndicators();
}

/** 歌词命中行: 命中句当副行, 右缘是艺人名; 点了连播这批命中并掀开歌词。 */
function lyricHitHTML(hit) {
  return `
    <button class="lyric-hit" data-lyric-track="${hit.track.track_id}">
      <span class="t-lead">${ICON_BARS}</span>
      <span class="t-main">
        <span class="t-title"><span class="t-title-text">${escapeHTML(hit.track.title)}</span></span>
        <small>${escapeHTML(hit.line_text)}</small>
      </span>
      <i class="t-lyric">${ICON_LYRICS}</i>
      <span class="t-time">${escapeHTML(hit.track.artist)}</span>
    </button>`;
}
