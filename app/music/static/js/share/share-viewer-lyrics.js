// share-viewer-lyrics — My Music 分享页歌词: 取词铺词/当前句高亮/手动滚词暂停跟唱。
// 拆自 share.html 的内联 <script> (结构化重构)。1.8.5 改 app 同款 (用户点名
// 「点开可以看字幕, 歌词界面跟 app 一致」): 标题行的字幕引号键开合歌词
// 视图 (罩住封面区的浮层), 不再常驻封面下面; 没词的曲子键灰掉。
"use strict";
/* global $, activeLyricIndex, audio, esc, lyricIndex: writable, lyrics: writable,
          lyricsAutoUntil: writable, lyricsCache, lyricsFollowPaused: writable,
          lyricsLastScrollAt: writable, parseLyrics, queue, queuePos, token */
/* exported loadLyrics, syncLyricHighlight */

// ------------------------------------------------------------ 歌词

let lyricsViewOpen = false;   // 字幕引号键开的歌词视图 (换曲不自动关, app 同款)

/** 字幕引号键: 开/合歌词视图 (没词的曲子键是灰的, 进不来)。 */
$("#fp-lyrics-btn").addEventListener("click", () => {
  if (!lyrics) return;
  lyricsViewOpen = !lyricsViewOpen;
  renderLyricsView();
});

/** 换曲铺词: 先空态, 取回来 (404 = 没词) 再铺; 换得快就听最后那首的。 */
async function loadLyrics(track) {
  lyrics = null;
  lyricIndex = -1;
  lyricsFollowPaused = false;
  renderLyricsView();
  if (lyricsCache.has(track.track_id)) {
    lyrics = lyricsCache.get(track.track_id);
    renderLyricsView();
    return;
  }
  let parsed = null;
  try {
    const resp = await fetch(`/music/share/${token}/lyrics/${track.track_id}`,
                             {cache: "no-store"});
    if (resp.ok) parsed = parseLyrics((await resp.json()).lyrics);
  } catch { /* 网络挂了当没词 */ }
  lyricsCache.set(track.track_id, parsed);
  const current = queue[queuePos];
  if (!current || current.track_id !== track.track_id) return;   // 已经换曲了
  lyrics = parsed;
  renderLyricsView();
}

function renderLyricsView() {
  const box = $("#fp-lyrics");
  const open = Boolean(lyrics) && lyricsViewOpen;
  box.classList.toggle("static", !lyrics || !lyrics.synced);
  $("#fp-lyrics-btn").disabled = !lyrics;         // 探明没词: 键灰掉点不开
  $("#fp-lyrics-btn").classList.toggle("on", open);
  box.hidden = !open;
  $("#fp-art-wrap").hidden = open;                // 视图开着: 封面让位
  if (!open) return;
  box.innerHTML = lyrics.lines.map(
    (line) => `<p class="lyrics-line" data-time="${line.timeSeconds}">`
      + `${esc(line.text)}</p>`).join("");
  box.scrollTop = 0;                              // 换曲/重铺从头 (1.8.5)
  syncLyricHighlight(true);
}

/** 高亮跟到当前句 (含近邻模糊分级), 顺带把当前句滚到视线中央。 */
function syncLyricHighlight(force) {
  if (!lyrics || !lyrics.synced) return;
  const index = activeLyricIndex(lyrics.lines, audio.currentTime);
  if (index === lyricIndex && !force) return;
  lyricIndex = index;
  const lines = $("#fp-lyrics").querySelectorAll(".lyrics-line");
  lines.forEach((line, i) => {
    line.classList.toggle("active", i === index);
    line.classList.toggle("near-1", Math.abs(i - index) === 1);
    line.classList.toggle("near-2", Math.abs(i - index) === 2);
  });
  if (index >= 0 && lines[index] && !lyricsFollowPaused) {
    scrollLyricsTo(lines[index]);
  }
}

function scrollLyricsTo(line) {
  const box = $("#fp-lyrics");
  lyricsAutoUntil = Date.now() + 900;   // smooth 滚动期间的 scroll 不算手动
  box.scrollTo({ top: line.offsetTop - box.clientHeight / 2
                         + line.offsetHeight / 2,
                 behavior: "smooth" });
}

// 手动滚词: 暂停跟唱, 静置 4 秒自动回去 (应用同款节奏)
$("#fp-lyrics").addEventListener("scroll", () => {
  if (Date.now() < lyricsAutoUntil) return;
  lyricsFollowPaused = true;
  lyricsLastScrollAt = Date.now();
});
setInterval(() => {
  if (lyricsFollowPaused && Date.now() - lyricsLastScrollAt > 4000) {
    lyricsFollowPaused = false;
    syncLyricHighlight(true);
  }
}, 600);

// 点句定位 (1.8.6, 用户点名「通过歌词快速定位歌曲进度」, app 同款):
// 点一句跳到那句的时间; 跳播后退出手动滚词的"暂停跟唱", 紧跟的
// timeupdate 把新当前句高亮并滚回视线中央。纯文本词没时间轴, 点不动。
$("#fp-lyrics").addEventListener("click", (event) => {
  const line = event.target.closest(".lyrics-line");
  if (!line || !lyrics || !lyrics.synced) return;
  const time = Number(line.dataset.time);
  if (time >= 0) audio.currentTime = time;
  lyricsFollowPaused = false;
  syncLyricHighlight(true);
});

