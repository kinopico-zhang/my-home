// music-library-views — My Music 资料库独立页 (1.8.0 拆段成页): 专辑/艺人页容器与分页挂载, 已下载管理页。
// 拆自 music.js (结构化重构), 原资料库页签分段 (segment) 撤掉,
// 专辑/艺人/已下载各自成推入层, 缓存仍按段名住 pageState.lists。
"use strict";
/* global $, appendListPage, bindDownloadsSelect, downloadAllCancelled: writable,
          downloadRingHTML, downloads, downloadsEnabled, escapeHTML, formatBytes,
          listPlaceholderHTML, loadListPage, navigate, pageState, playerStart, toast,
          syncDownloadsSelect */
/* exported downloadAllCancelled, playDownloadedRow, refreshDownloadsBody, renderAlbumsPane,
            renderArtistsPane, renderDownloadsBody, renderDownloadsPane,
            resetLibraryLists */

// ------------------------------------------------------------ 资料库独立页

function resetLibraryLists() {
  pageState.lists = {};
}

/** 专辑页: 大标题 + 网格 (缓存有货直接铺, 不够的分页链自己续)。 */
function renderAlbumsPane(target) {
  target.innerHTML = `
    <div class="pane-title">专辑</div>
    <div class="lib-body"></div>`;
  mountSegmentList(target.querySelector(".lib-body"), "albums");
}

/** 艺人页: 大标题 + 行列表 (与专辑页同一套分页链, 段名不同)。 */
function renderArtistsPane(target) {
  target.innerHTML = `
    <div class="pane-title">艺人</div>
    <div class="lib-body"></div>`;
  mountSegmentList(target.querySelector(".lib-body"), "artists");
}

/** 分页列表挂载: 缓存重铺从头渲染, 没缓存先占位再拉首页。 */
function mountSegmentList(body, segment) {
  bindLibraryBody(body);
  body.dataset.segment = segment;   // 段守卫的锚: 在途旧分页回来对不上就丢弃
  const list = pageState.lists[segment];
  if (list && list.items.length) {
    list.renderedCount = 0;         // 缓存重铺从头渲染 (旧值是上次铺到的位置)
    appendListPage(body, segment, list);
    return;
  }
  body.innerHTML = listPlaceholderHTML("加载中…");
  loadListPage(segment, body);
}

/** 已下载页: 下载管理 (统计行/逐首大小/删除与取消/一键清空/多选删除)。 */
function renderDownloadsPane(target) {
  target.innerHTML = `
    <div class="pane-title">已下载</div>
    <div class="lib-body" id="dl-pane-body"></div>`;
  const body = $("#dl-pane-body");
  bindLibraryBody(body);
  bindDownloadsSelect(target);   // 多选删除 (1.8.6): 绑 pane 层, 正文重铺不丢
  renderDownloadsBody(body);
}

/** 资料库页事件 (专辑/艺人跳转 + 已下载管理), 绑在各自的页容器上。 */
function bindLibraryBody(body) {
  body.addEventListener("click", (event) => {
    const albumCard = event.target.closest("[data-album-id]");
    if (albumCard) { navigate(`album/${albumCard.dataset.albumId}`); return; }
    const artistRow = event.target.closest("[data-artist-id]");
    if (artistRow) { navigate(`artist/${artistRow.dataset.artistId}`); return; }
    const clearButton = event.target.closest("#dl-clear-all");
    if (clearButton) {
      const count = downloads.entries().filter((entry) => !entry.state).length;
      if (window.confirm(`删除全部 ${count} 首已下载歌曲?`)) {
        downloadAllCancelled = true;   // 若有「下载全部」在跑, 整批叫停
        downloads.removeAll()
          .then(() => toast("已清空下载"))
          .catch((error) => toast(`清空失败: ${error.message}`));
      }
      return;
    }
    const removeButton = event.target.closest("[data-dl-remove]");
    if (removeButton) {
      const cancelling = removeButton.textContent.trim() === "取消";
      downloads.removeDownload(Number(removeButton.dataset.dlRemove))
        .then(() => toast(cancelling ? "已取消下载" : "已删除下载"))
        .catch((error) => toast(`删除失败: ${error.message}`));
      return;
    }
    const downloadRow = event.target.closest("[data-dl-row]");
    if (downloadRow) { playDownloadedRow(Number(downloadRow.dataset.dlRow)); }
  });
}

/** 已下载栏点行开播 (队列 = 已下载列表, 下载中的除外)。 */
function playDownloadedRow(trackId) {
  const tracks = downloads.entries().filter((entry) => !entry.state)
    .map((entry) => ({ ...entry, playable: true, lyrics_available: false,
                       file_format: "flac" }));
  const index = tracks.findIndex((track) => track.track_id === trackId);
  if (index >= 0) playerStart(tracks, index);
}

let downloadsRenderToken = 0;   // 重铺计数: 让在途的异步统计结果作废

