// setup.js — 首启引导: 四页全走完才能进应用, 线性前进不许跳 (2026-10-13
// 用户口径): 只有「上一步/下一步」, 步骤条只展示进度不可点。第一页建管理
// 员 (注册即登录, 后续接口都带会话); 第二/三页配 TeslaMate 与高德两把
// Key (一步变体 My Money / My Music 建完即完成); 第四页把三页所填汇成
// 一张过目单 (敏感信息只给掩码/****), 看准了「进入应用」显式跳转。起步
// 页数由 /api/setup-status 的 missing 决定 —— 中途退出的续走 (管理员已
// (管理员已在, 从缺口页接着); 完成跳转读 body 的 data-done; 页面按 DOM
// 现状收集, 同一份脚本服务两种页面。第二/三页的「测试闸」(测通了下一
// 步才解锁, 测试钮要填全才亮) 在 setup-gates.js, 一步变体不加载那半边。
/* exported pass, webKeySet, showStep, tmPassSet, amapKeySet */
/* global refreshTestButtons */   // setup-gates 的; 预填完重算测试钮明暗
"use strict";
const card = document.getElementById("card");
const doneUrl = document.body.dataset.done || "/";
const forms = ["form1", "form2", "form3"]
  .map(id => document.getElementById(id)).filter(Boolean);
const donePage = document.getElementById("done");

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

// 展示第 index 页: 0..forms.length-1 是表单页, forms.length = 完成面板
// (第四页)。步骤条只跟着换 active/done, 不接线点击 —— 跳步退役
const showStep = index => {
  forms.forEach((form, i) => { form.hidden = i !== index; });
  if (donePage) donePage.hidden = index !== forms.length;
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

const advance = index => {
  showStep(Math.min(index + 1, forms.length));
  if (index + 1 === 1) prefillSettings();
  if (index + 1 === forms.length) fillDoneSummary();
};

// 第四页「进入应用」: 前三页一路真存过来, 汇总过目完 (fillDoneSummary),
// 这里只跳转 (读 data-done)
if (donePage) document.getElementById("enter").addEventListener("click", () => {
  location.replace(doneUrl);
});

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

// 第一页: 建立第一个管理员。下一步 (真提交钮) = 三个框填全才亮, 点击走
// 表单原生校验 (required/minlength 的气泡) 后建号前进。管理员已建 (续走
// 回看 / 409 = 这页早已完成) 时表单转 noValidate + 输入框锁死, 空框直进
// 不重交 —— 建号是首启唯一入口, 已建过没有可改的值
let accountDone = false;
const next1 = forms[0].querySelector("#next1");
const markAccountDone = () => {
  accountDone = true;
  forms[0].noValidate = true;   // 回看直进: 原生 required 不再拦空框
  next1.disabled = false;
  for (const id of ["su-name", "su-pass", "su-pass2"])
    document.getElementById(id).disabled = true;   // 此页锁死, 没有可改的值
};
const next1Ready = () => {
  if (accountDone) return true;
  const v = id => document.getElementById(id).value.trim();
  return !!(v("su-name") && v("su-pass") && v("su-pass2"));
};
for (const id of ["su-name", "su-pass", "su-pass2"])
  document.getElementById(id).addEventListener("input", () => {
    if (!accountDone) next1.disabled = !next1Ready();
  });

// 点击/回车都落这里: 建号 (200) 或早已建过 (409) 都前进
forms[0].addEventListener("submit", async e => {
  e.preventDefault();
  if (accountDone) { advance(0); return; }
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
    if (r.ok) { markAccountDone(); advance(0); return; }
    if (r.status === 409) { markAccountDone(); advance(0); return; }
    const d = await r.json().catch(() => null);
    fail(forms[0], (d && d.detail) || `创建失败 (HTTP ${r.status})`);
  } catch (_e) {
    fail(forms[0], "网络错误, 请重试");
  }
  btn.disabled = false;
});

// 第三页 (地图) 校验用: Web 服务 Key 必填 (足迹道路拟合要用), 已有现值
// (掩码回显过) 时留空=保持 —— 预填时更新
let webKeySet = false;
// 数据源页校验用 (setup-gates 的快拦): 数据库密码还没存过时必填, 存过
// 才许留空=保持 —— 预填时更新。不拦的话空密码回落现值, 服务端只回一串
// 长连接报错, 没头没脑 (2026-10-12 向导验证实测)
let tmPassSet = false;
// 地图页测试钮点亮用 (setup-gates 的 ready3): 地图 Key 存过现值时空框
// 也算填全 —— 预填时更新 (与 webKeySet 同款)
let amapKeySet = false;

