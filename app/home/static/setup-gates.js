// setup-gates.js — 首启引导的测试闸 (setup.js 后加载, 只有三表单版页面引
// 用): 数据源/地图两页各带「测试」钮 —— 测通了「下一步」才解锁, 输入一改
// 作废重测 (与设置页「只有测试正常才能保存」同一口径, 2026-10-12 用户点
// 名「要测试, 测试好之后才能下一步」); 「测试」钮本身也要必填项填全了才
// 亮, 灰着点不动 (同日用户点名「要填写全了才亮起按钮」)。
//   数据源: 候选送 /tesla/api/settings/test 服务端实测 (空字段回落现值),
//           不落库不换引擎; 密码还没存过时空着就拦 (空密码回落现值只会
//           换来一串没头没脑的连接报错, 2026-10-12 向导验证实测);
//   地图:   Web 服务 Key 走服务端逆地理 (设置页同一端点), 地图 Key 走
//           适配层 iframe 探针 (空框回落现值, config 端点明文拿), 两把
//           都过才算过。
//   2026-10-13 四页线性版: 各页「上一步」退回改值, 表单值原样留着 ——
//   没动就仍是测过的口径 (闸开着), 动了输入才作废重测 (输入监听在下面);
//   测过的状态跨页保留, 只有真改值才掉。
//   测试钮状态机 (同日二轮用户口径): 必填项填全才亮 → 测进行中灰着转
//   圈 (「测试中…」, 飞行锁 —— 中途改输入也不许重新点亮, 不像假死) →
//   收尾按「填全与否」恢复; 飞行中改了输入, 这轮结果作废 —— 不许拿旧
//   候选的结果解新输入的锁。
//   401 (没会话) 统一去处: 续走的访客会话丢了, 测试/保存全 401 —— 不点
//   破就只剩一句「HTTP 401」。管理员还没建 → 提示后送回第一页 (建号即
//   登录); 已建过 (会话丢了) → 登录后回来续走。
// 主按钮 = 保存 + 前进: 保存后端还会再实测一遍 TeslaMate (连不上整体回
// 滚可重试); 存败时候选没变 (闸还开着), 改完直接重试或重测。
/* global forms, fail, pass, webKeySet, tmPassSet, amapKeySet,
          advance, showStep, mapLib */
/* exported refreshTestButtons */   // setup.js 预填完来踢一脚 (重算明暗)
"use strict";

// 401 的去处 (现查 setup-status 分流, 该端点本就免登录)
const noSession = async form => {
  let noAdmin = true;
  try {
    const r = await fetch("/api/setup-status", { cache: "no-store" });
    const d = r.ok ? await r.json() : null;
    noAdmin = !d || (d.missing || []).includes("account");
  } catch (_e) { /* 查不到就当没建过管理员: 回第一步 */}
  if (noAdmin) {
    fail(form, "还没有登录会话 —— 请先完成「管理员」页 (建号即登录), 再回来测");
    showStep(0);
  } else {
    location.href = "/login?next=/setup";
  }
};

// 「测试」钮的明暗: 必填项填全才亮, 缺一样就灰。口径与各步「测试」内部
// 校验对齐 —— 数据源步要 地址/用户/库名 (+ 没存过密码时的密码), 端口
// 留空 = 默认 5432 不算缺; 地图步要两把 Key (框里有或存过现值都算),
// 安全码不算缺 (没绑安全码的 Key 也测得通)。进门先按现状定一遍, 输入
// 一改、测试收尾、setup.js 预填完都会来重算 (refreshTestButtons)。
const tmReady = () => {
  const v = id => document.getElementById(id).value.trim();
  return !!(v("tm-host") && v("tm-user") && v("tm-name")
            && (v("tm-pass") || tmPassSet));
};
const amapReady = () => {
  const v = id => document.getElementById(id).value.trim();
  return !!((v("amap-key") || amapKeySet) && (v("amap-web") || webKeySet));
};
// 测试进行中 (飞行锁): 测没跑完测试钮就灰着 —— 中途改输入触发的重算不
// 许把钮重新点亮, 收尾才恢复 (2026-10-13 口径)
let tmTesting = false;
let amapTesting = false;
const refreshTestButtons = () => {
  const t2 = document.getElementById("tm-test");
  if (t2) t2.disabled = tmTesting || !tmReady();
  const t3 = document.getElementById("amap-test");
  if (t3) t3.disabled = amapTesting || !amapReady();
};
refreshTestButtons();   // 进门先按现状定 (没填全 = 灰)

