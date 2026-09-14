// downloads.js — 离线下载纯逻辑: 状态机 (下载中/已下载) + 索引合并 + 删除。
// 网络/Cache API/localStorage 都是适配器注入 (node --test 直测 + tsc +
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
 * @property {Function} downloadBody  (url, onProgress) => Promise<{body, contentType}>
 *                                    onProgress(0..1); body 直接交给 cachePut
 * @property {Function} cachePut      (url, body, contentType) => Promise
 * @property {Function} cacheDelete   (url) => Promise
 * @property {Function} now           () => number   epoch 秒 (测试可注入)
 */

/**
 * 下载管理器。
 * @typedef {Object} DownloadsManager
 * @property {Function} isDownloaded    (trackId: number) => boolean
 * @property {Function} stateOf         (trackId: number) => {status: string, progress: number}|null
 * @property {Function} entries         () => Array<DownloadEntry & {state}>   下载时刻倒序
 * @property {Function} downloadTrack   (track: Object) => Promise<boolean>    已在库/已在下返回 false
 * @property {Function} removeDownload  (trackId: number) => Promise
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
 * 建下载管理器 (状态在实例里; 同一页面只建一个)。
 * @param {DownloadAdapters} adapters
 * @returns {DownloadsManager}
 */
function createDownloads(adapters) {
  /** @type {Map<number, {status: string, progress: number}>} 下载中的瞬态 */
  const states = new Map();
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
    states.set(trackId, { status: "downloading", progress: 0 });
    notify();
    try {
      const { body, contentType } = await adapters.downloadBody(
        streamURL(trackId), (progress) => {
          const state = states.get(trackId);
          if (state) {
            state.progress = Math.min(1, Math.max(0, progress));
            notify();
          }
        });
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
      notify();
      return true;
    } catch (error) {
      states.delete(trackId);      // 失败不占位, 图标弹回未下载
      notify();
      throw error;
    }
  }

  async function removeDownload(trackId) {
    await adapters.cacheDelete(streamURL(trackId));
    writeIndex(indexEntries().filter((entry) => entry.track_id !== trackId));
    notify();
  }

  function onChange(listener) {
    listeners.push(listener);
  }

  return { isDownloaded, stateOf, entries, downloadTrack, removeDownload,
           onChange };
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { downloadsSupported, createDownloads };
}
