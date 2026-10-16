/* Public REIT funds and their separate first-offering / expansion submissions. */
'use strict';
import { REFRESH_SCHEDULE, refreshWarning } from './refresh-health.js?v=20261016-refresh-1';
import { closeFilterMenu, syncFilterSelects } from './filter-select.js?v=20261014-filter-menu-1';
import { PUBLIC_FIELDS, getPublicField, formatProjectField, projectFieldCellText } from './project-fields.js?v=20261015-origin-2';
import { fieldEvidenceHTML, fieldEvidenceText } from './field-evidence.js?v=20261015-origin-2';
import { initializeNdrcRecommendations, setNdrcRecommendationsActive, loadNdrcRecommendations, renderNdrcRecommendations, renderNdrcMetadata, exportNdrcCSV, openNdrcSources, openNdrcRecommendation, ndrcReverseLinksHTML } from './ndrc-recommendations.js?v=20261016-updates-1';

const DATA_URL = new URL('../data/public_reits.json', import.meta.url);
const COMPRESSED_DATA_URL = new URL('../data/public_reits.json.gz', import.meta.url);
const STORAGE_PREFIX = `reits:public:${DATA_URL.pathname}:v1`;
const $ = id => document.getElementById(id);
const html = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
const format = value => Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 });
const issued = fund => ['已上市', '成立待上市'].includes(fund.stage);
const present = value => value != null && value !== '';
const normalized = value => String(value ?? '').replace(/\s/g, '').toLowerCase();
const state = { view: 'funds', fields: 'core', ex: '', search: '', product: '', asset: '', stage: '', business: '', manager: '', savedOnly: false, direction: -1, page: 1, pageSize: 10 };
const CORE_FIELD_KEYS = new Set(['name', 'business_type', 'exchange', 'product_type', 'origin', 'manager', 'sale_amount_cny_100m', 'asset_type', 'project_status', 'updated_date']);
const FIELD_GROUPS = [
  ['基本资料', ['name', 'business_type', 'exchange', 'product_type', 'origin', 'manager', 'issuer', 'financial_advisor']],
  ['各版本融资规模', ['proposed_sale_amount_application_cny_100m', 'proposed_sale_amount_feedback_cny_100m', 'proposed_sale_amount_inquiry_cny_100m', 'sale_amount_cny_100m', 'external_loan_amount_cny_100m']],
  ['资产与预测', ['asset_type', 'underlying_assets', 'project_return_forecast']],
  ['进度与增信', ['project_status', 'updated_date', 'guarantee_support']]
];
let snapshot = null;
let funds = [];
let events = [];
let fundById = new Map();
let eventById = new Map();
let eventsByFund = new Map();
let loading = null;
let active = false;
let initialized = false;
let fromCache = false;
let storageWarning = '';
let loadError = '';
let lastPublicDetail = null;

function readStorage(key, fallback) {
  try { const value = localStorage.getItem(`${STORAGE_PREFIX}:${key}`); return value ? JSON.parse(value) : fallback; }
  catch { return fallback; }
}
function writeStorage(key, value) {
  try { localStorage.setItem(`${STORAGE_PREFIX}:${key}`, JSON.stringify(value)); return true; }
  catch { return false; }
}
const saved = readStorage('favorites', []);
const favorites = new Set(Array.isArray(saved) ? saved.filter(item => typeof item === 'string') : []);
if (readStorage('field-view', 'core') === 'all') state.fields = 'all';

function safeURL(value) {
  try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? url.href : ''; }
  catch { return ''; }
}
function valueText(value) {
  if (!present(value)) return '';
  if (Array.isArray(value)) return value.map(valueText).filter(Boolean).join('、');
  if (typeof value === 'object') {
    const name = value.name || value.asset_name || value.project_name || value.description;
    const location = [value.province, value.city].filter(Boolean).join('');
    return name ? `${name}${location ? `（${location}）` : ''}` : Object.entries(value).filter(([, item]) => present(item) && typeof item !== 'object').map(([, item]) => String(item)).join('、');
  }
  return String(value);
}
const label = value => valueText(value) || '未披露';
const assetLabel = record => valueText(record.asset_type) || '待分类';
const managerLabel = record => valueText(record.manager) || '未披露';
const productLabel = record => valueText(record.product_type) || '待确认';
const isEventView = () => state.view === 'events';
const isRecommendationView = () => state.view === 'recommendations';
const recordKey = (record, kind = state.view) => `${kind === 'events' ? 'event' : 'fund'}:${record.id}`;
const officialStatus = record => valueText(record.official_status) || valueText(record.stage) || '未披露';
const eventStage = event => valueText(event.stage) || officialStatus(event);
const stageFor = record => valueText(record.stage) || (isEventView() ? officialStatus(record) : '未披露');
const isoDate = value => String(value || '').match(/^\d{4}-\d{2}-\d{2}/)?.[0] || '';
const futureDate = value => Boolean(snapshot && isoDate(value) && isoDate(value) > snapshot.date);
const actualDate = value => futureDate(value) ? '' : isoDate(value);
const dateFor = record => {
  const spec = PUBLIC_FIELDS.find(field => field.key === 'updated_date');
  return spec ? actualDate(getPublicField(record, spec.key, fieldContext(record))) : '';
};
const plannedListingDate = record => record.planned_listing_date || record.expected_listing_date || (futureDate(record.listing_date) ? record.listing_date : '');
const fundFor = event => fundById.get(event.fund_id);
const fieldContext = (record, sequence, eventView = isEventView()) => ({ fund: eventView ? fundFor(record) : record, isEvent: eventView, sequence, collectedAt:snapshot?.updated_at,
  originSource:eventView ? record : (eventsByFund.get(record.id) || []).find(event => event.business_type === '首发' && event.origin === record.origin) });
