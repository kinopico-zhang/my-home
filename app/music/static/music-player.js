// music-player.js — 播放器: 音频引擎 + 迷你条 + 全屏页 (歌词/队列) + 锁屏控制。
// 队列状态机在 player-queue.js, 歌词解析在 lyrics-parser.js;
// 浏览页 (music.js) 只调 playerStart / playerCurrentTrackId / onTrackChange。
// 听过的歌顺手报给后端 (最近播放), 下一曲在后台预取 (秒切)。
"use strict";
/* exported playerStart, openLyricsView, onTrackChange, playerCurrentTrack */   // 供 music.js 引用

const PLAYER_STATE_KEY = "music-player-state";
// 手动滑动歌词后多久自动回到跟唱 (毫秒; Apple Music 同款节奏)
const LYRICS_FOLLOW_RESUME_MS = 4000;

/** @type {PlayQueue|null} */
let playQueue = null;
let currentTrack = null;
let lyricsCache = new Map();       // track_id → {synced, lines} | null (没歌词)
let lyricsActiveIndex = -1;
let lyricsViewOpen = false;
let scrubbing = false;
let playRecorded = false;          // 本曲已报过最近播放 (暂停续播不重复报)
// 歌词自由滑动: 手动滚过就暂停跟唱, 出"回到当前句"; 静置几秒自动恢复
let lyricsFollowPaused = false;
let lyricsLastScrollAt = 0;
let lyricsAutoScrolling = false;   // 程序定位引发的 scroll 事件不算手动
/** @type {Array<function(Object|null)>} 曲目切换回调 (列表高亮用) */
const trackChangeListeners = [];

// 下一曲预取: 单槽 blob (objectURL), 切歌即用即弃
let prefetched = null;             // {trackId, objectURL} | null
let prefetchSequence = 0;          // 旧请求回来发现序号变了就丢弃

function audioElement() {
  return $("#audio");
}

// ------------------------------------------------------------ 队列驱动

/** 浏览页入口: 给一批曲目 (及起始下标) 开播; shuffleOn = 随机播这批。 */
function playerStart(tracks, startIndex, shuffleOn) {
  playQueue = createPlayQueue(tracks, startIndex);
  if (shuffleOn) queueSetShuffle(playQueue, true);
  const track = queueCurrent(playQueue);
  if (!track) return;
  if (!track.playable) {
    advanceToPlayable();
    return;
  }
  loadTrack(track, true);
}

/** 起播统一入口 (音量走 audio.volume 原生通道, 不再绕 WebAudio)。 */
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
  renderPlayerChrome();
  renderQueueSheet();
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

// ------------------------------------------------------------ 持久化

function savePlayerState() {
  if (!playQueue || !currentTrack) return;
  const audio = audioElement();
  try {
    localStorage.setItem(PLAYER_STATE_KEY, JSON.stringify({
      tracks: playQueue.tracks.slice(0, 500),
      index: playQueue.tracks.indexOf(currentTrack),
      time: audio.currentTime,
      shuffle: playQueue.shuffle,
      repeat: playQueue.repeat,
    }));
  } catch (_error) { /* 存储满了就算了, 不影响听歌 */ }
}

/** 冷启动恢复上次听到的地方 (恢复到暂停态, iOS 不许自动播)。 */
function playerRestore() {
  let saved = null;
  try {
    saved = JSON.parse(localStorage.getItem(PLAYER_STATE_KEY) || "null");
  } catch (_error) { saved = null; }
  if (!saved || !Array.isArray(saved.tracks) || !saved.tracks.length) return;
  playQueue = createPlayQueue(saved.tracks, saved.index || 0);
  playQueue.repeat = saved.repeat || "off";
  const track = queueCurrent(playQueue);
  if (!track) { playQueue = null; return; }
  const audio = audioElement();
  audio.src = `/music/media/stream/${track.track_id}`;
  currentTrack = track;
  renderPlayerChrome();
  renderQueueSheet();
  updateMediaSession();
  for (const listener of trackChangeListeners) listener(track);
  $("#fp-lyrics-btn").disabled = false;    // 探明前先恢复可点 (与 loadTrack 同款)
  prefetchLyrics(track);                   // 恢复现场也探一遍词: 没词的键灰掉
  if (saved.time) audio.currentTime = saved.time;
  prefetchNextTrack();            // 恢复现场时也把下一曲备好
}

// ------------------------------------------------------------ 界面渲染

