// music-dock-menu — My Music 底部菜单键: 上弹菜单 (播放列表/专辑/艺人/已下载/设置) 的开关与导航。
// 1.8.0 页签栏撤掉, 原页签的导航职能收进这枚菜单 (用户点名「点击菜单按钮,
// 纵向向上弹出菜单」)。
"use strict";
/* global $, navigate */
/* exported bindDockMenu, closeDockMenu */

// ------------------------------------------------------------ 上弹菜单

function bindDockMenu() {
  $("#dock-menu").addEventListener("click", () => {
    const menu = $("#pop-menu");
    const opening = menu.hidden;
    menu.hidden = !opening;
    $("#pop-mask").hidden = !opening;
  });
  // 点背景收起 (遮罩盖全屏, 也是菜单外任何位置的兜底)
  $("#pop-mask").addEventListener("click", closeDockMenu);
  $("#pop-menu").addEventListener("click", (event) => {
    const button = event.target.closest("[data-pop-nav]");
    if (!button) return;
    closeDockMenu();     // 先收菜单再导航: 层滑入时菜单不在场
    navigate(button.dataset.popNav);
  });
}

/** 收起上弹菜单 (选完条目 / 点背景 / Esc 都走这里)。 */
function closeDockMenu() {
  $("#pop-menu").hidden = true;
  $("#pop-mask").hidden = true;
}
