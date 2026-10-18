import { test } from 'node:test';
import assert from 'node:assert/strict';
import { validateUpdatesSnapshot, filterUpdateEvents, groupUpdateEvents, summarizeUpdates, dailyUpdateEvents, dailyUpdateCounts, updateEventDate, updateDate, updatePeriod, updateSourceHealth, safeUpdateURL, updatesCSVTable, updatesCSVCell, timelineEvents, isUpdateFavorite, hasUpdateBefore, prioritizeUpdateEvents } from '../assets/project-updates.js';

const event = (id, extra = {}) => ({ id, population: 'public', entity_id: 'SSE_A', entity_kind: 'filing', project_name: '物流基金一期', exchange: '上交所', asset_type: '物流仓储', business_type: '首发', manager: '甲基金', origin: '甲集团', event_type: 'status_changed', title: '审核状态变化', before: { status: '已受理' }, after: { status: '已反馈' }, official_date: '2026-10-14', detected_at: '2026-10-16T08:00:00+08:00', discovery_type: 'observed', source_url: 'https://www.sse.com.cn/reits/info/', changes: [{ field: 'status', label: '审核状态', before: '已受理', after: '已反馈' }], ...extra });
const events = [event('a'), event('b', { event_type: 'document_added' }), event('c', { population: 'institutional', entity_id: 'SZSE_C', exchange: '深交所', business_type: '扩募', project_name: '能源项目', asset_type: '能源' }), event('d', { population: 'ndrc', entity_id: 'NDRC_D', entity_kind: 'recommendation', project_name: '新购入项目', official_date: '2026-10-12', discovery_type: 'baseline', is_baseline: true }), event('e', { entity_id: 'OLD', official_date: '2026-08-01', detected_at: '2026-10-16T10:00:00+08:00' })];
const data = { schema_version: 1, as_of_date: '2026-10-16', generated_at: '2026-10-16T08:00:00+08:00', events, projects: [], sources: {} };

