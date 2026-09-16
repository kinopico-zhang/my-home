// music-player-queue — My Music 队列驱动: 开播/暂停/上下曲/跳过不可播, loadTrack 换源, 下一曲预取。
// 拆自 music-player.js (结构化重构: 代码逐字节未动, 按 music.html 里的顺序加载, 跨模块引用走全局)。
"use strict";
/* global $, audioElement, createPlayQueue, currentTrack: writable, loadLyrics,
          lyricsActiveIndex: writable, lyricsCache, lyricsViewOpen, playQueue: writable,
          playRecorded: writable, prefetchLyrics, prefetchSequence: writable,
          prefetched: writable, queueAdvance, queueCurrent, queueGoBack, queueShuffleAll,
          queueUpcoming, renderPlayerChrome, renderQueueView, savePlayerState, toast,
          trackChangeListeners, updateMediaSession */
/* exported loadTrack, lyricsActiveIndex, onTrackChange, playRecorded, playerCurrentTrack,
            playerCurrentTrackId, playerIsPlaying, playerNext, playerPrevious, playerStart,
            playerToggle, prefetchNextTrack, startAudio */

// ------------------------------------------------------------ 队列驱动

/** 浏览页入口: 给一批曲目 (及起始下标) 开播; shuffleOn = 随机播这批。 */
function playerStart(tracks, startIndex, shuffleOn) {
  playQueue = createPlayQueue(tracks, startIndex);
  if (shuffleOn) queueShuffleAll(playQueue);   // 整队洗牌, 不是"当前曲钉队首"
  const track = queueCurrent(playQueue);
  if (!track) return;
  if (!track.playable) {
    advanceToPlayable();
    return;
  }
  loadTrack(track, true);
}

/** 起播统一入口。 */
function startAudio() {
  return audioElement().play();
}

function playerToggle() {
  const audio = audioElement();
  if (!currentTrack) return;
  if (audio.paused) {
    startAudio().catch(() => toast("播放被浏览器拦了, 再点一次"));
  } else {
    audio.pause();
  }
}

function playerNext() {
  if (!playQueue) return;
  const track = queueAdvance(playQueue);
  if (!track) {                       // 队尾: 停在原地 (苹果同款)
    toast("播完了");
    return;
  }
  loadTrack(track, true);
}

function playerPrevious() {
  if (!playQueue) return;
  const audio = audioElement();
  if (audio.currentTime > 3) {        // 播过 3 秒先回本曲开头
    audio.currentTime = 0;
    return;
  }
  const track = queueGoBack(playQueue);
  if (track) loadTrack(track, true);
}

/** 不可播格式连跳, 直到遇到能播的 (全队都播不了就提示)。 */
function advanceToPlayable() {
  let track = queueCurrent(playQueue);
  while (track && !track.playable) {
    track = queueAdvance(playQueue);
  }
  if (!track) {
    toast("这批曲目浏览器都播不了");
    return;
  }
  loadTrack(track, true);
}

/** 载入曲目: 音频源 (预取到位直接用 blob, 秒切) + 迷你条/全屏页/锁屏
    元数据 + 歌词缓存失效 + 顺手预取下一曲。 */
let playingObjectURL = "";   // audio 正在用的预取 blob; 换曲时 revoke (一首几十 MB, 攒着会撑爆手机内存)

function loadTrack(track, autoplay) {
  currentTrack = track;
  playRecorded = false;
  lyricsCache.delete(track.track_id);      // 每次换曲重取 (歌词可能刚扫描进来)
  $("#fp-lyrics-btn").disabled = false;    // 探明前先恢复可点
  prefetchLyrics(track);                   // 探明没有的把歌词键置灰
  lyricsActiveIndex = -1;
  const audio = audioElement();
  const prefetchedURL = prefetched && prefetched.trackId === track.track_id
    ? prefetched.objectURL : "";
  if (playingObjectURL) URL.revokeObjectURL(playingObjectURL);   // 上一曲用完的预取 blob
  playingObjectURL = prefetchedURL;
  if (prefetchedURL) prefetched = null;    // 占位交给 audio, 别再 revoke
  else discardPrefetch();                  // 其余情况旧预取作废
  audio.src = prefetchedURL || `/music/media/stream/${track.track_id}`;
  // 点播一律从头。冷启动恢复写过一次"待生效进度" (preload=none 时它一直挂着
  // 不生效), Safari 会把它漏到之后点开的歌上 —— 从一半播起的真凶。
  // 显式归零: HAVE_NOTHING 时是覆盖待生效进度, 已载入时是直接倒回开头。
  audio.currentTime = 0;
  renderPlayerChrome();
  renderQueueView();
  if (lyricsViewOpen) loadLyrics();
  updateMediaSession();
  for (const listener of trackChangeListeners) listener(track);
  savePlayerState();
  prefetchNextTrack();
  if (autoplay) startAudio().catch(() => { /* iOS 偶发拒绝: 保持暂停态 */ });
}

// ------------------------------------------------------------ 下一曲预取

/** 后台拉下一曲的完整音频进 blob (已下载过的会被 SW 直接回缓存, 更快);
    单槽: 只留即将播的那首, 旧的 revoke。下一曲的封面也顺手焐热 ——
    冷门专辑的封面服务端要现抽 (NAS 盘一忙就是好几秒), 藏在整首歌的
    播放时间里预取, 切歌时即取即有。 */
function prefetchNextTrack() {
  if (!playQueue || playQueue.repeat === "one") return;   // 单曲循环没有"下一曲"
  const next = nextUpcomingTrack();
  if (!next || !next.playable || next.track_id === playerCurrentTrackId()) return;
  if (next.album_id) {
    const warmCover = new Image();
    warmCover.src = `/music/media/albums/${next.album_id}/artwork`;
  }
  if (prefetched && prefetched.trackId === next.track_id) return;   // 已就位
  discardPrefetch();
  const trackId = next.track_id;
  const token = prefetchSequence;
  fetch(`/music/media/stream/${trackId}`)
    .then((response) => (response.ok ? response.blob()
      : Promise.reject(new Error(`HTTP ${response.status}`))))
    .then((blob) => {
      if (token !== prefetchSequence) return;             // 目标已经变了
      if (playerCurrentTrackId() === trackId) return;     // 已经切到这首了
      if (nextUpcomingTrack() !== next) return;           // 不再是下一曲
      prefetched = { trackId, objectURL: URL.createObjectURL(blob) };
    })
    .catch(() => { /* 预取失败: 到时候正常走网络 */ });
}

/** 下一曲 (不含当前; 队列快播完且不循环时没有)。 */
function nextUpcomingTrack() {
  const upcoming = queueUpcoming(playQueue);
  return upcoming.length > 1 ? upcoming[1] : null;
}

function discardPrefetch() {
  prefetchSequence++;              // 在途的旧请求回来也认作过期
  if (prefetched) {
    URL.revokeObjectURL(prefetched.objectURL);
    prefetched = null;
  }
}

function playerCurrentTrackId() {
  return currentTrack ? currentTrack.track_id : 0;
}

/** 全屏页 ⋯ / ♥ 按钮要的当前曲目 (含恢复现场那首)。 */
function playerCurrentTrack() {
  return currentTrack;
}

function playerIsPlaying() {
  return !!currentTrack && !audioElement().paused;
}

function onTrackChange(listener) {
  trackChangeListeners.push(listener);
}

