// bookkeeping-merge.js — 记账同步的纯合并逻辑 (离线副本与服务器下行按 LWW 归并)。
// 单独成模块: node --test 直测 + c8 覆盖 (页面脚本由 E2E 覆盖)。
//
// 条目形状 (本地存储与服务器下行的超集):
//   { id, date: "YYYY-MM-DD", time: "HH:MM"|"", amount, kind: "expense"|"income",
//     category, tags: [标签…], note, deleted, updatedAt: ISO 时间串,
//     createdByName, updatedByName }
// 时间比较一律 new Date(...).getTime() —— 服务器带 +00:00、本地带 Z,
// 混格式字符串按字典序比会错。

// 归并一行: 服务器行要不要覆盖本地行 (本地缺失 / 不旧于本地才覆盖)。
// 平局 (时间戳相等) 也归服务器 —— 服务器回声带着解析好的记账人名,
// 本地自建的条目同步后靠这个换成真名; 真冲突时服务器本来就是权威。
function remoteWins(local, remote) {
  if (!local) return true;
  return new Date(remote.updatedAt).getTime() >= new Date(local.updatedAt).getTime();
}

// 本地副本与下行批量归并: 返回合并后的完整条目数组 (原有顺序, 新行插尾部)。
// 删除是墓碑 (deleted=true 保留在账本里, 展示层负责过滤)。
function mergeEntries(localEntries, remoteEntries) {
  const byId = new Map(localEntries.map(e => [e.id, e]));
  for (const remote of remoteEntries) {
    if (remoteWins(byId.get(remote.id), remote)) byId.set(remote.id, remote);
  }
  return [...byId.values()];
}

// 本地要上行的条目: 脏名单里的 (上次同步成功后有本地改动的 id)。
// 不用时间戳比较挑上行 —— 客户端时钟若慢于服务器, 新建条目的
// updatedAt 会早于上次同步游标, 按时间挑就永远漏传。
// 返回值是协议形状 (snake_case 的 updated_at), 与本地形状 (updatedAt) 区分。
function entriesToUpload(localEntries, dirtyIds) {
  const dirty = new Set(dirtyIds);
  return localEntries
    .filter(e => dirty.has(e.id))
    .map(({ id, date, time, amount, kind, category, tags, note, deleted, updatedAt }) =>
      ({ id, date, time: time || "", amount, kind, category, tags: tags || [],
         note, deleted, updated_at: updatedAt }));
}

// 从完整条目里挑出该展示的 (按月份 + 记账人 + 未删除)
function visibleEntries(entries, month, person) {
  return entries.filter(e => !e.deleted && e.date.startsWith(month) &&
    (!person || e.createdByName === person));
}

// 月度合计: {expense, income} (只算未删除的)
function monthTotals(entries, month) {
  let expense = 0, income = 0;
  for (const e of entries) {
    if (e.deleted || !e.date.startsWith(month)) continue;
    if (e.kind === "income") income += e.amount;
    else expense += e.amount;
  }
  return { expense, income };
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { mergeEntries, entriesToUpload, remoteWins, visibleEntries, monthTotals };
}