test('validates event identity and explicit increment metadata', () => {
  assert.equal(validateUpdatesSnapshot(data), data);
  assert.throws(() => validateUpdatesSnapshot({ ...data, events: [event('a'), event('a')] }));
  assert.throws(() => validateUpdatesSnapshot({ ...data, events: [event('a', { detected_at: null })] }));
  assert.throws(() => validateUpdatesSnapshot({ ...data, events: [event('a', { population: 'unknown' })] }));
  assert.throws(() => validateUpdatesSnapshot({ ...data, events: [event('a', { is_incremental: 'true' })] }));
  const archived = { ...data, events: [event('archived', { is_incremental: false, detected_at: null, official_date: null })] };
  assert.equal(validateUpdatesSnapshot(archived), archived);
});
test('every record archives by official date and never substitutes a collection or legacy event date', () => {
  assert.equal(updateEventDate(events[4]), '2026-08-01');
  assert.equal(updateEventDate(events[3]), '2026-10-12');
  assert.equal(updateEventDate(event('unknown', { official_date: null, event_date: '2026-10-16' })), '');
  assert.equal(updateDate('2026-10-16T17:30:00Z'), '2026-10-17');
  const result = filterUpdateEvents(events, {}, new Set(), '2026-10-16');
  assert.equal(result.length, 5);
  assert.ok(result.some(item => item.is_baseline));
  assert.equal(filterUpdateEvents(events, {}, new Set(), '2026-10-24').length, 5);
  assert.deepEqual(result.map(item => item.id), ['a', 'b', 'c', 'd', 'e']);
});
test('daily counts use Beijing collection dates with inclusive midnight boundaries', () => {
  const boundaryEvents = [
    event('previous-day', { detected_at: '2026-10-15T15:59:59Z', is_incremental: true }),
    event('start', { detected_at: '2026-10-15T16:00:00Z', is_incremental: true }),
    event('last-second', { population: 'institutional', detected_at: '2026-10-16T15:59:59Z', is_incremental: true }),
    event('next-day', { population: 'ndrc', detected_at: '2026-10-16T16:00:00Z', is_incremental: true }),
    event('older', { detected_at: '2026-10-14T08:00:00+08:00', is_incremental: true }),
    event('future', { detected_at: '2026-10-18T08:00:00+08:00', is_incremental: true })
  ];
  assert.deepEqual(dailyUpdateCounts(boundaryEvents, '2026-10-16'), { public: 1, institutional: 1, ndrc: 0 });
  assert.deepEqual(dailyUpdateCounts(boundaryEvents, '2026-10-17'), { public: 0, institutional: 0, ndrc: 1 });
  assert.deepEqual(dailyUpdateCounts([], '2026-10-16'), { public: 0, institutional: 0, ndrc: 0 });
});
test('explicit increment flags control today independently of legacy classifications', () => {
  const markers = [{ is_baseline: true }, { is_backfill: true }, { discovery_type: 'baseline' }, { discovery_type: 'backfill' }, { discovery_type: 'historical' }];
  const legacy = markers.map((marker, index) => event(`legacy-${index}`, marker));
  assert.deepEqual(dailyUpdateCounts(legacy, '2026-10-16'), { public: 0, institutional: 0, ndrc: 0 });
  const current = markers.map((marker, index) => event(`current-${index}`, { ...marker, is_incremental: true }));
  current.push(event('migration', { is_incremental: false }));
  assert.deepEqual(dailyUpdateCounts(current, '2026-10-16'), { public: 5, institutional: 0, ndrc: 0 });
  assert.deepEqual(dailyUpdateCounts([event('legacy-observed')], '2026-10-16'), { public: 1, institutional: 0, ndrc: 0 });
});
test('today accumulates distinct increments while old or missing official dates remain eligible', () => {
  const dailyEvents = [
    event('status', { official_date: '2026-08-01', is_incremental: true }),
    event('document', { official_date: '2026-08-01', event_type: 'documents_added', detected_at: '2026-10-16T14:00:00+08:00', is_incremental: true }),
    event('recommendation', { population: 'ndrc', official_date: null, is_incremental: true }),
    event('old-collection', { official_date: '2026-10-16', detected_at: '2026-10-15T08:00:00+08:00', is_incremental: true }),
    event('missing-collection', { official_date: '2026-10-16', event_date: '2026-10-16', detected_at: null, is_incremental: true }),
    event('invalid-collection', { official_date: '2026-10-16', detected_at: 'not-a-date', is_incremental: true }),
    event('migration', { is_incremental: false })
  ];
  dailyEvents.push({ ...dailyEvents[0] });
  assert.deepEqual(dailyUpdateCounts(dailyEvents, '2026-10-16'), { public: 2, institutional: 0, ndrc: 1 });
  assert.deepEqual(dailyUpdateEvents(dailyEvents, '', '2026-10-16').map(item => item.id), ['document', 'status', 'recommendation']);
});
test('today population filters and library filters are independent', () => {
  const dailyEvents = [
    event('public-old', { official_date: '2026-08-01', detected_at: '2026-10-16T00:00:00+08:00', is_incremental: true }),
    event('institutional', { population: 'institutional', detected_at: '2026-10-16T09:00:00+08:00', is_incremental: true }),
    event('public-unknown', { official_date: null, detected_at: '2026-10-16T10:00:00+08:00', is_incremental: true }),
    event('ndrc', { population: 'ndrc', detected_at: '2026-10-16T12:00:00+08:00', is_incremental: true }),
    event('previous-day', { official_date: '2026-10-16', detected_at: '2026-10-15T23:59:59+08:00', is_incremental: true }),
    event('future', { detected_at: '2026-10-17T00:00:00+08:00', is_incremental: true })
  ];
  const originalOrder = dailyEvents.map(item => item.id);
  const library = filterUpdateEvents(dailyEvents, { population: 'ndrc', range: 'custom', start: '2026-10-14', end: '2026-10-14' }, new Set(), '2026-10-16');
  assert.deepEqual(library.map(item => item.id), ['ndrc']);
  assert.deepEqual(dailyUpdateEvents(dailyEvents, 'public', '2026-10-16').map(item => item.id), ['public-old', 'public-unknown']);
  assert.deepEqual(dailyUpdateEvents(dailyEvents, 'institutional', '2026-10-16').map(item => item.id), ['institutional']);
  assert.deepEqual(dailyUpdateEvents(dailyEvents, 'ndrc', '2026-10-16').map(item => item.id), ['ndrc']);
  assert.deepEqual(dailyUpdateEvents(dailyEvents, 'public', '2026-10-18'), []);
  assert.deepEqual(dailyEvents.map(item => item.id), originalOrder);
});
test('specific official-date ranges are inclusive and exclude unknown dates', () => {
  assert.deepEqual(updatePeriod({ range: '7' }, '2026-10-16'), { start: '2026-10-10', end: '2026-10-16', valid: true });
  assert.deepEqual(updatePeriod({ range: '30' }, '2026-10-16'), { start: '2026-09-17', end: '2026-10-16', valid: true });
  assert.equal(filterUpdateEvents(events, { range: 'custom', start: '2026-10-17', end: '2026-10-16' }, new Set(), '2026-10-16').length, 0);
  assert.equal(filterUpdateEvents(events, { range: 'custom', start: '2026-10-14', end: '2026-10-14' }, new Set(), '2026-10-16').length, 3);
  const unknown = event('unknown', { official_date: null });
  for (const range of ['7', '30', 'custom']) assert.deepEqual(filterUpdateEvents([unknown], { range }, new Set(), '2026-10-16'), []);
});
test('full library includes all records, with unknown official dates after dated records', () => {
  const libraryEvents = [
    event('current'),
    event('old', { official_date: '2026-08-01' }),
    event('previously-baseline', { official_date: '2026-07-01', discovery_type: 'baseline', is_incremental: false }),
    event('unknown', { official_date: null, event_date: '2026-10-16', detected_at: '2026-10-20T08:00:00+08:00' }),
    event('future-official', { official_date: '2026-10-20' })
  ];
  assert.deepEqual(updatePeriod({ range: 'all' }, '2026-10-16'), { start: '', end: '', valid: true });
  for (const range of ['7', '30']) assert.deepEqual(filterUpdateEvents(libraryEvents, { range }, new Set(), '2026-10-16').map(item => item.id), ['current']);
  const selected = filterUpdateEvents(libraryEvents, {}, new Set(), '2026-10-16');
  assert.deepEqual(selected.map(item => item.id), ['future-official', 'current', 'old', 'previously-baseline', 'unknown']);
  assert.equal(groupUpdateEvents(selected).at(-1).date, '');
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
  const collectedVersions = [event('v1', { source_version: { sha256: 'one' } }), event('v2', { is_baseline: true, is_incremental: false, detected_at: '2026-10-17T08:00:00+08:00', source_version: { sha256: 'two' } })];
  assert.equal(groupUpdateEvents(collectedVersions).length, 1);
  assert.equal(groupUpdateEvents([event('date1'), event('date2', { official_date: '2026-10-15' })]).length, 2);
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
test('manual association maintenance never enters the library, timeline, today counts or CSV', () => {
  const source = [
    event('business'),
    event('internal', { internal_only: true, is_incremental: true }),
    event('legacy-title', { title: '关联资料修订', is_incremental: true }),
    event('legacy-change', { changes: [{ field: 'related_entity_ids', before: [], after: ['NDRC'] }], is_incremental: true })
  ];
  assert.deepEqual(filterUpdateEvents(source).map(item => item.id), ['business']);
  assert.deepEqual(timelineEvents(source, source[0]).map(item => item.id), ['business']);
  assert.deepEqual(dailyUpdateCounts(source, '2026-10-16'), { public: 1, institutional: 0, ndrc: 0 });
  assert.equal(updatesCSVTable(source).length, 2);
});
test('CSV carries one official record date and no collection or classification fields', () => {
  const rows = updatesCSVTable([event('older', { source_version: { sha256: 'source-hash', path: 'data/public.json', retained_path: 'data/snapshots/public.json', collected_at: '2026-10-16T09:21:47+08:00' } }), event('unknown', { official_date: null, event_type: 'historical_milestone' })], data);
  const header = rows[0];
  assert.equal(header.length, 20);
  assert.equal(rows[1][header.indexOf('官方日期')], '2026-10-14');
  assert.equal(rows[2][header.indexOf('官方日期')], '');
  assert.equal(rows[2][header.indexOf('事件类型')], '阶段进展');
  for (const label of ['首次发现时间', '列表日期', '记录性质']) assert.ok(!header.includes(label));
  assert.ok(rows.every(row => row.length === header.length));
  assert.equal(rows[1][header.indexOf('官方来源')], 'https://www.sse.com.cn/reits/info/');
  assert.equal(rows[1][header.indexOf('来源版本')], 'sha256：source-hash；path：data/public.json；retained_path：data/snapshots/public.json');
  assert.ok(!JSON.stringify(rows).includes('collected_at'));
  assert.ok(!JSON.stringify(rows).includes('2026-10-16T09:21:47+08:00'));
});
test('timeline sorting uses official dates with unknown dates last, preserving source event data', () => {
  const source = [event('unknown', { official_date: null, event_date: '2026-10-20' }), event('old', { official_date: '2026-01-01' }), event('recent', { official_date: '2026-10-14', detected_at: '2026-01-01T00:00:00+08:00' })];
  assert.deepEqual(timelineEvents(source, source[0]).map(item => item.id), ['recent', 'old', 'unknown']);
  assert.deepEqual(source.map(item => item.id), ['unknown', 'old', 'recent']);
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
