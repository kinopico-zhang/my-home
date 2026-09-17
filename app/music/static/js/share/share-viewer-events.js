// share-viewer-events — My Music 分享页事件: 音频事件/曲目清单点播/进度拖动 + 开局。
// 拆自 share.html 的内联 <script> (结构化重构: 代码逐字节未动, 按 share.html 里的顺序加载, 跨模块引用走全局)。
"use strict";
/* global $, audio, boot, fmtTime, openFullPlayer, playQueue, queue, queuePos,
          seeking: writable, syncLyricHighlight, togglePlay, updateIcons */

// ------------------------------------------------------------ 音频事件

// 1.8.6: 红色播键一按顺势掀开全屏播放页 (用户点名) —— 迷你条的播键不掀,
// 只有大红键这样; 后面掀不迟 (openFullPlayer 自带"开着就不重复"守卫)
$("#hero-play").addEventListener("click", () => {
  togglePlay();
  openFullPlayer();
});
$("#p-toggle").addEventListener("click", togglePlay);

$("#share-list").addEventListener("click", (event) => {
  const row = event.target.closest(".row");
  if (!row || row.classList.contains("na")) return;
  const trackId = Number(row.dataset.trackId);
  const pos = queue.findIndex((t) => t.track_id === trackId);
  if (pos >= 0) playQueue(pos);
});

audio.addEventListener("play", updateIcons);
audio.addEventListener("pause", updateIcons);
audio.addEventListener("loadedmetadata", () => {
  $("#t-total").textContent = fmtTime(audio.duration);
  $("#fp-time-total").textContent = `-${fmtTime(audio.duration)}`;
});
audio.addEventListener("timeupdate", () => {
  const duration = Number.isFinite(audio.duration) ? audio.duration : 0;
  if (!seeking && duration > 0) {
    const value = String(Math.round(audio.currentTime / duration * 1000));
    $("#seek").value = value;
    $("#fp-scrub").value = value;
    setScrubFill($("#fp-scrub"));
  }
  $("#t-now").textContent = fmtTime(audio.currentTime);
  $("#fp-time-cur").textContent = `-${fmtTime(audio.currentTime)}`;
  $("#fp-time-total").textContent = `-${fmtTime(Math.max(0, duration - audio.currentTime))}`;
  syncLyricHighlight(false);
});
audio.addEventListener("ended", () => {
  if (queuePos + 1 < queue.length) playQueue(queuePos + 1);
});
audio.addEventListener("error", () => {
  $("#p-title").textContent = "播放失败";
  $("#p-artist").textContent = "";
});

// 拖进度 (迷你条/全屏页同一套): input 里只做标记 + 标签跟随, 真正 seek
// 落在 change (iOS 拖完才发); metadata 没到时 iOS 会拒 currentTime,
// try/catch 吞掉等 loadedmetadata。
// 全屏页是 app 同款细进度条 (填充与滑块同色), --fill 画已播段。
function setScrubFill(input) {
  input.style.setProperty("--fill", `${Number(input.value) / 10}%`);
}
function bindSeek(input) {
  input.addEventListener("input", () => {
    seeking = true;
    setScrubFill(input);
    if (Number.isFinite(audio.duration) && audio.duration > 0) {
      const at = Number(input.value) / 1000 * audio.duration;
      $("#t-now").textContent = fmtTime(at);
      $("#fp-time-cur").textContent = `-${fmtTime(at)}`;
    }
  });
  input.addEventListener("change", () => {
    if (Number.isFinite(audio.duration) && audio.duration > 0) {
      try {
        audio.currentTime = Number(input.value) / 1000 * audio.duration;
      } catch { /* iOS 换源瞬间还没 metadata */ }
    }
    seeking = false;
  });
}
bindSeek($("#seek"));
bindSeek($("#fp-scrub"));
setScrubFill($("#fp-scrub"));   // 开局归零 (有总时长前也画个起点)

boot();
