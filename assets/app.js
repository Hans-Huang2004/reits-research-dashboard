/* REITs dashboard for project lists collected directly from official SSE/SZSE APIs. */
'use strict';

const DATA_URL = new URL('../data/institutional.json', import.meta.url);
const STORAGE_PREFIX = `reits:${DATA_URL.pathname}:v1`;
const STORAGE = { favorites: `${STORAGE_PREFIX}:favorites`, overrides: `${STORAGE_PREFIX}:classification`, snapshot: `${STORAGE_PREFIX}:snapshot` };
const STATUS = { '0': '已申报', '1': '已受理', '2': '已反馈', '3': '已接收反馈意见', '4': '通过', '5': '未通过', '8': '终止', '9': '中止', '10': '已回复意见', '11': '提交注册', '12': '注册生效' };
const TAXONOMY = {
  '经营权类': ['市政生态', '交通设施', '能源'],
  '产权类': ['产业园', '租赁住房', '物流仓储', '消费', '数据中心', '办公', '综合业态', '文旅类'],
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
const state = { ex: '', kw: '', rights: '', asset: '', status: '', match: '', savedOnly: false, hideArchived: false, mode: 'count', sort: 'updated', direction: -1, page: 1, pageSize: 10 };
let snapshot = null;
let records = [];
let byId = new Map();
let cachedView = false;
let storageWarning = '';

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
  if (record.amt == null || record.amt === '') return null;
  const value = Number(record.amt);
  return Number.isFinite(value) ? value : null;
}
function classification(record) {
  const override = overrides[record.id];
  if (override && validClassification(override.ptype, override.psub)) return { psub: normalizedAsset(override.psub), ptype: override.ptype, source: 'local_manual', needsReview: override.psub === '待分类', note: String(override.pnote || override.note || '此前保存的本地分类，未填写依据。') };
  if (override && typeof override === 'object') return { psub: '待分类', ptype: '待分类', source: 'local_manual', needsReview: true, note: `此前的本地分类为“${String(override.ptype || '未填写')} → ${String(override.psub || '未填写')}”，与当前分类口径不符，已标为待复核。原值仍保存在浏览器，可修订或恢复数据文件分类。${override.pnote || override.note ? ` 原备注：${String(override.pnote || override.note)}` : ''}` };
  const psub = normalizedAsset(record.psub);
  const unknown = record.classification_source === 'unknown' || psub === '待分类' || !validClassification(record.ptype, psub);
  return { psub: unknown ? '待分类' : psub, ptype: unknown ? '待分类' : record.ptype, source: record.classification_source === 'manual' ? 'manual' : unknown ? 'unknown' : record.classification_source || 'keyword', needsReview: unknown || Boolean(record.pflag || record.uncertain), note: record.pnote || '数据文件未提供分类依据。' };
}
function classificationSource(category) { return { local_manual: '本地人工修订', manual: '仓库人工分类', keyword: '名称关键词初判', unknown: '待分类' }[category.source] || '数据文件分类'; }
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
      && (!state.savedOnly || favorites.has(record.id)) && (!state.hideArchived || !archived(record))
      && (!keyword || [record.name, record.writer || record.mgr, record.origin, category.ptype, category.psub].join(' ').toLowerCase().includes(keyword));
  }).sort((a, b) => {
    if (state.sort === 'amount') {
      if (amount(a) == null && amount(b) != null) return 1;
      if (amount(a) != null && amount(b) == null) return -1;
      return ((amount(a) ?? 0) - (amount(b) ?? 0)) * state.direction || a.id.localeCompare(b.id);
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
function render() {
  const data = currentRecords();
  const pages = Math.max(1, Math.ceil(data.length / state.pageSize));
  state.page = Math.min(pages, Math.max(1, state.page));
  const start = (state.page - 1) * state.pageSize;
  const totalAmount = data.reduce((sum, record) => sum + (amount(record) ?? 0), 0);
  const missingAmounts = data.filter(record => amount(record) == null).length;
  const approved = data.filter(record => String(record.status) === '4').length;
  const unknown = data.filter(record => classification(record).needsReview).length;
  const stats = [['当前匹配记录', format(data.length), '条', '按交易所与官方项目 ID 去重'], ['审核通过', format(approved), '条', '不代表已完成发行'], ['拟发行金额', format(totalAmount), '亿元', missingAmounts ? `${missingAmounts} 条未披露金额，未计入汇总` : '按当前筛选全部状态汇总'], ['分类待复核', format(unknown), '条', '名称不足或分类线索待核实']];
  $('stats').innerHTML = stats.map(([label, value, unit, foot]) => `<div class="stat"><div class="stat-label">${label}</div><div class="stat-value">${value}<small>${unit}</small></div><div class="stat-foot">${foot}</div></div>`).join('');
  renderBars('rights-chart', grouped(data, record => classification(record).ptype), { limit: Infinity, filter: 'rights' });
  renderBars('asset-chart', grouped(data, record => classification(record).psub), { limit: Infinity, filter: 'asset' });
  $('rights-chart-note').textContent = `当前筛选范围 · ${state.mode === 'count' ? '按记录数' : '按拟发行金额'} · 点击类别筛选`;
  $('asset-chart-note').textContent = `${state.rights || '全部权利类型'} · ${state.mode === 'count' ? '按记录数' : '按拟发行金额'} · 点击类别筛选`;
  renderBars('status-chart', grouped(data, record => String(record.status)), { isStatus: true, limit: Infinity });
  renderBars('manager-chart', grouped(data, record => record.writer || record.mgr));
  $('record-total').textContent = `${format(data.length)} 条`;
  $('scope-text').textContent = `统计、图表与表格共用当前筛选结果${data.some(archived) ? ' · 含历史保留记录' : ''}`;
  $('rows').innerHTML = data.slice(start, start + state.pageSize).map(record => {
    const category = classification(record);
    const url = sourceURL(record);
    const saved = favorites.has(record.id);
    const name = url ? `<a class="name-link" href="${escapeHTML(url)}" target="_blank" rel="noopener noreferrer">${escapeHTML(record.name)} ↗</a>` : `<span class="name-text">${escapeHTML(record.name)}</span>`;
    const categoryTags = category.psub === '待分类' ? '<span class="mini-tag review-tag">待分类</span>' : `<span class="mini-tag rights-tag${category.ptype === '经营权类' ? ' operating-tag' : ''}">${escapeHTML(category.ptype)}</span><span class="mini-tag">${escapeHTML(category.psub)}</span>`;
    return `<tr><td class="name-cell"><div class="name-line"><button class="star${saved ? ' saved' : ''}" data-save="${escapeHTML(record.id)}" aria-label="${saved ? '取消关注' : '关注'}${escapeHTML(record.name)}" aria-pressed="${saved}">${saved ? '★' : '☆'}</button>${name}</div><div class="row-sub">${categoryTags}${record.is_expansion ? '<span class="mini-tag">扩募</span>' : ''}${archived(record) ? '<span class="mini-tag archive-tag">历史保留</span>' : ''}${category.needsReview ? '<span class="review-label">待复核</span>' : ['manual', 'local_manual'].includes(category.source) ? `<span>${classificationSource(category)}</span>` : ''}<button class="detail-button" data-detail="${escapeHTML(record.id)}">详情与分类</button></div></td><td>${escapeHTML(record.ex)}</td><td class="numeric">${amount(record) == null ? '<span class="muted">未披露</span>' : format(amount(record))}</td><td><span class="status ${String(record.status) === '4' ? 'ok' : ['8', '5'].includes(String(record.status)) ? 'muted' : 'wait'}">${escapeHTML(statusLabel(record.status))}</span></td><td class="mgr">${escapeHTML(record.writer || record.mgr || '未披露')}</td><td class="date">${escapeHTML(record.up || '未披露')}</td><td>${url ? `<a class="source-link" href="${escapeHTML(url)}" target="_blank" rel="noopener noreferrer">${sourceLabel(record)} ↗</a>` : '<span class="muted">链接暂缺</span>'}</td></tr>`;
  }).join('') || `<tr><td colspan="7" class="empty">${snapshot ? '当前条件没有匹配记录' : '项目库尚未读取成功，请点击刷新数据'}</td></tr>`;
  $('page-count').textContent = data.length ? `显示 ${start + 1}–${Math.min(start + state.pageSize, data.length)} 条，共 ${data.length} 条` : '共 0 条';
  $('page-number').textContent = `${state.page} / ${pages}`;
  $('prev').disabled = state.page <= 1;
  $('next').disabled = state.page >= pages;
  $('export').disabled = !snapshot;
  document.querySelectorAll('[data-sort]').forEach(button => {
    const active = button.dataset.sort === state.sort;
    button.closest('th').setAttribute('aria-sort', active ? state.direction < 0 ? 'descending' : 'ascending' : 'none');
    button.textContent = `${button.dataset.sort === 'amount' ? '拟发行金额' : '更新日期'} ${active ? state.direction < 0 ? '↓' : '↑' : '↕'}`;
  });
}
function renderMetadata() {
  if (!snapshot) return;
  const warnings = [];
  if (cachedView) warnings.push('在线数据读取失败，正在展示此浏览器上次成功读取的快照。');
  const timestamp = Date.parse(snapshot.updated_at || `${snapshot.date}T08:00:00+08:00`);
  if (Number.isFinite(timestamp) && Date.now() - timestamp > 48 * 60 * 60 * 1000) warnings.push(`数据已超过 48 小时未更新，快照日期为 ${snapshot.date}。`);
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
  $('side-date').textContent = snapshot.date;
  const updatedAt = Number.isFinite(timestamp) ? new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(timestamp)) : snapshot.date;
  $('footer-date').textContent = `更新时间：${updatedAt}（北京时间）${cachedView ? ' · 浏览器缓存' : ''}`;
  const officialLinks = records.filter(record => sourceURL(record)).length;
  const retained = records.filter(archived).length;
  $('source-metadata').textContent = `本期 ${records.length} 条记录，${officialLinks} 条具备官方项目链接，${retained} 条历史保留记录。快照日期：${snapshot.date}。`;
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
}
function openDetail(id) {
  const record = byId.get(id);
  if (!record) return;
  const category = classification(record);
  const url = sourceURL(record);
  const linkStatus = { verified: '已核验', constructed: '依据官方项目 ID 构建，待逐条核验', unverified: '尚未核验' }[record.link_status] || '尚未核验';
  const fields = [['交易所', record.ex], ['当前状态', statusLabel(record.status)], ['拟发行金额', amount(record) == null ? '未披露' : `${format(amount(record))} 亿元`], ['权利类型', category.ptype], ['资产细类', category.psub], ['分类来源', classificationSource(category)], ['分类状态', category.needsReview ? '待复核' : '已有分类'], ['原始权益人', record.origin || '未披露'], ['计划管理人', record.writer || record.mgr || '未披露'], ['受理日期', record.acc || '未披露'], ['更新日期', record.up || '未披露'], ['名称命中口径', keywords(record).join('、') || '未提供'], ['记录状态', archived(record) ? '历史保留：本轮未再次检索到' : '本轮检索结果']];
  const options = (values, selected) => values.map(value => `<option value="${escapeHTML(value)}"${value === selected ? ' selected' : ''}>${escapeHTML(value)}</option>`).join('');
  $('detail-body').innerHTML = `<div class="detail-name">${escapeHTML(record.name)}</div><dl class="detail-grid">${fields.map(([label, value]) => `<div><dt>${label}</dt><dd>${escapeHTML(value)}</dd></div>`).join('')}</dl><div class="classification-evidence"><h3>分类依据</h3><p>${escapeHTML(category.note)}</p>${category.source === 'keyword' ? '<p class="muted">名称关键词提供初步线索；具体资产权利以项目披露文件为准。</p>' : ''}${category.source === 'local_manual' ? `<p class="muted">数据文件分类：${escapeHTML(normalizedAsset(record.psub))}；依据：${escapeHTML(record.pnote || '未提供')}。</p>` : ''}</div><form id="classification-form" class="classification-box"><h3>本地分类修订</h3><div class="classification-fields"><label class="field">权利类型<select name="rights">${options(RIGHTS, category.ptype)}</select></label><label class="field">资产细类<select name="asset">${options(TAXONOMY[category.ptype], category.psub)}</select></label></div><label class="field">分类依据／备注<textarea name="note" rows="3" maxlength="1000" required placeholder="写明披露文件、资产说明或判断依据">${category.source === 'local_manual' ? escapeHTML(category.note) : ''}</textarea></label><div class="classification-actions"><button class="button primary" type="submit">保存分类</button><button class="button" type="button" id="restore-classification"${category.source !== 'local_manual' ? ' disabled' : ''}>恢复数据文件分类</button></div><p class="classification-note">细类随权利类型联动。修订与依据仅保存在当前浏览器，导出结果会携带本地分类。</p><p id="classification-feedback" class="live" role="status"></p></form><div class="detail-source">官方项目 ID：${escapeHTML(record.source_id || record.id)}<p>来源链接：${escapeHTML(linkStatus)}${record.source_kind === 'project_data' ? '。深交所来源为该项目的官方原始数据。' : ''}</p>${url ? `<a href="${escapeHTML(url)}" target="_blank" rel="noopener noreferrer">打开${escapeHTML(record.ex)}${sourceLabel(record)} ↗</a>` : '<span class="muted">本条记录暂无可用官方详情链接。</span>'}</div>`;
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
    if (!validClassification(ptype, psub) || !pnote) { $('classification-feedback').textContent = '请选择对应的权利类型与资产细类，并填写分类依据。'; return; }
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
  const table = [['交易所', '项目名称', '计划管理人', '原始权益人', '资产细类', '权利类型', '拟发行金额(亿元)', '审核状态', '受理日期', '更新日期', '官方项目ID', 'source_url', 'match_keywords', '分类来源', '分类依据', '分类待复核', '是否扩募', 'archive_status', '链接核验状态'], ...currentRecords().map(record => {
    const category = classification(record);
    return [record.ex, record.name, record.writer || record.mgr, record.origin, category.psub, category.ptype, amount(record), statusLabel(record.status), record.acc, record.up, record.source_id || record.id, sourceURL(record), keywords(record).join(' | '), classificationSource(category), category.note, category.needsReview ? '是' : '否', record.is_expansion ? '是' : '否', record.archive_status || 'current', record.link_status || 'unverified'];
  })];
  const blob = new Blob(['\uFEFF' + table.map(row => row.map(csvCell).join(',')).join('\r\n')], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a'); link.href = url; link.download = `REITs_机构间项目_${snapshot.date}.csv`; document.body.appendChild(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

$('search').addEventListener('input', event => { state.kw = event.target.value; state.page = 1; render(); });
for (const id of ['rights', 'asset', 'status', 'match']) $(id).addEventListener('change', event => {
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
document.querySelectorAll('[data-sort]').forEach(button => button.addEventListener('click', () => { state.direction = state.sort === button.dataset.sort ? -state.direction : -1; state.sort = button.dataset.sort; state.page = 1; render(); }));
$('prev').addEventListener('click', () => { state.page--; render(); });
$('next').addEventListener('click', () => { state.page++; render(); });
$('page-size').addEventListener('change', event => { state.pageSize = Number(event.target.value); state.page = 1; render(); });
$('reset').addEventListener('click', () => {
  Object.assign(state, { ex: '', kw: '', rights: '', asset: '', status: '', match: '', savedOnly: false, hideArchived: false, sort: 'updated', direction: -1, page: 1 });
  for (const id of ['search', 'rights', 'asset', 'status', 'match']) $(id).value = '';
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
$('source-nav').addEventListener('click', () => $('source-dialog').showModal());
$('classification-help').addEventListener('click', () => $('source-dialog').showModal());
$('taxonomy-guide').innerHTML = RIGHTS.map(rights => `<div class="taxonomy-group"><strong>${escapeHTML(rights)}</strong><span>${escapeHTML(TAXONOMY[rights].join('、'))}</span></div>`).join('');
function showModule(name) {
  const isPublic = name === 'public'; $('institutional-panel').hidden = isPublic; $('public-panel').hidden = !isPublic;
  for (const [id, active] of [['institutional-nav', !isPublic], ['public-nav', isPublic]]) { $(id).classList.toggle('active', active); if (active) $(id).setAttribute('aria-current', 'page'); else $(id).removeAttribute('aria-current'); }
}
$('institutional-nav').addEventListener('click', () => showModule('institutional'));
$('public-nav').addEventListener('click', () => showModule('public'));
$('export').addEventListener('click', exportCSV);
$('reload').addEventListener('click', loadData);
render();
loadData();
