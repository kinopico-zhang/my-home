// music-scan-status — My Music 曲库扫描状态: 30s 轮询/增量消化/扫描条。
// 拆自 music.js (结构化重构: 代码逐字节未动, 经典脚本按 music.html 里的顺序加载, 跨模块引用走全局)。
"use strict";
/* global $, fetchJSON, pageState, pushStack, renderRootView, resetLibraryLists, route,
          toast, userRescanPending: writable */
/* exported SCAN_POLL_INTERVAL_MS, checkScanStatus, stopScanPolling */

// ------------------------------------------------------------ 扫描状态
// 服务器每几分钟自动增量重扫一轮 (新专辑自动冒出来), 这里 30 秒问一次:
// 在扫 → 进度条; 收尾 → 动过库 (changed) 才静默刷新, 手动触发的才出提示。

const SCAN_POLL_INTERVAL_MS = 30000;

async function checkScanStatus() {
  try {
    const scan = (await fetchJSON("/music/api/status")).scan;
    if (scan.running) {
      pageState.sawScanRunning = true;
      showScanStrip(scan);
    } else {
      const watched = pageState.sawScanRunning;
      pageState.sawScanRunning = false;
      digestScanSettled(scan, watched);
    }
  } catch (_error) { /* 状态条失败不影响浏览 */ }
}

/** 一轮扫描收尾的消化: 同一轮不重复响应; 启动首见的旧结果只记账不惊动;
    动过库就静默重铺, 手动按过「重新扫描」的再补一句提示。 */
function digestScanSettled(scan, watched) {
  $("#scan-strip").hidden = true;
  const signature = `${scan.finished_at || 0}:${scan.changed ? 1 : 0}`;
  if (signature === pageState.lastScanSignature) return;
  const firstSighting = !pageState.lastScanSignature && !watched;
  pageState.lastScanSignature = signature;
  if (firstSighting) return;              // 上次关页前就扫完的旧结果
  const manual = userRescanPending;
  userRescanPending = false;
  if (!manual && !scan.changed) return;   // 后台自动扫, 什么都没变: 不打扰
  resetLibraryLists();
  route(true);                            // 曲目/专辑列表重铺 (当前页自动刷新)
  if (pushStack.length) renderRootView(pageState.rootView);   // 层底下的一级页也重铺
  if (manual) toast("曲库扫描完成");
}

function showScanStrip(scan) {
  const strip = $("#scan-strip");
  strip.hidden = false;
  const total = scan.files_total || 0;
  const done = scan.files_done || 0;
  $("#scan-text").textContent = scan.phase === "commit" ? "扫描结果入库中…"
    : `曲库扫描中 ${total ? `${done}/${total}` : ""}`;
  clearTimeout(pageState.scanPollTimer);
  pageState.scanPollTimer = setTimeout(async () => {
    try {
      const status = await fetchJSON("/music/api/status");
      if (status.scan.running) showScanStrip(status.scan);
      else digestScanSettled(status.scan, true);
    } catch (_error) { /* 下轮再问 */ }
  }, 2000);
}

function stopScanPolling() {
  clearTimeout(pageState.scanPollTimer);
}