function renderPlayerChrome() {
  const track = currentTrack;
  $("#mini-player").hidden = !track;
  if (!track) return;
  $("#mini-art").src = PLACEHOLDER_ARTWORK;
  $("#mini-title").textContent = track.title;
  $("#mini-artist").textContent = track.artist;
  $("#fp-title").textContent = track.title;
  $("#fp-artist").textContent = track.artist;
  updateSourceLine(track);
  const artwork = track.album_id
    ? `/music/media/albums/${track.album_id}/artwork` : PLACEHOLDER_ARTWORK;
  $("#mini-art").src = artwork;
  $("#fp-art").src = artwork;
  $("#fp-bg-img").src = artwork;
  updatePlayButtons();
  updateShuffleRepeatButtons();
}

function updatePlayButtons() {
  const playing = playerIsPlaying();
  $("#mini-play").innerHTML = playing ? ICON_PAUSE : ICON_PLAY;
  $("#fp-play").innerHTML = playing ? ICON_PAUSE_BIG : ICON_PLAY_BIG;
  for (const element of document.querySelectorAll("[data-track-row]")) {
    element.classList.toggle("playing",
      Number(element.dataset.trackRow) === playerCurrentTrackId() && playing);
  }
}

function updateShuffleRepeatButtons() {
  if (!playQueue) return;
  $("#fp-shuffle").classList.toggle("on", playQueue.shuffle);
  const repeat = playQueue.repeat;
  const repeatButton = $("#fp-repeat");
  repeatButton.classList.toggle("on", repeat !== "off");
  repeatButton.classList.toggle("one", repeat === "one");
}

// ------------------------------------------------------------ 底部来源行
// 封面下那行小字: 有 作词/作曲 标签就显示, 没有退专辑名;
// 标签按需现读 (库里只有三成左右的歌带), 读过的缓存住。
const creditsCache = new Map();     // track_id → "作词 X · 作曲 Y" | ""
let creditsSequence = 0;            // 请求序号: 切曲后旧响应不再上屏

function updateSourceLine(track) {
  if (creditsCache.has(track.track_id)) {
    $("#fp-source").textContent = creditsCache.get(track.track_id)
      || track.album_title || "";
    return;
  }
  $("#fp-source").textContent = track.album_title || "";
  const token = ++creditsSequence;
  fetchJSON(`/music/api/tracks/${track.track_id}/credits`)
    .then((data) => {
      const parts = [];
      if (data.lyricist) parts.push(`作词 ${data.lyricist}`);
      if (data.composer) parts.push(`作曲 ${data.composer}`);
      creditsCache.set(track.track_id, parts.join(" · "));
      if (token !== creditsSequence) return;        // 已经切到别的歌了
      $("#fp-source").textContent = parts.join(" · ")
        || track.album_title || "";
    })
    .catch(() => { /* 拿不到标签就保持专辑名 */ });
}

// 收起后等滑出动画 (300ms) 再 display:none。这期间两层都要放行点击到下层列表
// (用户看见列表露出来了, 点了就该有反应); 重开必须撤掉挂着的隐藏定时器,
// 不然「刚关又马上开」时旧定时器会把正开着的播放页藏掉, 之后所有点击
// 全落到下层列表上 (表现为按键没反应、点了别的歌)。
let fpHideTimer = 0;

function openFullPlayer() {
  const fullPlayer = $("#full-player");
  clearTimeout(fpHideTimer);
  fullPlayer.hidden = false;
  fullPlayer.style.pointerEvents = "";
  void fullPlayer.offsetWidth;   // 强制起点样式先落地再放滑入 (rAF 在安静页会饿死)
  fullPlayer.classList.add("open");
}

function closeFullPlayer() {
  const fullPlayer = $("#full-player");
  fullPlayer.classList.remove("open");
  fullPlayer.style.pointerEvents = "none";   // 滑出途中别挡下层
  clearTimeout(fpHideTimer);
  fpHideTimer = setTimeout(() => {
    fullPlayer.hidden = true;
    fullPlayer.style.pointerEvents = "";
  }, 300);
  if (lyricsViewOpen) toggleLyricsView();
}

// ------------------------------------------------------------ 下拉收起 / 横划切歌
// 抓手条/封面往下拖: 播放页跟手下滑, 松手拖得够远或够快就收起, 否则弹回。
// 封面另有左右划: 跟手平移, 松手拖过三分之一 (或带甩劲) 就切上一首/下一首,
// 封面朝划的方向滑出, 新封面从另一侧滑入。抓手条拖动后的尾随 click 不算
// (不然小拖一下也收起)。
let fpDismissDragged = false;

