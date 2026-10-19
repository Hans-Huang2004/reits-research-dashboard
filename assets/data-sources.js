/* A single source guide for all dashboard views. */
const STATUS_URLS = {
  joint: new URL('../data/refresh_status.json', import.meta.url),
  ndrc: new URL('../data/ndrc_refresh_status.json', import.meta.url)
};
const POPULATIONS = { public: '公募REITs', institutional: '机构间REITs', ndrc: '国家发改委推荐' };
const SECTION_IDS = ['overview', 'dates', 'public', 'institutional', 'ndrc', 'fields', 'links'];
const beijingParts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
const $ = id => document.getElementById(id);
let initialized = false;
let active = false;
let loading = null;
let lastReadAt = 0;
let taxonomy = {};
const statuses = { joint: null, ndrc: null };
const errors = { joint: false, ndrc: false };

function calendarDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(value || ''))) return '';
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value ? value : '';
}
function instant(value) {
  if (value instanceof Date) return Number.isFinite(value.getTime()) ? value : null;
  if (typeof value !== 'string' || !calendarDate(value.slice(0, 10)) || !/T.*(?:Z|[+-]\d{2}:\d{2})$/i.test(value)) return null;
  const parsed = new Date(value);
  return Number.isFinite(parsed.getTime()) ? parsed : null;
}
function parts(value) {
  const date = instant(value);
  return date ? Object.fromEntries(beijingParts.formatToParts(date).map(part => [part.type, part.value])) : null;
}
export function sourceBeijingDate(value) {
  const plain = calendarDate(value);
  if (plain) return plain;
  const result = parts(value);
  return result ? `${result.year}-${result.month}-${result.day}` : '';
}
export function formatSourceTimestamp(value) {
  const result = parts(value);
  return result ? `${result.year}-${result.month}-${result.day} ${result.hour}:${result.minute}` : '未取得';
}
const countValue = value => Number.isSafeInteger(value) && value >= 0 ? value : null;
export const sourceStatusReloadDue = (previousRead, now = Date.now()) => !Number.isFinite(previousRead) || previousRead <= 0 || now < previousRead || now - previousRead >= 60000;

/** The status belongs to a completed publication batch, not every research field. */
export function sourceStatusSummary(status, { population = 'public', now = new Date(), readError = false } = {}) {
  const current = instant(now);
  const currentDay = sourceBeijingDate(current);
  const object = status && typeof status === 'object' && !Array.isArray(status) ? status : null;
  const validation = population === 'ndrc' ? object?.validation : object?.validation?.[population];
  const failed = Boolean(object && (object.attempt_ok === false || validation?.ok === false || ['failed', 'error', 'partial'].includes(object.status)));
  // A failed attempt's completed_at can describe the attempt, never a success.
  const successfulValue = object?.last_successful_at || (!failed && object?.status === 'complete' ? object.completed_at : null);
  const successful = instant(successfulValue);
  const validSuccess = successful && current && successful <= current ? successfulValue : '';
  const complete = Boolean(object?.status === 'complete' && object.attempt_ok !== false && validSuccess);
  const dataDate = complete ? calendarDate(object.date) || sourceBeijingDate(validSuccess) : sourceBeijingDate(validSuccess);
  const stale = Boolean(complete && currentDay && (dataDate < currentDay || sourceBeijingDate(validSuccess) < currentDay));
  let code = !object ? 'pending' : failed ? 'failed' : complete ? stale ? 'stale' : 'complete' : 'pending';
  if (complete && dataDate > currentDay) code = 'pending';
  if (readError) code = 'unavailable';
  const canCount = ['complete', 'stale'].includes(code) && validation && validation.ok !== false;
  const counts = canCount ? population === 'public' ? {
    issuedFunds: countValue(validation.issued_funds), filings: countValue(validation.filings)
  } : population === 'institutional' ? { records: countValue(validation.count) } : { records: countValue(validation.items) } : {};
  return {
    population, label: POPULATIONS[population] || '数据来源', code,
    statusLabel: code === 'pending' && validSuccess ? '本轮待完成' : ({ pending: '待读取', failed: '本轮未完成', stale: '待更新', complete: '已更新', unavailable: '读取失败' })[code],
    dataDate: dataDate || '未取得', lastSuccessfulAt: validSuccess || '',
    lastSuccessfulText: formatSourceTimestamp(validSuccess), counts,
    description: code === 'failed' ? '保留上次完整快照。' : code === 'stale' ? '当前展示此前成功发布的数据。' : code === 'unavailable' ? '暂未读取到最新发布状态。' : code === 'pending' ? validSuccess ? '本轮更新尚未完成，保留上次成功快照。' : '尚未取得可确认的成功更新记录。' : '名单与分页核验通过；研究字段按各自披露情况列示。'
  };
}

