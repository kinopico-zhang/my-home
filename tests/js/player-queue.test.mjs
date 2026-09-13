/* player-queue.js (播放队列纯逻辑) 的 node --test 单元测试。
   覆盖: 建队/当前曲、前进 (队尾停/循环回绕)、后退 (队首原地)、跳转、
   随机开关 (当前曲不换位)、循环模式轮换、剩余队列。 */
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const dir = path.join(path.dirname(fileURLToPath(import.meta.url)), "../../app/music/static");
const { createPlayQueue, queueCurrent, queueSetShuffle, queueCycleRepeat,
        queueAdvance, queueGoBack, queueJump, queueUpcoming } =
  require(path.join(dir, "player-queue.js"));

const titles = ["A", "B", "C", "D"].map((title, index) => ({ track_id: index + 1, title }));

test("createPlayQueue: 原顺序 + 起始位 (越界钳到队内)", () => {
  const queue = createPlayQueue(titles, 9);
  assert.deepEqual(queue.order, [0, 1, 2, 3]);
  assert.equal(queue.position, 3);
  assert.equal(queueCurrent(queue).title, "D");
  assert.equal(queue.shuffle, false);
  assert.equal(queue.repeat, "off");
});

test("createPlayQueue: 空队列合法, 当前曲为 null", () => {
  const queue = createPlayQueue([], 0);
  assert.equal(queue.position, -1);
  assert.equal(queueCurrent(queue), null);
  assert.equal(queueAdvance(queue), null);
});

test("queueAdvance: 顺播到队尾停 (null), all 模式回绕", () => {
  const queue = createPlayQueue(titles, 2);
  assert.equal(queueAdvance(queue).title, "D");
  assert.equal(queueAdvance(queue), null);            // off: 队尾停
  assert.equal(queue.position, 3);
  queue.repeat = "all";
  assert.equal(queueAdvance(queue).title, "A");       // 回绕
  assert.equal(queueCurrent(queue).title, "A");
});

test("queueAdvance: 单曲循环也照常前进 (重播由调用方处理)", () => {
  const queue = createPlayQueue(titles, 0);
  queue.repeat = "one";
  assert.equal(queueAdvance(queue).title, "B");
});

test("queueGoBack: 后退, 队首原地 (调用方 seek 0)", () => {
  const queue = createPlayQueue(titles, 2);
  assert.equal(queueGoBack(queue).title, "B");
  assert.equal(queueGoBack(queue).title, "A");
  assert.equal(queueGoBack(queue).title, "A");        // 不出队
  assert.equal(queue.position, 0);
});

test("queueJump: 按曲目 id 跳转, 没有返回 null", () => {
  const queue = createPlayQueue(titles, 0);
  assert.equal(queueJump(queue, 3).title, "C");
  assert.equal(queue.position, 2);
  assert.equal(queueJump(queue, 999), null);
  assert.equal(queue.position, 2);                    // 跳失败不动位置
});

test("queueSetShuffle: 开 = 当前曲领头其余洗牌, 关 = 回原顺序", () => {
  const queue = createPlayQueue(titles, 2);           // 当前 C
  queueSetShuffle(queue, true);
  assert.equal(queue.position, 0);
  assert.equal(queueCurrent(queue).title, "C");
  assert.equal(queue.order.length, 4);
  assert.deepEqual([...queue.order].sort((a, b) => a - b), [0, 1, 2, 3]);  // 是排列
  assert.equal(queue.shuffle, true);
  queueSetShuffle(queue, false);
  assert.deepEqual(queue.order, [0, 1, 2, 3]);
  assert.equal(queueCurrent(queue).title, "C");       // 曲目不因开关换掉
});

test("queueCycleRepeat: off → all → one → off", () => {
  const queue = createPlayQueue(titles, 0);
  assert.equal(queueCycleRepeat(queue), "all");
  assert.equal(queueCycleRepeat(queue), "one");
  assert.equal(queueCycleRepeat(queue), "off");
});

test("queueUpcoming: 当前曲领头的剩余队列", () => {
  const queue = createPlayQueue(titles, 2);
  assert.deepEqual(queueUpcoming(queue).map((t) => t.title), ["C", "D"]);
  queue.position = -1;
  assert.deepEqual(queueUpcoming(queue).map((t) => t.title),
    ["A", "B", "C", "D"]);                            // 没在播 = 整队
});

test("queueSetShuffle: 空队列开关随机都不炸, 仍是空队列", () => {
  const queue = createPlayQueue([], 0);
  queueSetShuffle(queue, true);
  assert.deepEqual(queue.order, []);
  assert.equal(queueCurrent(queue), null);
  queueSetShuffle(queue, false);
  assert.deepEqual(queue.order, []);
  assert.equal(queueCurrent(queue), null);
});
