// music-library-pagination — My Music 资料库分页拉取链: 首页拉取/翻页/铺页/哨兵观察 (串台守卫在这)。
// 拆自 music.js (结构化重构), 1.8.0 起容器由调用方传入 (专辑/艺人各开各的层)。
"use strict";
/* global albumCardHTML, artistRowHTML, fetchJSON, listPlaceholderHTML, pageState,
          syncPlayerIndicators, toast */
/* exported appendListPage, loadListPage */

async function loadListPage(segment, body) {
  if (pageState.lists[segment]) return;
  const list = { items: [], total: 0, offset: 0, renderedCount: 0,
                 done: false, loading: true };
  pageState.lists[segment] = list;
  await fetchListPage(segment, list);
  // 段守卫: 等待期间层已被收走/换掉, 这页内容不能铺 (换台串味)
  if (!body || !body.isConnected || body.dataset.segment !== segment) return;
  if (!list.items.length) {
    // 首页没拉到 (弱网/服务器打盹): 空单不缓存, 切回来还会重试
    delete pageState.lists[segment];
    body.innerHTML = listPlaceholderHTML("列表没拉到, 退出去再进来试试");
    return;
  }
  body.innerHTML = "";
  appendListPage(body, segment, list);
  syncPlayerIndicators();
}

async function fetchListPage(segment, list) {
  try {
    const parameters = new URLSearchParams({ limit: "60" });
    if (segment === "albums") parameters.set("sort", "title");
    parameters.set("offset", String(list.offset));
    const endpoint = segment === "artists" ? "/music/api/artists"
      : "/music/api/albums";
    const data = await fetchJSON(`${endpoint}?${parameters}`);
    list.items.push(...(segment === "artists" ? data.artists : data.albums));
    list.total = data.total_count;
    list.offset = list.items.length;
    list.done = list.offset >= list.total;
  } catch (error) {
    toast(`加载失败: ${error.message}`);
  } finally {
    list.loading = false;
  }
}

/** 把新到的一页铺进容器 + 哨兵; 哨兵还在屏内就续载 (IO 只在进出时回调)。
    追加而不重铺: 图片已经加载的格子不闪。段守卫: 页签已换走的话这页
    是在途旧账, 直接丢弃 —— 否则会把别的内容灌进当前页签 (串台)。 */
function appendListPage(body, segment, list) {
  if (body.dataset.segment !== segment) return;
  const firstRender = !body.querySelector(".list-sentinel")
    && !body.querySelector(".album-grid") && !body.querySelector(".track-row")
    && !body.querySelector(".artist-row");
  if (firstRender && !list.items.length) {
    body.innerHTML = listPlaceholderHTML("曲库还是空的");
    return;
  }
  const existingSentinel = body.querySelector(".list-sentinel");
  if (existingSentinel) existingSentinel.remove();
  const added = list.items.slice(list.renderedCount || 0);
  if (segment === "artists") {
    body.insertAdjacentHTML("beforeend", added.map(artistRowHTML).join(""));
  } else {
    let grid = body.querySelector(".album-grid");
    if (!grid) {
      body.insertAdjacentHTML("beforeend", '<div class="album-grid"></div>');
      grid = body.querySelector(".album-grid");
    }
    grid.insertAdjacentHTML("beforeend", added.map(albumCardHTML).join(""));
  }
  list.renderedCount = list.items.length;
  if (!list.done) {
    body.insertAdjacentHTML("beforeend",
      '<div class="list-sentinel" aria-hidden="true"></div>');
    observeSentinel(body, segment, list);
  }
}

function observeSentinel(body, segment, list) {
  const sentinel = body.querySelector(".list-sentinel");
  if (!sentinel) return;
  const continueLoading = async () => {
    if (list.loading || list.done) return;
    list.loading = true;
    await fetchListPage(segment, list);
    appendListPage(body, segment, list);    // 哨兵重挂, 下一轮续命
    syncPlayerIndicators();
  };
  const observer = new IntersectionObserver((entries) => {
    if (entries.some((entry) => entry.isIntersecting)) continueLoading();
  }, { rootMargin: "300px" });
  observer.observe(sentinel);
  // 列表不满一屏时 IO 不会再回调 → 主动续载 (IO 只在进出过渡时回调)
  if (sentinel.getBoundingClientRect().top < window.innerHeight) continueLoading();
}

