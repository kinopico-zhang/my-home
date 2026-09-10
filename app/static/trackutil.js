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

  return { splitGaps: splitGaps, speedLines: speedLines,
           speedBucket: speedBucket, SPEED_COLORS: SPEED_COLORS, _segLen: segLen };
});