/** "已下载"页 = 下载管理: 合计大小/每首大小/删除与取消/一键清空
 *  (明文 HTTP 下没有这一套, 说清楚)。 */
function renderDownloadsBody(body) {
  if (!downloadsEnabled) {
    body.innerHTML = listPlaceholderHTML(
      "离线下载需要 HTTPS 环境 (当前是明文 HTTP); 局域网在线听不受影响");
    return;
  }
  const entries = downloads.entries();
  if (!entries.length) {
    body.innerHTML = listPlaceholderHTML(
      "还没有下载的歌曲; 曲目行右侧的下载标就是下载");
    return;
  }
  body.innerHTML = `
    <div class="dl-stats">
      <span class="dl-stats-main">
        <strong id="dl-total">统计中…</strong>
        <small id="dl-quota"></small>
      </span>
      <button class="dl-clear" id="dl-select-delete" hidden>删除</button>
      <button class="dl-clear" id="dl-select-toggle">多选</button>
      <button class="dl-clear" id="dl-clear-all">全部删除</button>
    </div>
    ${entries.map(downloadRowHTML).join("")}`;
  syncDownloadsSelect(body);   // 选择模式开着时整页重铺: 圈/勾按 state 补
  if (!entries.some((entry) => entry.state)) fillDownloadsStats(body);
  // 有下载在跑: 等完成再量, 免得白量 (收批时 refreshDownloadsBody 补)
}

/** 单行模板 (整页重铺与原地补丁共用)。 */
function downloadRowHTML(entry) {
  return `
    <div class="dl-row${entry.state ? " busy" : ""}" data-dl-row="${entry.track_id}">
      ${entry.state
        ? '<span class="t-art">♪</span>'
        : `<img class="t-art" loading="lazy" decoding="async" alt=""
                src="/music/media/tracks/${entry.track_id}/artwork"
                onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'t-art',textContent:'♪'}))">`}
      <span class="t-main">
        <span class="t-title"><span class="t-title-text">${escapeHTML(entry.title || `曲目 ${entry.track_id}`)}</span></span>
        <small>${escapeHTML(entry.artist || "下载中…")}</small>
      </span>
      ${entry.state
        ? downloadRingHTML(entry.state.progress, 18)
        : `<span class="dl-state" data-dl-size="${entry.track_id}">…</span>`}
      <button class="dl-remove" data-dl-remove="${entry.track_id}"
              aria-label="${entry.state ? "取消下载" : "删除下载"}">${entry.state ? "取消" : "删除"}</button>
    </div>`;
}

/** 下载状态原地刷新 (1.8.5 修「下载中, 已下好行的封面闪」): 整页重铺会把
 *  所有行连同封面换成新 <img>, 解码间隙闪一下 —— 下载进度一秒触发好几
 *  次, 封面就一直闪。行集合没变 (同序同 id) 时只动该动的行: 进行中的换
 *  进度环, 刚下完的单行换新, 其余一根毫毛不碰。 */
function refreshDownloadsBody(body) {
  const entries = downloads.entries();
  const rows = body.querySelectorAll("[data-dl-row]");
  const sameSet = rows.length === entries.length && entries.every(
    (entry, index) => Number(rows[index].dataset.dlRow) === entry.track_id);
  if (!sameSet) { renderDownloadsBody(body); return; }   // 行集合变了才重铺
  entries.forEach((entry, index) => {
    const row = rows[index];
    if (row.classList.contains("busy") === Boolean(entry.state)) {
      if (entry.state) {
        const ring = row.querySelector(".dl-ring");
        if (ring) ring.outerHTML = downloadRingHTML(entry.state.progress, 18);
      }
    } else {
      row.outerHTML = downloadRowHTML(entry);   // 忙闲翻转 (下完/重下): 单行换新
    }
  });
  if (!entries.some((entry) => entry.state)) fillDownloadsStats(body);   // 收批补统计
}

/** 统计与每首大小 (异步, 在途期间又重铺过就作废)。 */
async function fillDownloadsStats(body) {
  const token = ++downloadsRenderToken;
  const usage = await downloads.storageUsage();
  if (token !== downloadsRenderToken) return;         // 期间又重铺了, 结果作废
  const total = body.querySelector("#dl-total");
  if (total) {
    total.textContent = `${usage.entries.length} 首 · ${formatBytes(usage.totalBytes)}`;
  }
  for (const row of usage.entries) {
    const size = body.querySelector(`[data-dl-size="${row.track_id}"]`);
    if (size) size.textContent = formatBytes(row.bytes);
  }
  if (navigator.storage && navigator.storage.estimate) {
    navigator.storage.estimate().then((estimate) => {
      if (token !== downloadsRenderToken) return;
      const quota = body.querySelector("#dl-quota");
      if (quota && estimate && estimate.quota) {
        quota.textContent = `占手机存储 ${formatBytes(estimate.usage || 0)}`;
      }
    }).catch(() => {});
  }
}
