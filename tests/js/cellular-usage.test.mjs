/* cellular-usage.js (蜂窝流量记账纯逻辑) 的 node --test 单元测试。
   覆盖: 水位去重 (快照重复给只记一次)、wifi/蜂窝归账门槛、
   够量立即报、隔时兜底报、上报失败留账重报、在途不并发
   (在途期间新攒的字节不丢不重)、onHide 兜底、start/stop 幂等、
   字段回退 (无 transferSize 用 decodedBodySize, 都没有记 0)。 */
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const dir = path.join(path.dirname(fileURLToPath(import.meta.url)), "../../app/music/static/js");
const { createCellularMonitor } = require(path.join(dir, "cellular-usage.js"));

/** 让出事件循环: tick 里火后不理的 flush 走完收尾 (扣账/解在途锁)。 */
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

/** 桩适配器: 资源表可逐步追加, 网络类型/时刻可切, 上报可编排成败。 */
function stubAdapters({ cellular = true, reportFail = null } = {}) {
  const state = { entries: [], cellular, now: 0, reports: [] };
  let hangReport = null;
  const adapters = {
    isCellular: () => state.cellular,
    takeEntries: () => state.entries,
    async report(bytes) {
      if (reportFail === "reject") throw new Error("offline");
      state.reports.push(bytes);
      if (reportFail === "hang") await new Promise((resolve) => { hangReport = resolve; });
    },
    now: () => state.now,
  };
  return { adapters, state, releaseHang: () => hangReport && hangReport() };
}

/** 往资源表里加一条 (transferSize 缺省给 100 字节)。 */
function addEntry(state, responseEnd, bytes = 100, fields = {}) {
  state.entries.push({ responseEnd, transferSize: bytes, ...fields });
}

test("水位去重: 资源表给全量快照, 同一条只记一次", () => {
  const { adapters, state } = stubAdapters();
  state.now = 0;
  const monitor = createCellularMonitor(adapters);
  addEntry(state, 10, 500);
  monitor.tick();
  assert.equal(monitor.pendingBytes(), 500);
  monitor.tick();              // 快照重复给同一条, 不重复记账
  monitor.tick();
  assert.equal(monitor.pendingBytes(), 500);
});

test("wifi 下不归账; 切回蜂窝后新资源才计", () => {
  const { adapters, state } = stubAdapters({ cellular: false });
  const monitor = createCellularMonitor(adapters);
  addEntry(state, 10, 500);
  monitor.tick();
  assert.equal(monitor.pendingBytes(), 0);
  state.cellular = true;
  addEntry(state, 20, 300);
  monitor.tick();
  assert.equal(monitor.pendingBytes(), 300);
});

test("攒够阈值立即上报, 账清零", async () => {
  const { adapters, state } = stubAdapters();
  const monitor = createCellularMonitor(adapters);
  addEntry(state, 10, 1024 * 1024);
  monitor.tick();
  assert.deepEqual(state.reports, [1024 * 1024]);
  await monitor.flush();       // 没账就是空操作, 不再报
  assert.equal(monitor.pendingBytes(), 0);
  assert.equal(state.reports.length, 1);
});

test("够隔时兜底上报 (阈值没到但 15 秒到了)", async () => {
  const { adapters, state } = stubAdapters();
  state.now = 1000;
  const monitor = createCellularMonitor({ ...adapters,
    flushThresholdBytes: 1024 * 1024, flushIntervalMs: 15000 });
  addEntry(state, 10, 400);
  state.now += 1000;
  monitor.tick();
  assert.equal(state.reports.length, 0);   // 时限没到, 攒着
  state.now += 15000;
  monitor.tick();
  await settle();
  assert.deepEqual(state.reports, [400]);
  assert.equal(monitor.pendingBytes(), 0);
});

test("上报失败留账, 下轮重报成功", async () => {
  const { adapters, state } = stubAdapters({ reportFail: "reject" });
  state.now = 1000;
  const monitor = createCellularMonitor(adapters);
  addEntry(state, 10, 700);
  state.now += 20000;
  monitor.tick();
  await settle();                             // 失败的 flush 走完 catch, 解在途锁
  assert.equal(state.reports.length, 0);
  assert.equal(monitor.pendingBytes(), 700);   // 失败没丢账
  adapters.report = async (bytes) => { state.reports.push(bytes); };
  monitor.tick();
  assert.deepEqual(state.reports, [700]);
});

test("在途不并发; 在途期间新攒的字节不丢不重", async () => {
  const { adapters, state, releaseHang } = stubAdapters({ reportFail: "hang" });
  state.now = 1000;
  const monitor = createCellularMonitor(adapters);
  addEntry(state, 10, 600);
  state.now += 20000;
  monitor.tick();                          // flush 挂住在途 (600 已报出口径先得)
  assert.equal(state.reports.length, 1);
  addEntry(state, 20, 50);                 // 在途期间又攒 50
  state.now += 20000;
  monitor.tick();                          // 在途, 不并发报
  assert.equal(state.reports.length, 1);
  releaseHang();                           // 放行上一笔 (扣账要走微任务)
  await settle();
  adapters.report = async (bytes) => { state.reports.push(bytes); };
  await monitor.flush();                   // 手动补一笔把 50 报掉
  assert.deepEqual(state.reports, [600, 50]);
  assert.equal(monitor.pendingBytes(), 0);
});

test("字段回退: 无 transferSize 用 decodedBodySize, 都没有记 0", () => {
  const { adapters, state } = stubAdapters();
  const monitor = createCellularMonitor(adapters);
  state.entries.push(
    { responseEnd: 10, decodedBodySize: 250 },                     // 老浏览器
    { responseEnd: 20, transferSize: 0, decodedBodySize: 9999 },   // 缓存命中 = 0
    { responseEnd: 30 });                                          // 啥都没有
  monitor.tick();
  assert.equal(monitor.pendingBytes(), 250);
});

test("onHide 兜底: 页面要走时把攒着的报出去", async () => {
  const { adapters, state } = stubAdapters();
  const flushes = [];
  const monitor = createCellularMonitor({ ...adapters,
    onHide: (flush) => flushes.push(flush) });
  addEntry(state, 10, 120);      // 不够阈值也不到时限
  monitor.tick();
  assert.equal(flushes.length, 0);
  monitor.start();               // 注入 onHide
  assert.equal(flushes.length, 1);
  await flushes[0]();
  assert.deepEqual(state.reports, [120]);
});

test("start/stop: 定时器起一次, 停了不再 tick, 幂等", async () => {
  const { adapters, state } = stubAdapters();
  state.now = 1000;
  const monitor = createCellularMonitor({ ...adapters, pollMs: 5 });
  addEntry(state, 10, 90);
  monitor.start();               // 起手先收口一轮 (没到阈值/时限, 攒着)
  await new Promise((resolve) => setTimeout(resolve, 30));
  monitor.stop();
  assert.equal(state.reports.length, 0);
  state.now += 60000;
  monitor.tick();                // 停了也能手动驱动
  assert.deepEqual(state.reports, [90]);
  monitor.start();
  monitor.start();               // 重复 start 不叠加定时器
  monitor.stop();
  monitor.stop();
});

test("没有 onHide 也能 start (钩子可选)", async () => {
  const { adapters, state } = stubAdapters();
  const monitor = createCellularMonitor({ ...adapters, pollMs: 5 });
  monitor.start();
  await new Promise((resolve) => setTimeout(resolve, 15));
  monitor.stop();
  assert.equal(state.reports.length, 0);   // 没账没网络活动, 自然无事
});
