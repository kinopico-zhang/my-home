// setup.js — 首启引导: 三步全走完才能进应用, 不允许跳过。第一步建管理
// 员 (注册即登录, 后续接口都带会话); 带数据源/地图步骤的部署 (My Home /
// My Tesla) 顺路配 TeslaMate 与高德两把 Key, 一步变体 (My Money / My Music)
// 建完即完成。起步步数由 /api/setup-status 的 missing 决定 —— 中途退出
// 的续走 (管理员已在, 从缺口步接着); 完成跳转读 body 的 data-done;
// 步骤按 DOM 现状收集, 同一份脚本服务两种页面。步骤条三项可点, 任意跳
// 步回改; 数据源/地图两步的「测试闸」(测通了主按钮才解锁) 在
// setup-gates.js, 一步变体不加载那半边。
/* exported pass, webKeySet */
"use strict";
const card = document.getElementById("card");
const doneUrl = document.body.dataset.done || "/";
const forms = ["form1", "form2", "form3"]
  .map(id => document.getElementById(id)).filter(Boolean);

const fail = (form, msg) => {
  const err = form.querySelector(".err");
  err.textContent = msg;
  err.classList.remove("ok");
  card.classList.remove("shake");
  void card.offsetWidth;
  card.classList.add("shake");
};

// 测试通过的正字: 与 fail 同一条 .err, 换个颜色说话 (绿色见 css .ok)
const pass = (form, msg) => {
  const err = form.querySelector(".err");
  err.textContent = msg;
  err.classList.add("ok");
};

const showStep = index => {
  forms.forEach((form, i) => { form.hidden = i !== index; });
  const steps = document.getElementById("steps");
  if (steps) {
    Array.from(steps.children).forEach((li, i) => {
      li.classList.toggle("active", i === index);
      li.classList.toggle("done", i < index);
    });
  }
  const first = forms[index] && forms[index].querySelector("input");
  if (first) first.focus();
};

// 步骤条可点: 任意跳步回改 (跳步不会骗过门 —— 每步的真伪由各步的测试/
// 保存把门, 缺步漏配由应用门兜底弹回引导)
const stepsEl = document.getElementById("steps");
if (stepsEl) Array.from(stepsEl.children).forEach((li, i) => {
  if (forms[i]) li.addEventListener("click", () => showStep(i));
});

const finish = () => {
  forms.forEach(form => { form.hidden = true; });
  const steps = document.getElementById("steps");
  if (steps) Array.from(steps.children).forEach(li => li.classList.add("done"));
  document.getElementById("done").hidden = false;
  setTimeout(() => location.replace(doneUrl), 1200);
};

const advance = index => {
  if (index + 1 >= forms.length) { finish(); return; }
  showStep(index + 1);
  if (index + 1 === 1) prefillSettings();
};

// 查看密码: 明文 ↔ 密文, 图标同步切换 (SVG 的显隐必须动 style.display,
// hidden 属性对 SVG 不生效)
document.getElementById("eye").addEventListener("click", () => {
  const passInput = document.getElementById("su-pass");
  const show = passInput.type === "password";
  passInput.type = show ? "text" : "password";
  document.getElementById("eye").setAttribute(
    "aria-label", show ? "隐藏密码" : "显示密码");
  document.getElementById("eye-open").style.display = show ? "none" : "";
  document.getElementById("eye-slash").style.display = show ? "" : "none";
});

// 第一步: 建立第一个管理员。409 = 已建过 —— 步骤条可回跳后再提交就是
// 「这步早已完成」, 直接进下一步 (不再是别的设备抢跑, 无会话的续走会
// 在后面各步被登录拦下, 不用这里赶人)
forms[0].addEventListener("submit", async e => {
  e.preventDefault();
  const btn = forms[0].querySelector(".btn");
  const password = document.getElementById("su-pass").value;
  if (password !== document.getElementById("su-pass2").value) {
    fail(forms[0], "两次输入的密码不一致");
    return;
  }
  btn.disabled = true;
  try {
    const r = await fetch("/api/setup-admin", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: document.getElementById("su-name").value.trim(),
        password,
      }),
    });
    if (r.ok) { advance(0); return; }
    if (r.status === 409) { advance(0); return; }
    const d = await r.json().catch(() => null);
    fail(forms[0], (d && d.detail) || `创建失败 (HTTP ${r.status})`);
  } catch (_e) {
    fail(forms[0], "网络错误, 请重试");
  }
  btn.disabled = false;
});

// 第三步校验用: Web 服务 Key 必填 (足迹道路拟合要用), 已有现值 (掩码
// 回显过) 时留空=保持 —— 预填时更新
let webKeySet = false;

// 进入数据源步骤时拉现值: 输入框预填 (掩码/密码只给 placeholder, 留空=保持)
async function prefillSettings() {
  try {
    const r = await fetch("/tesla/api/settings", { cache: "no-store" });
    if (!r.ok) return;
    const d = await r.json();
    const t = d.tmdb || {};
    const fill = (id, value) => {
      const el = document.getElementById(id);
      if (el) el.value = value || "";
    };
    fill("tm-host", t.host); fill("tm-port", t.port);
    fill("tm-user", t.user); fill("tm-name", t.name);
    const tmPass = document.getElementById("tm-pass");
    if (tmPass) tmPass.placeholder = t.password_set ? "已设置, 留空保持" : "未设置";
    const a = d.amap || {};
    webKeySet = !!a.web_key_masked;
    const key = document.getElementById("amap-key");
    if (key) key.placeholder = a.key_masked ? `现值 ${a.key_masked}, 留空保持` : "未设置";
    const code = document.getElementById("amap-code");
    if (code) code.placeholder = a.security_code_masked ? `现值 ${a.security_code_masked}, 留空保持` : "未设置";
    const web = document.getElementById("amap-web");
    if (web) web.placeholder = a.web_key_masked ? `现值 ${a.web_key_masked}, 留空保持` : "未设置";
  } catch (_e) { /* 拉不到现值不挡流程, 空表单照填 */ }
}

// 起步步数: 管理员没建 → 从头; 建过 (中途退出的续走) → 从第一个缺口步
// 接着 (服务端只对「管理员在 + 有会话」的访客放行续走, 缺口步的表单一定
// 在场)。查不到状态就从第一步走 —— 保存接口会给出真实的缺口。
(async () => {
  let start = 0;
  try {
    const r = await fetch("/api/setup-status", { cache: "no-store" });
    const d = r.ok ? await r.json() : null;
    const missing = (d && d.missing) || [];
    if (!missing.includes("account"))
      start = missing.includes("teslamate") ? 1 : 2;
  } catch (_e) { /* 网络坏掉: 从第一步走 */ }
  showStep(Math.min(start, forms.length - 1));
  if (start >= 1) prefillSettings();
})();
