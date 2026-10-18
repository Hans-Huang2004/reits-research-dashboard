# 项目动态

“项目动态”跟踪公募REITs、机构间REITs及国家发改委推荐项目的公开进度。所有记录统一按官方日期归档。公募基金、首发申报及每次扩募分别保留身份和关联关系。

上方“今日更新”展示北京时间当天各次成功采集中新识别的业务增量，卡片只筛选上方类别。首次爬到较早官方日期的节点或文件，也进入当天增量，记录仍显示官方日期。同一项目的多项更新分别计数，重复采集不重复计数。下方“全部动态库”默认覆盖全部日期，独立保留搜索、分类、日期和关注筛选。两块的筛选、分页和明细展开互不影响，CSV只导出下方动态库的当前筛选结果。

## 事件口径

- **审核状态更新**：同一官方申报ID的审核状态或审核子状态发生变化，保存前后值。单独更新页面日期不生成状态事件。
- **新增披露文件**：新增官方问询、反馈、回复、批复、发行、成立、上市等流程文件，保留文件标题、URL和发布日期。每个文件独立保存事件，页面可将同一项目同日文件合并展示。基金页面重复展示的申报附件只记在对应申报批次。
- **进度节点**：明确披露的受理、注册、发售、成立、上市及扩募完成日期，或官方项目页直接提供的审核时间线节点。
- **国家发改委推荐**：推荐名单的公开项目及推荐日期；项目名称、推荐主体和推荐日期形成派生身份。名单关联关系修订不会生成业务推进事件。
- **资料修订**：官方项目名称、机构间申报金额，以及国家发改委名单的拟发售金额、申报主体或行业改变，单列修订并保留前后值及亿元单位。研究分类和收益预测补录不在此范围。

受理、反馈、注册、成立、上市和推荐等节点使用对应官方业务日期；披露文件使用官方发布日期。日期未披露的记录留空，页面显示“日期未披露”，不得以采集日或人工审核日代替。成立公告发布日期使用“成立公告日期”，独立于明确披露的成立日期。未来的计划发行或上市日期，在日期尚未到达时不记为完成节点。

首份完整快照建立已知事实集合，不计入当天增量。后续完整快照与已知事实比较，首次出现的业务节点、文件、项目和官方资料变化均可形成增量，与其官方日期早晚无关。已有记录重放或迁移保留原采集时间，不计为迁移当天的新增。

同URL文件后续补齐或修订官方日期时，更新该文件的唯一归档记录，只调整其自身日期；修订进入本次采集增量，最早采集时间保存在后台first_detected_at。修订前的文件信息、事件和输入版本保留在audit.document_revisions。新项目没有形成明确业务事件时，即使已披露非流程类说明书，也保留“首次发现项目”，官方日期为空。

保留明确日期、官方时间线和文件，不按当前状态倒推过去的状态链。公募基金代码或申报关联完善后合并身份，不生成“新基金”动态。缺失记录、附件暂时消失及采集失败不会被解释为项目终止；已经披露的证据继续保留。

资产分类、研究字段、人工审核时间、匹配关系及派生阶段修改不生成业务事件。关联资料修订只保留在审核底稿，记录前后值、人工审核时间、采集时间和输入版本。金额统计仍由原项目库负责，三类项目不合并金额。

## 数据链路

1. 原交易所和国家发改委采集器保存官方请求、分页、Raw及来源清单。
2. 原项目库校验器审核三类完整快照。
3. 动态生成器按时间比较已审核快照，将精确字节副本、SHA256和原始路径保存在不可变输入登记表。
4. 动态生成器计算事件、前后值、官方文件、实体关联及来源健康状态，完成事件ID唯一性、日期、来源、前后值和当前输入勾稽。
5. 审核通过后生成页面JSON和来源清单。

每日联合采集底稿与历史快照均作为候选输入。当前三库必须通过现有严格校验；不符合现行校验器的历史版本被列为拒绝输入，不影响其他合格历史的使用。保留的旧NDRC关联允许引用它当时审核的公募快照，并在来源元数据中标记其是否仍为当前公募版本。

已有输入文件在生成器中保持只读。输入副本按内容哈希保存，已存在副本必须与原哈希一致。重复执行不会重复生成事件，输入、事件及来源健康状态均未改变时，输出字节和生成时间保持不变。重建通过输入登记表重放，保留历史成功版本。