const visibleFields = () => state.fields === 'all' ? PUBLIC_FIELDS : PUBLIC_FIELDS.filter(spec => CORE_FIELD_KEYS.has(spec.key));
const fieldTitle = spec => `${spec.label}${spec.unit && !spec.label.includes(spec.unit) ? `（${spec.unit}）` : ''}`;

function validate(data) {
  if (!data || !Array.isArray(data.funds) || !Array.isArray(data.events) || !/^\d{4}-\d{2}-\d{2}$/.test(data.date || '')) throw new Error('公募数据结构不正确');
  const fundIds = new Set();
  const eventIds = new Set();
  const codes = new Set();
  for (const fund of data.funds) {
    if (!fund || typeof fund.id !== 'string' || !fund.id || typeof fund.name !== 'string' || !['上交所', '深交所'].includes(fund.exchange) || fundIds.has(fund.id)) throw new Error('基金记录缺少唯一标识或交易所');
    if (fund.code && codes.has(String(fund.code))) throw new Error('公募数据存在重复基金代码');
    fundIds.add(fund.id);
    if (fund.code) codes.add(String(fund.code));
  }
  for (const event of data.events) {
    if (!event || typeof event.id !== 'string' || !event.id || typeof event.name !== 'string' || !['上交所', '深交所'].includes(event.exchange) || eventIds.has(event.id) || !fundIds.has(event.fund_id)) throw new Error('申报记录标识或基金关联不完整');
    eventIds.add(event.id);
  }
  return data;
}

function baseRecords() { return isEventView() ? events : funds.filter(issued); }
function currentRecords() {
  const needle = normalized(state.search);
  return baseRecords().filter(record => {
    const fund = isEventView() ? fundFor(record) : record;
    const searchText = [record.name, record.short_name, record.code, record.fund_code, record.issuer, record.manager, record.origin, record.financial_advisor, record.asset_type, record.product_type, record.province, record.city, record.stage, record.official_status, valueText(record.aliases), valueText(record.underlying_assets), fund?.short_name, fund?.name, fund?.code].join(' ');
    const businessMatch = !isEventView() || !state.business || record.business_type === state.business;
    return (!state.ex || record.exchange === state.ex) && (!state.product || productLabel(record) === state.product)
      && (!state.asset || assetLabel(record) === state.asset) && (!state.stage || stageFor(record) === state.stage)
      && (!state.manager || managerLabel(record) === state.manager) && businessMatch
      && (!state.savedOnly || favorites.has(recordKey(record))) && (!needle || normalized(searchText).includes(needle));
  }).sort((a, b) => {
    const left = dateFor(a); const right = dateFor(b);
    if (!left && right) return 1;
    if (left && !right) return -1;
    return String(left).localeCompare(String(right)) * state.direction || a.id.localeCompare(b.id);
  });
}
function setOptions(id, key, values) {
  const select = $(id);
  const first = select.options[0].cloneNode(true);
  select.replaceChildren(first);
  for (const value of [...new Set(values)].filter(Boolean).sort((a, b) => a.localeCompare(b, 'zh-CN'))) {
    const option = document.createElement('option'); option.value = value; option.textContent = value; select.append(option);
  }
  if (![...select.options].some(option => option.value === state[key])) state[key] = '';
  select.value = state[key];
}
function rebuildOptions() {
  const records = baseRecords();
  setOptions('public-product', 'product', records.map(productLabel));
  setOptions('public-asset', 'asset', records.map(assetLabel));
  setOptions('public-stage', 'stage', records.map(stageFor));
  setOptions('public-manager', 'manager', records.map(managerLabel));
  $('public-business').value = state.business;
  syncFilterSelects();
}

function grouped(records, getter) {
  const groups = new Map();
  for (const record of records) { const name = getter(record); groups.set(name, (groups.get(name) || 0) + 1); }
  return [...groups].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'zh-CN'));
}
function renderBars(id, groups, key, limit = Infinity) {
  const max = Math.max(1, ...groups.map(([, count]) => count));
  $(id).innerHTML = groups.slice(0, limit).map(([name, count]) => `<button class="bar-row bar-filter" data-public-chart-key="${key}" data-public-chart-value="${html(name)}" aria-pressed="${state[key] === name}"><div class="bar-line"><span class="bar-name" title="${html(name)}">${html(name)}</span><span class="bar-num">${format(count)}${isEventView() ? '条' : '只'}</span></div><div class="track"><div class="fill" style="width:${count / max * 100}%"></div></div></button>`).join('') || '<div class="empty">无匹配数据</div>';
}
function statusClass(value) { return /终止|中止|撤回|不通过|未通过/.test(value) ? 'muted' : /未完成/.test(value) ? 'wait' : /已上市|成立待上市|注册生效|通过|获批|已注册|已完成|扩募完成/.test(value) ? 'ok' : 'wait'; }
function statusHTML(value) { return `<span class="status ${statusClass(value)}">${html(value)}</span>`; }
function sourceLink(value, title = '官方资料') { const url = safeURL(value); return url ? `<a class="source-link" href="${html(url)}" target="_blank" rel="noopener noreferrer">${html(title)} ↗</a>` : '<span class="muted">暂未取得</span>'; }

