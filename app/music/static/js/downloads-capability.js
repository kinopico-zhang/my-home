// downloads-capability.js — 离线下载能力探测与字节数格式化 (纯逻辑, node --test 直测)。
// 拆自 downloads.js (结构化重构); 下载状态机本体在 downloads.js。
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

if (typeof module !== "undefined" && module.exports) {
  module.exports = { downloadsSupported, formatBytes };
}
