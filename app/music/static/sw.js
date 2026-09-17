// sw.js — My Music 的 Service Worker (scope /music):
//  - 曲目音频流: 已下载的从 Cache API 直接回 (拖进度条的 Range 请求切 206),
//    没下载的原样走网络;
//  - 封面图: 缓存优先 —— 后端虽已发长缓存头, iOS 的 HTTP 缓存容易被系统
//    整体清掉, 50k 曲库一刷列表就是几百张图全回源; Cache API 里存一份,
//    系统清不动 (配合 storage.persist), 只在没缓存过时才走网络;
//  - 应用壳 (页面 + 静态资源): 网络优先, 顺路存进缓存 —— 断网时页面也打得开,
//    已下载的歌才谈得上离线播放 (api/* 数据接口不缓存, 离线时列表加载不了
//    属正常, 已下载栏读的是本机索引, 不走接口);
//  - activate 时清掉旧版壳缓存 + 接管已打开的页面 (clients.claim, 不用等重载)。
// 下载动作本身是页面脚本直连 Cache API, 这里只管离线时把缓存喂给 <audio>。
// 注意: 只在安全上下文 (HTTPS / localhost) 能注册, 明文 HTTP 下不存在。
"use strict";

const DOWNLOAD_CACHE = "music-downloads-v1";
// 壳缓存 v3 (2026-09-17 1.8.0 界面重构: 底栏换成菜单键/气泡/搜索键三件套,
// 顶栏遮罩与兜底脚本全撤 —— 静态资源地址变了 (?v=2), 换版本号让 activate 清旧账)
const SHELL_CACHE = "music-shell-v3";
const ARTWORK_CACHE = "music-artwork-v1";
const TRACK_URL_PATTERN = /\/music\/media\/stream\/\d+$/;
// 封面族: 专辑/艺人/单曲封面 + 播放列表自定义封面
// (URL 全带 ?v= 版本号, 换图即换址 —— 缓存键跟着换, 不会读到旧图)
const ARTWORK_PATTERN
  = /^\/music\/media\/(?:albums|artists|tracks)\/\d+\/artwork$|^\/music\/media\/playlists\/\d+\/cover$/;
const SHELL_PATHS = new Set(["/music", "/music/", "/music/login", "/music/changelog"]);

function isShellPath(path) {
  return SHELL_PATHS.has(path) || path.startsWith("/music/static/");
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const path = new URL(request.url).pathname;
  if (TRACK_URL_PATTERN.test(path)) {
    event.respondWith(serveTrack(request));
  } else if (ARTWORK_PATTERN.test(path)) {
    event.respondWith(serveArtwork(request));
  } else if (isShellPath(path)) {
    event.respondWith(serveShell(request));
  }
});

/** 壳资源: 在线用网络的 (顺手把成功的存缓存, 下次断网有得回), 断网回缓存。 */
async function serveShell(request) {
  const cache = await caches.open(SHELL_CACHE);
  try {
    const response = await fetch(request);
    if (response.ok) cache.put(request, response.clone());
    return response;
  } catch (_error) {
    const cached = await cache.match(request);
    if (cached) return cached;
    return new Response("离线且尚未缓存过此页面, 联网打开一次后可离线使用",
      { status: 503, headers: { "Content-Type": "text/plain; charset=utf-8" } });
  }
}

/** 缓存里有就回缓存 (Range 切 206, iOS Safari 拖进度条需要), 没有走网络。 */
async function serveTrack(request) {
  const cache = await caches.open(DOWNLOAD_CACHE);
  const cached = await cache.match(request.url);
  if (!cached) return fetch(request);
  const rangeHeader = request.headers.get("range");
  if (!rangeHeader) return cached;
  const slice = rangeSlice(await cached.blob(), rangeHeader);
  if (!slice) return cached;              // 解析不出范围: 给全量兜底
  return new Response(slice.body, {
    status: 206,
    headers: {
      "Content-Type": cached.headers.get("Content-Type")
        || "application/octet-stream",
      "Content-Range": `bytes ${slice.start}-${slice.end}/${slice.total}`,
      "Content-Length": String(slice.end - slice.start + 1),
    },
  });
}

/** "bytes=start-end" → 全量 blob 的切片 (end 缺省 = 到尾; 越界钳到尾)。 */
function rangeSlice(blob, rangeHeader) {
  const match = /^bytes=(\d+)-(\d*)$/.exec(rangeHeader.trim());
  if (!match) return null;
  const start = Number(match[1]);
  if (start >= blob.size) return null;
  const end = match[2] ? Math.min(Number(match[2]), blob.size - 1)
    : blob.size - 1;
  return { start, end, total: blob.size, body: blob.slice(start, end + 1) };
}

/** 封面: 缓存优先 (URL 自带 ?v= 版本, 缓存里的内容永不换), 没缓存过才走
    网络并顺手存下。条数封顶防无限膨胀: 超了丢最早一批 (Cache API 没有
    LRU, keys() 顺序近似先来后到, 够用)。 */
async function serveArtwork(request) {
  const cache = await caches.open(ARTWORK_CACHE);
  const cached = await cache.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok) {
    await cache.put(request, response.clone());
    trimArtworkCache(cache);
  }
  return response;
}

async function trimArtworkCache(cache) {
  const keys = await cache.keys();
  if (keys.length <= 600) return;
  for (const key of keys.slice(0, keys.length - 400)) {
    await cache.delete(key);
  }
}

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    // 壳缓存换版本号时清旧账; 下载缓存 (DOWNLOAD_CACHE) 是用户数据, 不动
    const names = await caches.keys();
    for (const name of names) {
      if (name.startsWith("music-shell-") && name !== SHELL_CACHE) {
        await caches.delete(name);
      }
      if (name.startsWith("music-artwork-") && name !== ARTWORK_CACHE) {
        await caches.delete(name);
      }
    }
    await self.clients.claim();   // 不等刷新, 已开的页面立刻归我管
  })());
});
