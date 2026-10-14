# 数据模型与扩展

`data/institutional.json` 顶层含 `schema_version`、`date`、`updated_at`（上海时区）、`source_status`、`coverage`、`changes`、`quality`、`items`。

官方项目身份用 `id=SSE_{BOND_NUM}` 或 `SZSE_{xmbh}`；`source_id` 保留源站 ID，`num` 只是当前显示编号。两所相同名称也不会跨来源合并。

每条记录保留名称、原始权益人、计划管理人、承销商简称、拟发行金额、审核状态、受理／更新日期、分类及解释、命中关键词、抓取查询关键词、官方详情网页和链接核验状态。

列表原始行数、去重后的唯一项目数分别记录。重复记录保留较新状态并合并关键词来源。分类人工覆盖按稳定 ID 继承；未知类别不猜测。

## 两级资产分类

`ptype` 为研究大类，`psub` 为资产细类。经营权类包含市政生态、交通设施、能源；产权类包含产业园、租赁住房、物流仓储、消费、数据中心、办公、综合业态、文旅类、医疗健康；未知类别保留待分类。产权／经营权为历史研究分组，不自动代表核实法律权利，尤其不能由能源、交通、水务行业名称推导权利性质。

`pnote` 保存分类依据，`pflag` 保存待核标记。浏览器本地人工覆盖单独展示来源和依据，覆盖项目统计、图表、表格及 CSV，不修改官方项目身份或来源链接。

| 字段 | 含义 |
| --- | --- |
| `classification_source` | verified：披露核实；inferred：项目线索推定；keyword：名称初判；manual：人工分类；unknown：尚未确认 |
| `classification_confidence` | confirmed／likely／unknown；confirmed 指实际用途分类有公开证据，不代表权属或全部入池清单法律核验 |
| `classification_evidence` | `[{title,url}]`，可补 source_level、published_at、pages。确认为 verified 必须有有效HTTP(S)证据链接 |
| `underlying_assets` | 字符串，披露底层物业、设施或混合用途说明；推定项明确保留待核说明 |
| `classification_reviewed_at` | 分类核查日期 |
| `classification_updated_at` | 快照分类最近修改时间，独立于交易所数据采集时间 `updated_at` |
| `quality.classification_counts` | 按来源计算分类记录数，合计等于当前快照记录数 |

仓库证据配置按完整官方项目ID绑定，优先于名称关键词。刷新时保留证据、资产描述与核查日期；新项目不会仅因原始权益人相同就继承另一个项目的证据。证据不足时可在未知项目保留检索说明与官方身份链接，仍标 unknown。两种以上独立明确用途可用综合业态，不能用综合业态替代未知。

前端采用一致的分类名称，并兼容旧本地标签：仓储物流→物流仓储，办公楼→办公。资产大类与细类筛选联动；分类不明确的记录不会自动填充综合业态。

`quality.link_validation` 表示通过官方详情 API 核对项目身份和已确认官方网页路由，不表示每次刷新都逐页执行浏览器渲染。代表性网页另做浏览器验收。

`changes.missing_ids` 记录上一快照出现、本次未返回的记录。旧记录仍可在历史快照查阅，不静默算入当前查询总数。

公募 REITs 后续另建基金代码层、行情日期层、分红事件层、公告文件层；不能把它的市值与机构间项目的拟发行金额相加。
