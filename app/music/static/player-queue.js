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

/** 0..count-1 洗匀 (Fisher-Yates)。 */
function shuffledIndices(count) {
  const indices = Array.from({ length: count }, (_, index) => index);
  for (let i = indices.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    const swap = indices[i];
    indices[i] = indices[j];
    indices[j] = swap;
  }
  return indices;
}

/**
 * 随机开关。打开: 当前曲提到首位、其余洗牌; 关闭: 回到专辑原顺序。
 * 正在播的曲不换, 只换后面的走向 —— 这是"播到一半开随机"的语义。
 * @param {PlayQueue} queue
 * @param {boolean} shuffle
 */
function queueSetShuffle(queue, shuffle) {
  const currentTrackIndex = queue.order[queue.position];
  queue.shuffle = shuffle;
  if (shuffle) {
    const indices = shuffledIndices(queue.tracks.length);
    if (currentTrackIndex !== undefined) {
      indices.splice(indices.indexOf(currentTrackIndex), 1);
      queue.order = [currentTrackIndex, ...indices];
      queue.position = 0;
    } else {
      queue.order = indices;
    }
  } else {
    queue.order = queue.tracks.map((_, index) => index);
    queue.position = currentTrackIndex === undefined ? -1 : currentTrackIndex;
  }
}

/**
 * 开播即随机 (列表/专辑页的「随机播放」键): 整队洗牌, 从洗出来的队首播。
 * 与 queueSetShuffle 是两个语义 —— 那个把当前曲钉在队首, 用在起播上
 * 就是"随机播放永远第一首" (1.7.0 后遗症, 用户点名)。
 * @param {PlayQueue} queue
 */
function queueShuffleAll(queue) {
  queue.shuffle = true;
  queue.order = shuffledIndices(queue.tracks.length);
  queue.position = queue.order.length ? 0 : -1;
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
 * 队列视图里拖行换位 (from/to 都是 order 表里的绝对位置, 调用方把
 * 视图下标 + queue.position 换算好)。当前曲被拖走时 position 跟着走;
 * 别的行跨过当前位时 position 相应增减, 保证当前曲不换。
 * @param {PlayQueue} queue
 * @param {number} from
 * @param {number} to
 * @returns {boolean} 挪没挪 (越界/原地返回 false)
 */
function queueReorder(queue, from, to) {
  if (from < 0 || to < 0 || from >= queue.order.length
      || to >= queue.order.length || from === to) return false;
  const [moved] = queue.order.splice(from, 1);
  queue.order.splice(to, 0, moved);
  if (queue.position === from) {
    queue.position = to;                       // 拖的就是当前曲: 跟着走
  } else if (from < queue.position && to >= queue.position) {
    queue.position -= 1;                       // 前面的行插到了当前位之后
  } else if (from > queue.position && to <= queue.position) {
    queue.position += 1;                       // 后面的行插到了当前位之前
  }
  return true;
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
    createPlayQueue, queueCurrent, queueSetShuffle, queueShuffleAll,
    queueCycleRepeat, queueAdvance, queueGoBack, queueJump, queueUpcoming,
    queueReorder,
  };
}
