// music-player-media-session — My Music 锁屏/控制中心: MediaSession 元数据与进度上报。
// 拆自 music-player.js (结构化重构: 代码逐字节未动, 按 music.html 里的顺序加载, 跨模块引用走全局)。
"use strict";
/* global audioElement, currentTrack, playerNext, playerPrevious, startAudio */
/* exported syncPositionState, updateMediaSession */

// ------------------------------------------------------------ 锁屏/控制中心

function updateMediaSession() {
  if (!("mediaSession" in navigator) || !currentTrack) return;
  const artwork = `/music/media/albums/${currentTrack.album_id}/artwork`;
  navigator.mediaSession.metadata = new MediaMetadata({
    title: currentTrack.title,
    artist: currentTrack.artist,
    album: currentTrack.album_title || "",
    artwork: [{ src: artwork, sizes: "512x512", type: "image/jpeg" }],
  });
  for (const action of ["play", "pause", "previoustrack", "nexttrack",
                        "seekto", "seekbackward", "seekforward"]) {
    try {
      navigator.mediaSession.setActionHandler(action, mediaSessionAction(action));
    } catch (_error) { /* 老浏览器不认识某些动作 */ }
  }
}

/** 锁屏/控制中心的进度快照: 暂停时速率报 0 (不然外推器以为还在播),
    位置钳在 [0, 时长] 里; 时长没就绪就不报 (浏览器会拒)。 */
function syncPositionState() {
  if (!("mediaSession" in navigator) || !currentTrack) return;
  const audio = audioElement();
  if (!isFinite(audio.duration) || audio.duration <= 0) return;
  try {
    navigator.mediaSession.setPositionState({
      duration: audio.duration,
      playbackRate: audio.paused ? 0 : audio.playbackRate,
      position: Math.min(Math.max(audio.currentTime, 0), audio.duration),
    });
  } catch (_error) { /* 个别浏览器挑参数, 不挡播放 */ }
}

function mediaSessionAction(action) {
  const audio = audioElement();
  switch (action) {
    case "play": return () => startAudio().catch(() => {});
    case "pause": return () => audio.pause();
    case "previoustrack": return () => playerPrevious();
    case "nexttrack": return () => playerNext();
    case "seekto":
      return (details) => {
        if (details && typeof details.seekTime === "number") {
          audio.currentTime = details.seekTime;
        }
      };
    case "seekbackward": return () => { audio.currentTime = Math.max(0, audio.currentTime - 10); };
    default: return () => { audio.currentTime = Math.min(
      audio.duration || 0, audio.currentTime + 10); };
  }
}