function el(tag, className, value) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (value != null) node.textContent = value;
  return node;
}
function add(parent, ...children) { parent.append(...children.filter(Boolean)); return parent; }
function paragraph(value) { return el('p', '', value); }
function section(key, title) {
  const node = el('section', 'source-guide-section');
  node.id = `sources-${key}`;
  node.tabIndex = -1;
  return add(node, el('h2', '', title));
}
function definitionList(rows) {
  const list = el('dl', 'source-guide-definitions');
  for (const [term, definition] of rows) add(list, el('dt', '', term), el('dd', '', definition));
  return list;
}
function link(title, url, className = '') {
  const node = el('a', className, `${title} ↗`);
  node.href = url;
  node.target = '_blank';
  node.rel = 'noopener noreferrer';
  return node;
}
function buildUI() {
  const panel = $('sources-panel');
  if (!panel) return;
  const heading = el('header', 'head');
  const title = add(el('div'), el('div', 'eyebrow', 'DATA & SOURCES'), el('h1', '', '数据口径与来源'));
  const reload = el('button', 'button', '刷新状态');
  reload.id = 'sources-reload'; reload.type = 'button';
  reload.addEventListener('click', () => void loadStatuses());
  add(heading, title, add(el('div', 'header-actions'), reload));

  const navigation = el('nav', 'source-guide-nav');
  navigation.setAttribute('aria-label', '数据口径目录');
  for (const [key, title] of [['overview', '本期数据'], ['dates', '日期与动态'], ['public', '公募REITs'], ['institutional', '机构间REITs'], ['ndrc', '发改委推荐'], ['fields', '字段与更新'], ['links', '官方来源']]) {
    const anchor = el('a', '', title); anchor.href = `#sources-${key}`;
    anchor.addEventListener('click', event => { event.preventDefault(); openDataSourcesSection(key); });
    navigation.append(anchor);
  }
  const overview = section('overview', '本期数据');
  const cards = el('div', 'source-guide-cards'); cards.id = 'sources-status-cards'; cards.setAttribute('aria-live', 'polite');
  add(overview, cards, paragraph('数据日期对应已发布快照；最后成功更新时间采用北京时间。完整采集表示名单和分页检查通过，各项研究字段的披露与核查日期在项目详情中查看。'));

  const dates = section('dates', '日期与动态');
  add(dates, definitionList([
    ['全部动态库', '受理、反馈、注册、成立、上市及推荐等节点按官方业务日期归档；披露文件采用官方发布日期。列表、时间线、日期筛选与CSV使用相同口径。未取得官方日期的记录显示“日期未披露”，不纳入具体日期范围。'],
    ['今日更新', '累计北京时间当天采集新识别的节点、文件和内容变化，包含官方日期较早或尚未披露日期的记录。同一事件重复采集不重复计数，记录整理和关联关系维护不计入业务增量。'],
    ['事件计数', '一项状态变化、一个新增文件或一项资料修订各计一条事件。同项目同批次同官方日期可合并展示，计数和CSV仍逐条保留。'],
    ['上下独立', '顶部卡片只筛选今日更新；下方动态库独立搜索、筛选和分页，CSV导出下方当前筛选结果。项目时间线包含已确认关联记录，并保留具体申报批次。']
  ]));

  const publicSection = section('public', '公募REITs');
  add(publicSection, definitionList([
    ['已发行基金', '每只基金一条记录，包含已上市基金和成立待上市基金。既有基金新增扩募申报，不改变其已上市阶段。'],
    ['申报审核', '按交易所申报ID统计首发和扩募，首发与各次扩募分别保留。单独新购入不计入申报数量；同次扩募并新购入按一条扩募申报计数。中止、终止等记录继续保留。'],
    ['金额与预测', '申报稿、反馈稿、询价稿拟发售金额、发售金额及外部贷款分别列示，金额单位为亿元。基金视图采用首发口径，扩募另列；预测收益保留预测期间与披露版本。'],
    ['基金与申报', '基金阶段与申报状态分别记录，审核通过或出现计划上市日期均不直接认定发行、成立或上市已完成。']
  ]));

  const institutional = section('institutional', '机构间REITs');
  add(institutional, definitionList([
    ['收录范围', '在沪深交易所公开项目中搜索“持有型不动产”和“机构间REIT”，读取全部分页，并按交易所与官方项目ID去重。统计单位为申报记录，首发与扩募可能涉及同一底层资产。'],
    ['申报与发行', '拟发行金额采用申报口径，汇总当前筛选中的全部审核状态；是否完成发行依据发行披露单独核实。未披露金额不计入金额汇总。'],
    ['资产分类', '底层资产按“研究大类→资产细类”组织，区分披露核实、项目线索判断与名称初判；证据不足时保留待分类。产权类、经营权类用于研究分类，具体权利依据项目披露。'],
    ['记录保留', '已有项目本轮未再次检索到时继续保留，并标记本轮检索状态；不据此改为终止。']
  ]));
  if (taxonomy && typeof taxonomy === 'object') {
    const rows = Object.entries(taxonomy).filter(([, values]) => Array.isArray(values)).map(([name, values]) => [name, values.map(String).join('、')]);
    if (rows.length) {
      const details = add(el('details', 'source-guide-taxonomy'), el('summary', '', '查看资产分类目录'), definitionList(rows));
      institutional.append(details);
    }
  }

  const ndrc = section('ndrc', '国家发改委推荐');
  add(ndrc, definitionList([
    ['推荐记录', '采用国家发展改革委向中国证监会推荐的基础设施REITs项目公开名单，每项推荐分别保留。推荐记录与基金、交易所申报分别统计。'],
    ['推荐日期与金额', '推荐日期采用官方向证监会推荐日期；拟发售基金总额采用推荐口径，单位亿元，与实际募集金额分开。主申报地方／中央企业为官方申报主体字段，与资产所在地分别识别。'],
    ['项目关联', '推荐与交易所申报、基金的对应关系可以为多对多，首发、扩募及新购入按具体批次核实。已确认匹配列出关联记录与依据；候选待核实单列；未匹配表示尚未关联到当前交易所记录。']
  ]));

  const fields = section('fields', '字段与更新');
  add(fields, definitionList([
    ['字段证据', '项目详情列示字段对应的官方文件、文件日期、页码及金额口径。资产类型分别保留官方分类和研究判断，原始权益人、基金管理人、计划管理人等角色分别列示。'],
    ['缺失值', '未披露表示来源未提供；暂无法取得表示已知资料尚未取得；待核实表示证据不足；待补充表示尚未完成字段补录；不适用表示该字段不适用于本记录。缺失金额不以0代替。'],
    ['自动更新', '按北京时间，交易所每日05:37起、推荐名单每日07:45起安排检查，未完成时上午继续重试；推荐关系随交易所版本更新重新匹配。08:00为目标完成时间，实际结果见本期数据状态。页面刷新重新读取已发布数据。'],
    ['异常处理', '采集失败时保留上次完整快照，显示最近成功更新时间与本轮状态。来源更新未完成时，当日更新数为0不能据此认定官网当天无变化。'],
    ['核查与采集', '自动采集更新名单、审核状态及新增文件；需要判断的资产、预测和其他研究字段保留各自核查日期，不随采集日期自动变更。'],
    ['筛选与本地设置', '各项目库的统计、图表、表格和CSV使用当前筛选结果。公募及机构间CSV保留全部研究字段和来源，推荐与动态按各自记录结构导出。关注标记及机构间本地分类修订保存在当前浏览器，不回写官方来源或共享数据。']
  ]));

  const links = section('links', '官方来源');
  const linkGroups = el('div', 'source-guide-link-grid');
  for (const [title, entries] of [
    ['公募REITs', [['上交所项目审核信息', 'https://www.sse.com.cn/reits/info/'], ['深交所项目动态', 'https://reits.szse.cn/projectdynamic/index.html']]],
    ['机构间REITs', [['上交所项目查询', 'https://bond.sse.com.cn/bridge2/information/index_search.shtml'], ['深交所项目进度信息', 'https://bond.szse.cn/disclosure/progressinfo/index.html']]],
    ['国家发改委推荐', [['基础设施REITs推荐项目公示', 'https://reitsgl.tzxm.gov.cn:8881/atom-ui/reits/#/reits/project-publicity/project-publicity-list']]]
  ]) {
    const group = add(el('section', 'source-guide-link-group'), el('h3', '', title));
    for (const [label, url] of entries) group.append(link(label, url));
    linkGroups.append(group);
  }
  add(links, linkGroups, paragraph('各条记录的官方项目页、公告和字段依据可在项目详情中打开。'));
  const downloads = add(el('details', 'source-guide-downloads'), el('summary', '', '查看本期数据文件'));
  const files = el('div', 'source-guide-download-links');
  for (const [title, filename] of [['项目动态', 'project_updates.json'], ['公募REITs', 'public_reits.json'], ['机构间REITs', 'institutional.json'], ['国家发改委推荐', 'ndrc_recommendations.json']]) files.append(link(title, new URL(`../data/${filename}`, import.meta.url).href));
  downloads.append(files); links.append(downloads);
  panel.replaceChildren(heading, navigation, overview, dates, publicSection, institutional, ndrc, fields, links);
}