function bindDismissDrag(target, swipeTracks = false) {
  const player = $("#full-player");
  const art = $("#fp-art-wrap");
  let dragging = false;
  let pointerId = -1;
  let startX = 0;
  let startY = 0;
  let lastX = 0;
  let lastY = 0;
  let lastTime = 0;
  let velocity = 0;                  // px/ms, 松手那刻的甩速 (竖向)
  let hVelocity = 0;                 // 横向甩速
  let mode = "";                     // "" 未定 / "down" 收起 / "side" 切歌
  target.addEventListener("pointerdown", (event) => {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    dragging = true;
    pointerId = event.pointerId;
    startX = lastX = event.clientX;
    startY = lastY = event.clientY;
    lastTime = performance.now();
    velocity = 0;
    hVelocity = 0;
    mode = "";
    fpDismissDragged = false;
  });
  target.addEventListener("pointermove", (event) => {
    if (!dragging || event.pointerId !== pointerId) return;
    const now = performance.now();
    if (now > lastTime) {
      velocity = (event.clientY - lastY) / (now - lastTime);
      hVelocity = (event.clientX - lastX) / (now - lastTime);
      lastTime = now;
    }
    lastX = event.clientX;
    lastY = event.clientY;
    const dx = lastX - startX;
    const dy = lastY - startY;
    if (!mode) {
      if (Math.abs(dx) < 10 && Math.abs(dy) < 10) return;
      if (Math.abs(dy) >= Math.abs(dx)) mode = "down";
      else if (swipeTracks) mode = "side";
      else { dragging = false; return; }   // 抓手条上的横划没意义, 放掉
      player.style.transition = "none";
      if (mode === "side") art.style.transition = "none";
      target.setPointerCapture(event.pointerId);
    }
    if (mode === "down") {
      if (dy > 10) fpDismissDragged = true;
      player.style.transform = dy > 0 ? `translateY(${dy * 0.92}px)` : "";
    } else {
      const drag = dx * 0.9;         // 横向轻阻尼
      art.style.transform =
        `translateX(${drag}px) scale(${Math.max(.88, 1 - Math.abs(drag) / 900)})`;
      art.style.opacity = `${Math.max(.55, 1 - Math.abs(drag) / 700)}`;
    }
  });
  const finish = (event) => {
    if (!dragging || (event.pointerId !== undefined
                      && event.pointerId !== pointerId)) return;
    dragging = false;
    player.style.transition = "";
    player.style.transform = "";
    if (mode === "down") {
      if (lastY - startY > 90 || velocity > 0.55) closeFullPlayer();
      return;
    }
    if (mode !== "side") return;
    const width = art.offsetWidth || 1;
    const flick = Math.abs(hVelocity) > 0.5 && Math.abs(lastX - startX) > 30;
    if (lastX - startX <= -width / 3 || (flick && hVelocity < 0)) {
      swipeCoverTo("left");          // 样式交给动画接管 (从当前位置滑出)
    } else if (lastX - startX >= width / 3 || (flick && hVelocity > 0)) {
      swipeCoverTo("right");
    } else {
      art.style.transition = "";     // 没拖够: transition 回来, 弹回原位
      art.style.transform = "";
      art.style.opacity = "";
    }
  };
  target.addEventListener("pointerup", finish);
  target.addEventListener("pointercancel", finish);
}

/** 封面切歌动画: 朝划的方向滑出淡出 → 换歌 → 新封面从另一侧滑入。 */
function swipeCoverTo(direction) {
  const art = $("#fp-art-wrap");
  const swap = direction === "left" ? playerNext : playerPrevious;
  art.style.transition = "transform .2s ease-in, opacity .2s ease-in";
  art.style.transform = `translateX(${direction === "left" ? -70 : 70}%)`;
  art.style.opacity = "0";
  setTimeout(() => {
    swap();
    art.style.transition = "none";
    art.style.transform = `translateX(${direction === "left" ? 60 : -60}%)`;
    void art.offsetWidth;           // 起点先落地再放滑入 (rAF 在安静页会饿死)
    art.style.transition = "transform .24s cubic-bezier(.32,.72,.35,1)";
    art.style.transform = "";
    setTimeout(() => { art.style.transition = ""; }, 260);
  }, 200);
}

