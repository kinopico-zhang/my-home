// music-track-menus — My Music 曲目长按菜单: 开合/定位/按列表语境开播, 分享链接。
// 拆自 music.js (结构化重构: 代码逐字节未动, 经典脚本按 music.html 里的顺序加载, 跨模块引用走全局)。
"use strict";
/* global $, downloads, fetchJSON, playDownloadedRow, playerStart, rowForTrackMenu: writable,
          toast, trackListBindings */
/* exported closeTrackMenu, menuTrackDirect, openTrackMenu, openTrackMenuForTrack,
            pickerTrack, placeMenuAt, playTrackFromMenu, rowForTrackMenu, sharePlaylist,
            shareTrack, trackFromRow */

// ------------------------------------------------------------ 曲目长按菜单
// 任何界面的曲目行 (含「已下载」栏) 长按 500ms / 桌面右键, 弹出菜单:
// 播放 (在所在列表的语境里开播) / 进入艺人主页 / 进入专辑主页 (1.8.2) /
// 添加到播放列表 / 分享。全屏页 ⋯ 也走这个菜单 (对着当前曲目直接开,
// 没有「播放」项)。
let pickerTrack = null;                   // 正在挑列表往里加的曲目
let menuTrackDirect = null;               // 全屏页 ⋯ 直接对着曲目开时用这个

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

/** 分享 = 后端开一条 24 小时免登录的 uuid 链接, 有系统分享就发 URL
    (歌名 - 歌手 + 链接), 没有 (明文 HTTP) 退化为复制链接。 */
async function shareByLink(kind, id, title, text) {
  let url = "";
  try {
    const made = await fetchJSON("/music/api/shares", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind, id }),
    });
    url = `${location.origin}/music/share/${made.token}`;
  } catch (error) {
    toast(`分享链接没生成: ${error.message}`);
    return;
  }
  if (typeof navigator.share === "function") {
    try { await navigator.share({ title, text, url }); }
    catch (_error) { /* 用户取消/环境拒绝: 不算失败 */ }
    return;
  }
  let copied = false;
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(url);
      copied = true;
    } else {
      const input = document.createElement("textarea");
      input.value = url;
      document.body.appendChild(input);
      input.select();
      copied = document.execCommand("copy");
      input.remove();
    }
  } catch (_error) { /* 复制失败走下面的提示 */ }
  toast(copied ? "链接已复制, 24 小时内有效" : "这个环境分享不了");
}

async function shareTrack(track) {
  await shareByLink("track", track.track_id, track.title,
                    `${track.title} - ${track.artist}`);
}

/** 列表页的分享钮: 分享整个播放列表 (打开的人能看能听整张)。 */
async function sharePlaylist(playlist) {
  await shareByLink("playlist", playlist.playlist_id, playlist.name,
                    `播放列表「${playlist.name}」`);
}

function openTrackMenu(row, point) {
  const track = trackFromRow(row);
  if (!track || row.classList.contains("busy")
      || row.classList.contains("disabled")) return;
  rowForTrackMenu = row;
  menuTrackDirect = null;
  $("#menu-track-title").textContent = track.title;
  $("#menu-track-artist").textContent = track.artist;
  $("#track-menu-artist").hidden = !track.artist_id;   // 老下载索引没存艺人号
  $("#track-menu-album").hidden = !track.album_id;     // 同理 (1.8.2 加的键)
  $("#track-menu").querySelector('[data-track-action="play"]').hidden = false;
  const menu = $("#track-menu");
  menu.hidden = false;
  $("#track-menu-mask").hidden = false;
  placeMenuAt(menu, point);
}

/** 全屏页 ⋯: 对着当前曲目开菜单 (没有行, 「播放」项藏掉 — 正在播呢)。 */
function openTrackMenuForTrack(track, point) {
  rowForTrackMenu = null;
  menuTrackDirect = track;
  $("#menu-track-title").textContent = track.title;
  $("#menu-track-artist").textContent = track.artist;
  $("#track-menu-artist").hidden = !track.artist_id;
  $("#track-menu-album").hidden = !track.album_id;
  $("#track-menu").querySelector('[data-track-action="play"]').hidden = true;
  const menu = $("#track-menu");
  menu.hidden = false;
  $("#track-menu-mask").hidden = false;
  placeMenuAt(menu, point);
}

/** 菜单定位: 触点下方, 出屏就翻到上方/收边 (fixed 元素, 坐标即视口)。 */
function placeMenuAt(menu, point) {
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
  menuTrackDirect = null;
}

// 封面菜单: 长按/右键播放列表大封面弹「换封面 / 移除封面」(共用曲目菜单的遮罩)。
