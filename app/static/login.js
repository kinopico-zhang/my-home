// login.js — 由 login.html 内联脚本抽出 (位置/顺序/语义不变), 供 lint 与测试
"use strict";
const form = document.getElementById("form");
const errEl = document.getElementById("err");
const btn = document.getElementById("btn");
const card = document.getElementById("card");
const passInput = document.getElementById("pass");
const eyeBtn = document.getElementById("eye");

// 查看密码: 明文 ↔ 密文, 图标同步切换
eyeBtn.addEventListener("click", () => {
  const show = passInput.type === "password";
  passInput.type = show ? "text" : "password";
  eyeBtn.setAttribute("aria-label", show ? "隐藏密码" : "显示密码");
  document.getElementById("eye-open").hidden = show;
  document.getElementById("eye-slash").hidden = !show;
});

form.addEventListener("submit", async e => {
  e.preventDefault();
  errEl.textContent = "";
  btn.disabled = true;
  try {
    const r = await fetch("/tesla/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user: document.getElementById("user").value,
        password: document.getElementById("pass").value,
      }),
    });
    if (r.ok) {
      // 回上次停留的页面 (主屏 App 里会话过期重新登录 / Safari 书签进来都适用)
      var last = null;
      try { last = localStorage.getItem("mytesla-last-page"); } catch (e) {}
      location.replace(last && /^\/tesla\/(charging|map|trips|live|settings)(\?|$)/.test(last)
        ? last : "/tesla/charging");
      return;
    }
    // 优先展示后端给出的原因 (账号密码错误 / 尝试次数过多…), 兜底按状态码
    const d = await r.json().catch(() => null);
    let msg;
    if (d && d.detail) msg = String(d.detail);
    else if (r.status === 401) msg = "账号或密码错误";
    else if (r.status === 429) msg = "尝试次数过多, 请稍后再试";
    else if (r.status === 404) msg = "登录接口不存在, 服务可能未更新";
    else msg = `登录失败 (HTTP ${r.status})`;
    errEl.textContent = msg;
    card.classList.remove("shake");
    void card.offsetWidth;
    card.classList.add("shake");
  } catch (e) {
    errEl.textContent = "网络错误, 请重试";
  }
  btn.disabled = false;
});
document.getElementById("user").focus();
