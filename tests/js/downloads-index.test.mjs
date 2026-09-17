/* downloads.js 列表与统计的 node --test 单元测试: 在途条目合并展示,
   索引脏数据容错, 晚到进度回调, 缺字段曲目, 大小格式化, 用量统计。
   拆自 downloads.test.mjs (结构化重构, 代码逐字节未动)。 */
import test from "node:test";
import assert from "node:assert/strict";
import { createDownloads, formatBytes, TRACK,
         stubAdapters } from "./downloads-test-helpers.mjs";

test("entries: 下载中的条目也出现在列表里 (在途置顶)", async () => {
  const { adapters } = stubAdapters();
  const downloads = createDownloads(adapters);
  await downloads.downloadTrack(TRACK);                          // downloaded_at=1000
  const slow = { ...TRACK, track_id: 9, title: "曲B" };
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const originalBody = adapters.downloadBody;
  adapters.downloadBody = async (url, onProgress) => {           // 第二首挂住不完成
    await gate;
    return originalBody(url, onProgress);
  };
  const inFlight = downloads.downloadTrack(slow);
  await new Promise((resolve) => setTimeout(resolve, 0));         // 已进下载态
  const entries = downloads.entries();
  assert.equal(entries.length, 2);
  assert.equal(entries[0].track_id, 9);                           // 下载中排最上
  assert.equal(entries[0].state.status, "downloading");
  assert.equal(entries[1].track_id, 7);
  assert.equal(entries[1].state, null);
  release();
  assert.equal(await inFlight, true);
});

test("索引脏数据: 坏行丢弃, 时刻倒序 (缺时刻的排最后)", () => {
  const { adapters } = stubAdapters();
  adapters.readIndex = () => [
    null, { track_id: 1 }, { track_id: 2, downloaded_at: 100 },
    { track_id: 3, downloaded_at: 200 }, { track_id: 4 }, "junk",
  ];
  const downloads = createDownloads(adapters);
  // 缺时刻的 (1, 4) 沉底且保持原相对顺序
  assert.deepEqual(downloads.entries().map((entry) => entry.track_id), [3, 2, 1, 4]);
});

test("索引整体不是数组 (localStorage 手改坏): 当空处理", () => {
  const { adapters } = stubAdapters();
  adapters.readIndex = () => "not-a-json-array";
  const downloads = createDownloads(adapters);
  assert.deepEqual(downloads.entries(), []);
  assert.equal(downloads.isDownloaded(1), false);
});

test("晚到的进度回调 (状态已清) 不炸也不再上报", async () => {
  const { adapters } = stubAdapters();
  const downloads = createDownloads(adapters);
  let lateProgress;
  adapters.downloadBody = async (url, onProgress) => {
    lateProgress = onProgress;                     // 存起来, 下载"完成"后再发
    return { body: { size: 10 }, contentType: "audio/flac" };
  };
  assert.equal(await downloads.downloadTrack(TRACK), true);
  assert.equal(downloads.stateOf(7), null);        // 状态已清
  lateProgress(0.8);                               // 迟到的进度: 静默丢弃
  assert.equal(downloads.stateOf(7), null);
});

test("缺字段的曲目 (只有编号): 展示信息落空串, 不炸", async () => {
  const { adapters } = stubAdapters();
  const downloads = createDownloads(adapters);
  assert.equal(await downloads.downloadTrack({ track_id: 99 }), true);
  const [entry] = downloads.entries();
  assert.equal(entry.track_id, 99);
  assert.deepEqual(
    [entry.title, entry.artist, entry.album_title, entry.album_id,
     entry.duration_seconds],
    ["", "", "", 0, 0]);
});

test("formatBytes: B 恒整数, KB/MB 百内一位小数, 大数取整, 坏值归 0 B", () => {
  assert.equal(formatBytes(0), "0 B");
  assert.equal(formatBytes(-5), "0 B");
  assert.equal(formatBytes(Number.NaN), "0 B");
  assert.equal(formatBytes(512), "512 B");
  assert.equal(formatBytes(1023), "1023 B");
  assert.equal(formatBytes(1024), "1.0 KB");
  assert.equal(formatBytes(1536), "1.5 KB");
  assert.equal(formatBytes(38.2 * 1024 * 1024), "38.2 MB");
  assert.equal(formatBytes(100 * 1024 * 1024), "100 MB");
  assert.equal(formatBytes(1.5 * 1024 * 1024 * 1024), "1.5 GB");
  assert.equal(formatBytes(2048 * 1024 * 1024 * 1024), "2048 GB");   // 到 GB 封顶
});

test("storageUsage: 每首字节数 + 合计 (缓存丢了的按 0)", async () => {
  const { adapters } = stubAdapters();
  const downloads = createDownloads(adapters);
  await downloads.downloadTrack({ ...TRACK, track_id: 1 });
  await downloads.downloadTrack({ ...TRACK, track_id: 2 });
  await downloads.downloadTrack({ ...TRACK, track_id: 3 });
  adapters.cacheSize = async (url) =>
    ({ "/music/media/stream/1": 1000, "/music/media/stream/2": 2048 }[url] || 0);
  const usage = await downloads.storageUsage();
  assert.equal(usage.totalBytes, 3048);
  assert.deepEqual(usage.entries.map((row) => [row.track_id, row.bytes]),
    [[1, 1000], [2, 2048], [3, 0]]);
});
