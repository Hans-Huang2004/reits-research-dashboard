/* Recommended infrastructure REIT projects, separate from exchange submissions. */
import { closeFilterMenu, syncFilterSelects } from './filter-select.js?v=20261014-filter-menu-1';

const DATA_URL = new URL('../data/ndrc_recommendations.json', import.meta.url);
const REFRESH_STATUS_URL = new URL('../data/ndrc_refresh_status.json', import.meta.url);
const REFRESH_SCHEDULE = '每日07:45起 · 随交易所更新匹配';
const STORAGE_PREFIX = `reits:ndrc:${DATA_URL.pathname}:v1`;
const MATCH_LABELS = { confirmed: '已确认匹配', candidate: '候选待核实', unmatched: '未匹配' };
const METHOD_LABELS = { user_confirmed_association: '人工确认对应关系', official_document_asset_and_batch_review: '已核对官方资产及申报批次', official_project_identity_review: '已核对官方项目信息', official_explicit_recommendation_reference: '官方文件明确提及推荐', distinctive_name_or_asset_tokens_candidate_only: '名称或资产线索待核实', official_asset_identity_pending_recommendation_link: '已核对资产，推荐对应关系待核实' };
const $ = id => document.getElementById(id);
const html = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
const number = value => Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 });
const text = value => Array.isArray(value) ? value.map(text).filter(Boolean).join('、') : value == null ? '' : typeof value === 'object' ? value.name || value.title || value.url || '' : String(value);
const normalized = value => text(value).replace(/\s/g, '').toLowerCase();
const dateOnly = value => String(value || '').match(/^\d{4}-\d{2}-\d{2}/)?.[0] || '';
function discoveredDate(value) {
  if (/^\d{4}-\d{2}-\d{2}$/.test(value || '')) return value;
  const parsed = Date.parse(value || '');
  if (!Number.isFinite(parsed)) return '';
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date(parsed));
  return ['year', 'month', 'day'].map(key => parts.find(part => part.type === key).value).join('-');
}
const region = item => item.applicant_region || '未披露';
const industry = item => item.industry_official || '未披露';
const business = item => item.business_type || '待核实';
const year = item => dateOnly(item.recommended_date).slice(0, 4);
const state = { year: '', industry: '', region: '', business: '', match: '', search: '', recent: false, savedOnly: false, direction: -1, page: 1, pageSize: 10 };
let snapshot = null;
let callbacks = {};
let active = false;
let initialized = false;
let loading = null;
let fromCache = false;
let loadError = '';
let storageWarning = '';
let refreshStatus = null;
let favorites = new Set();

