"""Source-backed Shenzhen public REIT fund and submission collector.

The public REIT APIs use numeric prjid identities. The fund report uses uppercase
PAGENO (the superficially similar pageNo is silently ignored by the exchange).
Raw responses are byte-preserved and a manifest records every request and hash.
No registered submission is treated as an issued fund without a listing-report
row or an official contract-effective announcement tied to a security code.
"""
from __future__ import annotations

import hashlib
import html
import json
import math
import re
import threading
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from collectors.http_policy import PACER, backoff

BASE = "https://reits.szse.cn"
QUERY = BASE + "/api/reits/projectrends/query"
DETAIL = BASE + "/api/reits/projectrends/details"
REPORT = BASE + "/api/report/ShowReport/data"
ANNOUNCEMENTS = BASE + "/api/disc/announcement/annList"
PAGE_SIZE = 100
MAX_PAGES = 1000


class CollectionError(RuntimeError):
    """An official response or its completeness check failed."""


def clean(value):
    value = html.unescape(re.sub(r"<[^>]*>", "", str(value or ""))).strip()
    return "" if value in ("-", "--") else value


def date(value):
    value = clean(value)
    match = re.match(r"\d{4}-\d{2}-\d{2}", value)
    return match.group(0) if match else ""


def asset_type(value):
    """Map the disclosed asset-use category; keep novel uses unclassified."""
    value = clean(value)
    if value in ("垃圾处理及生物质发电", "垃圾焚烧发电"):
        return "市政生态"
    if value == "商业综合体":
        return "综合业态"
    categories = [
        ("数据中心", ("数据中心",)),
        ("租赁住房", ("租赁住房", "保障房", "人才安居")),
        ("物流仓储", ("仓储", "物流")),
        ("产业园", ("产业园", "园区")),
        ("交通设施", ("高速", "公路", "铁路", "机场", "港口码头")),
        ("能源", ("发电", "能源", "光伏", "风电", "水电", "燃煤", "燃气")),
        ("市政生态", ("水利", "水务", "污水", "垃圾", "环保", "生物质")),
        ("消费", ("消费", "零售", "农贸", "专业市场", "购物")),
        ("办公", ("办公", "写字楼")),
        ("文旅类", ("酒店", "旅游", "文旅")),
    ]
    hits = {label for label, words in categories if any(word in value for word in words)}
    return next(iter(hits)) if len(hits) == 1 else "综合业态" if len(hits) > 1 else "待分类"


def product_type(value):
    value = clean(value)
    if "商业不动产" in value:
        return "商业不动产REITs"
    if "基础设施" in value:
        return "基础设施REITs"
    return ""


def fund_name_from_title(title):
    segment = clean(title).rsplit("：", 1)[-1].rsplit(":", 1)[-1]
    if "关于" in segment:
        segment = segment.rsplit("关于", 1)[-1]
    segment = re.sub(r"^\d+\s*[-—、.]\s*", "", segment)
    match = re.search(r"(.+?封闭式(?:基础设施|商业不动产)证券投资基金)", segment)
    return match.group(1) if match else ""


def announcement_document(row):
    return {"title":clean(row.get("title")),
            "url":"https://disc.static.szse.cn/download" + str(row.get("attachPath") or ""),
            "date":date(row.get("publishTime")), "source_id":str(row.get("annId") or row.get("id") or "")}


def documents(detail):
    result, seen = [], set()
    for key, rows in detail.items():
        if not (key.endswith("Attachment") or key == "disclosureMaterials") or not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict) or not row.get("dfpth"):
                continue
            url = urllib.parse.urljoin("https://reportdocs.static.szse.cn", str(row["dfpth"]))
            identity = (str(row.get("dfid")), url)
            if identity in seen:
                continue
            seen.add(identity)
            result.append({"title":clean(row.get("dfnm") or row.get("dftitle") or row.get("matnm")),
                           "url":url, "date":date(row.get("ddt")), "source_id":str(row.get("dfid") or ""),
                           "official_document_type":row.get("dtyp")})
    return sorted(result, key=lambda r:(r["date"], r["source_id"]), reverse=True)


