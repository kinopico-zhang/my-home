// music-search-pages — My Music 搜索结果四子页 (1.8.3, 用户点名): 歌词/
// 艺人/专辑/歌曲各自一页, 左右滑动切换 (横向 scroll-snap), 页签指示器
// 点击跳页; 歌曲行带封面 (与播放列表行同款)。拆自 music-search-view.js。
"use strict";
/* global ICON_BARS, ICON_LYRICS, albumCardHTML, artistRowHTML, escapeHTML,
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
    键盘, 结果区立刻多一截)。target 是本层的 .pane-scroll —— 旧层滑出
    还挂着 DOM 的窗口里 $() 会找错 (1.8.6)。 */
function bindSearchTabs(target) {
  const body = target.querySelector("#search-body");
  const tabs = target.querySelector("#search-tabs");
  const highlight = (index) => {
    const input = target.querySelector("#search-input");
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

/** 结果按板块铺进四页 + 页签挂命中总数 (换词不重建容器, 页序不动)。
    1.8.6 数量口径: 板块头/页签报后端的总数 (列表按容量截断时的真数),
    截断时列表尾注明「已显示前 N」—— 不再拿截断长度当命中数。 */
function renderSearchResults(body, results) {
  const page = (name) => body.querySelector(`[data-search-page="${name}"]`);
  page("tracks").innerHTML = `
    <div class="section-head">歌曲 · ${results.track_total}</div>
    ${results.tracks.length
      ? `<div class="track-list">${results.tracks.map(
          (track) => trackRowHTML(track, trackArtHTML(track), "art")).join("")}</div>`
        + listNote(results.tracks.length, results.track_total, "首")
      : listPlaceholderHTML("没有命中的歌曲")}`;
  page("artists").innerHTML = `
    <div class="section-head">艺人 · ${results.artist_total}</div>
    ${results.artists.length ? results.artists.map(artistRowHTML).join("")
        + listNote(results.artists.length, results.artist_total, "位")
      : listPlaceholderHTML("没有命中的艺人")}`;
  page("albums").innerHTML = `
    <div class="section-head">专辑 · ${results.album_total}</div>
    ${results.albums.length
      ? `<div class="album-grid">${results.albums.map(albumCardHTML).join("")}</div>`
        + listNote(results.albums.length, results.album_total, "张")
      : listPlaceholderHTML("没有命中的专辑")}`;
  page("lyrics").innerHTML = `
    <div class="section-head">歌词 · ${results.lyric_total}</div>
    ${results.lyric_hits.length ? results.lyric_hits.map(lyricHitHTML).join("")
        + listNote(results.lyric_hits.length, results.lyric_total, "句")
      : listPlaceholderHTML("没有命中的歌词")}`;
  const counts = [results.track_total, results.artist_total,
                  results.album_total, results.lyric_total];
  const tabs = body.parentElement.querySelector("#search-tabs");
  for (const [index, button] of [...tabs.children].entries()) {
    button.querySelector("small").textContent = counts[index] || "";
  }
  syncPlayerIndicators();
}

/** 板块尾注: 命中超出容量时明示 (共 N, 已显示前 M)。 */
function listNote(shown, total, unit) {
  return total > shown
    ? `<div class="list-note">共 ${total} ${unit}, 已显示前 ${shown} ${unit}</div>`
    : "";
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