function renderStatusCards() {
  const container = $('sources-status-cards');
  if (!container) return;
  const cards = [];
  for (const population of Object.keys(POPULATIONS)) {
    const key = population === 'ndrc' ? 'ndrc' : 'joint';
    const summary = sourceStatusSummary(statuses[key], { population, readError: errors[key] });
    const card = el('section', 'source-guide-card'); card.dataset.source = population;
    const badge = el('span', `source-guide-status ${summary.code}`, summary.statusLabel);
    add(card, add(el('div', 'source-guide-card-heading'), el('h3', '', summary.label), badge));
    const countTexts = population === 'public' ? [summary.counts.issuedFunds != null ? `${summary.counts.issuedFunds}只已发行基金` : '', summary.counts.filings != null ? `${summary.counts.filings}条申报` : ''].filter(Boolean) : summary.counts.records != null ? [`${summary.counts.records}条${population === 'ndrc' ? '推荐' : '申报'}记录`] : [];
    add(card, el('p', 'source-guide-count', countTexts.join(' · ') || '记录数待读取'), definitionList([['数据日期', summary.dataDate], ['最后成功更新', summary.lastSuccessfulText]]), el('p', 'source-guide-status-note', summary.description));
    cards.push(card);
  }
  container.replaceChildren(...cards);
  const button = $('sources-reload');
  if (button) { button.disabled = Boolean(loading); button.textContent = loading ? '正在读取…' : '刷新状态'; }
}
async function loadStatuses() {
  if (loading) return loading;
  loading = (async () => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15000);
    try {
      await Promise.all(Object.entries(STATUS_URLS).map(async ([key, url]) => {
        try {
          const response = await fetch(url, { cache: 'no-store', signal: controller.signal });
          if (!response.ok) throw new Error('Status unavailable');
          const data = await response.json();
          if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('Invalid status');
          statuses[key] = data; errors[key] = false;
        } catch { errors[key] = true; }
      }));
    } finally { clearTimeout(timer); }
  })();
  renderStatusCards();
  try { await loading; }
  finally { lastReadAt = Date.now(); loading = null; renderStatusCards(); }
}
export function initializeDataSources(options = {}) {
  if (initialized || !$('sources-panel')) return;
  taxonomy = options.taxonomy || {};
  initialized = true; buildUI(); renderStatusCards(); void loadStatuses();
}
export function openDataSourcesSection(sectionName = 'overview') {
  if (!initialized) initializeDataSources();
  const shortName = String(sectionName || 'overview').replace(/^sources-/, '');
  const node = $(`sources-${SECTION_IDS.includes(shortName) ? shortName : 'overview'}`);
  if (node && active) {
    const scrollTarget = shortName === 'overview' ? $('sources-panel') : node;
    scrollTarget.scrollIntoView({ block: 'start' });
    node.focus({ preventScroll: true });
    history.replaceState(null, '', `${location.pathname}${location.search}#${node.id}`);
  }
}
export function setDataSourcesActive(value, { section: sectionName } = {}) {
  if (!initialized) initializeDataSources();
  active = Boolean(value);
  const panel = $('sources-panel'); if (panel) panel.hidden = !active;
  if (active) {
    renderStatusCards();
    if (!loading && sourceStatusReloadDue(lastReadAt)) void loadStatuses();
    if (sectionName) openDataSourcesSection(sectionName);
  }
}
