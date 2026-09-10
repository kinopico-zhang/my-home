/* trackutil.js (splitGaps 轨迹断档拆分) 的 node --test 单元测试。 */
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const TrackUtil = require("../../app/static/trackutil.js");
const { splitGaps } = TrackUtil;

const M = 0.00001;   // ~1.1m, 城市打点步长

function track(n, step = M, start = 114) {
  return Array.from({ length: n }, (_, i) => [start + i * step, 22.5]);
}

test("正常轨迹不拆分", () => {
  const pts = track(500);
  const segs = splitGaps(pts);
  assert.equal(segs.length, 1);
  assert.equal(segs[0].length, 500);
});

test("城市轨迹中的 GPS 断档 (731m 瞬移) 在断点处拆开", () => {
  const pts = track(500);
  const jump = 0.0066;   // ~730m
  // 在中间插入一个瞬移点: 第 250 点突然跳到 731m 外
  const withGap = [...pts.slice(0, 250),
                   [pts[249][0] + jump, pts[249][1] + jump * 0.5],
                   ...pts.slice(250).map(p => [p[0] + jump, p[1] + jump * 0.5])];
  const segs = splitGaps(withGap);
  assert.equal(segs.length, 2);
  assert.ok(segs[0].length >= 2 && segs[1].length >= 2);
  // 第一段止于断点前最后一点, 第二段从瞬移点开始 (不直连)
  assert.deepEqual(segs[0][segs[0].length - 1], pts[249]);
  assert.deepEqual(segs[1][0], [pts[249][0] + jump, pts[249][1] + jump * 0.5]);
});

test("概览粗轨迹 (段长公里级) 不误拆", () => {
  const pts = track(40, 0.01);   // 每段 ~1.1km
  const segs = splitGaps(pts);
  assert.equal(segs.length, 1);
});

test("混合轨迹 (城市+高速段) 中位数阈值不被高速段拉高", () => {
  const city = track(300, M);
  const hwy = track(100, 0.0013);   // 高速 ~145m/段
  const pts = [...city, ...hwy];
  // 末尾再接一个城市段并制造 731m 断档
  const tail = track(100, M, 115).map(p => [p[0] + 0.2, p[1] + 0.2]);
  const withGap = [...pts, tail];
  const segs = splitGaps(withGap);
  assert.equal(segs.length, 2);   // 城市中位阈值 ~160m 下限, 145m 高速段不拆, 731m 断档拆
  assert.ok(segs[1].length >= 2);
});

test("短轨迹原样返回", () => {
  assert.deepEqual(splitGaps([[114, 22.5], [114.1, 22.6]]),
                   [[[114, 22.5], [114.1, 22.6]]]);
  assert.deepEqual(splitGaps(null), []);
});

test("全是孤立大跳点时退回整条, 不让轨迹消失", () => {
  const pts = [[114, 22.5], [115, 23.5], [113, 21.5]];
  assert.deepEqual(splitGaps(pts), [pts]);
});


/* ---------------- speedLines: 速度着色分档 ---------------- */
const C0 = "#e5484d", C4 = "#1fa349";   // 最慢红 / 最快绿

test("匀速轨迹只出一段, 颜色按速度档", () => {
  const slow = Array.from({ length: 10 }, (_, i) => [114 + i * 1e-4, 22.5, 8]);
  const fast = Array.from({ length: 10 }, (_, i) => [114 + i * 1e-4, 22.5, 120]);
  assert.equal(splitGaps, splitGaps);   // import 自检
  const ls = TrackUtil.speedLines(slow);
  assert.equal(ls.length, 1);
  assert.equal(ls[0].color, C0);
  assert.equal(ls[0].pts.length, 10);
  assert.equal(TrackUtil.speedLines(fast)[0].color, C4);
});

test("变速轨迹分段着色, 相邻段共享端点不留缝", () => {
  // 5 段: 0 → 20 → 50 → 80 → 120 km/h, 每档 3 个点
  const speeds = [0, 0, 0, 20, 20, 20, 50, 50, 50, 80, 80, 80, 120, 120, 120];
  const pts = speeds.map((s, i) => [114 + i * 1e-4, 22.5, s]);
  const ls = TrackUtil.speedLines(pts);
  assert.equal(ls.length, 5);
  assert.deepEqual(ls.map(l => l.color), TrackUtil.SPEED_COLORS);
  for (let i = 1; i < ls.length; i++) {
    // 前一段末点 == 后一段首点 (共享端点)
    assert.deepEqual(ls[i].pts[0], ls[i - 1].pts[ls[i - 1].pts.length - 1]);
  }
});

test("速度缺失按 0 处理", () => {
  const pts = [[114, 22.5, null], [114.001, 22.5, undefined], [114.002, 22.5, 5]];
  const ls = TrackUtil.speedLines(pts);
  assert.equal(ls.length, 1);
  assert.equal(ls[0].color, C0);
});


