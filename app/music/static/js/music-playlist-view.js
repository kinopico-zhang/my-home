// music-playlist-view — My Music 播放列表详情页: 曲目管理/加歌/自定义封面上传。
// 拆自 music.js (结构化重构: 代码逐字节未动, 经典脚本按 music.html 里的顺序加载, 跨模块引用走全局)。
"use strict";
/* global $, ICON_ACTION_IMAGE, ICON_ACTION_PLAY, ICON_ACTION_SHARE, ICON_ACTION_SHUFFLE,
          ICON_ACTION_TRASH, ICON_DOWNLOAD, bindCoverPress, bindSwipeDelete, bindTrackLists,
          coverUploadPlaylistId: writable, describeDuration, downloadAllFromUI,
          downloadsEnabled, escapeHTML, fetchJSON, listPlaceholderHTML, navigate,
          playerStart, playlistCoverURL, pushPaneTarget, pushStack, renderRootView,
          sharePlaylist, syncPlayerIndicators, toast, trackArtHTML, trackRowHTML */
/* exported coverUploadPlaylistId, renderPlaylistView, uploadPlaylistCover */

// ------------------------------------------------------------ 播放列表页

async function renderPlaylistView(playlistId, target) {
  target = target || pushPaneTarget();    // 二级层薄层; 兜底 #main (无层时)
  target.innerHTML = listPlaceholderHTML("加载中…");
  let page = null;
  try {
    page = await fetchJSON(`/music/api/playlists/${playlistId}`);
  } catch (error) {
    target.innerHTML = listPlaceholderHTML(`加载失败: ${error.message}`);
    return;
  }
  const playlist = page.playlist;
  const playable = page.tracks.filter((track) => track.playable);
  const cover = playlistCoverURL(playlist);
  const coverLabel = cover ? "换封面" : "设置封面";
  target.innerHTML = `
    <div class="album-hero">
      <button class="pl-cover-btn" id="cover-tap" aria-label="${coverLabel}"
              title="${coverLabel}">
        ${cover
          ? `<img class="pl-icon big art" alt="" src="${cover}">`
          : '<div class="pl-icon big">♫</div>'}
        <span class="cover-hint" aria-hidden="true">${ICON_ACTION_IMAGE}</span>
      </button>
      <div class="hero-txt">
        <h2>${escapeHTML(playlist.name)}</h2>
        <small>${escapeHTML(describeDuration(
          playlist.duration_seconds, playlist.track_count))}</small>
      </div>
    </div>
    <div class="action-row">
      <button class="action icon primary" id="playlist-play" title="播放"
              aria-label="播放" ${playable.length ? "" : "disabled"}>
        ${ICON_ACTION_PLAY}</button>
      <button class="action icon" id="playlist-shuffle" title="随机播放"
              aria-label="随机播放" ${playable.length ? "" : "disabled"}>
        ${ICON_ACTION_SHUFFLE}</button>
      ${downloadsEnabled ? `
      <button class="action icon" id="playlist-download" title="下载全部"
              aria-label="下载全部" ${playable.length ? "" : "disabled"}>
        ${ICON_DOWNLOAD}</button>` : ""}
      <button class="action icon" id="playlist-share" title="分享"
              aria-label="分享">${ICON_ACTION_SHARE}</button>
      <button class="action icon" id="playlist-delete" title="删除列表"
              aria-label="删除列表">${ICON_ACTION_TRASH}</button>
    </div>
    <div class="track-list" id="playlist-tracks">
      ${page.tracks.map((track) => `
        <div class="swipe-wrap" data-swipe-track="${track.track_id}">
          ${trackRowHTML(track, trackArtHTML(track), "art")}
          <button class="swipe-del" aria-label="从列表移除">删除</button>
        </div>`).join("")}
    </div>`;
  target.querySelector("#playlist-play").addEventListener("click", () => {
    playerStart(page.tracks, page.tracks.indexOf(playable[0]));
  });
  target.querySelector("#playlist-shuffle").addEventListener("click", () => {
    playerStart(page.tracks, page.tracks.indexOf(playable[0]), true);
  });
  const playlistDownload = target.querySelector("#playlist-download");
  if (playlistDownload) {
    playlistDownload.addEventListener("click", () => downloadAllFromUI(page.tracks));
  }
  target.querySelector("#playlist-share").addEventListener("click", () => {
    sharePlaylist(playlist);
  });
  bindCoverPress(playlistId, playlist.name, !!cover);
  target.querySelector("#playlist-delete").addEventListener("click", async () => {
    if (!window.confirm(`删除播放列表「${playlist.name}」?`)) return;
    try {
      await fetchJSON(`/music/api/playlists/${playlistId}`, { method: "DELETE" });
      toast("已删除");
      navigate("home");                  // 回主页, 列表段重铺自然不再有它
      if (pushStack.length) renderRootView("home");   // 一级页就在层底下, 趁滑走前重铺
    } catch (error) {
      toast(`没删掉: ${error.message}`);
    }
  });
  bindTrackLists(target.querySelector("#playlist-tracks"), () => page.tracks);
  // 曲目行左滑露出删除: 移出列表后就地抽掉那行 (不整页重铺, 滚动位置保住),
  // 头上的 规模/时长 文案顺手重算。
  bindSwipeDelete(target.querySelector("#playlist-tracks"), async (wrap) => {
    const trackId = Number(wrap.dataset.swipeTrack);
    try {
      await fetchJSON(`/music/api/playlists/${playlistId}/tracks/${trackId}`,
                      { method: "DELETE" });
      wrap.remove();
      page.tracks = page.tracks.filter((track) => track.track_id !== trackId);
      const heroSmall = target.querySelector(".hero-txt small");
      if (heroSmall) {
        heroSmall.textContent = describeDuration(
          page.tracks.reduce((sum, track) => sum + (track.duration_seconds || 0), 0),
          page.tracks.length);
      }
      toast("已从列表移除");
    } catch (error) {
      toast(`没移除掉: ${error.message}`);
    }
  });
  coverUploadPlaylistId = playlistId;
  syncPlayerIndicators();
}

/** 隐藏文件选择器选中图片 → 直接把字节 PUT 上去 (原图直存, 不压缩)。 */
async function uploadPlaylistCover(playlistId) {
  const input = $("#cover-file");
  const file = input.files && input.files[0];
  input.value = "";                     // 同一张图重选也要触发 change
  if (!file) return;
  if (file.size > 10 * 1024 * 1024) {
    toast("封面太大了 (上限 10 MB)");
    return;
  }
  try {
    await fetchJSON(`/music/api/playlists/${playlistId}/cover`, {
      method: "PUT",
      headers: { "Content-Type": file.type || "application/octet-stream" },
      body: file,
    });
    toast("封面已更新");
    renderPlaylistView(playlistId);
  } catch (error) {
    toast(`封面没传上去: ${error.message}`);
  }
}

