/* REITs dashboard for project lists collected directly from official SSE/SZSE APIs. */
'use strict';
import { REFRESH_SCHEDULE, refreshWarning } from './refresh-health.js?v=20261017-refresh-2';
import { enhanceFilterSelects, syncFilterSelects, closeFilterMenu } from './filter-select.js?v=20261014-filter-menu-1';
import { initializePublicReits, setPublicModuleActive, openPublicSources, openPublicRecord } from './public-reits.js?v=20261017-refresh-2';
import { initializeProjectUpdates, setUpdatesModuleActive, openUpdatesSources } from './project-updates.js?v=20261018-official-date-1';
import { INSTITUTIONAL_FIELDS, getInstitutionalField, projectFieldCellText } from './project-fields.js?v=20261017-refresh-2';
import { fieldEvidenceHTML, fieldEvidenceText } from './field-evidence.js?v=20261015-disclosures-1';

const DATA_URL = new URL('../data/institutional.json', import.meta.url);
const STORAGE_PREFIX = `reits:${DATA_URL.pathname}:v1`;
const STORAGE = { favorites: `${STORAGE_PREFIX}:favorites`, overrides: `${STORAGE_PREFIX}:classification`, snapshot: `${STORAGE_PREFIX}:snapshot`, fields: `${STORAGE_PREFIX}:fields` };
const STATUS = { '0': '已申报', '1': '已受理', '2': '已反馈', '3': '已接收反馈意见', '4': '通过', '5': '未通过', '8': '终止', '9': '中止', '10': '已回复意见', '11': '提交注册', '12': '注册生效' };
const TAXONOMY = {
  '经营权类': ['市政生态', '交通设施', '能源'],
  '产权类': ['产业园', '租赁住房', '物流仓储', '消费', '数据中心', '办公', '综合业态', '文旅类', '医疗健康'],
  '待分类': ['待分类']
};
const ASSET_ALIASES = { '仓储物流': '物流仓储', '办公楼': '办公' };
const RIGHTS = Object.keys(TAXONOMY);
const ASSETS = Object.values(TAXONOMY).flat();
const rightsForAsset = value => RIGHTS.find(rights => TAXONOMY[rights].includes(value)) || '待分类';
const normalizedAsset = value => ASSET_ALIASES[value] || value || '待分类';
const validClassification = (rights, asset) => Boolean(TAXONOMY[rights]?.includes(normalizedAsset(asset)));
const $ = id => document.getElementById(id);
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
const format = value => Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 });
const statusLabel = value => STATUS[value] || String(value || '未披露');
const state = { ex: '', kw: '', rights: '', asset: '', status: '', confidence: '', match: '', savedOnly: false, hideArchived: false, mode: 'count', sort: 'updated', direction: -1, page: 1, pageSize: 10, fields: 'core' };
let snapshot = null;
let records = [];
let byId = new Map();
let cachedView = false;
let storageWarning = '';
let activeModule = 'updates';
let institutionalLoading = null;

function readStorage(key, fallback) {
  try { const value = localStorage.getItem(key); return value ? JSON.parse(value) : fallback; }
  catch { return fallback; }
}
function writeStorage(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); return true; }
  catch { return false; }
}
const storedFavorites = readStorage(STORAGE.favorites, []);
const favorites = new Set(Array.isArray(storedFavorites) ? storedFavorites.filter(id => typeof id === 'string') : []);
const storedOverrides = readStorage(STORAGE.overrides, {});
const overrides = storedOverrides && typeof storedOverrides === 'object' && !Array.isArray(storedOverrides) ? storedOverrides : {};
state.fields = readStorage(STORAGE.fields, 'core') === 'all' ? 'all' : 'core';

const THEME_STORAGE = 'reits:theme:v1';
const systemTheme = window.matchMedia('(prefers-color-scheme: dark)');
let themeChoice = 'system';
try { const saved = localStorage.getItem(THEME_STORAGE); if (['system', 'light', 'dark'].includes(saved)) themeChoice = saved; } catch { /* An unavailable storage still permits a session theme. */ }
function applyTheme(choice, persist = false) {
  themeChoice = choice;
  const dark = choice === 'dark' || (choice === 'system' && systemTheme.matches);
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  $('theme-color').content = dark ? '#10191f' : '#f5f7f8';
  document.querySelectorAll('[data-theme-choice]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.themeChoice === choice)));
  if (persist) { try { localStorage.setItem(THEME_STORAGE, choice); } catch { /* Keep the chosen appearance for this session. */ } }
}
document.querySelectorAll('[data-theme-choice]').forEach(button => button.addEventListener('click', () => applyTheme(button.dataset.themeChoice, true)));
systemTheme.addEventListener('change', () => { if (themeChoice === 'system') applyTheme('system'); });
window.addEventListener('storage', event => { if (event.key === THEME_STORAGE) applyTheme(['light', 'dark'].includes(event.newValue) ? event.newValue : 'system'); });
applyTheme(themeChoice);

function evidenceURL(value) {
  try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? url.href : ''; }
  catch { return ''; }
}
function evidenceFor(record) {
  return (Array.isArray(record.classification_evidence) ? record.classification_evidence : []).filter(item => item && evidenceURL(item.url)).map(item => ({ title: String(item.title || '分类来源材料'), url: evidenceURL(item.url) }));
}
const confidenceLabel = value => ({ confirmed: '已核实', likely: '初步判断', unknown: '待分类' }[value] || '待分类');
const underlyingAssets = record => Array.isArray(record.underlying_assets) ? record.underlying_assets.join('、') : String(record.underlying_assets || '');