/* ---------------- animIndex: 动画帧 → 点序号 (负时间戳钳制) ---------------- */

test("正常播放: 中点时刻取到中间点", () => {
  assert.equal(TrackUtil.animIndex(5000, 10000, 101), 50);
  assert.equal(TrackUtil.animIndex(0, 10000, 101), 0);
  assert.equal(TrackUtil.animIndex(10000, 10000, 101), 100);
});

test("Chrome rAF 时间戳早于 t0 (缓存命中同帧开播) → 钳制为 0, 不产生负下标", () => {
  // 实测抓到过 elapsed = -7.5ms → idx = -3 → pts[-3][2] 崩溃 → "没有动画"
  assert.equal(TrackUtil.animIndex(-7.5, 9600, 3845), 0);
  assert.equal(TrackUtil.animIndex(-1000, 9600, 3845), 0);
});

test("超出时长 (后台切回/帧延迟) → 钳制到末点", () => {
  assert.equal(TrackUtil.animIndex(999999, 9600, 3845), 3844);
  assert.equal(TrackUtil.animIndex(999999, 9600, 2), 1);
});


/* ---------------- cumDistKm: 播放中的实时里程 ---------------- */

test("cumDistKm: 向东每步 0.01° ≈ 1.03km (纬度 22.5°)", () => {
  const pts = [[114, 22.5], [114.01, 22.5], [114.02, 22.5]];
  const cum = TrackUtil.cumDistKm(pts);
  assert.equal(cum.length, 3);
  assert.equal(cum[0], 0);
  const step = 111.32 * Math.cos(22.5 * Math.PI / 180) * 0.01;  // ≈ 1.0286
  assert.ok(Math.abs(cum[1] - step) < 0.001, `cum[1]=${cum[1]}`);
  assert.ok(Math.abs(cum[2] - 2 * step) < 0.002);
});

test("cumDistKm: 对角步长按勾股定理累计", () => {
  // 向东北 45°: 每步 dx=0.01°, dy=0.01°, 约 1.455km
  const pts = [[114, 22.5], [114.01, 22.51], [114.02, 22.52]];
  const cum = TrackUtil.cumDistKm(pts);
  const kx = 111.32 * Math.cos(22.5 * Math.PI / 180), ky = 110.57;
  const step = Math.sqrt(kx ** 2 + ky ** 2) * 0.01;
  assert.ok(Math.abs(cum[1] - step) < 0.001);
  assert.ok(Math.abs(cum[2] - 2 * step) < 0.002);
});

test("cumDistKm: 单点为 0, 起点纬度缺失不炸", () => {
  assert.deepEqual(TrackUtil.cumDistKm([[114, 22.5]]), [0]);
  assert.equal(TrackUtil.cumDistKm([[114, null], [114.01, 0]])[1] > 1, true);
});


/* ---------------- gapsBetween: 真断档才画蓝色虚线 ---------------- */

test("gapsBetween: 真断档 (731m 跳变) 输出端点和公里数", () => {
  const pts = track(500);
  const jump = 0.0066;
  const withGap = [...pts.slice(0, 250),
                   [pts[249][0] + jump, pts[249][1] + jump * 0.5],
                   ...pts.slice(250).map(p => [p[0] + jump, p[1] + jump * 0.5])];
  const gaps = TrackUtil.gapsBetween(splitGaps(withGap));
  assert.equal(gaps.length, 1);
  assert.deepEqual(gaps[0].pts, [pts[249], [pts[249][0] + jump, pts[249][1] + jump * 0.5]]);
  assert.ok(gaps[0].km > 0.7 && gaps[0].km < 0.8, `km=${gaps[0].km}`);
});

test("gapsBetween: 孤立野点被 splitGaps 丢弃后的伪断档 (<160m) 不输出", () => {
  // A...B 野点C(跳出 731m) D(紧邻 B) E...: splitGaps 拆出 [A..B][C][D..E],
  // 丢掉单点段 C 后相邻段边界 B→D 很近, 不是真断档
  const pts = track(300);
  const jump = 0.0066;
  const b = pts[299];
  // 野点后轨迹在紧邻 B 处继续 (正常步长), 不再有大跳变
  const tail = Array.from({ length: 50 }, (_, i) => [b[0] + (i + 1) * M, b[1]]);
  const withOutlier = [...pts, [b[0] + jump, b[1] + jump], [b[0], b[1] + 0.0001], ...tail];
  const segs = splitGaps(withOutlier);
  assert.ok(segs.length >= 2, "应已拆段");
  assert.equal(TrackUtil.gapsBetween(segs).length, 0);
});


/* ---------------- splicePath: 断档跳变段替换为道路路径 ---------------- */

