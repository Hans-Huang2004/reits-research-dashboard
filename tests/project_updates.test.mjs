import { test } from 'node:test';
import assert from 'node:assert/strict';
import { validateUpdatesSnapshot, filterUpdateEvents, groupUpdateEvents, summarizeUpdates, dailyUpdateCounts, updateEventDate, updateDate, updatePeriod, updateSourceHealth, safeUpdateURL, updatesCSVTable, updatesCSVCell, timelineEvents, isUpdateFavorite, hasUpdateBefore, prioritizeUpdateEvents } from '../assets/project-updates.js';

const event = (id, extra = {}) => ({ id, population: 'public', entity_id: 'SSE_A', entity_kind: 'filing', project_name: '物流基金一期', exchange: '上交所', asset_type: '物流仓储', business_type: '首发', manager: '甲基金', origin: '甲集团', event_type: 'status_changed', title: '审核状态变化', before: { status: '已受理' }, after: { status: '已反馈' }, official_date: '2026-10-14', detected_at: '2026-10-16T08:00:00+08:00', discovery_type: 'observed', source_url: 'https://www.sse.com.cn/reits/info/', changes: [{ field: 'status', label: '审核状态', before: '已受理', after: '已反馈' }], ...extra });
const events = [event('a'), event('b', { event_type: 'document_added' }), event('c', { population: 'institutional', entity_id: 'SZSE_C', exchange: '深交所', business_type: '扩募', project_name: '能源项目', asset_type: '能源' }), event('d', { population: 'ndrc', entity_id: 'NDRC_D', entity_kind: 'recommendation', project_name: '新购入项目', official_date: '2026-10-12', discovery_type: 'baseline', is_baseline: true }), event('e', { entity_id: 'OLD', official_date: '2026-08-01', detected_at: '2026-10-16T10:00:00+08:00' })];
const data = { schema_version: 1, as_of_date: '2026-10-16', generated_at: '2026-10-16T08:00:00+08:00', events, projects: [], sources: {} };

