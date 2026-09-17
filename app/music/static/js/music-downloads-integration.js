// music-downloads-integration — My Music 离线下载接线: 能力探测/浏览器适配器/下载实例, 行内下载标, 全部下载。
// 拆自 music.js (结构化重构: 代码逐字节未动, 经典脚本按 music.html 里的顺序加载, 跨模块引用走全局)。
"use strict";
/* global $, ICON_DOWNLOAD, createDownloads, currentRoute, downloadsSupported,
          refreshDownloadsBody, toast */
/* exported downloadAllCancelled, downloadAllFromUI, downloadMarkHTML, downloadRingHTML,
            downloadTrackFromUI, downloads, downloadsEnabled, syncDownloadIcons */

// ------------------------------------------------------------ 下载 (离线)

// 离线下载要安全上下文 (HTTPS/localhost): Cache API 和 SW 在明文 HTTP
// 下浏览器不给 —— 明文环境整个功能收起来, 只留说明
const downloadsEnabled = downloadsSupported({
  secureContext: window.isSecureContext,
  cacheApi: typeof caches !== "undefined",
  serviceWorkerApi: "serviceWorker" in navigator,
});

const DOWNLOAD_CACHE = "music-downloads-v1";
const DOWNLOAD_INDEX_KEY = "music-downloads";

function browserDownloadAdapters() {
  return {
    readIndex() {
      try {
        return JSON.parse(localStorage.getItem(DOWNLOAD_INDEX_KEY) || "[]");
      } catch (_error) { return []; }
    },
    writeIndex(entries) {
      try {
        localStorage.setItem(DOWNLOAD_INDEX_KEY, JSON.stringify(entries));
      } catch (_error) { /* 存满了: 已下的字节还在缓存里, 只是列表丢了 */ }
    },
    async downloadBody(url, onProgress, signal) {
      const response = await fetch(url, { signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const contentType = response.headers.get("Content-Type")
        || "application/octet-stream";
      if (!response.body || !response.body.getReader) {
        return { body: await response.blob(), contentType };
      }
      const total = Number(response.headers.get("Content-Length")) || 0;
      const reader = response.body.getReader();
      const parts = [];
      let received = 0;
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        parts.push(value);
        received += value.byteLength;
        if (total) onProgress(received / total);
      }
      return { body: new Blob(parts), contentType };
    },
    async cachePut(url, body, contentType) {
      const cache = await caches.open(DOWNLOAD_CACHE);
      await cache.put(url, new Response(body, {
        headers: { "Content-Type": contentType },
      }));
    },
    async cacheDelete(url) {
      const cache = await caches.open(DOWNLOAD_CACHE);
      await cache.delete(url);
    },
    async cacheSize(url) {
      const cache = await caches.open(DOWNLOAD_CACHE);
      const response = await cache.match(url);
      return response ? (await response.blob()).size : 0;
    },
    now() { return Date.now() / 1000; },
  };
}

const downloads = downloadsEnabled
  ? createDownloads(browserDownloadAdapters()) : null;

if (downloadsEnabled) {
  navigator.serviceWorker.register("/music/sw.js").catch(() => {
    /* SW 注册失败: 在线照常, 只是离线放不了 */
  });
  downloads.onChange(syncDownloadIcons);
}

/** 下载中的进度环 (1.8.2 用户点名: 圆圈替掉百分比文字): 淡底圈 +
    进度弧从正上方顺时针画。 */
function downloadRingHTML(progress, size) {
  const CIRCLE = 2 * Math.PI * 8.5;   // r=8.5 的周长
  const offset = CIRCLE * (1 - Math.min(1, Math.max(0, progress)));
  return `<svg class="dl-ring" viewBox="0 0 24 24" width="${size}" height="${size}" aria-hidden="true">`
    + '<circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor"'
    + ' stroke-width="2.2" opacity=".3"/>'
    + `<circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor"`
    + ' stroke-width="2.2" stroke-linecap="round"'
    + ` stroke-dasharray="${CIRCLE.toFixed(2)}"`
    + ` stroke-dashoffset="${offset.toFixed(2)}" transform="rotate(-90 12 12)"/></svg>`;
}

/** 曲目行的下载图标状态 (明文 HTTP 下整列不渲染)。 */
function downloadMarkHTML(trackId) {
  if (!downloads) return "";
  if (downloads.isDownloaded(trackId)) {
    return '<svg viewBox="0 0 24 24" width="17" height="17" aria-hidden="true"><path d="M5 12.5 10 17.5 19 7" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  }
  const state = downloads.stateOf(trackId);
  if (state) {
    return downloadRingHTML(state.progress, 17);
  }
  return ICON_DOWNLOAD;
}

/** 下载状态变了 → 全站行图标刷新 (含已下载页里的进度)。 */
function syncDownloadIcons() {
  if (!downloads) return;
  for (const mark of document.querySelectorAll("[data-download-track]")) {
    mark.innerHTML = downloadMarkHTML(Number(mark.dataset.downloadTrack));
    mark.classList.toggle("done",
      downloads.isDownloaded(Number(mark.dataset.downloadTrack)));
  }
  if (currentRoute().view === "downloads") {
    const body = $("#dl-pane-body");
    // 1.8.5 原地刷: 整页重铺会让已下好行的封面连着闪 (用户报的 bug)
    if (body) refreshDownloadsBody(body);
  }
}

async function downloadTrackFromUI(track) {
  if (!downloads) return;
  try {
    await downloads.downloadTrack(track);
    toast(`已下载: ${track.title}`);
    if (navigator.storage && navigator.storage.persist) {
      navigator.storage.persist().catch(() => {});   // 别让系统清缓存
    }
  } catch (error) {
    toast(`下载失败: ${error.message}`);
  }
}

let downloadAllCancelled = false;   // 下载管理「全部删除」置位, 整批叫停

/** 「下载全部」: 一首下完再下下一首 (几十个 40MB 并发请求在手机上必炸),
    已在库/正在下的跳过; 单首失败不断批, 收尾一并报数。 */
async function downloadAllFromUI(tracks) {
  if (!downloads) return;
  const pending = tracks.filter((track) => track.playable
    && !downloads.isDownloaded(track.track_id)
    && !downloads.stateOf(track.track_id));
  if (!pending.length) {
    toast("都已经在下载里了");
    return;
  }
  downloadAllCancelled = false;
  let done = 0;
  let failed = 0;
  for (const track of pending) {
    if (downloadAllCancelled) return;   // 下载管理里点了全部删除
    try {
      if (await downloads.downloadTrack(track)) done += 1;
    } catch (error) {
      failed += 1;
    }
  }
  toast(failed ? `下载完成 ${done} 首, 失败 ${failed} 首` : `已下载 ${done} 首`);
  if (done && navigator.storage && navigator.storage.persist) {
    navigator.storage.persist().catch(() => {});   // 别让系统清缓存
  }
}