export function safeNdrcURL(value) {
  try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? url.href : ''; }
  catch { return ''; }
}
export function validateNdrcSnapshot(data) {
  if (!data || !Array.isArray(data.items) || !/^\d{4}-\d{2}-\d{2}$/.test(data.date || '')) throw new Error('推荐数据结构不正确');
  const ids = new Set();
  for (const item of data.items) {
    if (!item || typeof item.id !== 'string' || !item.id || ids.has(item.id) || typeof item.name !== 'string' || !item.name || !/^\d{4}-\d{2}-\d{2}$/.test(item.recommended_date || '') || !Object.hasOwn(MATCH_LABELS, item.match_status)) throw new Error('推荐记录的标识、日期或匹配状态不完整');
    if (!Array.isArray(item.relations) || !Array.isArray(item.candidates) || [...item.relations, ...item.candidates].some(rel => !rel || typeof rel !== 'object' || Array.isArray(rel))) throw new Error('推荐记录的关联结构不正确');
    if (item.proposed_fund_amount_yi != null && (!Number.isFinite(Number(item.proposed_fund_amount_yi)) || Number(item.proposed_fund_amount_yi) < 0)) throw new Error('推荐金额不正确');
    ids.add(item.id);
  }
  return data;
}
export function isRecentDiscovery(item, data, days = 30) {
  if (data?.changes?.baseline || item.discovery_type === 'baseline' || item.is_backfill === true || item.is_baseline === true) return false;
  // A first-seen timestamp alone cannot distinguish a historic backfill.
  const knownNew = item.discovery_type === 'new' || item.is_backfill === false || item.is_baseline === false || (data?.changes?.new_ids || []).includes(item.id);
  const firstSeen = discoveredDate(item.first_seen_at);
  if (!knownNew || !firstSeen) return false;
  const elapsed = Date.parse(`${data.date}T00:00:00Z`) - Date.parse(`${firstSeen}T00:00:00Z`);
  return elapsed >= 0 && elapsed < days * 86400000;
}
function relationText(relation, resolver = callbacks) {
  const event = resolver.getPublicEvent?.(relation.exchange_event_id);
  const fund = resolver.getPublicFund?.(relation.fund_id);
  return [relation.event_name || event?.name, relation.fund_name || fund?.short_name || fund?.name, event?.fund_code || fund?.code, relation.business_type || event?.business_type].filter(Boolean).join(' ');
}
export function filterNdrcItems(items, filters = {}, data = {}, saved = new Set(), resolver = {}) {
  const needle = normalized(filters.search);
  return items.filter(item => (!filters.year || year(item) === filters.year)
    && (!filters.industry || industry(item) === filters.industry) && (!filters.region || region(item) === filters.region)
    && (!filters.business || business(item) === filters.business) && (!filters.match || item.match_status === filters.match)
    && (!filters.recent || isRecentDiscovery(item, data)) && (!filters.savedOnly || saved.has(item.id))
    && (!needle || normalized([item.name, item.applicant_region, item.industry_official, item.business_type, ...(item.relations || []).map(relation => relationText(relation, resolver)), ...(item.candidates || []).map(relation => relationText(relation, resolver))].join(' ')).includes(needle)))
    .sort((a, b) => String(a.recommended_date).localeCompare(String(b.recommended_date)) * (filters.direction || -1) || a.id.localeCompare(b.id));
}
export function ndrcSummary(items, data = {}) {
  const newIds = new Set(data.changes?.baseline ? [] : data.changes?.new_ids || []);
  return { count: items.length, confirmed: items.filter(item => item.match_status === 'confirmed').length,
    candidate: items.filter(item => item.match_status === 'candidate').length, unmatched: items.filter(item => item.match_status === 'unmatched').length,
    newCount: items.filter(item => newIds.has(item.id)).length };
}
function evidenceRecords(relation) {
  const records = (Array.isArray(relation.evidence) ? relation.evidence : []).filter(entry => entry && safeNdrcURL(entry.url)).map(entry => ({ ...entry, url: safeNdrcURL(entry.url) }));
  const known = new Set(records.map(entry => entry.url));
  for (const url of [...(Array.isArray(relation.evidence_urls) ? relation.evidence_urls : []).map(entry => typeof entry === 'string' ? entry : entry?.url), relation.source_url].map(safeNdrcURL).filter(Boolean)) {
    if (!known.has(url)) { known.add(url); records.push({ url, title: '官方匹配依据' }); }
  }
  return records;
}
function evidenceText(relation) { return evidenceRecords(relation).map(entry => [entry.title, entry.document_date, entry.page ? `物理页码第${entry.page}页` : '', entry.note || entry.asset_anchor, entry.url].filter(Boolean).join('；')).join(' | '); }
export function ndrcEvidenceDetailsHTML(relation) {
  const evidence = evidenceRecords(relation);
  return evidence.length ? `<ul class="ndrc-evidence-list">${evidence.map(entry => `<li>${sourceLink(entry.url, entry.title || '官方匹配依据')}${entry.document_date || entry.page ? `<div class="ndrc-evidence-meta">${html([entry.document_date, entry.page ? `物理页码第${entry.page}页` : ''].filter(Boolean).join(' · '))}</div>` : ''}${entry.note || entry.asset_anchor ? `<p>${html(entry.note || entry.asset_anchor)}</p>` : ''}${entry.note && entry.asset_anchor ? `<small>${html(entry.asset_anchor)}</small>` : ''}</li>`).join('')}</ul>` : '';
}
export function ndrcCSVTable(items, data = {}, resolver = {}) {
  const headers = ['推荐记录ID', '推荐项目名称', '推荐日期', '主申报地方／中央企业', '官方行业分类', '拟发售基金总额（亿元）', '业务类型', '匹配状态', '已确认关联申报ID', '已确认关联基金ID', '已确认关联名称', '关联业务类型', '受理日期', '推荐至受理天数', '匹配依据', '候选关联', '官方来源', '系统首次发现时间', '发现类型', '数据日期', '采集时间'];
  return [headers, ...items.map(item => {
    const relations = item.match_status === 'confirmed' ? item.relations : [];
    return [item.id, item.name, item.recommended_date, item.applicant_region, item.industry_official, item.proposed_fund_amount_yi, business(item), MATCH_LABELS[item.match_status],
      relations.map(rel => rel.exchange_event_id).filter(Boolean).join(' | '), relations.map(rel => rel.fund_id).filter(Boolean).join(' | '), relations.map(rel => relationText(rel, resolver)).join(' | '), relations.map(rel => rel.business_type).filter(Boolean).join(' | '), relations.map(rel => rel.accepted_date).filter(Boolean).join(' | '), relations.map(rel => rel.days_to_acceptance ?? '').join(' | '), relations.map(rel => [METHOD_LABELS[rel.method] || rel.method, rel.note, evidenceText(rel)].filter(Boolean).join('；')).join(' | '), item.candidates.map(rel => [relationText(rel, resolver), rel.exchange_event_id, rel.fund_id, METHOD_LABELS[rel.method] || rel.method, rel.note, evidenceText(rel)].filter(Boolean).join('；')).join(' | '), safeNdrcURL(item.source_url), item.first_seen_at, item.discovery_type || (item.is_backfill ? 'baseline' : ''), data.date, data.updated_at];
  })];
}
export function ndrcCSVCell(value) {
  let valueString = text(value);
  if (/^[\s\u0000-\u001f\u007f-\u009f\u200b\u200c\u200d\u2060\ufeff]*[=+\-@]/.test(valueString)) valueString = `'${valueString}`;
  return `"${valueString.replace(/"/g, '""')}"`;
}
function readStorage(key, fallback) {
  try { const value = localStorage.getItem(`${STORAGE_PREFIX}:${key}`); return value ? JSON.parse(value) : fallback; }
  catch { return fallback; }
}
function writeStorage(key, value) {
  try { localStorage.setItem(`${STORAGE_PREFIX}:${key}`, JSON.stringify(value)); return true; }
  catch { return false; }
}
function currentRecords() { return filterNdrcItems(snapshot?.items || [], state, snapshot || {}, favorites, callbacks); }
function timestamp(value) {
  const parsed = Date.parse(value || '');
  return Number.isFinite(parsed) ? new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(parsed)) : value || '未披露';
}
function sourceLink(url, label = '官方推荐名单') { const safe = safeNdrcURL(url); return safe ? `<a class="source-link" href="${html(safe)}" target="_blank" rel="noopener noreferrer">${html(label)} ↗</a>` : '<span class="muted">暂未取得</span>'; }
function matchHTML(status) { return `<span class="status ${status === 'confirmed' ? 'ok' : status === 'candidate' ? 'wait' : 'muted'}">${MATCH_LABELS[status] || '待核实'}</span>`; }
function setOptions(key, getter) {
  const select = $(`ndrc-${key}`); const first = select.options[0].cloneNode(true);
  select.replaceChildren(first);
  const values = [...new Set((snapshot?.items || []).map(getter))].filter(Boolean).sort((a, b) => key === 'year' ? b.localeCompare(a) : a.localeCompare(b, 'zh-CN'));
  for (const value of values) { const option = document.createElement('option'); option.value = value; option.textContent = value; select.append(option); }
  if (!values.includes(state[key])) state[key] = '';
  select.value = state[key];
}
function rebuildOptions() {
  setOptions('year', year); setOptions('industry', industry); setOptions('region', region); setOptions('business', business);
  $('ndrc-match').value = state.match; syncFilterSelects();
}
function grouped(items, getter) {
  const groups = new Map();
  for (const item of items) { const key = getter(item); groups.set(key, (groups.get(key) || 0) + 1); }
  return [...groups].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'zh-CN'));
}
function bars(id, items, getter, key, limit = Infinity) {
  const groups = grouped(items, getter); const max = Math.max(1, ...groups.map(([, count]) => count));
  $(id).innerHTML = groups.slice(0, limit).map(([value, count]) => `<button class="bar-row bar-filter" data-ndrc-chart-key="${key}" data-ndrc-chart-value="${html(value)}" aria-pressed="${state[key] === value}"><div class="bar-line"><span class="bar-name" title="${html(key === 'match' ? MATCH_LABELS[value] : value)}">${html(key === 'match' ? MATCH_LABELS[value] : value)}</span><span class="bar-num">${number(count)}条</span></div><div class="track"><div class="fill" style="width:${count / max * 100}%"></div></div></button>`).join('') || '<div class="empty">无匹配数据</div>';
}
function relationLinks(relation, candidate = false) {
  const event = callbacks.getPublicEvent?.(relation.exchange_event_id);
  const fund = callbacks.getPublicFund?.(relation.fund_id);
  const eventTitle = relation.event_name || event?.name;
  const fundTitle = relation.fund_name || fund?.short_name || fund?.name;
  return `${event ? `<button class="detail-button ndrc-relation-link" data-ndrc-event="${html(event.id)}">${html(eventTitle)} ↗</button>` : eventTitle ? `<span>${html(eventTitle)}</span>` : ''}${fund ? `<button class="detail-button ndrc-relation-link" data-ndrc-fund="${html(fund.id)}">${candidate ? '候选基金' : '所属基金'}：${html(fundTitle)} ↗</button>` : fundTitle ? `<span>${html(fundTitle)}</span>` : ''}${relation.business_type || event?.business_type ? `<small class="ndrc-relation-stage">${html(relation.business_type || event.business_type)}${relation.current_stage || event?.stage ? ` · ${html(relation.current_stage || event.stage)}` : ''}</small>` : ''}`;
}
function relationCell(item) {
  if (item.match_status === 'confirmed' && item.relations.length) return item.relations.map(rel => `<div class="ndrc-relation">${relationLinks(rel)}</div>`).join('');
  if (item.match_status === 'candidate') return `<button class="detail-button ndrc-relation-link" data-ndrc-detail="${html(item.id)}">查看${item.candidates.length || ''}项候选依据 ↗</button>`;
  return '<span class="muted">尚未关联当前交易所记录</span>';
}
export function renderNdrcRecommendations() {
  const items = currentRecords(); const summary = ndrcSummary(items, snapshot || {});
  const cards = [['当前推荐记录', summary.count, '条', '按推荐项目统计'], ['已确认匹配', summary.confirmed, '条', '已关联交易所申报或基金'], ['未匹配', summary.unmatched, '条', `另有${summary.candidate}条候选待核实`], ['本次新增', summary.newCount, '条', snapshot?.changes?.baseline ? '首次历史回填不计入新增' : '当前筛选中的新发现记录']];
  $('ndrc-stats').innerHTML = cards.map(([title, count, unit, foot]) => `<div class="stat"><div class="stat-label">${title}</div><div class="stat-value">${number(count)}<small>${unit}</small></div><div class="stat-foot">${foot}</div></div>`).join('');
  bars('ndrc-year-chart', items, year, 'year'); bars('ndrc-industry-chart', items, industry, 'industry'); bars('ndrc-match-chart', items, item => item.match_status, 'match'); bars('ndrc-region-chart', items, region, 'region', 5);
  $('ndrc-record-total').textContent = `${number(items.length)}条`;
  $('ndrc-scope-text').textContent = `统计、图表与表格共用当前筛选的${number(items.length)}条推荐记录${state.recent ? ' · 最近30天首次发现，排除历史回填' : ''}`;
  const pages = Math.max(1, Math.ceil(items.length / state.pageSize)); state.page = Math.min(pages, Math.max(1, state.page)); const start = (state.page - 1) * state.pageSize;
  $('ndrc-rows').innerHTML = items.slice(start, start + state.pageSize).map(item => `<tr><td class="name-cell"><div class="name-line"><button class="star${favorites.has(item.id) ? ' saved' : ''}" data-ndrc-save="${html(item.id)}" aria-label="${favorites.has(item.id) ? '取消关注' : '关注'}${html(item.name)}" aria-pressed="${favorites.has(item.id)}">${favorites.has(item.id) ? '★' : '☆'}</button><button class="name-link" data-ndrc-detail="${html(item.id)}">${html(item.name)}</button></div>${isRecentDiscovery(item, snapshot) ? '<div class="row-sub"><span class="confidence-tag confirmed">近期新增</span></div>' : ''}</td><td class="date">${html(item.recommended_date)}</td><td>${html(region(item))}</td><td>${html(industry(item))}</td><td class="numeric">${item.proposed_fund_amount_yi == null ? '<span class="muted">未披露</span>' : number(item.proposed_fund_amount_yi)}</td><td>${html(business(item))}</td><td>${matchHTML(item.match_status)}</td><td class="ndrc-related-cell">${relationCell(item)}</td><td>${sourceLink(item.source_url)}</td></tr>`).join('') || `<tr><td colspan="9" class="empty">${snapshot ? '当前条件没有匹配记录' : loadError ? '推荐数据读取失败，请刷新重试。' : '正在读取推荐名单…'}</td></tr>`;
  $('ndrc-page-count').textContent = items.length ? `显示${start + 1}–${Math.min(start + state.pageSize, items.length)}条，共${items.length}条` : '共0条';
  $('ndrc-page-number').textContent = `${state.page} / ${pages}`; $('ndrc-prev').disabled = state.page <= 1; $('ndrc-next').disabled = state.page >= pages;
  $('ndrc-sort').textContent = `推荐日期 ${state.direction < 0 ? '↓' : '↑'}`; $('ndrc-date-heading').setAttribute('aria-sort', state.direction < 0 ? 'descending' : 'ascending');
  document.querySelectorAll('[data-ndrc-shortcut]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.ndrcShortcut === (state.recent ? 'recent' : state.match === 'unmatched' ? 'unmatched' : 'all'))));
  if (active) { $('public-export').disabled = !snapshot; $('public-reload').disabled = Boolean(loading); }
  syncFilterSelects();
}
export function renderNdrcMetadata() {
  const statuses = snapshot?.source_status || {}; const source = statuses.NDRC || statuses.ndrc || statuses; const coverage = snapshot?.coverage || {};
  const attempt = refreshStatus || source;
  const matchedVersion = (Array.isArray(snapshot?.source_versions) ? snapshot.source_versions : []).find(version => /(?:^|\/)public_reits\.json$/.test(version.path || ''));
  const warnings = [loadError, fromCache ? '正在展示此浏览器上次成功读取的推荐快照。' : '', storageWarning];
  if (attempt.ok === false || attempt.complete === false || attempt.attempt_ok === false || ['failed', 'error', 'partial'].includes(attempt.status) || coverage.complete === false) warnings.push('推荐来源本轮更新未完成，保留上次完整名单。');
  $('ndrc-data-notice').textContent = warnings.filter(Boolean).join(' '); $('ndrc-data-notice').hidden = !warnings.some(Boolean);
  $('ndrc-footer-date').textContent = snapshot ? `采集时间：${timestamp(snapshot.updated_at)}（北京时间） · 最新推荐：${coverage.latest_recommended_date || source.latest_recommended_date || '未披露'}` : '';
  $('ndrc-source-metadata').innerHTML = snapshot ? `<p>本期${number(snapshot.items.length)}条推荐记录；推荐期间：${html(coverage.earliest_recommended_date || [...snapshot.items].map(item => item.recommended_date).sort()[0] || '未披露')}至${html(coverage.latest_recommended_date || source.latest_recommended_date || [...snapshot.items].map(item => item.recommended_date).sort().at(-1) || '未披露')}。采集时间：${html(timestamp(snapshot.updated_at))}（北京时间）。</p>${matchedVersion ? `<p>用于匹配的公募快照日期：${html(matchedVersion.date || '未披露')}；采集时间：${html(timestamp(matchedVersion.updated_at))}（北京时间）。</p>` : ''}${snapshot.changes?.baseline ? '<p>本期为首次历史回填；新增统计从后续采集开始。</p>' : ''}${attempt.last_attempt_at || attempt.attempted_at ? `<p>最近尝试：${html(timestamp(attempt.last_attempt_at || attempt.attempted_at))}（北京时间）；${attempt.attempt_ok === false || attempt.ok === false ? '更新未完成' : '见本期采集状态'}。</p>` : ''}${attempt.error ? `<p>来源状态：${html(text(attempt.error))}</p>` : ''}` : '<p>推荐数据尚未读取成功。</p>';
  if (active) { $('public-data-pill').textContent = snapshot ? `${fromCache ? '本地快照' : '数据日期'} ${snapshot.date}` : loadError ? '读取失败' : '正在读取'; $('side-date').textContent = snapshot?.date || (loadError ? '读取失败' : '正在读取'); $('side-source').textContent = '国家发展改革委推荐项目'; $('side-schedule').textContent = REFRESH_SCHEDULE; }
}
function applySnapshot(data, cached) { snapshot = validateNdrcSnapshot(data); fromCache = cached; rebuildOptions(); renderNdrcMetadata(); renderNdrcRecommendations(); callbacks.onSnapshot?.(); }
export async function loadNdrcRecommendations() {
  if (loading) return loading;
  loading = (async () => {
    $('ndrc-loading').hidden = false; if (active) $('public-reload').disabled = true; loadError = '';
    const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), 35000);
    const statusRequest = fetch(REFRESH_STATUS_URL, { cache: 'no-store', signal: controller.signal }).then(response => response.ok ? response.json() : null).catch(() => null);
    try {
      const response = await fetch(DATA_URL, { cache: 'no-store', signal: controller.signal }); if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = validateNdrcSnapshot(await response.json()); applySnapshot(data, false); writeStorage('snapshot', data);
    } catch {
      loadError = '在线推荐数据读取失败，请稍后刷新。';
      try { const previous = snapshot || readStorage('snapshot', null); if (!previous) throw new Error('无缓存'); applySnapshot(previous, true); }
      catch { renderNdrcMetadata(); renderNdrcRecommendations(); }
    } finally { refreshStatus = await statusRequest; clearTimeout(timer); loading = null; $('ndrc-loading').hidden = true; if (active) $('public-reload').disabled = false; renderNdrcMetadata(); }
  })();
  return loading;
}
function detailFields(values) { return `<dl class="detail-grid">${values.map(([label, value]) => `<div><dt>${html(label)}</dt><dd>${html(value == null || value === '' ? '未披露' : value)}</dd></div>`).join('')}</dl>`; }
function relationDetail(relation, candidate) {
  const event = callbacks.getPublicEvent?.(relation.exchange_event_id);
  const accepted = relation.accepted_date || event?.accepted_date;
  return `<article class="ndrc-relation-detail">${relationLinks(relation, candidate)}${detailFields([['业务类型', relation.business_type || event?.business_type || '待核实'], ['受理日期', accepted], ['推荐至受理天数', relation.days_to_acceptance == null ? '' : `${relation.days_to_acceptance}天`], ['匹配方法', METHOD_LABELS[relation.method] || relation.method], ['匹配说明', relation.note], ...(relation.chronology_note ? [['日期说明', relation.chronology_note]] : [])])}${ndrcEvidenceDetailsHTML(relation)}</article>`;
}
export function openNdrcRecommendation(id) {
  const item = snapshot?.items.find(record => record.id === id); if (!item) return;
  closeFilterMenu();
  $('ndrc-detail-body').innerHTML = `<div class="detail-name">${html(item.name)}</div>${detailFields([['推荐日期', item.recommended_date], ['主申报地方／中央企业', item.applicant_region], ['官方行业分类', item.industry_official], ['拟发售基金总额（亿元）', item.proposed_fund_amount_yi == null ? '' : number(item.proposed_fund_amount_yi)], ['业务类型', business(item)], ['匹配状态', MATCH_LABELS[item.match_status]]])}<section class="public-detail-section"><h3>已确认关联 <span class="muted">${item.match_status === 'confirmed' ? item.relations.length : 0}项</span></h3>${item.match_status === 'confirmed' && item.relations.length ? item.relations.map(rel => relationDetail(rel, false)).join('') : '<p class="muted">尚未确认与当前交易所记录的关联。</p>'}</section>${item.candidates.length ? `<section class="public-detail-section"><h3>候选关联 <span class="confidence-tag likely">待核实</span></h3>${item.candidates.map(rel => relationDetail(rel, true)).join('')}</section>` : ''}<section class="public-detail-section"><h3>发现记录</h3>${detailFields([['系统首次发现', timestamp(item.first_seen_at)], ['发现类型', item.discovery_type === 'baseline' || item.is_backfill ? '历史回填' : isRecentDiscovery(item, snapshot) ? '后续新增' : '见来源记录'], ['最近检索到', timestamp(item.last_seen_at)]])}</section><div class="detail-source">${sourceLink(item.source_url)}<p>推荐记录：${html(item.id)}</p></div>`;
  const dialog = $('ndrc-detail-dialog'); if (!dialog.open) dialog.showModal(); dialog.scrollTop = 0;
}
export function ndrcReverseLinksHTML(kind, id) {
  const related = (snapshot?.items || []).filter(item => item.match_status === 'confirmed' && item.relations.some(rel => (kind === 'event' ? rel.exchange_event_id : rel.fund_id) === id));
  return related.length ? `<section class="public-detail-section"><h3>发改委推荐 <span class="muted">${related.length}条</span></h3><div class="public-event-list">${related.map(item => `<button class="public-event-card" data-ndrc-detail="${html(item.id)}"><span class="public-event-card-title">${html(item.name)}</span><span class="public-event-card-meta"><time>${html(item.recommended_date)}</time><span>查看推荐记录 ↗</span></span></button>`).join('')}</div></section>` : '';
}
export function exportNdrcCSV() {
  if (!snapshot) return;
  const csv = ndrcCSVTable(currentRecords(), snapshot, callbacks).map(row => row.map(ndrcCSVCell).join(',')).join('\r\n');
  const url = URL.createObjectURL(new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8' }));
  const link = document.createElement('a'); link.href = url; link.download = `REITs_发改委推荐_${snapshot.date}.csv`; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function openNdrcSources() { closeFilterMenu(); renderNdrcMetadata(); if (!$('ndrc-source-dialog').open) $('ndrc-source-dialog').showModal(); }
export function setNdrcRecommendationsActive(value) { active = value; if (active) { renderNdrcMetadata(); renderNdrcRecommendations(); if (!snapshot && !loading) loadNdrcRecommendations(); } }
export function initializeNdrcRecommendations(options = {}) {
  if (initialized) return; initialized = true; callbacks = options;
  const saved = readStorage('favorites', []); favorites = new Set(Array.isArray(saved) ? saved.filter(item => typeof item === 'string') : []);
  $('ndrc-search').addEventListener('input', event => { state.search = event.target.value; state.page = 1; renderNdrcRecommendations(); });
  for (const key of ['year', 'industry', 'region', 'business', 'match']) $(`ndrc-${key}`).addEventListener('change', event => { state[key] = event.target.value; state.page = 1; renderNdrcRecommendations(); });
  $('ndrc-saved-only').addEventListener('change', event => { state.savedOnly = event.target.checked; state.page = 1; renderNdrcRecommendations(); });
  $('ndrc-page-size').addEventListener('change', event => { state.pageSize = Number(event.target.value); state.page = 1; renderNdrcRecommendations(); });
  $('ndrc-prev').addEventListener('click', () => { state.page--; renderNdrcRecommendations(); }); $('ndrc-next').addEventListener('click', () => { state.page++; renderNdrcRecommendations(); });
  $('ndrc-sort').addEventListener('click', () => { state.direction *= -1; state.page = 1; renderNdrcRecommendations(); });
  $('ndrc-reset').addEventListener('click', () => { Object.assign(state, { year: '', industry: '', region: '', business: '', match: '', search: '', recent: false, savedOnly: false, direction: -1, page: 1 }); $('ndrc-search').value = ''; $('ndrc-saved-only').checked = false; rebuildOptions(); renderNdrcRecommendations(); });
  $('ndrc-panel').addEventListener('click', event => {
    const shortcut = event.target.closest('[data-ndrc-shortcut]'); if (shortcut) { state.match = shortcut.dataset.ndrcShortcut === 'unmatched' ? 'unmatched' : ''; state.recent = shortcut.dataset.ndrcShortcut === 'recent'; state.page = 1; $('ndrc-match').value = state.match; renderNdrcRecommendations(); }
    const chart = event.target.closest('[data-ndrc-chart-key]'); if (chart) { const key = chart.dataset.ndrcChartKey; state[key] = state[key] === chart.dataset.ndrcChartValue ? '' : chart.dataset.ndrcChartValue; $(`ndrc-${key}`).value = state[key]; state.page = 1; renderNdrcRecommendations(); }
    const save = event.target.closest('[data-ndrc-save]'); if (save) { const id = save.dataset.ndrcSave; if (favorites.has(id)) favorites.delete(id); else favorites.add(id); if (!writeStorage('favorites', [...favorites])) { storageWarning = '浏览器限制存储，关注标记在刷新后可能丢失。'; renderNdrcMetadata(); } renderNdrcRecommendations(); }
  });
  for (const id of ['ndrc-panel', 'ndrc-detail-dialog', 'public-detail-dialog']) $(id).addEventListener('click', event => {
    const detail = event.target.closest('[data-ndrc-detail]'); if (detail) { if ($('public-detail-dialog').open) $('public-detail-dialog').close(); openNdrcRecommendation(detail.dataset.ndrcDetail); }
    const fund = event.target.closest('[data-ndrc-fund]'); const filing = event.target.closest('[data-ndrc-event]');
    if (fund || filing) { $('ndrc-detail-dialog').close(); if (fund) callbacks.openPublicFund?.(fund.dataset.ndrcFund); else callbacks.openPublicEvent?.(filing.dataset.ndrcEvent); }
  });
  $('ndrc-source-help').addEventListener('click', openNdrcSources); renderNdrcRecommendations();
}
