// downloads.js — 离线下载纯逻辑: 状态机 (下载中/已下载) + 索引合并 + 删除/取消
// + 缓存大小统计。网络/Cache API/localStorage 都是适配器注入 (node --test 直测 + tsc +
// c8 覆盖), 浏览器接线在 music.js; Service Worker (sw.js) 负责离线回源。

/**
 * 一条下载索引 (localStorage "music-downloads"): 曲目展示信息 + 下载时刻。
 * @typedef {Object} DownloadEntry
 * @property {number} track_id
 * @property {string} title
 * @property {string} artist
 * @property {number} album_id
 * @property {string} album_title
 * @property {number} duration_seconds
 * @property {number} downloaded_at    epoch 秒
 */

/**
 * 适配器 (浏览器实现在 music.js, 测试用桩)。
 * @typedef {Object} DownloadAdapters
 * @property {Function} readIndex     () => Array<DownloadEntry>
 * @property {Function} writeIndex    (entries: Array<DownloadEntry>) => void
 * @property {Function} downloadBody  (url, onProgress, signal) => Promise<{body, contentType}>
 *                                    onProgress(0..1); signal 中断时以异常退出;
 *                                    body 直接交给 cachePut
 * @property {Function} cachePut      (url, body, contentType) => Promise
 * @property {Function} cacheDelete   (url) => Promise
 * @property {Function} cacheSize     (url) => Promise<number>  这首在缓存里的字节数, 没有则 0
 * @property {Function} now           () => number   epoch 秒 (测试可注入)
 */

/**
 * 下载管理器。
 * @typedef {Object} DownloadsManager
 * @property {Function} isDownloaded    (trackId: number) => boolean
 * @property {Function} stateOf         (trackId: number) => {status: string, progress: number}|null
 * @property {Function} entries         () => Array<DownloadEntry & {state}>   下载时刻倒序
 * @property {Function} downloadTrack   (track: Object) => Promise<boolean>    已在库/已在下/被取消返回 false
 * @property {Function} removeDownload  (trackId: number) => Promise           下载中的 = 取消
 * @property {Function} removeAll       () => Promise                          全删 (含取消下载中的)
 * @property {Function} storageUsage    () => Promise<{entries: Array<DownloadEntry & {bytes}>,
 *                                                     totalBytes: number}>
 * @property {Function} onChange        (listener: Function) => void
 */

/**
 * 离线下载要不要亮出来: 需要安全上下文 (HTTPS 或 localhost) ——
 * Cache API 和 Service Worker 在明文 HTTP 下浏览器根本不给。
 * @param {Object} environment {secureContext, cacheApi, serviceWorkerApi}
 * @returns {boolean}
 */
function downloadsSupported(environment) {
  return Boolean(environment.secureContext && environment.cacheApi
                 && environment.serviceWorkerApi);
}

/**
 * 字节数 → 人话 ("38.2 MB"): B 恒整数, KB 以上百内一位小数、以上取整。
 * 下载管理页的合计/单行大小和测试共用。
 * @param {number} bytes
 * @returns {string}
 */
function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  if (unit === 0) return `${Math.round(value)} B`;
  return `${value >= 100 ? Math.round(value) : value.toFixed(1)} ${units[unit]}`;
}

/**
 * 建下载管理器 (状态在实例里; 同一页面只建一个)。
 * @param {DownloadAdapters} adapters
 * @returns {DownloadsManager}
 */
