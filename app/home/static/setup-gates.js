// setup-gates.js — 首启引导的测试闸 (setup.js 后加载, 只有三步版页面引
// 用): 数据源/地图两步各带「测试」钮 —— 测通了「下一步/进入应用」才解
// 锁, 输入一改作废重测 (与设置页「只有测试正常才能保存」同一口径, 2026-
// 10-12 用户点名「要测试, 测试好之后才能下一步」)。
//   数据源: 候选送 /tesla/api/settings/test 服务端实测 (空字段回落现值),
//           不落库不换引擎;
//   地图:   Web 服务 Key 走服务端逆地理 (设置页同一端点), 地图 Key 走
//           适配层 iframe 探针 (空框回落现值, config 端点明文拿), 两把
//           都过才算过。
// 主按钮 = 保存 + 前进: 保存后端还会再实测一遍 TeslaMate (连不上整体回
// 滚可重试); 存败时候选没变 (闸还开着), 改完直接重试或重测。
/* global forms, fail, pass, webKeySet, advance, mapLib */
"use strict";

// 第二步 (有则存在): TeslaMate 连接
if (forms[1]) {
  const next2 = forms[1].querySelector("button[type=submit]");
  let tmOk = false;                       // 测试闸: 通过才开「下一步」
  const tmLock = () => { tmOk = false; next2.disabled = true; };
  for (const id of ["tm-host", "tm-port", "tm-user", "tm-pass", "tm-name"])
    document.getElementById(id).addEventListener("input", tmLock);

  document.getElementById("tm-test").addEventListener("click", async () => {
    const test = document.getElementById("tm-test");
    test.disabled = true;
    tmLock();                             // 重测从锁起跑
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
      const r = await fetch("/tesla/api/settings/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tmdb_host: v("tm-host"), tmdb_port: port,
          tmdb_user: v("tm-user"), tmdb_password: v("tm-pass"),
          tmdb_name: v("tm-name"),
        }),
      });
      const d = await r.json().catch(() => null);
      if (!r.ok || !d || !d.ok) {
        fail(forms[1], "测试未通过: " + ((d && d.detail) || `HTTP ${r.status}`));
        return;
      }
      tmOk = true;
      next2.disabled = false;
      pass(forms[1], "连接正常");
    } catch (_e) {
      fail(forms[1], "测试失败: 网络错误, 请重试");
    } finally {
      test.disabled = false;
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
      if (r.ok) { advance(1); return; }
      const d = await r.json().catch(() => null);
      fail(forms[1], (d && d.detail) || `保存失败 (HTTP ${r.status})`);
    } catch (_e) {
      fail(forms[1], "网络错误, 请重试");
    }
    next2.disabled = false;               // 存败候选没变, 闸还开着
  });
}

// 第三步 (有则存在): 高德两把 Key + 安全码 —— Web 服务 Key 必填 (足迹
// 道路拟合要用), 已有现值时留空=保持; 其余留空=保持现值
if (forms[2]) {
  const next3 = forms[2].querySelector("button[type=submit]");
  let amapOk = false;                     // 两把 Key 都测过才开「进入应用」
  const amapLock = () => { amapOk = false; next3.disabled = true; };
  for (const id of ["amap-key", "amap-code", "amap-web"])
    document.getElementById(id).addEventListener("input", amapLock);

  document.getElementById("amap-test").addEventListener("click", async () => {
    const test = document.getElementById("amap-test");
    test.disabled = true;
    amapLock();
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
      amapOk = true;
      next3.disabled = false;
      pass(forms[2], "地图 Key " + verdict + ", Web 服务 Key " + d.detail);
    } catch (err) {
      fail(forms[2], "测试未通过: " + err.message);
    } finally {
      test.disabled = false;
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
      if (r.ok) {
        /* Web 服务 key 存好立即踢一脚后台 worker: 历史道路开始构造,
           不用等空转轮 (60s); 足迹地图会盖「正在构造数据」蒙版报进度 */
        fetch("/tesla/map/api/roads/tick").catch(() => {});
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
