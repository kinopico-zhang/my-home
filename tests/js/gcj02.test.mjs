/* gcj02.js (WGS-84 ↔ GCJ-02) 的 node --test 单元测试。 */
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const G = require(path.join(
  path.dirname(fileURLToPath(import.meta.url)), "..", "..",
  "app", "static", "gcj02.js"));

test("outOfChina 判断中国范围", () => {
  assert.equal(G.outOfChina(0, 0), true);
  assert.equal(G.outOfChina(139.69, 35.69), true);   // 东京
  assert.equal(G.outOfChina(116.4, 39.9), false);    // 北京
  assert.equal(G.outOfChina(114.05, 22.55), false);  // 深圳
});

test("中国范围外坐标原样返回", () => {
  assert.deepEqual(G.wgs84ToGcj02(139.69, 35.69), [139.69, 35.69]);
  assert.deepEqual(G.gcj02ToWgs84(-0.1276, 51.5072), [-0.1276, 51.5072]);
});

test("境内偏移量级合理 (数百米)", () => {
  for (const [lng, lat] of [[116.3975, 39.9089], [114.05, 22.55],
                            [121.4737, 31.2304], [104.0657, 30.6599]]) {
    const [glng, glat] = G.wgs84ToGcj02(lng, lat);
    const dLng = Math.abs(glng - lng), dLat = Math.abs(glat - lat);
    // 0.001° ≈ 100m, 实际偏移约 300-700m
    assert.ok(dLng > 0.001 && dLng < 0.012, `dLng=${dLng} at ${lat},${lng}`);
    assert.ok(dLat > 0.001 && dLat < 0.012, `dLat=${dLat} at ${lat},${lng}`);
  }
});

test("深圳点经度东移, 纬度偏移方向不固定 (南半球段为负)", () => {
  const [glng, glat] = G.wgs84ToGcj02(114.05, 22.55);
  assert.ok(glng > 114.05, `经度应东移: ${glng}`);
  // 华南纬度偏移为负 (向南), 量级与其他城市一致
  assert.ok(Math.abs(glat - 22.55) > 0.001, `纬度偏移量级异常: ${glat}`);
});

test("逆变换近似还原 (误差 < 1e-4°, 约 10m)", () => {
  for (const [lng, lat] of [[116.3975, 39.9089], [114.05, 22.55],
                            [121.4737, 31.2304], [113.2644, 23.1291]]) {
    const [glng, glat] = G.wgs84ToGcj02(lng, lat);
    const [wlng, wlat] = G.gcj02ToWgs84(glng, glat);
    assert.ok(Math.abs(wlng - lng) < 1e-4, `lng ${lng} -> ${wlng}`);
    assert.ok(Math.abs(wlat - lat) < 1e-4, `lat ${lat} -> ${wlat}`);
  }
});
