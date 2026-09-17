// music-common.js — My Music 页面公共小件 (DOM 查询/转义/请求/提示/资源 URL)。
// 纯逻辑在 lyrics-parser.js / player-queue.js / cellular-usage.js;
// 浏览与播放两个页面脚本共用这里。
"use strict";
/* exported escapeHTML, fetchJSON, toast, albumArtworkURL, artistArtworkURL,
   trackArtworkURL, playlistCoverURL, PLACEHOLDER_ARTWORK,
   describeDuration,
   ICON_PLAY, ICON_PAUSE, ICON_BARS, ICON_DOWNLOAD, ICON_LYRICS,
   ICON_PLAY_BIG, ICON_PAUSE_BIG,
   ICON_ACTION_PLAY, ICON_ACTION_SHUFFLE, ICON_ACTION_TRASH,
   ICON_ACTION_IMAGE, ICON_ACTION_SHARE, ICON_GRIP, ICON_REPEAT,
   ICON_REPEAT_ONE */   // 供 music-player.js / music.js 引用

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
    // 挂上状态码: 有的调用方要按码分叉 (如加歌 409 = 已在列表里, 不算失败)
    throw Object.assign(new Error(detail), { status: response.status });
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

/** 单曲自己的内嵌封面 URL (播放列表里每行用各首歌的; ?v= 是文件 mtime,
    改过标签重扫后自动换图)。 */
function trackArtworkURL(track) {
  return `/music/media/tracks/${track.track_id}/artwork?v=${track.mtime || 0}`;
}

/** 播放列表自定义封面 URL (0 = 没传过, 返回空串); ?v= 是版本号,
    换图即换址, 配合 immutable 长缓存。 */
function playlistCoverURL(playlist) {
  return playlist.cover_version
    ? `/music/media/playlists/${playlist.playlist_id}/cover?v=${playlist.cover_version}`
    : "";
}

/** 占位封面 (无封面/加载失败时的纯色音符, 免 404 图标闪)。 */
const PLACEHOLDER_ARTWORK =
  'data:image/svg+xml;utf8,' + encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    + '<rect width="64" height="64" rx="8" fill="#2c2c2e"/>'
    + '<path d="M40 14v24.5a7.5 7.5 0 1 1-3-6V22l-12 3v17.5a7.5 7.5 0 1 1-3-6V19z"'
    + ' fill="#5a5a5e"/></svg>');

/** 专辑总时长文案: "48 分钟" / "1.2 小时" / "3 首 · 12 分钟"。 */
function describeDuration(totalSeconds, trackCount) {
  const minutes = Math.round(totalSeconds / 60);
  const durationText = minutes >= 60
    ? `${(minutes / 60).toFixed(1)} 小时` : `${minutes} 分钟`;
  return trackCount ? `${trackCount} 首 · ${durationText}` : durationText;
}

// ---------- 图标 (播放器与列表共用) ----------
// 三角一律包围盒中心对准 24 格的正中 (x=12): 图标光心 = 按键中心,
// 播放↔暂停切换不左右跳位 (2026-09-14 前的三角右偏 2 格, 一切换肉眼可见地歪)。
const ICON_PLAY = '<svg viewBox="0 0 24 24" width="28" height="28" aria-hidden="true"><path d="M6.583 17.075L6.583 6.925Q6.583 5.5 7.805 6.233L16.176 11.256Q17.416 12 16.176 12.744L7.805 17.767Q6.583 18.5 6.583 17.075z" fill="currentColor"/></svg>';
const ICON_PAUSE = '<svg viewBox="0 0 24 24" width="28" height="28" aria-hidden="true"><path d="M14.857 5.571q0.887 0 1.515 0.628t0.628 1.515l0 8.571q0 0.887-0.628 1.515t-1.515 0.628t-1.515-0.628t-0.628-1.515l0-8.571q0-0.887 0.628-1.515t1.515-0.628zM9.143 5.571q0.887 0 1.515 0.628t0.628 1.515l0 8.571q0 0.887-0.628 1.515t-1.515 0.628t-1.515-0.628t-0.628-1.515l0-8.571q0-0.887 0.628-1.515t1.515-0.628z" fill="currentColor"/></svg>';
// 全屏播放页的播放/暂停: 裸白字形站在传输键上 (三键一般大, 播放键
// 不再大一号 —— 用户嫌中间的播放键过于巨大; 字形 36→32 只略大于上下曲)
const ICON_PLAY_BIG = '<svg viewBox="0 0 24 24" width="32" height="32" aria-hidden="true"><path d="M5.029 3.127L19 10.889Q21 12 19 13.111L5.029 20.873Q3 22 3 19.679L3 4.321Q3 2 5.029 3.127z" fill="currentColor"/></svg>';
const ICON_PAUSE_BIG = '<svg viewBox="0 0 24 24" width="32" height="32" aria-hidden="true"><path d="M4 4.5q0-2.5 2.5-2.5t2.5 2.5v15q0 2.5-2.5 2.5t-2.5-2.5v-15zM15 4.5q0-2.5 2.5-2.5t2.5 2.5v15q0 2.5-2.5 2.5t-2.5-2.5v-15z" fill="currentColor"/></svg>';
const ICON_BARS = '<span class="bars" aria-hidden="true"><i></i><i></i><i></i></span>';

