// music-pane-swipe — My Music 推入层右划返回手势: 面板任意位置起手, 横竖先分家
// (竖向交还滚动), 拖过三分之一或带甩劲松手就收层, 否则弹回。
// 拆自 music-push-panes.js (1.8.6: 文件超 200 行按域再拆, 代码逐字节未动;
// 手势回调时才解析, 后加载无碍)。
"use strict";
/* global paneMotion, pushStack, saveLastRoute, syncSearchDock, unlockRootScroll */
/* exported bindPaneSwipe */

/** 右划返回: 面板任意位置起手, 横竖先分家 (竖向交还滚动); 拖过三分之一
    或带甩劲松手就收层, 否则弹回。收层是纯视图收层, 不碰浏览器历史
    (一个地址走全程)。
    左缘的归属按环境各安其位: 主屏图标打开 (standalone) 没有系统手势,
    整条左缘 (含屏幕最边) 都是这里的; 浏览器里苹果把最边上一小条握在
    系统手里 (整页截图滑走, 网页收不到触摸, preventDefault/Navigation
    API 都掐不动 —— 试过两轮, 别再试), 那一条之外的左缘归这里。 */
function bindPaneSwipe(pane) {
  pane.addEventListener("pointerdown", (event) => {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    // 搜索结果四子页 (1.8.3) 自己是横向 snap 滚动器: 起手在页里的横拖
    // 归切页, 不归右划返回 —— 1.8.5 松一格: 歌曲页在最左 (scrollLeft 0)
    // 没得再往左滚, 右划归返回 (用户点名); 滚到别的页上照旧归切页
    const searchBody = event.target.closest("#search-body.paged");
    if (searchBody && searchBody.scrollLeft > 0) return;
    const startX = event.clientX;
    const startY = event.clientY;
    let horizontal = false;
    let decided = false;
    let lastX = startX;
    let lastT = event.timeStamp;
    const signals = new AbortController();        // 拆掉 cleanup ↔ 手柄的互相引用
    const cleanup = () => signals.abort();
    const move = (ev) => {
      const dx = ev.clientX - startX;
      const dy = ev.clientY - startY;
      if (!decided) {
        if (Math.abs(dx) < 8 && Math.abs(dy) < 8) return;
        decided = true;
        horizontal = dx > 0 && Math.abs(dx) > Math.abs(dy);
        if (!horizontal) { cleanup(); return; }   // 竖向: 交还滚动
        pane.setPointerCapture(ev.pointerId);
        pane.style.transition = "none";
      }
      paneMotion();                 // 拖动中: 气泡磨砂持续暂撤 (每下续期)
      pane.style.transform = `translateX(${Math.max(0, dx)}px)`;
      lastX = ev.clientX;
      lastT = ev.timeStamp;
    };
    const end = (ev) => {
      cleanup();
      if (!horizontal) return;      // 点按/竖向: 不归这里管
      const dx = Math.max(0, ev.clientX - startX);
      const width = pane.offsetWidth || 1;
      const flick = ev.timeStamp - lastT < 100 && lastX - startX > 40;
      pane.style.transition = "";
      pane.style.transform = "";
      if (dx <= width / 3 && !flick) {
        paneMotion();               // 弹回也是一段运动, 磨砂照旧暂撤
        return;                     // 没拖够: 弹回 (.open 的 0)
      }
      paneMotion();                 // 滑出途中气泡暂撤磨砂 (重影对策)
      pane.classList.remove("open");              // 从当前位置滑出
      pushStack.pop();
      // 焦点在本层 (如搜索输入框): 摘走再滑出, 键盘跟手收下 (同 closePushStack)
      if (pane.contains(document.activeElement)) document.activeElement.blur();
      setTimeout(() => pane.remove(), 420);
      if (!pushStack.length) unlockRootScroll();
      syncSearchDock();             // 手势收层也算换顶层 (1.8.5)
      saveLastRoute();              // 手势收层也记停在哪页 (开局回跳)
    };
    const cancel = () => {
      cleanup();
      if (horizontal) {
        paneMotion();               // 弹回也是一段运动, 磨砂照旧暂撤
        pane.style.transition = "";
        pane.style.transform = "";
      }
    };
    pane.addEventListener("pointermove", move, { signal: signals.signal });
    pane.addEventListener("pointerup", end, { signal: signals.signal });
    pane.addEventListener("pointercancel", cancel, { signal: signals.signal });
  });
}
