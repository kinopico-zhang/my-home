// music-global-events — My Music 全局事件绑定 (船坞键/封面文件/Esc) + 蜂窝流量浏览器适配器。
// 拆自 music.js (结构化重构), 1.8.0 页签栏撤掉: 搜索键/菜单键在这里接线。
"use strict";
/* global $, SCAN_POLL_INTERVAL_MS, bindDockMenu, checkScanStatus, closeDockMenu,
          closeFullPlayer, closePushStack, coverUploadPlaylistId, createCellularMonitor,
          navigate, playerOpen, pushStack, uploadPlaylistCover */
/* exported bindGlobalEvents */

// ------------------------------------------------------------ 启动

function bindGlobalEvents() {
  // 底部船坞: 搜索键进搜索层 (顺手聚焦输入框 —— 老放大镜按钮的手感;
  // 导航是同步渲染, 走到这儿输入框已经在页面上了); 菜单键的上弹菜单自成一模块
  $("#dock-search").addEventListener("click", () => {
    navigate("search");
    const input = $("#search-input");
    if (input) input.focus();
  });
  bindDockMenu();
  $("#cover-file").addEventListener("change", () => {
    if (coverUploadPlaylistId) uploadPlaylistCover(coverUploadPlaylistId);
  });
  // 后台自动增量重扫的探针: 页面可见时每 30 秒问一次状态
  setInterval(() => {
    if (!document.hidden) checkScanStatus();
  }, SCAN_POLL_INTERVAL_MS);
  // 电脑上的"返回": Esc 依序收上弹菜单 → 播放页 → 顶层二级页 (手机上有右划,
  // 电脑总不能指望鼠标拖页面; 浏览器返回键在应用里已没有可退的条目)
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || event.repeat) return;
    if (!$("#pop-menu").hidden) closeDockMenu();
    else if (playerOpen) closeFullPlayer();
    else if (pushStack.length) closePushStack(pushStack.length - 1);
  });
  // 键盘避让 (1.8.3 搜索栏钉页底): iOS 键盘只盖不缩布局, visualViewport
  // 量出键盘高写进 --kb-h (CSS 把搜索栏抬到键盘上沿); 没有输入框在焦点上
  // 时归零 —— 捏拉缩放同样会缩 visualViewport, 别误抬。安卓
  // interactive-widget=resizes-content 布局自己缩, 量出来是 0, 两不误伤。
  if (window.visualViewport) {
    const lift = () => {
      const active = document.activeElement;
      const keyboard = active && active.tagName === "INPUT"
        ? Math.max(0, window.innerHeight - visualViewport.height
                   - visualViewport.offsetTop)
        : 0;
      document.documentElement.style.setProperty("--kb-h", `${keyboard}px`);
    };
    visualViewport.addEventListener("resize", lift);
    visualViewport.addEventListener("scroll", lift);
  }
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

