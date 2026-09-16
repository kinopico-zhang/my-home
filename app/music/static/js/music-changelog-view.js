// music-changelog-view — My Music 更新日志视图 (应用内, 听歌不中断)。
// 拆自 music.js (结构化重构: 代码逐字节未动, 经典脚本按 music.html 里的顺序加载, 跨模块引用走全局)。
"use strict";
/* global $, escapeHTML, fetchJSON */
/* exported renderChangelogView */

// ------------------------------------------------------------ 更新日志
// 应用内视图 (原来是整页跳转 /music/changelog, 会卸载音频断歌):
// 拉同一个条目接口铺在 #main, 播放气泡常驻, 听歌不断。
const CHANGELOG_KIND_CLS = { "新增": "add", "改进": "imp", "修复": "fix" };

async function renderChangelogView() {
  $("#root-view").innerHTML = '<div class="list-empty">正在读取版本历史…</div>';
  let versions = null;
  try {
    versions = await fetchJSON("/music/changelog/api/entries");
  } catch (error) {
    $("#root-view").innerHTML = `<div class="list-empty">加载失败: ${escapeHTML(error.message)}</div>`;
    return;
  }
  if (!versions.length) {
    $("#root-view").innerHTML = '<div class="list-empty">还没有版本记录</div>';
    return;
  }
  $("#root-view").innerHTML = `
    <div id="changelog-entries">
      ${versions.map((version) => `
        <div class="ver">
          <div class="v-head">
            <span class="v-badge">${escapeHTML(version.version)}</span>
            <span class="v-date">${escapeHTML(version.date)}</span>
          </div>
          <ul class="v-items">${version.items.map((item) => `
            <li><span class="k k-${CHANGELOG_KIND_CLS[item.kind] || "imp"}">${escapeHTML(item.kind)}</span>
                <span class="t">${escapeHTML(item.text)}</span></li>`).join("")}
          </ul>
        </div>`).join("")}
    </div>`;
}

