// music-common.js — My Music 页面公共小件 (DOM 查询/转义/请求/提示/资源 URL)。
// 纯逻辑在 lyrics-parser.js / player-queue.js; 浏览与播放两个页面脚本共用这里。
"use strict";
/* exported escapeHTML, fetchJSON, toast, albumArtworkURL, artistArtworkURL,
   PLACEHOLDER_ARTWORK, describeDuration, formatAddedDate,
   ICON_PLAY, ICON_PAUSE, ICON_BARS, ICON_DOWNLOAD,
   ICON_PLAY_BIG, ICON_PAUSE_BIG,
   ICON_ACTION_PLAY, ICON_ACTION_SHUFFLE */   // 供 music-player.js / music.js 引用

function $(selector) {
  return document.querySelector(selector);
}

function escapeHTML(value) {
  return String(value ?? "").replace(/[&<>"']/g,
    (char) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;",
                '"': "&quot;", "'": "&#39;"}[char]));
}

/** fetch JSON; 非 2xx 抛错 (调用方 catch 后 toast)。 */
async function fetchJSON(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      detail = (await response.json()).detail || detail;
    } catch (_error) { /* 保持 HTTP 状态文案 */ }
    throw new Error(detail);
  }
  return response.json();
}

let toastTimer = 0;
/** 底部浮层提示 (2.4s 自动消失; 连续调用只保最后一条)。 */
function toast(message) {
  const element = $("#toast");
  element.textContent = message;
  element.hidden = false;
  element.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    element.classList.remove("show");
    setTimeout(() => { element.hidden = true; }, 300);
  }, 2400);
}

/** 专辑封面 URL (?v= 是 added_at 版本号, 配合 immutable 长缓存)。 */
function albumArtworkURL(album) {
  return `/music/media/albums/${album.album_id}/artwork?v=${album.added_at || 0}`;
}

/** 艺人海报 URL (曲库 poster.* 透传)。 */
function artistArtworkURL(artist) {
  return `/music/media/artists/${artist.artist_id}/artwork`;
}

/** 占位封面 (无封面/加载失败时的纯色音符, 免 404 图标闪)。 */
const PLACEHOLDER_ARTWORK =
  'data:image/svg+xml;utf8,' + encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    + '<rect width="64" height="64" rx="8" fill="#2c2c2e"/>'
    + '<path d="M40 14v24.5a7.5 7.5 0 1 1-3-6V22l-12 3v17.5a7.5 7.5 0 1 1-3-6V19z"'
    + ' fill="#5a5a5e"/></svg>');

/** 入库日期文案: "2026年9月10日" (epoch 秒; 0/缺省返回空串)。 */
function formatAddedDate(addedAt) {
  if (!addedAt) return "";
  const date = new Date(addedAt * 1000);
  return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日`;
}

/** 专辑总时长文案: "48 分钟" / "1.2 小时" / "3 首 · 12 分钟"。 */
function describeDuration(totalSeconds, trackCount) {
  const minutes = Math.round(totalSeconds / 60);
  const durationText = minutes >= 60
    ? `${(minutes / 60).toFixed(1)} 小时` : `${minutes} 分钟`;
  return trackCount ? `${trackCount} 首 · ${durationText}` : durationText;
}

// ---------- 图标 (播放器与列表共用) ----------
const ICON_PLAY = '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M8 5.5v13l11-6.5z" fill="currentColor"/></svg>';
const ICON_PAUSE = '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M7 5h3.4v14H7zM13.6 5H17v14h-3.4z" fill="currentColor"/></svg>';
// 全屏播放页的大号播放/暂停 (Apple Music 风: 素图标, 无圆底)
const ICON_PLAY_BIG = '<svg viewBox="0 0 24 24" width="46" height="46" aria-hidden="true"><path d="M8 4.5v15l12-7.5z" fill="currentColor"/></svg>';
const ICON_PAUSE_BIG = '<svg viewBox="0 0 24 24" width="46" height="46" aria-hidden="true"><path d="M6.5 4.5h4v15h-4zM13.5 4.5h4v15h-4z" fill="currentColor"/></svg>';
const ICON_BARS = '<span class="bars" aria-hidden="true"><i></i><i></i><i></i></span>';
// 下载 (曲目行右侧; 已下载时 music.js 换成勾)
const ICON_DOWNLOAD = '<svg viewBox="0 0 24 24" width="17" height="17" aria-hidden="true"><path d="M12 3v11M7.5 9.5 12 14l4.5-4.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="M5 17.5v1.5a1.5 1.5 0 0 0 1.5 1.5h11a1.5 1.5 0 0 0 1.5-1.5v-1.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';
const ICON_ACTION_PLAY = '<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"><path d="M8 5.5v13l11-6.5z" fill="currentColor"/></svg>';
const ICON_ACTION_SHUFFLE = '<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"><path d="M16 3h5v5M4 20 21 3M21 16v5h-5M15 15l6 6M4 4l5 5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
