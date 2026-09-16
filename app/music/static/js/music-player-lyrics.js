// music-player-lyrics — My Music 歌词: 拉取/解析缓存/当前行高亮 + rAF 缓动滚动跟唱。
// 拆自 music-player.js (结构化重构: 代码逐字节未动, 按 music.html 里的顺序加载, 跨模块引用走全局)。
"use strict";
/* global $, LYRICS_FOLLOW_RESUME_MS, activeLyricIndex, audioElement, currentTrack,
          escapeHTML, fetchJSON, lyricsActiveIndex: writable, lyricsAutoScrolling: writable,
          lyricsCache, lyricsFollowPaused: writable, lyricsLastScrollAt, lyricsViewOpen,
          parseLyrics, syncLyricsButton */
/* exported cancelLyricsScroll, highlightActiveLyric, loadLyrics, lyricsAutoScrolling,
            resumeLyricsFollow */

// ------------------------------------------------------------ 歌词

async function loadLyrics() {
  const track = currentTrack;
  if (!track) return;
  if (!lyricsCache.has(track.track_id)) {
    try {
      const response = await fetchJSON(
        `/music/api/tracks/${track.track_id}/lyrics`);
      lyricsCache.set(track.track_id, response.lyrics ? parseLyrics(response.lyrics) : null);
    } catch (_error) {
      lyricsCache.set(track.track_id, null);
    }
  }
  if (!currentTrack || currentTrack.track_id !== track.track_id) return;  // 已切曲
  syncLyricsButton();
  const lyricsDocument = lyricsCache.get(track.track_id);
  const container = $("#fp-lyrics");
  if (!lyricsDocument || !lyricsDocument.lines.length) {
    cancelLyricsScroll();                  // 旧动画别再追已重铺的行
    container.innerHTML = '<div class="lyrics-empty">这首歌没有歌词</div>';
    return;
  }
  cancelLyricsScroll();
  container.innerHTML = lyricsDocument.lines.map((line) =>
    `<div class="lyrics-line" data-time="${line.timeSeconds}">${escapeHTML(line.text)}</div>`
  ).join("");
  // 无时间轴的歌词没有"当前句", 谈不上距离模糊 → 整页清晰
  container.classList.toggle("static", !lyricsDocument.synced);
  lyricsActiveIndex = -1;
  highlightActiveLyric();
}

/** timeupdate 驱动: 高亮行永远跟着歌走; 手动滑过就只亮不滚,
    静置片刻自动回位。 */
function highlightActiveLyric() {
  if (!lyricsViewOpen || !currentTrack) return;
  const lyricsDocument = lyricsCache.get(currentTrack.track_id);
  if (!lyricsDocument || !lyricsDocument.synced) return;
  const index = activeLyricIndex(lyricsDocument.lines, audioElement().currentTime);
  if (index !== lyricsActiveIndex) {
    lyricsActiveIndex = index;
    const container = $("#fp-lyrics");
    const lines = container.children;
    for (let position = 0; position < lines.length; position++) {
      lines[position].classList.toggle("active", position === index);
      // 距离模糊: 离当前句越近越清晰 (近一两句半模糊, 更远全模糊)
      const distance = Math.abs(position - index);
      lines[position].classList.toggle("near-1", distance === 1);
      lines[position].classList.toggle("near-2", distance === 2);
    }
    if (!lyricsFollowPaused && index >= 0 && lines[index]) {
      scrollLyricsTo(lines[index]);
    }
  }
  if (lyricsFollowPaused) maybeResumeLyricsFollow();
}

/** 歌词容器滚动到某行居中 —— rAF 指数缓出追目标, 丝滑滚动 (Apple Music 风):
    目标位置每帧重算 (行高跟着"放大动画"在变, 一次算死会差半行);
    Chrome 的 rAF 时间戳会回退, dt 钳制后再用。 */
let lyricsScrollRaf = 0;            // 在跑的动画帧句柄 (0 = 没在动)
let lyricsScrollTargetLine = null;  // 追踪中的行 (换曲重铺后作废)
let lyricsScrollLastTime = 0;       // 上一帧时刻 (算 dt)
let lyricsScrollGraceTimer = 0;     // 动画停后还把 scroll 事件当自己的宽限期

function scrollLyricsTo(lineElement) {
  const container = $("#fp-lyrics");
  if (!container.contains(lineElement)) return;   // 换曲重铺前的旧行: 别滚
  lyricsScrollTargetLine = lineElement;
  clearTimeout(lyricsScrollGraceTimer);
  lyricsAutoScrolling = true;
  if (!lyricsScrollRaf) {
    lyricsScrollLastTime = performance.now();
    lyricsScrollRaf = requestAnimationFrame(lyricsScrollFrame);
  }
}

function lyricsScrollFrame(now) {
  lyricsScrollRaf = 0;
  const container = $("#fp-lyrics");
  const line = lyricsScrollTargetLine;
  if (!line || !container.contains(line)) {
    endLyricsScroll();
    return;
  }
  const dt = Math.min(Math.max(now - lyricsScrollLastTime, 0), 40) / 1000;
  lyricsScrollLastTime = now;
  const target = line.offsetTop - container.clientHeight / 2
    + line.offsetHeight / 2;
  const remaining = target - container.scrollTop;
  if (Math.abs(remaining) < 1) {
    container.scrollTop = target;
    endLyricsScroll();
    return;
  }
  container.scrollTop += remaining * Math.min(1, dt * 10);   // 指数缓出
  lyricsScrollRaf = requestAnimationFrame(lyricsScrollFrame);
}

/** 动画到点收尾: 撤目标, scroll 事件的宽限再撑一小会儿。 */
function endLyricsScroll() {
  lyricsScrollTargetLine = null;
  clearTimeout(lyricsScrollGraceTimer);
  lyricsScrollGraceTimer = setTimeout(() => {
    lyricsAutoScrolling = false;
  }, 150);
}

/** 用户上手滚歌词: 立刻交还控制权 (别跟手指抢), 之后的滚动算手动。 */
function cancelLyricsScroll() {
  if (lyricsScrollRaf) cancelAnimationFrame(lyricsScrollRaf);
  lyricsScrollRaf = 0;
  lyricsScrollTargetLine = null;
  clearTimeout(lyricsScrollGraceTimer);
  lyricsAutoScrolling = false;
}

/** 手动滑过歌词后静置够了就回到跟唱。 */
function maybeResumeLyricsFollow() {
  if (!lyricsFollowPaused) return;
  if (Date.now() - lyricsLastScrollAt < LYRICS_FOLLOW_RESUME_MS) return;
  resumeLyricsFollow();
}

function resumeLyricsFollow(scrollToActive = true) {
  lyricsFollowPaused = false;
  $("#lyrics-resume").hidden = true;
  $("#fp-lyrics").classList.remove("browsing");   // 浏览态结束, 距离模糊回来
  const lines = $("#fp-lyrics").children;
  if (scrollToActive && lyricsActiveIndex >= 0 && lines[lyricsActiveIndex]) {
    scrollLyricsTo(lines[lyricsActiveIndex]);
  }
}

