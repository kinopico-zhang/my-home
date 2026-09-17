/* downloads.js 下载与删除的 node --test 单元测试: 能力判定, 下载成功
   (索引落库 + 状态流转 + 进度回调), 重复/坏曲目拒绝, 失败不占位,
   删除清缓存与索引, 下载中删除 = 取消, 一键清空。
   拆自 downloads.test.mjs (结构化重构, 代码逐字节未动)。 */
import test from "node:test";
import assert from "node:assert/strict";
import { createDownloads, downloadsSupported, TRACK,
         hangOnSignal, stubAdapters } from "./downloads-test-helpers.mjs";

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

test("removeDownload 对下载中的歌 = 取消: 掐断下载, 状态清, 索引不落, 不算失败", async () => {
  const { adapters, calls } = stubAdapters();
  const downloads = createDownloads(adapters);
  hangOnSignal(adapters);
  const inFlight = downloads.downloadTrack({ ...TRACK, track_id: 5 });
  await new Promise((resolve) => setTimeout(resolve, 0));        // 已进下载态
  assert.equal(downloads.stateOf(5).status, "downloading");
  await downloads.removeDownload(5);
  assert.equal(await inFlight, false);                           // 取消不抛错
  assert.equal(downloads.stateOf(5), null);
  assert.equal(downloads.isDownloaded(5), false);
  assert.deepEqual(downloads.entries(), []);                     // 索引里没有这一首
  assert.deepEqual(calls.deletes, ["/music/media/stream/5"]);   // 空删一次, 无妨
});

test("removeAll: 已完成的逐首清缓存 + 索引清空, 下载中的一并取消", async () => {
  const { adapters, calls } = stubAdapters();
  const downloads = createDownloads(adapters);
  await downloads.downloadTrack({ ...TRACK, track_id: 1 });
  await downloads.downloadTrack({ ...TRACK, track_id: 2 });
  hangOnSignal(adapters);
  const inFlight = downloads.downloadTrack({ ...TRACK, track_id: 3 });
  await new Promise((resolve) => setTimeout(resolve, 0));
  const notified = [];
  downloads.onChange(() => notified.push(1));
  await downloads.removeAll();
  assert.equal(await inFlight, false);                           // 取消路径先收尾
  assert.deepEqual([...calls.deletes].sort(),
    ["/music/media/stream/1", "/music/media/stream/2"]);
  assert.equal(downloads.isDownloaded(1), false);
  assert.equal(downloads.isDownloaded(2), false);
  assert.deepEqual(downloads.entries(), []);                     // 索引空, 在途也清了
  assert.ok(notified.length >= 1);
});
