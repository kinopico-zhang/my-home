// cellular-usage.js — 蜂窝流量记账 (纯逻辑模块, 浏览器适配器注入)。
// 只有能认出蜂窝网络的浏览器 (安卓 Chrome 的 connection.type) 才记;
// iOS Safari 认不出网络类型, 记不上。每隔几秒收口一次资源表 (按
// responseEnd 水位去重), 是蜂窝就攒进账; 攒够一批 (够大或隔太久)
// 上报给后端按月入账, 上报失败的字节留到下一轮再报。
"use strict";

/**
 * 造一个监控器 (不直接碰 window/document, 浏览器行为全由适配器注入)。
 * @param {Object} adapters
 * @param {() => boolean} adapters.isCellular 现在走的是不是蜂窝网
 * @param {() => Array<{responseEnd: number, transferSize?: number,
 *   decodedBodySize?: number}>} adapters.takeEntries 资源表快照 (可重复给全量)
 * @param {(bytes: number) => Promise<void>} adapters.report 上报一批字节
 *   (失败要 reject, 字节会留账重报)
 * @param {() => number} adapters.now 当前毫秒时刻
 * @param {(flush: () => void) => void} [adapters.onHide] 页面要走了的钩子
 *   (浏览器注入 pagehide / 切后台, 做兜底上报)
 * @param {number} [adapters.pollMs] 收口间隔 (缺省 3 秒)
 * @param {number} [adapters.flushIntervalMs] 攒多久必须报一笔 (缺省 15 秒)
 * @param {number} [adapters.flushThresholdBytes] 攒够多少字节立刻报 (缺省 1 MB)
 */
function createCellularMonitor(adapters) {
  const pollMs = adapters.pollMs ?? 3000;
  const flushIntervalMs = adapters.flushIntervalMs ?? 15000;
  const flushThresholdBytes = adapters.flushThresholdBytes ?? 1024 * 1024;
  let watermark = 0;          // 收口到的 responseEnd 水位 (快照重复给也只记一次)
  let pendingBytes = 0;       // 攒着还没报出去的字节
  let lastFlushAt = 0;        // 上一笔报出去的时刻
  let reporting = false;      // 一笔在途就不并发报第二笔
  let timer = 0;

  /** 一条资源的网络字节: 优先 transferSize (含响应头; 缓存命中为 0),
      老浏览器没这个字段才退 decodedBodySize。 */
  function entryBytes(entry) {
    if (typeof entry.transferSize === "number") return entry.transferSize;
    return entry.decodedBodySize || 0;
  }

  /** 收口一轮: 新资源按当前网络归账, 到点/够量就上报。 */
  function tick() {
    let freshBytes = 0;
    for (const entry of adapters.takeEntries()) {
      if (entry.responseEnd > watermark) {
        freshBytes += entryBytes(entry);
        watermark = entry.responseEnd;   // responseEnd 是时刻戳, 只会往前
      }
    }
    if (freshBytes > 0 && adapters.isCellular()) pendingBytes += freshBytes;
    if (!reporting && pendingBytes > 0
        && (pendingBytes >= flushThresholdBytes
            || adapters.now() - lastFlushAt >= flushIntervalMs)) {
      flush();
    }
  }

  /** 把攒的字节报出去; 在途/没账就是空操作, 失败留账下轮再报。 */
  async function flush() {
    if (reporting || !pendingBytes) return;
    reporting = true;
    const amount = pendingBytes;
    try {
      await adapters.report(amount);
      pendingBytes -= amount;       // 上报期间又攒的不动 (没报丢也没重复报)
      lastFlushAt = adapters.now();
    } catch (_error) { /* 断网/接口挂: 字节留在账上 */ }
    reporting = false;
  }

  return {
    /** 起监控 (重复调用不叠加定时器)。 */
    start() {
      if (timer) return;
      lastFlushAt = adapters.now();
      timer = setInterval(tick, pollMs);
      unrefTimer(timer);
      if (adapters.onHide) adapters.onHide(flush);
      tick();
    },
    /** 停监控 (测试清理用; 浏览器页面卸载自然全停)。 */
    stop() {
      if (timer) clearInterval(timer);
      timer = 0;
    },
    tick,
    flush,
    /** 攒着未报的字节数 (测试/诊断用)。 */
    pendingBytes() {
      return pendingBytes;
    },
  };
}

/** Node 的定时器要 unref (测试进程别被拖住不退); 浏览器返回数字, 没这方法。 */
function unrefTimer(handle) {
  if (handle && typeof handle.unref === "function") handle.unref();
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { createCellularMonitor };
}
