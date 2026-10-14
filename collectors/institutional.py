"""Collect institutional REIT project lists directly from official SSE/SZSE APIs.

Uses only Python's standard library. Lists are fetched for BOTH keywords and
all reported pages. A failed list query aborts publication of the new snapshot.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
import re
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

KEYWORDS = ("持有型不动产", "机构间REIT")
SSE_ENDPOINT = "https://query.sse.com.cn/sseQuery/commonSoaQuery.do"
SSE_REFERER = "https://bond.sse.com.cn/bridge2/information/index_search.shtml"
SZSE_ENDPOINT = "https://bond.szse.cn/api/report/ShowReport/data"
SZSE_REFERER = "https://bond.szse.cn/disclosure/progressinfo/index.html"
PAGE_SIZE = 100
MAX_PAGES = 1000
STATUS_MAP_SZSE = {"已受理":"1", "已反馈":"2", "通过":"4", "不通过":"5",
                   "提交注册":"11", "注册生效":"12", "不予注册":"5", "终止":"8", "中止":"9"}
STATUS_LABEL = {"0":"已申报", "1":"已受理", "2":"已反馈", "3":"已接收反馈意见", "4":"通过",
                "5":"未通过", "8":"终止", "9":"中止", "10":"已回复交易所意见", "11":"提交注册", "12":"注册生效"}


class CollectionError(RuntimeError):
    """A source did not return a complete, trustworthy set of list pages."""


def text(value):
    value = html.unescape(re.sub(r"<[^>]*>", "", str(value or ""))).strip()
    return "" if value in ("-", " , ") else value


def amount(value):
    try:
        result = float(text(value).replace(",", ""))
        return result if math.isfinite(result) and result >= 0 else None
    except (ValueError, TypeError):
        return None


def matching_keywords(name, candidates=KEYWORDS):
    normalized = re.sub(r"\s+", "", text(name)).casefold()
    return [kw for kw in candidates if re.sub(r"\s+", "", kw).casefold() in normalized]


def classify_by_name(name):
    """Transparent keyword classification; ambiguous names remain unknown."""
    groups = [
        ("经营权类", "交通设施", ["高速", "公路", "铁路", "机场", "港口", "大桥", "隧道", "地铁", "码头", "轨道交通"]),
        ("经营权类", "能源", ["能源", "光伏", "风电", "水电", "储能", "电力", "天然气", "燃气", "热力", "电站"]),
        ("经营权类", "市政生态", ["水务", "供水", "污水", "水厂", "垃圾", "环卫", "环保", "生态", "市政"]),
        ("产权类", "租赁住房", ["租赁住房", "住房租赁", "保租房", "保障房", "人才房", "租赁房", "公寓", "安居", "长租"]),
        ("产权类", "数据中心", ["数据中心", "idc", "算力", "智算", "超算", "数据港"]),
        ("产权类", "物流仓储", ["物流", "仓储", "冷链", "快递"]),
        ("产权类", "产业园", ["产业园", "园区", "科技园", "工业", "厂房", "孵化"]),
        ("产权类", "办公", ["办公", "写字楼", "总部"]),
        ("产权类", "文旅类", ["文旅", "旅游", "酒店", "景区", "度假", "乐园"]),
        ("产权类", "消费", ["消费", "商业", "广场", "购物中心", "百货", "商场", "零售", "农贸", "商厦"]),
    ]
    n = text(name).casefold()
    hits = [(pt, sub, kw) for pt, sub, kws in groups for kw in kws if kw.casefold() in n]
    categories = {(pt, sub) for pt, sub, _ in hits}
    if len(categories) == 1:
        pt, sub = next(iter(categories))
        return {"ptype":pt, "psub":sub, "pflag":"", "pnote":"名称关键词：" + "、".join(sorted({h[2] for h in hits})), "classification_source":"keyword"}
    reason = "名称无明确资产关键词" if not hits else "名称命中多个资产类别，需核对底层资产"
    return {"ptype":"待分类", "psub":"待分类", "pflag":"待分类", "pnote":reason, "classification_source":"unknown"}


def parse_szse_identity(zqmc):
    # The official anchor's href may be javascript:void(0). xmbh is in a-param.
    match = re.search(r"(?:[?&]|&amp;)xmbh=([a-f0-9]+)(?=[&'\"\s<>]|$)", html.unescape(str(zqmc)), re.I)
    if not match:
        raise ValueError("SZSE project anchor is missing its official xmbh ID")
    return match.group(1).upper()


def source_url(exchange, source_id):
    if not re.fullmatch(r"[a-fA-F0-9]+", str(source_id or "")):
        raise ValueError("Invalid official project ID")
    if exchange in ("SSE", "上交所"):
        return "https://bond.sse.com.cn/bridge/information/index_detail.shtml?bound_id=" + urllib.parse.quote(str(source_id))
    if exchange in ("SZSE", "深交所"):
        # Official report JS forwards these query parameters to the detail catalog.
        params = {"CATALOGID":"xmjdxx_xq", "TABKEY":"tab1", "xmbh":str(source_id).upper(), "type":"2"}
        return SZSE_REFERER + "?" + urllib.parse.urlencode(params)
    raise ValueError("Unknown exchange")


def normalize_sse(raw, query_keyword):
    source_id = str(raw.get("BOND_NUM") or "").strip()
    if not source_id:
        raise CollectionError("SSE record is missing BOND_NUM")
    name = text(raw.get("AUDIT_NAME"))
    row = {"id":"SSE_"+source_id, "source_id":source_id, "ex":"上交所", "name":name,
           "writer":text(raw.get("WRITER_NAME")), "mgr":text(raw.get("SHORT_NAME")), "origin":text(raw.get("FULL_NAME")),
           "amt":amount(raw.get("PLAN_ISSUE_AMOUNT")), "status":str(raw.get("AUDIT_STATUS") or ""),
           "up":text(raw.get("PUBLISH_DATE")), "acc":text(raw.get("ACCEPT_DATE")),
           "match_keywords":matching_keywords(name) or [query_keyword], "query_keywords":[query_keyword],
           "source_url":source_url("SSE",source_id), "source_kind":"project_page", "link_status":"constructed",
           "is_expansion":"扩募" in name, "archive_status":"current", "product_type":"institutional"}
    row.update(classify_by_name(name))
    return row


def normalize_szse(raw, query_keyword, detail=None):
    source_id = parse_szse_identity(raw.get("zqmc", ""))
    name = text(raw.get("zqmc"))
    detail = detail or {}
    row = {"id":"SZSE_"+source_id, "source_id":source_id, "ex":"深交所", "name":name,
           "writer":text(detail.get("cxsqc") or detail.get("cxsjc")), "mgr":text(raw.get("cxsjc")), "origin":text(detail.get("fxr")),
           "amt":amount(raw.get("nfxje")), "status":STATUS_MAP_SZSE.get(text(raw.get("xmzt")), text(raw.get("xmzt"))),
           "up":text(raw.get("xmztgxrq")), "acc":text(raw.get("xmslrq")),
           "match_keywords":matching_keywords(name) or [query_keyword], "query_keywords":[query_keyword],
           "source_url":source_url("SZSE",source_id), "source_kind":"project_page", "link_status":"constructed",
           "source_data_url":SZSE_ENDPOINT+"?"+urllib.parse.urlencode({"SHOWTYPE":"JSON","CATALOGID":"xmjdxx_xq","TABKEY":"tab1","xmbh":source_id,"type":"2"}),
           "is_expansion":"扩募" in name, "archive_status":"current", "product_type":"institutional"}
    row.update(classify_by_name(name))
    return row


def merge_records(records):
    merged = {}
    for row in records:
        if not row.get("id") or not row.get("source_id"):
            raise CollectionError("Cannot merge records without stable official IDs")
        key = row["id"]
        if key not in merged:
            merged[key] = dict(row)
            continue
        old = merged[key]
        queries = set(old.get("query_keywords",[])) | set(row.get("query_keywords",[]))
        matches = set(old.get("match_keywords",[])) | set(row.get("match_keywords",[]))
        if (row.get("up", ""), row.get("acc", "")) > (old.get("up", ""), old.get("acc", "")):
            combined = dict(old)
            combined.update({k:v for k,v in row.items() if v not in (None, "")})
            old = merged[key] = combined
        else:
            for k,v in row.items():
                if old.get(k) in (None, "") and v not in (None, ""):
                    old[k] = v
        old["query_keywords"] = sorted(queries)
        old["match_keywords"] = sorted(matches)
    result = sorted(merged.values(), key=lambda r:(r.get("up", ""), r.get("acc", ""), r.get("amt") if r.get("amt") is not None else -1, r["id"]), reverse=True)
    for n,row in enumerate(result,1):
        row["num"] = str(n)
    return result


def http_get_json(url, params, referer):
    query = urllib.parse.urlencode(params)
    target = url + ("&" if "?" in url else "?") + query
    request = urllib.request.Request(target, headers={"User-Agent":"Mozilla/5.0 (compatible; REITsResearchDashboard/1.0)", "Referer":referer, "Accept":"application/json,text/javascript,*/*"})
    error = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8-sig")
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                match = re.fullmatch(r"\s*[\w.$]+\s*\((.*)\)\s*;?\s*",raw,re.S)
                if not match:
                    raise CollectionError("Official API returned neither JSON nor JSONP")
                return json.loads(match.group(1))
        except Exception as exc:
            error = exc
            if attempt < 2:
                time.sleep(1 + attempt)
    raise CollectionError("Request failed: " + url + " (" + str(error) + ")")


def _pages(exchange, keyword, request=None):
    fetch = request or http_get_json
    all_rows, raw_pages, advertised_total = [], [], None
    page, expected_pages, actual_size = 1, 1, PAGE_SIZE
    page_fingerprints = set()
    while page <= expected_pages:
        if page > MAX_PAGES:
            raise CollectionError("Pagination exceeds protective limit")
        if exchange == "SSE":
            params = {"jsonCallBack":"cb", "isPagination":"true", "sqlId":"ZQ_XMLB", "key":keyword,
                      "pageHelp.pageSize":PAGE_SIZE, "pageHelp.pageNo":page, "pageHelp.beginPage":page, "pageHelp.endPage":page}
            packet = fetch(SSE_ENDPOINT, params, SSE_REFERER + "?key=" + urllib.parse.quote(keyword))
            if not isinstance(packet,dict) or "result" not in packet:
                raise CollectionError("SSE response schema changed")
            if any(packet.get(key) for key in ("error","actionErrors","fieldErrors")):
                raise CollectionError("SSE reported an API error")
            rows, meta = packet.get("result"), packet.get("pageHelp") or {}
            total = int(meta.get("total",len(rows or [])))
            actual_size = int(meta.get("pageSize") or meta.get("page_size") or PAGE_SIZE)
            new_pages = int(meta.get("pageCount") or meta.get("pagecount") or math.ceil(total/actual_size) or 1)
        else:
            params = {"SHOWTYPE":"JSON", "CATALOGID":"xmjdxx", "txtZqmc":keyword, "pageSize":PAGE_SIZE, "pageNo":page}
            packet = fetch(SZSE_ENDPOINT, params, SZSE_REFERER)
            if not isinstance(packet,list) or not packet or "data" not in packet[0]:
                raise CollectionError("SZSE response schema changed")
            if packet[0].get("error"):
                raise CollectionError("SZSE reported an API error")
            rows, meta = packet[0].get("data"), packet[0].get("metadata") or {}
            total = int(meta.get("recordcount",len(rows or [])))
            actual_size = int(meta.get("pagesize") or PAGE_SIZE)
            new_pages = int(meta.get("pagecount") or math.ceil(total/actual_size) or 1)
        if not isinstance(rows,list):
            raise CollectionError(exchange + " page is not a record list")
        returned_page = int(meta.get("pageNo") or meta.get("pageno") or page)
        if returned_page != page:
            raise CollectionError(exchange + " API returned a different page than requested")
        fingerprint = hashlib.sha256(json.dumps(rows,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        if rows and fingerprint in page_fingerprints:
            raise CollectionError(exchange + " repeated an entire list page")
        page_fingerprints.add(fingerprint)
        if advertised_total is None:
            advertised_total = total
        elif total != advertised_total:
            raise CollectionError(exchange + " list changed during pagination; retry a consistent snapshot")
        expected_pages = max(expected_pages, new_pages)
        if not rows and total > 0:
            raise CollectionError(exchange + " returned an empty page before completion")
        all_rows.extend(rows)
        raw_pages.append(packet)
        page += 1
    if len(all_rows) < (advertised_total or 0):
        raise CollectionError(exchange + " returned fewer records than its advertised total")
    return all_rows, {"keyword":keyword, "advertised_total":advertised_total or 0,
                      "raw_count":len(all_rows), "pages":len(raw_pages), "actual_page_size":actual_size,
                      "raw_pages":raw_pages}


def fetch_sse(keyword, request=None):
    return _pages("SSE",keyword,request)


def fetch_szse(keyword, request=None):
    return _pages("SZSE",keyword,request)


def _atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w",encoding="utf-8",dir=path.parent,prefix="."+path.name+".",suffix=".tmp",delete=False) as handle:
            temporary = handle.name
            json.dump(payload,handle,ensure_ascii=False,indent=2,allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary,path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def _inherit_classification(row, previous, overrides):
    # Repository-owned overrides take precedence. Unknown defaults stay unknown.
    override = overrides.get(row["id"]) or overrides.get(row["source_id"])
    if override:
        for k in ("ptype","psub","pnote"):
            if k in override:row[k]=override[k]
        row.update({"pflag":"", "classification_source":"manual"})
    elif previous and previous.get("classification_source") == "manual":
        for k in ("ptype","psub","pflag","pnote","classification_source"):
            if k in previous:row[k]=previous[k]


def collect_snapshot(request=None, previous=None, overrides=None, raw_dir=None):
    fetch = request or http_get_json
    previous = previous or {}
    previous_rows = {r["id"]:r for r in previous.get("items",[])}
    overrides = overrides or {}
    collected, source_status, warnings = [], {}, []
    details_cache = {}
    for exchange, loader, normalizer in (("SSE",fetch_sse,normalize_sse),("SZSE",fetch_szse,normalize_szse)):
        queries, source_records = [], []
        for keyword in KEYWORDS:
            try:
                raw_rows, metadata = loader(keyword,request=fetch)
            except Exception as exc:
                raise CollectionError(exchange + " query " + keyword + " incomplete: " + str(exc)) from exc
            packets = metadata.pop("raw_pages")
            if raw_dir:
                slug = "holding" if keyword == KEYWORDS[0] else "institutional"
                for page,packet in enumerate(packets,1):
                    _atomic_json(Path(raw_dir)/(exchange.lower()+"_"+slug+"_page"+str(page)+".json"),packet)
            normalized = []
            for raw in raw_rows:
                if exchange == "SZSE":
                    sid = parse_szse_identity(raw.get("zqmc",""))
                    if sid not in details_cache:
                        params = {"SHOWTYPE":"JSON", "CATALOGID":"xmjdxx_xq", "TABKEY":"tab1", "xmbh":sid, "type":"2"}
                        try:
                            packet = fetch(SZSE_ENDPOINT,params,SZSE_REFERER)
                            detail = packet[0]["data"][0]
                            details_cache[sid] = detail
                            if raw_dir:_atomic_json(Path(raw_dir)/("szse_detail_"+sid+".json"),packet)
                        except Exception as exc:
                            details_cache[sid] = {}
                            warnings.append({"source":"SZSE", "project_id":sid, "field":"detail", "reason":str(exc)})
                    row = normalizer(raw,keyword,details_cache[sid])
                    if details_cache[sid]:row["link_status"]="verified"
                else:
                    row = normalizer(raw,keyword)
                if not matching_keywords(row["name"]):
                    warnings.append({"source":exchange,"project_id":row["source_id"],"field":"name_match","reason":"API keyword matched a field other than name; excluded"})
                    continue
                normalized.append(row)
            metadata["unique_count"] = len({r["id"] for r in normalized})
            queries.append(metadata)
            source_records.extend(normalized)
        unique_source = merge_records(source_records)
        source_status[exchange] = {"ok":True, "total":len(unique_source), "queries":queries,
                                   "list_endpoint":SSE_ENDPOINT if exchange=="SSE" else SZSE_ENDPOINT}
        collected.extend(unique_source)
    items = merge_records(collected)
    if not items:
        raise CollectionError("Both sources returned an empty union; refusing to replace an existing snapshot")
    for row in items:
        old = previous_rows.get(row["id"],{})
        _inherit_classification(row,old,overrides)
        if row["ex"] == "深交所" and not details_cache.get(row["source_id"]):
            for field in ("writer","origin"):
                if not row.get(field) and old.get(field):row[field]=old[field]
    old_ids = set(previous_rows)
    current_ids = {r["id"] for r in items}
    missing = sorted(old_ids-current_ids)
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    checksum = hashlib.sha256(json.dumps(items,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    return {"schema_version":1, "date":now.date().isoformat(), "updated_at":now.isoformat(timespec="seconds"),
            "source_status":source_status, "coverage":{"complete":True,"keywords":list(KEYWORDS),"population":"直接采集沪深交易所项目名称匹配关键词的机构间 REITs 申报记录","unit":"亿元","count":len(items)},
            "changes":{"added_ids":sorted(current_ids-old_ids) if old_ids else [],"missing_ids":missing},
            "quality":{"duplicate_ids":0,"unknown_classification":sum(r["classification_source"]=="unknown" for r in items),"detail_warnings":warnings,"content_sha256":checksum},
            "items":items}


def write_snapshot(snapshot, output, archive_dir=None):
    if not snapshot.get("coverage",{}).get("complete"):
        raise CollectionError("Incomplete snapshots cannot replace published data")
    rows = snapshot.get("items")
    if not isinstance(rows,list) or not rows or len({r.get("id") for r in rows}) != len(rows):
        raise CollectionError("Snapshot IDs must be unique and nonempty")
    if any(not r.get("id") or not r.get("source_url") for r in rows):
        raise CollectionError("Every record must retain its official project ID and URL")
    if archive_dir:
        _atomic_json(Path(archive_dir)/(snapshot["date"]+".json"),snapshot)
    _atomic_json(output,snapshot)


def verify_project_links(snapshot, request=None, workers=4):
    """Validate identity through each official detail API, not just an HTML 200."""
    fetch = request or http_get_json
    def check(row):
        if row['ex'] == '上交所':
            packet = fetch('https://query.sse.com.cn/commonSoaQuery.do',
                           {'jsonCallBack':'cb','isPagination':'false','sqlId':'ZQ_XMLB',
                            'audit_id':row['source_id'],'bond_type':'0,1,2,3,5,6,7'}, row['source_url'])
            records = packet.get('result', [])
            valid = any(str(r.get('BOND_NUM')) == row['source_id'] and text(r.get('AUDIT_NAME')) == row['name'] for r in records)
        else:
            packet = fetch(SZSE_ENDPOINT, {'SHOWTYPE':'JSON','CATALOGID':'xmjdxx_xq','TABKEY':'tab1',
                                          'xmbh':row['source_id'],'type':'2'}, SZSE_REFERER)
            records = packet[0].get('data', [])
            valid = any(text(r.get('zqmc')) == row['name'] for r in records)
        if not valid:
            raise CollectionError('Official detail does not match project identity: '+row['id'])
        return row['id']
    with ThreadPoolExecutor(max_workers=workers) as executor:
        verified = set(executor.map(check,snapshot['items']))
    checked_at = datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')
    for row in snapshot['items']:
        if row['id'] in verified:
            row['source_url'] = source_url(row['ex'],row['source_id'])
            row['link_status'] = 'verified'
            row['link_checked_at'] = checked_at
    snapshot['quality']['link_validation'] = {'verified':len(verified),'total':len(snapshot['items']),
                                               'checked_at':checked_at,'method':'official_detail_identity_and_official_page_route'}
    snapshot['quality']['content_sha256'] = hashlib.sha256(json.dumps(snapshot['items'],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    return snapshot


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",default="data/institutional.json")
    parser.add_argument("--archive-dir",default="snapshots")
    parser.add_argument("--raw-dir",default=None)
    parser.add_argument("--overrides",default="config/classification_overrides.json")
    parser.add_argument("--verify-links",action="store_true",help="Verify every project ID/name against its official detail API")
    args = parser.parse_args(argv)
    try:
        previous = json.loads(Path(args.output).read_text(encoding="utf-8")) if Path(args.output).exists() else None
        overrides = json.loads(Path(args.overrides).read_text(encoding="utf-8")) if Path(args.overrides).exists() else {}
        snapshot = collect_snapshot(previous=previous,overrides=overrides,raw_dir=args.raw_dir)
        if args.verify_links:
            verify_project_links(snapshot)
        write_snapshot(snapshot,args.output,args.archive_dir)
        print(json.dumps({"date":snapshot["date"],"count":len(snapshot["items"]),"SSE":snapshot["source_status"]["SSE"]["total"],"SZSE":snapshot["source_status"]["SZSE"]["total"],"warnings":len(snapshot["quality"]["detail_warnings"])},ensure_ascii=False))
        return 0
    except Exception as exc:
        print("Collection aborted; previous complete snapshot retained: " + str(exc),file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
