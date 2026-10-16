/* An auditable event feed; baseline snapshots never become new discoveries. */
import { syncFilterSelects } from './filter-select.js?v=20261014-filter-menu-1';
const DATA_URL = new URL('../data/project_updates.json', import.meta.url);
const COMPRESSED_DATA_URL = new URL('../data/project_updates.json.gz', import.meta.url);
const POPULATIONS = { public: '公募REITs', institutional: '机构间REITs', ndrc: '发改委推荐' };
const EVENT_LABELS = { status_change: '状态变化', status_changed: '状态变化', new_project: '新增项目', document_added: '新增披露', documents_added: '新增披露', revision: '资料修订', metadata_changed: '资料修订', recommendation: '新增推荐', recommendation_added: '新增推荐', milestone: '阶段进展', historical_milestone: '历史进展', baseline: '历史基线' };
const DEFAULT_FILTERS = { population: '', range: 'all', start: '', end: '', search: '', exchange: '', asset: '', business: '', type: '', savedOnly: false, includeHistory: false, page: 1, pageSize: 25 };
let state = { ...DEFAULT_FILTERS };
let dailyPopulation = '';
let snapshot = null;
let active = false;
let initialized = false;
let loading = null;
let error = '';
let callbacks = {};
let lastEntity = null;
const $ = id => document.getElementById(id);
const dateCache = new Map();
const chinaDateFormatter = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' });

export function updateDate(value) {
  if (/^\d{4}-\d{2}-\d{2}$/.test(String(value || ''))) return value;
  if (dateCache.has(value)) return dateCache.get(value);
  const date = new Date(value || '');
  if (!Number.isFinite(date.getTime())) return '';
  const parts = chinaDateFormatter.formatToParts(date);
  const result = ['year', 'month', 'day'].map(key => parts.find(part => part.type === key).value).join('-');
  if (dateCache.size > 10000) dateCache.clear();
  dateCache.set(value, result);
  return result;
}
const today = () => updateDate(new Date().toISOString());
const isHistory = event => event.is_baseline === true || event.is_backfill === true || ['baseline', 'backfill', 'historical'].includes(event.discovery_type);
export const updateEventDate = event => isHistory(event) ? updateDate(event.official_date || event.event_date) : updateDate(event.detected_at || event.event_date || event.official_date);
const text = value => value == null || value === '' ? '未披露' : Array.isArray(value) ? value.map(text).join('、') : typeof value === 'object' ? Object.entries(value).map(([key, item]) => `${key}：${text(item)}`).join('；') : typeof value === 'boolean' ? value ? '是' : '否' : String(value);
const normalized = value => String(value || '').replace(/\s/g, '').toLowerCase();
export const updateEntityKey = event => `${event.population}:${event.entity_kind || 'project'}:${event.entity_id}`;
const eventLabel = event => EVENT_LABELS[event.event_type] || event.event_type || '项目进展';
export const isUpdateFavorite = (event, favorites) => favorites.has(updateEntityKey(event)) || favorites.has(event.entity_id) || (event.population === 'public' && favorites.has(`${event.entity_kind === 'fund' ? 'fund' : 'event'}:${event.entity_id}`)) || Boolean(event.fund_id && favorites.has(`fund:${event.fund_id}`));
export const hasUpdateBefore = value => value != null && value !== '' && (!Array.isArray(value) || value.length > 0) && (typeof value !== 'object' || Array.isArray(value) || Object.keys(value).length > 0);
export function prioritizeUpdateEvents(events) {
  const priority = { status_change: 0, status_changed: 0, milestone: 1, historical_milestone: 1, new_project: 2, recommendation: 2, recommendation_added: 2, documents_added: 3, document_added: 3, revision: 4 };
  return [...events].sort((a, b) => (priority[a.event_type] ?? 5) - (priority[b.event_type] ?? 5));
}

export function safeUpdateURL(value) {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && !url.username && !url.password && /(^|\.)(sse\.com\.cn|szse\.cn|gov\.cn)$/i.test(url.hostname) ? url.href : '';
  } catch { return ''; }
}

export function validateUpdatesSnapshot(data) {
  if (!data || data.schema_version !== 1 || !Array.isArray(data.events) || !Array.isArray(data.projects) || !/^\d{4}-\d{2}-\d{2}$/.test(data.as_of_date || '') || !data.sources || typeof data.sources !== 'object') throw new Error('项目动态的数据结构不完整');
  const ids = new Set();
  for (const event of data.events) {
    if (!event || !event.id || typeof event.id !== 'string' || ids.has(event.id) || !Object.hasOwn(POPULATIONS, event.population) || !event.entity_id || typeof event.project_name !== 'string' || !event.project_name || !Array.isArray(event.changes || [])) throw new Error('项目动态存在重复标识或缺少必要字段');
    ids.add(event.id);
    if (!isHistory(event) && !updateDate(event.detected_at)) throw new Error('新发现动态缺少可核实的发现日期');
  }
  return data;
}

