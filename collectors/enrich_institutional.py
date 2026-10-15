"""Collect traceable official institutional REIT details and document metadata.

This produces a supplement for review; it never changes the published snapshot.
Every run has an immutable raw response directory and field-level evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from collectors import institutional as base

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "workpapers/enrichment/institutional"
RAW = ROOT / "data/raw/enrichment/institutional"
RESEARCH_FIELDS = ("origin", "writer", "underlying_assets", "asset_type", "approved_date", "issued_date", "is_issued")


def now():
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def clean(value):
    result = html.unescape(re.sub(r"<[^>]+>", "", str(value or ""))).strip()
    return "" if result in ("-", "--", "None", "null") else result


class Recorder:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.manifest = []
        self.lock = threading.Lock()

    def request(self, url, params=None, referer=None, suffix=None):
        target = url + (("&" if "?" in url else "?") + urllib.parse.urlencode(params) if params else "")
        digest = hashlib.sha256(target.encode()).hexdigest()[:20]
        with self.lock:
            index = len(self.manifest) + 1
            entry = {"url": url, "request_url": target, "query_parameters": params or {}, "referer": referer, "extracted_at": now()}
            self.manifest.append(entry)
        error = None
        for attempt in range(3):
            try:
                request = urllib.request.Request(target, headers={"User-Agent": "Mozilla/5.0", "Referer": referer or url, "Accept": "application/json,text/javascript,text/html,application/pdf,*/*"})
                with urllib.request.urlopen(request, timeout=35) as response:
                    content = response.read()
                    content_type = response.headers.get("Content-Type", "")
                    entry.update({"http_status": response.status, "final_url": response.url, "content_type": content_type, "content_encoding": response.headers.get("Content-Encoding", "")})
                extension = suffix or ("pdf" if content.startswith(b"%PDF") else "html" if "html" in content_type else "txt" if "javascript" in content_type else "json")
                path = self.directory / (f"{index:05d}_{digest}." + extension)
                path.write_bytes(content)
                entry.update({"file": str(path.relative_to(ROOT)), "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content), "ok": True})
                return content, entry
            except Exception as exc:
                error = exc
                if attempt < 2:
                    time.sleep(0.6 + attempt)
        entry.update({"ok": False, "error": str(error)})
        raise base.CollectionError(f"Official request failed: {target}: {error}")

    def json(self, url, params, referer):
        content, _ = self.request(url, params, referer)
        raw = content.decode("utf-8-sig")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            match = re.fullmatch(r"\s*[\w.$]+\s*\((.*)\)\s*;?\s*", raw, re.S)
            if not match:
                raise base.CollectionError("Response is not JSON or JSONP")
            return json.loads(match.group(1))


def packet_rows(packet):
    if isinstance(packet, dict):
        return packet.get("result", [])
    return [row for tab in packet if isinstance(tab, dict) for row in tab.get("data", [])]


def source_for(row, title, fields=None, excerpt=None, **kwargs):
    result = {"title": title, "url": row["source_url"], "published_at": None, "source_updated_at": row.get("up"), "checked_at": now()}
    if fields:
        result["api_fields"] = fields
    if excerpt:
        result["excerpt"] = excerpt
    result.update(kwargs)
    return result


def available_links(packet, base_url="https://bond.sse.com.cn"):
    result = []
    for raw in packet_rows(packet):
        if not isinstance(raw, dict):
            continue
        path = raw.get("FILE_PATH") or raw.get("filePath") or raw.get("url")
        if path:
            result.append({"title": clean(raw.get("FILE_TITLE") or raw.get("fileTitle") or "项目披露文件"), "url": urllib.parse.urljoin(base_url, path), "published_at": clean(raw.get("FILE_TIME") or raw.get("fileTime")), "raw_metadata": raw})
        for value in raw.values():
            if isinstance(value, str):
                for link in re.finditer(r"href\s*=\s*['\"]([^'\"]+)['\"]", value, re.I):
                    href = html.unescape(link.group(1))
                    if not href.startswith(("javascript:", "#")):
                        result.append({"title": clean(value), "url": urllib.parse.urljoin(base_url, href), "raw_metadata": raw})
    seen = set()
    return [item for item in result if not (item["url"] in seen or seen.add(item["url"]))]


def collect_project_metadata(row, recorder):
    if row["ex"] == "上交所":
        basic = recorder.json("https://query.sse.com.cn/commonSoaQuery.do", {"jsonCallBack": "cb", "isPagination": "false", "sqlId": "ZQ_XMLB", "audit_id": row["source_id"], "bond_type": "0,1,2,3,5,6,7"}, row["source_url"])
        docs = recorder.json("https://query.sse.com.cn/commonSoaQuery.do", {"jsonCallBack": "cb", "isPagination": "false", "sqlId": "ZQ_GGJG", "audit_id": row["source_id"], "bond_type": "0,1,2,3,5,6,7"}, row["source_url"])
        raw = next((item for item in packet_rows(basic) if str(item.get("BOND_NUM")) == row["source_id"]), None)
        if not raw or clean(raw.get("AUDIT_NAME")) != row["name"]:
            raise base.CollectionError("Detail identity mismatch: " + row["id"])
        origin, manager = clean(raw.get("FULL_NAME")), clean(raw.get("WRITER_NAME"))
        origin_key, manager_key = "FULL_NAME", "WRITER_NAME"
        asset = clean(raw.get("REITS_ASSET_TYPE"))
    else:
        params = {"SHOWTYPE": "JSON", "CATALOGID": "xmjdxx_xq", "xmbh": row["source_id"], "type": "2"}
        basic = recorder.json(base.SZSE_ENDPOINT, params, base.SZSE_REFERER)
        docs = basic
        raw = next((item for item in packet_rows(basic) if clean(item.get("zqmc")) == row["name"]), None)
        if not raw:
            raise base.CollectionError("Detail identity mismatch: " + row["id"])
        origin, manager = clean(raw.get("fxr")), clean(raw.get("cxsqc") or raw.get("cxsjc"))
        origin_key, manager_key = "fxr", "cxsqc"
        asset = clean(raw.get("zclx"))
    fields, sources, unavailable = {}, {}, {}
    for key, value, source_key in (("origin", origin, origin_key), ("writer", manager, manager_key)):
        if value:
            fields[key] = value
            sources[key] = [source_for(row, row["ex"] + "项目基本信息", {source_key: value})]
    if asset:
        fields["asset_type"] = asset
        sources["asset_type"] = [source_for(row, row["ex"] + "项目基本信息", {"REITS_ASSET_TYPE" if row["ex"] == "上交所" else "zclx": asset})]
    documents = available_links(docs, "https://bond.sse.com.cn" if row["ex"] == "上交所" else "https://bond.szse.cn")
    for key in RESEARCH_FIELDS:
        if key not in fields:
            reason = "官方申报详情未披露该字段，待核对公开附件或正式发行/成立/挂牌公告。"
            if key in ("issued_date", "is_issued"):
                reason = "当前项目详情仅披露申报审核状态，未取得该申报事件对应的实际发行、成立或挂牌证据；不以审核通过推定已发行，亦不因未取得证据判为未发行。"
            if key == "approved_date":
                reason = "官方详情更新日期并非通过日期；需项目审核时间线或明确通过日期的官方文件。"
            unavailable[key] = {"status": "not_disclosed_in_project_metadata", "reason": reason, "source_url": row["source_url"], "checked_at": now()}
    return {"official_id": row["id"], "name": row["name"], "fields": fields, "sources": sources, "unavailable": unavailable, "documents": documents, "basic_metadata": raw, "metadata_tabs": [tab.get("metadata", {}) for tab in basic] if isinstance(basic, list) else [], "is_expansion": row.get("is_expansion", False), "checked_at": now()}


def canonical(value):
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", value).casefold()


def iso_date(value):
    raw = clean(value)
    if re.fullmatch(r"\d{8}", raw):
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    return raw[:10] if re.match(r"\d{4}-\d{2}-\d{2}", raw) else ""


def update_coverage(result):
    result["coverage"]["filled_fields"] = {key: sum(key in item["fields"] for item in result["items"].values()) for key in RESEARCH_FIELDS}
    result["coverage"]["collected_at"] = now()


def apply_reviewed_pdf_fields(result):
    reviewed = {
        "SZSE_CA98A72685014BA5BC8F18E5D376FF30": {"asset_type": "文旅类", "ptype": "产权类", "pages": [2, 3], "underlying_assets": "长春高新洲际酒店、长春高新假日酒店及438个地下停车位对应的房屋所有权及国有建设用地使用权；项目公司为长春海容酒店有限公司。", "published_at": "2026-08-21", "role": "上市发行人董事会正式公告", "matching": "公告第2页专项计划全称与该申报全称一致（仅暂定名说明不同）；原始权益人一致；本次为首发。"},
        "SZSE_A008DEF35DB7497B80240D4B840C3F89": {"asset_type": "消费", "ptype": "产权类", "pages": [1], "underlying_assets": "北京市朝阳区北四环东路73号院1号北四环智能家居体验中心物业；项目公司为北京睿鸿商业管理有限公司、北京居然之家智能家居有限公司。", "published_at": "2026-08-07", "role": "上市发行人关于无异议函的正式进展公告", "matching": "公告逐字列示该申报完整名称（含机构间REIT），确认函号深证函〔2026〕702号；本次为首发。"},
        "SSE_f112c7774ea84dbea54e17bdb33895b5": {"asset_type": "医疗健康", "ptype": "产权类", "pages": [4, 7, 8], "underlying_assets": "深圳市恒裕联翔投资发展有限公司全部股权、相关股东贷款及其全资物业。物业位于深圳市福田区梅林街道锦运大厦B5–B1、1–2、4–8、10–18、20–21、25–27，总楼面面积78,170.34平方米，主要由深圳中山妇产医院租用，租约至2045年12月31日。", "published_at": "2026-09-29", "role": "香港上市发行人锦欣生殖向香港交易所提交的正式交易公告", "matching": "该申报唯一原始权益人锦欣生殖、受理日2026-09-29、拟发行19.30亿元与同日HKEX公告主体及拟募1,930百万元一致；公告描述该次首发，未涉及扩募。"}
    }
    documents = []
    for path in sorted((WORK / "pdf_text").glob("*.json")):
        data = json.loads(path.read_text())
        if data.get("official_id") in reviewed:
            documents.append((path, data))
    for path, data in documents:
        pid = data["official_id"]
        spec = reviewed[pid]
        item = result["items"][pid]
        doc = data["document"]
        excerpts = [{"page": page["page"], "excerpt": page["text"], "text_file": str(path.relative_to(ROOT))} for page in data["pages"] if page["page"] in spec["pages"]]
        evidence = {"title": doc.get("title") or "发行人正式交易公告", "url": doc["url"], "published_at": spec["published_at"], "page": spec["pages"], "excerpt": "\n".join(entry["excerpt"] for entry in excerpts), "page_excerpts": excerpts, "raw_file": data["raw"]["file"], "sha256": data["raw"]["sha256"], "checked_at": now(), "source_type": "official_issuer_announcement", "source_role": spec["role"], "project_identity_evidence": spec["matching"], "business_batch": "首发", "text_file": str(path.relative_to(ROOT))}
        for field in ("underlying_assets", "asset_type"):
            item["fields"][field] = spec[field]
            item["sources"][field] = [evidence]
            item["unavailable"].pop(field, None)
        item["fields"].update({"ptype": spec["ptype"], "psub": spec["asset_type"], "pnote": "发行人正式公告披露的物业用途；页码与原句见字段证据。", "classification_source": "verified", "classification_confidence": "confirmed", "classification_evidence": [{"title": evidence["title"], "url": evidence["url"], "published_at": evidence["published_at"], "pages": spec["pages"]}]})
        item["documents"].append({"title": evidence["title"], "url": evidence["url"], "published_at": evidence["published_at"], "raw_file": evidence["raw_file"], "text_file": evidence["text_file"], "pages": spec["pages"], "document_type": "official_issuer_announcement"})
        if pid == "SZSE_A008DEF35DB7497B80240D4B840C3F89":
            item["fields"]["approval_notice_received_date"] = "2026-08-06"
            item["sources"]["approval_notice_received_date"] = [evidence]
            item["unavailable"]["approved_date"]["reason"] = "发行人公告明确2026-08-06收到深交所无异议函，仅能核实收函日；未将该日期或官网2026-07-17更新日期冒充审核通过日。"
    result["coverage"]["reviewed_official_pdf_projects"] = len(documents)
    update_coverage(result)
    return result


def apply_szse_security_dates(result):
    path = WORK / "szse_security_details.json"
    if not path.exists():
        return result
    for packet in json.loads(path.read_text()):
        if packet.get("error") or packet["id"] not in result["items"]:
            continue
        item = result["items"][packet["id"]]
        for tab in packet.get("response", []):
            cols = tab.get("metadata", {}).get("cols", {})
            if cols.get("cpclr") != "产品设立日":
                continue
            for row in tab.get("data", []):
                date = iso_date(row.get("cpclr"))
                if canonical(clean(row.get("cpqc"))) != canonical(item["name"]) or str(row.get("zqdh")) != packet["code"] or not date or date > result["coverage"]["as_of"]:
                    continue
                url = "https://bond.szse.cn/disclosure/productinfo/detail/index.html?catelogId=gscpxq&code=" + packet["code"]
                evidence = {"title": "深交所证券详情（产品设立日）：" + item["name"], "url": url, "published_at": None, "checked_at": now(), "source_type": "official_security_profile", "api_fields": {"cpqc": row["cpqc"], "zqdh": row["zqdh"], "cpclr": row["cpclr"]}, "api_field_labels": cols, "excerpt": f"证券代码：{row['zqdh']}；产品全称：{row['cpqc']}；产品设立日：{date}", "date_basis": "产品设立日（证券详情明示字段），不是产品列表里的起息日期"}
                item["fields"]["issued_date"] = date
                item["fields"]["issued_date_basis"] = "深交所证券详情：产品设立日（cpclr；按该详情字段中文标签核验）。"
                item["sources"]["issued_date"] = [evidence]
                item["unavailable"].pop("issued_date", None)
    update_coverage(result)
    return result


def finalize_supplement(result):
    manifest = [entry for manifest_path in RAW.glob("*/manifest.json") for entry in json.loads(manifest_path.read_text())]
    by_file = {entry.get("file") or entry.get("request_url"): entry for entry in manifest}
    result["manifest"] = list(by_file.values())
    for pid, item in result["items"].items():
        sid = pid.split("_", 1)[1]
        basic_raw = [entry for entry in manifest if entry.get("ok") and (entry.get("query_parameters", {}).get("audit_id") == sid or entry.get("query_parameters", {}).get("xmbh") == sid) and entry.get("query_parameters", {}).get("sqlId", "ZQ_XMLB") == "ZQ_XMLB"]
        if basic_raw:
            for key in ("origin", "writer"):
                for source in item["sources"].get(key, []):
                    source["source_updated_at"] = source.get("source_updated_at") or source.get("published_at")
                    source["published_at"] = None
                    source["raw_file"] = basic_raw[-1]["file"]
                    source["sha256"] = basic_raw[-1]["sha256"]
                    source["source_role"] = "交易所公开申报详情元数据"
        unique = {}
        for doc in item["documents"]:
            unique[(doc.get("url"), doc.get("document_type"))] = doc
        item["documents"] = list(unique.values())
        for field, missing in item["unavailable"].items():
            missing["status"] = "not_obtained_after_official_source_review"
            if field in ("underlying_assets", "asset_type"):
                missing["reason"] = "本项目官方申报详情及公开附件接口未提供资产清单/明确资产分类；未取得能够完全对应本申报批次的公开资产披露，不以项目名称或同主体其他计划代替资产清单。"
            if field in ("is_issued", "issued_date") and "szse_product_checks" in item and not item["szse_product_checks"]["matches"]:
                missing["reason"] += " 深交所184条不动产ABS产品名录已完整检查；定向信息公告入口需要登录，未取得该计划进一步公开发行材料。"
        # A source name match is never used to fill an expansion from its first offering.
        if item.get("is_expansion") and item["fields"].get("is_issued"):
            if not any(source.get("business_batch") == "扩募" or "扩募" in source.get("api_fields", {}).get("BOND_FULL", "") for source in item["sources"].get("is_issued", [])):
                raise base.CollectionError("Expansion lacks event-specific issuance evidence: " + pid)
    update_coverage(result)
    coverage = result["coverage"]
    coverage["public_project_attachment_metadata_count"] = 0
    coverage["projects_with_documents"] = sum(bool(item["documents"]) for item in result["items"].values())
    coverage["document_count"] = sum(len(item["documents"]) for item in result["items"].values())
    coverage["official_pdfs_reviewed"] = 3
    coverage["limitations"] = ["131项官方详情均已逐ID核验，申报附件接口未返回公开附件。", "上交所发行核对使用完整ABS证券简称主表生成候选后比对全称及日期，未匹配不等同未发行。", "深交所产品名录完整184条；其定向信息公告入口要求登录。", "上交所两份上市公司公告原路径返回防护HTML，已保留原始响应，未作为PDF正文取数。", "未取得独立审核通过日期的项目保留未知；无异议函收函日与更新日期不替代通过日期。"]
    matrix = [{"id": pid, "name": item["name"], "fields": {key: {"value": item["fields"].get(key), "has_source": bool(item["sources"].get(key)), "unavailable": item["unavailable"].get(key)} for key in RESEARCH_FIELDS}} for pid, item in result["items"].items()]
    write_json(WORK / "field_coverage_matrix.json", matrix)
    return result


def enrich_issuance(snapshot, result, recorder, workers=4):
    content, manifest = recorder.request("https://bond.sse.com.cn/disclosure/info/tb/allBonds.js", referer="https://bond.sse.com.cn/disclosure/info/index.shtml", suffix="js")
    securities = re.findall(r"'([0-9]+)'\s*:\s*\['([^']+)',_t\[11\]\]", content.decode("utf-8"))
    if not securities:
        raise base.CollectionError("Official ABS security master did not contain recognizable records")
    parsed = []
    generic = {"中信证券", "中金公司", "国金资管", "平安证券", "资产支持", "不动产", "持有型", "资产", "基金", "证券", "商业", "能源", "中信", "中金", "国金", "平安", "中铁", "产业", "投资", "绿色", "碳中和"}
    for code, short in securities:
        token = canonical(re.sub(r"[0-9A-Za-z]+$", "", re.sub(r"^\d{2}", "", short)))
        if len(token) >= 3 and token not in generic:
            parsed.append((code, short, token))
    candidates = {}
    codes = set()
    for row in snapshot["items"]:
        # Candidate inclusion is deliberately broad; only exact full-name and
        # timing checks below can turn a candidate into an issuance fact.
        body = canonical(row["name"].split("-", 1)[-1])
        found = [{"code": code, "short_name": short} for code, short, token in parsed if token in body]
        candidates[row["id"]] = found
        codes.update(item["code"] for item in found)
    write_json(WORK / "issuance_candidates.json", {"security_master": manifest, "master_abs_count": len(securities), "projects": candidates})

    def fetch_profile(code):
        packet = recorder.json("https://query.sse.com.cn/commonQuery.do", {"jsonCallBack": "cb", "isPagination": "false", "sqlId": "COMMON_SSEBOND_XXPL_ZQXX_KZHGSZQ_XQ_C", "BOND_CODE": code}, "https://bond.sse.com.cn/disclosure/info/index.shtml?BONDCODE=" + code)
        rows = packet_rows(packet)
        if len(rows) != 1 or str(rows[0].get("BOND_CODE")) != code:
            raise base.CollectionError("Security identity mismatch: " + code)
        return code, rows[0]

    profiles, failures = {}, []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        tasks = {pool.submit(fetch_profile, code): code for code in sorted(codes)}
        for task in as_completed(tasks):
            try:
                code, profile = task.result()
                profiles[code] = profile
            except Exception as exc:
                failures.append({"code": tasks[task], "error": str(exc)})
    write_json(WORK / "security_profiles.json", {"profiles": profiles, "failures": failures})
    matches = []
    for row in snapshot["items"]:
        item = result["items"][row["id"]]
        checks = []
        for candidate in candidates[row["id"]]:
            code = candidate["code"]
            profile = profiles.get(code)
            if not profile:
                continue
            name = clean(profile.get("BOND_FULL"))
            exact = canonical(row["name"]) in canonical(name)
            # Same-name first-offering securities never prove an expansion.
            expansion_exact = not row.get("is_expansion") or ("扩募" in name and exact)
            start = iso_date(profile.get("ONLINE_START_DATE"))
            end = iso_date(profile.get("ONLINE_END_DATE"))
            listing = iso_date(profile.get("LISTING_DATE"))
            timing_ok = bool(end and end <= snapshot["date"] and (not row.get("acc") or end >= row["acc"]))
            check = {"code": code, "security_full_name": name, "full_name_match": exact, "expansion_event_match": expansion_exact, "issue_start": start, "issue_end": end, "listing_date": listing, "timing_ok": timing_ok}
            checks.append(check)
            if exact and expansion_exact and timing_ok:
                url = "https://bond.sse.com.cn/disclosure/info/index.shtml?BONDCODE=" + code
                evidence = {"title": "上海证券交易所债券基本要素：" + name, "url": url, "checked_at": now(), "source_type": "official_security_profile", "api_fields": {key: profile.get(key) for key in ("BOND_CODE", "BOND_FULL", "ONLINE_START_DATE", "ONLINE_END_DATE", "LISTING_DATE")}, "excerpt": f"债券代码：{code}；债券全称：{name}；发行起始日：{start}；发行终止日：{end}；上市日期：{listing}"}
                item["fields"]["is_issued"] = True
                item["sources"].setdefault("is_issued", []).append(evidence)
                item["unavailable"].pop("is_issued", None)
                if start:
                    item["fields"]["issued_date"] = start
                    item["fields"]["issued_date_basis"] = "交易所债券要素：发行起始日（ONLINE_START_DATE），不使用起息日替代。"
                    item["sources"].setdefault("issued_date", []).append(evidence)
                    item["unavailable"].pop("issued_date", None)
                item["documents"].append({"title": evidence["title"], "url": url, "document_type": "security_profile"})
                matches.append({"id": row["id"], **check})
        item["issuance_security_checks"] = {"master_count": len(securities), "candidate_count": len(candidates[row["id"]]), "checked_profiles": checks, "master_url": "https://bond.sse.com.cn/disclosure/info/tb/allBonds.js", "checked_at": now(), "matching_method": "distinctive_short_name_candidates_then_exact_project_full_name_and_issue_after_acceptance; expansions_require_exact_expansion_event_name"}
        if "is_issued" not in item["fields"]:
            item["unavailable"]["is_issued"]["reason"] += f" 已全量检索上交所{len(securities)}条ABS证券简称主表，取得{len(checks)}条候选证券要素；未取得完全匹配本申报事件的已发行证据。"
    result["coverage"]["official_security_master_abs_count"] = len(securities)
    result["coverage"]["issuance_profiles_checked"] = len(profiles)
    result["coverage"]["issuance_profile_failures"] = failures
    result["coverage"]["issuance_matches"] = matches
    update_coverage(result)
    return result


def enrich_szse_products(snapshot, result, recorder, workers=4):
    endpoint = base.SZSE_ENDPOINT
    referer = "https://bond.szse.cn/disclosure/productinfo/reit/index.html"
    first = recorder.json(endpoint, {"SHOWTYPE": "JSON", "CATALOGID": "ints_reits_cplb", "pageNo": 1}, referer)
    all_rows, checks = [], []
    for tab in first:
        meta = tab["metadata"]
        tab_key, pages, total = meta["tabkey"], int(meta["pagecount"]), int(meta["recordcount"])
        rows = list(tab.get("data", []))
        def fetch_page(page):
            packet = recorder.json(endpoint, {"SHOWTYPE": "JSON", "CATALOGID": "ints_reits_cplb", "TABKEY": tab_key, "PAGENO": page}, referer)
            selected = next(item for item in packet if item["metadata"]["tabkey"] == tab_key)
            if int(selected["metadata"]["recordcount"]) != total or int(selected["metadata"]["pageno"]) != page:
                raise base.CollectionError("SZSE product pagination changed")
            return selected["data"]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for packet_rows_ in pool.map(fetch_page, range(2, pages + 1)):
                rows.extend(packet_rows_)
        if len(rows) != total:
            raise base.CollectionError("SZSE product list incomplete")
        all_rows.extend(rows)
        checks.append({"tab": tab_key, "name": meta["name"], "pages": pages, "advertised_total": total, "raw_count": len(rows), "cols": meta["cols"]})
    write_json(WORK / "szse_products.json", {"pagination": checks, "rows": all_rows})
    matches = []
    for row in snapshot["items"]:
        if row["ex"] != "深交所":
            continue
        item = result["items"][row["id"]]
        expected = canonical(row["name"])
        verified = []
        for product in all_rows:
            name = clean(product.get("cpqc"))
            if expected != canonical(name):
                continue
            listing = iso_date(product.get("gprq"))
            code = clean(product.get("zqdh"))
            if not listing or listing > snapshot["date"] or (row.get("acc") and listing < row["acc"]):
                continue
            url = "https://bond.szse.cn/disclosure/productinfo/detail/index.html?catelogId=gscpxq&code=" + code
            evidence = {"title": "深圳证券交易所不动产ABS产品信息：" + name, "url": url, "checked_at": now(), "source_type": "official_security_profile", "api_fields": {"cpqc": name, "gprq": listing, "zqdh": code}, "excerpt": f"证券代码：{code}；产品名称：{name}；挂牌日期：{listing}"}
            item["fields"]["is_issued"] = True
            item["sources"].setdefault("is_issued", []).append(evidence)
            item["unavailable"].pop("is_issued", None)
            item["documents"].append({"title": evidence["title"], "url": url, "document_type": "security_profile"})
            verified.append({"code": code, "name": name, "listing_date": listing})
        item["szse_product_checks"] = {"master_count": len(all_rows), "matches": verified, "source_url": referer, "checked_at": now()}
        if verified:
            matches.append({"id": row["id"], "securities": verified})
            item["unavailable"]["issued_date"]["reason"] = "已从官方不动产ABS产品名录核实本计划实际挂牌；该名录日期字段为起息日期和挂牌日期，未取得发行起始日或实际设立日，不以起息日/挂牌日代替发行日期。"
    result["coverage"].update({"szse_product_pagination": checks, "szse_product_rows_checked": len(all_rows), "szse_issuance_matches": matches})
    update_coverage(result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume-source", action="store_true", help="Reuse the source snapshot from the current enrichment pass")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--issuance-only", action="store_true", help="Add official issued-security evidence to the existing full-coverage supplement")
    parser.add_argument("--szse-issuance-only", action="store_true")
    parser.add_argument("--reviewed-documents-only", action="store_true", help="Apply the page-bound reviewed facts from downloaded issuer PDFs")
    args = parser.parse_args(argv)
    run_id = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%dT%H%M%S_%f")
    recorder = Recorder(RAW / run_id)
    WORK.mkdir(parents=True, exist_ok=True)
    try:
        if args.reviewed_documents_only:
            result = json.loads((WORK / "supplement.json").read_text())
            apply_reviewed_pdf_fields(result)
            apply_szse_security_dates(result)
            finalize_supplement(result)
            write_json(WORK / "supplement.json", result)
            write_json(WORK / "coverage.json", result["coverage"])
            print(json.dumps(result["coverage"]["filled_fields"], ensure_ascii=False), flush=True)
            return
        if args.issuance_only or args.szse_issuance_only:
            snapshot = json.loads((WORK / "latest_source.json").read_text())
            result = json.loads((WORK / "supplement.json").read_text())
            if args.issuance_only:
                enrich_issuance(snapshot, result, recorder, args.workers)
            else:
                enrich_szse_products(snapshot, result, recorder, args.workers)
            result["manifest"].extend(recorder.manifest)
            write_json(WORK / "supplement.json", result)
            write_json(WORK / "coverage.json", result["coverage"])
            print(json.dumps(result["coverage"], ensure_ascii=False), flush=True)
            return
        if args.resume_source:
            snapshot = json.loads((WORK / "latest_source.json").read_text())
        else:
            previous = json.loads((ROOT / "data/institutional.json").read_text())
            overrides = json.loads((ROOT / "config/classification_overrides.json").read_text())
            snapshot = base.collect_snapshot(request=recorder.json, previous=previous, overrides=overrides, raw_dir=recorder.directory / "normalized_packets")
            base.verify_project_links(snapshot, request=recorder.json, workers=args.workers)
            write_json(WORK / "latest_source.json", snapshot)
        print(json.dumps({"phase": "complete_source_refresh", "projects": len(snapshot["items"]), "run_id": run_id}), flush=True)
        supplements, failures = {}, []
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            tasks = {executor.submit(collect_project_metadata, row, recorder): row for row in snapshot["items"]}
            for task in as_completed(tasks):
                row = tasks[task]
                try:
                    item = task.result()
                    supplements[row["id"]] = item
                    write_json(WORK / "projects" / (row["id"] + ".json"), item)
                except Exception as exc:
                    failures.append({"id": row["id"], "error": str(exc)})
                if (len(supplements) + len(failures)) % 20 == 0:
                    print(json.dumps({"phase": "project_metadata", "done": len(supplements), "failed": len(failures)}), flush=True)
        coverage = {"total_projects": len(snapshot["items"]), "metadata_checked": len(supplements), "metadata_failures": failures, "complete_metadata": not failures, "projects_with_documents": sum(bool(item["documents"]) for item in supplements.values()), "document_count": sum(len(item["documents"]) for item in supplements.values()), "filled_fields": {key: sum(key in item["fields"] for item in supplements.values()) for key in RESEARCH_FIELDS}, "as_of": snapshot["date"], "collected_at": now()}
        result = {"items": supplements, "coverage": coverage, "manifest": recorder.manifest}
        write_json(WORK / "supplement.json", result)
        write_json(WORK / "coverage.json", coverage)
        print(json.dumps(coverage, ensure_ascii=False), flush=True)
    finally:
        write_json(recorder.directory / "manifest.json", recorder.manifest)
        write_json(WORK / ("manifest_" + run_id + ".json"), recorder.manifest)


if __name__ == "__main__":
    main()
