"""Collect public REIT filings, issuance batches and listed funds from SSE.

Raw responses are immutable and have a request/hash manifest. Publication must
use the returned checked result; a missing page or detail fails collection.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import html
import json
import math
from pathlib import Path
import re
import threading
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo
from collectors.http_policy import PACER, backoff
from collectors.http_transport import urlopen

API = "https://query.sse.com.cn/"
REFERER = "https://www.sse.com.cn/reits/home/"
STATUS = {"0":"已申报", "1":"已受理", "2":"已反馈", "3":"已接收反馈意见", "4":"通过", "5":"未通过", "8":"终止", "9":"中止", "10":"已回复交易所意见", "11":"提交注册", "12":"注册生效"}
PRODUCT_TYPE = {"0":"商业不动产REITs", "1":"基础设施REITs"}
PAGE_SIZE = 100


class CollectionError(RuntimeError):
    pass


def clean(value):
    value = html.unescape(re.sub(r"<[^>]*>", "", str("" if value is None else value))).strip()
    return "" if value in ("-", "None", "null") else value


def number(value):
    try:
        result = float(clean(value).replace(",", ""))
        return result if math.isfinite(result) and result >= 0 else None
    except (ValueError, TypeError):
        return None


def date(value):
    value = clean(value)
    return value[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", value) else ""


def now():
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def parse_json(body):
    raw = body.decode("utf-8-sig")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.fullmatch(r"\s*[\w.$]+\s*\((.*)\)\s*;?\s*", raw, re.S)
        if not match:
            raise CollectionError("Official response is not JSON/JSONP")
        return json.loads(match.group(1))


class RawClient:
    def __init__(self, raw_dir):
        self.raw_dir = Path(raw_dir)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.manifest_path = self.raw_dir / "manifest.json"
        self.manifest = json.loads(self.manifest_path.read_text()) if self.manifest_path.exists() else []
        self.cache = {(r["url"], json.dumps(r.get("params", {}), sort_keys=True, ensure_ascii=False)): r for r in self.manifest if r.get("status") == "ok"}

    def get(self, path, params=None, label="response", referer=REFERER, raw=False):
        url = path if path.startswith("https://") else API + path
        params = params or {}
        key = (url, json.dumps(params, sort_keys=True, ensure_ascii=False))
        with self.lock:
            cached = self.cache.get(key)
        if cached:
            body = (self.raw_dir / cached["file"]).read_bytes()
            if hashlib.sha256(body).hexdigest() != cached["sha256"]:
                raise CollectionError("Raw cache hash mismatch: " + cached["file"])
            return body if raw else parse_json(body)
        target = url + (("&" if "?" in url else "?") + urllib.parse.urlencode(params) if params else "")
        error = None
        for attempt in range(3):
            try:
                PACER.wait(target)
                req = urllib.request.Request(target, headers={"User-Agent":"Mozilla/5.0 (REITsResearchDashboard)", "Referer":referer, "Accept":"application/json,text/javascript,*/*"})
                with urlopen(req, timeout=40) as response:
                    body = response.read()
                    final_url = response.url
                    content_type = response.headers.get("Content-Type", "")
                if not raw:
                    parsed = parse_json(body)
                    if not isinstance(parsed, dict) or parsed.get("actionErrors") or parsed.get("fieldErrors"):
                        raise CollectionError("Malformed/error official response")
                digest = hashlib.sha256(body).hexdigest()
                file = re.sub(r"[^A-Za-z0-9_.-]", "_", label) + "_" + hashlib.sha256(target.encode()).hexdigest()[:12] + (".bin" if raw else ".json")
                with self.lock:
                    dest = self.raw_dir / file
                    if dest.exists() and dest.read_bytes() != body:
                        file = dest.stem + "_" + digest[:12] + dest.suffix
                        dest = self.raw_dir / file
                    if not dest.exists():
                        dest.write_bytes(body)
                    entry = {"url":url, "params":params, "request_url":target, "response_url":final_url, "referer":referer, "retrieved_at":now(), "file":file, "sha256":digest, "bytes":len(body), "content_type":content_type, "status":"ok"}
                    self.manifest.append(entry)
                    self.cache[key] = entry
                    self.manifest_path.write_text(json.dumps(self.manifest, ensure_ascii=False, indent=2) + "\n")
                return body if raw else parsed
            except Exception as exc:
                error = exc
                if attempt < 2:
                    backoff(target, exc, attempt)
        raise CollectionError("Request failed: " + target + " : " + str(error))


def fetch_pages(client, sql_id, endpoint="commonSoaQuery.do", params=None, identity=None):
    rows, ids, fingerprints = [], set(), set()
    total, count, page = None, 1, 1
    while page <= count:
        if page > 1000:
            raise CollectionError("Protective page limit exceeded")
        query = {"sqlId":sql_id, "isPagination":"true", "pageHelp.pageSize":PAGE_SIZE, "pageHelp.cacheSize":1, "pageHelp.pageNo":page, "pageHelp.beginPage":page, "pageHelp.endPage":page, **(params or {})}
        response = client.get(endpoint, query, sql_id + "_p" + str(page))
        result, meta = response.get("result"), response.get("pageHelp")
        if not isinstance(result, list) or not isinstance(meta, dict):
            raise CollectionError(sql_id + " missing list/pagination")
        try:
            advertised, actual_page, size, pages = (int(meta[k]) for k in ("total", "pageNo", "pageSize", "pageCount"))
        except (KeyError, TypeError, ValueError):
            raise CollectionError(sql_id + " invalid pagination metadata")
        if advertised < 0 or size < 1 or pages < 0 or actual_page != page or pages != max(1, math.ceil(advertised / size)) and not (advertised == 0 and pages == 0):
            raise CollectionError(sql_id + " inconsistent pagination")
        if total is None:
            total, count = advertised, max(1, pages)
        elif advertised != total or max(1, pages) != count:
            raise CollectionError(sql_id + " source changed during pagination")
        # cacheSize=1 ensures each response contains exactly this page.
        expected = max(0, min(size, total - (page - 1) * size))
        if len(result) != expected:
            raise CollectionError(sql_id + " truncated/extra page rows")
        fingerprint = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
        if result and fingerprint in fingerprints:
            raise CollectionError(sql_id + " repeated page")
        fingerprints.add(fingerprint)
        for row in result:
            if identity:
                key = identity(row)
                if not key or key in ids:
                    raise CollectionError(sql_id + " missing/duplicate identity")
                ids.add(key)
            rows.append(row)
        page += 1
    if len(rows) != total:
        raise CollectionError(sql_id + " total does not reconcile")
    return rows, {"sql_id":sql_id, "advertised_total":total, "collected_rows":len(rows), "pages":count, "complete":True}


def source_url(source_id):
    return "https://www.sse.com.cn/reits/info/index_detail.shtml?audit_id=" + urllib.parse.quote(source_id)


def normalize_event(raw, documents=()):
    source_id = clean(raw.get("BOND_NUM"))
    if not source_id:
        raise CollectionError("Missing official SSE filing ID")
    rt = clean(raw.get("REITS_TYPE"))
    business = {"0":"首发", "1":"扩募"}.get(rt, "待核实")
    status = clean(raw.get("AUDIT_STATUS"))
    # Mirror the exact ordering in SSE's status_transfer function.
    label = STATUS.get(status, "待核实")
    if status not in ("0", "1", "2", "3", "4", "5", "8") and clean(raw.get("AUDIT_SUB_STATUS")) == "901":
        label = "承销商/管理人超期中止"
    docs = [{"title":clean(d.get("FILE_TITLE")) or clean(d.get("FILE_TYPE")), "url":"https://static.sse.com.cn/bond" + clean(d.get("FILE_PATH")), "date":date(d.get("FILE_TIME")), "official_file_type":clean(d.get("FILE_TYPE")), "official_version":clean(d.get("FILE_VERSION"))} for d in documents if clean(d.get("FILE_PATH"))]
    return {"id":"SSE_" + source_id, "source_id":source_id, "name":clean(raw.get("AUDIT_NAME")), "exchange":"上交所", "business_type":business, "official_business_type":rt, "fund_code":"", "manager":clean(raw.get("WRITER_NAME")), "manager_short_name":clean(raw.get("SHORT_NAME")), "origin":clean(raw.get("FULL_NAME")), "official_status":label, "official_status_code":status, "official_sub_status":clean(raw.get("AUDIT_SUB_STATUS")), "accepted_date":date(raw.get("ACCEPT_DATE")), "updated_date":date(raw.get("PUBLISH_DATE")), "registered_date":"", "source_url":source_url(source_id), "asset_type":"待分类", "product_type":PRODUCT_TYPE.get(clean(raw.get("REITS_ASSET_TYPE")), "待核实"), "documents":docs, "underlying_assets":[], "planned_issue_amount_official":number(raw.get("PLAN_ISSUE_AMOUNT")), "planned_issue_amount_unit":"未展示（官方字段PLAN_ISSUE_AMOUNT，未纳入规模统计）", "special_plan_name":clean(raw.get("PRIORITY_NAME")), "special_plan_manager":clean(raw.get("PRIORITY_MANAGER")), "official_registration_approval_no":clean(raw.get("REG_APRV_WEN_HAO")), "official_no_objection_no":clean(raw.get("WEN_HAO"))}


def normalize_fund(code, list_row, detail, issue=None, as_of=None):
    issue = issue or {}
    as_of = as_of or now()[:10]
    name = clean(detail.get("FUND_NAME")) or clean(list_row.get("FUND_EXPANSION_ABBR")) or clean(issue.get("fundExpansionAbbr"))
    planned_listing = date(detail.get("LISTING_DATE")) or date(list_row.get("LISTING_DATE")) or date(issue.get("listingDate"))
    actual_listing = planned_listing if planned_listing and planned_listing <= as_of else ""
    established = date(detail.get("ESTABLISH_DATE"))
    established = established if established and established <= as_of else ""
    start, end = date(issue.get("startDate")), date(issue.get("endDate"))
    if actual_listing:
        stage = "已上市"
    elif established:
        stage = "成立待上市"
    elif start and start <= as_of and (not end or end >= as_of):
        stage = "发行中"
    elif end and end < as_of:
        stage = "发售结束待成立核验"
    else:
        stage = "获批待发行"
    price, copies = number(issue.get("salePrice")), number(issue.get("saleCopies"))
    return {"id":"SSE_FUND_"+code, "code":code, "name":name, "short_name":clean(list_row.get("FUND_EXPANSION_ABBR")) or clean(issue.get("fundExpansionAbbr")), "exchange":"上交所", "manager":clean(detail.get("COMPANY_NAME")) or clean(list_row.get("COMPANY_NAME")), "fund_managers":clean(detail.get("FUND_MANAGER")), "origin":"", "product_type":"商业不动产REITs" if "商业不动产" in name else ("基础设施REITs" if "基础设施" in name else "待核实"), "asset_type":"待分类", "listing_date":actual_listing, "planned_listing_date":planned_listing if planned_listing > as_of else "", "established_date":established, "initial_raise_cny_100m":round(price * copies, 8) if price is not None and copies is not None and established else None, "initial_offered_cny_100m":round(price * copies, 8) if price is not None and copies is not None else None, "initial_price_cny":price, "initial_copies_100m":copies, "initial_issue_start":start, "initial_issue_end":end, "stage":stage, "source_url":"https://etf.sse.com.cn/fundlist/funddetail/index.shtml?code="+code+"&category="+clean(list_row.get("CATEGORY") or "F600"), "documents":[], "aliases":list(dict.fromkeys(v for v in (name, clean(list_row.get("FUND_ABBR")), clean(list_row.get("FUND_EXPANSION_ABBR")), clean(issue.get("fundAbbr")), clean(issue.get("fundExpansionAbbr"))) if v))}


def link_exact_fund_names(events, funds):
    names = {}
    for fund in funds:
        for name in fund.get("aliases", []) + [fund["name"]]:
            names.setdefault(re.sub(r"\s+", "", name), set()).add(fund["code"])
    by_code = {f["code"]:f for f in funds}
    for event in events:
        candidates = names.get(re.sub(r"\s+", "", event["name"]), set())
        if len(candidates) == 1:
            event["fund_code"] = next(iter(candidates))
            event["fund_link_evidence"] = {"method":"exact_official_fund_name", "matched_name":event["name"], "source_url":by_code[event["fund_code"]]["source_url"]}
            if not by_code[event["fund_code"]]["origin"] and event["business_type"] == "首发":
                by_code[event["fund_code"]]["origin"] = event["origin"]


def apply_reviewed_links(events, funds, overrides):
    """Apply only reviewed official-name/code evidence, retaining its source."""
    by_code = {fund["code"]:fund for fund in funds}
    for event in events:
        link = overrides.get(event["id"])
        if not link:
            continue
        parsed = urllib.parse.urlparse(link.get("source_url", ""))
        if parsed.scheme != "https" or not (parsed.hostname or "").endswith("sse.com.cn") or not link.get("note") or link.get("fund_code") not in by_code:
            raise CollectionError("Invalid reviewed official linkage " + event["id"])
        event["fund_code"] = link["fund_code"]
        event["fund_link_evidence"] = dict(link, method="reviewed_official_name_code_announcement")
        fund = by_code[link["fund_code"]]
        fund["aliases"] = list(dict.fromkeys(fund.get("aliases", []) + [event["name"]]))
        if event["business_type"] == "首发" and not fund.get("origin"):
            fund["origin"] = event["origin"]


def mark_unique_completed_expansions(events, batches):
    """Match only a unique registered filing and unique completed offer batch."""
    for batch in batches:
        if batch["business_type"] != "扩募" or not batch["completed_listing_date"]:
            continue
        same_batches = [b for b in batches if b["business_type"] == "扩募" and b["fund_code"] == batch["fund_code"]]
        candidates = [e for e in events if e.get("fund_code") == batch["fund_code"] and e["business_type"] == "扩募" and e["official_status_code"] == "12" and e["accepted_date"] and e["accepted_date"] <= batch["start_date"] and e["updated_date"] <= batch["start_date"]]
        if len(same_batches) != 1 or len(candidates) != 1:
            continue
        event = candidates[0]
        event["completion_date"] = batch["completed_listing_date"]
        event["completion_evidence"] = {"method":"unique_official_fund_code_and_completed_expansion_batch", "source_url":batch["source_url"], "fund_code":batch["fund_code"], "official_fund_stage":batch["official_fund_stage"], "start_date":batch["start_date"], "end_date":batch["end_date"], "listing_date":batch["completed_listing_date"], "filing_accepted_date":event["accepted_date"], "filing_status_update_date":event["updated_date"], "matching_registered_filings":1, "matching_expansion_batches":1}


def collect(raw_dir, link_overrides=None):
    client = RawClient(raw_dir)
    collected_at = now()
    as_of = collected_at[:10]
    # Preserve the source's interface definitions used to interpret types/units.
    for name, url in (("filing_script","https://www.sse.com.cn/xhtml/reits/js/search/search_info.js"), ("issuance_script","https://www.sse.com.cn/xhtml/reits/js/search/search_issuanceInfo_2026.js"), ("fundlist_script","https://etf.sse.com.cn/xhtml/js/fundlist.js")):
        client.get(url, label=name, raw=True)
    filings, filing_check = fetch_pages(client, "ZQ_XMLB", params={"bond_type":4}, identity=lambda r:clean(r.get("BOND_NUM")))
    issues, issue_check = fetch_pages(client, "REITS_FXYKM", identity=lambda r:(clean(r.get("fundCode")), clean(r.get("fundStage")), date(r.get("startDate"))))
    listed, listed_check = fetch_pages(client, "COMMON_JJZWZ_JJLB_L", "commonQuery.do", {"CATEGORY":"F600"}, identity=lambda r:clean(r.get("FUND_CODE")))
    first_issues = {}
    for row in issues:
        if clean(row.get("fundStage")) == "1":
            code = clean(row.get("fundCode"))
            if code in first_issues:
                raise CollectionError("Multiple first-offer rows for " + code)
            first_issues[code] = row
    listed_by_code = {clean(r.get("FUND_CODE")):r for r in listed}
    codes = sorted(set(listed_by_code) | set(first_issues))

    def get_fund(code):
        response = client.get("commonQuery.do", {"sqlId":"COMMON_JJZWZ_JJLB_JJXQ_JBXX_C", "isPagination":"false", "FUND_CODE":code}, "fund_"+code)
        records = response.get("result")
        if not isinstance(records, list) or len(records) != 1 or clean(records[0].get("FUND_CODE")) != code:
            raise CollectionError("Missing/mismatched fund detail " + code)
        return normalize_fund(code, listed_by_code.get(code, {}), records[0], first_issues.get(code), as_of)

    def get_event(row):
        sid = clean(row.get("BOND_NUM"))
        response = client.get("commonSoaQuery.do", {"sqlId":"ZQ_GGJG", "isPagination":"false", "audit_id":sid}, "filing_documents_"+sid)
        docs = response.get("result")
        if not isinstance(docs, list):
            raise CollectionError("Missing filing documents " + sid)
        event = normalize_event(row, docs)
        event["documents_checked"] = True
        return event

    funds = [get_fund(code) for code in codes]
    events = [get_event(row) for row in filings]
    link_exact_fund_names(events, funds)
    if link_overrides is None:
        override_path = Path(__file__).resolve().parent.parent / "config/public_fund_links.json"
        link_overrides = json.loads(override_path.read_text()) if override_path.exists() else {}
    apply_reviewed_links(events, funds, link_overrides)
    # Keep issuance batches separate; a batch date cannot safely be assigned to a
    # same-name re-submission without an identified link to that filing.
    batches = [{"fund_code":clean(r.get("fundCode")), "official_fund_stage":clean(r.get("fundStage")), "business_type":{"1":"首发", "2":"扩募"}.get(clean(r.get("fundStage")), "待核实"), "official_expansion_type":clean(r.get("fundType")), "short_name":clean(r.get("fundExpansionAbbr")), "start_date":date(r.get("startDate")), "end_date":date(r.get("endDate")), "listing_date":date(r.get("listingDate")), "completed_listing_date":date(r.get("listingDate")) if date(r.get("listingDate")) <= as_of else "", "price_cny":number(r.get("salePrice")), "copies_100m":number(r.get("saleCopies")), "source_url":"https://www.sse.com.cn/reits/listing/issue/"} for r in issues]
    mark_unique_completed_expansions(events, batches)
    status = {"exchange":"上交所", "collected_at":collected_at, "as_of_date":as_of, "complete":True, "checks":[filing_check, issue_check, listed_check], "fund_details_expected":len(codes), "fund_details_collected":len(funds), "filing_documents_expected":len(filings), "filing_documents_collected":len(events), "latest_filing_update":max((e["updated_date"] for e in events), default=""), "earliest_filing_acceptance":min((e["accepted_date"] for e in events if e["accepted_date"]), default=""), "exact_linked_events":sum(bool(e["fund_code"]) for e in events), "unlinked_events":sum(not e["fund_code"] for e in events), "notes":["基金名录与首次发售批次取并集，发售未开始及未来上市日期不视为已发行或已上市", "REITS_TYPE=1按官方脚本标为扩募；保留原始申报类型，未独立推断新购入", "扩募批次上市日期单独保留，未仅凭基金相同将完成日期分配至申报事件"]}
    source_times = [r["retrieved_at"] for r in client.manifest if r.get("params", {}).get("sqlId")]
    if source_times:
        status["collected_at"] = min(source_times)
        status["collection_finished_at"] = max(source_times)
    status["normalization_updated_at"] = now()
    status["exact_linked_events"] = sum(e.get("fund_link_evidence", {}).get("method") == "exact_official_fund_name" for e in events)
    status["reviewed_linked_events"] = sum(e.get("fund_link_evidence", {}).get("method") == "reviewed_official_name_code_announcement" for e in events)
    status["linked_events"] = sum(bool(e["fund_code"]) for e in events)
    status["completed_expansions"] = sum(bool(e.get("completion_date")) for e in events)
    status["notes"][-1] = "仅对已核实基金代码、唯一已注册扩募申报及唯一已上市扩募批次匹配完成日期；其余保留未匹配状态"
    return {"funds":funds, "events":events, "issuance_batches":batches, "source_status":status, "manifest":client.manifest}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", default="data/raw/public/"+now()[:10]+"/sse")
    parser.add_argument("--output", default="workpapers/public/sse_collected.json")
    args = parser.parse_args()
    result = collect(args.raw_dir)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps(result["source_status"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
