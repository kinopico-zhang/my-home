// amount-calculator.js — 金额键盘的纯逻辑: 表达式求值 + 按键输入规则。
// 单独成模块: node --test 直测 + c8 覆盖 (键盘 DOM 与交互在 bookkeeping.js, 由 E2E 覆盖)。
//
// 表达式文法: 数字 (0-9 与小数点) 与 + - * / 四则, 乘除优先, 不带括号;
// 空串 / 有剩余字符 / 除零 / 结果非有限 → null。

// 求值: 递归下降 (expr → term → unary → number), 支持一元正负 (如 5*-2)。
function evaluateAmount(expr) {
  const s = String(expr == null ? "" : expr).replace(/\s+/g, "");
  if (!s) return null;
  let pos = 0;
  function number() {
    const m = /^[0-9]+(\.[0-9]*)?|\.[0-9]+/.exec(s.slice(pos));
    if (!m) throw new Error("not a number");
    pos += m[0].length;
    return parseFloat(m[0]);
  }
  function unary() {
    if (s[pos] === "+" || s[pos] === "-") {
      const sign = s[pos] === "-" ? -1 : 1;
      pos++;
      return sign * unary();
    }
    return number();
  }
  function term() {
    let v = unary();
    while (s[pos] === "*" || s[pos] === "/") {
      const op = s[pos++];
      const r = unary();
      v = op === "*" ? v * r : v / r;
    }
    return v;
  }
  function sum() {
    let v = term();
    while (s[pos] === "+" || s[pos] === "-") {
      const op = s[pos++];
      const r = term();
      v = op === "+" ? v + r : v - r;
    }
    return v;
  }
  try {
    const v = sum();
    if (pos !== s.length || !isFinite(v)) return null;  // 没吃完 = 非法
    return v;
  } catch (_e) { return null; }
}

// 按键 → 新表达式。key: "0"~"9" / "." / "+" / "-" / "*" / "/" / "back" / "clear"。
// 计算器习惯: 没数之前按不动运算符; 运算符连按是改主意 (顶掉前一个);
// 一段数字最多一个小数点; 前导 0 被数字顶掉 (05 → 5)。
function applyAmountKey(expr, key) {
  const s = String(expr == null ? "" : expr);
  const OPS = "+-*/";
  if (key === "clear") return "";
  if (key === "back") return s.slice(0, -1);
  if (OPS.indexOf(key) !== -1) {
    if (!s) return s;                                    // 先有数才有运算
    return OPS.indexOf(s.slice(-1)) !== -1 ? s.slice(0, -1) + key : s + key;
  }
  const seg = s.split(/[+\-*/]/).pop();                  // 当前数段
  if (key === ".") {
    if (seg.indexOf(".") !== -1) return s;               // 一段一个点
    return s + (seg === "" ? "0." : ".");
  }
  if (/^[0-9]$/.test(key)) {
    if (s.length >= 24) return s;                        // 表达式长度上限
    if (seg === "0") return s.slice(0, -1) + key;        // 前导 0 顶掉
    return s + key;
  }
  return s;                                              // 不认识的键不动
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { evaluateAmount, applyAmountKey };
}