export function updatePeriod(filters = {}, asOf = today()) {
  const end = filters.range === 'custom' ? filters.end || asOf : asOf;
  if (filters.range === 'custom') return { start: filters.start || '', end, valid: !filters.start || !end || filters.start <= end };
  if (filters.range === 'all') return { start: '', end, valid: true };
  const date = new Date(`${asOf}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() - (filters.range === '30' ? 29 : 6));
  return { start: date.toISOString().slice(0, 10), end, valid: true };
}

export function filterUpdateEvents(events, filters = {}, favorites = new Set(), asOf = today()) {
  const period = updatePeriod(filters, asOf);
  if (!period.valid) return [];
  const needle = normalized(filters.search);
  return events.filter(event => {
    const date = updateEventDate(event);
    return (!isHistory(event) || filters.includeHistory)
      && (!period.start || date >= period.start) && (!period.end || date <= period.end) && Boolean(date)
      && (!filters.population || event.population === filters.population)
      && (!filters.exchange || event.exchange === filters.exchange)
      && (!filters.asset || event.asset_type === filters.asset)
      && (!filters.business || event.business_type === filters.business)
      && (!filters.type || event.event_type === filters.type)
      && (!filters.savedOnly || isUpdateFavorite(event, favorites))
      && (!needle || normalized([event.project_name, event.manager, event.origin, event.fund_code, event.fund_id, event.entity_id, event.title, event.asset_type].join(' ')).includes(needle));
  }).sort((a, b) => updateEventDate(b).localeCompare(updateEventDate(a)) || String(b.detected_at || '').localeCompare(String(a.detected_at || '')) || a.id.localeCompare(b.id));
}

export function groupUpdateEvents(events) {
  const groups = new Map();
  for (const event of events) {
    // Entity IDs identify the official filing batch. Dates keep separate refreshes visible.
    const key = `${updateEntityKey(event)}:${event.business_type || ''}:${updateEventDate(event)}:${event.source_version?.sha256 || ''}:${isHistory(event) ? 'history' : 'observed'}`;
    if (!groups.has(key)) groups.set(key, { key, date: updateEventDate(event), event, events: [] });
    groups.get(key).events.push(event);
  }
  return [...groups.values()];
}

export function summarizeUpdates(events) {
  const result = { total: events.length, projects: new Set(events.map(updateEntityKey)).size, groups: groupUpdateEvents(events).length, observed: 0, historical: 0, public: 0, institutional: 0, ndrc: 0 };
  for (const event of events) { result[event.population]++; result[isHistory(event) ? 'historical' : 'observed']++; }
  return result;
}

export function dailyUpdateEvents(events, population = '', asOf = today()) {
  return filterUpdateEvents(events.filter(event => updateDate(event.detected_at) === asOf), { range: 'custom', start: asOf, end: asOf, population }, new Set(), asOf);
}

export function dailyUpdateCounts(events, asOf = today()) {
  const counts = { public: 0, institutional: 0, ndrc: 0 };
  for (const event of dailyUpdateEvents(events, '', asOf)) {
    if (Object.hasOwn(counts, event.population)) counts[event.population]++;
  }
  return counts;
}

export function updateSourceHealth(sources = {}, asOf = today()) {
  return Object.keys(POPULATIONS).map(key => {
    const source = sources[key] || {};
    const checkedDate = updateDate(source.checked_at);
    const issue = (source.status && source.status !== 'complete') || source.attempt_ok === false || source.error ? '核查失败' : source.complete !== true ? '核查未完成' : !checkedDate ? '缺少核查时间' : checkedDate < asOf ? '待刷新' : '';
    return { key, ...source, label: source.label || POPULATIONS[key], issue, checkedDate, healthy: !issue };
  });
}

export function updatesCSVTable(events, data = {}) {
  const header = ['事件ID', '范围', '项目ID', '项目名称', '业务类型', '交易所', '资产类型', '管理人', '原始权益人', '事件类型', '标题', '变化前', '变化后', '字段变化', '官方日期', '首次发现时间', '列表日期', '记录性质', '官方来源', '基金ID', '关联项目ID', '来源版本', '生成时间'];
  return [header, ...events.map(event => [event.id, POPULATIONS[event.population], event.entity_id, event.project_name, event.business_type || '', event.exchange || '', event.asset_type || '', event.manager || '', event.origin || '', eventLabel(event), event.title || '', text(event.before), text(event.after), (event.changes || []).map(change => `${change.label || change.field}：${text(change.before)} → ${text(change.after)}`).join('；'), event.official_date || '', event.detected_at || '', updateEventDate(event), isHistory(event) ? '历史回填' : '持续跟踪', safeUpdateURL(event.source_url), event.fund_id || '', (event.related_entity_ids || []).join('；'), text(event.source_version), data.generated_at || ''])];
}
export function updatesCSVCell(value) {
  let cell = value == null ? '' : String(value);
  if (/^[\s\u0000-\u001f\u007f-\u009f\u200b\u200c\u200d\u2060\ufeff]*[=+\-@]/.test(cell)) cell = `'${cell}`;
  return `"${cell.replaceAll('"', '""')}"`;
}

function el(tag, className = '', content) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content != null) node.textContent = String(content);
  return node;
}
function button(label, className, action, value) {
  const node = el('button', className, label);
  node.type = 'button';
  if (action) { node.dataset.updatesAction = action; if (value != null) node.dataset.value = String(value); }
  return node;
}
function externalLink(label, url) {
  const safe = safeUpdateURL(url);
  if (!safe) return null;
  const node = el('a', 'updates-source-link', label);
  node.href = safe; node.target = '_blank'; node.rel = 'noopener noreferrer';
  return node;
}
function add(parent, ...children) { parent.append(...children.filter(Boolean)); return parent; }
function labeledControl(label, id, type = 'select', options = []) {
  const wrapper = el('div', 'field');
  const caption = el('label', '', label); caption.htmlFor = id; caption.id = `${id}-label`;
  wrapper.append(caption);
  const input = el(type === 'select' ? 'select' : 'input'); input.id = id;
  if (type !== 'select') input.type = type;
  for (const [value, name] of options) { const option = el('option', '', name); option.value = value; input.append(option); }
  wrapper.append(input); return wrapper;
}

