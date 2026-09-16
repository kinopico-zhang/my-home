// music-home-view — My Music 主页视图: 播放列表段 + 最近播放段。
// 拆自 music.js (结构化重构: 代码逐字节未动, 经典脚本按 music.html 里的顺序加载, 跨模块引用走全局)。
"use strict";
/* global $, bindSwipeDelete, bindTrackLists, fetchJSON, listPlaceholderHTML, navigate,
          pageState, playlistRowHTML, toast, trackArtHTML, trackRowHTML */
/* exported renderHomeView */

// ------------------------------------------------------------ 主页

function renderHomeView() {
  $("#root-view").innerHTML = `
    <div class="section-head">播放列表</div>
    <div id="home-playlists">${listPlaceholderHTML("加载中…")}</div>
    <div class="section-head">最近播放</div>
    <div id="home-recent">${listPlaceholderHTML("加载中…")}</div>`;
  // 事件绑在容器上 (内容是异步重铺的, 绑内容会重复累加)
  $("#home-playlists").addEventListener("click", (event) => {
    const row = event.target.closest("[data-playlist-id]");
    if (row) navigate(`playlist/${row.dataset.playlistId}`);
  });
  // 列表行左滑露出删除: 删掉后就地抽行, 不整页重铺
  bindSwipeDelete($("#home-playlists"), async (wrap) => {
    const playlistId = Number(wrap.dataset.swipePlaylist);
    try {
      await fetchJSON(`/music/api/playlists/${playlistId}`, { method: "DELETE" });
      wrap.remove();
      toast("已删除");
    } catch (error) {
      toast(`没删掉: ${error.message}`);
    }
  });
  bindTrackLists($("#home-recent"), () => pageState.homeRecent || []);
  loadHomePlaylists();
  loadHomeRecent();
}

async function loadHomePlaylists() {
  let playlists = null;
  try {
    playlists = (await fetchJSON("/music/api/playlists")).playlists;
  } catch (_error) { /* 下面占位文案兜底 */ }
  const element = $("#home-playlists");
  if (!element || !element.isConnected) return;   // 已被换掉 (二级层下重铺也一样保护)
  element.innerHTML = playlists && playlists.length
    ? playlists.map(playlistRowHTML).join("")
    : listPlaceholderHTML("还没有播放列表; 长按任意歌曲就能新建一个");
}

async function loadHomeRecent() {
  let tracks = null;
  try {
    tracks = (await fetchJSON("/music/api/plays/recent?limit=20")).tracks;
  } catch (_error) { /* 下面占位文案兜底 */ }
  const element = $("#home-recent");
  if (!element || !element.isConnected) return;   // 已被换掉 (二级层下重铺也一样保护)
  pageState.homeRecent = tracks || [];
  element.innerHTML = pageState.homeRecent.length
    ? pageState.homeRecent.map(
        (track) => trackRowHTML(track, trackArtHTML(track), "art")).join("")
    : listPlaceholderHTML("听过歌就会出现在这里, 各账号各记各的");
}

