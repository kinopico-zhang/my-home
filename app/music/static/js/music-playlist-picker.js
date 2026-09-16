// music-playlist-picker — My Music 添加到播放列表选择单: 弹层/列表渲染/加歌去重。
// 拆自 music.js (结构化重构: 代码逐字节未动, 经典脚本按 music.html 里的顺序加载, 跨模块引用走全局)。
"use strict";
/* global $, describeDuration, escapeHTML, fetchJSON, listPlaceholderHTML,
          pickerTrack: writable, playlistCoverURL, toast */
/* exported openPlaylistPicker */


// ------------------------------------------------ 添加到播放列表 (选择单)

function closePlaylistPicker() {
  $("#picker-mask").hidden = true;
  $("#picker-sheet").hidden = true;
  pickerTrack = null;
}

function openPlaylistPicker(track) {
  pickerTrack = track;
  $("#picker-track-title").textContent = track.title;
  $("#picker-name").value = "";
  $("#picker-mask").hidden = false;
  $("#picker-sheet").hidden = false;
  renderPlaylistPicker();
}

/** 列表清单 (纯加歌的选择单, 列表删除在各自的详情页; 新建的排前面);
 * 空态给新建引导。 */
async function renderPlaylistPicker() {
  const list = $("#picker-list");
  list.innerHTML = listPlaceholderHTML("加载中…");
  let playlists = [];
  try {
    playlists = (await fetchJSON("/music/api/playlists")).playlists;
  } catch (error) {
    list.innerHTML = listPlaceholderHTML(`列表没拉到: ${error.message}`);
    return;
  }
  if (!playlists.length) {
    list.innerHTML = listPlaceholderHTML("还没有播放列表; 起个名字新建一个");
    return;
  }
  list.innerHTML = playlists.map((playlist) => {
    const cover = playlistCoverURL(playlist);
    return `
    <button class="picker-row" data-picker-playlist="${playlist.playlist_id}">
      ${cover
        ? `<img class="pl-icon art" loading="lazy" decoding="async" alt="" src="${cover}">`
        : '<span class="pl-icon">♫</span>'}
      <span class="a-main"><b>${escapeHTML(playlist.name)}</b>
        <small>${describeDuration(playlist.duration_seconds, playlist.track_count)}</small></span>
    </button>`;
  }).join("");
}

async function addTrackToPlaylist(playlistId, playlistName) {
  if (!pickerTrack) return;
  try {
    await fetchJSON(`/music/api/playlists/${playlistId}/tracks`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ track_id: pickerTrack.track_id }),
    });
    toast(`已加入「${playlistName}」`);
    renderPlaylistPicker();               // 刷新计数, 也能接着加别的列表
  } catch (error) {
    if (error.status === 409) {           // 已在列表里: 直说原因, 不算没加成
      toast(error.message);
    } else {
      toast(`没加进去: ${error.message}`);
    }
  }
}

$("#picker-list").addEventListener("click", async (event) => {
  const pick = event.target.closest("[data-picker-playlist]");
  if (pick) await addTrackToPlaylist(Number(pick.dataset.pickerPlaylist),
                                     pick.querySelector("b").textContent);
});

$("#picker-create").addEventListener("click", async () => {
  const input = $("#picker-name");
  const name = input.value.trim();
  if (!name) { toast("先给新列表起个名字"); input.focus(); return; }
  if (!pickerTrack) return;
  try {
    const playlist = await fetchJSON("/music/api/playlists", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    input.value = "";
    await addTrackToPlaylist(playlist.playlist_id, playlist.name);
  } catch (error) {
    toast(`没建起来: ${error.message}`);
  }
});

$("#picker-close").addEventListener("click", closePlaylistPicker);
$("#picker-mask").addEventListener("click", closePlaylistPicker);

