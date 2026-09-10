/* trackutil.js (splitGaps 轨迹断档拆分) 的 node --test 单元测试。 */
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { splitGaps } = require("../../app/static/trackutil.js");

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
