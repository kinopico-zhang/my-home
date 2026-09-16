// music-list-rendering — My Music 公共渲染件: 专辑卡/曲目行/艺人行/播放列表行/占位, 列表容器绑定, 播放指示同步。
// 拆自 music.js (结构化重构: 代码逐字节未动, 经典脚本按 music.html 里的顺序加载, 跨模块引用走全局)。
"use strict";
/* global ICON_BARS, ICON_LYRICS, PLACEHOLDER_ARTWORK, albumArtworkURL, artistArtworkURL,
          describeDuration, downloadMarkHTML, downloadTrackFromUI, downloads,
          downloadsEnabled, escapeHTML, formatPlaybackTime, playerStart, playlistCoverURL,
          toast, trackArtworkURL, updatePlayButtons */
/* exported albumCardHTML, artistRowHTML, bindTrackLists, listPlaceholderHTML,
            playlistRowHTML, rowForTrackMenu, syncPlayerIndicators, trackArtHTML,
            trackListBindings, trackRowHTML */

// ------------------------------------------------------------ 公共渲染件

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

function syncPlayerIndicators() {
  updatePlayButtons();       // 播放器模块的行高亮同步 (换视图后行是新 DOM)
}

