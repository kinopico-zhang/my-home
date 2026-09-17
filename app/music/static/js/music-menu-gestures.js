// music-menu-gestures — My Music 菜单接线与手势: 封面菜单, 菜单遮罩点击, 全屏页 ⋯/♥, 500ms 长按/右键检测。
// 拆自 music.js (结构化重构: 代码逐字节未动, 经典脚本按 music.html 里的顺序加载, 跨模块引用走全局)。
// 1.8.2: 菜单加「进入专辑主页」; 艺人/专辑跳转前先收全屏页 (它盖着推入层,
// 不收的话页面在底下开了也看不见 —— 表现就是「点了没反应」)。
"use strict";
/* global $, closeFullPlayer, closeTrackMenu, fetchJSON, menuTrackDirect, navigate,
          onTrackChange, openPlaylistPicker, openTrackMenu, openTrackMenuForTrack,
          placeMenuAt, playTrackFromMenu, playerCurrentTrack, playerOpen,
          renderPlaylistView, rowForTrackMenu, shareTrack, toast, trackFromRow */
/* exported bindCoverPress */

// 长按开过菜单的那个元素 (行/封面): 它随后补发的尾随 click 要吞。
// 按元素吞而不是一次性吞: 有的设备补发得晚 (能落到下一次点击之后),
// 一次性的标记会被先到的正常点击清掉, 迟到的那下就砸回长按的行上,
// 表现成"菜单没点到, 却播了别的歌"。落点离开这个元素的手势都放行
// (长按着滑到菜单项上松手 = 选它, 天经地义)。
let suppressTrailingTarget = null;
let coverMenuPlaylistId = 0;
let coverMenuPlaylistName = "";

function openCoverMenu(playlistId, name, hasCover, point) {
  coverMenuPlaylistId = playlistId;
  coverMenuPlaylistName = name;
  $("#menu-cover-title").textContent = name;
  $("#cover-menu-remove").hidden = !hasCover;   // 没有自定义封面就没得移除
  const menu = $("#cover-menu");
  menu.hidden = false;
  $("#track-menu-mask").hidden = false;
  placeMenuAt(menu, point);
}

function closeCoverMenu() {
  $("#cover-menu").hidden = true;
  $("#track-menu-mask").hidden = true;
}

/** 大封面的手势: 点按 = 直接换封面; 长按 500ms / 电脑右键 = 封面菜单。
    吞尾随 click 的标记绑在"开菜单的那次按压"上, 新按下即清 (同曲目行长按)。 */
function bindCoverPress(playlistId, name, hasCover) {
  const tap = $("#cover-tap");
  let pressTimer = 0;
  let pressPoint = null;
  let pressPointerId = null;
  const cancelPress = (event) => {
    if (event && event.pointerId !== undefined
        && event.pointerId !== pressPointerId) return;
    clearTimeout(pressTimer);
    pressTimer = 0;
    pressPoint = null;
  };
  tap.addEventListener("pointerdown", (event) => {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    pressPoint = { x: event.clientX, y: event.clientY };
    pressPointerId = event.pointerId;
    clearTimeout(pressTimer);
    pressTimer = setTimeout(() => {
      pressTimer = 0;
      suppressTrailingTarget = tap;    // 抬手补发的 click 不许触发换封面
      openCoverMenu(playlistId, name, hasCover, pressPoint);
    }, 500);
  });
  tap.addEventListener("pointermove", (event) => {
    if (!pressTimer || !pressPoint) return;
    if (Math.hypot(event.clientX - pressPoint.x,
                   event.clientY - pressPoint.y) > 10) cancelPress(event);
  });
  tap.addEventListener("pointerup", cancelPress);
  tap.addEventListener("pointercancel", cancelPress);
  tap.addEventListener("contextmenu", (event) => {
    event.preventDefault();              // 封面上的长按/右键归菜单管
    cancelPress();
    if (!$("#cover-menu").hidden) return;    // 安卓长按: 计时器可能已经开了
    openCoverMenu(playlistId, name, hasCover,
                  { x: event.clientX, y: event.clientY });
  });
  tap.addEventListener("click", () => {
    $("#cover-file").click();            // 点大封面直接换 (隐藏的文件选择器)
  });
}

$("#track-menu-mask").addEventListener("click", () => {
  closeTrackMenu();
  closeCoverMenu();
});