// 第二页 (有则存在): TeslaMate 连接
if (forms[1]) {
  const next2 = forms[1].querySelector("button[type=submit]");
  let tmOk = false;                       // 测试闸: 通过才开「下一步」
  const tmLock = () => { tmOk = false; next2.disabled = true; };
  // 「上一步」退回管理员页: 表单值原样留着, 没动就仍是测过的口径
  document.getElementById("back2").addEventListener("click", () => showStep(0));
  // 输入一改: 下一步作废重测 + 测试钮按「填全没有」重定明暗 + 记一笔
  // (测试飞行中改的, 那轮结果作废)
  let tmEdits = 0;
  for (const id of ["tm-host", "tm-port", "tm-user", "tm-pass", "tm-name"])
    document.getElementById(id).addEventListener("input", () => {
      tmEdits += 1;
      tmLock();
      refreshTestButtons();
    });

  document.getElementById("tm-test").addEventListener("click", async () => {
    const test = document.getElementById("tm-test");
    const label = test.textContent;       // 飞行中换「测试中…」转圈, 不像假死
    tmTesting = true;                     // 飞行锁: 测进行中不许再点
    test.classList.add("testing");
    test.textContent = "测试中…";
    test.disabled = true;
    tmLock();                             // 重测从锁起跑
    const mark = tmEdits;                 // 飞行中有新改动, 这轮结果作废
    try {
      const v = id => document.getElementById(id).value.trim();
      if (!v("tm-host")) { fail(forms[1], "请先填地址"); return; }
      // 端口填了就得是 1~65535 的数字 —— 字母混进去后端报一长串连接串
      // 报错, 关在前面报得清楚 (留空 = 默认 5432, 不拦)
      const port = v("tm-port");
      if (port && (!/^\d+$/.test(port) || +port < 1 || +port > 65535)) {
        fail(forms[1], "端口请填 1~65535 的数字");
        return;
      }
      // 密码还没存过 (预填的 placeholder 是「未设置」) 就不许空着测 ——
      // 空密码回落现值只会换来服务端一串连接报错, 当场拦下报人话
      if (!v("tm-pass") && !tmPassSet) {
        fail(forms[1], "数据库密码还没填 —— 密码框空着, 此前也没存过密码");
        return;
      }
      const r = await fetch("/tesla/api/settings/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tmdb_host: v("tm-host"), tmdb_port: port,
          tmdb_user: v("tm-user"), tmdb_password: v("tm-pass"),
          tmdb_name: v("tm-name"),
        }),
      });
      if (r.status === 401) { await noSession(forms[1]); return; }
      const d = await r.json().catch(() => null);
      if (!r.ok || !d || !d.ok) {
        fail(forms[1], "测试未通过: " + ((d && d.detail) || `HTTP ${r.status}`));
        return;
      }
      if (tmEdits !== mark) return;       // 中途改过输入: 作废, 闸保持锁
      tmOk = true;
      next2.disabled = false;
      pass(forms[1], "连接正常");
    } catch (_e) {
      fail(forms[1], "测试失败: 网络错误, 请重试");
    } finally {
      tmTesting = false;
      test.classList.remove("testing");
      test.textContent = label;
      refreshTestButtons();   // 收尾恢复: 按填全与否 (中途清空了 = 保持灰)
    }
  });

  forms[1].addEventListener("submit", async e => {
    e.preventDefault();
    if (!tmOk) return;                    // 闸锁着进不来, 兜底
    next2.disabled = true;
    try {
      const v = id => document.getElementById(id).value.trim();
      const r = await fetch("/tesla/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tmdb_host: v("tm-host"), tmdb_port: v("tm-port"),
          tmdb_user: v("tm-user"), tmdb_password: v("tm-pass"),
          tmdb_name: v("tm-name"),
        }),
      });
      if (r.status === 401) { await noSession(forms[1]); return; }
      // 成功也要解锁: 存好即测过, 回到本页 (上一步退回) 闸保持开着 ——
      // 飞行锁只在存败时留着 (候选没变, 改完直接重试或重测)
      if (r.ok) { next2.disabled = false; advance(1); return; }
      const d = await r.json().catch(() => null);
      fail(forms[1], (d && d.detail) || `保存失败 (HTTP ${r.status})`);
    } catch (_e) {
      fail(forms[1], "网络错误, 请重试");
    }
    next2.disabled = false;               // 存败候选没变, 闸还开着
  });
}

