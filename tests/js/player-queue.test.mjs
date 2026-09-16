/* player-queue.js (播放队列纯逻辑) 的 node --test 单元测试。
   覆盖: 建队/当前曲、前进 (队尾停/循环回绕)、后退 (队首原地)、跳转、
   随机开关 (当前曲不换位)、循环模式轮换、剩余队列、拖行换位。 */
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const dir = path.join(path.dirname(fileURLToPath(import.meta.url)), "../../app/music/static");
const { createPlayQueue, queueCurrent, queueSetShuffle, queueShuffleAll,
        queueCycleRepeat, queueAdvance, queueGoBack, queueJump, queueUpcoming,
        queueReorder } =
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

test("queueShuffleAll: 开播即随机 = 整队洗牌, 不把起播曲钉在队首", () => {
  const queue = createPlayQueue(titles, 0);           // 随机键场景: 起播下标 0
  queueShuffleAll(queue);
  assert.equal(queue.position, 0);
  assert.equal(queue.shuffle, true);
  assert.deepEqual([...queue.order].sort((a, b) => a - b), [0, 1, 2, 3]);  // 是排列
  // 洗出来不总是原顺序 (4 首全排列 24 种, 洗 20 次回回撞上原样的概率 ~1e-27)
  const seenShuffled = Array.from({ length: 20 }, () => {
    queueShuffleAll(queue);
    return queue.order.some((value, index) => value !== index);
  });
  assert.ok(seenShuffled.some(Boolean));
});

test("queueShuffleAll: 单曲/空队列不炸", () => {
  const single = createPlayQueue([titles[0]], 0);
  queueShuffleAll(single);
  assert.deepEqual(single.order, [0]);
  assert.equal(queueCurrent(single).title, "A");
  const empty = createPlayQueue([], 0);
  queueShuffleAll(empty);
  assert.deepEqual(empty.order, []);
  assert.equal(queueCurrent(empty), null);
});

test("queueCycleRepeat: off → all → one → off", () => {  const queue = createPlayQueue(titles, 0);
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

test("queueReorder: 下面的行往上拖, 当前曲位置相应后移", () => {
  const queue = createPlayQueue(titles, 0);             // 当前 A, 顺序 ABCD
  assert.equal(queueReorder(queue, 2, 0), true);        // C 拖到最前
  assert.deepEqual(queue.order, [2, 0, 1, 3]);          // CABD
  assert.equal(queue.position, 1);                      // A 还在播, 顺位变 2
  assert.equal(queueCurrent(queue).title, "A");
  assert.deepEqual(queueUpcoming(queue).map((t) => t.title), ["A", "B", "D"]);
});

test("queueReorder: 上面的行往下拖, 当前曲位置前移", () => {
  const queue = createPlayQueue(titles, 2);             // 当前 C, 顺序 ABCD
  assert.equal(queueReorder(queue, 0, 3), true);        // A 拖到队尾
  assert.deepEqual(queue.order, [1, 2, 3, 0]);          // BCDA
  assert.equal(queue.position, 1);                      // C 顺位提前
  assert.equal(queueCurrent(queue).title, "C");
});

test("queueReorder: 拖当前曲自己, 当前曲跟着走", () => {
  const queue = createPlayQueue(titles, 1);             // 当前 B
  assert.equal(queueReorder(queue, 1, 3), true);        // B 拖到队尾
  assert.deepEqual(queue.order, [0, 2, 3, 1]);          // ACDB
  assert.equal(queue.position, 3);
  assert.equal(queueCurrent(queue).title, "B");
  assert.deepEqual(queueUpcoming(queue).map((t) => t.title), ["B"]);
});

test("queueReorder: 与当前位无关的换位不动 position; 越界/原地拒绝", () => {
  const queue = createPlayQueue(titles, 3);             // 当前 D
  assert.equal(queueReorder(queue, 0, 1), true);        // A B 互换, 在 D 前
  assert.deepEqual(queue.order, [1, 0, 2, 3]);
  assert.equal(queue.position, 3);
  assert.equal(queueReorder(queue, 0, 0), false);       // 原地
  assert.equal(queueReorder(queue, -1, 2), false);      // 越界
  assert.equal(queueReorder(queue, 0, 9), false);
  assert.equal(queueReorder(queue, 9, 0), false);
  assert.deepEqual(queue.order, [1, 0, 2, 3]);          // 拒绝的都不动队
  const empty = createPlayQueue([], 0);
  assert.equal(queueReorder(empty, 0, 0), false);
});
