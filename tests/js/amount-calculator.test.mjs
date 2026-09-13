// amount-calculator.test.mjs — 金额键盘纯逻辑: 表达式求值 + 按键输入规则
// (键盘 DOM 与交互在 bookkeeping.js, 由 E2E 覆盖; 这里只测能 require 的部分)
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const dir = path.join(path.dirname(fileURLToPath(import.meta.url)),
  "../../app/bookkeeping/static");
const { evaluateAmount, applyAmountKey } = require(
  path.join(dir, "amount-calculator.js"));

/* ---------- evaluateAmount: 四则表达式 (无括号, 乘除优先, 一元正负) ---------- */

test("evaluateAmount 四则混合乘除优先", () => {
  assert.equal(evaluateAmount("2+3*4"), 14);
  assert.equal(evaluateAmount("10-6/3"), 8);
  assert.equal(evaluateAmount("2*3+4*5"), 26);
  assert.equal(evaluateAmount("100/5/2"), 10);
});

test("evaluateAmount 小数与点尾", () => {
  assert.equal(evaluateAmount("25.5"), 25.5);
  assert.equal(evaluateAmount(".5"), 0.5);       // 无零头的小数
  assert.equal(evaluateAmount("12."), 12);       // 点结尾 (还在输入的中间态)
  assert.equal(evaluateAmount("0.1+0.2"), 0.30000000000000004);
});

test("evaluateAmount 一元正负", () => {
  assert.equal(evaluateAmount("-5"), -5);
  assert.equal(evaluateAmount("5*-2"), -10);
  assert.equal(evaluateAmount("-2--3"), 1);      // 减负数
  assert.equal(evaluateAmount("+5"), 5);
});

test("evaluateAmount 空白与空白串", () => {
  assert.equal(evaluateAmount(" 2 + 3 "), 5);    // 空白全剥
  assert.equal(evaluateAmount(""), null);
  assert.equal(evaluateAmount("   "), null);
  assert.equal(evaluateAmount(null), null);      // 空输入框
  assert.equal(evaluateAmount(undefined), null);
});

test("evaluateAmount 非法输入返回 null", () => {
  assert.equal(evaluateAmount("2+"), null);      // 运算符结尾 (输入中间态)
  assert.equal(evaluateAmount("*5"), null);      // 运算符开头
  assert.equal(evaluateAmount("1/0"), null);     // 除零 (非有限值)
  assert.equal(evaluateAmount("0/0"), null);
  assert.equal(evaluateAmount("1.2.3"), null);   // 一段里两个点
  assert.equal(evaluateAmount("abc"), null);
  assert.equal(evaluateAmount("2++3"), 5);      // 连续运算符: 第二个当一元正号
  assert.equal(evaluateAmount("()"), null);
});

/* ---------- applyAmountKey: 键盘按键怎么改表达式 ---------- */

test("applyAmountKey 数字与点", () => {
  assert.equal(applyAmountKey("", "5"), "5");
  assert.equal(applyAmountKey("5", "2"), "52");
  assert.equal(applyAmountKey("", "."), "0.");   // 空串点 → 补零
  assert.equal(applyAmountKey("5", "."), "5.");
  assert.equal(applyAmountKey("5.", "3"), "5.3");
});

test("applyAmountKey 前导零换掉, 一段只一个点", () => {
  assert.equal(applyAmountKey("0", "5"), "5");         // "05" 不要
  assert.equal(applyAmountKey("10", "5"), "105");      // 只有整段是 0 才换
  assert.equal(applyAmountKey("1+0", "5"), "1+5");     // 每段独立
  assert.equal(applyAmountKey("1.2", "."), "1.2");     // 同段第二个点忽略
  assert.equal(applyAmountKey("1.2+3", "."), "1.2+3.");  // 新段可点
});

test("applyAmountKey 运算符: 空不发, 连发替换", () => {
  assert.equal(applyAmountKey("", "+"), "");      // 没数先别运算
  assert.equal(applyAmountKey("5", "+"), "5+");
  assert.equal(applyAmountKey("5+", "-"), "5-");  // 运算符换运算符
  assert.equal(applyAmountKey("5*2", "+"), "5*2+");
});

test("applyAmountKey 回删与清除", () => {
  assert.equal(applyAmountKey("123", "back"), "12");
  assert.equal(applyAmountKey("1", "back"), "");
  assert.equal(applyAmountKey("", "back"), "");
  assert.equal(applyAmountKey("123", "clear"), "");
  assert.equal(applyAmountKey("", "clear"), "");
});

test("applyAmountKey 长度上限与非键字符", () => {
  let expr = "9".repeat(24);
  assert.equal(applyAmountKey(expr, "9"), expr);   // 24 字符封顶
  expr = "9".repeat(23);
  assert.equal(applyAmountKey(expr, "9"), "9".repeat(24));
  assert.equal(applyAmountKey("5", "x"), "5");     // 不认识的键原样返回
  assert.equal(applyAmountKey(5, "7"), "57");      // 数字输入兜底转串
});