$("#cover-menu").addEventListener("click", async (event) => {
  const action = event.target.closest("[data-cover-action]");
  if (!action) return;
  closeCoverMenu();
  if (action.dataset.coverAction === "change") {
    $("#cover-file").click();
    return;
  }
  if (action.dataset.coverAction === "remove") {
    if (!window.confirm(`移除「${coverMenuPlaylistName}」的自定义封面?`)) return;
    try {
      await fetchJSON(`/music/api/playlists/${coverMenuPlaylistId}/cover`,
                      { method: "DELETE" });
      toast("封面已移除");
      renderPlaylistView(coverMenuPlaylistId);
    } catch (error) {
      toast(`没移除掉: ${error.message}`);
    }
  }
});

$("#track-menu").addEventListener("click", async (event) => {
  const action = event.target.closest("[data-track-action]");
  if (!action) return;
  const row = rowForTrackMenu;             // closeTrackMenu 会清, 先抓住
  const directTrack = menuTrackDirect;
  const track = row ? trackFromRow(row) : directTrack;
  closeTrackMenu();
  if (!track) return;
  if (action.dataset.trackAction === "play") playTrackFromMenu(track, row);
  else if (action.dataset.trackAction === "artist"
           || action.dataset.trackAction === "album") {
    // 1.8.2 修: 全屏页 (z90) 盖着推入层 (z44), 不先收播放页的话
    // 艺人/专辑页在底下开了也看不见 —— 表现就是「点了没反应」
    if (playerOpen) closeFullPlayer();
    navigate(action.dataset.trackAction === "artist"
             ? `artist/${track.artist_id}` : `album/${track.album_id}`);
  }
  else if (action.dataset.trackAction === "share") shareTrack(track);
  else if (action.dataset.trackAction === "playlist") openPlaylistPicker(track);
});

// 全屏页 ⋯ / ♥: ⋯ 开长按菜单 (没有"播放"项), ♥ 直接开加歌选择单。
// 当前曲目跟着换曲走 (恢复现场那首也接得上)。
let fpCurrentTrack = null;
onTrackChange((track) => { fpCurrentTrack = track; });
fpCurrentTrack = playerCurrentTrack();

$("#fp-menu-btn").addEventListener("click", (event) => {
  if (!fpCurrentTrack) return;
  openTrackMenuForTrack(fpCurrentTrack, { x: event.clientX, y: event.clientY });
});
$("#fp-like-btn").addEventListener("click", () => {
  if (fpCurrentTrack) openPlaylistPicker(fpCurrentTrack);
});

// 长按检测: 指针按下起 500ms 计时, 移动超 10px / 抬起 / 取消都作废;
// contextmenu (桌面右键 + 安卓长按) 直接开 (计时器先开过就不重复)。
let trackPressTimer = 0;
let trackPressPoint = null;
let trackPressPointerId = null;

function cancelTrackPress(event) {
  if (event && event.pointerId !== undefined
      && event.pointerId !== trackPressPointerId) return;
  clearTimeout(trackPressTimer);
  trackPressTimer = 0;
  trackPressPoint = null;
}

document.addEventListener("pointerdown", (event) => {
  if (event.pointerType === "mouse" && event.button !== 0) return;  // 右键走 contextmenu
  const row = event.target.closest("[data-track-row], .dl-row");
  if (!row || row.classList.contains("disabled")) return;
  trackPressPoint = { x: event.clientX, y: event.clientY };
  trackPressPointerId = event.pointerId;
  clearTimeout(trackPressTimer);
  trackPressTimer = setTimeout(() => {
    trackPressTimer = 0;
    suppressTrailingTarget = row;
    openTrackMenu(row, trackPressPoint);
  }, 500);
});
document.addEventListener("pointermove", (event) => {
  if (!trackPressTimer || !trackPressPoint) return;
  if (Math.hypot(event.clientX - trackPressPoint.x,
                 event.clientY - trackPressPoint.y) > 10) cancelTrackPress(event);
});
document.addEventListener("pointerup", cancelTrackPress);
document.addEventListener("pointercancel", cancelTrackPress);
document.addEventListener("contextmenu", (event) => {
  const row = event.target.closest("[data-track-row], .dl-row");
  if (!row) return;                      // 别处的右键 (选歌词等) 不拦
  event.preventDefault();
  cancelTrackPress();
  if (!$("#track-menu").hidden) return;  // 安卓长按: 计时器可能已经开了
  suppressTrailingTarget = row;
  openTrackMenu(row, { x: event.clientX, y: event.clientY });
});
// 长按开了菜单, 抬手补发的 click 会落回长按的那个元素上 —— 吞掉;
// 点了别处 (菜单项/遮罩) 就翻篇。见 suppressTrailingTarget 的说明。
document.addEventListener("click", (event) => {
  if (!suppressTrailingTarget) return;
  if (suppressTrailingTarget.contains(event.target)) {
    event.stopPropagation();
    event.preventDefault();
    return;
  }
  suppressTrailingTarget = null;
}, true);
