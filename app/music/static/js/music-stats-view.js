// music-stats-view — My Music 统计视图 (听歌数据)。
// 拆自 music.js (结构化重构: 代码逐字节未动, 经典脚本按 music.html 里的顺序加载, 跨模块引用走全局)。
"use strict";
/* global $, describeDuration, escapeHTML, fetchJSON */
/* exported renderStatsView */

// ------------------------------------------------------------ 统计页

async function renderStatsView() {
  $("#root-view").innerHTML = '<div id="stats-body">'
    + '<p class="stat-empty">正在统计…</p></div>';
  const body = $("#stats-body");
  let stats;
  try {
    stats = await fetchJSON("/music/api/stats");
  } catch (error) {
    body.innerHTML = `<p class="stat-empty">统计拿不到: ${escapeHTML(error.message)}</p>`;
    return;
  }
  const [durationValue, durationUnit] =
    describeDuration(stats.total_duration_seconds).split(" ");
  body.innerHTML = `
    <div class="stat-grid">
      <div class="stat-card"><b>${stats.artist_count}</b><small>艺人</small></div>
      <div class="stat-card"><b>${stats.album_count}</b><small>专辑</small></div>
      <div class="stat-card"><b>${stats.track_count}</b><small>曲目</small></div>
      <div class="stat-card"><b>${durationValue}<small>${durationUnit}</small></b><small>总时长</small></div>
    </div>
    <h3 class="stats-title">各格式曲目数</h3>
    ${stats.formats.length
      ? stats.formats.map((row) => formatRowHTML(row, stats.track_count)).join("")
      : '<p class="stat-empty">曲库还是空的, 扫描完成后这里就有数了</p>'}`;
}

/** 格式分布行: 名字 + 比例条 + 数量; 浏览器播不了的置灰注明。 */
function formatRowHTML(row, totalCount) {
  const percent = totalCount ? Math.round(row.count / totalCount * 100) : 0;
  return `
    <div class="format-row${row.playable ? "" : " disabled"}">
      <span class="format-name">${escapeHTML(row.format)}${row.playable
        ? "" : "<i> 播不了</i>"}</span>
      <span class="format-bar"><i style="width:${Math.max(percent, 2)}%"></i></span>
      <span class="format-count">${row.count}</span>
    </div>`;
}

