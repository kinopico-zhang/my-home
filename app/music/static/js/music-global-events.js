// music-global-events — My Music 全局事件绑定 (页签栏/封面文件/Esc) + 蜂窝流量浏览器适配器。
// 拆自 music.js (结构化重构: 代码逐字节未动, 经典脚本按 music.html 里的顺序加载, 跨模块引用走全局)。
"use strict";
/* global $, SCAN_POLL_INTERVAL_MS, checkScanStatus, closeFullPlayer, closePushStack,
          coverUploadPlaylistId, createCellularMonitor, navigate, playerOpen, pushStack,
          uploadPlaylistCover */
/* exported bindGlobalEvents */

// ------------------------------------------------------------ 启动

function bindGlobalEvents() {
  // 底部页签栏: 主页/资料库/搜索/设置 (设置 = 原品牌菜单的职能进设置页)
  $("#tabbar").addEventListener("click", (event) => {
    const button = event.target.closest("[data-view-tab]");
    if (!button) return;
    navigate(button.dataset.viewTab);
    if (button.dataset.viewTab !== "search") return;
    // 进搜索页签顺手聚焦输入框 (老放大镜按钮的手感); 导航是同步渲染,
    // 走到这儿输入框已经在页面上了
    const input = $("#search-input");
    if (input) input.focus();
  });
  $("#cover-file").addEventListener("change", () => {
    if (coverUploadPlaylistId) uploadPlaylistCover(coverUploadPlaylistId);
  });
  // 后台自动增量重扫的探针: 页面可见时每 30 秒问一次状态
  setInterval(() => {
    if (!document.hidden) checkScanStatus();
  }, SCAN_POLL_INTERVAL_MS);
  // 电脑上的"返回": Esc 收播放页, 没开播放页就收顶层二级页 (手机上有右划,
  // 电脑总不能指望鼠标拖页面; 浏览器返回键在应用里已没有可退的条目)
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || event.repeat) return;
    if (playerOpen) closeFullPlayer();
    else if (pushStack.length) closePushStack(pushStack.length - 1);
  });
}

// ------------------------------------------------------------ 蜂窝流量
// 只有能认出蜂窝网络的浏览器 (安卓 Chrome 的 navigator.connection) 才上报,
// iPhone 的 Safari 认不出网络类型, 记不上 (设置页有说明)。收口/上报的
// 节奏在 cellular-usage.js, 这里只给浏览器适配器。
if (window.performance && performance.getEntriesByType
    && typeof createCellularMonitor === "function") {
  createCellularMonitor({
    isCellular: () => {
      const connection = navigator.connection
        || navigator.mozConnection || navigator.webkitConnection;
      return !!connection && connection.type === "cellular";
    },
    takeEntries: () => performance.getEntriesByType("resource"),
    report: async (bytes) => {
      const response = await fetch("/music/api/cellular-usage", {
        method: "POST", keepalive: true,      // 离开页面那一笔也要送到
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bytes }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
    },
    onHide: (flush) => {
      window.addEventListener("pagehide", flush);
      document.addEventListener("visibilitychange", () => {
        if (document.hidden) flush();     // 切后台就报, 别等系统杀页
      });
    },
    now: () => Date.now(),
  }).start();
}

