// music-player-audio-events — My Music 播放器滑杆增强与 audio 元素事件 (出声计数/进度/播完切歌/兜底存档)。
// 拆自 music-player.js (结构化重构: 按逻辑再切一刀, 前半按钮事件留在 music-player-events)。
"use strict";
/* global $, currentTrack, formatPlaybackTime, highlightActiveLyric, playQueue,
          playRecorded: writable, playerIsPlaying, playerNext, savePlayerState,
          scrubbing: writable, startAudio, syncPositionState, toast, updatePlayButtons */
/* exported bindPlayerAudioEvents */

function bindPlayerAudioEvents(audio) {
  const enhanceSliderTouch = (input) => {
    const wrap = document.createElement("div");
    wrap.className = "slider-hit";
    input.replaceWith(wrap);
    wrap.appendChild(input);
    let dragging = false;
    const apply = (clientX) => {
      const rect = wrap.getBoundingClientRect();
      if (rect.width <= 0) return;
      const min = Number(input.min);
      const max = Number(input.max);
      const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
      input.value = String(Math.round(min + ratio * (max - min)));
      input.dispatchEvent(new Event("input", { bubbles: true }));
    };
    wrap.addEventListener("pointerdown", (event) => {
      dragging = true;
      event.preventDefault();               // 别触发文字选择/页面滚动
      wrap.setPointerCapture(event.pointerId);
      apply(event.clientX);
    });
    wrap.addEventListener("pointermove", (event) => {
      if (dragging) apply(event.clientX);
    });
    const release = () => {
      if (!dragging) return;
      dragging = false;
      input.dispatchEvent(new Event("change", { bubbles: true }));
    };
    wrap.addEventListener("pointerup", release);
    wrap.addEventListener("pointercancel", release);
  };
  enhanceSliderTouch($("#fp-scrub"));   // 进度条 (音量条 1.5.1 撤了, 音量交给设备)

  const scrubber = $("#fp-scrub");
  // 时间文案照参考图: 左 = −已播, 右 = −剩余 (倒数式, 两边都带负号)
  const renderTimes = (current, total) => {
    $("#fp-time-cur").textContent = `-${formatPlaybackTime(current)}`;
    $("#fp-time-total").textContent =
      `-${formatPlaybackTime(Math.max(0, (total || 0) - current))}`;
  };
  scrubber.addEventListener("input", () => {
    scrubbing = true;
    const total = audio.duration || 0;
    const time = total * Number(scrubber.value) / 1000;
    renderTimes(time, total);
    scrubber.style.setProperty("--fill", `${scrubber.value / 10}%`);
  });
  const applyScrub = () => {
    if (!scrubbing) return;
    scrubbing = false;
    const total = audio.duration || 0;
    audio.currentTime = total * Number(scrubber.value) / 1000;
  };
  scrubber.addEventListener("change", applyScrub);
  scrubber.addEventListener("touchend", applyScrub);

  audio.addEventListener("playing", () => {
    // 真正出声了才算"听过" (恢复现场直接暂停的不算); 暂停续播不重复报
    if (playRecorded || !currentTrack) return;
    playRecorded = true;
    fetch("/music/api/plays", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ track_id: currentTrack.track_id }),
    }).catch(() => { /* 记不上不挡听歌 */ });
  });
  audio.addEventListener("play", updatePlayButtons);
  audio.addEventListener("pause", () => {
    updatePlayButtons();
    savePlayerState();
  });
  audio.addEventListener("loadedmetadata", () => {
    renderTimes(audio.currentTime, audio.duration);
    syncPositionState();
  });
  // 锁屏/控制中心的进度是浏览器拿「位置 + 流逝时间 × 速率」估的:
  // 暂停、跳句、拖动、变速后不重报, iPhone 锁屏进度条就会自顾自走
  // (暂停了还在爬、跳完对不上)。凡有动静都重报一次真实位置。
  for (const eventName of ["play", "pause", "seeked", "ratechange"]) {
    audio.addEventListener(eventName, syncPositionState);
  }
  audio.addEventListener("timeupdate", () => {
    const progress = audio.duration
      ? audio.currentTime / audio.duration : 0;
    $("#mini-progress").style.width = `${Math.round(progress * 100)}%`;
    if (!scrubbing) {
      const scrubber = $("#fp-scrub");
      scrubber.value = String(Math.round(progress * 1000));
      scrubber.style.setProperty("--fill", `${Math.round(progress * 100)}%`);
      renderTimes(audio.currentTime, audio.duration);
    }
    syncPositionState();
    highlightActiveLyric();
  });
  audio.addEventListener("ended", () => {
    if (playQueue && playQueue.repeat === "one") {   // 单曲循环: 回开头重播
      audio.currentTime = 0;
      startAudio().catch(() => {});
      return;
    }
    playerNext();
  });
  audio.addEventListener("error", () => {
    if (currentTrack) toast("这首播放失败了");
  });

  window.addEventListener("pagehide", savePlayerState);
  setInterval(() => { if (playerIsPlaying()) savePlayerState(); }, 5000);
}
