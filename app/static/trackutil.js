/* 轨迹折线工具: 识别 GPS 断档大跳变 (隧道/信号丢失时相邻点瞬移几百米),
   把折线在跳变处拆成多段 —— 不拆的话两点间直连"飞线"会穿过街区。
   阈值自适应 (段长中位数的 10 倍, 下限 ~0.0016° ≈ 160m):
   - 城市轨迹段长 10-30m, 断档 700m+ → 拆;
   - 概览粗轨迹 (40 点/条, 段长常达公里级) → 阈值跟着变大, 不误拆。
   UMD: 浏览器挂 window.TrackUtil, node (测试) 走 module.exports。 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.TrackUtil = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";
  const MIN_GAP = 0.0016;   // ~160m, 城市里正常采样不会一步跨这么远

  function segLen(a, b) {   // 段长 (取经纬度差较大者, 度)
    return Math.max(Math.abs(b[0] - a[0]), Math.abs(b[1] - a[1]));
  }

  function splitGaps(pts) {
    if (!pts || pts.length < 3) return pts ? [pts] : [];
    // 抽样取段长中位数 (不是平均数: 混着高速段的轨迹平均会被拉高)
    const lens = [];
    for (let i = 1; i < pts.length; i += 7) lens.push(segLen(pts[i - 1], pts[i]));
    lens.sort((a, b) => a - b);
    const med = lens.length ? lens[lens.length >> 1] : 0;
    const thresh = Math.max(MIN_GAP, med * 10);
    const segs = [];
    let cur = [pts[0]];
    for (let i = 1; i < pts.length; i++) {
      if (segLen(pts[i - 1], pts[i]) > thresh) { segs.push(cur); cur = []; }
      cur.push(pts[i]);
    }
    segs.push(cur);
    const ok = segs.filter(s => s.length >= 2);
    return ok.length ? ok : [pts];   // 全是孤立点时按原样画, 不能让轨迹消失
  }

  /* ---- 速度着色: 慢=红 快=绿 (行程弹层轨迹) ----
     pts 每点 [lng, lat, speed_km_h]; 相邻点同档连成一段, 相邻段共享端点。
     返回 [{color, pts: [[lng,lat], ...]}], 坐标保持 WGS-84, 由调用方转 GCJ-02。 */
  const SPEED_STOPS = [15, 40, 70, 100];   // 分档阈值 km/h
  const SPEED_COLORS = ["#e5484d", "#e08a2e", "#d9b42a", "#9dbb32", "#1fa349"];

  function speedBucket(s) {
    let i = 0;
    while (i < SPEED_STOPS.length && s >= SPEED_STOPS[i]) i++;
    return i;
  }

  function speedLines(pts) {
    const lines = [];
    let cur = null;                            // {color, pts}
    for (let i = 1; i < pts.length; i++) {
      const s = Math.max(pts[i - 1][2] || 0, pts[i][2] || 0);   // 段速取两端较大
      const color = SPEED_COLORS[speedBucket(s)];
      if (!cur || cur.color !== color) {
        if (cur) lines.push(cur);
        cur = { color: color, pts: [pts[i - 1]] };   // 共享端点, 段间不留缝
      }
      cur.pts.push(pts[i]);
    }
    if (cur) lines.push(cur);
    return lines;
  }

  /* ---- 累计里程: 轨迹点 → 每点累计公里数 (等距圆柱近似, 展示精度足够) ----
     cum[i] = 起点到第 i 点的里程 (km), cum[0] = 0; 播放动画实时里程用它。 */
  function cumDistKm(pts) {
    const cum = [0];
    const kx = 111.32 * Math.cos((pts[0][1] || 0) * Math.PI / 180);  // 每经度 km
    const ky = 110.57;                                                // 每纬度 km
    for (let i = 1; i < pts.length; i++) {
      const dx = (pts[i][0] - pts[i - 1][0]) * kx;
      const dy = (pts[i][1] - pts[i - 1][1]) * ky;
      cum.push(cum[i - 1] + Math.sqrt(dx * dx + dy * dy));
    }
    return cum;
  }

  /* ---- 相邻段之间的断档 (供"缺失段"蓝色虚线): [{pts: [a, b], km: 跳变公里数}] ----
     注意 splitGaps 会丢掉只含 1 个点的孤立段 (GPS 野点), 这时相邻返回段的
     边界距离可能很小, 不是真断档 —— 按最小跳变距离过滤掉。 */
  const MIN_GAP_KM = 0.16;   // 与 MIN_GAP (~160m) 对齐

  function gapsBetween(segs) {
    const gaps = [];
    for (let i = 1; i < segs.length; i++) {
      const a = segs[i - 1][segs[i - 1].length - 1], b = segs[i][0];
      const kx = 111.32 * Math.cos((((a[1] || 0) + (b[1] || 0)) / 2) * Math.PI / 180);
      const ky = 110.57;
      const km = Math.hypot((b[0] - a[0]) * kx, (b[1] - a[1]) * ky);
      if (km >= MIN_GAP_KM) gaps.push({ pts: [a, b], km: km });
    }
    return gaps;
  }

  /* ---- 动画: 已播放毫秒 → 当前点序号 ----
     Chrome 的 rAF 回调时间戳是"帧开始时刻", 可能早于 scheduling 前一刻取的
     performance.now() (t0)。命中缓存的轨迹在同一帧内开播就会得到负 t →
     负下标 → 读 pts[-3][2] 直接崩溃, 表现为"这条轨迹没有动画" (Safari 时间戳
     不回退所以不复现)。钳制 elapsed 到 [0, dur], 序号到 [0, n-1]。 */
  function animIndex(elapsed, dur, n) {
    const t = Math.min(Math.max(elapsed / dur, 0), 1);
    return Math.max(0, Math.min(n - 1, Math.round(t * (n - 1))));
  }

  return { splitGaps: splitGaps, gapsBetween: gapsBetween, speedLines: speedLines, cumDistKm: cumDistKm, animIndex: animIndex,
           speedBucket: speedBucket, SPEED_COLORS: SPEED_COLORS, _segLen: segLen };
});
