/* downloads 测试共享助手: 模块加载 + 桩适配器 (索引内存版, 下载体
   可编排进度, 缓存记录调用)。拆自 downloads.test.mjs (结构化重构,
   代码逐字节未动, 仅把声明改成 export)。 */
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const dir = path.join(path.dirname(fileURLToPath(import.meta.url)), "../../app/music/static/js");
const { createDownloads } = require(path.join(dir, "downloads.js"));
const { downloadsSupported, formatBytes } =
  require(path.join(dir, "downloads-capability.js"));

const TRACK = { track_id: 7, title: "曲A", artist: "AI机组", album_id: 3,
                album_title: "甲", duration_seconds: 200, playable: true };

/** 桩适配器: 索引在内存里, 下载体可编排进度, 缓存记录调用。 */
function stubAdapters({ bodyChunks = [new Uint8Array(10)], failAt = null,
                        sizes = {} } = {}) {
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
      async cacheSize(url) { return sizes[url] || 0; },
      now: () => 1000,
    },
    calls,
  };
}

/** 把桩的下载体换成 "一直挂住等信号" 的版本 (测取消; 不主动完成)。 */
function hangOnSignal(adapters) {
  adapters.downloadBody = (url, onProgress, signal) => new Promise((resolve, reject) => {
    const onAbort = () => {
      const error = new Error("aborted");
      error.name = "AbortError";
      reject(error);
    };
    if (signal.aborted) return onAbort();
    signal.addEventListener("abort", onAbort);
  });
}

export { createDownloads, downloadsSupported, formatBytes,
         TRACK, stubAdapters, hangOnSignal };
