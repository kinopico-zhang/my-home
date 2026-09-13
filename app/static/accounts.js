// accounts.js — 管理员账号管理: 用户列表 + 邀请签发/复制/撤销 (非管理员只看到提示)
"use strict";
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g,
  c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

let toastTimer = null;
function toast(msg, isErr) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.toggle("err", !!isErr);
  el.hidden = false;
  requestAnimationFrame(() => el.classList.add("on"));
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    el.classList.remove("on");
    setTimeout(() => { el.hidden = true; }, 250);
  }, isErr ? 3500 : 1800);
}

async function api(path, opts) {
  const r = await fetch(path, Object.assign({ cache: "no-store" }, opts));
  if (r.status === 401) { location.replace("/tesla/login"); throw new Error("未登录"); }
  const body = await r.json().catch(() => null);
  if (!r.ok) {
    const err = new Error((body && body.detail) || `${r.status} ${r.statusText}`);
    err.status = r.status;
    throw err;
  }
  return body;
}

function fmtDT(iso) {          // 本地时间串 (服务端给的就是本地时刻, 带时区偏移)
  const d = new Date(iso);
  if (isNaN(d)) return "";
  const p = n => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ` +
         `${p(d.getHours())}:${p(d.getMinutes())}`;
}

// 邀请状态: 撤销 > 已用 > 过期 > 有效 (顺序即优先级)
function invState(inv) {
  const now = Date.now();
  if (inv.revoked) return { cls: "revoked", text: "已撤销" };
  if (inv.used_at) return { cls: "used", text: "已注册" };
  if (new Date(inv.expires_at).getTime() < now) return { cls: "expired", text: "已过期" };
  return { cls: "ok", text: "有效" };
}

function inviteLink(token) {
  return `${location.origin}/tesla/register?invite=${encodeURIComponent(token)}`;
}

// HTTP 环境没有异步剪贴板 API: 退化用隐藏 textarea + execCommand (iOS Safari 两路都通)
async function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    try { await navigator.clipboard.writeText(text); return true; } catch (_e) { /* 落回 */ }
  }
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.cssText = "position:fixed;top:-999px;opacity:0";
  document.body.appendChild(ta);
  ta.contentEditable = "true";   // iOS 需要可编辑才有键盘行为
  ta.readOnly = false;
  const range = document.createRange();
  range.selectNodeContents(ta);
  const sel = getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
  ta.setSelectionRange(0, text.length);
  const ok = document.execCommand("copy");
  sel.removeAllRanges();
  ta.remove();
  return ok;
}

/* ---------- 载入 ---------- */
async function loadUsers() {
  const users = await api("/tesla/accounts/api/users");
  $("#user-list").innerHTML = users.map(u =>
    `<div class="usr-row">` +
    `<div class="usr-name">${esc(u.name)}${u.is_admin ? '<span class="usr-badge">管理员</span>' : ""}</div>` +
    `<div class="usr-meta">${esc(fmtDT(u.created_at))}</div></div>`).join("");
}

function renderInvites(invites) {
  $("#invite-empty").hidden = invites.length > 0;
  $("#invite-list").innerHTML = invites.map(inv => {
    const st = invState(inv);
    const dead = inv.revoked || inv.used_at;
    return `<div class="inv-card" data-token="${esc(inv.token)}">` +
      `<div class="inv-top">` +
      `<div class="inv-date">${esc(fmtDT(inv.created_at))} 签发 · ${esc(fmtDT(inv.expires_at))} 到期</div>` +
      `<span class="inv-state ${st.cls}">${st.text}</span></div>` +
      `<div class="inv-acts">` +
      `<button class="copy" data-act="copy">复制链接</button>` +
      (dead ? "" : `<button class="revoke" data-act="revoke">撤销</button>`) +
      `</div></div>`;
  }).join("");
}

async function loadInvites() {
  renderInvites(await api("/tesla/accounts/api/invitations"));
}

async function loadAll() {
  try {
    await Promise.all([loadUsers(), loadInvites()]);
  } catch (err) {      // 403 = 普通用户: 只留提示卡
    if (err.status === 403) {
      $("#denied").hidden = false;
      return;
    }
    throw err;
  }
  $("#users-card").hidden = false;
  $("#invite-card").hidden = false;
  $("#list-card").hidden = false;
}

/* ---------- 邀请签发 ---------- */
let inviteDays = 1;
$("#days-row").addEventListener("click", e => {
  const btn = e.target.closest("button[data-days]");
  if (!btn) return;
  inviteDays = +btn.dataset.days;
  document.querySelectorAll("#days-row button").forEach(b =>
    b.classList.toggle("on", b === btn));
});

$("#invite-make").addEventListener("click", async () => {
  const btn = $("#invite-make");
  btn.disabled = true;
  try {
    const made = await api("/tesla/accounts/api/invitations", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ days: inviteDays }),
    });
    const link = inviteLink(made.token);
    const copied = await copyText(link);
    await loadInvites();
    toast(copied ? `链接已复制, ${fmtDT(made.expires_at)} 前有效`
                 : `生成成功 (复制失败, 请点列表里的复制)`);
  } catch (err) {
    toast(`生成失败: ${err.message}`, true);
  } finally {
    btn.disabled = false;
  }
});

/* ---------- 邀请列表操作 (事件委托; innerHTML 脱链坑见 index.js) ---------- */
$("#invite-list").addEventListener("click", async e => {
  const t = e.target;
  if (!(t instanceof Element) || !t.isConnected) return;   // 重渲染脱链防误触
  const card = t.closest(".inv-card");
  if (!card) return;
  const token = card.dataset.token;
  try {
    if (t.closest(".copy")) {
      const ok = await copyText(inviteLink(token));
      toast(ok ? "链接已复制" : "复制失败, 请长按链接手动复制", !ok);
    } else if (t.closest(".revoke")) {
      if (!confirm("撤销这个邀请? 未注册前撤销后不能再用。")) return;
      await api(`/tesla/accounts/api/invitations/${encodeURIComponent(token)}`,
        { method: "DELETE" });
      await loadInvites();
      toast("已撤销");
    }
  } catch (err) {
    toast(`操作失败: ${err.message}`, true);
  }
});

/* ---------- 顶栏刷新 ---------- */
$("#refresh-btn").addEventListener("click", async () => {
  const btn = $("#refresh-btn");
  btn.classList.add("busy");
  if (!$("#denied").hidden) {       // 非管理员: 无可刷新数据
    btn.classList.remove("busy");
    return;
  }
  try { await loadAll(); } catch (err) { toast(`刷新失败: ${err.message}`, true); }
  btn.classList.remove("busy");
});

$("#logout").addEventListener("click", async () => {
  await fetch("/tesla/api/logout", { method: "POST" });
  location.replace("/tesla/login");
});

loadAll().catch(err => toast(`加载失败: ${err.message}`, true));
