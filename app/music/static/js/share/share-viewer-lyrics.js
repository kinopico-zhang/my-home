// share-viewer-lyrics — My Music 分享页歌词: 取词铺词/当前句高亮/手动滚词暂停跟唱。
// 拆自 share.html 的内联 <script> (结构化重构)。1.8.2 起有词的曲子歌词
// 常驻封面下面跟着滚 (不再点封面切换): 没词整块收掉, 封面独占。
"use strict";
/* global $, activeLyricIndex, audio, esc, lyricIndex: writable, lyrics: writable,
          lyricsAutoUntil: writable, lyricsCache, lyricsFollowPaused: writable,
          lyricsLastScrollAt: writable, parseLyrics, queue, queuePos, token */
/* exported loadLyrics, syncLyricHighlight */

// ------------------------------------------------------------ 歌词

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
  box.classList.toggle("static", !lyrics || !lyrics.synced);
  box.hidden = !lyrics;                          // 没词: 封面独占
  box.closest(".fp-body").classList.toggle("with-lyrics", Boolean(lyrics));
  if (!lyrics) return;
  box.innerHTML = lyrics.lines.map(
    (line) => `<p class="lyrics-line">${esc(line.text)}</p>`).join("");
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

