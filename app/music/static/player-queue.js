// player-queue.js — 播放队列纯逻辑 (顺序 / 随机洗牌 / 循环 / 前进后退 / 跳转)。
// 队列状态是一个普通对象, 由页面脚本持有; 这里只提供状态转移函数,
// node --test 直测 + tsc --checkJs + c8 覆盖 (页面脚本由 E2E 覆盖)。

/**
 * 循环模式: off = 播完即停, all = 全队循环, one = 单曲循环
 * (单曲循环由调用方在曲目自然播完时自行 seek 0, 队列层不感知)。
 * @typedef {"off"|"all"|"one"} RepeatMode
 */

/**
 * 播放队列。
 * @typedef {Object} PlayQueue
 * @property {Array<Object>} tracks 队列里的曲目 (后端 TrackBrief 形状)
 * @property {number[]} order       播放顺序 (tracks 的下标序列; 随机时被打乱)
 * @property {number} position      当前播到 order 的第几位
 * @property {boolean} shuffle
 * @property {RepeatMode} repeat
 */

/**
 * 建队列: tracks 从头到尾按原顺序播, 从 startIndex 那首开始。
 * 空列表也会得到合法队列 (当前曲为 null)。
 * @param {Array<Object>} tracks
 * @param {number} [startIndex]
 * @returns {PlayQueue}
 */
function createPlayQueue(tracks, startIndex) {
  const start = startIndex === undefined ? 0 : startIndex;
  const order = tracks.map((_, index) => index);
  return {
    tracks: tracks.slice(),
    order,
    position: order.length ? Math.min(Math.max(0, start), order.length - 1) : -1,
    shuffle: false,
    repeat: "off",
  };
}

/**
 * 当前曲目 (没在播/空队列返回 null)。
 * @param {PlayQueue} queue
 * @returns {Object|null}
 */
function queueCurrent(queue) {
  const trackIndex = queue.order[queue.position];
  return trackIndex === undefined ? null : (queue.tracks[trackIndex] || null);
}

/**
 * 随机开关。打开: 当前曲提到首位、其余洗牌; 关闭: 回到专辑原顺序。
 * 正在播的曲不换, 只换后面的走向。
 * @param {PlayQueue} queue
 * @param {boolean} shuffle
 */
function queueSetShuffle(queue, shuffle) {
  const currentTrackIndex = queue.order[queue.position];
  queue.shuffle = shuffle;
  const indices = queue.tracks.map((_, index) => index);
  if (shuffle) {
    for (let i = indices.length - 1; i > 0; i--) {   // Fisher-Yates
      const j = Math.floor(Math.random() * (i + 1));
      const swap = indices[i];
      indices[i] = indices[j];
      indices[j] = swap;
    }
    if (currentTrackIndex !== undefined) {
      indices.splice(indices.indexOf(currentTrackIndex), 1);
      queue.order = [currentTrackIndex, ...indices];
      queue.position = 0;
    } else {
      queue.order = indices;
    }
  } else {
    queue.order = indices;
    queue.position = currentTrackIndex === undefined ? -1 : currentTrackIndex;
  }
}

/**
 * 循环模式循环切换: 关 → 全部循环 → 单曲循环 → 关。
 * @param {PlayQueue} queue
 * @returns {RepeatMode} 切换后的模式
 */
function queueCycleRepeat(queue) {
  queue.repeat = queue.repeat === "off" ? "all"
    : queue.repeat === "all" ? "one" : "off";
  return queue.repeat;
}

/**
 * 前进一位: 队尾时 all 模式回绕到队首, 其他模式停在队尾返回 null
 * (调用方以此停播)。单曲循环想重播由调用方在 natural end 自己处理。
 * @param {PlayQueue} queue
 * @returns {Object|null} 下一首 (null = 到头了)
 */
function queueAdvance(queue) {
  if (!queue.order.length) return null;
  if (queue.position >= queue.order.length - 1) {
    if (queue.repeat !== "all") return null;
    queue.position = 0;
  } else {
    queue.position += 1;
  }
  return queueCurrent(queue);
}

/**
 * 后退一位; 已在队首时原地返回当前曲 (调用方 seek 0 重播, 苹果同款)。
 * @param {PlayQueue} queue
 * @returns {Object|null}
 */
function queueGoBack(queue) {
  if (queue.position > 0) queue.position -= 1;
  return queueCurrent(queue);
}

/**
 * 跳到队列里指定曲目 (点队列列表/搜索结果/歌词命中)。
 * @param {PlayQueue} queue
 * @param {number|string} trackId 曲目 id (TrackBrief.track_id)
 * @returns {Object|null} 跳到的那首 (null = 队列里没有)
 */
function queueJump(queue, trackId) {
  const trackIndex = queue.tracks.findIndex(
    (track) => track && track.track_id === trackId);
  if (trackIndex < 0) return null;
  const position = queue.order.indexOf(trackIndex);
  if (position < 0) return null;         // 顺序表缺了下标, 防御
  queue.position = position;
  return queueCurrent(queue);
}

/**
 * 队列从当前位开始的剩余播放顺序 (队列面板展示用, 含当前曲)。
 * @param {PlayQueue} queue
 * @returns {Array<Object>}
 */
function queueUpcoming(queue) {
  return queue.order.slice(Math.max(0, queue.position))
    .map((trackIndex) => queue.tracks[trackIndex])
    .filter(Boolean);
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    createPlayQueue, queueCurrent, queueSetShuffle, queueCycleRepeat,
    queueAdvance, queueGoBack, queueJump, queueUpcoming,
  };
}