// ------------------------------------------------------------ 音量
// 桌面/安卓: audio.volume 原生有效, 应用内音量条直接调, 记住上次的位置。
// iPhone Safari: audio.volume 写了也白写。1.5.0 试过绕 WebAudio 增益调,
// 结果拖不动、声音还脱开手机音量键 —— 索性 iPhone 上整个收起音量条,
// 音频走原生通道, 音量键说了算 (苹果自家的音乐应用也没有应用内音量条)。
function loadSavedVolume() {
  const raw = localStorage.getItem("music-volume");
  if (raw === null) return 100;         // 没拖过 = 满音量 (Number(null) 是 0, 不能直接转)
  const saved = Number(raw);
  return Number.isFinite(saved) && saved >= 0 && saved <= 100 ? saved : 100;
}

/** audio.volume 写得进吗? (iOS 写了也白写, 读回来还是 1)。开播放器时探一次。 */
function nativeVolumeWorks() {
  const audio = audioElement();
  const before = audio.volume;
  try {
    audio.volume = before >= 1 ? 0.5 : 1;
    const changed = audio.volume !== before;
    audio.volume = before;
    return changed;
  } catch (_e) {
    return false;
  }
}

function applyVolume(value) {
  try { audioElement().volume = value / 100; } catch (_e) { /* 静默忽略 */ }
}

/** 歌词结果/外部入口: 打开歌词视图 (已开着就不动; 没歌词的曲子点不开)。 */
function openLyricsView() {
  if (!lyricsViewOpen && !$("#fp-lyrics-btn").disabled) toggleLyricsView();
}

/** 歌词键状态: 探明没歌词的置灰禁点 (歌词视图正开着的顺手关回封面)。 */
function syncLyricsButton() {
  const noLyrics = currentTrack && lyricsCache.has(currentTrack.track_id)
    && lyricsCache.get(currentTrack.track_id) === null;
  $("#fp-lyrics-btn").disabled = !!noLyrics;
  if (noLyrics && lyricsViewOpen) toggleLyricsView();
}

/** 换曲后台探一遍歌词: 结果进缓存, 歌词键跟着亮/灰 (探不到先不灰)。 */
function prefetchLyrics(track) {
  if (!track) return;
  fetchJSON(`/music/api/tracks/${track.track_id}/lyrics`)
    .then((response) => {
      lyricsCache.set(track.track_id,
        response.lyrics ? parseLyrics(response.lyrics) : null);
    })
    .catch(() => { /* 探不到就当还没探: 键保持可点, 开视图再试 */ })
    .finally(() => {
      if (currentTrack && currentTrack.track_id === track.track_id) {
        syncLyricsButton();
      }
    });
}

function toggleLyricsView() {
  lyricsViewOpen = !lyricsViewOpen;
  $("#fp-art-wrap").hidden = lyricsViewOpen;
  $("#fp-lyrics").hidden = !lyricsViewOpen;
  $("#fp-lyrics-btn").classList.toggle("on", lyricsViewOpen);
  $("#full-player").classList.toggle("lyrics", lyricsViewOpen);
  lyricsFollowPaused = false;         // 开/关歌词都回到跟唱
  $("#lyrics-resume").hidden = true;
  $("#fp-lyrics").classList.remove("browsing");   // 距离模糊重新生效
  if (lyricsViewOpen) {
    loadLyrics();
  } else {
    cancelLyricsScroll();          // 关页时动画立刻停, scroll 事件别再误判
    lyricsActiveIndex = -1;
  }
}

// ------------------------------------------------------------ 歌词

async function loadLyrics() {
  const track = currentTrack;
  if (!track) return;
  if (!lyricsCache.has(track.track_id)) {
    try {
      const response = await fetchJSON(
        `/music/api/tracks/${track.track_id}/lyrics`);
      lyricsCache.set(track.track_id, response.lyrics ? parseLyrics(response.lyrics) : null);
    } catch (_error) {
      lyricsCache.set(track.track_id, null);
    }
  }
  if (!currentTrack || currentTrack.track_id !== track.track_id) return;  // 已切曲
  syncLyricsButton();
  const lyricsDocument = lyricsCache.get(track.track_id);
  const container = $("#fp-lyrics");
  if (!lyricsDocument || !lyricsDocument.lines.length) {
    cancelLyricsScroll();                  // 旧动画别再追已重铺的行
    container.innerHTML = '<div class="lyrics-empty">这首歌没有歌词</div>';
    return;
  }
  cancelLyricsScroll();
  container.innerHTML = lyricsDocument.lines.map((line) =>
    `<div class="lyrics-line" data-time="${line.timeSeconds}">${escapeHTML(line.text)}</div>`
  ).join("");
  // 无时间轴的歌词没有"当前句", 谈不上距离模糊 → 整页清晰
  container.classList.toggle("static", !lyricsDocument.synced);
  lyricsActiveIndex = -1;
  highlightActiveLyric();
}

