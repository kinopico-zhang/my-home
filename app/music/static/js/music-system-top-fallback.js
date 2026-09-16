// music-system-top-fallback — My Music iOS 系统顶带兜底 (WebKit 301994 机型表, 下批界面重构撤除)。
// 拆自 music.js (结构化重构: 代码逐字节未动, 经典脚本按 music.html 里的顺序加载, 跨模块引用走全局)。
"use strict";

// ------------------------------------------------------------ iOS 系统顶带兜底
// 苹果的系统 bug (WebKit 301994): iOS 26.1 起主屏独立模式里, 系统在屏幕
// 顶部盖一条磨砂带 (画在网页层外面, DOM/CSS 都够不着), 同时把
// env(safe-area-inset-top) 误报成 0 —— 26.2 修过一次, 26.5.2 和 iOS 27
// 又复发了。env 一报 0, 页面里所有顶部让位全部失效, 内容照样钻进磨砂带
// 被糊掉、还顶出屏幕外。
// 这个 bug 有两副面孔, 兜底各给各的值写进 --sys-top-inset:
//   盖磨砂型 (env=0): 按机型屏幕尺寸表兜「刘海高 + 磨砂深度」;
//   推下型 (innerHeight 被吃掉一截): 兜「推下量 + 渗边」, 让不透明黑罩
//     (#top-shield) 盖过整条系统带 —— 带子里显示的是系统从网页顶部抓拍
//     的画面, 黑罩够高, 抓拍条里就只剩纯黑, 残影带跟着隐形 (磨砂盖在
//     纯黑上看不出来)。
// 黑罩把「滚进带子的内容被栅糊」也一并了结: 内容从罩子底下扫过, 只会被
// 干净地遮住。健康 iOS 和浏览器里 env 正常, 兜底恒 0, 一切照旧。
const SYS_TOP_INSETS = {  // 机型屏幕 (短边x长边, CSS px) → 刘海/灵动岛高度
  "375x812": 47, "390x844": 47, "393x852": 59, "414x896": 47,
  "428x926": 47, "430x932": 59, "440x956": 62,
};
// 系统磨砂带比安全区还深一截: 用户 iOS 27.2 实测 (2026-09-16, 393x852),
// 兜底 59 时第一排内容 (CSS 60-88) 仍被栅糊 (边缘强度只有下面几排的
// 1/4), 到 CSS 116 才完全锐利; 第二轮实测 (次日) 兜底 115 后用户仍见
// 带子底缘渗进一小条 —— 带子深度会浮动, 干脆垫足 88 (≈刘海+88=147),
// 宁可多让一截黑也别再露出糊边 (只在 env 谎报 0 的中招系统上生效)。
const SYS_FROST_EXTRA = 88;
// 推下变体里系统带的抓拍条比推下线还渗出一小截 (用户 iOS 27.2 实测:
// 推下 81, 阴影渗到 ~92), 黑罩在推下量上再垫这 16, 把渗边也盖进纯黑里
const SYS_PUSH_BLEED = 16;
function sysTopInsetFor(w, h) {
  const exact = SYS_TOP_INSETS[`${Math.min(w, h)}x${Math.max(w, h)}`];
  const inset = exact || (h >= 940 ? 62 : h >= 850 ? 59 : 47);  // 表外新机型按高度估
  return inset + SYS_FROST_EXTRA;
}
function envTopPx() {
  const probe = document.createElement("div");
  probe.style.cssText = "position:fixed;top:0;left:0;"
    + "height:env(safe-area-inset-top);visibility:hidden;pointer-events:none;";
  document.body.appendChild(probe);
  const px = probe.offsetHeight;
  probe.remove();
  return px;
}
// 会话锁 (只锁在中招变体里): env 偶发抖回真值的那一下不许撤兜底
// (撤了内容整页跳回磨砂带); 离开中招状态 (横屏/浏览器) 立即清零 ——
// 锁着进横屏会把竖屏的兜底高度带过去, 顶部凭空让出一大截。
// 苹果哪天真修好: 冷启动第一次同步 env 就是真值且没推下, 锁不会上,
// 一切照旧。
let sysTopLocked = 0;
function syncSysTopInset() {
  const state = {
    envTop: envTopPx(),
    standalone: matchMedia("(display-mode: standalone)").matches,
    portrait: matchMedia("(orientation: portrait)").matches,
  };
  const phone = /iPhone|iPod/.test(navigator.userAgent);
  const tall = Math.max(screen.width, screen.height) >= 800;  // SE 这类无刘海机除外
  const push = screen.height - innerHeight;
  const eligible = state.standalone && state.portrait && phone && tall;
  let target = 0;
  if (eligible) {
    if (push > 40) {
      // 推下变体: 兜底盖过整条系统带 (含渗边), 让抓拍条里只剩黑罩
      target = push + SYS_PUSH_BLEED;
    } else if (state.envTop === 0) {
      // 盖磨砂变体: 机型表 + 磨砂深度
      target = sysTopInsetFor(screen.width, screen.height);
    }
  }
  if (target) sysTopLocked = target;
  else if (!eligible) sysTopLocked = 0;
  document.documentElement.style.setProperty(
    "--sys-top-inset", `${sysTopLocked}px`);
}
addEventListener("resize", syncSysTopInset);
addEventListener("orientationchange", syncSysTopInset);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) syncSysTopInset();   // 挂后台几小时回来也重新核一遍
});
syncSysTopInset();
setTimeout(syncSysTopInset, 800);    // 冷启动 env 可能晚到 (短暂报 0),
setTimeout(syncSysTopInset, 2500);   // 稳定后自会翻回真值, max() 无缝接手