function buildUI() {
  const panel = $('updates-panel');
  if (!panel) throw new Error('缺少项目动态页面容器');
  panel.classList.add('updates-panel');
  const head = el('header', 'head');
  const heading = el('div'); const eyebrow = add(el('div', 'eyebrow'), el('span', 'eyebrow-line'), el('span', '', 'PROJECT UPDATES'));
  add(heading, eyebrow, el('h1', '', '项目动态'));
  const actions = el('div', 'header-actions'); const pill = el('span', 'pill', '正在读取动态'); pill.id = 'updates-data-pill';
  const exportButton = button('↓ 导出动态库', 'button primary', 'export'); exportButton.id = 'updates-export'; exportButton.disabled = true;
  add(actions, pill, add(el('div', 'action-buttons'), button('↻ 刷新动态', 'button', 'reload'))); add(head, heading, actions);
  const notice = el('div', 'data-notice'); notice.id = 'updates-notice'; notice.setAttribute('role', 'status'); notice.hidden = true;
  const sources = el('div', 'updates-source-strip'); sources.id = 'updates-source-strip';
  const stats = el('div', 'updates-stats'); stats.id = 'updates-stats'; stats.setAttribute('aria-live', 'polite');
  const daily = el('section', 'project-box updates-today'); daily.id = 'updates-today'; daily.tabIndex = -1; daily.setAttribute('aria-label', '今日更新');
  const dailyDate = el('time', 'updates-today-date'); dailyDate.id = 'updates-today-date';
  const dailyAll = button('全部', 'text-button', 'today-population', ''); dailyAll.id = 'updates-today-all';
  const dailyList = el('div', 'updates-list updates-today-list'); dailyList.id = 'updates-today-list'; dailyList.setAttribute('aria-live', 'polite');
  add(daily, add(el('div', 'project-top'), el('h2', '', '今日更新'), add(el('div', 'updates-today-tools'), dailyDate, dailyAll)), stats, dailyList);
  const box = el('section', 'project-box updates-feed'); box.id = 'updates-feed'; box.tabIndex = -1; box.setAttribute('aria-label', '全部动态库');
  const top = el('div', 'project-top'); const topHeading = add(el('div'), el('h2', '', '全部动态库'));
  const range = el('div', 'segment updates-ranges'); range.setAttribute('role', 'group'); range.setAttribute('aria-label', '动态时间范围');
  for (const [value, name] of [['all', '全部'], ['7', '近7天'], ['30', '近30天'], ['custom', '自定义']]) range.append(button(name, '', 'range', value));
  add(top, topHeading, add(el('div', 'updates-library-tools'), range, exportButton));
  const populations = el('div', 'segment updates-populations'); populations.setAttribute('role', 'group'); populations.setAttribute('aria-label', '动态范围');
  for (const [value, name] of [['', '全部'], ...Object.entries(POPULATIONS)]) populations.append(button(name, '', 'population', value));
  const custom = el('div', 'updates-custom-dates'); custom.id = 'updates-custom-dates'; custom.hidden = true;
  add(custom, labeledControl('起始日期', 'updates-start', 'date'), labeledControl('截止日期', 'updates-end', 'date'));
  const filters = el('div', 'filters updates-filters');
  const search = labeledControl('搜索项目／机构', 'updates-search', 'search'); search.classList.add('search-field'); search.lastChild.placeholder = '项目、基金代码、原始权益人或管理人';
  add(filters, search, labeledControl('交易所', 'updates-exchange', 'select', [['', '全部交易所']]), labeledControl('资产类型', 'updates-asset', 'select', [['', '全部资产']]), labeledControl('业务类型', 'updates-business', 'select', [['', '全部业务']]), labeledControl('事件类型', 'updates-type', 'select', [['', '全部事件']]), button('↺ 重置筛选', 'button reset-button', 'reset'));
  const foot = el('div', 'filter-foot');
  const extras = el('div', 'filter-extras');
  for (const [id, label] of [['updates-saved-only', '仅看关注项目'], ['updates-include-history', '包含历史回填']]) { const wrapper = el('label'); const input = el('input'); input.type = 'checkbox'; input.id = id; add(wrapper, input, document.createTextNode(label)); extras.append(wrapper); }
  add(foot, extras);
  const list = el('div', 'updates-list'); list.id = 'updates-list'; list.setAttribute('aria-live', 'polite');
  const pagination = el('div', 'pagination'); const pageCount = el('span'); pageCount.id = 'updates-page-count'; const pages = el('div', 'pages'); const pageNumber = el('span'); pageNumber.id = 'updates-page-number';
  add(pages, button('上一页', 'button', 'prev'), pageNumber, button('下一页', 'button', 'next')); add(pagination, pageCount, pages);
  add(box, top, populations, custom, filters, foot, list, pagination);
  const footer = el('footer', 'foot'); const generated = el('span'); generated.id = 'updates-generated'; add(footer, generated, button('数据口径与来源 ↗', 'text-button', 'sources'));
  const detail = el('dialog', 'updates-detail-dialog'); detail.id = 'updates-detail-dialog'; detail.setAttribute('aria-labelledby', 'updates-detail-title');
  const sourceDialog = el('dialog', 'updates-source-dialog'); sourceDialog.id = 'updates-source-dialog'; sourceDialog.setAttribute('aria-labelledby', 'updates-source-title');
  panel.replaceChildren(head, notice, sources, daily, box, footer, detail, sourceDialog);
}

