// music-player-persistence — My Music 播放现场持久化: localStorage 存/恢复 (队列/曲目/进度)。
// 拆自 music-player.js (结构化重构: 代码逐字节未动, 按 music.html 里的顺序加载, 跨模块引用走全局)。
"use strict";
/* global $, PLAYER_STATE_KEY, audioElement, createPlayQueue, currentTrack: writable,
          playQueue: writable, prefetchLyrics, prefetchNextTrack, queueCurrent,
          renderPlayerChrome, renderQueueView, trackChangeListeners, updateMediaSession */
/* exported playerRestore, savePlayerState */

// ------------------------------------------------------------ 持久化

function savePlayerState() {
  if (!playQueue || !currentTrack) return;
  const audio = audioElement();
  try {
    localStorage.setItem(PLAYER_STATE_KEY, JSON.stringify({
      tracks: playQueue.tracks.slice(0, 500),
      index: playQueue.tracks.indexOf(currentTrack),
      order: playQueue.order.slice(0, 500),     // 拖拽换过的顺序别丢 (随机序也保真)
      position: playQueue.position,
      time: audio.currentTime,
      shuffle: playQueue.shuffle,
      repeat: playQueue.repeat,
    }));
  } catch (_error) { /* 存储满了就算了, 不影响听歌 */ }
}

/** 冷启动恢复上次听到的地方 (恢复到暂停态, iOS 不许自动播)。 */
function playerRestore() {
  let saved = null;
  try {
    saved = JSON.parse(localStorage.getItem(PLAYER_STATE_KEY) || "null");
  } catch (_error) { saved = null; }
  if (!saved || !Array.isArray(saved.tracks) || !saved.tracks.length) return;
  playQueue = createPlayQueue(saved.tracks, saved.index || 0);
  playQueue.repeat = saved.repeat || "off";
  // 存过顺序 (拖拽换位/随机洗牌后的 order) 就原样恢复: 队列视图所见即所存。
  // 校验是完整排列才认 (老存档/被截断的都不认, 回落原始顺序); 没恢复成
  // 顺序就不认 shuffle 旗标 —— 顺序是重建的, 旗标亮着却按原序走会骗人。
  let orderRestored = false;
  if (Array.isArray(saved.order) && saved.order.length === saved.tracks.length
      && new Set(saved.order).size === saved.tracks.length
      && saved.order.every((n) => Number.isInteger(n)
                            && n >= 0 && n < saved.tracks.length)) {
    playQueue.order = saved.order.slice();
    playQueue.position = Math.min(Math.max(0, saved.position || 0),
                                  saved.order.length - 1);
    orderRestored = true;
  }
  playQueue.shuffle = orderRestored && !!saved.shuffle;
  const track = queueCurrent(playQueue);
  if (!track) { playQueue = null; return; }
  const audio = audioElement();
  audio.src = `/music/media/stream/${track.track_id}`;
  currentTrack = track;
  renderPlayerChrome();
  renderQueueView();
  updateMediaSession();
  for (const listener of trackChangeListeners) listener(track);
  $("#fp-lyrics-btn").disabled = false;    // 探明前先恢复可点 (与 loadTrack 同款)
  prefetchLyrics(track);                   // 恢复现场也探一遍词: 没词的键灰掉
  if (saved.time) audio.currentTime = saved.time;
  prefetchNextTrack();            // 恢复现场时也把下一曲备好
}