def normalize_event(row, detail):
    source_id = str(row.get("prjid") or "")
    if not re.fullmatch(r"[0-9]+", source_id) or str(detail.get("prjid")) != source_id:
        raise CollectionError("SZSE detail identity does not match its official list record")
    docs = documents(detail)
    business_code = str(row.get("biztypsb") or detail.get("biztypsb") or "")
    official_business = clean(row.get("biztypsbName") or detail.get("biztypsbName"))
    if business_code == "21":
        business = "首发"
    elif business_code == "23":
        business = "扩募" if any("扩募" in d["title"] for d in docs) else "新购入"
    else:
        raise CollectionError("Unknown SZSE public REIT business type: " + business_code)
    registered = [date(p.get("date")) for p in detail.get("prjprogs", [])
                  if str(p.get("value")) == "70" and date(p.get("date"))]
    native_asset = clean(detail.get("issueTargetName") or row.get("issueTargetName"))
    fund_code = clean(detail.get("cmpcode") or row.get("cmpcode"))
    if not re.fullmatch(r"18\d{4}", fund_code):
        fund_code = ""
    return {"id":"SZSE_" + source_id, "source_id":source_id,
            "name":clean(row.get("cmpnm")), "exchange":"深交所", "business_type":business,
            "official_business_type":official_business, "official_business_code":business_code,
            "fund_code":fund_code, "manager":clean(detail.get("acctfm") or row.get("acctfm")),
            "origin":clean(detail.get("primitiveInterestsor") or row.get("primitiveInterestsor")),
            "official_status":clean(row.get("prjst")), "official_status_code":row.get("prjstatus"),
            "accepted_date":date(row.get("acptdt")), "updated_date":date(row.get("updtdt")),
            "registered_date":max(registered, default=""),
            "source_url":BASE + "/projectdynamic/detail/index.html?id=" + source_id,
            "source_data_url":DETAIL + "?id=" + source_id,
            "asset_type":asset_type(native_asset), "official_asset_type":native_asset,
            "product_type":product_type(detail.get("bizcategorynm") or row.get("bizcategorynm")),
            "documents":docs, "underlying_assets":[],
            "asset_location":"",
            "manager_location":clean(detail.get("fundProvinceName")),
            "special_plan_name":clean(detail.get("specialPlanName")),
            "special_plan_manager":clean(detail.get("sprinst")),
            "timeline":[{"title":clean(p.get("caption")), "date":date(p.get("date")),
                         "official_status_code":p.get("value")}
                        for p in detail.get("prjprogs", []) if date(p.get("date"))]}


