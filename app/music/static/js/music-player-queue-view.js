// music-player-queue-view — My Music 队列视图 (占封面区): 翻开/重排/拖把拖拽换序。
// 拆自 music-player.js (结构化重构: 代码逐字节未动, 按 music.html 里的顺序加载, 跨模块引用走全局)。
"use strict";
/* global $, ICON_BARS, ICON_GRIP, escapeHTML, lyricsViewOpen, playQueue,
          playerCurrentTrackId, queueDrag: writable, queueReorder, queueUpcoming,
          queueViewOpen: writable, savePlayerState, toggleLyricsView */
/* exported bindQueueDrag, closeQueueView, renderQueueView, toggleQueueView */

// ------------------------------------------------------------ 队列视图 (占封面区)

/** 点队列键: 封面原地翻开成播放队列 (顶排 随机/循环 + upcoming 列表)。
    封面区就一块地方 —— 歌词开着先让歌词收掉。(开合状态 queueViewOpen
    声明在文件顶部: 前面的收起函数也要引用它。) */
function closeQueueView() {
  queueViewOpen = false;
  $("#fp-queue").hidden = true;
  $("#fp-art-wrap").hidden = false;
  $("#fp-queue-btn").classList.remove("on");
  $("#full-player").classList.remove("queue");
}

function toggleQueueView() {
  if (queueViewOpen) { closeQueueView(); return; }
  if (lyricsViewOpen) toggleLyricsView();   // 同住封面区, 二选一
  queueViewOpen = true;
  renderQueueView();
  $("#fp-art-wrap").hidden = true;
  $("#fp-queue").hidden = false;
  $("#fp-queue-btn").classList.add("on");
  $("#full-player").classList.add("queue");
}

function renderQueueView() {
  if (!playQueue) return;
  const upcoming = queueUpcoming(playQueue);
  const currentId = playerCurrentTrackId();
  $("#fq-count").textContent = `${upcoming.length} 首歌曲`;
  // 当前曲 eq 动条, 其余接续编号 (当前算 1); 右缘拖拽把手按住上下拖换顺序
  $("#queue-list").innerHTML = upcoming.map((track, index) => `
    <button class="queue-row${track.track_id === currentId ? " on" : ""}"
            data-queue-track-id="${track.track_id}">
      <span class="q-lead">${track.track_id === currentId ? ICON_BARS
        : `<i class="q-num">${index + 1}</i>`}</span>
      <span class="q-title">${escapeHTML(track.title)}</span>
      <span class="q-artist">${escapeHTML(track.artist)}</span>
      <span class="q-grip" aria-hidden="true">${ICON_GRIP}</span>
    </button>`).join("") || '<div class="lyrics-empty">队列是空的</div>';
}

// 拖拽换位: 按住右缘把手上下拖 —— 被拖行跟手 (transform), 其余行让位平移;
// 松手按落点改 order (当前曲位照旧由 queueReorder 兜住)。把手 touch-action:
// none, 拖把不滚列表; 行本身 pan-y, 列表照常滚。视图下标 0 = order[position]。
function finishQueueDrag(cancelled) {
  const drag = queueDrag;
  queueDrag = null;
  if (!drag) return;
  drag.row.classList.remove("dragging");
  drag.rows.forEach((row) => { row.style.transform = ""; });
  if (cancelled || !drag.moved || drag.target === undefined
      || drag.target === drag.fromView || !playQueue) return;
  const base = Math.max(0, playQueue.position);
  if (queueReorder(playQueue, base + drag.fromView, base + drag.target)) {
    renderQueueView();
    savePlayerState();
  }
}

function bindQueueDrag() {
  const list = $("#queue-list");
  list.addEventListener("pointerdown", (event) => {
    const grip = event.target.closest(".q-grip");
    if (!grip || queueDrag) return;
    const row = grip.closest(".queue-row");
    const rows = [...list.querySelectorAll(".queue-row")];
    const index = rows.indexOf(row);
    if (!row || index < 0 || !playQueue) return;
    event.preventDefault();                       // 拖把按下就是拖, 不当点击
    grip.setPointerCapture(event.pointerId);      // 移出把手事件也不丢
    queueDrag = { row, rows, fromView: index, target: index,
                  rowH: row.offsetHeight || 1, startY: event.clientY,
                  offsetTop: row.offsetTop, moved: false };
    row.classList.add("dragging");
  });
  list.addEventListener("pointermove", (event) => {
    if (!queueDrag) return;
    const drag = queueDrag;
    const dy = event.clientY - drag.startY;
    if (!drag.moved) {
      if (Math.abs(dy) < 6) return;
      drag.moved = true;
    }
    drag.row.style.transform = `translateY(${dy}px)`;
    drag.target = Math.max(0, Math.min(drag.rows.length - 1,
      Math.round((drag.offsetTop + dy) / drag.rowH)));
    drag.rows.forEach((row, index) => {           // 其余行让位
      if (row === drag.row) return;
      let shift = 0;
      if (drag.target > drag.fromView) {
        if (index > drag.fromView && index <= drag.target) shift = -drag.rowH;
      } else if (drag.target < drag.fromView) {
        if (index >= drag.target && index < drag.fromView) shift = drag.rowH;
      }
      row.style.transform = shift ? `translateY(${shift}px)` : "";
    });
  });
  list.addEventListener("pointerup", () => finishQueueDrag(false));
  list.addEventListener("pointercancel", () => finishQueueDrag(true));
}