test('validates event identity and requires observed discovery dates', () => {
  assert.equal(validateUpdatesSnapshot(data), data);
  assert.throws(() => validateUpdatesSnapshot({ ...data, events: [event('a'), event('a')] }));
  assert.throws(() => validateUpdatesSnapshot({ ...data, events: [event('a', { detected_at: null })] }));
  assert.throws(() => validateUpdatesSnapshot({ ...data, events: [event('a', { population: 'unknown' })] }));
});
test('observed events use discovery date while historical backfill uses official date', () => {
  assert.equal(updateEventDate(events[4]), '2026-10-16');
  assert.equal(updateEventDate(events[3]), '2026-10-12');
  assert.equal(updateDate('2026-10-16T17:30:00Z'), '2026-10-17');
  const result = filterUpdateEvents(events, {}, new Set(), '2026-10-16');
  assert.equal(result.length, 4);
  assert.ok(!result.some(item => item.is_baseline));
  assert.equal(filterUpdateEvents(events, { includeHistory: true }, new Set(), '2026-10-16').length, 5);
  assert.equal(filterUpdateEvents(events, { includeHistory: true }, new Set(), '2026-10-24').length, 0);
});
test('daily counts use Beijing discovery dates with inclusive midnight boundaries', () => {
  const boundaryEvents = [
    event('previous-day', { detected_at: '2026-10-15T15:59:59Z' }),
    event('start', { detected_at: '2026-10-15T16:00:00Z' }),
    event('last-second', { population: 'institutional', detected_at: '2026-10-16T15:59:59Z' }),
    event('next-day', { population: 'ndrc', detected_at: '2026-10-16T16:00:00Z' }),
    event('older', { detected_at: '2026-10-14T08:00:00+08:00' }),
    event('future', { detected_at: '2026-10-18T08:00:00+08:00' })
  ];
  assert.deepEqual(dailyUpdateCounts(boundaryEvents, '2026-10-16'), { public: 1, institutional: 1, ndrc: 0 });
  assert.deepEqual(dailyUpdateCounts(boundaryEvents, '2026-10-17'), { public: 0, institutional: 0, ndrc: 1 });
  assert.deepEqual(dailyUpdateCounts([], '2026-10-16'), { public: 0, institutional: 0, ndrc: 0 });
});
test('daily counts exclude every historical marker even when discovered today', () => {
  const historicalMarkers = [
    { is_baseline: true }, { is_backfill: true },
    { discovery_type: 'baseline' }, { discovery_type: 'backfill' }, { discovery_type: 'historical' }
  ];
  const history = historicalMarkers.map((marker, index) => event(`history-${index}`, { official_date: '2026-10-16', ...marker }));
  assert.deepEqual(dailyUpdateCounts(history, '2026-10-16'), { public: 0, institutional: 0, ndrc: 0 });
});
test('daily counts count each event and never substitute official dates for discovery dates', () => {
  const dailyEvents = [
    event('status', { official_date: '2026-08-01' }),
    event('document', { official_date: '2026-08-01', event_type: 'documents_added' }),
    event('recommendation', { population: 'ndrc', official_date: '2026-08-01' }),
    event('old-discovery', { official_date: '2026-10-16', detected_at: '2026-10-15T08:00:00+08:00' }),
    event('missing-discovery', { official_date: '2026-10-16', event_date: '2026-10-16', detected_at: null }),
    event('invalid-discovery', { official_date: '2026-10-16', detected_at: 'not-a-date' })
  ];
  assert.deepEqual(dailyUpdateCounts(dailyEvents, '2026-10-16'), { public: 2, institutional: 0, ndrc: 1 });
  assert.equal(dailyEvents[0].entity_id, dailyEvents[1].entity_id);
  assert.deepEqual(dailyEvents.map(item => item.id), ['status', 'document', 'recommendation', 'old-discovery', 'missing-discovery', 'invalid-discovery']);
});
test('ranges are inclusive and invalid custom dates return no records', () => {
  assert.deepEqual(updatePeriod({ range: '7' }, '2026-10-16'), { start: '2026-10-10', end: '2026-10-16', valid: true });
  assert.deepEqual(updatePeriod({ range: '30' }, '2026-10-16'), { start: '2026-09-17', end: '2026-10-16', valid: true });
  assert.equal(filterUpdateEvents(events, { range: 'custom', start: '2026-10-17', end: '2026-10-16' }, new Set(), '2026-10-16').length, 0);
  assert.equal(filterUpdateEvents(events, { range: 'custom', start: '2026-10-16', end: '2026-10-16' }, new Set(), '2026-10-16').length, 4);
});
test('all filters intersect and search covers institutions and codes', () => {
  assert.deepEqual(filterUpdateEvents(events, { population: 'institutional', exchange: '深交所', asset: '能源', business: '扩募', search: '能源' }, new Set(), '2026-10-16').map(item => item.id), ['c']);
  assert.equal(filterUpdateEvents(events, { search: '甲集团', type: 'document_added' }, new Set(), '2026-10-16').length, 1);
  assert.deepEqual(filterUpdateEvents(events, { savedOnly: true }, new Set(['public:filing:SSE_A']), '2026-10-16').map(item => item.id), ['a', 'b']);
  assert.deepEqual(filterUpdateEvents(events, { savedOnly: true }, new Set(['event:SSE_A']), '2026-10-16').map(item => item.id), ['a', 'b']);
  assert.equal(isUpdateFavorite(event('f', { fund_id: 'FUND_1' }), new Set(['fund:FUND_1'])), true);
  assert.deepEqual(events.map(item => item.id), ['a', 'b', 'c', 'd', 'e']);
});
test('same entity batch and date merge visually while statistics and CSV count every event', () => {
  const selected = filterUpdateEvents(events, { population: 'public', search: '一期' }, new Set(), '2026-10-16');
  const summary = summarizeUpdates(selected);
  assert.equal(summary.total, 3);
  assert.equal(summary.groups, 2);
  assert.equal(summary.projects, 2);
  assert.equal(summary.public, 3);
  assert.equal(groupUpdateEvents(selected).find(group => group.event.entity_id === 'SSE_A').events.length, 2);
  assert.equal(updatesCSVTable(selected, data).length - 1, summary.total);
  assert.equal(groupUpdateEvents([event('a'), event('b', { business_type: '扩募' })]).length, 2);
});
test('failed or stale sources cannot imply a successful no-change check', () => {
  const health = updateSourceHealth({ public: { complete: true, checked_at: '2026-10-16T08:00:00+08:00' }, institutional: { complete: false, checked_at: '2026-10-16' }, ndrc: { complete: true, checked_at: '2026-10-15' } }, '2026-10-16');
  assert.equal(health[0].healthy, true);
  assert.equal(health[1].issue, '核查未完成');
  assert.equal(health[2].issue, '待刷新');
  assert.equal(updateSourceHealth({}, '2026-10-16').filter(source => !source.healthy).length, 3);
  assert.equal(updateSourceHealth({ public: { complete: true, status: 'failure', checked_at: '2026-10-16', error: 'timeout' } }, '2026-10-16')[0].issue, '核查失败');
});
test('timeline joins only explicit relationships and retains expansion identities', () => {
  const root = event('a', { related_entity_ids: ['NDRC_D'] });
  const selected = timelineEvents([...events, event('f', { entity_id: 'EXPANSION', business_type: '扩募', related_entity_ids: ['SSE_A'] }), event('unrelated', { entity_id: 'U', project_name: root.project_name })], root);
  assert.deepEqual(new Set(selected.map(item => item.id)), new Set(['a', 'b', 'd', 'f']));
});
test('official URLs reject unsafe protocols, credentials and misleading domains; CSV blocks formulas', () => {
  assert.equal(safeUpdateURL('https://www.sse.com.cn/reits/'), 'https://www.sse.com.cn/reits/');
  assert.equal(safeUpdateURL('https://reitsgl.tzxm.gov.cn:8881/reits/'), 'https://reitsgl.tzxm.gov.cn:8881/reits/');
  for (const value of ['javascript:alert(1)', 'http://www.sse.com.cn/', 'https://www.sse.com.cn.evil.test/', 'https://name:secret@www.szse.cn/']) assert.equal(safeUpdateURL(value), '');
  assert.equal(updatesCSVCell(' =SUM(A1)'), '"\' =SUM(A1)"');
  assert.equal(updatesCSVCell('a"b'), '"a""b"');
  const row = updatesCSVTable([event('zero', { before: 0, after: false })], data);
  assert.equal(row[1][row[0].indexOf('变化前')], '0');
  assert.equal(row[1][row[0].indexOf('变化后')], '否');
});
test('new evidence does not claim an absent disclosure and milestones lead grouped documents', () => {
  for (const value of [null, undefined, '', [], {}]) assert.equal(hasUpdateBefore(value), false);
  for (const value of [0, false, '已受理', ['旧文件']]) assert.equal(hasUpdateBefore(value), true);
  const source = [event('doc', { event_type: 'documents_added' }), event('date', { event_type: 'milestone' }), event('status', { event_type: 'status_change' })];
  assert.deepEqual(prioritizeUpdateEvents(source).map(item => item.id), ['status', 'date', 'doc']);
  assert.deepEqual(source.map(item => item.id), ['doc', 'date', 'status']);
});