// 进入数据源步骤时拉现值 —— 只为占位提示与「留空=保持」的标志, 不预
// 填值 (2026-10-13 用户点名退役: 预填的地址来自 env / docker 定位, 每
// 处部署都不一样, 看着像权威值其实是猜的 —— 框留白, 用户自己填)
async function prefillSettings() {
  try {
    const r = await fetch("/tesla/api/settings", { cache: "no-store" });
    if (!r.ok) return;
    const d = await r.json();
    const t = d.tmdb || {};
    const tmPass = document.getElementById("tm-pass");
    if (tmPass) tmPass.placeholder = t.password_set ? "已设置, 留空保持" : "未设置";
    tmPassSet = !!t.password_set;   // setup-gates 快拦用 (没存过密码不许空着测)
    const a = d.amap || {};
    webKeySet = !!a.web_key_masked;
    amapKeySet = !!a.key_masked;   // setup-gates 测试钮点亮用 (存过现值空框也算填全)
    const key = document.getElementById("amap-key");
    if (key) key.placeholder = a.key_masked ? `现值 ${a.key_masked}, 留空保持` : "未设置";
    const code = document.getElementById("amap-code");
    if (code) code.placeholder = a.security_code_masked ? `现值 ${a.security_code_masked}, 留空保持` : "未设置";
    const web = document.getElementById("amap-web");
    if (web) web.placeholder = a.web_key_masked ? `现值 ${a.web_key_masked}, 留空保持` : "未设置";
  } catch (_e) { /* 拉不到现值不挡流程, 空表单照填 */ }
  // 预填完按「填全没有」重算测试钮明暗 (拉挂了也算一遍: 空表单 → 保持灰)
  if (typeof refreshTestButtons === "function") refreshTestButtons();
}

// 进完成页时填汇总: 三页所填在此过目一遍再进应用 (2026-10-13 口径)。
// 敏感信息不回显 —— 密码一律 ****, Key/安全码走设置端点的半遮掩码
// (ab12****yz89, 识别够了完整值不外泄); 拉不到现值就整块不露脸, 完
// 成面板只剩标题与按钮
async function fillDoneSummary() {
  const dl = document.getElementById("done-summary");
  if (!dl) return;
  const [me, st] = await Promise.all([
    fetch("/api/me", { cache: "no-store" })
      .then(r => r.ok ? r.json() : null),
    fetch("/tesla/api/settings", { cache: "no-store" })
      .then(r => r.ok ? r.json() : null),
  ]).catch(() => [null, null]);
  if (!st) return;
  const group = title => {
    const g = document.createElement("div");
    g.className = "ds-group";
    const head = document.createElement("div");
    head.className = "ds-title";
    head.textContent = title;
    g.append(head);
    dl.append(g);
    return g;
  };
  const row = (parent, label, value) => {
    const r = document.createElement("div");
    r.className = "ds-row";
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.textContent = value;
    r.append(dt, dd);
    parent.append(r);
  };
  dl.replaceChildren();
  const t = st.tmdb || {};
  const a = st.amap || {};
  const admin = group("管理员");
  row(admin, "账号", (me && me.name) || "—");
  row(admin, "密码", "****");
  const tm = group("数据源");
  row(tm, "地址", (t.host || "—") + (t.port ? ":" + t.port : ""));
  row(tm, "用户", t.user || "—");
  row(tm, "密码", t.password_set ? "****" : "未设置");
  row(tm, "库名", t.name || "—");
  const map = group("地图");
  row(map, "地图 Key", a.key_masked || "未设置");
  row(map, "安全码", a.security_code_masked || "未设置");
  row(map, "Web 服务 Key", a.web_key_masked || "未设置");
  dl.hidden = false;
}

// 起步页数: 管理员没建 → 从头; 建过 (中途退出的续走) → 从第一个缺口页
// 接着 (服务端只对「管理员在 + 有会话」的访客放行续走, 缺口页的表单一定
// 在场)。查不到状态就从第一页走 —— 保存接口会给出真实的缺口。
(async () => {
  let start = 0;
  try {
    const r = await fetch("/api/setup-status", { cache: "no-store" });
    const d = r.ok ? await r.json() : null;
    const missing = (d && d.missing) || [];
    if (!missing.includes("account")) {
      markAccountDone();       // 续走: 管理员页只作回看
      start = missing.includes("teslamate") ? 1 : 2;
    }
  } catch (_e) { /* 网络坏掉: 从第一页走 */ }
  showStep(Math.min(start, forms.length - 1));
  if (start >= 1) prefillSettings();
})();