function readFavoriteSet() {
  const result = new Set();
  try {
    const paths = [
      [`reits:${new URL('../data/institutional.json', import.meta.url).pathname}:v1:favorites`, 'institutional', 'project'],
      [`reits:public:${new URL('../data/public_reits.json', import.meta.url).pathname}:v1:favorites`, 'public', ''],
      [`reits:ndrc:${new URL('../data/ndrc_recommendations.json', import.meta.url).pathname}:v1:favorites`, 'ndrc', 'recommendation']
    ];
    for (const [key, population, kind] of paths) {
      const values = JSON.parse(localStorage.getItem(key) || '[]');
      if (!Array.isArray(values)) continue;
      for (const value of values.filter(item => typeof item === 'string')) {
        result.add(value);
        if (population === 'public') { const match = value.match(/^(fund|event):(.*)$/); if (match) result.add(`${population}:${match[1] === 'event' ? 'filing' : 'fund'}:${match[2]}`); }
        else if (population) result.add(`${population}:${kind}:${value}`);
      }
    }
  } catch { /* A restricted browser can still browse all events. */ }
  return result;
}
function currentEvents() { return filterUpdateEvents(snapshot?.events || [], state, readFavoriteSet()); }

function fillOptions() {
  for (const [key, property] of [['exchange', 'exchange'], ['asset', 'asset_type'], ['business', 'business_type'], ['type', 'event_type']]) {
    const select = $(`updates-${key}`); const first = select.firstElementChild.cloneNode(true);
    select.replaceChildren(first);
    const values = [...new Set((snapshot?.events || []).map(event => event[property]).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'zh-CN'));
    for (const value of values) { const option = el('option', '', key === 'type' ? EVENT_LABELS[value] || value : value); option.value = value; select.append(option); }
    select.value = state[key];
  }
}
function sourceStrip() {
  const strip = $('updates-source-strip'); strip.replaceChildren();
  for (const source of updateSourceHealth(snapshot?.sources)) {
    const item = el('div', `updates-source-status${source.healthy ? '' : ' is-warning'}`);
    add(item, el('span', 'updates-status-dot'), el('strong', '', POPULATIONS[source.key]), el('span', '', source.checked_at ? `更新时间 ${String(source.checked_at).replace('T', ' ').slice(0, 16)}` : '更新时间 暂无'), source.issue ? el('span', 'updates-source-issue', source.issue) : null);
    strip.append(item);
  }
}
function renderStats() {
  const day = today(); const counts = dailyUpdateCounts(snapshot?.events || [], day);
  const stats = $('updates-stats'); stats.replaceChildren();
  for (const population of ['public', 'institutional', 'ndrc']) {
    const selected = dailyPopulation === population;
    const card = button('', `stat updates-stat${selected ? ' selected' : ''}`, 'today-population', population);
    card.setAttribute('aria-pressed', String(selected));
    card.setAttribute('aria-label', `查看${POPULATIONS[population]}今日${counts[population]}条更新`);
    card.title = `${day} · 北京时间`;
    add(card, el('span', 'stat-label', POPULATIONS[population]), add(el('span', 'stat-value'), document.createTextNode(String(counts[population])), el('small', '', '条更新')));
    stats.append(card);
  }
}
function renderToday() {
  if (!initialized) return;
  renderStats();
  const day = today(); const date = $('updates-today-date'); date.textContent = day; date.dateTime = day;
  $('updates-today-all').setAttribute('aria-pressed', String(!dailyPopulation));
  const list = $('updates-today-list'); list.replaceChildren();
  for (const group of groupUpdateEvents(dailyUpdateEvents(snapshot?.events || [], dailyPopulation, day))) list.append(renderGroup(group));
  if (!list.children.length) {
    const healthy = updateSourceHealth(snapshot?.sources).filter(source => !dailyPopulation || source.key === dailyPopulation).every(source => source.healthy);
    const message = !snapshot ? error ? '今日动态读取失败' : '正在读取今日更新…' : !healthy ? '今日动态待更新' : `${POPULATIONS[dailyPopulation] || ''}今日暂无更新`;
    list.append(add(el('div', 'updates-empty'), el('strong', '', message)));
  }
}
function changeDisplay(field, value) {
  if (field !== 'related_entity_ids' || !Array.isArray(value)) return text(value);
  const names = value.map(id => (snapshot?.projects || []).find(project => (project.entity_id || project.id) === id)?.project_name
    || snapshot?.events.find(event => event.entity_id === id)?.project_name).filter(Boolean);
  return names.length ? [...new Set(names)].join('、') : `${value.length}项关联`;
}
function changeRows(event) {
  const list = el('div', 'updates-changes');
  if (event.changes?.length) {
    for (const change of event.changes) {
      const row = el('div', 'updates-change');
      const beforePresent = hasUpdateBefore(change.before);
      add(row, el('span', 'updates-change-label', `${change.label || change.field || '变化'}${beforePresent ? '' : '：'}`), beforePresent ? el('span', 'updates-before', changeDisplay(change.field, change.before)) : null, beforePresent ? el('span', 'updates-arrow', '→') : null, el('strong', 'updates-after', changeDisplay(change.field, change.after)));
      list.append(row);
    }
  } else if (event.before != null || event.after != null) {
    const beforePresent = hasUpdateBefore(event.before);
    add(list, add(el('div', 'updates-change'), beforePresent ? el('span', 'updates-before', text(event.before)) : null, beforePresent ? el('span', 'updates-arrow', '→') : null, el('strong', 'updates-after', text(event.after))));
  }
  return list;
}
function eventDetail(event) {
  const item = el('div', 'updates-event-detail');
  add(item, el('strong', 'updates-event-title', event.title || eventLabel(event)), changeRows(event));
  const dates = el('div', 'updates-event-dates');
  if (event.official_date) dates.append(el('span', '', `官方日期 ${updateDate(event.official_date)}`));
  if (event.detected_at) dates.append(el('span', '', `${isHistory(event) ? '收录时间' : '首次发现'} ${String(event.detected_at).replace('T', ' ').slice(0, 16)}`));
  add(item, dates, externalLink('官方披露 ↗', event.source_url));
  if (event.documents?.length) {
    const docs = el('div', 'updates-document-links');
    for (const doc of event.documents) docs.append(...[externalLink(typeof doc === 'object' ? doc.title || doc.name || '披露文件' : '披露文件', typeof doc === 'object' ? doc.url || doc.source_url : doc)].filter(Boolean));
    item.append(docs);
  }
  return item;
}
function renderGroup(group) {
  const events = prioritizeUpdateEvents(group.events); const event = events[0]; const article = el('article', 'updates-row');
  const marker = el('div', 'updates-row-marker'); marker.setAttribute('aria-hidden', 'true');
  const body = el('div', 'updates-row-body'); const line = el('div', 'updates-row-heading');
  const name = button(event.project_name, 'updates-project-name', 'timeline', event.id);
  const tags = el('div', 'updates-tags');
  for (const label of [POPULATIONS[event.population], event.exchange, event.business_type, isHistory(event) ? '历史回填' : '']) if (label) tags.append(el('span', isHistory(event) && label === '历史回填' ? 'updates-tag history' : 'updates-tag', label));
  add(line, name, tags); body.append(line);
  const main = events[0];
  add(body, el('p', 'updates-row-title', events.length === 1 ? main.title || eventLabel(main) : `${[...new Set(events.map(eventLabel))].join('、')} · ${events.length}条事件`), changeRows(main));
  const meta = el('div', 'updates-row-meta');
  add(meta, el('span', '', event.official_date ? `官方日期 ${updateDate(event.official_date)}` : `首次发现 ${updateDate(event.detected_at)}`), event.asset_type ? el('span', '', event.asset_type) : null, event.manager ? el('span', 'updates-manager', event.manager) : null);
  body.append(meta);
  const links = el('div', 'updates-row-links');
  add(links, button('项目时间线', 'text-button', 'timeline', event.id), button('项目库 ↗', 'text-button', 'project', event.id), externalLink('官方披露 ↗', event.source_url));
  body.append(links);
  if (events.length > 1) { const details = el('details', 'updates-group-details'); details.append(el('summary', '', `展开${events.length}条事件明细`)); for (const item of events) details.append(eventDetail(item)); body.append(details); }
  add(article, marker, body); return article;
}
function renderLibrary() {
  if (!initialized) return;
  const events = currentEvents(); const groups = groupUpdateEvents(events);
  const health = updateSourceHealth(snapshot?.sources); const issues = health.filter(item => !item.healthy);
  const period = updatePeriod(state);
  $('updates-export').disabled = !snapshot || !events.length;
  document.querySelectorAll('[data-updates-action="range"]').forEach(node => node.setAttribute('aria-pressed', String(node.dataset.value === state.range)));
  document.querySelectorAll('.updates-populations [data-updates-action="population"]').forEach(node => node.setAttribute('aria-pressed', String(node.dataset.value === state.population)));
  $('updates-custom-dates').hidden = state.range !== 'custom';
  const list = $('updates-list'); list.replaceChildren();
  const pages = Math.max(1, Math.ceil(groups.length / state.pageSize)); state.page = Math.min(pages, Math.max(1, state.page));
  const visible = groups.slice((state.page - 1) * state.pageSize, state.page * state.pageSize);
  let date = '';
  for (const group of visible) { if (date !== group.date) { date = group.date; list.append(el('h3', 'updates-date-heading', date)); } list.append(renderGroup(group)); }
  if (!visible.length) {
    const empty = el('div', 'updates-empty');
    const title = !snapshot ? error ? '动态读取失败' : '正在读取项目动态…' : !period.valid ? '请调整日期范围' : '当前条件没有可展示的动态';
    const hint = !snapshot ? error || '正在核查动态记录与数据来源。' : issues.length ? '部分来源尚未完成核查，请查看上方来源状态。' : state.includeHistory ? '可以扩大日期范围，或重置其他筛选条件。' : '持续跟踪从建立基线后开始；可包含历史回填，查看已有项目的公开进展。';
    add(empty, el('strong', '', title), el('p', '', hint));
    if (snapshot && !state.includeHistory) empty.append(button('查看历史回填', 'button', 'show-history'));
    list.append(empty);
  }
  $('updates-page-count').textContent = `共${groups.length}组动态，每页${state.pageSize}组`;
  $('updates-page-number').textContent = `${state.page} / ${pages}`;
  document.querySelector('[data-updates-action="prev"]').disabled = state.page <= 1;
  document.querySelector('[data-updates-action="next"]').disabled = state.page >= pages;
  syncFilterSelects();
}
function render() {
  if (!initialized) return;
  sourceStrip(); renderToday(); renderLibrary();
  const issues = updateSourceHealth(snapshot?.sources).filter(item => !item.healthy);
  const notice = $('updates-notice');
  notice.textContent = error || (snapshot && issues.length ? `${issues.map(item => `${POPULATIONS[item.key]}${item.issue}`).join('；')}。当前展示最近成功收录的动态，不能据此判断今日是否无变化。` : '');
  notice.hidden = !notice.textContent;
  $('updates-data-pill').textContent = snapshot ? `动态截至 ${snapshot.as_of_date}` : error ? '动态读取失败' : '正在读取动态';
  $('updates-generated').textContent = snapshot ? `生成时间 ${String(snapshot.generated_at || '').replace('T', ' ').slice(0, 16)}` : '';
  const reload = document.querySelector('[data-updates-action="reload"]'); if (reload) reload.disabled = Boolean(loading);
  if (active) { if ($('side-date')) $('side-date').textContent = snapshot?.as_of_date || '正在读取'; if ($('side-schedule')) $('side-schedule').textContent = '每日核查 · 记录项目进展'; if ($('side-source')) $('side-source').textContent = '交易所／国家发改委公开信息'; }
}