class SourceReader:
    def __init__(self, raw_dir):
        self.raw_dir = Path(raw_dir)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.manifest = []
        self.lock = threading.Lock()

    def request(self, key, url, params=None, body=None):
        params = params or {}
        target = url + ("?" + urllib.parse.urlencode(params) if params else "")
        payload = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        headers = {"User-Agent":"Mozilla/5.0 (compatible; REITsResearchDashboard/1.0)",
                   "Referer":BASE + "/", "Accept":"application/json,text/javascript,*/*"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(target, data=payload, headers=headers)
        error = None
        for attempt in range(3):
            try:
                PACER.wait(target)
                with urllib.request.urlopen(request, timeout=45) as response:
                    raw = response.read()
                    content_type = response.headers.get("Content-Type", "")
                packet = json.loads(raw.decode("utf-8-sig"))
                break
            except Exception as exc:
                error = exc
                if attempt < 2:
                    backoff(target, exc, attempt)
        else:
            raise CollectionError("SZSE request failed: " + target + " (" + str(error) + ")")
        filename = key + ".json"
        path = self.raw_dir / filename
        # Never silently replace an earlier response in the same Raw version.
        with self.lock:
            if path.exists() and path.read_bytes() != raw:
                raise CollectionError("Raw path already contains another response; use a new version directory: " + str(path))
            path.write_bytes(raw)
            self.manifest.append({"file":str(path), "source":"深圳证券交易所", "url":url,
                                  "request_url":target, "method":"POST" if body is not None else "GET",
                                  "query_parameters":params, "request_body":body,
                                  "extracted_at":datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
                                  "content_type":content_type, "sha256":hashlib.sha256(raw).hexdigest(),
                                  "bytes":len(raw)})
        return packet


def _integer(value, field, minimum=0):
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise CollectionError("Invalid SZSE pagination field: " + field)
    return value


def fetch_projects(reader, business=None):
    rows, signatures, total = [], set(), None
    index, pages = 0, 1
    while index < pages:
        if index >= MAX_PAGES:
            raise CollectionError("SZSE pagination exceeds protective limit")
        params = {"pageIndex":index, "pageSize":PAGE_SIZE, "bizType":2}
        if business is not None:
            params["biztypsb"] = business
        label = str(business) if business is not None else "all"
        packet = reader.request("projects_" + label + "_page" + str(index + 1), QUERY, params)
        if not isinstance(packet, dict) or not isinstance(packet.get("data"), list):
            raise CollectionError("SZSE public project schema changed")
        count = _integer(packet.get("totalSize"), "totalSize")
        size = _integer(packet.get("pageSize"), "pageSize", 1)
        page_count = _integer(packet.get("totalPage"), "totalPage")
        if page_count != math.ceil(count / size):
            raise CollectionError("SZSE public project page count is inconsistent")
        if _integer(packet.get("pageIndex"), "pageIndex") != index:
            raise CollectionError("SZSE project API returned a different page than requested")
        if total is not None and count != total:
            raise CollectionError("SZSE project list changed during pagination")
        total, pages = count, max(1, page_count)
        data = packet["data"]
        signature = hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if data and signature in signatures:
            raise CollectionError("SZSE repeated a public project list page")
        signatures.add(signature)
        if len(data) != min(size, max(0, count - index * size)):
            raise CollectionError("SZSE public project page has an unexpected record count")
        rows.extend(data)
        index += 1
    ids = [str(row.get("prjid")) for row in rows]
    if len(rows) != total or len(ids) != len(set(ids)):
        raise CollectionError("SZSE public project record count or identity is inconsistent")
    return rows, {"business_code":business, "advertised_total":total, "raw_count":len(rows), "pages":index}


def fetch_fund_report(reader):
    rows, total, pages, page, report_date = [], None, 1, 1, ""
    while page <= pages:
        if page > MAX_PAGES:
            raise CollectionError("SZSE report pagination exceeds protective limit")
        packet = reader.request("funds_page" + str(page), REPORT,
                                {"SHOWTYPE":"JSON", "CATALOGID":"reits_fund_list", "TABKEY":"tab1", "PAGENO":page})
        if not isinstance(packet, list) or len(packet) != 1 or not isinstance(packet[0].get("data"), list):
            raise CollectionError("SZSE public fund report schema changed")
        tab = packet[0]
        if tab.get("error"):
            raise CollectionError("SZSE public fund report returned an error")
        meta = tab.get("metadata") or {}
        count = _integer(meta.get("recordcount"), "recordcount")
        size = _integer(meta.get("pagesize"), "pagesize", 1)
        page_count = _integer(meta.get("pagecount"), "pagecount")
        if _integer(meta.get("pageno"), "pageno", 1) != page or page_count != math.ceil(count / size):
            raise CollectionError("SZSE fund report pagination metadata is inconsistent")
        if total is not None and count != total:
            raise CollectionError("SZSE fund report changed during pagination")
        if len(tab["data"]) != min(size, max(0, count - (page - 1) * size)):
            raise CollectionError("SZSE fund report page has an unexpected record count")
        total, pages = count, max(1, page_count)
        current_date = date(meta.get("subname"))
        if report_date and current_date != report_date:
            raise CollectionError("SZSE fund report date changed during pagination")
        report_date = current_date
        rows.extend(tab["data"])
        page += 1
    ids = [clean(row.get("sys_key")) for row in rows]
    if len(rows) != total or len(ids) != len(set(ids)) or any(not re.fullmatch(r"18\d{4}", code) for code in ids):
        raise CollectionError("SZSE fund report record count or code uniqueness failed")
    return rows, {"advertised_total":total, "raw_count":len(rows), "pages":page - 1, "report_date":report_date}


def fetch_announcements(reader, keyword, label, stock=None):
    rows, total, page = [], None, 1
    while True:
        if page > MAX_PAGES:
            raise CollectionError("SZSE announcement pagination exceeds protective limit")
        body = {"channelCode":["reits-xxpl"], "searchKey":[keyword], "pageSize":50, "pageNum":page}
        if stock:
            body["stock"] = [stock]
        packet = reader.request("ann_" + label + "_page" + str(page), ANNOUNCEMENTS, body=body)
        if not isinstance(packet, dict) or not isinstance(packet.get("data"), list):
            raise CollectionError("SZSE announcement schema changed")
        count = _integer(packet.get("announceCount"), "announceCount")
        if total is not None and count != total:
            raise CollectionError("SZSE announcement list changed during pagination")
        total = count
        data = packet["data"]
        if len(data) != min(50, max(0, count - (page - 1) * 50)):
            raise CollectionError("SZSE announcement page has an unexpected record count")
        rows.extend(data)
        if len(rows) >= count:
            break
        page += 1
    ids = [row.get("id") for row in rows]
    if len(rows) != total or len(ids) != len(set(ids)) or any(not id_ for id_ in ids):
        raise CollectionError("SZSE announcement count or identity uniqueness failed")
    return rows, {"keyword":keyword, "stock":stock, "advertised_total":total, "raw_count":len(rows), "pages":page}


def _unique_documents(rows):
    return list({row["url"]:row for row in rows}.values())


def match_first_offering_announcements(events, announcements):
    """Bind disclosed codes through one exact first-issuance project name.

    A sale notice supplies identity and publication metadata only. Expansion
    notices and ambiguous names never create or establish a first-offering fund.
    """
    first_by_name = {}
    for event in events:
        if event["business_type"] == "首发":
            first_by_name.setdefault(event["name"], []).append(event)
    matched, skipped, event_codes = {}, [], {}
    for announcement in announcements:
        title = clean(announcement.get("title"))
        if "基金份额发售公告" not in title or any(word in title for word in ("扩募", "新购入")):
            skipped.append({"source_id":str(announcement.get("id") or ""), "reason":"not_first_offering_notice"})
            continue
        name = fund_name_from_title(title)
        matches = first_by_name.get(name, [])
        codes = {str(code) for code in announcement.get("secCode", []) if re.fullmatch(r"18\d{4}", str(code))}
        if len(matches) != 1 or len(codes) != 1:
            skipped.append({"source_id":str(announcement.get("id") or ""), "name":name,
                            "reason":"no_unique_exact_first_issuance_identity", "project_matches":len(matches),
                            "valid_codes":sorted(codes)})
            continue
        first, code = matches[0], next(iter(codes))
        document = announcement_document(announcement)
        if not document["date"] or not announcement.get("attachPath"):
            raise CollectionError("Official sale notice is missing publication date or document URL: " + code)
        previous = first.get("fund_code") or event_codes.get(first["id"])
        if previous and previous != code:
            raise CollectionError("Official sale code conflicts with SZSE first-issuance identity: " + first["id"])
        event_codes[first["id"]] = code
        matched.setdefault(code, []).append(announcement)
    return matched, {"matched_announcement_count":sum(len(rows) for rows in matched.values()),
                     "matched_fund_codes":sorted(matched), "skipped_announcements":skipped,
                     "identity_rule":"唯一首发项目全名精确匹配；发售公告不证明合同生效"}


def collect(raw_dir):
    reader = SourceReader(raw_dir)
    listing_rows, listing_check = fetch_fund_report(reader)
    all_rows, all_check = fetch_projects(reader)
    checks = []
    filtered_rows = []
    for business in (21, 23):
        part, check = fetch_projects(reader, business)
        filtered_rows.extend(part)
        checks.append(check)
    if {str(r["prjid"]) for r in all_rows} != {str(r["prjid"]) for r in filtered_rows}:
        raise CollectionError("SZSE unfiltered project list differs from the union of its public business categories")
    if sum(c["advertised_total"] for c in checks) != all_check["advertised_total"]:
        raise CollectionError("SZSE public project category counts do not reconcile")

    def get_detail(row):
        source_id = str(row["prjid"])
        packet = reader.request("detail_" + source_id, DETAIL, {"id":source_id})
        if not isinstance(packet, dict) or not isinstance(packet.get("data"), dict):
            raise CollectionError("SZSE public project detail schema changed: " + source_id)
        return normalize_event(row, packet["data"])

    with ThreadPoolExecutor(max_workers=5) as pool:
        events = list(pool.map(get_detail, all_rows))
    effective, effective_check = fetch_announcements(reader, "基金合同生效", "effective")
    listing_ann, announcement_check = fetch_announcements(reader, "上市交易公告书", "listing")
    sale_ann, sale_check = fetch_announcements(reader, "基金份额发售公告", "sales")
    offering_by_code, offering_links = match_first_offering_announcements(events, sale_ann)
    by_code = {clean(row["sys_key"]):row for row in listing_rows}
    effective_codes = {str(code) for row in effective for code in row.get("secCode", []) if re.fullmatch(r"18\d{4}", str(code))}
    issued_codes = set(by_code) | effective_codes
    offering_only_codes = set(offering_by_code) - issued_codes
    codes = issued_codes | set(offering_by_code)
    announcements_by_code = {code:[] for code in codes}
    for announcement in effective + listing_ann:
        for code in announcement.get("secCode", []):
            if code in announcements_by_code:
                announcements_by_code[code].append(announcement)
    for code, announcements in offering_by_code.items():
        announcements_by_code[code].extend(announcements)
    event_names = {e["name"] for e in events if e["business_type"] == "首发"}
    prospectus_checks = []
    for code in sorted(codes):
        aliases = {fund_name_from_title(r["title"]) for r in announcements_by_code[code]}
        # Resolve absent or changed long names through a security-code-bound
        # official prospectus query, never through fuzzy issuer matching.
        if not (aliases & event_names):
            extra, check = fetch_announcements(reader, "招募说明书", "prospectus_" + code, code)
            announcements_by_code[code].extend(extra)
            prospectus_checks.append(check)

    funds = []
    for code in sorted(codes):
        report = by_code.get(code, {})
        anns = announcements_by_code[code]
        aliases = sorted({fund_name_from_title(r["title"]) for r in anns if fund_name_from_title(r["title"])})
        matching_events = [e for e in events if e["business_type"] == "首发" and e["name"] in aliases]
        if len(matching_events) > 1:
            raise CollectionError("Several first-issuance identities match one SZSE fund: " + code)
        first = matching_events[0] if matching_events else {}
        name = first.get("name") or next(iter(aliases), "")
        short = clean(report.get("jjjcurl")) or next((clean(r.get("secName", [""])[0]) for r in anns if r.get("secName")), "")
        if not name:
            raise CollectionError("No official long name available for SZSE fund " + code)
        fund_docs = _unique_documents([announcement_document(a) for a in anns])
        offering_docs = _unique_documents([announcement_document(a) for a in offering_by_code.get(code, [])])
        fund = {"id":"SZSE_FUND_" + code, "code":code, "name":name, "short_name":short,
                "exchange":"深交所", "manager":clean(report.get("glrmc")) or first.get("manager", ""),
                "origin":first.get("origin", ""), "product_type":first.get("product_type") or product_type(name),
                "asset_type":first.get("asset_type", "待分类"), "official_asset_type":first.get("official_asset_type", ""),
                "listing_date":date(report.get("ssrq")), "established_date":"", "initial_raise_cny_100m":None,
                "source_url":BASE + "/disclosure/index.html?stock=" + code,
                "status":"已上市" if report else "已成立待上市" if code in effective_codes else "发售准备", "aliases":aliases,
                "documents":fund_docs, "asset_location":"",
                "offering_announcements":offering_docs,
                "manager_location":first.get("manager_location", ""),
                "underlying_assets":[], "issuance_evidence_url":next((announcement_document(a)["url"] for a in anns if "基金合同生效" in a["title"]), ""),
                "establishment_announcement_date":next((date(a.get("publishTime")) for a in anns if "基金合同生效" in a["title"]), "")}
        funds.append(fund)
        for event in events:
            if event["name"] in aliases and (code in issued_codes or event["business_type"] == "首发"):
                event["fund_code"] = code
                event["fund_link_evidence"] = [{"title":a["title"], "url":announcement_document(a)["url"],
                                               "date":date(a["publishTime"])}
                                              for a in anns if fund_name_from_title(a["title"]) == event["name"]][:1]
    # Completed historical expansions need actual post-registration evidence.
    # An announcement publication date is not the expansion-share listing date.
    for event in events:
        if event["business_type"] not in ("扩募", "新购入") or not event.get("fund_code"):
            continue
        completion = [a for a in announcements_by_code.get(event["fund_code"], [])
                      if "扩募" in a["title"] and "上市交易公告书" in a["title"]
                      and date(a.get("publishTime")) >= event["accepted_date"]]
        if completion:
            completion.sort(key=lambda a:date(a.get("publishTime")))
            doc = announcement_document(completion[0])
            event["completed"] = True
            event["completion_announcement_date"] = doc["date"]
            event["completion_evidence"] = [doc]
            event["documents"] = _unique_documents(event["documents"] + [doc])
    pending = [f["code"] for f in funds if not f["listing_date"] and f["code"] in issued_codes]
    latest = max((e["updated_date"] for e in events), default="")
    collected_at = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
    source_status = {"exchange":"深交所", "status":"complete", "collected_at":collected_at,
                     "latest_project_update":latest, "fund_report_date":listing_check["report_date"],
                     "listed_fund_count":len(listing_rows), "issued_fund_count":len(issued_codes),
                     "disclosed_fund_count":len(funds), "offering_only_fund_count":len(offering_only_codes),
                     "offering_only_codes":sorted(offering_only_codes), "offering_identity_checks":offering_links,
                     "issued_pending_listing_codes":pending, "event_count":len(events),
                     "detail_success_count":len(events), "detail_failure_count":0,
                     "pagination_checks":{"all_projects":all_check, "project_categories":checks,
                                          "listed_funds":listing_check, "effective_announcements":effective_check,
                                          "listing_announcements":announcement_check, "sale_announcements":sale_check,
                                          "identity_prospectuses":prospectus_checks},
                     "freshness":{"series":"深交所公募REITs基金名录", "latest_available_date":listing_check["report_date"],
                                  "expected_date":collected_at[:10], "lagging":listing_check["report_date"] != collected_at[:10]},
                     "limitations":["基金合同生效日及首发募集金额未从公告正文提取；公告发布日期另列，不替代生效日。",
                                    "完成扩募以正式扩募上市交易公告书为证；公告发布日期另列，不替代扩募份额上市日。",
                                    "仅有发售公告的产品保留公开代码、全名及公告来源，不据此认定成立或推定发售起止日。",
                                    "底层资产名称与数量未从招募说明书正文提取；保留全部官方申报附件入口。"]}
    reader.manifest.sort(key=lambda r:r["file"])
    (Path(raw_dir) / "manifest.json").write_text(json.dumps({"source":"深圳证券交易所", "generated_at":collected_at,
                                                            "requests":reader.manifest}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"funds":funds, "events":sorted(events, key=lambda r:(r["updated_date"], r["id"]), reverse=True),
            "source_status":source_status, "manifest":reader.manifest}


def correct_manager_region_mapping(snapshot, raw_dir, workpaper_dir):
    """Correct v1/v2 fundProvinceName mapping using the official field label.

    fundProvinceName denotes 基金管理人注册地. It provides no asset geography.
    Source responses and previous normalized versions remain unmodified.
    """
    import copy
    result = copy.deepcopy(snapshot)
    raw_dir, workpaper_dir = Path(raw_dir), Path(workpaper_dir)
    source_manifest = json.loads((raw_dir / "manifest_field_semantics_v1.json").read_text(encoding="utf-8"))
    evidence = source_manifest["requests"][0]
    if hashlib.sha256(Path(evidence["file"]).read_bytes()).hexdigest() != evidence["sha256"]:
        raise CollectionError("Official field-semantics evidence does not match its source hash")
    changes = []
    for event in result["events"]:
        packet = json.loads((raw_dir / ("detail_" + event["source_id"] + ".json")).read_text(encoding="utf-8"))
        actual = clean(packet["data"].get("fundProvinceName"))
        previous = event.get("asset_location", "")
        event["manager_location"] = actual
        event["asset_location"] = ""
        changes.append({"id":event["id"], "source_field":"fundProvinceName", "source_value":actual,
                        "old_asset_location":previous, "manager_location":actual, "asset_location":""})
    for fund in result["funds"]:
        matches = [event for event in result["events"] if event.get("fund_code") == fund["code"] and event["business_type"] == "首发"]
        if len(matches) != 1:
            raise CollectionError("Cannot bind manager region to a unique first-issuance source: " + fund["code"])
        previous = fund.get("asset_location", "")
        actual = matches[0]["manager_location"]
        fund["manager_location"] = actual
        fund["asset_location"] = ""
        changes.append({"id":fund["id"], "source_event_id":matches[0]["id"], "source_field":"fundProvinceName",
                        "source_value":actual, "old_asset_location":previous, "manager_location":actual,
                        "asset_location":""})
    result["normalization_version"] = "szse_public_v3_manager_region_correction"
    result["source_status"]["field_semantics_correction"] = {"source_field":"fundProvinceName",
        "official_label":"基金管理人注册地", "normalized_field":"manager_location",
        "asset_location":"", "affected_funds":len(result["funds"]), "affected_events":len(result["events"]),
        "source_url":evidence["url"], "evidence_sha256":evidence["sha256"]}
    result["manifest"].extend(source_manifest["requests"])
    record = {"version":"v3", "corrected_at":datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
              "reason":"fundProvinceName是基金管理人注册地，原映射为资产所在地有误。资产所在地不由本字段推断。",
              "source_field":"fundProvinceName", "official_label":"输入基金管理人注册地",
              "evidence":evidence, "parser":"collectors.public_szse.correct_manager_region_mapping", "changes":changes,
              "checks":{"all_asset_locations_empty":all(not row["asset_location"] for row in result["funds"] + result["events"]),
                        "manager_regions_bound_to_raw":True, "fund_count_unchanged":len(result["funds"]) == len(snapshot["funds"]),
                        "event_count_unchanged":len(result["events"]) == len(snapshot["events"])}}
    (workpaper_dir / "szse_field_semantics_correction_v3.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def parse_effective_announcement_text(text, expected_code):
    """Extract labelled contract fields; announcement date is never substituted."""
    from decimal import Decimal
    compact = re.sub(r"\s+", "", text)
    code = re.search(r"基金主代码(18\d{4})", compact)
    if not code or code.group(1) != expected_code:
        raise CollectionError("Contract-effective PDF security code does not match " + expected_code)
    name = re.search(r"基金名称(.+?)基金简称", compact)
    effective = re.search(r"基金合同生效日(\d{4})年(\d{1,2})月(\d{1,2})日", compact)
    net = re.search(r"募集期间净认购金额[（(]单位[：:]人民币元[）)]([\d,]+\.\d{2})", compact)
    shares = re.search(r"有效认购份额([\d,]+)", compact)
    if not name or not effective:
        raise CollectionError("Contract-effective PDF is missing required labelled identity/date fields")
    established = datetime(*map(int, effective.groups())).date().isoformat()
    result = {"code":expected_code, "name":name.group(1), "established_date":established,
              "initial_raise_cny_100m":float(Decimal(net.group(1).replace(",", "")) / Decimal(100000000)) if net else None,
              "initial_raise_basis":"募集期间净认购金额（不含认购利息）" if net else "",
              "initial_units":int(shares.group(1).replace(",", "")) if shares else None,
              "evidence_snippets":{"code":code.group(0), "effective_date":effective.group(0),
                                   "net_subscription":net.group(0) if net else ""}}
    return result


def enrich_pending_from_local_pdfs(snapshot, raw_dir, workpaper_dir):
    """Reproducible optional PDF enrichment of issued-but-unlisted funds only.

    The network collector remains standard-library-only. This independent audit
    step requires locally available pypdf and previously preserved source PDFs.
    It writes a new normalized version; it never edits the source snapshot/Raw.
    """
    import copy
    import pypdf
    raw_dir, workpaper_dir = Path(raw_dir), Path(workpaper_dir)
    result = copy.deepcopy(snapshot)
    audit = []
    supplement = json.loads((raw_dir / "manifest_effective_pdfs_v1.json").read_text(encoding="utf-8"))
    manifests = {row["code"]:row for row in supplement["requests"]}
    for fund in result["funds"]:
        if fund.get("listing_date") or fund["code"] not in manifests:
            continue
        code = fund["code"]
        manifest = manifests[code]
        pdf_path = raw_dir / ("effective_" + code + ".pdf")
        raw = pdf_path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != manifest["sha256"]:
            raise CollectionError("PDF no longer matches its recorded source hash: " + code)
        if manifest["url"] != fund.get("issuance_evidence_url"):
            raise CollectionError("Pending-fund PDF URL differs from the code-bound official announcement")
        pdf = pypdf.PdfReader(str(pdf_path))
        pages = [page.extract_text() or "" for page in pdf.pages]
        text = "\n\n".join("PAGE " + str(i + 1) + "\n" + t for i, t in enumerate(pages))
        text_path = workpaper_dir / ("szse_effective_" + code + "_text.txt")
        text_path.write_text(text, encoding="utf-8")
        parsed = parse_effective_announcement_text(text, code)
        if parsed["name"] != re.sub(r"\s+", "", fund["name"]):
            raise CollectionError("PDF full fund name differs from the code-bound official identity: " + code)
        evidence_pages = [i + 1 for i, t in enumerate(pages) if "基金合同生效日" in t]
        if not evidence_pages:
            raise CollectionError("No page contains the labelled fund contract-effective date")
        fund.update({key:parsed[key] for key in ("established_date", "initial_raise_cny_100m", "initial_raise_basis", "initial_units")})
        fund["establishment_evidence"] = {"title":fund["name"] + "基金合同生效公告", "url":manifest["url"],
                                           "pages":evidence_pages, "raw_file":str(pdf_path), "sha256":digest}
        audit.append({"code":code, "source_url":manifest["url"], "raw_file":str(pdf_path), "sha256":digest,
                      "text_file":str(text_path), "evidence_pages":evidence_pages, "parsed":parsed,
                      "checks":{"security_code_match":True, "full_name_match":True, "raw_hash_match":True,
                                "actual_date_label_present":True}})
    result["normalization_version"] = "szse_public_v2_pending_pdf_verification"
    result["source_status"]["pending_pdf_verification_count"] = len(audit)
    result["source_status"]["limitations"][0] = "已成立待上市的2只基金已核验实际合同生效日及净认购金额；其余已上市基金的生效日和首发募集金额尚未解析正文。"
    result["manifest"].extend(supplement["requests"])
    verification = {"version":"v1", "verified_at":datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
                    "parser":"collectors.public_szse.enrich_pending_from_local_pdfs", "pypdf_version":pypdf.__version__,
                    "source_snapshot":"szse_collected.json", "records":audit}
    (workpaper_dir / "szse_establishment_verification_v1.json").write_text(json.dumps(verification, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = collect(args.raw_dir)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(result["source_status"], ensure_ascii=False, indent=2))
