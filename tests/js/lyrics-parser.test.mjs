/* lyrics-parser.js (歌词解析纯逻辑) 的 node --test 单元测试。
   覆盖: lrc 时间轴 (多标签展开/排序/元数据剔除)、纯文本模式、
   逐行高亮定位、时间格式化。 */
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const dir = path.join(path.dirname(fileURLToPath(import.meta.url)), "../../app/music/static/js");
const { parseLyrics, activeLyricIndex, formatPlaybackTime } = require(path.join(dir, "lyrics-parser.js"));

test("parseLyrics: 同步歌词 (剥时间轴/排序/元数据与空行剔除)", () => {
  const document = parseLyrics([
    "[ti:曲名]",                                  // 元数据行剔除
    "[00:00.00]",                                 // 空时间轴行剔除
    "",
    "[00:12.50]第二行",
    "[00:05]第一行",                              // 乱序输入
    "[00:20][00:40]副歌",                         // 一行多时间轴展开
    "纯文本尾巴",                                  // 同步模式下的无轴行剔除
  ].join("\r\n"));
  assert.equal(document.synced, true);
  assert.deepEqual(document.lines, [
    { timeSeconds: 5, text: "第一行" },
    { timeSeconds: 12.5, text: "第二行" },
    { timeSeconds: 20, text: "副歌" },
    { timeSeconds: 40, text: "副歌" },
  ]);
});

test("parseLyrics: 毫秒按位数补零, 逗号分隔也认", () => {
  const document = parseLyrics("[00:12.5]a\n[01:02,345]b\n[001:02]c");
  assert.deepEqual(document.lines.map((line) => line.timeSeconds),
    [12.5, 62, 62.345]);
  assert.deepEqual(document.lines.map((line) => line.text), ["a", "c", "b"]);
});

test("parseLyrics: 纯文本歌词 → 整页阅读模式", () => {
  const document = parseLyrics("第一句\n[看不懂的方括号] 第二句\n\n第三句");
  assert.equal(document.synced, false);
  assert.deepEqual(document.lines, [
    { timeSeconds: -1, text: "第一句" },
    { timeSeconds: -1, text: "[看不懂的方括号] 第二句" },
    { timeSeconds: -1, text: "第三句" },
  ]);
});

test("parseLyrics: 空内容/纯标签 → 空文档", () => {
  assert.deepEqual(parseLyrics(""), { synced: false, lines: [] });
  assert.deepEqual(parseLyrics(null), { synced: false, lines: [] });
  assert.deepEqual(parseLyrics("[ti:x][ar:y]"), { synced: false, lines: [] });
});

test("activeLyricIndex: 按进度定位当前行", () => {
  const { lines } = parseLyrics("[00:05]a\n[00:10]b\n[00:20]c");
  assert.equal(activeLyricIndex(lines, 0), -1);       // 还没到第一行
  assert.equal(activeLyricIndex(lines, 4.999), -1);
  assert.equal(activeLyricIndex(lines, 5), 0);
  assert.equal(activeLyricIndex(lines, 9.9), 0);
  assert.equal(activeLyricIndex(lines, 10.0001), 1);  // 浮点容差内算已开始
  assert.equal(activeLyricIndex(lines, 999), 2);
  // 纯文本没有可高亮的行
  assert.equal(activeLyricIndex(parseLyrics("a\nb").lines, 5), -1);
  assert.equal(activeLyricIndex([], 5), -1);
});

test("formatPlaybackTime: 分秒/时分秒/非数兜底", () => {
  assert.equal(formatPlaybackTime(0), "0:00");
  assert.equal(formatPlaybackTime(65), "1:05");
  assert.equal(formatPlaybackTime(600.7), "10:00");
  assert.equal(formatPlaybackTime(3723), "1:02:03");
  assert.equal(formatPlaybackTime(-5), "0:00");
  assert.equal(formatPlaybackTime(Number.NaN), "0:00");
});
