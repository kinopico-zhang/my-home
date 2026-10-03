// no-zoom — 全应用禁缩放的最后一道 (1.7.0): iOS Safari 的两指捏合走
// 非标准 gesture 事件, 不吃 css 的 touch-action, 只能拦事件本身
// (my-tesla 同款); 双击放大/点输入框的自动放大由各页 viewport meta 的
// maximum-scale=1 掐。所有页面 body 后第一条装载, 在业务脚本之前。
"use strict";
for (const ev of ["gesturestart", "gesturechange"]) {
  document.addEventListener(ev, (e) => e.preventDefault());
}