/** timeupdate 驱动: 高亮行永远跟着歌走; 手动滑过就只亮不滚,
    静置片刻自动回位。 */
function highlightActiveLyric() {
  if (!lyricsViewOpen || !currentTrack) return;
  const lyricsDocument = lyricsCache.get(currentTrack.track_id);
  if (!lyricsDocument || !lyricsDocument.synced) return;
  const index = activeLyricIndex(lyricsDocument.lines, audioElement().currentTime);
  if (index !== lyricsActiveIndex) {
    lyricsActiveIndex = index;
    const container = $("#fp-lyrics");
    const lines = container.children;
    for (let position = 0; position < lines.length; position++) {
      lines[position].classList.toggle("active", position === index);
      // 距离模糊: 离当前句越近越清晰 (近一两句半模糊, 更远全模糊)
      const distance = Math.abs(position - index);
      lines[position].classList.toggle("near-1", distance === 1);
      lines[position].classList.toggle("near-2", distance === 2);
    }
    if (!lyricsFollowPaused && index >= 0 && lines[index]) {
      scrollLyricsTo(lines[index]);
    }
  }
  if (lyricsFollowPaused) maybeResumeLyricsFollow();
}

/** 歌词容器滚动到某行居中 —— rAF 指数缓出追目标, 丝滑滚动 (Apple Music 风):
    目标位置每帧重算 (行高跟着"放大动画"在变, 一次算死会差半行);
    Chrome 的 rAF 时间戳会回退, dt 钳制后再用。 */
let lyricsScrollRaf = 0;            // 在跑的动画帧句柄 (0 = 没在动)
let lyricsScrollTargetLine = null;  // 追踪中的行 (换曲重铺后作废)
let lyricsScrollLastTime = 0;       // 上一帧时刻 (算 dt)
let lyricsScrollGraceTimer = 0;     // 动画停后还把 scroll 事件当自己的宽限期

function scrollLyricsTo(lineElement) {
  const container = $("#fp-lyrics");
  if (!container.contains(lineElement)) return;   // 换曲重铺前的旧行: 别滚
  lyricsScrollTargetLine = lineElement;
  clearTimeout(lyricsScrollGraceTimer);
  lyricsAutoScrolling = true;
  if (!lyricsScrollRaf) {
    lyricsScrollLastTime = performance.now();
    lyricsScrollRaf = requestAnimationFrame(lyricsScrollFrame);
  }
}

function lyricsScrollFrame(now) {
  lyricsScrollRaf = 0;
  const container = $("#fp-lyrics");
  const line = lyricsScrollTargetLine;
  if (!line || !container.contains(line)) {
    endLyricsScroll();
    return;
  }
  const dt = Math.min(Math.max(now - lyricsScrollLastTime, 0), 40) / 1000;
  lyricsScrollLastTime = now;
  const target = line.offsetTop - container.clientHeight / 2
    + line.offsetHeight / 2;
  const remaining = target - container.scrollTop;
  if (Math.abs(remaining) < 1) {
    container.scrollTop = target;
    endLyricsScroll();
    return;
  }
  container.scrollTop += remaining * Math.min(1, dt * 10);   // 指数缓出
  lyricsScrollRaf = requestAnimationFrame(lyricsScrollFrame);
}

/** 动画到点收尾: 撤目标, scroll 事件的宽限再撑一小会儿。 */
function endLyricsScroll() {
  lyricsScrollTargetLine = null;
  clearTimeout(lyricsScrollGraceTimer);
  lyricsScrollGraceTimer = setTimeout(() => {
    lyricsAutoScrolling = false;
  }, 150);
}

/** 用户上手滚歌词: 立刻交还控制权 (别跟手指抢), 之后的滚动算手动。 */
function cancelLyricsScroll() {
  if (lyricsScrollRaf) cancelAnimationFrame(lyricsScrollRaf);
  lyricsScrollRaf = 0;
  lyricsScrollTargetLine = null;
  clearTimeout(lyricsScrollGraceTimer);
  lyricsAutoScrolling = false;
}

/** 手动滑过歌词后静置够了就回到跟唱。 */
function maybeResumeLyricsFollow() {
  if (!lyricsFollowPaused) return;
  if (Date.now() - lyricsLastScrollAt < LYRICS_FOLLOW_RESUME_MS) return;
  resumeLyricsFollow();
}

