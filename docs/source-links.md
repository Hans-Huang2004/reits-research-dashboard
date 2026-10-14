# 官方项目链接与采集证据

核验日期：2026-10-14。本文记录链接的官方生成方式、项目采集口径和程序核验方法。网页的 HTTP 200 只说明页面外壳存在，不能单独证明项目对应正确；应同时核验项目详情接口返回的 ID 和名称。

## 上交所

使用列表响应中的 `BOND_NUM` 作为官方项目 ID，以 `AUDIT_NAME` 作为名称。不要使用分页行号 `NUM`、发行人 ID 或 `SEQ` 替代项目 ID。

官方前端 [search_common.js](https://bond.sse.com.cn/xhtml/bridge2/js/common/search_common.js) 的 `contentLink1(data)` 将项目名称链接生成为：

```text
/bridge2/information/index_detail.shtml?bound_id={BOND_NUM}
```

当前 `bridge2` 页面会重定向至 `bridge`，项目库采用最终路径：

```text
https://bond.sse.com.cn/bridge/information/index_detail.shtml?bound_id={BOND_NUM}
```

已核验示例：

- [国金资管-铜陵长江公铁大桥不动产资产支持专项计划（机构间REIT）](https://bond.sse.com.cn/bridge/information/index_detail.shtml?bound_id=213e64e05b2a4db8a98568e1740b5101)
- [国家电投-黄河公司水光互补清洁能源绿色持有型不动产资产支持专项计划](https://bond.sse.com.cn/bridge/information/index_detail.shtml?bound_id=0af8d41233494350aa7aea124071b93a)

官方 [search_pjinfo.js](https://bond.sse.com.cn/xhtml/bridge2/js/search/search_pjinfo.js) 的详情初始化读取 URL 参数 `bound_id`，随后将其作为 `audit_id` 请求 `ZQ_XMLB`。可用如下请求核验链接对应的项目：

```text
https://query.sse.com.cn/commonSoaQuery.do
  ?jsonCallBack=cb
  &isPagination=false
  &sqlId=ZQ_XMLB
  &audit_id={BOND_NUM}
  &bond_type=0,1,2,3,5,6,7
```

请求头应带浏览器 User-Agent 与上交所债券平台 Referer。返回内容是 JSONP。检查 `result` 恰好含一条记录，且 `BOND_NUM` 与目标 ID 一致，`AUDIT_NAME` 与列表名称一致。2026-10-14 的国家电投黄河、铜陵大桥和江苏国开新能源详情样本均通过上述身份核验，完整快照中的上交所 109 条记录也均完成详情接口身份核验。

列表查询：`https://query.sse.com.cn/sseQuery/commonSoaQuery.do`，参数 `sqlId=ZQ_XMLB`、`key={关键词}`、`isPagination=true`、`pageHelp.pageNo`、`pageHelp.pageSize`。按响应 `pageHelp.pageCount` 动态翻页，并保存 `pageHelp.total`。本日“持有型不动产”响应总数为 104，但 `BOND_NUM` 去重后为 103；其中“财通-正泰安能新能源基础设施碳中和绿色持有型不动产资产支持专项计划（乡村振兴）”的 ID `72429c4ccc1d4ad0978aaa8a5ca9fe39` 在行号 26、27 重复。因此完整性检查应检查收到的原始行数与分页元数据，同时单独记录重复 ID，不应强制唯一项目数量等于源站原始行数。

## 深交所

列表查询：

```text
https://bond.szse.cn/api/report/ShowReport/data
  ?SHOWTYPE=JSON
  &CATALOGID=xmjdxx
  &txtZqmc={关键词}
  &pageNo={页码}
```

响应 `data[0].metadata` 提供 `pagecount`、`recordcount`、`pagesize`、`pageno`；实际数据位于 `data[0].data`（这里的 `data` 指根 JSON 数组）。本日即使传入 `pageSize=100`，实际元数据的 `pagesize` 仍为 20，不能按请求的页面大小自行推算总页数。官方报表 [report_new.min.js](https://res.static.szse.cn/modules/report/js/report_new.min.js?version=1.2.221) 使用 `PAGENO` 和 `{tabkey}PAGESIZE`（例如 `tab1PAGESIZE`）传递分页，采集器应依照实际元数据分页。

债券名称字段 `zqmc` 是带 `<a>` 的 HTML。当前返回的 `href` 为 `javascript:void(0);`，真实详情参数在 `a-param`，例如：

```html
<a href='javascript:void(0);' a-back=1
   a-param='/ShowReport/data?SHOWTYPE=JSON&CATALOGID=xmjdxx_xq&TABKEY=tab1&xmbh=A008DEF35DB7497B80240D4B840C3F89&type=2'>
  中信建投-居然智家不动产资产支持专项计划（机构间REIT）
</a>
```

应通过 HTML 解析提取 `a-param`，再用 URL 查询参数解析获取 `xmbh`，支持大小写字母，避免依赖只接受大写十六进制的正则。保留官方 ID 与完整原始详情参数；可由该参数生成 `source_data_url`：

```text
https://bond.szse.cn/api/report/ShowReport/data
  ?SHOWTYPE=JSON
  &CATALOGID=xmjdxx_xq
  &TABKEY=tab1
  &xmbh={xmbh}
  &type=2
```

官方 `report_new.min.js` 的 `clickCheckDetail` 读取 `a-param` 并实例化 `DetailReport`；这个点击在页面内展示详情，并非导航到一个新的静态详情文件。

原始网页支持查询参数指定详情报表。官方 [concatJs.min.js](https://res.static.szse.cn/common/js/concatJs.min.js?version=1.2.221) 读取 `location.search`，将 `CATALOGID` 写入报表容器的 `data-s-catalog-id`，将 `TABKEY` 写入 `data-s-active-tabkey`，并将其他查询参数传入 `ShowReport/data`。因此采用下面的源站网页链接，并同时保留上述原始数据接口链接：

```text
https://bond.szse.cn/disclosure/progressinfo/index.html
  ?CATALOGID=xmjdxx_xq
  &TABKEY=tab1
  &xmbh={xmbh}
  &type=2
```

示例：[中信建投-居然智家](https://bond.szse.cn/disclosure/progressinfo/index.html?CATALOGID=xmjdxx_xq&TABKEY=tab1&xmbh=A008DEF35DB7497B80240D4B840C3F89&type=2)。该链接由官方前端代码的查询参数机制推导；详情 API 已返回该项目的完整基本信息。浏览器实际渲染验收应独立进行，不能用源码推导或 HTML 外壳响应替代。

`xmjdxx_xq`、`tab1` 返回 `zqmc`（无 HTML 的完整名称）、`fxr`（发行人）、`cxsqc`（管理人全称）、`nfxje`（亿元）、`xmzt`、`xmslrq`、`xmztgxrq`、`jysqrwjwh` 等。应核验非空详情、名称与列表一致以及元数据条件中的 `xmbh` 一致。2026-10-14 完整快照中的深交所 22 条记录均已采集详情并通过身份核验。

## 查询结果与覆盖

本日两所分别查询“持有型不动产”和“机构间REIT”，按交易所与官方项目 ID 合并：

| 交易所 | 持有型不动产唯一记录 | 机构间REIT唯一记录 | 两组重合 | 合并唯一记录 |
| --- | ---: | ---: | ---: | ---: |
| 上交所 | 103 | 6 | 0 | 109 |
| 深交所 | 17 | 5 | 0 | 22 |
| 合计 | 120 | 11 | 0 | 131 |

名称分类与项目纳入是两个独立步骤。两个搜索词的结果应取并集，保留每条记录的 `matched_keywords`，并按去空白、统一大小写的名称再次检查关键词。名称查询口径并非读完交易结构后的法律判断，也不等同于已发行项目清单。

名称包含“机构间REIT”的上交所项目包括铜陵长江公铁大桥、河北旅投崇礼滑雪场、至善伏安新能源、海盐潮能新能源、电建地产、江苏国开新能源；深交所项目包括 TCL 新能源、阳光新能源、开弦新能源、居然智家、依云四季酒店文旅。

## 本地证据

完整分页响应保存在 `raw/2026-10-14/`：

- `sse_holding_page1.json`、`sse_holding_page2.json`、`sse_institutional_page1.json`。
- `szse_holding_page1.json`、`szse_institutional_page1.json`。
- `sse_detail_{BOND_NUM}.json`：3 个上交所详情样本。
- `szse_detail_{xmbh}.json`：22 个深交所项目详情。

链接路由核验还读取了上文引用的官方前端脚本；仓库仅保存数据响应，脚本内容不随仓库分发。

接口为交易所网页当前使用的公开接口，参数、路径和字段可能调整。更新时需保留分页元数据、原始响应和失败记录，若任一所或任一关键词未抓取完整，应保留上次完整快照。
