# REITs项目库

直接采集上交所、深交所公开披露的机构间 REITs／持有型不动产 ABS 申报与审核列表，提供项目查询、状态跟踪和官方披露入口。

网站使用 GitHub Pages 部署，源代码保存在私有仓库。页面也可以在本地运行。

网站入口：[沪深机构间REITs项目库](https://hans-huang2004.github.io/reits-research-dashboard/)。

## 当前版本

- 两所同时搜索 **持有型不动产** 与 **机构间REIT**，取并集并按官方项目 ID 去重。
- 2026-10-14 实际抓取：**131 条**，上交所 **109** 条、深交所 **22** 条。
- 每条记录保留官方项目 ID、命中关键词、原始项目详情网页；深交所还保留原始详情数据接口。
- 分页依据服务端元数据，支持接口实际每页大小与请求值不一致；拒绝重复页、错误响应和不完整快照。
- 搜索、交易所／资产大类／资产细类／状态／关键词筛选，统计、图表和表格统一联动；分类图表展示当前筛选中的全部类别。
- 支持关注项目、浏览器内手动分类覆盖、排序、分页和 CSV 导出。
- 采用红色主题，提供自动／白天／黑夜三种配色选择，记住当前浏览器的偏好。
- 对全部131条记录进行分类排查：120条有类别标签、11条待分类；其中27条类别有明确公开披露，6条依据项目线索推定，87条仍为名称关键词初判。详情展示底层资产、核验程度和证据链接。
- 公募REITs页签支持已发行基金与申报审核两个视图，扩募关联原基金。
- 公募19项、机构间13项研究字段支持核心／全部字段切换，详情及CSV保留完整字段与来源。字段定义见[字段范围](docs/project-fields.md)。

## 本地查看

需要 Python 3.9 及以上；抓取与测试仅使用标准库。

```bash
git clone https://github.com/Hans-Huang2004/reits-research-dashboard.git
cd reits-research-dashboard
python3 -m http.server 8765 --bind 127.0.0.1
```

浏览器打开 <http://127.0.0.1:8765/>。通过 HTTP 服务读取 JSON，不能直接双击 `index.html` 后期待浏览器允许 `file://` 数据请求。

## 更新数据

```bash
python3 -m collectors.institutional --verify-links
```

脚本抓取两所、两个关键词的全部列表页，补齐深交所详情，再核验每条记录的官方详情身份，成功后原子写入 `data/institutional.json` 和 `snapshots/YYYY-MM-DD.json`。任一关键词／列表页或必需链接核验失败会中止，保留旧完整快照。

需要保留原始证据时：

```bash
python3 -m collectors.institutional --verify-links --raw-dir raw/2026-10-14
```

仓库的`Refresh all REIT data`每天设定为北京时间08:30，同一批次采集公募与机构间项目清单、官方审核状态及可取得的成立上市信息。两类数据均校验通过后统一提交并发布；09:30、10:30仅在当天联合批次未完成时补跑。实际启动时间受GitHub调度影响。已核实研究字段与来源按项目ID保留，披露核查日期与清单采集日期分别记录。失败不发布部分结果，原始响应和核查记录保留在`data/raw/daily_refresh/`、`data/source_manifest/daily_refresh/`、`workpapers/daily_refresh/`，另保留30天运行证据。

## 数据口径

一条记录代表一个交易所申报／审核项目，不能等同于一只已发行证券或一个独立底层资产。

- `amt`：**拟发行金额，单位亿元**；不是已发行规模、存续规模或市值。
- `status=4`：审核通过；不等于完成发行。
- `is_expansion`：名称中包含扩募，作为独立申报记录保留。
- 名称关键词匹配是项目纳入口径，不代替对交易结构的法律或投资判断。
- 名称不能确认资产类别的项目保留“待分类”，不默认归为综合业态。
- `classification_source` 区分披露核实（verified）、线索推定（inferred）、名称初判（keyword）、人工分类（manual）和待分类（unknown）。分类证据确认的是资产用途，不自动确认法律权属。
- 资产大类采用产权类、经营权类，资产细类使用下表的统一名称。两级分类均为研究分类；自动结果根据名称初判，具体权利与资产范围需结合项目披露确认。
- 浏览器内关注和分类保存在当前浏览器。更换设备不会自动同步；当前可通过 CSV 导出筛选结果，尚未实现本地标记的 JSON 备份。
- 仓库长期人工分类放在 `config/classification_overrides.json`；格式为项目 ID 到分类字段的映射，刷新不会覆盖它。

示例：

```json
{
  "SSE_官方项目ID": {
    "ptype": "产权类",
    "psub": "办公",
    "pnote": "公告明确本项目入池写字楼",
    "classification_confidence": "confirmed",
    "classification_evidence": [{"title": "项目公告", "url": "https://example.com/project-disclosure"}],
    "underlying_assets": "写字楼及配套停车位"
  }
}
```

当前完整性是“两所两个关键词的全部列表页已获取”，不表示所有可能的机构间 REITs 都一定出现在这些名称查询中。

| 资产大类 | 资产细类 |
| --- | --- |
| 经营权类 | 市政生态、交通设施、能源 |
| 产权类 | 产业园、租赁住房、物流仓储、消费、数据中心、办公、综合业态、文旅类、医疗健康 |
| 待分类 | 待分类 |

项目库、分类图表、详情和 CSV 使用同一套分类结果。详情区分名称关键词初判、仓库人工分类与当前浏览器的本地人工分类，并展示分类依据。旧本地标记“仓储物流”“办公楼”分别显示为“物流仓储”“办公”；不影响项目关注标记。

名称规则识别滑雪场、商贸城、批发市场等明确线索。明确包含吾悦广场的项目不会仅因机构名称中的“安居”被判为住房；同时出现明确住房与商业资产线索时仍需复核。单纯的公司名称或“碳中和”等政策标签不足以确认底层资产，未确认项目不会默认归为综合业态。

分类核查依据见 [分类研究记录](docs/asset-classification.md)。首发、扩募分别按项目ID核查；不能把首期资产或同一主体的其他证券化项目套入新申报。多个明确独立用途组成资产池时可标综合业态，配套停车位不单独改变主类。产权类／经营权类沿用研究分组，能源、市政、交通的行业名称不代表已验证其法律权利类型。

补充仓库分类证据后，可直接应用到现有快照：

```bash
python3 scripts/classify_snapshot.py
```

该命令保留原始采集时间 `updated_at`，另写 `classification_updated_at`，重新计算分类质量统计和内容校验值。每日采集亦应用同一份分类配置，证据不会因刷新丢失；新项目按名称初判，信息不足时继续待分类。

## 项目结构

| 路径 | 用途 |
| --- | --- |
| `index.html`、`assets/` | 页面、样式与交互 |
| `collectors/institutional.py` | 官方 API 采集、规范化、去重、链接身份核验 |
| `data/institutional.json` | 页面读取的当前完整数据 |
| `snapshots/` | 按日期保留的完整快照 |
| `raw/` | 首次采集的原始响应证据 |
| `config/classification_overrides.json` | 仓库内人工分类覆盖 |
| `tests/` | 纯离线回归与真实响应小样本 |
| `scripts/validate_data.py` | 发布前的完整性、唯一性和原始链接检查 |
| `scripts/classify_snapshot.py` | 将仓库证据应用到已有快照，保留真实采集时间 |
| `scripts/build_static.py` | 生成静态站点 `dist/` |
| `docs/source-links.md` | 官方链接机制、采集口径与核验证据 |
| `docs/asset-classification.md` | 已检索分类、底层资产、证据与尚未确认项 |
| `.github/workflows/` | 检查、定时刷新及网页部署配置 |

## 验证

```bash
python3 -m unittest discover -s tests -v
node --check assets/app.js
python3 scripts/validate_data.py data/institutional.json
python3 scripts/build_static.py
```

Node 只用于 JavaScript 语法检查，查看页面和采集数据不需要安装 Node。

## 公募REITs与研究字段

公募部分使用独立采集器和`data/public_reits.json`，基金与首发、扩募申报分别建模。各版本拟发售金额、发售金额、外部贷款、收益预测与担保补足按具体业务事件记录；缺失值保留为空。机构间项目分别记录受理、通过、发行日期与发行状态。

字段配置为`config/project_field_scope.json`，字段新增或修订后可用`python3 scripts/apply_project_field_scope.py`应用到现有快照，保留原有项目值和数据采集时间。采集器刷新按稳定ID保留研究字段。字段映射及来源核对位置见[字段范围](docs/project-fields.md)。

## 网站部署

静态网页由 GitHub Pages 托管，部署内容包括页面、样式、交互脚本和完整数据快照。私有源代码仓库与网页访问范围分别管理；网站上的项目数据来自交易所公开披露。

发布工作流为 `Publish REITs project library to GitHub Pages`：主分支更新、手动运行或定时采集成功后触发，先验证完整数据，再构建并发布静态网页。仓库 Pages 的发布来源使用 **GitHub Actions**。

数据准确性及披露口径以交易所官网为准。代码使用 MIT 许可；公开数据及来源网站内容的权利归相应权利人。