test("splicePath: 无路由时退回前缀切片", () => {
  const path = [[0, 0], [1, 0], [2, 0], [3, 0], [4, 0]];
  assert.deepEqual(TrackUtil.splicePath(path, [], 4), path);
  assert.deepEqual(TrackUtil.splicePath(path, [], 2), [[0, 0], [1, 0], [2, 0]]);
});

test("splicePath: 播过断档后跳变段被道路路径替换 (route 含两端)", () => {
  const path = [[0, 0], [1, 0], [2, 0], [3, 0], [4, 0]];
  const route = [[2, 0], [2.5, 0.5], [3, 0]];   // path[2]→path[3] 的道路路径
  const splices = [{ aIdx: 2, bIdx: 3, route }];
  // 播到 idx=2 (还没过断档 bIdx=3): 原样前缀
  assert.deepEqual(TrackUtil.splicePath(path, splices, 2),
                   [[0, 0], [1, 0], [2, 0]]);
  // 播到 idx=4 (已过断档): path[2..3] 被 route 整段替换
  assert.deepEqual(TrackUtil.splicePath(path, splices, 4),
                   [[0, 0], [1, 0], [2, 0], [2.5, 0.5], [3, 0], [4, 0]]);
});

test("splicePath: 多处断档按序替换", () => {
  const path = [[0, 0], [1, 0], [2, 0], [3, 0], [4, 0], [5, 0], [6, 0]];
  const splices = [
    { aIdx: 1, bIdx: 2, route: [[1, 0], [1.5, 1], [2, 0]] },
    { aIdx: 4, bIdx: 5, route: [[4, 0], [4.5, -1], [5, 0]] },
  ];
  assert.deepEqual(TrackUtil.splicePath(path, splices, 6),
                   [[0, 0], [1, 0], [1.5, 1], [2, 0], [3, 0], [4, 0],
                    [4.5, -1], [5, 0], [6, 0]]);
  // 播到 idx=3 (过第一处, 没过第二处 bIdx=5): 只替换第一处
  assert.deepEqual(TrackUtil.splicePath(path, splices, 3),
                   [[0, 0], [1, 0], [1.5, 1], [2, 0], [3, 0]]);
});

/* ---------------- meanPowerW: 按时间加权的平均功耗 ---------------- */

test("meanPowerW: 按时间加权, 段功耗取两端平均", () => {
  // 段1 0→10s: (1000+1000)/2×10; 段2 10→30s: (1000+4000)/2×20
  // → (10000 + 50000)/30 = 2000W
  const pts = [[114, 22.5, 10, 1000], [114.001, 22.5, 20, 1000],
               [114.002, 22.5, 30, 4000]];
  const ts = [0, 10, 30];
  assert.equal(TrackUtil.meanPowerW(pts, ts), 2000);
});

test("meanPowerW: 单端缺失用另一端, 双缺段不计入", () => {
  // 0-10s: a=1000 b=null → 1000; 10-20s: 双 null 跳过; 20-40s: a=null b=6000 → 6000
  // → (1000×10 + 6000×20) / 30
  const pts = [[114, 22.5, 10, 1000], [114.001, 22.5, 20, null],
               [114.002, 22.5, 30, null], [114.003, 22.5, 30, 6000]];
  const ts = [0, 10, 20, 40];
  assert.equal(TrackUtil.meanPowerW(pts, ts), (1000 * 10 + 6000 * 20) / 30);
});

test("meanPowerW: 全无数据/零时长返回 null", () => {
  assert.equal(TrackUtil.meanPowerW([[114, 22.5, 10, null], [114.001, 22.5, 20, null]],
                                    [0, 10]), null);
  assert.equal(TrackUtil.meanPowerW([[114, 22.5, 10, 5000]], [0]), null);
});

/* ---- ptDistKm / bearingDeg (断档补路的方向校验) ---- */
test("ptDistKm: 东移 0.01° ≈ 1.03km (cos22°), 北移 0.01° ≈ 1.11km", () => {
  assert.ok(Math.abs(TrackUtil.ptDistKm([114, 22], [114.01, 22]) - 1.03) < 0.02);
  assert.ok(Math.abs(TrackUtil.ptDistKm([114, 22], [114, 22.01]) - 1.11) < 0.02);
  assert.equal(TrackUtil.ptDistKm([114, 22], [114, 22]), 0);
});

test("bearingDeg: 北 0 东 90 南 180 西 270", () => {
  assert.equal(Math.round(TrackUtil.bearingDeg([114, 22], [114, 22.01])), 0);
  assert.equal(Math.round(TrackUtil.bearingDeg([114, 22], [114.01, 22])), 90);
  assert.equal(Math.round(TrackUtil.bearingDeg([114, 22], [114, 22 - 0.01])), 180);
  assert.equal(Math.round(TrackUtil.bearingDeg([114, 22], [114 - 0.01, 22])), 270);
});