function publicColumnClass(spec) {
  if (spec.key === 'name') return 'name-cell';
  if (spec.key === 'sequence') return 'public-sequence-cell';
  if (spec.key.endsWith('_cny_100m')) return 'numeric public-money-cell';
  if (spec.key === 'updated_date') return 'date';
  if (['issuer', 'origin'].includes(spec.key)) return 'public-issuer-cell';
  if (spec.key === 'manager') return 'mgr';
  if (spec.key === 'asset_type') return 'public-asset-cell';
  if (['underlying_assets', 'project_return_forecast', 'guarantee_support'].includes(spec.key)) return 'public-narrative-cell';
  if (spec.key === 'project_status') return 'public-state-cell';
  return 'public-compact-cell';
}
function publicCellHTML(record, spec, context) {
  const text = projectFieldCellText(record, spec, context);
  const raw = getPublicField(record, spec.key, context);
  if (spec.key === 'name') {
    const fund = context.fund;
    const code = context.isEvent ? record.fund_code || fund?.code : record.code;
    const key = recordKey(record);
    const extra = context.isEvent ? [] : (eventsByFund.get(record.id) || []).filter(item => item.business_type === '扩募');
    const classificationTag = record.classification_source === 'keyword' && !record.official_asset_type ? '<span class="confidence-tag likely">名称初判</span>' : '';
    const parent = context.isEvent && fund ? `<button class="detail-button public-parent-link" data-public-fund="${html(fund.id)}">所属基金：${html(fund.short_name || fund.name)} ↗</button>` : '';
    const related = extra.length ? `<button class="detail-button public-parent-link" data-public-fund="${html(record.id)}">${extra.length}项扩募记录 ↗</button>` : '';
    return `<div class="name-line"><button class="star${favorites.has(key) ? ' saved' : ''}" data-public-save="${html(key)}" aria-label="${favorites.has(key) ? '取消关注' : '关注'}${html(text)}" aria-pressed="${favorites.has(key)}">${favorites.has(key) ? '★' : '☆'}</button><button class="name-link" data-public-${context.isEvent ? 'event' : 'fund'}="${html(record.id)}">${html(text)}</button></div><div class="row-sub">${code ? `<span class="public-fund-code">${html(code)}</span>` : '<span class="muted">代码待披露</span>'}${classificationTag}${parent}${related}</div>`;
  }
  if (!present(raw) || (Array.isArray(raw) && !raw.length)) return `<span class="public-field-empty">${html(text)}</span>`;
  if (spec.key === 'project_status') {
    const stage = context.isEvent ? eventStage(record) : record.stage;
    const sourceStatus = context.isEvent ? officialStatus(record) : '';
    return `${statusHTML(text)}${stage && stage !== text ? `<small class="public-date-note">业务阶段：${html(stage)}</small>` : ''}${sourceStatus && sourceStatus !== text && sourceStatus !== stage ? `<small class="public-date-note">官方：${html(sourceStatus)}</small>` : ''}`;
  }
  return `${html(text)}${spec.key === 'updated_date' && futureDate(raw) ? '<small class="public-date-note">计划日期</small>' : ''}`;
}

