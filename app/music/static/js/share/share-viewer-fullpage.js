// share-viewer-fullpage — My Music 分享页全屏播放页: 开合/下拉收起/顶部绑定。
// 拆自 share.html 的内联 <script> (结构化重构)。1.8.5 下拉收起扩到整页
// (封面/歌词/标题区都能拉, app 同款): 传输区和歌词键照常点; 歌词滚到
// 中间时竖拖先归滚词, 滚到头再往下拉才收。
"use strict";
/* global $, nextTrack, prevTrack, togglePlay */

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

// 下拉收起: 整页跟手下移, 松手过 90px 或带甩劲就收; 横移/上移撒手
(function bindPullClose() {
  const sheet = $("#fp .fp-sheet");
  const fp = $("#fp");
  let drag = null;
  sheet.addEventListener("pointerdown", (event) => {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    if (event.target.closest("button, input")) return;   // 传输区/歌词键照常点
    const scroller = event.target.closest("#fp-lyrics");
    if (scroller && scroller.scrollTop > 0) return;      // 词滚到中间: 先归滚词
    drag = { startX: event.clientX, startY: event.clientY,
             lastY: event.clientY, lastT: event.timeStamp,
             y: 0, decided: false };
  });
  sheet.addEventListener("pointermove", (event) => {
    if (!drag) return;
    const dx = event.clientX - drag.startX;
    const dy = event.clientY - drag.startY;
    if (!drag.decided) {
      if (Math.abs(dx) < 8 && Math.abs(dy) < 8) return;
      drag.decided = true;
      if (!(dy > 0 && dy > Math.abs(dx))) { drag = null; return; }  // 只收下拉
      try { sheet.setPointerCapture(event.pointerId); } catch { /* 照拖 */ }
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
  sheet.addEventListener("pointerup", (event) => finish(event, false));
  sheet.addEventListener("pointercancel", () => finish(null, true));
})();

$("#fp-grab").addEventListener("click", closeFullPlayer);
$("#p-text").addEventListener("click", openFullPlayer);
$("#fp-prev").addEventListener("click", prevTrack);
$("#fp-next").addEventListener("click", nextTrack);
$("#fp-play").addEventListener("click", togglePlay);
