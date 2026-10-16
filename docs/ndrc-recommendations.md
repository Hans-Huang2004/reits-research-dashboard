# 发改委推荐项目

公募REITs页面的“发改委推荐”独立展示国家发展改革委向中国证监会推荐的基础设施REITs项目。推荐记录、交易所申报事件和基金分别计数，通过关系表关联。

## 来源与口径

- 来源：全国投资项目在线审批监管平台，基础设施REITs项目信息系统。
- 页面：<https://reitsgl.tzxm.gov.cn:8881/atom-ui/reits/#/reits/project-publicity/project-publicity-list>。
- 公开列表接口：`POST https://reitsgl.tzxm.gov.cn:8881/atom/api/v1/reits/getReitsPublicInfoList`。全部查询条件及分页参数随每次请求保存。
- 正式采集使用域名并执行默认HTTPS证书验证，不关闭全局TLS验证。
- 原始字段为项目名称、主申报地方／中央企业、所属行业、拟发售基金总额、国家发展改革委向中国证监会推荐日期。
- 主申报地方不替代资产所在地；拟发售基金总额不替代实际发行金额。
- 源接口没有项目ID，派生ID绑定精确项目名称、主申报地方／中央企业和推荐日期。行业或金额修订不改变该ID。身份字段改变或记录消失时停止替换，保留上次完整快照供复核。
- 官方未公布固定更新频率。新鲜度底稿保留最新公开推荐日期、核查时间和无法判断固定日程滞后的原因。

## 历史匹配

`config/ndrc_exchange_links.json`保存按推荐派生ID及交易所官方事件ID绑定的审阅结果。每项确认包括官方证据、可定位页码和资产／批次说明。名称及资产词只用于生成候选。

首发、扩募和单独新购入分别处理。新购入推荐不得关联基金首发申报。交易所商业不动产路径须另核对同一推荐与资产关系，不根据同名或集团归属自动确认。关系允许多对多，候选不计入已确认数。

推荐日期与交易所正式受理日独立保留。受理日期早于推荐日时列出日期异常说明，`days_to_acceptance`为空，不计作提前量。系统首次发现时间从首次成功采集起记录；首轮历史回填持久标为`discovery_type=baseline`，后续新增标为`new`。

## 处理与审核链路

1. `data/source_manifest/ndrc/`：来源、查询参数、时间及逐页SHA256。
2. `data/raw/ndrc/`：未经业务转换的原始响应及必要披露文件。
3. `workpapers/ndrc/`：规范化结果、具体资产证据、匹配审核、新鲜度及勾稽。
4. `data/ndrc_recommendations.json`：完整审核后生成的页面数据。
5. `outputs/ndrc/`：从已验证快照生成的CSV及交付清单。

校验包括分页总数、逐页行数、唯一身份、原始及规范化金额校验和、日期范围、哈希、关系引用、证据地址、首发／新购入边界和日期异常。所有页面统计、图表、列表和CSV共用当前筛选结果。

## 复现

```sh
python -m collectors.ndrc_recommendations
python scripts/validate_ndrc_data.py data/ndrc_recommendations.json --public-input data/public_reits.json
python scripts/export_ndrc_review.py
```

指定`--reuse-raw <目录>`可按请求记录及哈希重放完整采集；指定`--public-input`固定匹配采用的交易所版本。人工证据配置按稳定身份保留并记录版本哈希。

## 每日刷新与发布

“Refresh NDRC recommendations”独立刷新推荐来源，在北京时间07:45首次检查、08:10至11:40每半小时补查，并在交易所联合刷新完成后检查匹配输入版本。今日完整数据且匹配输入未变时跳过重复采集。来源或核验失败时保留上次完整快照，只更新`data/ndrc_refresh_status.json`供页面显示。

发布检查同时比较交易所联合批次和推荐批次，避免交易所数据已上线时漏发新推荐。来源正常、静态构建成功与真实定时运行分别验收。