## 产物

| 层级 | 路径 |
|---|---|
| 原采集来源清单 | data/source_manifest/daily_refresh/、data/source_manifest/public/、data/source_manifest/ndrc/ |
| 原采集Raw | data/raw/daily_refresh/、data/raw/ndrc/及既有raw/目录 |
| 精确审核输入 | workpapers/project_updates/inputs/{population}/{sha256}.json |
| 输入登记表 | workpapers/project_updates/input_index.json |
| 事件计算及检查 | scripts/project_updates.py、workpapers/project_updates/runs/{input_version}/audit.json |
| 最终页面数据 | data/project_updates.json |
| 最终来源清单 | data/source_manifest/project_updates/{input_version}.json |

每个事件保存本次和上次输入版本的路径、留存路径、SHA256及采集时间。静态事实按官方证据去重，无关字段或快照序列化变化不产生新的事实ID；反复发生的状态转换和官方资料修订通过重放顺序中的稳定出现序号逐次保留。当前来源摘要绑定三库最终文件的SHA256，同时记录匹配的原采集manifest、Raw文件校验数量及留存情况。原采集Raw无法在本地定位时，审核底稿列出缺失文件和原归档位置，保留精确已审核输入作为替代控制。

## 调用

~~~sh
python3 scripts/project_updates.py --root /path/to/reits-research-dashboard
python3 scripts/project_updates.py --root /path/to/reits-research-dashboard --rebuild
python3 scripts/project_updates.py --root /path/to/reits-research-dashboard --check
~~~

--check只读检查现有JSON、三库当前SHA256、当前实体集合、事件ID及变化前后对应的留存快照，不写文件。

Python调用：

~~~python
from scripts.project_updates import build, build_payload, validate

payload = build(root)                 # 计算、审核并保存产物
result = validate(payload, root)      # 校验并勾稽当前输入
payload = build_payload(versions, current, generated_at)  # 纯计算，输入须先校验
~~~

build(root, generated_at=None, rebuild=False)返回最终JSON。versions是按population分组的版本列表，每项包含snapshot、path、retained_path、sha256、collected_at、sequence和is_current。重建会重放登记表和仍在仓库中的合格历史；不删除此前的成功输入。

## JSON合同

顶层包含schema_version、generated_at、as_of_date、sources、events、projects和audit。

sources按public、institutional、ndrc保存label、checked_at/collected_at、latest_official_date、coverage_start、complete、record_count、source_url/source_urls、snapshot_path、snapshot_sha256、status、error、last_successful_at及原采集来源记录。complete描述保留快照是否完整；status描述最近一次采集是否成功，两者分别判断。核查时间落后当日或最新采集失败时，应显示待刷新或异常状态。

事件包含：

- id、population、entity_id、entity_kind及项目筛选字段。
- business_type、fund_id、fund_code、related_entity_ids，保留首发、扩募和推荐的具体关联。
- event_type、title、changes、before、after、documents、source_url。
- official_date、event_date及is_incremental；detected_at仅供后台识别采集日增量。
- source_version、previous_source_version及batch_key；状态转换和资料修订另含occurrence。
- 文件事件另含后台first_detected_at；detected_at为首次采集或最近一次官方文件信息修订的采集时间。

event_date恒等于official_date，二者缺失时均为空字符串。列表、项目时间线、日期筛选及CSV按此官方日期口径处理。is_incremental为布尔值，首份完整快照的既有事实为false，此后新识别的业务事实为true。每日更新仅以is_incremental=true且detected_at对应的北京时间自然日为当天的事件组成。

batch_key由population、entity_id和official_date组成，缺日期时使用undated，前端可将同一项目同一官方日期的多项变化合并展开。discovery_type和is_baseline作为兼容字段保留，不用于页面分类、显示或筛选。detected_at始终保留实际来源采集时间，重放不会改为脚本运行时间。

projects保存当前实体元数据及已核实的直接关联。时间线应先定位具体申报或基金，再按对应业务类型筛选关联事件，避免把同一基金的不同扩募批次误作同一笔申报。

audit记录输入起点、输入数量、事件数量、增量事件数量、缺官方日期数量、缺失实体、元数据修订、文件归档修订、拒绝输入、Raw校验和详细审核底稿路径。
