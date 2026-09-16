// music-player-state — My Music 播放器共享状态: 常量/队列与歌词等顶层数据 + audio 元素访问。
// 拆自 music-player.js (结构化重构: 代码逐字节未动, 按 music.html 里的顺序加载, 跨模块引用走全局)。
"use strict";
/* global $ */
/* exported LYRICS_FOLLOW_RESUME_MS, PLAYER_STATE_KEY, audioElement, currentTrack,
            lyricsActiveIndex, lyricsAutoScrolling, lyricsCache, lyricsFollowPaused,
            lyricsLastScrollAt, lyricsViewOpen, playQueue, playRecorded, prefetchSequence,
            prefetched, queueDrag, queueViewOpen, scrubbing, trackChangeListeners */

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
let queueViewOpen = false;           // 封面区翻开成队列视图 (与歌词视图二选一)
let queueDrag = null;                // 队列拖拽换位进行中 (null = 没在拖)
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

