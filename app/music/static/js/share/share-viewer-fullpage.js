// share-viewer-fullpage — My Music 分享页全屏播放页: 开合/下拉收起/封面歌词切换与顶部绑定。
// 拆自 share.html 的内联 <script> (结构化重构: 代码逐字节未动, 按 share.html 里的顺序加载, 跨模块引用走全局)。
"use strict";
/* global $, lyricsViewOpen: writable, nextTrack, prevTrack, pullSuppressClick: writable,
          syncLyricHighlight, togglePlay */

// ------------------------------------------------------------ 全屏播放页

function openFullPlayer() {
  const fp = $("#fp");
  if (!fp.hidden) return;
  fp.hidden = false;
  void fp.offsetWidth;    // 起点样式落地再放滑入
  fp.classList.add("open");
}

function closeFullPlayer() {
  const fp = $("#fp");
  if (fp.hidden) return;
  fp.classList.remove("open");
  setTimeout(() => { fp.hidden = true; }, 340);
}

// 封面点一下 ↔ 歌词; 拖动 (下拉) 不算点
function toggleLyricsView() {
  lyricsViewOpen = !lyricsViewOpen;
  $("#fp-lyrics").hidden = !lyricsViewOpen;
  $("#fp-art-wrap").hidden = lyricsViewOpen;
  if (lyricsViewOpen) syncLyricHighlight(true);
}

// 下拉收起: 封面区跟手下移, 松手过 90px 或带甩劲就收; 横移/上移撒手
(function bindPullClose() {
  const art = $("#fp-art-wrap");
  const fp = $("#fp");
  let drag = null;
  art.addEventListener("pointerdown", (event) => {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    drag = { startX: event.clientX, startY: event.clientY,
             lastY: event.clientY, lastT: event.timeStamp,
             y: 0, decided: false };
  });
  art.addEventListener("pointermove", (event) => {
    if (!drag) return;
    const dx = event.clientX - drag.startX;
    const dy = event.clientY - drag.startY;
    if (!drag.decided) {
      if (Math.abs(dx) < 8 && Math.abs(dy) < 8) return;
      drag.decided = true;
      if (!(dy > 0 && dy > Math.abs(dx))) { drag = null; return; }  // 只收下拉
      pullSuppressClick = true;
      try { art.setPointerCapture(event.pointerId); } catch { /* 照拖 */ }
      fp.style.transition = "none";
    }
    drag.y = Math.max(0, dy);
    drag.lastY = event.clientY;
    drag.lastT = event.timeStamp;
    fp.style.transform = `translateY(${drag.y}px)`;
  });
  const finish = (event, cancelled) => {
    if (!drag) return;
    const d = drag;
    drag = null;
    if (!d.decided) return;
    fp.style.transition = "";
    fp.style.transform = "";
    if (cancelled) return;                     // 浏览器接管: 弹回原位
    const flick = event.timeStamp - d.lastT < 100 && d.lastY - d.startY > 40;
    if (d.y > 90 || flick) closeFullPlayer();
  };
  art.addEventListener("pointerup", (event) => finish(event, false));
  art.addEventListener("pointercancel", () => finish(null, true));
  art.addEventListener("click", () => {
    if (pullSuppressClick) { pullSuppressClick = false; return; }
    toggleLyricsView();
  });
})();

$("#fp-lyrics").addEventListener("click", toggleLyricsView);
$("#fp-grab").addEventListener("click", closeFullPlayer);
$("#p-text").addEventListener("click", openFullPlayer);
$("#fp-prev").addEventListener("click", prevTrack);
$("#fp-next").addEventListener("click", nextTrack);
$("#fp-play").addEventListener("click", togglePlay);