function render() {
  $('public-exchange-content').hidden = isRecommendationView();
  $('ndrc-panel').hidden = !isRecommendationView();
  if (active) document.querySelector('.skip-link').href = isRecommendationView() ? '#ndrc-projects' : '#public-projects';
  if (isRecommendationView()) {
    document.querySelectorAll('[data-public-view]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.publicView === state.view)));
    $('public-view-note').textContent = '发改委向证监会推荐项目 · 关联交易所申报';
    renderNdrcMetadata(); renderNdrcRecommendations(); return;
  }
  if (active) $('public-reload').disabled = Boolean(loading);
  const records = currentRecords();
  const eventView = isEventView();
  const unit = eventView ? '条' : '只';
  const managerCount = new Set(records.map(managerLabel).filter(item => item !== '未披露')).size;
  const stats = eventView
    ? [['当前匹配申报', records.length, '条', '按交易所官方申报ID统计'], ['首发申报', records.filter(item => item.business_type === '首发').length, '条', '当前筛选中的首次发行申报'], ['扩募申报', records.filter(item => item.business_type === '扩募').length, '条', '每次扩募分别保留，关联原基金'], ['中止与终止', records.filter(item => /中止|终止|撤回/.test(officialStatus(item))).length, '条', '历史申报仍可检索']]
    : [['当前匹配基金', records.length, '只', '每只基金一条记录'], ['已上市', records.filter(item => item.stage === '已上市').length, '只', '以基金上市资料为准'], ['成立待上市', records.filter(item => item.stage === '成立待上市').length, '只', '已成立、尚未上市'], ['基金管理人', managerCount, '家', '当前筛选中的已披露管理人']];
  $('public-stats').innerHTML = stats.map(([title, count, suffix, foot]) => `<div class="stat"><div class="stat-label">${title}</div><div class="stat-value">${format(count)}<small>${suffix}</small></div><div class="stat-foot">${foot}</div></div>`).join('');
  renderBars('public-product-chart', grouped(records, productLabel), 'product');
  renderBars('public-asset-chart', grouped(records, assetLabel), 'asset');
  renderBars('public-stage-chart', grouped(records, stageFor), 'stage');
  renderBars('public-manager-chart', grouped(records, managerLabel), 'manager', 5);
  $('public-stage-chart-heading').textContent = eventView ? '业务阶段' : '基金阶段';
  $('public-stage-chart-note').textContent = eventView ? '首发、审核与完成进程 · 点击筛选' : '点击阶段筛选';
  $('public-stage-label').textContent = eventView ? '业务阶段' : '基金阶段';
  $('public-stage').options[0].textContent = '全部阶段';
  $('public-business-field').hidden = !eventView;
  $('public-list-heading').textContent = eventView ? '申报审核' : '已发行基金';
  $('public-record-total').textContent = `${format(records.length)}${unit}`;
  $('public-view-note').textContent = eventView ? '每次申报一条记录 · 区分首发与扩募' : '每只基金一条记录 · 包含成立待上市基金';
  $('public-list-note').textContent = eventView ? '点击名称查看申报资料，点击所属基金查阅历次业务。' : '点击名称查看基金资料、底层资产与历次申报。';
  $('public-table-caption').textContent = eventView ? '公募REITs首发与扩募申报记录' : '公募REITs已发行基金';
  $('public-scope-text').textContent = `统计、图表与表格共用当前筛选的${format(records.length)}${unit}${eventView ? '申报记录' : '基金'}`;
  const pages = Math.max(1, Math.ceil(records.length / state.pageSize));
  state.page = Math.min(pages, Math.max(1, state.page));
  const start = (state.page - 1) * state.pageSize;
  const specs = visibleFields();
  $('public-table').classList.toggle('public-table-all', state.fields === 'all');
  $('public-table-head').innerHTML = `<tr>${specs.map(spec => `<th scope="col" class="${publicColumnClass(spec)}"${spec.key === 'updated_date' ? ` aria-sort="${state.direction < 0 ? 'descending' : 'ascending'}"` : ''}>${spec.key === 'updated_date' ? `<button class="sort-button" data-public-sort="date">${html(spec.label)} ${state.direction < 0 ? '↓' : '↑'}</button>` : html(spec.label)}${spec.unit && !spec.label.includes(spec.unit) ? `<span class="column-unit">${html(spec.unit)}</span>` : ''}</th>`).join('')}<th scope="col">官方来源</th></tr>`;
  $('public-rows').innerHTML = records.slice(start, start + state.pageSize).map((record, index) => {
    const context = fieldContext(record, start + index + 1);
    return `<tr>${specs.map(spec => `<td class="${publicColumnClass(spec)}">${publicCellHTML(record, spec, context)}</td>`).join('')}<td>${sourceLink(record.source_url, eventView ? '官方项目页' : '基金资料')}</td></tr>`;
  }).join('') || `<tr><td colspan="${specs.length + 1}" class="empty">${snapshot ? '当前条件没有匹配记录' : loadError ? '公募项目库读取失败，请刷新重试。' : '选择公募模块后读取项目资料。'}</td></tr>`;
  document.querySelectorAll('[data-public-fields]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.publicFields === state.fields)));
  $('public-fields-note').textContent = state.fields === 'all' ? `完整${PUBLIC_FIELDS.length}项字段 · 左右滚动查看` : `核心${CORE_FIELD_KEYS.size}项字段 · 详情查看全部资料`;
  $('public-page-count').textContent = records.length ? `显示${start + 1}–${Math.min(start + state.pageSize, records.length)}条，共${records.length}条` : '共0条';
  $('public-page-number').textContent = `${state.page} / ${pages}`;
  $('public-prev').disabled = state.page <= 1;
  $('public-next').disabled = state.page >= pages;
  $('public-export').disabled = !snapshot;
  document.querySelectorAll('[data-public-view]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.publicView === state.view)));
  document.querySelectorAll('[data-public-ex]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.publicEx === state.ex)));
  syncFilterSelects();
}

function formatTimestamp(value) {
  const timestamp = Date.parse(value || '');
  return Number.isFinite(timestamp) ? new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(timestamp)) : value || '未披露';
}
function sourceName(key, info) {
  return info?.exchange || info?.name || info?.title || (/sse/i.test(key) && !/szse/i.test(key) ? '上交所' : /szse/i.test(key) ? '深交所' : key);
}
function sourceEntries() {
  const source = snapshot?.source_status || {};
  return source.exchange ? [[source.exchange, source]] : Object.entries(source).filter(([, info]) => info && typeof info === 'object');
}
function sourceFailed(info) { return info?.ok === false || ['failed', 'error', 'partial'].includes(info?.status); }
function sourceSucceeded(info) { return info?.ok === true || info?.status === 'complete'; }
function renderMetadata() {
  if (isRecommendationView()) { renderNdrcMetadata(); return; }
  const warnings = [];
  if (loadError) warnings.push(loadError);
  if (fromCache) warnings.push('正在展示此浏览器上次成功读取的公募快照。');
  if (snapshot?.coverage?.complete === false) warnings.push('本期来源尚未完整覆盖，具体缺口见数据口径。');
  if (snapshot) {
    const morningWarning = refreshWarning(snapshot);
    if (morningWarning) warnings.push(morningWarning);
    for (const [key, info] of sourceEntries()) if (sourceFailed(info)) warnings.push(`${sourceName(key, info)}本轮更新未完成。`);
  }
  if (storageWarning) warnings.push(storageWarning);
  $('public-data-notice').hidden = warnings.length === 0;
  $('public-data-notice').textContent = warnings.join(' ');
  $('public-data-pill').textContent = snapshot ? `${fromCache ? '本地快照' : '数据日期'} ${snapshot.date}` : loadError ? '读取失败' : '等待读取';
  $('public-footer-date').textContent = snapshot ? `采集时间：${formatTimestamp(snapshot.updated_at || snapshot.date)}（北京时间）${fromCache ? ' · 浏览器缓存' : ''}` : '';
  if (snapshot) {
    const sourceRows = sourceEntries().map(([key, info]) => `<tr><td>${html(sourceName(key, info))}</td><td>${html(info.fund_report_date || info.as_of_date || info.latest_available_date || info.freshness?.latest_available_date || '未单独披露')}</td><td>${html(info.latest_project_update || info.latest_filing_update || info.latest_date || '未单独披露')}</td><td>${sourceFailed(info) ? '更新未完成' : sourceSucceeded(info) ? '采集成功' : '见来源记录'}</td></tr>`).join('');
    const gaps = snapshot.coverage?.limitations || snapshot.coverage?.notes || snapshot.coverage?.missing_sources || [];
    const sourceNotes = snapshot.enrichment?.checked_at ? `<li>披露核查：${html(formatTimestamp(snapshot.enrichment.checked_at))}（北京时间）。各字段来源、文件日期、物理页码及未取得原因见项目详情。基金视图的融资与预测采用首发口径，扩募另列。</li>` : sourceEntries().filter(([, info]) => valueText(info.limitations)).map(([key, info]) => `<li>${html(sourceName(key, info))}：${html(valueText(info.limitations))}</li>`).join('');
    $('public-source-metadata').innerHTML = `<p>本期共${funds.filter(issued).length}只已发行基金、${events.length}条申报记录；另保留${funds.filter(fund => !issued(fund)).length}条待发行基金主记录。采集时间：${html(formatTimestamp(snapshot.updated_at || snapshot.date))}（北京时间）。</p>${present(gaps) && valueText(gaps) ? `<p>覆盖说明：${html(valueText(gaps))}</p>` : ''}${sourceRows ? `<div class="table-wrap"><table class="public-source-table"><thead><tr><th>来源</th><th>基金名录日期</th><th>申报最新更新</th><th>更新状态</th></tr></thead><tbody>${sourceRows}</tbody></table></div>` : ''}${sourceNotes ? `<ul>${sourceNotes}</ul>` : ''}`;
  } else $('public-source-metadata').textContent = '公募数据尚未读取成功。';
  if (active) {
    $('side-date').textContent = snapshot?.date || (loadError ? '读取失败' : '正在读取');
    $('side-source').textContent = '上交所／深交所公募REITs';
    $('side-schedule').textContent = REFRESH_SCHEDULE;
  }
}
function applySnapshot(data, cached) {
  snapshot = validate(data); fromCache = cached;
  funds = snapshot.funds; events = snapshot.events.filter(event => ['首发', '扩募'].includes(event.business_type));
  fundById = new Map(funds.map(fund => [fund.id, fund]));
  eventById = new Map(events.map(event => [event.id, event]));
  eventsByFund = new Map();
  for (const event of events) { if (!eventsByFund.has(event.fund_id)) eventsByFund.set(event.fund_id, []); eventsByFund.get(event.fund_id).push(event); }
  for (const list of eventsByFund.values()) list.sort((a, b) => String(b.updated_date || b.accepted_date || '').localeCompare(String(a.updated_date || a.accepted_date || '')));
  rebuildOptions(); renderMetadata(); render();
}
async function loadData() {
  if (loading) return loading;
  loading = (async () => {
    if (!isRecommendationView()) $('public-reload').disabled = true; $('public-loading').hidden = false;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 35000);
    loadError = '';
    try {
      let payload;
      if (typeof DecompressionStream === 'function') {
        try {
          const compressed = await fetch(COMPRESSED_DATA_URL, { cache: 'no-store', signal: controller.signal });
          if (!compressed.ok || !compressed.body) throw new Error('Compressed snapshot unavailable');
          payload = await new Response(compressed.body.pipeThrough(new DecompressionStream('gzip'))).json();
        } catch (error) { if (controller.signal.aborted) throw error; }
      }
      if (!payload) {
        const response = await fetch(DATA_URL, { cache: 'no-store', signal: controller.signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        payload = await response.json();
      }
      const data = validate(payload);
      applySnapshot(data, false); writeStorage('snapshot', data);
    } catch {
      loadError = '在线公募数据读取失败，请稍后刷新。';
      const previous = snapshot || readStorage('snapshot', null);
      try { if (!previous) throw new Error('无缓存'); applySnapshot(previous, true); }
      catch { renderMetadata(); render(); }
    } finally { clearTimeout(timer); $('public-loading').hidden = true; if (!isRecommendationView()) $('public-reload').disabled = false; loading = null; }
  })();
  return loading;
}

function fieldHTML(fields) { return `<dl class="detail-grid">${fields.map(([name, value]) => `<div><dt>${html(name)}</dt><dd>${html(label(value))}</dd></div>`).join('')}</dl>`; }
function datedField(title, value) { return [futureDate(value) ? `计划${title}` : title, value]; }
function referenceGroupsHTML(record, context, additions = {}) {
  const extraByGroup = [additions.basic || [], additions.finance || [], additions.assets || [], additions.progress || []];
  return FIELD_GROUPS.map(([title, keys], index) => {
    const fields = keys.map(key => PUBLIC_FIELDS.find(spec => spec.key === key)).filter(Boolean).map(spec => {
      const raw = getPublicField(record, spec.key, context);
      const empty = !present(raw) || (Array.isArray(raw) && !raw.length);
      return `<div class="${['underlying_assets', 'project_return_forecast', 'guarantee_support'].includes(spec.key) ? 'public-detail-wide' : ''}"><dt>${html(fieldTitle(spec))}</dt><dd${empty ? ' class="public-field-empty"' : ''}>${html(projectFieldCellText(record, spec, context))}${fieldEvidenceHTML(record, spec.key, context)}</dd></div>`;
    }).join('');
    const extra = extraByGroup[index];
    return `<section class="public-detail-section public-reference-section"><h3>${title}</h3><dl class="detail-grid">${fields}</dl>${extra.length ? fieldHTML(extra) : ''}${index === 2 ? classificationHTML(record) : ''}${index === 3 ? additions.progressBody || '' : ''}</section>`;
  }).join('');
}
function classificationHTML(record) {
  if (record.official_asset_type) return `<section class="classification-evidence"><h3>资产分类 <span class="confidence-tag confirmed">官方分类</span></h3><p>官方资产类型：${html(valueText(record.official_asset_type))}</p></section>`;
  if (record.classification_source === 'keyword') return `<section class="classification-evidence"><h3>资产分类 <span class="confidence-tag likely">名称初判</span></h3>${record.classification_note ? `<p>${html(record.classification_note)}</p>` : ''}</section>`;
  return record.classification_note ? `<section class="classification-evidence"><h3>资产分类</h3><p>${html(record.classification_note)}</p></section>` : '';
}
function documentsHTML(documents) {
  const list = (Array.isArray(documents) ? documents : []).filter(doc => doc && safeURL(doc.url));
  return list.length ? `<ul class="public-document-list">${list.map(doc => `<li><a href="${html(safeURL(doc.url))}" target="_blank" rel="noopener noreferrer">${html(doc.title || '披露文件')} ↗</a>${doc.date ? `<span>${html(doc.date)}${futureDate(doc.date) ? '（计划日期）' : ''}</span>` : ''}</li>`).join('')}</ul>` : '<p class="muted">暂无独立文件入口，可从官方资料页查阅。</p>';
}
function timelineHTML(event) {
  const disclosed = (Array.isArray(event.timeline) ? event.timeline : []).filter(item => item && item.title && isoDate(item.date));
  const fallback = [['受理', event.accepted_date], ['注册', event.registered_date], ['最新进展', event.updated_date]].filter(([, date]) => isoDate(date)).map(([title, date]) => ({ title, date }));
  const milestones = [...(disclosed.length ? disclosed : fallback)];
  if (event.completion_announcement_date) milestones.push({ title: '完成公告发布', date: event.completion_announcement_date });
  const seen = new Set();
  const unique = milestones.filter(item => {
    const key = `${item.title}|${isoDate(item.date)}`;
    if (seen.has(key)) return false;
    seen.add(key); return true;
  }).sort((a, b) => isoDate(a.date).localeCompare(isoDate(b.date)) || String(a.title).localeCompare(String(b.title), 'zh-CN'));
  return unique.length ? `<ol class="public-timeline">${unique.map(item => `<li><span>${item.planned || item.is_planned || futureDate(item.date) ? '计划：' : ''}${html(item.title)}</span><time>${html(item.date)}</time></li>`).join('')}</ol>` : '<p class="muted">暂无已披露的时间节点。</p>';
}
function showDetail(title, body) {
  closeFilterMenu();
  $('public-detail-heading').textContent = title;
  $('public-detail-body').innerHTML = body;
  const dialog = $('public-detail-dialog');
  if (!dialog.open) dialog.showModal();
  dialog.scrollTop = 0;
}
function openFund(id) {
  const fund = fundById.get(id); if (!fund) return;
  lastPublicDetail = { kind: 'fund', id };
  const related = eventsByFund.get(id) || [];
  const progress = [datedField('基金成立日期', fund.established_date), datedField('上市日期', fund.listing_date)];
  if (fund.establishment_announcement_date) progress.push(datedField('成立公告发布日期', fund.establishment_announcement_date));
  if (plannedListingDate(fund) && !futureDate(fund.listing_date)) progress.push(['计划上市日期', plannedListingDate(fund)]);
  const groups = referenceGroupsHTML(fund, fieldContext(fund, null, false), {
    basic: [['基金代码', fund.code || '待披露']],
    finance: fund.initial_raise_basis ? [['募集规模口径', fund.initial_raise_basis]] : [],
    assets: [['资产所在地', [valueText(fund.province), valueText(fund.city)].filter(Boolean).join('、')]],
    progress
  });
  const relatedHTML = related.length ? `<div class="public-event-list">${related.map(event => `<button class="public-event-card" data-public-event="${html(event.id)}"><span class="public-event-card-title"><span class="mini-tag rights-tag">${html(event.business_type || '待确认')}</span>${html(event.name)}</span><span class="public-event-card-meta"><span>${html(eventStage(event))}${eventStage(event) !== officialStatus(event) ? ` · 官方：${html(officialStatus(event))}` : ''}</span><time>${html(actualDate(event.updated_date) || actualDate(event.accepted_date) || '日期未披露')}</time><span>查看申报 ↗</span></span></button>`).join('')}</div>` : '<p class="muted">暂无已关联的交易所申报记录。</p>';
  showDetail('基金详情', `<div class="detail-name">${html(fund.short_name || fund.name)}</div>${fund.short_name && fund.short_name !== fund.name ? `<p class="public-full-name">${html(fund.name)}</p>` : ''}${groups}${ndrcReverseLinksHTML('fund', fund.id)}<section class="public-detail-section"><h3>首发与扩募 <span class="muted">${related.length}条</span></h3>${relatedHTML}</section><section class="public-detail-section"><h3>基金披露资料</h3>${documentsHTML(fund.documents)}</section><div class="detail-source">${sourceLink(fund.source_url, '打开官方基金资料')}<p>基金记录：${html(fund.id)}</p></div>`);
}
function openEvent(id) {
  const event = eventById.get(id); if (!event) return;
  lastPublicDetail = { kind: 'event', id };
  const fund = fundFor(event);
  const completionEvidence = Array.isArray(event.completion_evidence) ? event.completion_evidence : [];
  const completion = event.completed === true || completionEvidence.length ? `<section class="public-detail-section"><h3>完成依据</h3>${event.completion_announcement_date ? `<p class="muted">${futureDate(event.completion_announcement_date) ? '计划完成公告发布日期' : '完成公告发布日期'}：${html(event.completion_announcement_date)}</p>` : ''}${documentsHTML(completionEvidence)}</section>` : '';
  const basis = event.sale_amount_basis || event.initial_raise_basis || (event.business_type === '首发' ? fund?.initial_raise_basis : '');
  const groups = referenceGroupsHTML(event, fieldContext(event, null, true), {
    basic: [['基金代码', event.fund_code || fund?.code || '待披露']],
    finance: basis ? [['募集规模口径', basis]] : [],
    progress: [['官方审核状态', officialStatus(event)], datedField('受理日期', event.accepted_date), datedField('注册日期', event.registered_date)],
    progressBody: `<h3 class="public-timeline-title">披露时间节点</h3>${timelineHTML(event)}`
  });
  showDetail('申报详情', `<div class="detail-name">${html(event.name)}</div>${fund ? `<button class="button public-back-fund" data-public-fund="${html(fund.id)}">← 所属基金：${html(fund.short_name || fund.name)}</button>` : ''}${groups}${ndrcReverseLinksHTML('event', event.id)}${completion}<section class="public-detail-section"><h3>申报披露资料</h3>${documentsHTML(event.documents)}</section><div class="detail-source">${sourceLink(event.source_url, '打开官方申报项目')}<p>申报记录：${html(event.id)}</p></div>`);
}

function csvCell(value) {
  let text = valueText(value);
  if (/^[\s\u0000-\u001f\u007f-\u009f\u200b\u200c\u200d\u2060\ufeff]*[=+\-@]/.test(text)) text = `'${text}`;
  return `"${text.replace(/"/g, '""')}"`;
}
function documentsText(documents) {
  return (Array.isArray(documents) ? documents : []).filter(doc => doc && safeURL(doc.url)).map(doc => `${doc.title || '披露文件'}${doc.date ? `（${futureDate(doc.date) ? '计划日期：' : ''}${doc.date}）` : ''}：${safeURL(doc.url)}`).join(' | ');
}
function publicCSVTable(selected) {
  const eventView = isEventView();
  const extraHeaders = ['视图', '基金代码', '基金ID', '申报ID', '官方审核状态', '官方资产类型', '分类来源', '分类确认程度', '分类依据', '基金成立日期', '上市日期', '计划成立日期', '计划上市日期', '成立公告发布日期', '募集规模口径', '完成公告发布日期', '计划完成公告发布日期', '完成依据', '关联申报ID', '披露文件', '官方来源', '数据日期', '采集时间'];
  const rows = selected.map((record, index) => {
    const context = fieldContext(record, index + 1);
    const fund = context.fund;
    const reference = PUBLIC_FIELDS.map(spec => {
      const raw = getPublicField(record, spec.key, context);
      if (!present(raw) || (Array.isArray(raw) && !raw.length)) return '';
      return ['amount', 'integer'].includes(spec.type) ? raw : formatProjectField(raw, spec);
    });
    const basis = record.sale_amount_basis || record.initial_raise_basis || (eventView && record.business_type === '首发' ? fund?.initial_raise_basis : '');
    const extras = [eventView ? '申报审核' : '已发行基金', eventView ? record.fund_code || fund?.code : record.code, fund?.id || '', eventView ? record.id : '', eventView ? officialStatus(record) : '', record.official_asset_type, record.classification_source, record.classification_confidence, record.classification_note, !eventView ? actualDate(record.established_date) : '', !eventView ? actualDate(record.listing_date) : '', !eventView && futureDate(record.established_date) ? record.established_date : '', !eventView ? plannedListingDate(record) : '', !eventView ? actualDate(record.establishment_announcement_date) : '', basis, eventView ? actualDate(record.completion_announcement_date) : '', eventView && futureDate(record.completion_announcement_date) ? record.completion_announcement_date : '', eventView ? documentsText(record.completion_evidence) : '', (eventsByFund.get(fund?.id) || []).map(event => event.id).join(' | '), documentsText(record.documents), safeURL(record.source_url), snapshot.date, snapshot.updated_at];
    return [...reference, ...extras];
  });
  const sourceHeaders = PUBLIC_FIELDS.filter(spec => spec.key !== 'sequence').map(spec => `${fieldTitle(spec)}：披露来源及日期`);
  return [[...PUBLIC_FIELDS.map(fieldTitle), ...extraHeaders, ...sourceHeaders], ...rows.map((row, index) => [...row, ...PUBLIC_FIELDS.filter(spec => spec.key !== 'sequence').map(spec => fieldEvidenceText(selected[index], spec.key, fieldContext(selected[index], index + 1)))])];
}
function exportCSV() {
  if (!snapshot) return;
  const eventView = isEventView();
  const table = publicCSVTable(currentRecords());
  const blob = new Blob(['\uFEFF' + table.map(row => row.map(csvCell).join(',')).join('\r\n')], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a'); link.href = url; link.download = `REITs_公募_${eventView ? '申报审核' : '已发行基金'}_${snapshot.date}.csv`; document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function switchView(view, business = '') {
  closeFilterMenu();
  state.view = view; state.stage = ''; state.business = business; state.page = 1; state.direction = -1;
  setNdrcRecommendationsActive(active && isRecommendationView());
  if (!isRecommendationView()) rebuildOptions(); renderMetadata(); render();
}

export function openPublicSources() { if (isRecommendationView()) { openNdrcSources(); return; } closeFilterMenu(); renderMetadata(); if (!$('public-source-dialog').open) $('public-source-dialog').showModal(); }
export async function openPublicRecord(project) {
  if (!project?.entity_id) return false;
  for (const id of ['updates-timeline-dialog', 'updates-detail-dialog']) { const dialog = $(id); if (dialog?.open) dialog.close(); }
  if (project.population === 'ndrc') {
    switchView('recommendations');
    await loadNdrcRecommendations();
    openNdrcRecommendation(project.entity_id);
    return Boolean($('ndrc-detail-dialog')?.open);
  }
  await loadData();
  if (project.entity_kind === 'fund') {
    switchView('funds');
    if (!fundById.has(project.entity_id)) return false;
    openFund(project.entity_id);
  } else {
    switchView('events', ['首发', '扩募'].includes(project.business_type) ? project.business_type : '');
    if (!eventById.has(project.entity_id)) return false;
    openEvent(project.entity_id);
  }
  return Boolean($('public-detail-dialog')?.open);
}
export function setPublicModuleActive(value) {
  active = value;
  setNdrcRecommendationsActive(active && isRecommendationView());
  if (!active) return;
  document.querySelector('.skip-link').href = isRecommendationView() ? '#ndrc-projects' : '#public-projects';
  renderMetadata();
  if (!snapshot && !loading) loadData();
  loadNdrcRecommendations();
}
export function initializePublicReits() {
  if (initialized) return; initialized = true;
  initializeNdrcRecommendations({ getPublicFund: id => fundById.get(id), getPublicEvent: id => eventById.get(id), openPublicFund: openFund, openPublicEvent: openEvent,
    onSnapshot: () => { if ($('public-detail-dialog').open && lastPublicDetail) { if (lastPublicDetail.kind === 'fund') openFund(lastPublicDetail.id); else openEvent(lastPublicDetail.id); } } });
  $('public-search').addEventListener('input', event => { state.search = event.target.value; state.page = 1; render(); });
  for (const key of ['product', 'asset', 'stage', 'business', 'manager']) $(`public-${key}`).addEventListener('change', event => { state[key] = event.target.value; state.page = 1; render(); });
  $('public-saved-only').addEventListener('change', event => { state.savedOnly = event.target.checked; state.page = 1; render(); });
  $('public-page-size').addEventListener('change', event => { state.pageSize = Number(event.target.value); state.page = 1; render(); });
  $('public-prev').addEventListener('click', () => { state.page--; render(); });
  $('public-next').addEventListener('click', () => { state.page++; render(); });
  $('public-reset').addEventListener('click', () => {
    Object.assign(state, { ex: '', search: '', product: '', asset: '', stage: '', business: '', manager: '', savedOnly: false, direction: -1, page: 1 });
    $('public-search').value = ''; $('public-saved-only').checked = false; rebuildOptions(); render();
  });
  document.querySelectorAll('[data-public-view]').forEach(button => button.addEventListener('click', () => switchView(button.dataset.publicView)));
  document.querySelectorAll('[data-public-ex]').forEach(button => button.addEventListener('click', () => { state.ex = button.dataset.publicEx; state.page = 1; render(); }));
  $('public-expansion-shortcut').addEventListener('click', () => {
    Object.assign(state, { ex: '', search: '', product: '', asset: '', manager: '', savedOnly: false });
    $('public-search').value = ''; $('public-saved-only').checked = false;
    switchView('events', '扩募');
    $('public-projects').scrollIntoView({ block: 'start', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
  });
  $('public-panel').addEventListener('click', event => {
    const sort = event.target.closest('[data-public-sort]');
    if (sort) { state.direction *= -1; state.page = 1; render(); }
    const fields = event.target.closest('[data-public-fields]');
    if (fields) { state.fields = fields.dataset.publicFields; writeStorage('field-view', state.fields); render(); }
    const chart = event.target.closest('[data-public-chart-key]');
    if (chart) { const key = chart.dataset.publicChartKey; state[key] = state[key] === chart.dataset.publicChartValue ? '' : chart.dataset.publicChartValue; $(`public-${key}`).value = state[key]; state.page = 1; render(); }
    const save = event.target.closest('[data-public-save]');
    if (save) { const key = save.dataset.publicSave; if (favorites.has(key)) favorites.delete(key); else favorites.add(key); if (!writeStorage('favorites', [...favorites])) { storageWarning = '浏览器限制存储，关注标记在刷新后可能丢失。'; renderMetadata(); } render(); }
  });
  for (const id of ['public-panel', 'public-detail-dialog']) $(id).addEventListener('click', event => {
    const fundButton = event.target.closest('[data-public-fund]'); if (fundButton) openFund(fundButton.dataset.publicFund);
    const eventButton = event.target.closest('[data-public-event]'); if (eventButton) openEvent(eventButton.dataset.publicEvent);
  });
  $('public-export').addEventListener('click', () => isRecommendationView() ? exportNdrcCSV() : exportCSV());
  $('public-reload').addEventListener('click', () => isRecommendationView() ? loadNdrcRecommendations() : loadData());
  $('public-source-help').addEventListener('click', openPublicSources);
  render();
}