function showDialog(dialog) {
  if (!dialog.open) dialog.showModal();
  dialog.scrollTop = 0;
}
function closeButton() { const close = button('关闭', 'button updates-dialog-close', 'close'); close.setAttribute('aria-label', '关闭对话框'); return close; }
export function timelineEvents(events, target) {
  const related = new Set([target.entity_id, ...(target.related_entity_ids || [])]);
  return events.filter(event => updateEntityKey(event) === updateEntityKey(target) || related.has(event.entity_id) || (event.related_entity_ids || []).includes(target.entity_id)).sort((a, b) => (updateDate(b.official_date) || updateEventDate(b)).localeCompare(updateDate(a.official_date) || updateEventDate(a)) || a.id.localeCompare(b.id));
}
function openTimeline(target) {
  if (!target || !snapshot) return;
  lastEntity = target;
  const dialog = $('updates-detail-dialog'); const header = el('div', 'updates-dialog-heading'); const title = el('h2', 'detail-name', target.project_name); title.id = 'updates-detail-title';
  const saved = isUpdateFavorite(target, readFavoriteSet());
  add(header, title, closeButton());
  const tools = el('div', 'updates-dialog-tools');
  const attention = el('span', 'updates-timeline-note', saved ? '★ 项目或所属基金已关注' : '☆ 尚未关注');
  add(tools, attention, button('前往项目库／管理关注 ↗', 'button', 'project', target.id), externalLink('官方项目页 ↗', target.source_url));
  const meta = el('p', 'updates-timeline-note', [POPULATIONS[target.population], target.business_type, target.asset_type, target.fund_code].filter(Boolean).join(' · '));
  const note = el('p', 'updates-timeline-note', '按官方日期排列；缺少官方日期的记录使用发现日期。已确认关联项目一并展示，首发与扩募保留各自批次。');
  const list = el('div', 'updates-timeline');
  for (const event of timelineEvents(snapshot.events, target)) {
    const entry = el('section', 'updates-timeline-entry');
    const day = updateDate(event.official_date) || updateEventDate(event);
    add(entry, el('h3', '', `${day || '日期未披露'} · ${event.business_type || POPULATIONS[event.population]}${isHistory(event) ? ' · 历史回填' : ''}`), event.entity_id !== target.entity_id ? el('p', 'updates-timeline-related', event.project_name) : null, eventDetail(event));
    list.append(entry);
  }
  dialog.replaceChildren(header, meta, tools, note, list); showDialog(dialog);
}
export function openUpdatesSources() {
  if (!initialized) return;
  const dialog = $('updates-source-dialog'); const title = el('h2', '', '项目动态：口径与来源'); title.id = 'updates-source-title';
  const heading = add(el('div', 'updates-dialog-heading'), title, closeButton());
  const intro = el('p', '', '动态来自公募REITs、机构间REITs及国家发展改革委推荐项目的公开资料。三类事件分别统计；状态、业务批次和原始日期保留来源口径。');
  const definitions = el('dl', 'updates-definitions');
  const baselineAt = snapshot?.audit?.tracking_started_at || snapshot?.audit?.baseline_at || snapshot?.audit?.baseline_created_at || snapshot?.generated_at;
  const coverage = `${snapshot ? `持续变化记录自${updateDate(baselineAt) || '本次基线建立时'}开始。` : '跟踪起点待读取。'}首次导入的历史进展未计为新动态，可勾选“包含历史回填”查阅。时间线只展示已取得并留存的公开记录。`;
  for (const [term, definition] of [['事件与项目', '一项状态变化、一次新增披露或一项资料修订各计一条事件。同项目同批次同日的事件合并显示，统计与CSV仍按事件计数。'], ['日期', '持续跟踪动态按首次发现日期筛选，官方日期另列；历史回填按官方日期筛选。'], ['历史覆盖', coverage], ['关联与批次', '只合并已确认的关联关系；首发、扩募及具体申报批次分别保留。'], ['异常与刷新', '采集失败、来源不完整或记录暂时消失不生成终止事件。来源核查未完成时，不据此判断当天无变化。'], ['筛选与导出', '上方今日更新按北京时间当天首次发现的事件展示，不含历史回填。卡片只筛选今日列表；下方全部动态库的筛选、分页和明细展开与上方独立。CSV只导出下方动态库的当前筛选结果。项目时间线展示该项目及已确认关联项目的全部已留存记录。']]) add(definitions, el('dt', '', term), el('dd', '', definition));
  const sourceList = el('div', 'updates-source-details');
  for (const source of updateSourceHealth(snapshot?.sources)) {
    const section = el('section');
    add(section, el('h3', '', source.label), el('p', '', `最近核查：${source.checked_at || '未取得'}；最新官方日期：${source.latest_official_date || '未披露'}；${source.issue || '核查完整'}`), externalLink('官方来源 ↗', source.source_url));
    sourceList.append(section);
  }
  add(sourceList, el('p', 'updates-timeline-note', `生成时间：${snapshot?.generated_at || '尚未读取'}。`));
  dialog.replaceChildren(heading, intro, definitions, sourceList); showDialog(dialog);
}

