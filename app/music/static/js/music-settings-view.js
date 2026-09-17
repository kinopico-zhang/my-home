// music-settings-view — My Music 设置视图: 曲库路径/歌词源/蜂窝账单/重新扫描等。
// 拆自 music.js (结构化重构), 1.8.0 起住推入层 (菜单「设置」进来), 渲染目标由调用方给。
"use strict";
/* global $, checkScanStatus, escapeHTML, fetchJSON, formatBytes, navigate, toast,
          userRescanPending: writable */
/* exported renderSettingsView, userRescanPending */

// ------------------------------------------------------------ 设置页
// 账号 (谁登录/退出) + 曲库路径 / 联网补歌词开关与地址 / 蜂窝流量月账 +
// 统计和更新日志入口 + 重新扫描曲库 —— 1.7.0 起品牌菜单的职能全在这页,
// 1.8.0 起从页签改由菜单键进。谁登录都能看;
// 改 (路径/开关/地址/保存) 只有管理员 —— 普通账号进来是只读的。
// 曲库路径改了服务器会立刻重新扫描整个曲库。

async function renderSettingsView(target) {
  target.innerHTML = '<div class="pane-title">设置</div><div id="settings-body">'
    + '<p class="stat-empty">加载中…</p></div>';
  const body = $("#settings-body");
  let settings;
  try {
    settings = await fetchJSON("/music/api/settings");
  } catch (error) {
    body.innerHTML = `<p class="stat-empty">设置拿不到: ${escapeHTML(error.message)}</p>`;
    return;
  }
  const me = await fetchJSON("/api/me").catch(() => null);
  const editable = !!(me && me.is_admin);        // 管理员才出得起保存钮
  const lock = editable ? "" : " disabled";
  body.innerHTML = `
    <div class="settings-block">
      <div class="settings-title">账号</div>
      ${me && me.name ? `<div class="settings-user"><svg viewBox="0 0 24 24" width="17" height="17" aria-hidden="true"><path d="M12 11.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM5.5 20a6.5 6.5 0 0 1 13 0" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg><span>${escapeHTML(me.name)}</span>${me.is_admin ? "<em>管理员</em>" : ""}</div>` : ""}
      <button class="settings-row logout" id="set-logout">退出登录</button>
    </div>
    <div class="settings-block">
      <div class="settings-title">音乐库</div>
      <div class="settings-field">
        <label for="set-dir">曲库路径</label>
        <input id="set-dir" spellcheck="false" autocomplete="off"${lock}
               placeholder="${escapeHTML(settings.music_directory_default)}"
               value="${escapeHTML(settings.music_directory)}">
        <small>服务器上存放音乐的目录 (留空用默认); 改了会立刻重新扫描整个曲库</small>
      </div>
      <button class="settings-row" id="set-rescan"
              title="增量重扫曲库 (没变的文件只 stat 不读标签)">重新扫描曲库</button>
    </div>
    <div class="settings-block">
      <div class="settings-title">联网补歌词</div>
      <div class="settings-field switch-row">
        <label>库里没歌词时上网求一遍</label>
        <button class="switch${settings.lyrics_api_enabled ? " on" : ""}"
                id="set-lyrics-on" role="switch"${lock}
                aria-checked="${settings.lyrics_api_enabled}"><i></i></button>
      </div>
      <div class="settings-field">
        <label for="set-lyrics-base">歌词 API 地址</label>
        <input id="set-lyrics-base" spellcheck="false" autocomplete="off" inputmode="url"${lock}
               placeholder="${escapeHTML(settings.lyrics_api_default)}"
               value="${escapeHTML(settings.lyrics_api_base)}">
        <small>LRCLIB 兼容接口; 求到的歌词会写回曲库, 离线也能看</small>
      </div>
    </div>
    ${editable
      ? `<div class="set-save-row"><button class="action primary" id="set-save">保存设置</button></div>`
      : '<p class="settings-note">仅管理员可修改设置, 普通账号只读。</p>'}
    <div class="settings-block">
      <div class="settings-title">蜂窝流量 · 听歌消耗</div>
      ${settings.cellular_months.length
        ? settings.cellular_months.map(monthRowHTML).join("")
        : '<p class="stat-empty">还没有记录</p>'}
      <small class="settings-note">能认出蜂窝网络的浏览器 (如安卓 Chrome) 会自动按月上报;
        iPhone 的 Safari 认不出网络类型, 那部分记不上。</small>
    </div>
    <div class="settings-block">
      <div class="settings-title">更多</div>
      <button class="settings-row" data-set-nav="stats">统计</button>
      <button class="settings-row" data-set-nav="changelog">更新日志</button>
    </div>`;
  const toggle = $("#set-lyrics-on");
  for (const row of body.querySelectorAll("[data-set-nav]")) {
    row.addEventListener("click", () => navigate(row.dataset.setNav));
  }
  $("#set-rescan").addEventListener("click", async () => {
    try {
      await fetchJSON("/music/api/rescan", { method: "POST" });
      userRescanPending = true;      // 这轮收尾要出提示 (后台自动扫的不出)
      toast("开始扫描曲库");
      checkScanStatus();
    } catch (error) {
      toast(error.message);
    }
  });
  $("#set-logout").addEventListener("click", async () => {
    try { await fetch("/music/api/logout", { method: "POST" }); }
    catch (_error) { /* 清 cookie 失败也照样走 */ }
    location.href = "/music/login";
  });
  if (editable) {
    toggle.addEventListener("click", () => {
      const on = toggle.getAttribute("aria-checked") !== "true";
      toggle.setAttribute("aria-checked", String(on));
      toggle.classList.toggle("on", on);
    });
    $("#set-save").addEventListener("click", async () => {
      const button = $("#set-save");
      button.disabled = true;
      try {
        await fetchJSON("/music/api/settings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            music_directory: $("#set-dir").value.trim(),
            lyrics_api_enabled: toggle.getAttribute("aria-checked") === "true",
            lyrics_api_base: $("#set-lyrics-base").value.trim(),
          }),
        });
        toast("设置已保存");
        checkScanStatus();      // 曲库路径换过的话, 扫描已起: 进度条接上
      } catch (error) {
        toast(`没保存上: ${error.message}`);
      } finally {
        button.disabled = false;
      }
    });
  }
}

/** 流量月账一行: "2026年9月" + 友好字节数。 */
function monthRowHTML(month) {
  const [year, monthNumber] = month.month.split("-");
  return `
    <div class="month-row">
      <span>${year}年${Number(monthNumber)}月</span>
      <b>${formatBytes(month.bytes)}</b>
    </div>`;
}

