// music-player-events — My Music 播放器事件绑定 (音频/按钮/键盘) + 开局接线。
// 拆自 music-player.js (结构化重构: 代码逐字节未动, 按 music.html 里的顺序加载, 跨模块引用走全局)。
"use strict";
/* global $, audioElement, bindDismissDrag, bindPlayerAudioEvents, bindQueueDrag,
          cancelLyricsScroll, closeFullPlayer, fpDismissDragged: writable, loadTrack,
          lyricsAutoScrolling, lyricsFollowPaused: writable, lyricsLastScrollAt: writable,
          openFullPlayer, playQueue, playerNext, playerPrevious, playerToggle,
          queueCycleRepeat, queueJump, queueSetShuffle, renderQueueView, resumeLyricsFollow,
          savePlayerState, toast, toggleLyricsView, toggleQueueView,
          updateShuffleRepeatButtons */
/* exported bindPlayerEvents, lyricsFollowPaused, lyricsLastScrollAt */

// ------------------------------------------------------------ 事件绑定

function bindPlayerEvents() {
  const audio = audioElement();

  // 按钮点击不冒泡到 #mini-open (点了上一首/暂停/下一首不该弹全屏页)
  $("#mini-play").addEventListener("click", (event) => { event.stopPropagation(); playerToggle(); });
  $("#mini-next").addEventListener("click", (event) => { event.stopPropagation(); playerNext(); });
  $("#mini-prev").addEventListener("click", (event) => { event.stopPropagation(); playerPrevious(); });
  $("#mini-open").addEventListener("click", openFullPlayer);
  $("#fp-grab").addEventListener("click", () => {
    if (fpDismissDragged) {            // 刚拖过: 抬手补发的 click 不算
      fpDismissDragged = false;
      return;
    }
    closeFullPlayer();
  });
  bindDismissDrag($("#fp-grab"), false, true);   // 抓手条: 下拉收起 + 横拖右甩收起
  bindDismissDrag($("#fp-art-wrap"), true);   // 封面: 下拉收起 + 左右划切歌
  $("#fp-play").addEventListener("click", playerToggle);
  $("#fp-next").addEventListener("click", playerNext);
  $("#fp-prev").addEventListener("click", playerPrevious);
  $("#fp-shuffle").addEventListener("click", () => {
    if (!playQueue) return;
    queueSetShuffle(playQueue, !playQueue.shuffle);
    updateShuffleRepeatButtons();
    renderQueueView();
    savePlayerState();
    toast(playQueue.shuffle ? "随机播放: 开" : "随机播放: 关");
  });
  $("#fp-repeat").addEventListener("click", () => {
    if (!playQueue) return;
    const mode = queueCycleRepeat(playQueue);
    updateShuffleRepeatButtons();
    savePlayerState();
    toast(mode === "all" ? "列表循环" : mode === "one" ? "单曲循环" : "循环: 关");
  });
  $("#fp-lyrics-btn").addEventListener("click", toggleLyricsView);
  $("#fp-queue-btn").addEventListener("click", toggleQueueView);
  $("#lyrics-resume").addEventListener("click", resumeLyricsFollow);

  // 手动滑歌词 (程序定位引发的 scroll 不算) → 暂停跟唱 + 出"回到当前句";
  // 手指按下的那一刻先撤掉滚动动画, 之后的位置全算用户的。
  // 浏览期间整页取消模糊 (凑近了看), 静置或点行跳播后恢复距离模糊。
  $("#fp-lyrics").addEventListener("pointerdown", cancelLyricsScroll);
  $("#fp-lyrics").addEventListener("scroll", () => {
    if (lyricsAutoScrolling) return;
    if (!$("#fp-lyrics").classList.contains("static")) {   // 无时间轴: 没跟唱可暂停
      lyricsFollowPaused = true;
      $("#fp-lyrics").classList.add("browsing");
      $("#lyrics-resume").hidden = false;
    }
    lyricsLastScrollAt = Date.now();
  });

  $("#queue-list").addEventListener("click", (event) => {
    if (event.target.closest(".q-grip")) return;   // 拖把不是行点击 (拖完那下更不是)
    const row = event.target.closest("[data-queue-track-id]");
    if (!row || !playQueue) return;
    const track = queueJump(playQueue, Number(row.dataset.queueTrackId));
    if (track && track.playable) {
      loadTrack(track, true);
    } else {
      toast("这首浏览器播不了");
    }
  });
  bindQueueDrag();

  $("#fp-lyrics").addEventListener("click", (event) => {
    const line = event.target.closest(".lyrics-line");
    if (!line) return;
    const time = Number(line.dataset.time);
    if (time >= 0) audioElement().currentTime = time;
    // 点行跳播 = 在新位置落座: 退出浏览态恢复模糊;
    // 不抢着滚, 紧跟的 timeupdate 会把新当前句滚居中
    resumeLyricsFollow(false);
  });

  // 滑杆命中层: iOS 的 range 输入点轨道不跳值、7px 滑钮抓不住 (音量条整个
  // 点不动)。输入框包一层透明垫子自己算比例 —— 按下即跳、拖动跟手;
  // 值写回 input 再补发 input/change, 既有 --fill/seek/存档逻辑全复用。
  bindPlayerAudioEvents(audio);
}