async function loadUpdates() {
  if (loading) return loading;
  loading = (async () => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 25000);
    try {
      let payload;
      if (typeof DecompressionStream === 'function') {
        try {
          const compressed = await fetch(COMPRESSED_DATA_URL, { cache: 'no-store', signal: controller.signal });
          if (!compressed.ok || !compressed.body) throw new Error('压缩动态暂不可用');
          payload = await new Response(compressed.body.pipeThrough(new DecompressionStream('gzip'))).json();
        } catch (cause) { if (controller.signal.aborted) throw cause; }
      }
      if (!payload) {
        const response = await fetch(DATA_URL, { cache: 'no-store', signal: controller.signal });
        if (!response.ok) throw new Error(`服务器返回${response.status}`);
        payload = await response.json();
      }
      const next = validateUpdatesSnapshot(payload);
      snapshot = next; error = ''; fillOptions();
    } catch (cause) { error = `项目动态读取失败${snapshot ? '，已保留上次成功记录' : ''}。${cause.message || '请稍后刷新重试。'}`; }
    finally { clearTimeout(timer); loading = null; render(); if ($('updates-source-dialog').open) openUpdatesSources(); if (lastEntity && $('updates-detail-dialog').open) openTimeline(lastEntity); }
  })();
  render(); return loading;
}
function exportCSV() {
  const rows = updatesCSVTable(currentEvents(), snapshot || {});
  const blob = new Blob(['\ufeff', rows.map(row => row.map(updatesCSVCell).join(',')).join('\r\n')], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob); const link = document.createElement('a');
  link.href = url; link.download = `REITs动态库_${snapshot?.as_of_date || today()}.csv`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function eventById(id) { return snapshot?.events.find(event => event.id === id); }
function synchronizeInputs() {
  for (const key of ['search', 'exchange', 'asset', 'business', 'type', 'start', 'end']) $(`updates-${key}`).value = state[key];
  $('updates-saved-only').checked = state.savedOnly; $('updates-include-history').checked = state.includeHistory;
}
async function onAction(event) {
  const action = event.target.closest('[data-updates-action]'); if (!action) return;
  const value = action.dataset.value;
  switch (action.dataset.updatesAction) {
    case 'today-population': dailyPopulation = dailyPopulation === value ? '' : value; renderToday(); break;
    case 'population': state.population = value; state.page = 1; renderLibrary(); break;
    case 'range': state.range = value; if (value === 'custom' && !state.start) { const period = updatePeriod({ range: '30' }); state.start = period.start; state.end = period.end; synchronizeInputs(); } state.page = 1; renderLibrary(); break;
    case 'reload': loadUpdates(); break;
    case 'export': exportCSV(); break;
    case 'sources': openUpdatesSources(); break;
    case 'timeline': openTimeline(eventById(value)); break;
    case 'project': {
      const target = eventById(value);
      if (target) {
        action.closest('dialog')?.close(); action.disabled = true;
        try {
          const opened = await callbacks.onOpenProject?.(target);
          if (opened === false) {
            error = '当前项目库未保留这笔历史记录，可通过时间线中的官方披露查看。';
            render(); openTimeline(target);
          }
        } catch { error = '项目资料暂未读取成功，请稍后重试或查看官方披露。'; render(); }
        finally { action.disabled = false; }
      }
      break;
    }
    case 'close': action.closest('dialog')?.close(); break;
    case 'show-history': state.includeHistory = true; state.range = 'all'; state.page = 1; synchronizeInputs(); renderLibrary(); break;
    case 'reset': state = { ...DEFAULT_FILTERS }; synchronizeInputs(); renderLibrary(); break;
    case 'prev': state.page--; renderLibrary(); break;
    case 'next': state.page++; renderLibrary(); break;
  }
}
export function setUpdatesModuleActive(value) {
  active = Boolean(value);
  if (!initialized) return;
  if (!active) { for (const id of ['updates-detail-dialog', 'updates-source-dialog']) { const dialog = $(id); if (dialog?.open) dialog.close(); } return; }
  document.querySelector('.skip-link')?.setAttribute('href', '#updates-today');
  render(); if (!snapshot && !loading) loadUpdates();
}
export function initializeProjectUpdates(options = {}) {
  callbacks = { ...callbacks, ...options };
  if (initialized) return;
  buildUI(); initialized = true;
  $('updates-panel').addEventListener('click', onAction);
  for (const key of ['search', 'exchange', 'asset', 'business', 'type', 'start', 'end']) $(`updates-${key}`).addEventListener(key === 'search' ? 'input' : 'change', event => { state[key] = event.target.value; state.page = 1; renderLibrary(); });
  for (const [id, key] of [['updates-saved-only', 'savedOnly'], ['updates-include-history', 'includeHistory']]) $(id).addEventListener('change', event => { state[key] = event.target.checked; state.page = 1; renderLibrary(); });
  for (const id of ['updates-detail-dialog', 'updates-source-dialog']) $(id).addEventListener('click', event => { if (event.target !== event.currentTarget) return; const rect = event.currentTarget.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) event.currentTarget.close(); });
  window.addEventListener('storage', () => { if (active) renderLibrary(); });
  window.addEventListener('reits:favorites-changed', () => { if (active) renderLibrary(); });
  render(); loadUpdates();
}
