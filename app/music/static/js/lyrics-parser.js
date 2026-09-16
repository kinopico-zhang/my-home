// lyrics-parser.js — 歌词解析纯逻辑 (lrc 时间轴 / 逐行高亮定位 / 时间格式化)。
// 单独成模块: node --test 直测 + tsc --checkJs + c8 覆盖 (页面脚本由 E2E 覆盖)。

/**
 * 一行歌词。
 * @typedef {Object} LyricLine
 * @property {number} timeSeconds 该行开始时间; 纯文本歌词无时间轴, 恒 -1
 * @property {string} text       剥掉时间轴标签后的文本
 */

/**
 * 整篇歌词。
 * @typedef {Object} LyricsDocument
 * @property {boolean} synced    true = 有时间轴, 逐行高亮; false = 纯文本整页阅读
 * @property {LyricLine[]} lines 同步歌词按时间升序
 */

// 行首时间轴标签: [00:12.34] / [1:02:03] / [00:12,345] (分 1-3 位, 秒 2 位, 毫秒 1-3 位)
const TIMECODE_PATTERN = /^\[(\d{1,3}):(\d{2})(?:[.,](\d{1,3}))?\]/;
// 整行只有标签 (元数据 [ti:xxx] / 独占一行的空时间轴) → 丢弃
const TAG_ONLY_PATTERN = /^(?:\[[^\]]*\])+\s*$/;

/** 时间轴标签里的分/秒/毫秒 → 秒数 (毫秒按位数右补零到千分位)。 */
function timecodeToSeconds(minutes, seconds, fraction) {
  const milliseconds = fraction ? Number(fraction.padEnd(3, "0")) : 0;
  return Number(minutes) * 60 + Number(seconds) + milliseconds / 1000;
}

/**
 * 歌词原文 → 结构化歌词。
 * 一行带多个时间轴 ([00:10]词[00:30]词) 展开成多条; 有时间轴的行才算同步
 * 歌词, 没有时间轴的文本行只在整篇都不同步时保留 (同步模式下它们多半是
 * 元数据或翻译注)。空文本行 (只有时间轴没有词) 一律丢弃。
 * @param {string} lyricsText 歌词原文 (lrc 或纯文本)
 * @returns {LyricsDocument}
 */
function parseLyrics(lyricsText) {
  /** @type {LyricLine[]} */
  const timed = [];
  /** @type {LyricLine[]} */
  const plain = [];
  for (const rawLine of String(lyricsText || "").split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || TAG_ONLY_PATTERN.test(line)) continue;
    /** @type {number[]} */
    const times = [];
    let rest = line;
    while (true) {
      const match = TIMECODE_PATTERN.exec(rest);
      if (!match) break;
      times.push(timecodeToSeconds(match[1], match[2], match[3]));
      rest = rest.slice(match[0].length);
    }
    const text = rest.trim();
    if (!text) continue;
    if (times.length) {
      for (const timeSeconds of times) timed.push({ timeSeconds, text });
    } else {
      plain.push({ timeSeconds: -1, text });
    }
  }
  timed.sort((a, b) => a.timeSeconds - b.timeSeconds);
  return timed.length ? { synced: true, lines: timed }
    : { synced: false, lines: plain };
}

/**
 * 播放进度 → 当前该高亮第几行 (该行已开始、下一行还没开始的最后一行)。
 * 纯文本歌词 (无时间轴) 恒 -1; 进度在第一行之前也是 -1。
 * @param {LyricLine[]} lines
 * @param {number} timeSeconds
 * @returns {number} 行下标, -1 = 还没到第一行
 */
function activeLyricIndex(lines, timeSeconds) {
  let active = -1;
  for (let index = 0; index < lines.length; index++) {
    const lineTime = lines[index].timeSeconds;
    if (lineTime < 0) break;              // 纯文本歌词没有可高亮的行
    if (lineTime <= timeSeconds + 1e-6) active = index;
    else break;
  }
  return active;
}

/**
 * 秒数 → 播放器时间文案 ("3:05" / "1:02:03")。负数/NaN 都当 0。
 * @param {number} seconds
 * @returns {string}
 */
function formatPlaybackTime(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const rest = total % 60;
  const minuteText = hours ? String(minutes).padStart(2, "0") : String(minutes);
  const secondText = String(rest).padStart(2, "0");
  return hours ? `${hours}:${minuteText}:${secondText}` : `${minutes}:${secondText}`;
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { parseLyrics, activeLyricIndex, formatPlaybackTime };
}
