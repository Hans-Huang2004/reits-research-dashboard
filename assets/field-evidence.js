/* Field-level disclosure references shared by both project libraries. */
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const exists = value => value !== null && value !== undefined && value !== '' && (!Array.isArray(value) || value.length);
const safeURL = value => {
  try { const u = new URL(value); return u.protocol === 'https:' && !u.username && !u.password ? u.href : ''; }
  catch { return ''; }
};
export const AVAILABILITY_LABELS = {not_disclosed:'未披露', not_available:'暂无法取得', not_applicable:'不适用', unverified:'待核实', pending:'待补充', conflict:'待核实'};
const localAssetClassification = (key, context) => key === 'asset_type' && context.classification?.source === 'local_manual';

export function fieldEvidence(record, key, context = {}) {
  if (localAssetClassification(key, context)) return [];
  let evidence = record.research_field_sources?.[key] || [];
  const roleSource = key === 'origin' && !context.isEvent && context.originSource?.origin === record.origin ? context.originSource : record;
  if (!evidence.length && ['origin', 'manager'].includes(key) && exists(record[key]) && safeURL(roleSource?.source_url)) {
    evidence = [{title:'交易所项目基本信息', url:roleSource.source_url,
      checked_at:context.collectedAt || '',
      note:roleSource.updated_date ? `交易所项目更新日期：${roleSource.updated_date}` : ''}];
  }
  if (!evidence.length && key === 'sale_amount_cny_100m') {
    if (!context.isEvent) evidence = record.research_field_sources?.initial_raise_cny_100m || [];
    else if (record.business_type === '首发') evidence = context.fund?.research_field_sources?.sale_amount_cny_100m || context.fund?.research_field_sources?.initial_raise_cny_100m || [];
  }
  return (Array.isArray(evidence) ? evidence : [evidence]).filter(item => item && safeURL(item.url || item.source_url));
}

export function fieldAvailability(record, key) { return record.field_availability?.[key] || null; }
export function missingFieldText(record, key, fallback = '待补充') {
  return AVAILABILITY_LABELS[fieldAvailability(record, key)?.status] || fallback;
}
const evidenceValue = value => Array.isArray(value) ? value.map(evidenceValue).filter(Boolean).join('、') : exists(value) ? String(value) : '';
const uniqueValues = values => [...new Set(values.map(evidenceValue).filter(Boolean))];

// Keep the same provenance and every independent explanation in both delivery formats.
function evidenceEntries(record, key, context) {
  if (localAssetClassification(key, context)) return [{
    title:'本地分类修订', url:'', notes:uniqueValues([context.classification.note]),
    published:'', pages:[], checkedAt:''
  }];
  const evidence = fieldEvidence(record, key, context);
  if (evidence.length) return evidence.map(item => ({
    title:evidenceValue(item.title) || '官方披露', url:safeURL(item.url || item.source_url),
    published:evidenceValue(item.published_at || item.date),
    pages:uniqueValues([item.page, item.pages].flat()),
    checkedAt:evidenceValue(item.checked_at),
    notes:uniqueValues([item.note, item.calculation, item.conversion, item.basis, item.amount_nature, item.scope])
  }));
  const availability = fieldAvailability(record, key);
  return availability ? [{
    title:AVAILABILITY_LABELS[availability.status] || evidenceValue(availability.status),
    url:safeURL(availability.source_url), unavailable:true,
    published:'', pages:[], checkedAt:evidenceValue(availability.checked_at),
    notes:uniqueValues([availability.display_reason || availability.reason])
  }] : [];
}
function locatorParts(item, compact = false) {
  return [item.published, item.pages.length ? `第${item.pages.join('、')}页` : '',
    item.checkedAt ? `核查：${compact ? item.checkedAt.slice(0, 10) : item.checkedAt}` : ''].filter(Boolean);
}
export function fieldEvidenceHTML(record, key, context = {}) {
  const entries = evidenceEntries(record, key, context);
  return entries.length ? `<div class="field-evidence${entries[0].unavailable ? ' field-unavailable' : ''}">${entries.map(item => {
    const title = item.url ? `<a href="${esc(item.url)}" target="_blank" rel="noopener noreferrer" title="${esc(item.title)}">${esc(item.title)} ↗</a>` : `<span>${esc(item.title)}</span>`;
    const locator = locatorParts(item, true).join(' · ');
    const notes = item.notes.join('；');
    return `${title}${locator ? `<span>${esc(locator)}</span>` : ''}${notes ? `<span>${esc(notes)}</span>` : ''}`;
  }).join('')}</div>` : '';
}
export function fieldEvidenceText(record, key, context = {}) {
  return evidenceEntries(record, key, context).map(item => [item.title, ...locatorParts(item), ...item.notes, item.url].filter(Boolean).join('；')).join(' | ');
}
