// music-player-fullpage — My Music 全屏播放页开合: 滑入滑出, 下拉/横划收起, 封面左右划切歌。
// 拆自 music-player.js (结构化重构: 代码逐字节未动, 按 music.html 里的顺序加载, 跨模块引用走全局)。
"use strict";
/* global $, closeQueueView, lyricsViewOpen, playerNext, playerPrevious, queueViewOpen,
          toggleLyricsView */
/* exported bindDismissDrag, closeFullPlayer, fpDismissDragged, openFullPlayer, playerOpen */

let fpHideTimer = 0;

let playerOpen = false;   // 全屏页开着吗 (防重入; 开关是纯视图状态, 不碰历史)

function openFullPlayer() {
  const fullPlayer = $("#full-player");
  clearTimeout(fpHideTimer);
  fullPlayer.hidden = false;
  fullPlayer.style.pointerEvents = "";
  void fullPlayer.offsetWidth;   // 强制起点样式先落地再放滑入 (rAF 在安静页会饿死)
  fullPlayer.classList.add("open");
  playerOpen = true;
}

// direction "right" = 向右甩出收起 (抓手条横拖); 默认向下收 (下拉/Esc)。
function closeFullPlayer(direction) {
  if (!playerOpen) return;
  playerOpen = false;
  const fullPlayer = $("#full-player");
  fullPlayer.classList.remove("open");
  if (direction === "right") fullPlayer.classList.add("dismiss-right");
  fullPlayer.style.pointerEvents = "none";   // 滑出途中别挡下层
  clearTimeout(fpHideTimer);
  fpHideTimer = setTimeout(() => {
    fullPlayer.hidden = true;
    fullPlayer.style.pointerEvents = "";
    fullPlayer.classList.remove("dismiss-right");
  }, 300);
  if (lyricsViewOpen) toggleLyricsView();
  if (queueViewOpen) closeQueueView();
}

// ------------------------------------------------------------ 下拉收起 / 横划切歌
// 抓手条/封面往下拖: 播放页跟手下滑, 松手拖得够远或够快就收起, 否则弹回。
// 封面另有左右划: 跟手平移, 松手拖过三分之一 (或带甩劲) 就切上一首/下一首,
// 封面朝划的方向滑出, 新封面从另一侧滑入。抓手条还有横拖收起: 往右拖整页
// 跟手走, 松手拖过三分之一 (或带甩劲) 就向右甩出收起。拖动后的尾随 click
// 不算 (不然小拖一下也收起)。
// 1.8.2 整页化 (用户点名「任何一点都能拖」): .fp-sheet/.fp-bg 也绑一份
// (ignoreInteractive), 起手点落在自带手势的东西上就让路 —— 歌词/队列自带
// 滚动, 抓手/封面自带拖动, 按钮/滑杆各有点击与拖拽语义。
let fpDismissDragged = false;

