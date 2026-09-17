// music-downloads-select — My Music 已下载页多选删除 (1.8.6, 用户点名):
// 「多选」进选择模式: 行左缘出选择圈, 点行改勾选 (capture 阶段截下, 不再
// 开播); 统计条换出「删除 N 首」; 「完成」退出, 删完自动退出。
// 事件绑在已下载页的 pane 层 (正文重铺不丢), 模式/勾选住本模块 ——
// 正文整页重铺后由 syncDownloadsSelect 按 state 补勾 (music-library-views 调)。
"use strict";
/* global downloads, toast */
/* exported bindDownloadsSelect, syncDownloadsSelect */

let dlSelecting = false;         // 选择模式开关 (开页复位)
const dlSelected = new Set();    // 勾中的曲目号 (下载中的不参与)

/** 挂到已下载页容器 (renderDownloadsPane 每次开页调一次: pane 是新 DOM,
    不会重复绑; 顺手把上一场的选择模式复位)。 */
function bindDownloadsSelect(target) {
  dlSelecting = false;
  dlSelected.clear();
  // capture 阶段截下点行: 选择模式里点行 = 勾选, 不走开播那条路
  target.addEventListener("click", (event) => {
    if (!dlSelecting) return;
    const row = event.target.closest("[data-dl-row]");
    if (!row) return;                        // 选择圈外 (删除/完成钮等): 放行
    event.stopPropagation();
    if (row.classList.contains("busy")) return;   // 下载中的不参与多选
    const trackId = Number(row.dataset.dlRow);
    if (dlSelected.has(trackId)) {
      dlSelected.delete(trackId);
      row.classList.remove("sel");
    } else {
      dlSelected.add(trackId);
      row.classList.add("sel");
    }
    syncDownloadsSelect(row.closest("#dl-pane-body"));
  }, true);
  target.addEventListener("click", (event) => {
    const toggle = event.target.closest("#dl-select-toggle");
    const remove = event.target.closest("#dl-select-delete");
    if (toggle) {
      dlSelecting = !dlSelecting;
      if (!dlSelecting) dlSelected.clear();  // 完成退出: 勾选不留到下一场
    } else if (remove) {
      deleteSelected(target);
      return;
    } else {
      return;
    }
    syncDownloadsSelect(target.querySelector("#dl-pane-body"));
  });
}

/** 删掉勾中的 (一首删完再删下一首); 删完退出选择模式。 */
async function deleteSelected(target) {
  if (!dlSelected.size) return;
  if (!window.confirm(`删除选中的 ${dlSelected.size} 首?`)) return;
  let failed = 0;
  for (const trackId of dlSelected) {
    try {
      await downloads.removeDownload(trackId);   // 每删一首触发一次重铺
    } catch (_error) {
      failed += 1;                               // 单首失败不断批
    }
  }
  dlSelecting = false;
  dlSelected.clear();
  if (failed) toast(`有 ${failed} 首没删掉, 再试一次`);
  syncDownloadsSelect(target.querySelector("#dl-pane-body"));
}

/** 把选择模式刷到正文 (开页/整页重铺后调): 圈/勾/按钮文案对齐 state。 */
function syncDownloadsSelect(body) {
  if (!body) return;
  body.classList.toggle("selecting", dlSelecting);
  const toggle = body.querySelector("#dl-select-toggle");
  if (toggle) toggle.textContent = dlSelecting ? "完成" : "多选";
  const remove = body.querySelector("#dl-select-delete");
  if (remove) {
    remove.hidden = !dlSelecting;
    remove.textContent = dlSelected.size ? `删除 ${dlSelected.size} 首` : "删除";
    remove.disabled = !dlSelected.size;
  }
  for (const row of body.querySelectorAll("[data-dl-row]")) {
    row.classList.toggle("sel", dlSelected.has(Number(row.dataset.dlRow)));
  }
}
