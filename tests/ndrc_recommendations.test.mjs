import { test } from 'node:test';
import assert from 'node:assert/strict';
import { validateNdrcSnapshot, filterNdrcItems, ndrcSummary, isRecentDiscovery, ndrcCSVTable, ndrcCSVCell, safeNdrcURL, ndrcEvidenceDetailsHTML } from '../assets/ndrc-recommendations.js';

const item = (id, extra = {}) => ({ id, name: `推荐项目${id}`, recommended_date: '2026-09-10', applicant_region: '北京市', industry_official: '园区基础设施', proposed_fund_amount_yi: 12, business_type: '首发', match_status: 'unmatched', relations: [], candidates: [], source_url: 'https://example.gov.cn/list', first_seen_at: '2026-10-16T08:00:00+08:00', discovery_type: 'baseline', ...extra });
const data = { date: '2026-10-16', updated_at: '2026-10-16T08:00:00+08:00', changes: { baseline: true, new_ids: [] }, items: [item('a'), item('b', { recommended_date: '2025-08-01', applicant_region: '广东省', business_type: '新购入', match_status: 'candidate', candidates: [{ event_name: '候选物流项目', exchange_event_id: 'e2' }] }), item('c', { name: '能源项目', industry_official: '能源基础设施', match_status: 'confirmed', relations: [{ exchange_event_id: 'e1', fund_id: 'f1', business_type: '扩募', evidence_urls: ['https://www.sse.com.cn/evidence.pdf'] }] })] };

test('recommendation validation rejects duplicate IDs and invalid structural fields', () => {
  assert.equal(validateNdrcSnapshot(data), data);
  assert.throws(() => validateNdrcSnapshot({ ...data, items: [item('a'), item('a')] }));
  assert.throws(() => validateNdrcSnapshot({ ...data, items: [item('a', { match_status: '已上市' })] }));
  assert.throws(() => validateNdrcSnapshot({ ...data, items: [item('a', { proposed_fund_amount_yi: -1 })] }));
});
test('filters intersect without mutating input and recommendation dates default newest first', () => {
  assert.deepEqual(filterNdrcItems(data.items).map(row => row.id), ['a', 'c', 'b']);
  assert.deepEqual(filterNdrcItems(data.items, { year: '2026', industry: '能源基础设施', match: 'confirmed' }).map(row => row.id), ['c']);
  assert.deepEqual(filterNdrcItems(data.items, { business: '新购入', region: '广东省', direction: 1 }).map(row => row.id), ['b']);
  assert.deepEqual(data.items.map(row => row.id), ['a', 'b', 'c']);
});
test('search covers confirmed and candidate names while favorites use stable recommendation IDs', () => {
  const resolver = { getPublicFund: id => id === 'f1' ? { short_name: '能源基金', code: '508001' } : null };
  assert.deepEqual(filterNdrcItems(data.items, { search: '508001' }, data, new Set(), resolver).map(row => row.id), ['c']);
  assert.deepEqual(filterNdrcItems(data.items, { search: '候选物流' }).map(row => row.id), ['b']);
  assert.deepEqual(filterNdrcItems(data.items, { savedOnly: true }, data, new Set(['a'])).map(row => row.id), ['a']);
});
test('initial backfill remains excluded from recent discoveries after the next refresh', () => {
  const first = item('historic');
  const later = { ...data, date: '2026-10-17', changes: { baseline: false, new_ids: ['new'] } };
  assert.equal(isRecentDiscovery(first, data), false);
  assert.equal(isRecentDiscovery(first, later), false);
  assert.equal(isRecentDiscovery({ ...first, discovery_type: undefined }, later), false);
  assert.equal(isRecentDiscovery(item('new', { discovery_type: 'new' }), later), true);
  assert.equal(isRecentDiscovery(item('old', { discovery_type: 'new', first_seen_at: '2026-09-01' }), later), false);
  assert.equal(isRecentDiscovery(item('future', { discovery_type: 'new', first_seen_at: '2026-10-18' }), later), false);
  assert.equal(isRecentDiscovery(item('utc', { discovery_type: 'new', first_seen_at: '2026-10-16T17:00:00Z' }), { date: '2026-10-17' }), true);
  assert.equal(isRecentDiscovery(item('utc-future', { discovery_type: 'new', first_seen_at: '2026-10-17T17:00:00Z' }), { date: '2026-10-17' }), false);
});
test('summary and CSV use the supplied filtered population and keep candidates out of confirmed IDs', () => {
  const selected = filterNdrcItems(data.items, { business: '新购入' });
  assert.deepEqual(ndrcSummary(selected, data), { count: 1, confirmed: 0, candidate: 1, unmatched: 0, newCount: 0 });
  const csv = ndrcCSVTable(selected, data);
  assert.equal(csv.length - 1, selected.length);
  assert.equal(csv[1][csv[0].indexOf('已确认关联申报ID')], '');
  assert.ok(csv[1][csv[0].indexOf('候选关联')].includes('候选物流项目'));
  assert.equal(csv[1][csv[0].indexOf('业务类型')], '新购入');
  assert.equal(csv[1][csv[0].indexOf('主申报地方／中央企业')], '广东省');
  assert.equal(ndrcSummary(data.items, { changes: { baseline: false, new_ids: ['a'] } }).newCount, 1);
  assert.equal(ndrcSummary(data.items, { changes: { baseline: true, new_ids: ['a'] } }).newCount, 0);
});
test('CSV preserves zero and safely escapes formulas; source links reject executable URLs', () => {
  const csv = ndrcCSVTable([item('zero', { proposed_fund_amount_yi: 0 })], data);
  assert.equal(csv[1][csv[0].indexOf('拟发售基金总额（亿元）')], 0);
  assert.equal(ndrcCSVCell('=SUM(A1)'), '"\'=SUM(A1)"');
  assert.equal(ndrcCSVCell('a"b'), '"a""b"');
  assert.equal(safeNdrcURL('javascript:alert(1)'), '');
  assert.equal(safeNdrcURL('https://name:secret@example.gov.cn/'), '');
  assert.equal(safeNdrcURL('https://example.gov.cn/list'), 'https://example.gov.cn/list');
});
test('evidence details preserve physical page references and safely render the source explanation', () => {
  const relation = { evidence: [{ url: 'https://www.sse.com.cn/a.pdf', title: '官方招募说明书', page: 19, note: '<script>资产名称</script>', asset_anchor: '园区一期', document_date: '2026-01-01' }, { url: 'javascript:alert(1)', title: '不安全链接' }], evidence_urls: ['https://www.sse.com.cn/a.pdf'] };
  const view = ndrcEvidenceDetailsHTML(relation);
  assert.ok(view.includes('物理页码第19页'));
  assert.ok(view.includes('官方招募说明书'));
  assert.ok(view.includes('&lt;script&gt;资产名称&lt;/script&gt;'));
  assert.ok(view.includes('园区一期'));
  assert.ok(!view.includes('不安全链接'));
  assert.equal(view.match(/href=/g).length, 1);
});