function resumeLyricsFollow(scrollToActive = true) {
  lyricsFollowPaused = false;
  $("#lyrics-resume").hidden = true;
  $("#fp-lyrics").classList.remove("browsing");   // 浏览态结束, 距离模糊回来
  const lines = $("#fp-lyrics").children;
  if (scrollToActive && lyricsActiveIndex >= 0 && lines[lyricsActiveIndex]) {
    scrollLyricsTo(lines[lyricsActiveIndex]);
  }
}

// ------------------------------------------------------------ 队列面板

// 同播放页: 收起 300ms 内重开要撤掉隐藏定时器; 滑出途中放行点击。
let queueHideTimer = 0;

function openQueueSheet() {
  clearTimeout(queueHideTimer);
  renderQueueSheet();
  $("#queue-mask").hidden = false;
  const sheet = $("#queue-sheet");
  sheet.hidden = false;
  sheet.style.pointerEvents = "";
  void sheet.offsetWidth;        // 同 openFullPlayer: 不等 rAF
  sheet.classList.add("open");
}

function closeQueueSheet() {
  const sheet = $("#queue-sheet");
  sheet.classList.remove("open");
  sheet.style.pointerEvents = "none";
  $("#queue-mask").hidden = true;      // 遮罩不等动画 (点穿比残影烦人)
  clearTimeout(queueHideTimer);
  queueHideTimer = setTimeout(() => {
    sheet.hidden = true;
    sheet.style.pointerEvents = "";
  }, 300);
}

function renderQueueSheet() {
  if (!playQueue) return;
  const upcoming = queueUpcoming(playQueue);
  const currentId = playerCurrentTrackId();
  $("#queue-list").innerHTML = upcoming.map(track => `
    <button class="queue-row${track.track_id === currentId ? " on" : ""}"
            data-queue-track-id="${track.track_id}">
      ${track.track_id === currentId ? ICON_BARS : ""}
      <span class="q-title">${escapeHTML(track.title)}</span>
      <span class="q-artist">${escapeHTML(track.artist)}</span>
    </button>`).join("") || '<div class="lyrics-empty">队列是空的</div>';
}

// ------------------------------------------------------------ 锁屏/控制中心

function updateMediaSession() {
  if (!("mediaSession" in navigator) || !currentTrack) return;
  const artwork = `/music/media/albums/${currentTrack.album_id}/artwork`;
  navigator.mediaSession.metadata = new MediaMetadata({
    title: currentTrack.title,
    artist: currentTrack.artist,
    album: currentTrack.album_title || "",
    artwork: [{ src: artwork, sizes: "512x512", type: "image/jpeg" }],
  });
  for (const action of ["play", "pause", "previoustrack", "nexttrack",
                        "seekto", "seekbackward", "seekforward"]) {
    try {
      navigator.mediaSession.setActionHandler(action, mediaSessionAction(action));
    } catch (_error) { /* 老浏览器不认识某些动作 */ }
  }
}

/** 锁屏/控制中心的进度快照: 暂停时速率报 0 (不然外推器以为还在播),
    位置钳在 [0, 时长] 里; 时长没就绪就不报 (浏览器会拒)。 */
function syncPositionState() {
  if (!("mediaSession" in navigator) || !currentTrack) return;
  const audio = audioElement();
  if (!isFinite(audio.duration) || audio.duration <= 0) return;
  try {
    navigator.mediaSession.setPositionState({
      duration: audio.duration,
      playbackRate: audio.paused ? 0 : audio.playbackRate,
      position: Math.min(Math.max(audio.currentTime, 0), audio.duration),
    });
  } catch (_error) { /* 个别浏览器挑参数, 不挡播放 */ }
}

function mediaSessionAction(action) {
  const audio = audioElement();
  switch (action) {
    case "play": return () => startAudio().catch(() => {});
    case "pause": return () => audio.pause();
    case "previoustrack": return () => playerPrevious();
    case "nexttrack": return () => playerNext();
    case "seekto":
      return (details) => {
        if (details && typeof details.seekTime === "number") {
          audio.currentTime = details.seekTime;
        }
      };
    case "seekbackward": return () => { audio.currentTime = Math.max(0, audio.currentTime - 10); };
    default: return () => { audio.currentTime = Math.min(
      audio.duration || 0, audio.currentTime + 10); };
  }
}

// ------------------------------------------------------------ 事件绑定

