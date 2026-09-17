// share-viewer-playback — My Music 分享页播放: 队列开播/暂停/上下曲/播键态/锁屏控制中心。
// 拆自 share.html 的内联 <script> (结构化重构: 代码逐字节未动, 按 share.html 里的顺序加载, 跨模块引用走全局)。
"use strict";
/* global $, BARS_SVG, ICON_PAUSE_BIG, ICON_PLAY_BIG, artURL, audio, loadLyrics, queue,
          queuePos: writable, setArt, token */
/* exported nextTrack, playQueue, prevTrack, togglePlay, updateIcons */

function playQueue(pos) {
  if (pos < 0 || pos >= queue.length) return;
  queuePos = pos;
  const track = queue[pos];
  audio.src = `/music/share/${token}/stream/${track.track_id}`;
  for (const input of [$("#seek"), $("#fp-scrub")]) input.value = "0";
  $("#t-now").textContent = "0:00";
  $("#t-total").textContent = "-:--";
  $("#fp-time-cur").textContent = "-0:00";
  $("#fp-time-total").textContent = "-0:00";
  $("#player").hidden = false;
  $("#p-title").textContent = track.title;
  $("#p-artist").textContent = track.artist;
  setArt($("#p-art"), artURL(track));
  // 全屏页: 曲名/作者·专辑/封面/毛玻璃底 一起跟上 (1.8.5 作者行并上
  // 专辑名, app 同款「下面是标题和作者专辑名称」)
  $("#fp-title").textContent = track.title;
  $("#fp-artist").textContent =
    [track.artist, track.album_title].filter(Boolean).join(" | ");
  // 1.8.6 修「全屏页看不到封面」: #fp-art 本尊是 <img> (app 同款), 直接挂
  // src; 此前错用了给容器 div 用的 setArt —— 往 <img> 里塞子 <img> 永远
  // 不渲染, 封面就一直空着 (迷你条的 #p-art 是 div, setArt 没问题)
  $("#fp-art").src = artURL(track);
  const bgImg = $("#fp-bg-img");
  bgImg.onerror = () => { $("#fp-bg").classList.add("ph"); bgImg.removeAttribute("src"); };
  if (bgImg.getAttribute("src") !== artURL(track)) {
    $("#fp-bg").classList.remove("ph");
    bgImg.src = artURL(track);
  }
  $("#fp-prev").disabled = queuePos <= 0;
  $("#fp-next").disabled = queuePos >= queue.length - 1;
  document.title = `${track.title} · My Music`;
  loadLyrics(track);
  updateMediaSession(track);
  updateIcons();     // 自动播放被浏览器拦住时 play 事件不来, 键态先就位
  document.querySelectorAll(".row").forEach((row) => {
    const on = Number(row.dataset.trackId) === track.track_id;
    row.classList.toggle("on", on);
    const lead = row.querySelector(".lead");
    if (on) {
      lead.innerHTML = BARS_SVG;
    } else {
      const idx = Array.prototype.indexOf.call(row.parentNode.children, row);
      lead.innerHTML = `<i class="num">${idx + 1}</i>`;
    }
  });
  audio.play().catch(() => {});
}

function togglePlay() {
  if (audio.paused) {
    if (!audio.src) return playQueue(0);
    audio.play().catch(() => {});
  } else {
    audio.pause();
  }
}

function prevTrack() {
  if (queuePos > 0) playQueue(queuePos - 1);
}

function nextTrack() {
  if (queuePos + 1 < queue.length) playQueue(queuePos + 1);
}

function updateIcons() {
  const playing = !audio.paused;
  $("#ic-play").hidden = playing;
  $("#ic-pause").hidden = !playing;
  const toggleSvg = $("#p-toggle svg");
  toggleSvg.querySelector(".use-play").style.display = playing ? "none" : "";
  toggleSvg.querySelector(".use-pause").style.display = playing ? "" : "none";
  $("#fp-play").innerHTML = playing ? ICON_PAUSE_BIG : ICON_PLAY_BIG;
  const bars = document.querySelector(".row .bars");
  if (bars) bars.classList.toggle("paused", audio.paused);
}

// 锁屏/控制中心 (支持的浏览器才有; 微信内建浏览器没有也不碍事)
function updateMediaSession(track) {
  if (!("mediaSession" in navigator) || typeof MediaMetadata === "undefined") return;
  try {
    navigator.mediaSession.metadata = new MediaMetadata({
      title: track.title, artist: track.artist, album: "My Music",
      artwork: [{ src: new URL(artURL(track), location.href).href,
                  sizes: "512x512", type: "image/jpeg" }],
    });
    navigator.mediaSession.setActionHandler("play", () => audio.play().catch(() => {}));
    navigator.mediaSession.setActionHandler("pause", () => audio.pause());
    if (queue.length > 1) {
      navigator.mediaSession.setActionHandler("previoustrack", prevTrack);
      navigator.mediaSession.setActionHandler("nexttrack", nextTrack);
    }
  } catch { /* 老浏览器 setActionHandler 会抛, 不值得为它炸页面 */ }
}

