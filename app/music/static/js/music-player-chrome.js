// music-player-chrome — My Music 播放器界面渲染: 迷你条 (含跑马灯)/全屏页文案, 播放键同步, 底部来源行 (作词/作曲)。
// 拆自 music-player.js (结构化重构), 1.8.0 气泡变窄: 上下曲撤走,
// 歌名/作者太长改跑马灯来回滚 (用户点名), 不再截断省略号。
// 1.8.2 专辑名并进艺人行 (| 分隔), 来源行只留 作词/作曲, 没有就整行收掉。
"use strict";
/* global $, ICON_PAUSE, ICON_PAUSE_BIG, ICON_PLAY, ICON_PLAY_BIG, PLACEHOLDER_ARTWORK,
          currentTrack, fetchJSON, playQueue, playerCurrentTrackId, playerIsPlaying */
/* exported renderPlayerChrome, updatePlayButtons, updateShuffleRepeatButtons */

// ------------------------------------------------------------ 界面渲染

function renderPlayerChrome() {
  const track = currentTrack;
  $("#mini-player").hidden = !track;   // 先显形再量跑马灯 (display:none 量不出宽)
  if (!track) return;
  $("#mini-art").src = PLACEHOLDER_ARTWORK;
  setMarqueeLine($("#mini-title"), track.title);
  setMarqueeLine($("#mini-artist"), track.artist);
  $("#fp-title").textContent = track.title;
  // 1.8.2 专辑名并进艺人行 (用户点名「用一个 | 隔开」): 底部来源行省下来,
  // 页面纵向空间多一截
  $("#fp-artist").textContent = [track.artist, track.album_title]
    .filter(Boolean).join(" | ");
  updateSourceLine(track);
  const artwork = track.album_id
    ? `/music/media/albums/${track.album_id}/artwork` : PLACEHOLDER_ARTWORK;
  $("#mini-art").src = artwork;
  $("#fp-art").src = artwork;
  $("#fp-bg-img").src = artwork;
  updatePlayButtons();
  updateShuffleRepeatButtons();
}

/** 迷你条一行文字: 放得下静止, 放不下挂 .marquee 来回滚
    (距离/时长写 CSS 变量, 两端各停一拍 —— 见 music-bottom-bar.css)。 */
function setMarqueeLine(line, text) {
  const run = line.querySelector(".mq-run");
  run.textContent = text;
  run.classList.remove("marquee");
  if (!text) return;
  const overflow = run.scrollWidth - line.clientWidth;
  if (overflow <= 2) return;               // 放得下: 不滚
  run.style.setProperty("--mq-dx", `${-overflow}px`);
  run.style.setProperty("--mq-dur", `${Math.max(8, overflow / 18)}s`);
  run.classList.add("marquee");
}

// 转屏/改窗口后行宽变了, 静止/滚动的判定要重量一遍 (防抖一下, 别跟每帧 resize 跑)
let marqueeResizeTimer = 0;
addEventListener("resize", () => {
  clearTimeout(marqueeResizeTimer);
  marqueeResizeTimer = setTimeout(() => {
    if (!currentTrack) return;
    setMarqueeLine($("#mini-title"), currentTrack.title);
    setMarqueeLine($("#mini-artist"), currentTrack.artist);
  }, 200);
});

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
// 封面下那行小字 (1.8.2 起只住 作词/作曲 标签, 专辑名挪去了艺人行):
// 有标签才占行, 没有整行收掉 —— 播放页纵向空间多一截 (用户点名)。
// 标签按需现读 (库里只有三成左右的歌带), 读过的缓存住。
const creditsCache = new Map();     // track_id → "作词 X · 作曲 Y" | ""
let creditsSequence = 0;            // 请求序号: 切曲后旧响应不再上屏

function updateSourceLine(track) {
  if (creditsCache.has(track.track_id)) {
    renderSourceLine(creditsCache.get(track.track_id));
    return;
  }
  renderSourceLine("");
  const token = ++creditsSequence;
  fetchJSON(`/music/api/tracks/${track.track_id}/credits`)
    .then((data) => {
      const parts = [];
      if (data.lyricist) parts.push(`作词 ${data.lyricist}`);
      if (data.composer) parts.push(`作曲 ${data.composer}`);
      creditsCache.set(track.track_id, parts.join(" · "));
      if (token !== creditsSequence) return;        // 已经切到别的歌了
      renderSourceLine(parts.join(" · "));
    })
    .catch(() => { /* 拿不到标签就不占行 */ });
}

/** 来源行上屏: 空文案整行藏掉 (不占布局)。 */
function renderSourceLine(text) {
  const line = $("#fp-source");
  line.hidden = !text;
  line.textContent = text;
}

// 收起后等滑出动画 (300ms) 再 display:none。这期间两层都要放行点击到下层列表
// (用户看见列表露出来了, 点了就该有反应); 重开必须撤掉挂着的隐藏定时器,
// 不然「刚关又马上开」时旧定时器会把正开着的播放页藏掉, 之后所有点击
// 全落到下层列表上 (表现为按键没反应、点了别的歌)。