function bindPlayerEvents() {
  const audio = audioElement();

  // 按钮点击不冒泡到 #mini-open (点了暂停/下一首不该弹全屏页)
  $("#mini-play").addEventListener("click", (event) => { event.stopPropagation(); playerToggle(); });
  $("#mini-next").addEventListener("click", (event) => { event.stopPropagation(); playerNext(); });
  $("#mini-open").addEventListener("click", openFullPlayer);
  $("#fp-grab").addEventListener("click", () => {
    if (fpDismissDragged) {            // 刚拖过: 抬手补发的 click 不算
      fpDismissDragged = false;
      return;
    }
    closeFullPlayer();
  });
  bindDismissDrag($("#fp-grab"));
  bindDismissDrag($("#fp-art-wrap"), true);   // 封面: 下拉收起 + 左右划切歌
  $("#fp-play").addEventListener("click", playerToggle);
  $("#fp-next").addEventListener("click", playerNext);
  $("#fp-prev").addEventListener("click", playerPrevious);
  $("#fp-shuffle").addEventListener("click", () => {
    if (!playQueue) return;
    queueSetShuffle(playQueue, !playQueue.shuffle);
    updateShuffleRepeatButtons();
    renderQueueSheet();
    savePlayerState();
    toast(playQueue.shuffle ? "随机播放: 开" : "随机播放: 关");
  });
  $("#fp-repeat").addEventListener("click", () => {
    if (!playQueue) return;
    const mode = queueCycleRepeat(playQueue);
    updateShuffleRepeatButtons();
    savePlayerState();
    toast(mode === "all" ? "列表循环" : mode === "one" ? "单曲循环" : "循环: 关");
  });
  $("#fp-lyrics-btn").addEventListener("click", toggleLyricsView);
  $("#fp-queue-btn").addEventListener("click", openQueueSheet);
  $("#queue-close").addEventListener("click", closeQueueSheet);
  $("#queue-mask").addEventListener("click", closeQueueSheet);
  $("#lyrics-resume").addEventListener("click", resumeLyricsFollow);

  // 手动滑歌词 (程序定位引发的 scroll 不算) → 暂停跟唱 + 出"回到当前句";
  // 手指按下的那一刻先撤掉滚动动画, 之后的位置全算用户的。
  // 浏览期间整页取消模糊 (凑近了看), 静置或点行跳播后恢复距离模糊。
  $("#fp-lyrics").addEventListener("pointerdown", cancelLyricsScroll);
  $("#fp-lyrics").addEventListener("scroll", () => {
    if (lyricsAutoScrolling) return;
    if (!$("#fp-lyrics").classList.contains("static")) {   // 无时间轴: 没跟唱可暂停
      lyricsFollowPaused = true;
      $("#fp-lyrics").classList.add("browsing");
      $("#lyrics-resume").hidden = false;
    }
    lyricsLastScrollAt = Date.now();
  });

  $("#queue-list").addEventListener("click", (event) => {
    const row = event.target.closest("[data-queue-track-id]");
    if (!row || !playQueue) return;
    const track = queueJump(playQueue, Number(row.dataset.queueTrackId));
    if (track && track.playable) {
      loadTrack(track, true);
    } else {
      toast("这首浏览器播不了");
    }
  });

  $("#fp-lyrics").addEventListener("click", (event) => {
    const line = event.target.closest(".lyrics-line");
    if (!line) return;
    const time = Number(line.dataset.time);
    if (time >= 0) audioElement().currentTime = time;
    // 点行跳播 = 在新位置落座: 退出浏览态恢复模糊;
    // 不抢着滚, 紧跟的 timeupdate 会把新当前句滚居中
    resumeLyricsFollow(false);
  });

  // 滑杆命中层: iOS 的 range 输入点轨道不跳值、7px 滑钮抓不住 (音量条整个
  // 点不动)。输入框包一层透明垫子自己算比例 —— 按下即跳、拖动跟手;
  // 值写回 input 再补发 input/change, 既有 --fill/seek/存档逻辑全复用。
  const enhanceSliderTouch = (input) => {
    const wrap = document.createElement("div");
    wrap.className = "slider-hit";
    input.replaceWith(wrap);
    wrap.appendChild(input);
    let dragging = false;
    const apply = (clientX) => {
      const rect = wrap.getBoundingClientRect();
      if (rect.width <= 0) return;
      const min = Number(input.min);
      const max = Number(input.max);
      const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
      input.value = String(Math.round(min + ratio * (max - min)));
      input.dispatchEvent(new Event("input", { bubbles: true }));
    };
    wrap.addEventListener("pointerdown", (event) => {
      dragging = true;
      event.preventDefault();               // 别触发文字选择/页面滚动
      wrap.setPointerCapture(event.pointerId);
      apply(event.clientX);
    });
    wrap.addEventListener("pointermove", (event) => {
      if (dragging) apply(event.clientX);
    });
    const release = () => {
      if (!dragging) return;
      dragging = false;
      input.dispatchEvent(new Event("change", { bubbles: true }));
    };
    wrap.addEventListener("pointerup", release);
    wrap.addEventListener("pointercancel", release);
  };
  enhanceSliderTouch($("#fp-scrub"));
  enhanceSliderTouch($("#fp-volume"));

  const scrubber = $("#fp-scrub");
  // 时间文案照参考图: 左 = −已播, 右 = −剩余 (倒数式, 两边都带负号)
  const renderTimes = (current, total) => {
    $("#fp-time-cur").textContent = `-${formatPlaybackTime(current)}`;
    $("#fp-time-total").textContent =
      `-${formatPlaybackTime(Math.max(0, (total || 0) - current))}`;
  };
  scrubber.addEventListener("input", () => {
    scrubbing = true;
    const total = audio.duration || 0;
    const time = total * Number(scrubber.value) / 1000;
    renderTimes(time, total);
    scrubber.style.setProperty("--fill", `${scrubber.value / 10}%`);
  });
  const applyScrub = () => {
    if (!scrubbing) return;
    scrubbing = false;
    const total = audio.duration || 0;
    audio.currentTime = total * Number(scrubber.value) / 1000;
  };
  scrubber.addEventListener("change", applyScrub);
  scrubber.addEventListener("touchend", applyScrub);

  // 音量条: 原生 audio.volume 写得进的平台才留 (桌面/安卓)。
  // iOS 写了也白写 —— 整条收起, 音量交给手机音量键。
  const volumeSlider = $("#fp-volume");
  if (nativeVolumeWorks()) {
    const savedVolume = loadSavedVolume();
    volumeSlider.value = String(savedVolume);
    volumeSlider.style.setProperty("--fill", `${savedVolume}%`);
    applyVolume(savedVolume);
    volumeSlider.addEventListener("input", () => {
      const value = Number(volumeSlider.value);
      volumeSlider.style.setProperty("--fill", `${value}%`);
      applyVolume(value);
      try { localStorage.setItem("music-volume", String(value)); }
      catch (_e) { /* 存不上就不记, 不影响本次调节 */ }
    });
  } else {
    $("#full-player").classList.add("volume-off");
  }

  audio.addEventListener("playing", () => {
    // 真正出声了才算"听过" (恢复现场直接暂停的不算); 暂停续播不重复报
    if (playRecorded || !currentTrack) return;
    playRecorded = true;
    fetch("/music/api/plays", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ track_id: currentTrack.track_id }),
    }).catch(() => { /* 记不上不挡听歌 */ });
  });
  audio.addEventListener("play", updatePlayButtons);
  audio.addEventListener("pause", () => {
    updatePlayButtons();
    savePlayerState();
  });
  audio.addEventListener("loadedmetadata", () => {
    renderTimes(audio.currentTime, audio.duration);
    syncPositionState();
  });
  // 锁屏/控制中心的进度是浏览器拿「位置 + 流逝时间 × 速率」估的:
  // 暂停、跳句、拖动、变速后不重报, iPhone 锁屏进度条就会自顾自走
  // (暂停了还在爬、跳完对不上)。凡有动静都重报一次真实位置。
  for (const eventName of ["play", "pause", "seeked", "ratechange"]) {
    audio.addEventListener(eventName, syncPositionState);
  }
  audio.addEventListener("timeupdate", () => {
    const progress = audio.duration
      ? audio.currentTime / audio.duration : 0;
    $("#mini-progress").style.width = `${Math.round(progress * 100)}%`;
    if (!scrubbing) {
      const scrubber = $("#fp-scrub");
      scrubber.value = String(Math.round(progress * 1000));
      scrubber.style.setProperty("--fill", `${Math.round(progress * 100)}%`);
      renderTimes(audio.currentTime, audio.duration);
    }
    syncPositionState();
    highlightActiveLyric();
  });
  audio.addEventListener("ended", () => {
    if (playQueue && playQueue.repeat === "one") {   // 单曲循环: 回开头重播
      audio.currentTime = 0;
      startAudio().catch(() => {});
      return;
    }
    playerNext();
  });
  audio.addEventListener("error", () => {
    if (currentTrack) toast("这首播放失败了");
  });

  window.addEventListener("pagehide", savePlayerState);
  setInterval(() => { if (playerIsPlaying()) savePlayerState(); }, 5000);
}

bindPlayerEvents();
playerRestore();