function createDownloads(adapters) {
  /** @type {Map<number, {status: string, progress: number}>} 下载中的瞬态 */
  const states = new Map();
  /** @type {Map<number, AbortController>} 下载中的中断器 (删除下载中的歌 = 取消) */
  const aborts = new Map();
  /** @type {Array<Function>} */
  const listeners = [];
  const notify = () => { for (const listener of listeners) listener(); };

  const streamURL = (trackId) => `/music/media/stream/${trackId}`;

  /** 索引读出来先洗一遍 (坏行丢弃), 顺手按下载时刻倒序。 */
  function indexEntries() {
    const entries = adapters.readIndex();
    return (Array.isArray(entries) ? entries : [])
      .filter((entry) => entry && Number.isFinite(entry.track_id))
      .sort((left, right) => (right.downloaded_at || 0) - (left.downloaded_at || 0));
  }

  function writeIndex(next) {
    adapters.writeIndex(next);
  }

  function isDownloaded(trackId) {
    return indexEntries().some((entry) => entry.track_id === trackId);
  }

  function stateOf(trackId) {
    return states.get(trackId) || null;
  }

  /** "已下载"一栏的数据: 下载中的排最上 (正发生), 完成的按时刻倒序。 */
  function entries() {
    const completed = indexEntries().map(
      (entry) => ({ ...entry, state: states.get(entry.track_id) || null }));
    const inflight = [];
    for (const [trackId, state] of states) {
      if (!completed.some((entry) => entry.track_id === trackId)) {
        inflight.push({ track_id: trackId, title: "", artist: "", album_id: 0,
                        album_title: "", duration_seconds: 0,
                        downloaded_at: 0, state });
      }
    }
    return [...inflight, ...completed];
  }

  /** 下载一首: 整曲字节进 Cache API (键 = 音频流地址, SW 离线时按它回源)。 */
  async function downloadTrack(track) {
    const trackId = track && track.track_id;
    if (!Number.isFinite(trackId)) return false;
    if (states.has(trackId) || isDownloaded(trackId)) return false;
    const controller = new AbortController();
    states.set(trackId, { status: "downloading", progress: 0 });
    aborts.set(trackId, controller);
    notify();
    try {
      const { body, contentType } = await adapters.downloadBody(
        streamURL(trackId), (progress) => {
          const state = states.get(trackId);
          if (state) {
            state.progress = Math.min(1, Math.max(0, progress));
            notify();
          }
        }, controller.signal);
      await adapters.cachePut(streamURL(trackId), body, contentType);
      writeIndex(indexEntries().filter((entry) => entry.track_id !== trackId)
        .concat({
          track_id: trackId,
          title: track.title || "",
          artist: track.artist || "",
          album_id: track.album_id || 0,
          album_title: track.album_title || "",
          duration_seconds: track.duration_seconds || 0,
          downloaded_at: adapters.now(),
        }));
      states.delete(trackId);
      aborts.delete(trackId);
      notify();
      return true;
    } catch (error) {
      states.delete(trackId);      // 失败/取消都不占位, 图标弹回未下载
      aborts.delete(trackId);
      notify();
      if (controller.signal.aborted) return false;   // 用户删了正在下的: 不算失败
      throw error;
    }
  }

  async function removeDownload(trackId) {
    const controller = aborts.get(trackId);
    if (controller) controller.abort();   // 下载中的: 掐断, 状态由 downloadTrack 收
    await adapters.cacheDelete(streamURL(trackId));
    writeIndex(indexEntries().filter((entry) => entry.track_id !== trackId));
    notify();
  }

  /** 全删: 已完成的逐首清缓存, 下载中的一并取消。 */
  async function removeAll() {
    for (const controller of aborts.values()) controller.abort();
    for (const entry of indexEntries()) {
      await adapters.cacheDelete(streamURL(entry.track_id));
    }
    writeIndex([]);
    notify();
  }

  /** 缓存用量: 每首量字节 (缓存里丢了的按 0), 给管理页显示合计和单行大小。 */
  async function storageUsage() {
    const rows = [];
    let totalBytes = 0;
    for (const entry of indexEntries()) {
      const bytes = await adapters.cacheSize(streamURL(entry.track_id));
      rows.push({ ...entry, bytes });
      totalBytes += bytes;
    }
    return { entries: rows, totalBytes };
  }

  function onChange(listener) {
    listeners.push(listener);
  }

  return { isDownloaded, stateOf, entries, downloadTrack, removeDownload,
           removeAll, storageUsage, onChange };
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { downloadsSupported, createDownloads, formatBytes };
}
