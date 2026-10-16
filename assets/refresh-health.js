/* Both populations use the same Beijing morning freshness rule. */
export const REFRESH_SCHEDULE = '每日07:37起 · 08:00前为目标';

export function refreshWarning(snapshot, now = new Date()) {
  if (!snapshot) return '';
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', hourCycle: 'h23'
  }).formatToParts(now).map(part => [part.type, part.value]));
  const today = `${parts.year}-${parts.month}-${parts.day}`;
  const date = snapshot.refresh_batch?.date || snapshot.date;
  if (date && date < today && Number(parts.hour) >= 8) {
    return `今日刷新尚未完成，当前展示${date}的快照。云端将在早间继续补查，最近一次采集时间见页尾。`;
  }
  return '';
}
