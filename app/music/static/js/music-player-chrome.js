// music-player-chrome — My Music 播放器界面渲染: 迷你条/全屏页文案, 播放键同步, 底部来源行。
// 拆自 music-player.js (结构化重构: 代码逐字节未动, 按 music.html 里的顺序加载, 跨模块引用走全局)。
"use strict";
/* global $, ICON_PAUSE, ICON_PAUSE_BIG, ICON_PLAY, ICON_PLAY_BIG, PLACEHOLDER_ARTWORK,
          currentTrack, fetchJSON, playQueue, playerCurrentTrackId, playerIsPlaying */
/* exported renderPlayerChrome, updatePlayButtons, updateShuffleRepeatButtons */

// ------------------------------------------------------------ 界面渲染

function renderPlayerChrome() {
  const track = currentTrack;
  $("#mini-player").hidden = !track;
  if (!track) return;
  $("#mini-art").src = PLACEHOLDER_ARTWORK;
  $("#mini-title").textContent = track.title;
  $("#mini-artist").textContent = track.artist;
  $("#fp-title").textContent = track.title;
  $("#fp-artist").textContent = track.artist;
  updateSourceLine(track);
  const artwork = track.album_id
    ? `/music/media/albums/${track.album_id}/artwork` : PLACEHOLDER_ARTWORK;
  $("#mini-art").src = artwork;
  $("#fp-art").src = artwork;
  $("#fp-bg-img").src = artwork;
  updatePlayButtons();
  updateShuffleRepeatButtons();
}

function updatePlayButtons() {
  const playing = playerIsPlaying();
  $("#mini-play").innerHTML = playing ? ICON_PAUSE : ICON_PLAY;
  $("#fp-play").innerHTML = playing ? ICON_PAUSE_BIG : ICON_PLAY_BIG;
  for (const element of document.querySelectorAll("[data-track-row]")) {
    element.classList.toggle("playing",
      Number(element.dataset.trackRow) === playerCurrentTrackId() && playing);
  }
}

function updateShuffleRepeatButtons() {
  if (!playQueue) return;
  $("#fp-shuffle").classList.toggle("on", playQueue.shuffle);
  const repeat = playQueue.repeat;
  const repeatButton = $("#fp-repeat");
  repeatButton.classList.toggle("on", repeat !== "off");
  repeatButton.classList.toggle("one", repeat === "one");
}

// ------------------------------------------------------------ 底部来源行
// 封面下那行小字: 有 作词/作曲 标签就显示, 没有退专辑名;
// 标签按需现读 (库里只有三成左右的歌带), 读过的缓存住。
const creditsCache = new Map();     // track_id → "作词 X · 作曲 Y" | ""
let creditsSequence = 0;            // 请求序号: 切曲后旧响应不再上屏

function updateSourceLine(track) {
  if (creditsCache.has(track.track_id)) {
    $("#fp-source").textContent = creditsCache.get(track.track_id)
      || track.album_title || "";
    return;
  }
  $("#fp-source").textContent = track.album_title || "";
  const token = ++creditsSequence;
  fetchJSON(`/music/api/tracks/${track.track_id}/credits`)
    .then((data) => {
      const parts = [];
      if (data.lyricist) parts.push(`作词 ${data.lyricist}`);
      if (data.composer) parts.push(`作曲 ${data.composer}`);
      creditsCache.set(track.track_id, parts.join(" · "));
      if (token !== creditsSequence) return;        // 已经切到别的歌了
      $("#fp-source").textContent = parts.join(" · ")
        || track.album_title || "";
    })
    .catch(() => { /* 拿不到标签就保持专辑名 */ });
}

// 收起后等滑出动画 (300ms) 再 display:none。这期间两层都要放行点击到下层列表
// (用户看见列表露出来了, 点了就该有反应); 重开必须撤掉挂着的隐藏定时器,
// 不然「刚关又马上开」时旧定时器会把正开着的播放页藏掉, 之后所有点击
// 全落到下层列表上 (表现为按键没反应、点了别的歌)。
