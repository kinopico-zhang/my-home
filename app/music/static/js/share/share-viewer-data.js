// share-viewer-data — My Music 分享页数据与状态: uuid 换数据/失效态/卡片与清单渲染, 工具与封面兜底。
// 拆自 share.html 的内联 <script> (结构化重构: 代码逐字节未动, 按 share.html 里的顺序加载, 跨模块引用走全局)。
"use strict";
/* exported $, BARS_SVG, ICON_PAUSE_BIG, ICON_PLAY_BIG, artURL, audio, boot, esc, fmtTime,
            lyricIndex, lyrics, lyricsAutoUntil, lyricsCache, lyricsFollowPaused,
            lyricsLastScrollAt, queue, queuePos, seeking,
            setArt, token */

// 分享页逻辑: 拿 uuid 换数据 → 渲染 → 流地址播放; 失效 (410) 走错误态。
// 迷你条点文字区掀全屏播放页 (1.8.5 与 app 同款: 封面/标题行字幕引号/
// 传输三键/细进度条); 歌词解析借应用公开的 lyrics-parser.js (纯模块,
// 不带会话)。一切状态以 <audio> 的 play/pause 事件为准, 按钮只改 audio。

const $ = (sel) => document.querySelector(sel);
const esc = (value) => String(value).replace(/[&<>"']/g, (ch) => (
  {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[ch]));

const PATH_PARTS = location.pathname.split("/");   // ["", "music", "share", token]
const token = PATH_PARTS.length > 3 ? PATH_PARTS[3] : "";

const ICON_PLAY_BIG = '<svg viewBox="0 0 24 24" width="32" height="32" aria-hidden="true"><path d="M5.029 3.127L19 10.889Q21 12 19 13.111L5.029 20.873Q3 22 3 19.679L3 4.321Q3 2 5.029 3.127z" fill="currentColor"/></svg>';
const ICON_PAUSE_BIG = '<svg viewBox="0 0 24 24" width="32" height="32" aria-hidden="true"><path d="M4 4.5q0-2.5 2.5-2.5t2.5 2.5v15q0 2.5-2.5 2.5t-2.5-2.5v-15zM15 4.5q0-2.5 2.5-2.5t2.5 2.5v15q0 2.5-2.5 2.5t-2.5-2.5v-15z" fill="currentColor"/></svg>';

const audio = $("#audio");
let queue = [];            // 可播的曲目 (按分享里的顺序)
let queuePos = -1;         // 正在播的下标
let seeking = false;
let lyrics = null;         // 当前曲的 {synced, lines} | null (没歌词)
let lyricsCache = new Map();     // track_id → 解析结果 (null = 没歌词)
let lyricIndex = -1;       // 正在唱的行
let lyricsFollowPaused = false;  // 手动滚过: 暂停跟唱
let lyricsLastScrollAt = 0;
let lyricsAutoUntil = 0;   // 程序滚动宽限期 (这期间的 scroll 不算手动)

const BARS_SVG = '<svg class="bars paused" viewBox="0 0 14 14" aria-hidden="true">'
  + '<rect x="1" y="2" width="2.6" height="10" rx="1.3"/>'
  + '<rect x="5.7" y="2" width="2.6" height="10" rx="1.3"/>'
  + '<rect x="10.4" y="2" width="2.6" height="10" rx="1.3"/></svg>';

function fmtTime(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "-:--";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function fmtDateTime(epochSeconds) {
  const d = new Date(epochSeconds * 1000);
  const two = (n) => String(n).padStart(2, "0");
  return `${d.getMonth() + 1}月${d.getDate()}日 `
    + `${two(d.getHours())}:${two(d.getMinutes())}`;
}

// 封面: 这一首自己的 → 它的专辑的 → 渐变占位 (onerror 兜底)
function artURL(track) {
  if (track.has_artwork) {
    return `/music/share/${token}/artwork/track/${track.track_id}?v=${track.mtime}`;
  }
  return `/music/share/${token}/artwork/album/${track.album_id}`;
}

function setArt(el, url) {
  el.classList.remove("ph");
  el.textContent = "";
  const img = document.createElement("img");
  img.alt = "";
  img.decoding = "async";
  img.onerror = () => {
    el.classList.add("ph");
    el.textContent = "♪";
    img.remove();
  };
  img.src = url;
  el.appendChild(img);
}

function setPlaceholder(el) {
  el.classList.add("ph");
  el.textContent = "♪";
}

async function boot() {
  if (!token) return showError();
  let data = null;
  try {
    const resp = await fetch(`/music/share/${token}/api`,
                             {cache: "no-store"});
    if (!resp.ok) return showError();          // 410 / 404 → 失效态
    data = await resp.json();
  } catch {
    return showError();
  }
  render(data);
}

function showError() {
  $("#share-error").hidden = false;
}

function render(data) {
  document.title = `${data.title} · My Music`;
  $("#share-title").textContent = data.title;
  $("#share-subtitle").textContent = data.subtitle;
  $("#share-expire").textContent = `链接有效期至 ${fmtDateTime(data.expires_at)}`;

  const heroArt = $("#hero-art");
  if (data.kind === "playlist" && data.playlist) {
    if (data.playlist.cover_version > 0) {
      setArt(heroArt, `/music/share/${token}/artwork/playlist/`
             + `${data.playlist.playlist_id}?v=${data.playlist.cover_version}`);
    } else {
      setPlaceholder(heroArt);
    }
  } else if (data.tracks.length > 0) {
    setArt(heroArt, artURL(data.tracks[0]));
  } else {
    setPlaceholder(heroArt);
  }

  queue = data.tracks.filter((t) => t.playable);
  if (data.kind === "playlist") {
    $("#list-head").hidden = false;
    $("#list-head").textContent = `${data.tracks.length} 首歌曲`;
    $("#share-list").innerHTML = data.tracks.map((t, i) => (
      `<div class="row${t.playable ? "" : " na"}" data-track-id="${t.track_id}">`
      + `<span class="lead"><i class="num">${i + 1}</i></span>`
      + `<span class="txt"><span class="t">${esc(t.title)}</span>`
      + `<span class="a">${esc(t.artist)}</span></span>`
      + `<span class="dur">${fmtTime(t.duration_seconds)}</span></div>`
    )).join("");
  }
  // 单曲分享没有上一首/下一首可言, 传输区收成一颗播放键
  if (queue.length < 2) {
    $("#fp-prev").hidden = true;
    $("#fp-next").hidden = true;
  }
  if (queue.length === 0) $("#hero-play").classList.add("off");
  $("#share-card").hidden = false;
}

