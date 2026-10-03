// back-swipe — 全局右划返回 (1.7.1): iOS 独立模式的 PWA 没有系统边缘返回,
// 这副手势补上 — 屏幕左缘起手往右划, 页面跟手滑开, 松手过阈值退回上一页
// (body[data-back] 给目标地址, 没这属性的页不接线, 记账主页/登录前都不装)。
// 与类别列表的行左滑互不抢: 行滑那边认「左缘起手且右划」让位 (同 24px)。
"use strict";
(function () {
  const target = document.body.dataset.back;
  if (!target) return;
  const EDGE = 24;    // 左缘判定 (bookkeeping-categories.js 让位用的同一条, 改要两边一起)
  const GO = 72;      // 划过这道才算返回; 轻快一甩 (36px 内 160ms) 也认
  let g = null;
  document.addEventListener("touchstart", (e) => {
    const t = e.changedTouches[0];
    g = null;
    if (t.clientX > EDGE) return;                 // 不在左缘: 普通触摸
    if (t.target instanceof Element && t.target.closest("#cat-modal")) return;
    g = { x0: t.clientX, y0: t.clientY, t0: e.timeStamp, mode: "" };  // 弹框开着不返回
  }, { passive: true });
  document.addEventListener("touchmove", (e) => {
    if (!g) return;
    const t = e.changedTouches[0];
    const dx = t.clientX - g.x0, dy = t.clientY - g.y0;
    if (!g.mode) {              // 先辨意图: 竖着滚还给页面, 横着才接
      if (Math.abs(dy) > 8 && Math.abs(dy) > Math.abs(dx)) { g = null; return; }
      if (dx > 12) g.mode = "back";
      else return;
    }
    e.preventDefault();         // 横拖钉住页面 (别同时纵滚)
    document.body.style.transition = "none";
    document.body.style.transform = `translateX(${dx}px)`;
  }, { passive: false });
  function settle(e) {          // 松手: 过线走人, 不过线弹回
    if (!g) return;
    if (g.mode === "back") {
      const t = e.changedTouches[0];
      const dx = t.clientX - g.x0, dt = e.timeStamp - g.t0;
      document.body.style.transition = "transform .18s ease";
      if (dx > GO || (dx > 36 && dt < 160)) {
        document.body.style.transform = "translateX(100%)";
        location.href = target;
      } else {
        document.body.style.transform = "";
      }
    }
    g = null;
  }
  document.addEventListener("touchend", settle);
  document.addEventListener("touchcancel", settle);
  window.addEventListener("pageshow", () => {   // bfcache 恢复: 滑出一半的页面别定格在外头
    document.body.style.transform = "";
  });
})();
