/* Field-level disclosure references shared by both project libraries. */
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const exists = value => value !== null && value !== undefined && value !== '' && (!Array.isArray(value) || value.length);
const safeURL = value => {
  try { const u = new URL(value); return u.protocol === 'https:' && !u.username && !u.password ? u.href : ''; }
  catch { return ''; }
};
export const AVAILABILITY_LABELS = {not_disclosed:'未披露', not_available:'暂无法取得', not_applicable:'不适用', unverified:'待核实', pending:'待补充', conflict:'待核实'};

export function fieldEvidence(record, key, context = {}) {
  let evidence = record.research_field_sources?.[key] || [];
  if (!evidence.length && ['origin', 'manager'].includes(key) && exists(record[key]) && safeURL(record.source_url)) {
    evidence = [{title:'交易所项目基本信息', url:record.source_url,
      checked_at:context.collectedAt || '',
      note:record.updated_date ? `交易所项目更新日期：${record.updated_date}` : ''}];
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
export function fieldEvidenceHTML(record, key, context = {}) {
  const evidence = fieldEvidence(record, key, context);
  if (evidence.length) return `<div class="field-evidence">${evidence.map(item => {
    const url = safeURL(item.url || item.source_url);
    const published = item.published_at || item.date || '';
    const page = item.page || item.pages;
    const locator = [published || (item.checked_at ? `核查：${String(item.checked_at).slice(0, 10)}` : ''), page ? `第${Array.isArray(page) ? page.join('、') : page}页` : ''].filter(Boolean).join(' · ');
    const notes = [item.note || item.calculation || item.conversion || item.basis, item.amount_nature, item.scope].filter(Boolean).join('；');
    return `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer" title="${esc(item.title || '官方披露')}">${esc(item.title || '官方披露')} ↗</a>${locator ? `<span>${esc(locator)}</span>` : ''}${notes ? `<span>${esc(notes)}</span>` : ''}`;
  }).join('')}</div>`;
  const availability = fieldAvailability(record, key);
  if (!availability?.reason) return '';
  const source = safeURL(availability.source_url);
  return `<div class="field-evidence field-unavailable"><span>${esc(availability.display_reason || availability.reason)}</span>${source ? `<a href="${esc(source)}" target="_blank" rel="noopener noreferrer">查看官方披露 ↗</a>` : ''}${availability.checked_at ? `<span>核查：${esc(String(availability.checked_at).slice(0, 10))}</span>` : ''}</div>`;
}
export function fieldEvidenceText(record, key, context = {}) {
  const evidence = fieldEvidence(record, key, context);
  if (evidence.length) return evidence.map(item => [item.title, item.published_at || item.date || (item.checked_at ? `核查：${item.checked_at}` : ''), item.page ? `第${item.page}页` : '', item.note, item.url || item.source_url].filter(Boolean).join('；')).join(' | ');
  const availability = fieldAvailability(record, key);
  return availability ? [AVAILABILITY_LABELS[availability.status] || availability.status, availability.reason, availability.source_url, availability.checked_at].filter(Boolean).join('；') : '';
}
