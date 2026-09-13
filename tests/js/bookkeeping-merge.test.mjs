/* bookkeeping-merge.js (记账同步纯合并逻辑) 的 node --test 单元测试。
   覆盖: LWW 归并 (新行/覆盖/平局归服务器/本地更新保留)、脏名单上行、
   展示过滤 (月份/记账人/墓碑)、月度合计。 */
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const dir = path.join(path.dirname(fileURLToPath(import.meta.url)), "../../app/bookkeeping/static");
const { mergeEntries, entriesToUpload, remoteWins,
        visibleEntries, monthTotals } = require(path.join(dir, "bookkeeping-merge.js"));

const e = (id, updatedAt, extra = {}) => Object.assign({
  id, date: "2026-09-01", amount: 10, kind: "expense",
  category: "餐饮", note: "", deleted: false, updatedAt,
  createdByName: "甲", updatedByName: "甲",
}, extra);

test("remoteWins: 本地缺失 → 服务器覆盖", () => {
  assert.equal(remoteWins(null, e("a", "2026-09-01T00:00:00Z")), true);
});

test("remoteWins: 服务器更新 → 覆盖; 服务器更旧 → 不覆盖", () => {
  const local = e("a", "2026-09-01T00:00:05Z");
  assert.equal(remoteWins(local, e("a", "2026-09-01T00:00:06Z")), true);
  assert.equal(remoteWins(local, e("a", "2026-09-01T00:00:04Z")), false);
});

test("remoteWins: 时间戳相等归服务器 (回声带记账人名, 换掉本地的占位)", () => {
  const local = e("a", "2026-09-01T00:00:05Z", { createdByName: "" });
  assert.equal(remoteWins(local, e("a", "2026-09-01T00:00:05Z")), true);
});

test("remoteWins: 服务器 +00:00 与本地 Z 是同一时刻 (字符串字典序不可比)", () => {
  const local = e("a", "2026-09-01T08:00:05Z");
  assert.equal(remoteWins(local, e("a", "2026-09-01T08:00:05+00:00")), true);
  assert.equal(remoteWins(local, e("a", "2026-09-01T08:00:04+00:00")), false);
});

test("mergeEntries: 新行插入, 已有按 LWW 归并, 无关行原样保留", () => {
  const local = [e("a", "2026-09-01T00:00:05Z"), e("b", "2026-09-01T00:00:05Z")];
  const remote = [
    e("a", "2026-09-01T00:00:06Z", { amount: 20 }),       // 更新: 覆盖
    e("c", "2026-09-01T00:00:01Z"),                       // 新行: 收下
    e("b", "2026-09-01T00:00:04Z", { amount: 99 }),       // 更旧: 本地保留
  ];
  const merged = mergeEntries(local, remote);
  assert.equal(merged.length, 3);
  assert.equal(merged.find(x => x.id === "a").amount, 20);
  assert.equal(merged.find(x => x.id === "b").amount, 10);
  assert.ok(merged.find(x => x.id === "c"));
});

test("mergeEntries: 墓碑 (删除) 也走 LWW 同步", () => {
  const local = [e("a", "2026-09-01T00:00:05Z")];
  const merged = mergeEntries(local,
    [e("a", "2026-09-01T00:00:06Z", { deleted: true })]);
  assert.equal(merged[0].deleted, true);
  assert.equal(merged.length, 1);      // 墓碑留在账本里, 展示层过滤
});

test("entriesToUpload: 只带脏名单里的, 且只挑协议字段 (snake_case, 不带记账人名)", () => {
  const entries = [
    e("a", "2026-09-01T00:00:01Z"),
    e("b", "2026-09-01T00:00:02Z", { note: "改过" }),
    e("c", "2026-09-01T00:00:03Z", { deleted: true }),
  ];
  const up = entriesToUpload(entries, ["b", "c"]);
  assert.deepEqual(up.map(x => x.id), ["b", "c"]);
  assert.deepEqual(up[0], {
    id: "b", date: "2026-09-01", time: "", amount: 10, kind: "expense",
    category: "餐饮", tags: [], note: "改过", deleted: false,
    updated_at: "2026-09-01T00:00:02Z",
  });
  assert.equal(up[1].deleted, true);
});

test("entriesToUpload: 时刻和标签跟着上行; 老条目缺字段补空", () => {
  const up = entriesToUpload([
    e("a", "2026-09-01T00:00:01Z", { time: "08:15", tags: ["报销", "固定"] }),
    e("b", "2026-09-01T00:00:02Z"),               // 再记功能前记的老账
  ], ["a", "b"]);
  assert.equal(up[0].time, "08:15");
  assert.deepEqual(up[0].tags, ["报销", "固定"]);
  assert.equal(up[1].time, "");
  assert.deepEqual(up[1].tags, []);
});

test("entriesToUpload: 脏名单是空 → 不上行任何东西", () => {
  const entries = [e("a", "2026-09-01T00:00:01Z")];
  assert.deepEqual(entriesToUpload(entries, []), []);
});

test("visibleEntries: 过滤墓碑 / 其他月份 / 记账人", () => {
  const entries = [
    e("a", "2026-09-01T00:00:01Z"),
    e("b", "2026-09-02T00:00:01Z", { deleted: true }),                 // 墓碑
    e("c", "2026-08-31T00:00:01Z", { date: "2026-08-31" }),            // 别的月
    e("d", "2026-09-03T00:00:01Z", { createdByName: "乙" }),           // 别人
  ];
  assert.deepEqual(visibleEntries(entries, "2026-09", "").map(x => x.id), ["a", "d"]);
  assert.deepEqual(visibleEntries(entries, "2026-09", "乙").map(x => x.id), ["d"]);
});

test("monthTotals: 支出收入分开, 墓碑和别的月不算", () => {
  const entries = [
    e("a", "2026-09-01T00:00:01Z", { amount: 12.5 }),
    e("b", "2026-09-02T00:00:01Z", { amount: 7.5, kind: "income" }),
    e("c", "2026-09-03T00:00:01Z", { amount: 99, deleted: true }),
    e("d", "2026-08-31T00:00:01Z", { amount: 88, date: "2026-08-31" }),
  ];
  assert.deepEqual(monthTotals(entries, "2026-09"), { expense: 12.5, income: 7.5 });
  assert.deepEqual(monthTotals(entries, "2026-08"), { expense: 88, income: 0 });
});
