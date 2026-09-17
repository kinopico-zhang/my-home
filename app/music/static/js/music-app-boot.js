// music-app-boot — My Music 开局: 绑全局事件, 旧深链消化一次, 回到上次停的页。
// 拆自 music.js (结构化重构: 代码逐字节未动, 经典脚本按 music.html 里的顺序加载, 跨模块引用走全局)。
"use strict";
/* global bindGlobalEvents, navigate, parseRoute, readLastRoute */

bindGlobalEvents();
// 旧深链只消化一次 (#playlist/5 之类 → 按它开局), 随即把 URL 洗成光杆
// /music —— 之后全程一个地址, 应用内导航不再碰浏览器历史 (系统侧滑/
// 返回键没有可退的条目, 整页截图滑走绝迹; 用户点名)。
// 1.8.3 开局回跳 (用户点名「打开 app 自动回最后一个页面」): 没有旧深链
// 就读上次停的页; 没记过 (= 头一回) 回主页播放列表。
const legacyHash = location.hash.replace(/^#\/?/, "");
const lastRoute = readLastRoute();
const legacyTarget = legacyHash && parseRoute(legacyHash) ? legacyHash
  : (lastRoute && parseRoute(lastRoute) ? lastRoute : "home");
history.replaceState(null, "", location.pathname + location.search);
navigate(legacyTarget);