// 第三页 (有则存在): 高德两把 Key + 安全码 —— Web 服务 Key 必填 (足迹
// 道路拟合要用), 已有现值时留空=保持; 其余留空=保持现值
if (forms[2]) {
  const next3 = forms[2].querySelector("button[type=submit]");
  let amapOk = false;                     // 两把 Key 都测过才开「下一步」
  const amapLock = () => { amapOk = false; next3.disabled = true; };
  // 「上一步」退回数据源页改值: 改了要重测才能再往下 (没动闸保持开着)
  document.getElementById("back3").addEventListener("click", () => showStep(1));
  // 输入一改: 下一步作废重测 + 测试钮按「填全没有」重定明暗 + 记一笔
  // (测试飞行中改的, 那轮结果作废)
  let amapEdits = 0;
  for (const id of ["amap-key", "amap-code", "amap-web"])
    document.getElementById(id).addEventListener("input", () => {
      amapEdits += 1;
      amapLock();
      refreshTestButtons();
    });

  document.getElementById("amap-test").addEventListener("click", async () => {
    const test = document.getElementById("amap-test");
    const label = test.textContent;       // 飞行中换「测试中…」转圈, 不像假死
    amapTesting = true;                   // 飞行锁: 测进行中不许再点
    test.classList.add("testing");
    test.textContent = "测试中…";
    test.disabled = true;
    amapLock();
    const mark = amapEdits;               // 飞行中有新改动, 这轮结果作废
    try {
      const v = id => document.getElementById(id).value.trim();
      if (!v("amap-web") && !webKeySet) {
        fail(forms[2], "Web 服务 Key 必填: 足迹道路拟合要用");
        return;
      }
      const keyRE = /^[0-9a-zA-Z]{32}$/;
      for (const [id, lb] of [["amap-key", "地图 Key"], ["amap-code", "安全码"],
                              ["amap-web", "Web 服务 Key"]]) {
        if (v(id) && !keyRE.test(v(id))) {
          fail(forms[2], lb + " 应为 32 位字母数字");
          return;
        }
      }
      // Web 服务 Key: 框里空 = 测现值 (服务端), 有值测候选
      const r = await fetch("/tesla/map/api/web-key-test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: v("amap-web") }),
      });
      if (r.status === 401) { await noSession(forms[2]); return; }
      const d = await r.json().catch(() => null);
      if (!r.ok || !d || !d.ok) {
        fail(forms[2], "Web 服务 Key 测试未通过: " +
             ((d && d.detail) || `HTTP ${r.status}`));
        return;
      }
      if (typeof mapLib === "undefined") {
        fail(forms[2], "地图引擎没加载出来, 刷新页面重试");
        return;
      }
      // 地图 Key + 安全码: 空框回落现值 (config 端点明文拿, 引擎装载走
      // 的就是它), 独立 iframe 装候选引擎逆地理验真伪 (探针住适配层,
      // 与设置页「测试」同一支)
      let key = v("amap-key");
      let code = document.getElementById("amap-code").value.trim();
      if (!key || !code) {
        const cfg = await fetch("/tesla/map/api/config?_=" + Date.now(),
                                { cache: "no-store" });
        const cd = cfg.ok ? await cfg.json().catch(() => null) : null;
        key = key || (cd && cd.amap_key) || "";
        code = code || (cd && cd.security_code) || "";
      }
      if (!key) { fail(forms[2], "地图 Key 还没填"); return; }
      const verdict = await mapLib.probeKey(key, code);
      if (amapEdits !== mark) return;     // 中途改过输入: 作废, 闸保持锁
      amapOk = true;
      next3.disabled = false;
      pass(forms[2], "地图 Key " + verdict + ", Web 服务 Key " + d.detail);
    } catch (err) {
      fail(forms[2], "测试未通过: " + err.message);
    } finally {
      amapTesting = false;
      test.classList.remove("testing");
      test.textContent = label;
      refreshTestButtons();   // 收尾恢复: 按填全与否 (中途清空了 = 保持灰)
    }
  });

  forms[2].addEventListener("submit", async e => {
    e.preventDefault();
    if (!amapOk) return;
    next3.disabled = true;
    try {
      const v = id => document.getElementById(id).value.trim();
      const r = await fetch("/tesla/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          amap_key: v("amap-key"), amap_security_code: v("amap-code"),
          amap_web_key: v("amap-web"),
        }),
      });
      if (r.status === 401) { await noSession(forms[2]); return; }
      if (r.ok) {
        /* Web 服务 key 存好立即踢一脚后台 worker: 历史道路开始构造,
           不用等空转轮 (60s); 足迹地图会盖「正在构造数据」蒙版报进度 */
        fetch("/tesla/map/api/roads/tick").catch(() => {});
        next3.disabled = false;          // 同 next2: 存好即测过, 闸保持开
        advance(2); return;
      }
      const d = await r.json().catch(() => null);
      fail(forms[2], (d && d.detail) || `保存失败 (HTTP ${r.status})`);
    } catch (_e) {
      fail(forms[2], "网络错误, 请重试");
    }
    next3.disabled = false;
  });
}
