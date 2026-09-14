/* downloads.js (离线下载纯逻辑) 的 node --test 单元测试。
   覆盖: 能力判定、下载成功 (索引落库 + 状态流转 + 进度回调)、
   重复下载拒绝、失败不占位、删除 (缓存 + 索引)、下载中条目合并展示。 */
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const dir = path.join(path.dirname(fileURLToPath(import.meta.url)), "../../app/music/static");
const { downloadsSupported, createDownloads } =
  require(path.join(dir, "downloads.js"));

const TRACK = { track_id: 7, title: "曲A", artist: "AI机组", album_id: 3,
                album_title: "甲", duration_seconds: 200, playable: true };

/** 桩适配器: 索引在内存里, 下载体可编排进度, 缓存记录调用。 */
function stubAdapters({ bodyChunks = [new Uint8Array(10)], failAt = null } = {}) {
  const calls = { puts: [], deletes: [], indexWrites: 0, progress: [] };
  let index = [];
  return {
    adapters: {
      readIndex: () => JSON.parse(JSON.stringify(index)),
      writeIndex: (entries) => { index = JSON.parse(JSON.stringify(entries)); calls.indexWrites += 1; },
      async downloadBody(url, onProgress) {
        if (failAt === "fetch") throw new Error("HTTP 503");
        let total = 0;
        for (const chunk of bodyChunks) total += chunk.byteLength;
        let seen = 0;
        for (const chunk of bodyChunks) {
          seen += chunk.byteLength;
          onProgress(seen / total);
        }
        calls.progress = null;
        if (failAt === "put") throw new Error("quota");
        return { body: { size: total }, contentType: "audio/flac" };
      },
      async cachePut(url, body, contentType) {
        if (failAt === "put") throw new Error("quota");
        calls.puts.push({ url, size: body.size, contentType });
      },
      async cacheDelete(url) { calls.deletes.push(url); },
      now: () => 1000,
    },
    calls,
  };
}

test("downloadsSupported: 三个条件齐了才亮", () => {
  assert.equal(downloadsSupported(
    { secureContext: true, cacheApi: true, serviceWorkerApi: true }), true);
  assert.equal(downloadsSupported(
    { secureContext: false, cacheApi: true, serviceWorkerApi: true }), false);
  assert.equal(downloadsSupported(
    { secureContext: true, cacheApi: false, serviceWorkerApi: true }), false);
  assert.equal(downloadsSupported(
    { secureContext: true, cacheApi: true, serviceWorkerApi: false }), false);
});

test("downloadTrack: 字节进缓存 + 索引落库 + 进度回调 + 通知", async () => {
  const { adapters, calls } = stubAdapters(
    { bodyChunks: [new Uint8Array(30), new Uint8Array(10)] });
  const downloads = createDownloads(adapters);
  const events = [];
  downloads.onChange(() => events.push("n"));
  assert.equal(downloads.isDownloaded(7), false);
  const progressSeen = [];
  adapters.downloadBody = async (url, onProgress) => {
    onProgress(0.5); onProgress(1);
    progressSeen.push(url);
    return { body: { size: 40 }, contentType: "audio/flac" };
  };
  assert.equal(await downloads.downloadTrack(TRACK), true);
  assert.deepEqual(calls.puts,
    [{ url: "/music/media/stream/7", size: 40, contentType: "audio/flac" }]);
  assert.equal(downloads.isDownloaded(7), true);
  assert.equal(downloads.stateOf(7), null);           // 完成后瞬态清掉
  const [entry] = downloads.entries();
  assert.equal(entry.title, "曲A");
  assert.equal(entry.downloaded_at, 1000);
  assert.ok(events.length >= 3);                      // 开始 + 进度 + 完成
});

test("downloadTrack: 已下载/下载中/坏曲目都拒绝", async () => {
  const { adapters } = stubAdapters();
  const downloads = createDownloads(adapters);
  await downloads.downloadTrack(TRACK);
  assert.equal(await downloads.downloadTrack(TRACK), false);   // 已在库
  const other = { ...TRACK, track_id: 8 };
  const first = downloads.downloadTrack(other);                // 在途
  assert.equal(await downloads.downloadTrack(other), false);   // 重复触发
  await first;
  assert.equal(await downloads.downloadTrack(null), false);
  assert.equal(await downloads.downloadTrack({ track_id: "x" }), false);
});

test("downloadTrack: 失败不占位 (图标弹回未下载), 索引不落", async () => {
  for (const failAt of ["fetch", "put"]) {
    const { adapters, calls } = stubAdapters({ failAt });
    const downloads = createDownloads(adapters);
    await assert.rejects(downloads.downloadTrack(TRACK), /503|quota/);
    assert.equal(downloads.isDownloaded(7), false);
    assert.equal(downloads.stateOf(7), null);
    assert.equal(calls.indexWrites, 0);
  }
});

test("removeDownload: 缓存与索引一起清", async () => {
  const { adapters, calls } = stubAdapters();
  const downloads = createDownloads(adapters);
  await downloads.downloadTrack(TRACK);
  await downloads.removeDownload(7);
  assert.deepEqual(calls.deletes, ["/music/media/stream/7"]);
  assert.equal(downloads.isDownloaded(7), false);
  assert.deepEqual(downloads.entries(), []);
});

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