// horizontalClose: 抓手条上的横划改成拖整页收起 (true), 而不是放掉。
// ignoreInteractive: 起手点命中按钮/输入/滑杆/歌词/队列 (或已绑拖动的
// 抓手/封面) 时整个手势放掉, 让位给它们自己的行为。
function bindDismissDrag(target, swipeTracks = false, horizontalClose = false,
                         ignoreInteractive = false) {
  const player = $("#full-player");
  const art = $("#fp-art-wrap");
  let dragging = false;
  let pointerId = -1;
  let startX = 0;
  let startY = 0;
  let lastX = 0;
  let lastY = 0;
  let lastTime = 0;
  let velocity = 0;                  // px/ms, 松手那刻的甩速 (竖向)
  let hVelocity = 0;                 // 横向甩速
  let mode = "";                     // "" 未定 / "down" 收起 / "side" 切歌
                                     //   / "across" 抓手横拖收起
  target.addEventListener("pointerdown", (event) => {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    if (ignoreInteractive && event.target.closest(
          "#fp-grab, #fp-art-wrap, #fp-lyrics, #fp-queue, .fp-scrub,"
          + " button, input")) return;
    dragging = true;
    pointerId = event.pointerId;
    startX = lastX = event.clientX;
    startY = lastY = event.clientY;
    lastTime = performance.now();
    velocity = 0;
    hVelocity = 0;
    mode = "";
    fpDismissDragged = false;
  });
  target.addEventListener("pointermove", (event) => {
    if (!dragging || event.pointerId !== pointerId) return;
    const now = performance.now();
    if (now > lastTime) {
      velocity = (event.clientY - lastY) / (now - lastTime);
      hVelocity = (event.clientX - lastX) / (now - lastTime);
      lastTime = now;
    }
    lastX = event.clientX;
    lastY = event.clientY;
    const dx = lastX - startX;
    const dy = lastY - startY;
    if (!mode) {
      if (Math.abs(dx) < 10 && Math.abs(dy) < 10) return;
      if (Math.abs(dy) >= Math.abs(dx)) mode = "down";
      else if (swipeTracks) mode = "side";
      else if (horizontalClose) mode = "across";
      else { dragging = false; return; }   // 横划没意义的目标, 放掉
      player.style.transition = "none";
      if (mode === "side") art.style.transition = "none";
      target.setPointerCapture(event.pointerId);
    }
    if (mode === "down") {
      if (dy > 10) fpDismissDragged = true;
      player.style.transform = dy > 0 ? `translateY(${dy * 0.92}px)` : "";
    } else if (mode === "across") {
      if (dx > 10) fpDismissDragged = true;
      player.style.transform = dx > 0 ? `translateX(${dx * 0.92}px)` : "";
    } else {
      const drag = dx * 0.9;         // 横向轻阻尼
      art.style.transform =
        `translateX(${drag}px) scale(${Math.max(.88, 1 - Math.abs(drag) / 900)})`;
      art.style.opacity = `${Math.max(.55, 1 - Math.abs(drag) / 700)}`;
    }
  });
  const finish = (event) => {
    if (!dragging || (event.pointerId !== undefined
                      && event.pointerId !== pointerId)) return;
    dragging = false;
    player.style.transition = "";
    player.style.transform = "";
    if (mode === "down") {
      if (lastY - startY > 90 || velocity > 0.55) closeFullPlayer();
      return;
    }
    if (mode === "across") {
      const width = player.offsetWidth || 1;
      const flick = hVelocity > 0.5 && lastX - startX > 30;
      if (lastX - startX >= width / 3 || flick) {
        closeFullPlayer("right");    // 样式交给 .dismiss-right 接管 (从当前位置甩出)
      }
      return;                        // 没拖够: 行内样式已清, 弹回原位
    }
    if (mode !== "side") return;
    const width = art.offsetWidth || 1;
    const flick = Math.abs(hVelocity) > 0.5 && Math.abs(lastX - startX) > 30;
    if (lastX - startX <= -width / 3 || (flick && hVelocity < 0)) {
      swipeCoverTo("left");          // 样式交给动画接管 (从当前位置滑出)
    } else if (lastX - startX >= width / 3 || (flick && hVelocity > 0)) {
      swipeCoverTo("right");
    } else {
      art.style.transition = "";     // 没拖够: transition 回来, 弹回原位
      art.style.transform = "";
      art.style.opacity = "";
    }
  };
  target.addEventListener("pointerup", finish);
  target.addEventListener("pointercancel", finish);
}

/** 封面切歌动画: 朝划的方向滑出淡出 → 换歌 → 新封面从另一侧滑入。 */
function swipeCoverTo(direction) {
  const art = $("#fp-art-wrap");
  const swap = direction === "left" ? playerNext : playerPrevious;
  art.style.transition = "transform .2s ease-in, opacity .2s ease-in";
  art.style.transform = `translateX(${direction === "left" ? -70 : 70}%)`;
  art.style.opacity = "0";
  setTimeout(() => {
    swap();
    art.style.transition = "none";
    art.style.transform = `translateX(${direction === "left" ? 60 : -60}%)`;
    void art.offsetWidth;           // 起点先落地再放滑入 (rAF 在安静页会饿死)
    art.style.transition =
      "transform .24s cubic-bezier(.32,.72,.35,1), opacity .24s ease-out";
    art.style.transform = "";
    art.style.opacity = "";         // 滑入连带淡入 —— 不恢复就一直透明!
    setTimeout(() => { art.style.transition = ""; }, 260);
  }, 200);
}

/** 歌词结果/外部入口: 打开歌词视图 (已开着就不动; 没歌词的曲子点不开)。 */
