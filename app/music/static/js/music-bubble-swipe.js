// music-bubble-swipe — My Music 播放气泡右划返回 (1.8.5 修「气泡右划返回
// 不好用」): 气泡是船坞里的固定件 (z50), 盖在推入层 (z44) 上面 —— 层上的
// 右划手势根本收不到它, 1.8.0 层铺满全高后气泡底下的内容全是层, 气泡
// 自己就成了手势死角。给气泡单绑一份: 拖的是栈顶层 (跟手上层同款位移),
// 松手够远或带甩劲就收层; 竖向/左划立刻放掉, 不碍气泡自己的点击与滚动。
"use strict";
/* global $, closePushStack, paneMotion, pushStack */

(function bindBubbleSwipe() {
  const bubble = $("#mini-player");
  bubble.addEventListener("pointerdown", (event) => {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    if (!pushStack.length) return;          // 没有层可收, 原样
    const pane = pushStack[pushStack.length - 1].pane;
    const startX = event.clientX;
    const startY = event.clientY;
    let horizontal = false;
    let decided = false;
    let lastX = startX;
    let lastT = event.timeStamp;
    const signals = new AbortController();
    const cleanup = () => signals.abort();
    const move = (ev) => {
      const dx = ev.clientX - startX;
      const dy = ev.clientY - startY;
      if (!decided) {
        if (Math.abs(dx) < 8 && Math.abs(dy) < 8) return;
        decided = true;
        horizontal = dx > 0 && Math.abs(dx) > Math.abs(dy);
        if (!horizontal) { cleanup(); return; }   // 竖向/左划: 还给气泡
        bubble.setPointerCapture(ev.pointerId);
        pane.style.transition = "none";
      }
      paneMotion();                 // 拖动中: 磨砂持续暂撤 (每下续期)
      pane.style.transform = `translateX(${Math.max(0, dx)}px)`;
      lastX = ev.clientX;
      lastT = ev.timeStamp;
    };
    const end = (ev) => {
      cleanup();
      if (!horizontal) return;
      const dx = Math.max(0, ev.clientX - startX);
      const width = pane.offsetWidth || 1;
      const flick = ev.timeStamp - lastT < 100 && lastX - startX > 40;
      pane.style.transition = "";
      pane.style.transform = "";
      if (dx <= width / 3 && !flick) {
        paneMotion();               // 弹回也是一段运动, 磨砂照旧暂撤
        return;
      }
      closePushStack(pushStack.length - 1);   // 只收顶层 (Esc 同款走法)
    };
    const cancel = () => {
      cleanup();
      if (horizontal) {
        paneMotion();
        pane.style.transition = "";
        pane.style.transform = "";
      }
    };
    bubble.addEventListener("pointermove", move, { signal: signals.signal });
    bubble.addEventListener("pointerup", end, { signal: signals.signal });
    bubble.addEventListener("pointercancel", cancel, { signal: signals.signal });
  });
}());
