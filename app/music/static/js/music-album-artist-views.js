// music-album-artist-views — My Music 专辑详情页 + 艺人详情页 (推入层内容)。
// 拆自 music.js (结构化重构: 代码逐字节未动, 经典脚本按 music.html 里的顺序加载, 跨模块引用走全局)。
"use strict";
/* global ICON_ACTION_PLAY, ICON_ACTION_SHUFFLE, ICON_DOWNLOAD, PLACEHOLDER_ARTWORK,
          albumArtworkURL, albumCardHTML, artistArtworkURL, bindTrackLists, describeDuration,
          downloadAllFromUI, downloadsEnabled, escapeHTML, fetchJSON,
          listPlaceholderHTML, navigate, playerStart, pushPaneTarget, syncPlayerIndicators,
          toast, trackArtHTML, trackRowHTML */
/* exported renderAlbumView, renderArtistView */

// ------------------------------------------------------------ 专辑页

async function renderAlbumView(albumId, target) {
  target = target || pushPaneTarget();    // 二级层薄层; 兜底 #main (无层时)
  target.innerHTML = listPlaceholderHTML("加载中…");
  let page = null;
  try {
    page = await fetchJSON(`/music/api/albums/${albumId}`);
  } catch (error) {
    target.innerHTML = listPlaceholderHTML(`加载失败: ${error.message}`);
    return;
  }
  const album = page.album;
  const playable = page.tracks.filter((track) => track.playable);
  target.innerHTML = `
    <div class="album-hero">
      <img alt="" src="${albumArtworkURL(album)}"
           onerror="this.onerror=null;this.src='${PLACEHOLDER_ARTWORK}'">
      <div class="hero-txt">
        <h2>${escapeHTML(album.title)}</h2>
        <button class="hero-artist" data-artist-id="${album.artist_id}">${escapeHTML(album.artist_name)}</button>
        <small>${escapeHTML([album.year || "",
          describeDuration(album.duration_seconds, album.track_count)]
          .filter(Boolean).join(" · "))}</small>
      </div>
    </div>
    <div class="action-row">
      <button class="action primary" id="album-play" ${playable.length ? "" : "disabled"}>
        ${ICON_ACTION_PLAY} 播放</button>
      <button class="action" id="album-shuffle" ${playable.length ? "" : "disabled"}>
        ${ICON_ACTION_SHUFFLE} 随机</button>
      ${downloadsEnabled ? `
      <button class="action" id="album-download" ${playable.length ? "" : "disabled"}>
        ${ICON_DOWNLOAD} 下载全部</button>` : ""}
    </div>
    <div class="track-list" id="album-tracks">
      ${page.tracks.map((track) => trackRowHTML(track, trackArtHTML(track), "art")).join("")}
    </div>`;
  target.querySelector(".hero-artist").addEventListener("click", (event) => {
    navigate(`artist/${event.currentTarget.dataset.artistId}`);
  });
  target.querySelector("#album-play").addEventListener("click", () => {
    playerStart(page.tracks, page.tracks.indexOf(playable[0]));
  });
  target.querySelector("#album-shuffle").addEventListener("click", () => {
    playerStart(page.tracks, page.tracks.indexOf(playable[0]), true);
  });
  const albumDownload = target.querySelector("#album-download");
  if (albumDownload) {
    albumDownload.addEventListener("click", () => downloadAllFromUI(page.tracks));
  }
  bindTrackLists(target.querySelector("#album-tracks"), () => page.tracks);
  syncPlayerIndicators();
}

// ------------------------------------------------------------ 艺人页

async function renderArtistView(artistId, target) {
  target = target || pushPaneTarget();    // 二级层薄层; 兜底 #main (无层时)
  target.innerHTML = listPlaceholderHTML("加载中…");
  let page = null;
  try {
    page = await fetchJSON(`/music/api/artists/${artistId}`);
  } catch (error) {
    target.innerHTML = listPlaceholderHTML(`加载失败: ${error.message}`);
    return;
  }
  const artist = page.artist;
  target.innerHTML = `
    <div class="artist-hero">
      <img alt="" src="${artistArtworkURL(artist)}"
           onerror="this.onerror=null;this.src='${PLACEHOLDER_ARTWORK}'">
      <h2>${escapeHTML(artist.name)}</h2>
      <small>${artist.album_count} 张专辑 · ${artist.track_count} 首</small>
    </div>
    <div class="action-row">
      <button class="action primary" id="artist-play">${ICON_ACTION_PLAY} 播放</button>
      <button class="action" id="artist-shuffle">${ICON_ACTION_SHUFFLE} 随机</button>
    </div>
    <div class="section-head">专辑</div>
    <div class="album-grid" id="artist-albums">
      ${page.albums.map(albumCardHTML).join("")}
    </div>`;
  const playArtist = async (shuffle) => {
    try {
      const albumPages = await Promise.all(page.albums.map(
        (album) => fetchJSON(`/music/api/albums/${album.album_id}`)));
      const tracks = albumPages.flatMap((albumPage) => albumPage.tracks);
      if (!tracks.length) { toast("这位艺人还没有能播的曲目"); return; }
      playerStart(tracks, 0, shuffle);
    } catch (error) {
      toast(`加载失败: ${error.message}`);
    }
  };
  target.querySelector("#artist-play").addEventListener("click", () => playArtist(false));
  target.querySelector("#artist-shuffle").addEventListener("click", () => playArtist(true));
  target.querySelector("#artist-albums").addEventListener("click", (event) => {
    const card = event.target.closest("[data-album-id]");
    if (card) navigate(`album/${card.dataset.albumId}`);
  });
}