// ❝ 引号 glyph (与全屏页歌词键同款): 曲目行「有词」的标记。
// 17×17 与下载标同大, 行内同一高度 (小了看着像上标)。
const ICON_LYRICS = '<svg viewBox="0 0 24 24" width="17" height="17" aria-hidden="true"><path d="M11.049 7.801L11.049 13.662Q11.406 15.378 10.242 16.689Q9.078 18 7.332 17.848Q7.244 17.9 7.146 17.87Q7.049 17.84 7.005 17.748Q6.9 17.71 6.858 17.608Q6.815 17.505 6.863 17.404L6.863 15.73Q6.83 15.576 6.931 15.454Q7.032 15.333 7.189 15.336Q7.857 15.352 8.276 14.832Q8.695 14.311 8.537 13.662L8.537 12.825L6.026 12.825Q5.286 12.952 4.755 12.421Q4.224 11.89 4.351 11.15L4.351 7.801Q4.224 7.062 4.755 6.531Q5.286 6 6.026 6.127L9.375 6.127Q10.114 6 10.645 6.531Q11.176 7.062 11.049 7.801L11.049 7.801M17.747 6.127L14.398 6.127Q13.658 6 13.127 6.531Q12.597 7.062 12.723 7.801L12.723 11.15Q12.597 11.89 13.127 12.421Q13.658 12.952 14.398 12.825L16.91 12.825L16.91 13.662Q17.068 14.311 16.649 14.832Q16.23 15.352 15.562 15.336Q15.399 15.335 15.298 15.462Q15.197 15.589 15.235 15.747L15.235 17.421Q15.194 17.517 15.236 17.611Q15.279 17.706 15.377 17.739Q15.421 17.832 15.518 17.862Q15.616 17.892 15.704 17.84Q17.448 17.992 18.612 16.684Q19.776 15.376 19.421 13.662L19.421 7.801Q19.548 7.062 19.017 6.531Q18.487 6 17.747 6.127L17.747 6.127" fill="currentColor"/></svg>';
// 下载 (曲目行右侧; 已下载时 music.js 换成勾)
const ICON_DOWNLOAD = '<svg viewBox="0 0 24 24" width="17" height="17" aria-hidden="true"><path d="M12 3v11M7.5 9.5 12 14l4.5-4.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="M5 17.5v1.5a1.5 1.5 0 0 0 1.5 1.5h11a1.5 1.5 0 0 0 1.5-1.5v-1.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';
const ICON_ACTION_PLAY = '<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"><path d="M6.583 17.075L6.583 6.925Q6.583 5.5 7.805 6.233L16.176 11.256Q17.416 12 16.176 12.744L7.805 17.767Q6.583 18.5 6.583 17.075z" fill="currentColor"/></svg>';
const ICON_ACTION_SHUFFLE = '<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"><path d="M16.5 3q0.31 0 0.533 0.223l3 3q0.217 0.217 0.217 0.527q0 0.316-0.217 0.533l-3 3q-0.217 0.217-0.533 0.217q-0.31 0-0.53-0.22t-0.22-0.53q0-0.299 0.217-0.527l1.723-1.723l-1.19 0q-1.055 0-1.981 0.46t-1.552 1.257q-0.967 1.231-0.967 2.783q0 1.564-0.75 2.906q-0.398 0.721-0.967 1.295q-0.832 0.85-1.94 1.325t-2.344 0.475l-1.5 0q-0.31 0-0.53-0.22t-0.22-0.53t0.22-0.53t0.53-0.22l1.5 0q1.061 0 1.984-0.457t1.55-1.254q0.967-1.231 0.967-2.789q0-1.564 0.75-2.906q0.404-0.727 0.967-1.289q0.832-0.85 1.94-1.327t2.344-0.478l1.19 0l-1.723-1.717q-0.217-0.229-0.217-0.533q0-0.31 0.22-0.53t0.53-0.22zM16.5 13.5q0.31 0 0.533 0.223l3 3q0.217 0.217 0.217 0.533q0 0.31-0.217 0.527l-3 3q-0.217 0.217-0.533 0.217q-0.31 0-0.53-0.217t-0.22-0.527q0-0.305 0.217-0.533l1.723-1.723l-1.19 0q-1.236 0-2.344-0.475t-1.94-1.325q0.451-0.662 0.75-1.412q0.627 0.796 1.55 1.254t1.984 0.457l1.19 0l-1.723-1.717q-0.217-0.229-0.217-0.533q0-0.31 0.22-0.53t0.53-0.22zM4.5 6l1.5 0q1.236 0 2.344 0.478t1.94 1.327q-0.457 0.673-0.75 1.412q-0.627-0.796-1.552-1.257t-1.981-0.46l-1.5 0q-0.31 0-0.53-0.22t-0.22-0.53t0.22-0.53t0.53-0.22z" fill="currentColor"/></svg>';
const ICON_ACTION_TRASH = '<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"><path d="M4 7h16M9.5 7V4.5h5V7M6.5 7l.7 12.5h9.6l.7-12.5M10 10.5v6M14 10.5v6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
const ICON_ACTION_IMAGE = '<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"><path d="M4.5 5.5h15v13h-15zM4.5 15l4.5-4 4 3.5 3-2.5 4 3.5M9 9.5a1 1 0 1 1-2 0 1 1 0 0 1 2 0z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';
const ICON_ACTION_SHARE = '<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"><path d="M12 3.5v11M8.5 7 12 3.5 15.5 7M6 12v6.5a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
// 队列行的拖拽把手 (三条横线, 右缘示意"这里可以拖") — 装饰图形, 不进居中对齐测试
const ICON_GRIP = '<svg viewBox="0 0 24 24" width="17" height="17" aria-hidden="true"><path d="M4 6.5h16M4 12h16M4 17.5h16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';
// 循环图标 (1.8.5 用户贴的 iconfont 单曲循环): 列表循环 = 去掉中间的 "1",
// 单曲循环带 "1" —— 两态由 music-player-chrome.js 按循环模式换 innerHTML
const ICON_REPEAT = '<svg viewBox="0 0 1024 1024" width="18" height="18" aria-hidden="true"><path d="M640 810.666667H341.333333C187.733333 810.666667 64 686.933333 64 533.333333s123.733333-277.333333 277.333333-277.333333h597.333334c12.8 0 21.333333 8.533333 21.333333 21.333333s-8.533333 21.333333-21.333333 21.333334H341.333333C211.2 298.666667 106.666667 403.2 106.666667 533.333333s104.533333 234.666667 234.666666 234.666667h298.666667c85.333333 0 164.266667-38.4 217.6-104.533333 19.2-25.6 36.266667-53.333333 44.8-83.2 4.266667-14.933333 8.533333-29.866667 10.666667-42.666667 2.133333-10.666667 12.8-19.2 23.466666-17.066667 10.666667 2.133333 19.2 12.8 17.066667 23.466667-2.133333 17.066667-6.4 34.133333-12.8 51.2-12.8 34.133333-29.866667 68.266667-53.333333 96-57.6 74.666667-149.333333 119.466667-247.466667 119.466667z" fill="currentColor"/><path d="M810.666667 426.666667c-6.4 0-10.666667-2.133333-14.933334-6.4-8.533333-8.533333-8.533333-21.333333 0-29.866667l113.066667-113.066667-113.066667-113.066666c-8.533333-8.533333-8.533333-21.333333 0-29.866667s21.333333-8.533333 29.866667 0l128 128c8.533333 8.533333 8.533333 21.333333 0 29.866667l-128 128c-4.266667 4.266667-8.533333 6.4-14.933333 6.4z" fill="currentColor"/></svg>';
const ICON_REPEAT_ONE = '<svg viewBox="0 0 1024 1024" width="18" height="18" aria-hidden="true"><path d="M640 810.666667H341.333333C187.733333 810.666667 64 686.933333 64 533.333333s123.733333-277.333333 277.333333-277.333333h597.333334c12.8 0 21.333333 8.533333 21.333333 21.333333s-8.533333 21.333333-21.333333 21.333334H341.333333C211.2 298.666667 106.666667 403.2 106.666667 533.333333s104.533333 234.666667 234.666666 234.666667h298.666667c85.333333 0 164.266667-38.4 217.6-104.533333 19.2-25.6 36.266667-53.333333 44.8-83.2 4.266667-14.933333 8.533333-29.866667 10.666667-42.666667 2.133333-10.666667 12.8-19.2 23.466666-17.066667 10.666667 2.133333 19.2 12.8 17.066667 23.466667-2.133333 17.066667-6.4 34.133333-12.8 51.2-12.8 34.133333-29.866667 68.266667-53.333333 96-57.6 74.666667-149.333333 119.466667-247.466667 119.466667z" fill="currentColor"/><path d="M810.666667 426.666667c-6.4 0-10.666667-2.133333-14.933334-6.4-8.533333-8.533333-8.533333-21.333333 0-29.866667l113.066667-113.066667-113.066667-113.066666c-8.533333-8.533333-8.533333-21.333333 0-29.866667s21.333333-8.533333 29.866667 0l128 128c8.533333 8.533333 8.533333 21.333333 0 29.866667l-128 128c-4.266667 4.266667-8.533333 6.4-14.933333 6.4z" fill="currentColor"/><path d="M512 682.666667c-12.8 0-21.333333-8.533333-21.333333-21.333334V405.333333c0-12.8 8.533333-21.333333 21.333333-21.333333s21.333333 8.533333 21.333333 21.333333v256c0 12.8-8.533333 21.333333-21.333333 21.333334z" fill="currentColor"/><path d="M416 522.666667c-6.4 0-10.666667-2.133333-14.933333-6.4-8.533333-8.533333-8.533333-21.333333 0-29.866667l96-96c8.533333-8.533333 21.333333-8.533333 29.866666 0s8.533333 21.333333 0 29.866667l-96 96c-4.266667 4.266667-8.533333 6.4-14.933333 6.4z" fill="currentColor"/></svg>';