function sourceURL(record) {
  if (!record.source_url) return '';
  try {
    const url = new URL(record.source_url);
    const officialHost = /(^|\.)sse\.com\.cn$|(^|\.)szse\.cn$/i.test(url.hostname);
    return url.protocol === 'https:' && officialHost && !url.username && !url.password ? url.href : '';
  } catch { return ''; }
}
function sourceLabel(record) { return record.source_kind === 'project_data' ? '官方项目数据' : '官方项目页'; }
function validated(data) {
  if (!data || !Array.isArray(data.items) || !/^\d{4}-\d{2}-\d{2}$/.test(data.date || '')) throw new Error('数据文件结构或日期不正确');
  const ids = new Set();
  for (const record of data.items) {
    if (!record || typeof record.id !== 'string' || !record.id || typeof record.name !== 'string' || !['上交所', '深交所'].includes(record.ex)) throw new Error('项目记录缺少官方标识、名称或交易所');
    if (ids.has(record.id)) throw new Error('数据文件存在重复项目 ID');
    ids.add(record.id);
  }
  return data;
}
function amount(record) {
  const raw = getInstitutionalField(record, 'declared_amount_cny_100m');
  if (raw == null || raw === '') return null;
  const value = Number(String(raw).replaceAll(',', ''));
  return Number.isFinite(value) ? value : null;
}
function classification(record) {
  const override = overrides[record.id];
  if (override && validClassification(override.ptype, override.psub)) return { psub: normalizedAsset(override.psub), ptype: override.ptype, source: 'local_manual', confidence: override.psub === '待分类' ? 'unknown' : 'likely', needsReview: true, note: String(override.pnote || override.note || '此前保存的本地分类，未填写依据。'), evidence: [] };
  if (override && typeof override === 'object') return { psub: '待分类', ptype: '待分类', source: 'local_manual', confidence: 'unknown', needsReview: true, evidence: [], note: `此前的本地分类为“${String(override.ptype || '未填写')} → ${String(override.psub || '未填写')}”，与当前分类口径不符，已标为待复核。原值仍保存在浏览器，可修订或恢复数据文件分类。${override.pnote || override.note ? ` 原备注：${String(override.pnote || override.note)}` : ''}` };
  const psub = normalizedAsset(record.psub);
  const unknown = record.classification_source === 'unknown' || psub === '待分类' || !validClassification(record.ptype, psub);
  const confidence = unknown ? 'unknown' : ['confirmed', 'likely'].includes(record.classification_confidence) ? record.classification_confidence : record.classification_source === 'verified' ? 'confirmed' : 'likely';
  return { psub: unknown ? '待分类' : psub, ptype: unknown ? '待分类' : record.ptype, source: unknown ? 'unknown' : record.classification_source || 'keyword', confidence, needsReview: confidence !== 'confirmed', note: record.pnote || '数据文件未提供分类依据。', evidence: evidenceFor(record) };
}
function classificationSource(category) { return { local_manual: '本地人工修订', manual: '仓库人工分类', verified: '项目披露核实', inferred: '项目线索推定', keyword: '名称关键词初判', unknown: '尚无充分分类依据' }[category.source] || '数据文件分类'; }
function keywords(record) {
  return Array.isArray(record.match_keywords) ? record.match_keywords.map(String) : [];
}
function keywordMatches(record, needle) {
  const normalize = value => value.replace(/\s/g, '').toLowerCase();
  return keywords(record).some(value => normalize(value).includes(normalize(needle)));
}
function archived(record) { return Boolean(record.archive_status && record.archive_status !== 'current'); }
function currentRecords() {
  const keyword = state.kw.trim().toLowerCase();
  return records.filter(record => {
    const category = classification(record);
    return (!state.ex || record.ex === state.ex) && (!state.rights || category.ptype === state.rights) && (!state.asset || category.psub === state.asset)
      && (!state.status || String(record.status) === state.status) && (!state.match || keywordMatches(record, state.match))
      && (!state.confidence || category.confidence === state.confidence)
      && (!state.savedOnly || favorites.has(record.id)) && (!state.hideArchived || !archived(record))
      && (!keyword || [record.name, record.writer || record.mgr, record.origin, category.ptype, category.psub, underlyingAssets(record)].join(' ').toLowerCase().includes(keyword));
  }).sort((a, b) => {
    if (state.sort === 'amount') {
      if (amount(a) == null && amount(b) != null) return 1;
      if (amount(a) != null && amount(b) == null) return -1;
      return ((amount(a) ?? 0) - (amount(b) ?? 0)) * state.direction || a.id.localeCompare(b.id);
    }
    if (state.sort === 'status') return statusLabel(a.status).localeCompare(statusLabel(b.status), 'zh-CN') * state.direction || a.id.localeCompare(b.id);
    const dateKeys = { accepted: 'accepted_date', approved: 'approved_date', issued: 'issued_date' };
    if (dateKeys[state.sort]) {
      const spec = dateKeys[state.sort];
      const valueA = getInstitutionalField(a, spec, { classification: classification(a), statusLabel });
      const valueB = getInstitutionalField(b, spec, { classification: classification(b), statusLabel });
      if (!valueA && valueB) return 1;
      if (valueA && !valueB) return -1;
      return String(valueA || '').localeCompare(String(valueB || '')) * state.direction || a.id.localeCompare(b.id);
    }
    return String(a.up || '').localeCompare(String(b.up || '')) * state.direction || String(b.acc || '').localeCompare(String(a.acc || '')) || a.id.localeCompare(b.id);
  });
}
function grouped(data, valueFor) {
  const totals = new Map();
  for (const record of data) {
    const name = valueFor(record) || '未披露';
    const value = state.mode === 'count' ? 1 : amount(record) ?? 0;
    totals.set(name, (totals.get(name) || 0) + value);
  }
  return [...totals].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'zh-CN'));
}
function renderBars(id, groups, { isStatus = false, limit = 5, filter = '' } = {}) {
  const max = Math.max(1, ...groups.map(([, value]) => value));
  $(id).innerHTML = groups.slice(0, limit).map(([name, value]) => {
    const label = isStatus ? statusLabel(name) : name;
    const parent = filter === 'asset' ? rightsForAsset(name) : '';
    const fillClass = isStatus ? (name === '4' ? ' ok' : ['1', '2'].includes(name) ? ' pending' : '') : (parent || name) === '经营权类' ? ' operating' : name === '待分类' ? ' unclassified' : '';
    const content = `<div class="bar-line"><span class="bar-name">${escapeHTML(label)}${parent && name !== '待分类' ? `<small>${escapeHTML(parent)}</small>` : ''}</span><span class="bar-num">${format(value)} ${state.mode === 'count' ? '条' : '亿元'}</span></div><div class="track"><div class="fill${fillClass}" style="width:${Math.max(0, value / max * 100)}%"></div></div>`;
    return filter ? `<button class="bar-row bar-filter" data-class-filter="${filter}" data-class-value="${escapeHTML(name)}" aria-pressed="${state[filter] === name}" aria-label="筛选${escapeHTML(label)}，${format(value)}${state.mode === 'count' ? '条' : '亿元'}">${content}</button>` : `<div class="bar-row">${content}</div>`;
  }).join('') || '<div class="empty">无匹配数据</div>';
}
function fillSelect(id, values, labelFor = value => value) {
  const select = $(id);
  const selected = state[id];
  const first = select.options[0].cloneNode(true);
  select.replaceChildren(first);
  for (const value of values) { const option = document.createElement('option'); option.value = value; option.textContent = labelFor(value); select.appendChild(option); }
  select.value = selected;
  if (select.selectedIndex < 0) { select.value = ''; state[id] = ''; }
}
function rebuildOptions() {
  fillSelect('rights', RIGHTS);
  rebuildAssetOptions();
  fillSelect('status', [...new Set(records.map(record => String(record.status || '')))].filter(Boolean).sort(), statusLabel);
}
function rebuildAssetOptions() {
  const assets = state.rights ? TAXONOMY[state.rights] : ASSETS;
  if (state.asset && !assets.includes(state.asset)) state.asset = '';
  fillSelect('asset', assets);
}
function selectClassificationFilter(key, value) {
  if (key === 'rights') { state.rights = state.rights === value ? '' : value; rebuildAssetOptions(); }
  else { state.asset = state.asset === value ? '' : value; if (state.asset) state.rights = rightsForAsset(state.asset); rebuildAssetOptions(); }
  $('rights').value = state.rights;
  $('asset').value = state.asset;
  state.page = 1;
  render();
}
const CORE_INSTITUTIONAL_FIELDS = new Set(['name', 'status', 'exchange', 'declared_amount_cny_100m', 'asset_type', 'origin', 'manager', 'accepted_date', 'is_issued']);
const INSTITUTIONAL_SORT_FIELDS = { status: 'status', declared_amount_cny_100m: 'amount', accepted_date: 'accepted', approved_date: 'approved', issued_date: 'issued' };
function institutionalFields() { return state.fields === 'all' ? INSTITUTIONAL_FIELDS : INSTITUTIONAL_FIELDS.filter(spec => CORE_INSTITUTIONAL_FIELDS.has(spec.key)); }
function institutionalContext(record, sequence) { return { population: 'institutional', sequence, classification: classification(record), statusLabel }; }
function institutionalHeader() { return $('institutional-table-head-row') || $('rows').closest('table')?.querySelector('thead tr'); }
function renderInstitutionalHeader(fields) {
  const head = institutionalHeader();
  if (!head) return;
  head.innerHTML = fields.map(spec => {
    const sort = INSTITUTIONAL_SORT_FIELDS[spec.key];
    const active = sort && state.sort === sort;
    const direction = active ? state.direction < 0 ? 'descending' : 'ascending' : 'none';
    const arrow = active ? state.direction < 0 ? '↓' : '↑' : '↕';
    const label = escapeHTML(spec.label);
    return `<th scope="col"${['amount', 'integer'].includes(spec.type) ? ' class="numeric"' : ''}${sort ? ` aria-sort="${direction}"` : ''}>${sort ? `<button type="button" class="sort-button" data-sort="${sort}" aria-label="按${label}排序">${label} ${arrow}</button>` : label}</th>`;
  }).join('') + '<th scope="col">来源与依据</th>';
  document.querySelectorAll('[data-institutional-fields]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.institutionalFields === state.fields)));
}
function institutionalTableCell(record, spec, context) {
  const text = projectFieldCellText(record, spec, context);
  if (spec.key === 'name') {
    const saved = favorites.has(record.id);
    const category = context.classification;
    return `<td class="name-cell"><div class="name-line"><button class="star${saved ? ' saved' : ''}" data-save="${escapeHTML(record.id)}" aria-label="${saved ? '取消关注' : '关注'}${escapeHTML(record.name)}" aria-pressed="${saved}">${saved ? '★' : '☆'}</button><button type="button" class="name-link" data-detail="${escapeHTML(record.id)}">${escapeHTML(text)}</button></div><div class="row-sub">${record.is_expansion ? '<span class="mini-tag">扩募</span>' : ''}${archived(record) ? '<span class="mini-tag archive-tag">历史保留</span>' : ''}<span class="confidence-tag ${category.confidence}" title="${escapeHTML(classificationSource(category))}">${confidenceLabel(category.confidence)}</span>${category.source === 'local_manual' ? '<span>本地人工修订</span>' : ''}</div></td>`;
  }
  if (spec.key === 'status') return `<td><span class="status ${String(record.status) === '4' ? 'ok' : ['8', '5'].includes(String(record.status)) ? 'muted' : 'wait'}">${escapeHTML(text)}</span></td>`;
  if (spec.key === 'asset_type') {
    const category = context.classification;
    return `<td><span class="mini-tag${category.psub === '待分类' ? ' review-tag' : ''}">${escapeHTML(text)}</span>${category.psub !== '待分类' ? `<div class="row-sub"><span class="mini-tag rights-tag${category.ptype === '经营权类' ? ' operating-tag' : ''}">${escapeHTML(category.ptype)}</span></div>` : ''}</td>`;
  }
  const className = spec.key === 'declared_amount_cny_100m' || spec.key === 'sequence' ? 'numeric' : ['accepted_date', 'approved_date', 'issued_date'].includes(spec.key) ? 'date' : ['origin', 'manager'].includes(spec.key) ? 'mgr' : '';
  return `<td${className ? ` class="${className}"` : ''}${spec.key === 'underlying_assets' ? ` title="${escapeHTML(text)}"` : ''}>${escapeHTML(text)}</td>`;
}
function render() {
  syncFilterSelects();
  const data = currentRecords();
  const pages = Math.max(1, Math.ceil(data.length / state.pageSize));
  state.page = Math.min(pages, Math.max(1, state.page));
  const start = (state.page - 1) * state.pageSize;
  const totalAmount = data.reduce((sum, record) => sum + (amount(record) ?? 0), 0);
  const approved = data.filter(record => String(record.status) === '4').length;
  const unknown = data.filter(record => classification(record).confidence === 'unknown').length;
  const stats = [['当前匹配记录', format(data.length), '条'], ['审核通过', format(approved), '条'], ['申报金额', format(totalAmount), '亿元'], ['资产待分类', format(unknown), '条']];
  const icons = ['<path d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z"/>', '<path d="m6 12 4 4 8-9M4 3h16v18H4z"/>', '<path d="M4 20h16M6 16v-5M12 16V5M18 16V8"/>', '<path d="M4 5h7l2 3h7v12H4zM9 14h6M12 11v6"/>'];
  $('stats').innerHTML = stats.map(([label, value, unit], index) => `<div class="stat"><div class="stat-label">${label}<svg class="stat-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[index]}</svg></div><div class="stat-value">${value}<small>${unit}</small></div></div>`).join('');
  renderBars('rights-chart', grouped(data, record => classification(record).ptype), { limit: Infinity, filter: 'rights' });
  renderBars('asset-chart', grouped(data, record => classification(record).psub), { limit: Infinity, filter: 'asset' });
  renderBars('status-chart', grouped(data, record => String(record.status)), { isStatus: true, limit: Infinity });
  renderBars('manager-chart', grouped(data, record => record.writer || record.mgr));
  $('record-total').textContent = `${format(data.length)} 条`;
  const fields = institutionalFields();
  $('institutional-table')?.classList.toggle('institutional-table-all', state.fields === 'all');
  renderInstitutionalHeader(fields);
  $('rows').innerHTML = data.slice(start, start + state.pageSize).map((record, index) => {
    const context = institutionalContext(record, start + index + 1);
    const url = sourceURL(record);
    return `<tr>${fields.map(spec => institutionalTableCell(record, spec, context)).join('')}<td>${url ? `<a class="source-link" href="${escapeHTML(url)}" target="_blank" rel="noopener noreferrer">${sourceLabel(record)} ↗</a>` : '<span class="muted">链接暂缺</span>'}<div class="row-sub"><button type="button" class="detail-button" data-detail="${escapeHTML(record.id)}">项目详情 ↗</button></div></td></tr>`;
  }).join('') || `<tr><td colspan="${fields.length + 1}" class="empty">${snapshot ? '当前条件没有匹配记录' : '项目库尚未读取成功，请点击刷新数据'}</td></tr>`;
  $('page-count').textContent = data.length ? `显示 ${start + 1}–${Math.min(start + state.pageSize, data.length)} 条，共 ${data.length} 条` : '共 0 条';
  $('page-number').textContent = `${state.page} / ${pages}`;
  $('prev').disabled = state.page <= 1;
  $('next').disabled = state.page >= pages;
  $('export').disabled = !snapshot;

}
function renderMetadata() {
  if (!snapshot) return;
  const warnings = [];
  if (cachedView) warnings.push('在线数据读取失败，正在展示此浏览器上次成功读取的快照。');
  const timestamp = Date.parse(snapshot.updated_at || `${snapshot.date}T08:00:00+08:00`);
  const morningWarning = refreshWarning(snapshot);
  if (morningWarning) warnings.push(morningWarning);
  if (snapshot.coverage?.complete === false) warnings.push('本轮抓取未完成全部来源，当前数据可能不完整。');
  for (const [source, info] of Object.entries(snapshot.source_status || {})) {
    if (info?.ok === false) warnings.push(`${source === 'SSE' ? '上交所' : source === 'SZSE' ? '深交所' : source}本轮更新未完成。`);
  }
  if (snapshot.quality?.detail_warnings?.length) warnings.push(`${snapshot.quality.detail_warnings.length} 条项目详情本轮未能补全，部分机构字段可能缺失。`);
  const missingLinks = records.filter(record => !sourceURL(record)).length;
  if (missingLinks) warnings.push(`${missingLinks} 条记录暂缺可用官方项目链接。`);
  if (storageWarning) warnings.push(storageWarning);
  $('data-notice').hidden = warnings.length === 0;
  $('data-notice').textContent = warnings.join(' ');
  $('data-pill').textContent = `${cachedView ? '本地快照' : snapshot.coverage?.complete === false ? '部分更新' : '数据日期'} ${snapshot.date}`;
  if (activeModule === 'institutional') $('side-date').textContent = snapshot.date;
  const updatedAt = Number.isFinite(timestamp) ? new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(timestamp)) : snapshot.date;
  $('footer-date').textContent = `更新时间：${updatedAt}（北京时间）${cachedView ? ' · 浏览器缓存' : ''}`;
  const officialLinks = records.filter(record => sourceURL(record)).length;
  const retained = records.filter(archived).length;
  $('source-metadata').textContent = `本期${records.length}条记录，${officialLinks}条具备官方项目链接，${retained}条历史保留记录。快照日期：${snapshot.date}。${snapshot.enrichment?.checked_at ? `披露核查：${snapshot.enrichment.checked_at.slice(0, 10)}。各字段来源、文件日期和未取得原因见项目详情。` : ''}`;
}
function applySnapshot(data, fromCache = false) {
  snapshot = validated(data);
  records = snapshot.items;
  byId = new Map(records.map(record => [record.id, record]));
  cachedView = fromCache;
  rebuildOptions();
  renderMetadata();
  render();
}
async function loadData() {
  if (institutionalLoading) return institutionalLoading;
  institutionalLoading = (async () => {
  $('reload').disabled = true;
  $('loading-state').hidden = false;
  $('loading-state').textContent = '正在读取项目库…';
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(DATA_URL, { cache: 'no-store', signal: controller.signal });
    if (!response.ok) throw new Error(`数据读取失败（HTTP ${response.status}）`);
    const data = validated(await response.json());
    applySnapshot(data);
    writeStorage(STORAGE.snapshot, data);
  } catch (error) {
    const last = snapshot || readStorage(STORAGE.snapshot, null);
    try {
      if (!last) throw error;
      applySnapshot(last, true);
    } catch {
      $('data-pill').textContent = '读取失败';
      $('data-notice').hidden = false;
      $('data-notice').textContent = '项目库读取失败，当前浏览器没有可用快照。请稍后刷新，或查看数据文件。';
      render();
    }
  } finally { clearTimeout(timer); $('loading-state').hidden = true; $('reload').disabled = false; }
  })();
  try { return await institutionalLoading; } finally { institutionalLoading = null; }
}
function openDetail(id) {
  closeFilterMenu();
  const record = byId.get(id);
  if (!record) return;
  const category = classification(record);
  const url = sourceURL(record);
  const linkStatus = { verified: '已核验', constructed: '依据官方项目 ID 构建，待逐条核验', unverified: '尚未核验' }[record.link_status] || '尚未核验';
  const sequence = currentRecords().findIndex(item => item.id === id) + 1;
  const context = institutionalContext(record, sequence || records.findIndex(item => item.id === id) + 1);
  const detailGroups = [
    ['项目概况', ['sequence', 'name', 'status', 'exchange']],
    ['资产与参与机构', ['declared_amount_cny_100m', 'asset_type', 'underlying_assets', 'origin', 'manager']],
    ['审核与发行', ['accepted_date', 'approved_date', 'issued_date', 'is_issued']]
  ];
  const groupedFields = detailGroups.map(([title, keys]) => `<section><h3>${title}</h3><dl class="detail-grid">${keys.map(key => INSTITUTIONAL_FIELDS.find(spec => spec.key === key)).filter(Boolean).map(spec => `<div><dt>${escapeHTML(spec.label)}</dt><dd>${escapeHTML(projectFieldCellText(record, spec, context))}${fieldEvidenceHTML(record, spec.key, context)}</dd></div>`).join('')}</dl></section>`).join('');
  const extraFields = [['研究大类', category.ptype], ['分类来源', classificationSource(category)], ['资产确认程度', confidenceLabel(category.confidence)], ['更新日期', record.up || '未披露'], ['名称命中口径', keywords(record).join('、') || '未提供'], ['记录状态', archived(record) ? '历史保留：本轮未再次检索到' : '本轮检索结果']];
  const options = (values, selected) => values.map(value => `<option value="${escapeHTML(value)}"${value === selected ? ' selected' : ''}>${escapeHTML(value)}</option>`).join('');
  const evidenceLinks = category.evidence.map(item => `<li><a href="${escapeHTML(item.url)}" target="_blank" rel="noopener noreferrer"><span aria-hidden="true">↗</span>${escapeHTML(item.title)}</a> <span>${escapeHTML(new URL(item.url).hostname.replace(/^www\./, ''))}</span></li>`).join('');
  $('detail-body').innerHTML = `<div class="detail-name">${escapeHTML(record.name)}</div>${groupedFields}<section><h3>来源与分类记录</h3><dl class="detail-grid">${extraFields.map(([label, value]) => `<div><dt>${escapeHTML(label)}</dt><dd>${escapeHTML(value)}</dd></div>`).join('')}</dl></section><div class="classification-evidence"><h3>分类依据 <span class="confidence-tag ${category.confidence}">${confidenceLabel(category.confidence)}</span></h3><p>${escapeHTML(category.note)}</p>${evidenceLinks ? `<ul class="evidence-links" aria-label="分类来源材料">${evidenceLinks}</ul>` : ''}<p class="muted evidence-label">确认程度针对底层资产类型。产权／经营权为研究分类，具体法律权利以披露文件为准。</p>${category.source === 'keyword' ? '<p class="muted">名称关键词仅提供初步线索，尚未逐项核实底层资产。</p>' : ''}${category.source === 'local_manual' ? `<p class="muted">数据文件分类：${escapeHTML(normalizedAsset(record.psub))}；依据：${escapeHTML(record.pnote || '未提供')}。</p>` : ''}</div><form id="classification-form" class="classification-box"><h3>本地分类修订</h3><div class="classification-fields"><label class="field">研究大类<select name="rights">${options(RIGHTS, category.ptype)}</select></label><label class="field">资产细类<select name="asset">${options(TAXONOMY[category.ptype], category.psub)}</select></label></div><label class="field">分类依据／备注<textarea name="note" rows="3" maxlength="1000" required placeholder="写明披露文件、资产说明或判断依据">${category.source === 'local_manual' ? escapeHTML(category.note) : ''}</textarea></label><div class="classification-actions"><button class="button primary" type="submit">保存分类</button><button class="button" type="button" id="restore-classification"${category.source !== 'local_manual' ? ' disabled' : ''}>恢复数据文件分类</button></div><p class="classification-note">细类随研究大类联动。修订与依据仅保存在当前浏览器，导出结果会携带本地分类。</p><p id="classification-feedback" class="live" role="status"></p></form><div class="detail-source">官方项目 ID：${escapeHTML(record.source_id || record.id)}<p>来源链接：${escapeHTML(linkStatus)}${record.source_kind === 'project_data' ? '。深交所来源为该项目的官方原始数据。' : ''}</p>${url ? `<a href="${escapeHTML(url)}" target="_blank" rel="noopener noreferrer">打开${escapeHTML(record.ex)}${sourceLabel(record)} ↗</a>` : '<span class="muted">本条记录暂无可用官方详情链接。</span>'}</div>`;
  if (!$('detail-dialog').open) $('detail-dialog').showModal();
  const formElement = $('classification-form');
  formElement.elements.rights.addEventListener('change', event => {
    const allowed = TAXONOMY[event.target.value];
    const selected = formElement.elements.asset.value;
    formElement.elements.asset.innerHTML = options(allowed, allowed.includes(selected) ? selected : allowed[0]);
  });
  $('classification-form').addEventListener('submit', event => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const psub = String(form.get('asset'));
    const ptype = String(form.get('rights'));
    const pnote = String(form.get('note') || '').trim();
    if (!validClassification(ptype, psub) || !pnote) { $('classification-feedback').textContent = '请选择对应的研究大类与资产细类，并填写分类依据。'; return; }
    overrides[id] = { psub, ptype, pnote };
    const persisted = writeStorage(STORAGE.overrides, overrides);
    rebuildOptions(); render(); openDetail(id);
    $('classification-feedback').textContent = persisted ? '分类已保存，统计与表格已同步更新。' : '分类已在本页生效；浏览器限制存储，刷新后可能丢失。';
  });
  $('restore-classification').addEventListener('click', () => {
    delete overrides[id];
    const persisted = writeStorage(STORAGE.overrides, overrides);
    rebuildOptions(); render(); openDetail(id);
    $('classification-feedback').textContent = persisted ? '已恢复数据文件中的分类。' : '本页已恢复数据文件分类；浏览器限制存储。';
  });
}
function csvCell(value) {
  let text = String(value ?? '');
  if (/^[\s\u0000-\u001f]*[=+\-@]/.test(text)) text = `'${text}`;
  return `"${text.replace(/"/g, '""')}"`;
}
function exportCSV() {
  if (!snapshot) return;
  const traceHeaders = ['官方项目ID', 'source_url', 'match_keywords', '更新日期', '研究大类', '分类来源', '分类依据', '资产确认程度', '分类证据', '分类待复核', '是否扩募', 'archive_status', '链接核验状态', '原始研究大类', '原始资产类型', '原始分类来源', '原始分类依据', '原始分类确认程度', '原始底层资产', '原始通过时间', '原始发行时间', '原始是否已发行', ...INSTITUTIONAL_FIELDS.filter(spec => spec.key !== 'sequence').map(spec => `${spec.label}：披露来源及日期`)];
  const table = [[...INSTITUTIONAL_FIELDS.map(spec => spec.label), ...traceHeaders], ...currentRecords().map((record, index) => {
    const context = institutionalContext(record, index + 1);
    const category = context.classification;
    return [...INSTITUTIONAL_FIELDS.map(spec => projectFieldCellText(record, spec, context)), record.source_id || record.id, sourceURL(record), keywords(record).join(' | '), record.up, category.ptype, classificationSource(category), category.note, confidenceLabel(category.confidence), category.evidence.map(item => `${item.title}: ${item.url}`).join(' | '), category.needsReview ? '是' : '否', record.is_expansion ? '是' : '否', record.archive_status || 'current', record.link_status || 'unverified', record.ptype, record.psub, record.classification_source, record.pnote, record.classification_confidence, typeof record.underlying_assets === 'object' ? JSON.stringify(record.underlying_assets) : record.underlying_assets, record.approved_date, record.issued_date, typeof record.is_issued === 'boolean' ? String(record.is_issued) : '', ...INSTITUTIONAL_FIELDS.filter(spec => spec.key !== 'sequence').map(spec => fieldEvidenceText(record, spec.key, context))];
  })];
  const blob = new Blob(['\uFEFF' + table.map(row => row.map(csvCell).join(',')).join('\r\n')], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a'); link.href = url; link.download = `REITs_机构间项目_${snapshot.date}.csv`; document.body.appendChild(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

$('search').addEventListener('input', event => { state.kw = event.target.value; state.page = 1; render(); });
for (const id of ['rights', 'asset', 'status', 'confidence', 'match']) $(id).addEventListener('change', event => {
  state[id] = event.target.value;
  if (id === 'rights') rebuildAssetOptions();
  if (id === 'asset' && state.asset) { state.rights = rightsForAsset(state.asset); $('rights').value = state.rights; rebuildAssetOptions(); }
  state.page = 1; render();
});
for (const id of ['rights-chart', 'asset-chart']) $(id).addEventListener('click', event => {
  const button = event.target.closest('[data-class-filter]');
  if (button) selectClassificationFilter(button.dataset.classFilter, button.dataset.classValue);
});
for (const [id, key] of [['saved-only', 'savedOnly'], ['hide-archived', 'hideArchived']]) $(id).addEventListener('change', event => { state[key] = event.target.checked; state.page = 1; render(); });
for (const [attribute, key] of [['data-ex', 'ex'], ['data-mode', 'mode']]) document.querySelectorAll(`[${attribute}]`).forEach(button => button.addEventListener('click', () => { state[key] = button.getAttribute(attribute); state.page = 1; document.querySelectorAll(`[${attribute}]`).forEach(other => other.setAttribute('aria-pressed', String(other === button))); render(); }));
institutionalHeader()?.addEventListener('click', event => {
  const button = event.target.closest('[data-sort]');
  if (!button) return;
  state.direction = state.sort === button.dataset.sort ? -state.direction : -1;
  state.sort = button.dataset.sort; state.page = 1; render();
});
document.addEventListener('click', event => {
  const button = event.target.closest('[data-institutional-fields]');
  if (!button || !['core', 'all'].includes(button.dataset.institutionalFields)) return;
  state.fields = button.dataset.institutionalFields;
  writeStorage(STORAGE.fields, state.fields);
  render();
});
$('prev').addEventListener('click', () => { state.page--; render(); });
$('next').addEventListener('click', () => { state.page++; render(); });
$('page-size').addEventListener('change', event => { state.pageSize = Number(event.target.value); state.page = 1; render(); });
$('reset').addEventListener('click', () => {
  Object.assign(state, { ex: '', kw: '', rights: '', asset: '', status: '', confidence: '', match: '', savedOnly: false, hideArchived: false, sort: 'updated', direction: -1, page: 1 });
  for (const id of ['search', 'rights', 'asset', 'status', 'confidence', 'match']) $(id).value = '';
  rebuildAssetOptions();
  for (const id of ['saved-only', 'hide-archived']) $(id).checked = false;
  document.querySelectorAll('[data-ex]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.ex === '')));
  render();
});
$('rows').addEventListener('click', event => {
  const save = event.target.closest('[data-save]');
  if (save) {
    const id = save.dataset.save; if (favorites.has(id)) favorites.delete(id); else favorites.add(id);
    if (!writeStorage(STORAGE.favorites, [...favorites])) { storageWarning = '浏览器限制存储，关注标记在刷新后可能丢失。'; renderMetadata(); }
    render(); return;
  }
  const detail = event.target.closest('[data-detail]'); if (detail) openDetail(detail.dataset.detail);
});
document.querySelectorAll('[data-close]').forEach(button => button.addEventListener('click', () => $(button.dataset.close).close()));
document.querySelectorAll('dialog').forEach(dialog => dialog.addEventListener('click', event => { if (event.target === dialog) { const box = dialog.getBoundingClientRect(); if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) dialog.close(); } }));
$('source-nav').addEventListener('click', () => { closeFilterMenu(); if (activeModule === 'updates') openUpdatesSources(); else if (activeModule === 'public') openPublicSources(); else $('source-dialog').showModal(); });
$('classification-help').addEventListener('click', () => { closeFilterMenu(); $('source-dialog').showModal(); });
$('taxonomy-guide').innerHTML = RIGHTS.map(rights => `<div class="taxonomy-group"><strong>${escapeHTML(rights)}</strong><span>${escapeHTML(TAXONOMY[rights].join('、'))}</span></div>`).join('');
function showModule(name) {
  closeFilterMenu();
  activeModule = ['updates', 'public', 'institutional'].includes(name) ? name : 'updates';
  for (const module of ['updates', 'public', 'institutional']) {
    const active = activeModule === module;
    $(`${module}-panel`).hidden = !active;
    $(`${module}-nav`).classList.toggle('active', active);
    if (active) $(`${module}-nav`).setAttribute('aria-current', 'page'); else $(`${module}-nav`).removeAttribute('aria-current');
  }
  document.querySelector('.skip-link').href = { updates: '#updates-list', public: '#public-projects', institutional: '#projects' }[activeModule];
  setPublicModuleActive(activeModule === 'public');
  setUpdatesModuleActive(activeModule === 'updates');
  if (activeModule === 'institutional') {
    $('side-date').textContent = snapshot?.date || '正在读取';
    $('side-schedule').textContent = REFRESH_SCHEDULE;
    $('side-source').textContent = '上交所／深交所公开申报';
    if (!snapshot && !institutionalLoading) loadData();
  }
}
$('updates-nav').addEventListener('click', () => showModule('updates'));
$('institutional-nav').addEventListener('click', () => showModule('institutional'));
$('public-nav').addEventListener('click', () => showModule('public'));
$('export').addEventListener('click', exportCSV);
$('reload').addEventListener('click', loadData);
initializePublicReits();
initializeProjectUpdates({ onOpenProject: async project => {
  if (project.population === 'institutional') {
    showModule('institutional');
    if (!snapshot) await loadData();
    if (!byId.has(project.entity_id)) { showModule('updates'); return false; }
    openDetail(project.entity_id);
    return true;
  }
  showModule('public');
  const opened = await openPublicRecord(project);
  if (!opened) showModule('updates');
  return opened;
} });
enhanceFilterSelects();
render();
showModule('updates');
