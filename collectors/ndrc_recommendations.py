"""Collect the complete NDRC public REIT recommendation register.

The source does not expose a project ID. NDRC_<hash> is a derived identity of
the exact project name, submitting region/central enterprise and recommendation
date; it is never represented as an official ID. The HTTPS hostname below
serves the public IP page with a valid certificate, so no TLS bypass is used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import ssl
import urllib.error
import urllib.request
from collections import Counter
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from collectors.http_policy import PACER, backoff

ROOT = Path(__file__).resolve().parents[1]
SOURCE_URL = "https://reitsgl.tzxm.gov.cn:8881/atom-ui/reits/#/reits/project-publicity/project-publicity-list"
ORIGINAL_SOURCE_URL = "https://59.252.66.79:8881/atom-ui/reits/#/reits/project-publicity/project-publicity-list"
API_URL = "https://reitsgl.tzxm.gov.cn:8881/atom/api/v1/reits/getReitsPublicInfoList"
PAGE_SIZE = 50
MAX_PAGES = 1000
RAW_FIELDS = ("reitsProName", "mainDeclareUnit", "industry", "fundMoney", "reportRecommendTime")
BUSINESS_TYPES = {"首发", "扩募", "新购入", "待核实"}
MATCH_STATUSES = {"confirmed", "candidate", "unmatched"}


class CollectionError(ValueError):
    """Reject an incomplete, inconsistent, or malformed source response."""


def now_shanghai():
    return datetime.now(ZoneInfo("Asia/Shanghai"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def relative(path):
    path = Path(path).resolve()
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def query_params(page_num, page_size=PAGE_SIZE):
    return {"pageSize": page_size, "pageNum": page_num, "reitsProName": "", "industry": "",
            "mainDeclareUnit": "", "startFundMoney": "", "endFundMoney": "",
            "reportRecommendStartTime": "", "reportRecommendEndTime": ""}


def stable_id(name, applicant_region, recommended_date):
    identity = json.dumps([name, applicant_region, recommended_date], ensure_ascii=False, separators=(",", ":"))
    return "NDRC_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]


def normalize_record(row, now, previous=None, baseline=True):
    if not isinstance(row, dict) or any(field not in row for field in RAW_FIELDS):
        raise CollectionError("Recommendation lacks required official fields")
    if any(not isinstance(row[key], str) for key in ("reitsProName", "mainDeclareUnit", "industry", "reportRecommendTime")):
        raise CollectionError("Invalid official recommendation text field types")
    name, region = str(row["reitsProName"] or "").strip(), str(row["mainDeclareUnit"] or "").strip()
    industry = str(row["industry"] or "").strip()
    value = row["fundMoney"]
    if not name or not region or not industry:
        raise CollectionError("Recommendation lacks project, submitter or industry")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise CollectionError("Invalid official proposed fund amount")
    try:
        day = datetime.strptime(str(row["reportRecommendTime"]), "%Y-%m-%d %H:%M:%S").date().isoformat()
    except (TypeError, ValueError) as exc:
        raise CollectionError("Invalid official recommendation date") from exc
    if day > now.date().isoformat():
        raise CollectionError("Future recommendation date")
    identity = stable_id(name, region, day)
    old = (previous or {}).get(identity, {})
    stamp = now.isoformat(timespec="seconds")
    return {"id": identity, "source_id": None, "name": name, "applicant_region": region,
            "industry_official": industry, "proposed_fund_amount_yi": value, "recommended_date": day,
            "first_seen_at": old.get("first_seen_at") or stamp, "last_seen_at": stamp,
            "discovery_type": old.get("discovery_type") or ("baseline" if baseline else "new"),
            "business_type": "新购入" if "新购入" in name else "待核实",
            "match_status": "unmatched", "relations": [], "candidates": [], "source_url": SOURCE_URL}


class SourceReader:
    """Byte-preserve each successful response and its exact request parameters."""
    def __init__(self, raw_dir, now=None):
        self.raw_dir, self.now = Path(raw_dir), now or now_shanghai()
        self.raw_dir.mkdir(parents=True, exist_ok=False)
        self.manifest = []

    def request(self, page_num, page_size=PAGE_SIZE):
        params = query_params(page_num, page_size)
        body = json.dumps(params, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        req = urllib.request.Request(API_URL, data=body, headers={
            "Content-Type": "application/json", "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; REITsResearchDashboard/1.0)",
            "Referer": SOURCE_URL})
        for attempt in range(3):
            PACER.wait(API_URL)
            try:
                with urllib.request.urlopen(req, timeout=45, context=ssl.create_default_context()) as response:
                    raw, status = response.read(), response.status
                break
            except (OSError, urllib.error.URLError) as exc:
                if attempt == 2:
                    raise CollectionError("NDRC request failed: " + str(exc)) from exc
                backoff(API_URL, exc, attempt)
        path = self.raw_dir / f"page{page_num:04d}.json"
        if path.exists():
            raise CollectionError("Refusing to overwrite existing Raw response")
        path.write_bytes(raw)
        entry = {"url": API_URL, "method": "POST", "params": params,
                 "retrieved_at": now_shanghai().isoformat(timespec="seconds"), "status": status,
                 "tls_verified": True, "raw_path": relative(path),
                 "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        self.manifest.append(entry)
        write_json(self.raw_dir / "requests.json", self.manifest)
        try:
            return json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CollectionError("NDRC response is not JSON") from exc


def collect_pages(reader, page_size=PAGE_SIZE):
    pages, expected_total, expected_pages = [], None, None
    for page_num in range(1, MAX_PAGES + 1):
        response = reader.request(page_num, page_size)
        data = response.get("data") if isinstance(response, dict) else None
        if not isinstance(response, dict) or response.get("code") != "SYS.200" or not isinstance(data, dict) or not isinstance(data.get("list"), list):
            raise CollectionError("NDRC source did not return a successful list")
        total, count = data.get("total"), data.get("pages")
        if any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in (total, count)):
            raise CollectionError("Invalid or empty NDRC source totals")
        calculated_pages = math.ceil(total / page_size)
        if count != calculated_pages or count > MAX_PAGES:
            raise CollectionError("NDRC pagination metadata does not reconcile")
        if data.get("pageNum") != page_num or data.get("pageSize") != page_size:
            raise CollectionError("NDRC ignored requested pagination")
        if expected_total is None:
            expected_total, expected_pages = total, count
        elif (total, count) != (expected_total, expected_pages):
            raise CollectionError("NDRC source changed during pagination")
        expected_size = min(page_size, total - (page_num - 1) * page_size)
        if len(data["list"]) != expected_size or data.get("size") != expected_size:
            raise CollectionError("NDRC page row count does not reconcile")
        pages.append(response)
        if page_num == expected_pages:
            break
    records = [deepcopy(row) for page in pages for row in page["data"]["list"]]
    if len(records) != expected_total:
        raise CollectionError("NDRC full pagination total does not reconcile")
    return records, {"official_total": expected_total, "pages": expected_pages,
                     "page_size": page_size, "raw_row_count": len(records), "complete": True,
                     "pages_checked": [{"page_num": page["data"]["pageNum"], "row_count": len(page["data"]["list"])} for page in pages]}


def build_snapshot(records, collection, previous=None, now=None, source_manifest=None):
    now, previous = now or now_shanghai(), previous or {}
    old = {row["id"]: row for row in previous.get("items", [])}
    baseline = not previous.get("coverage", {}).get("complete")
    items = [normalize_record(row, now, old, baseline) for row in records]
    identities = [row["id"] for row in items]
    if len(set(identities)) != len(identities):
        raise CollectionError("Duplicate derived recommendation identity")
    if collection.get("complete") is not True or len(items) != collection.get("official_total"):
        raise CollectionError("Complete reconciled collection required")
    missing = sorted(set(old) - set(identities))
    if missing:
        # A disappearing row may be an official revision, but must be reviewed
        # before it can remove a project from the published complete history.
        raise CollectionError("Recommendations disappeared; retain prior snapshot and review: " + ", ".join(missing))
    changed_fields = ("name", "applicant_region", "industry_official", "proposed_fund_amount_yi", "recommended_date")
    changed = [{"id": row["id"], "fields": {key: {"before": old[row["id"]].get(key), "after": row.get(key)}
                for key in changed_fields if row.get(key) != old[row["id"]].get(key)}} for row in items if row["id"] in old]
    changed = [row for row in changed if row["fields"]]
    dates = sorted(row["recommended_date"] for row in items)
    latest = dates[-1]
    raw_amount_sum = sum((Decimal(str(row["fundMoney"])) for row in records), Decimal(0))
    normalized_amount_sum = sum((Decimal(str(row["proposed_fund_amount_yi"])) for row in items), Decimal(0))
    freshness = {"series": "国家发展改革委向中国证监会推荐基础设施REITs项目名单", "source": SOURCE_URL,
                 "latest_available_date": latest, "checked_at": now.isoformat(timespec="seconds"),
                 "expected_latest_date": None, "update_frequency": "不定期公开；未披露固定发布日程",
                 "is_lagging": None, "days_since_latest_record": (now.date() - datetime.strptime(latest, "%Y-%m-%d").date()).days,
                 "reason": "公开接口全量查询返回的最新推荐日期；页面未披露固定更新频率，无法据固定日程判断滞后",
                 "treatment": "保留全量最新公开名单，并展示采集时点和最新推荐日期", "revision_status": "公开名单当前版本；未披露初值或修订标识"}
    snapshot = {"schema_version": 1, "date": now.date().isoformat(), "updated_at": now.isoformat(timespec="seconds"),
                "source_status": {"NDRC": {"ok": True, "complete": True, "updated_at": now.isoformat(timespec="seconds"),
                    "latest_recommended_date": latest, "source_url": SOURCE_URL, "api_url": API_URL, "tls_verified": True}},
                "coverage": dict(collection, item_count=len(items), earliest_recommended_date=dates[0], latest_recommended_date=latest,
                    population="国家发展改革委向中国证监会推荐的基础设施REITs项目公开名单", amount_unit="亿元",
                    amount_basis="拟发售基金总额；不是实际发行金额", applicant_basis="主申报地方／中央企业；不是资产所在地"),
                "changes": {"baseline": baseline, "new_ids": [] if baseline else sorted(set(identities) - set(old)),
                    "changed_ids": [row["id"] for row in changed], "field_changes": changed, "missing_ids": []},
                "quality": {"duplicate_ids": [], "missing_required_fields": [], "raw_to_normalized_count_difference": 0,
                    "raw_amount_checksum_yi": str(raw_amount_sum), "normalized_amount_checksum_yi": str(normalized_amount_sum),
                    "raw_to_normalized_amount_difference_yi": str(normalized_amount_sum - raw_amount_sum),
                    "amount_checksum_note": "逐笔金额校验和，仅用于Raw与计算层勾稽；跨首发和新购入批次，不作为市场规模",
                    "freshness": [freshness], "identity_basis": "derived_sha256_exact_name_applicant_date",
                    "identity_note": "源接口无官方项目ID；派生ID由项目名称、主申报地方／中央企业及推荐日期生成；行业和金额变化不改变ID",
                    "unmatched_is_not_forecast": "未匹配表示当前交易所来源尚未找到已确认对应记录"},
                "source_versions": source_manifest or [],
                "items": sorted(items, key=lambda row: (row["recommended_date"], row["id"]), reverse=True)}
    return snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "data/ndrc_recommendations.json")
    parser.add_argument("--public-input", type=Path, default=ROOT / "data/public_reits.json")
    parser.add_argument("--work-dir", type=Path, default=ROOT / "workpapers/ndrc")
    parser.add_argument("--overrides", type=Path, default=ROOT / "config/ndrc_exchange_links.json")
    parser.add_argument("--reuse-raw", type=Path, help="Replay a saved Raw directory with requests.json")
    parser.add_argument("--collect-only", action="store_true", help="Write collection workpapers only, without matching or publishing")
    args = parser.parse_args()
    now = now_shanghai()
    run_id = now.strftime("%Y%m%d-%H%M%S-%f")
    if args.reuse_raw:
        raw_dir = args.reuse_raw
        manifest = json.loads((raw_dir / "requests.json").read_text(encoding="utf-8"))

        class SavedReader:
            def request(self, page_num, page_size):
                entries = [row for row in manifest if row["params"]["pageNum"] == page_num]
                if len(entries) != 1 or entries[0]["params"] != query_params(page_num, page_size):
                    raise CollectionError("Saved Raw requests do not reproduce full query")
                entry = entries[0]
                path = ROOT / entry["raw_path"]
                if sha256(path) != entry["sha256"]:
                    raise CollectionError("Saved Raw hash mismatch")
                return json.loads(path.read_bytes())

        reader = SavedReader()
        collected_at = manifest[0]["retrieved_at"]
        now = datetime.fromisoformat(collected_at)
    else:
        raw_dir = args.raw_dir or ROOT / "data/raw/ndrc" / run_id
        reader = SourceReader(raw_dir, now)
    records, collection = collect_pages(reader)
    if not args.reuse_raw:
        manifest = reader.manifest
    previous = json.loads(args.output.read_text(encoding="utf-8")) if args.output.exists() else {}
    snapshot = build_snapshot(records, collection, previous, now, manifest)
    args.work_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.work_dir / "collection_normalized.json", snapshot["items"])
    write_json(args.work_dir / "collection_audit.json", {"generated_at": now_shanghai().isoformat(timespec="seconds"),
        "source_collected_at": now.isoformat(timespec="seconds"),
        "coverage": snapshot["coverage"], "freshness": snapshot["quality"]["freshness"],
        "quality": snapshot["quality"], "changes": snapshot["changes"], "raw_manifest": manifest})
    run_manifest = {"generated_at": now_shanghai().isoformat(timespec="seconds"),
                    "source_collected_at": now.isoformat(timespec="seconds"), "source_url": SOURCE_URL,
                    "original_user_url": ORIGINAL_SOURCE_URL, "api_url": API_URL, "tls_verified": True,
                    "collection": collection, "requests": manifest, "normalization": {
                        "identity": snapshot["quality"]["identity_note"],
                        "date": "reportRecommendTime按源日期提取YYYY-MM-DD，未做时区偏移",
                        "text": "仅在计算层去除字段首尾空格，Raw保留原值", "amount": "保留fundMoney数值，单位亿元，无换算"}}
    if args.collect_only:
        write_json(ROOT / "data/source_manifest/ndrc" / (run_id + ".json"), run_manifest)
        print(json.dumps({"ok": True, "collect_only": True, **collection}, ensure_ascii=False))
        return
    from collectors.ndrc_matching import match_recommendations
    from scripts.validate_ndrc_data import validate
    public = json.loads(args.public_input.read_text(encoding="utf-8"))
    overrides = json.loads(args.overrides.read_text(encoding="utf-8")) if args.overrides.exists() else None
    matching_now = now_shanghai()
    snapshot["matching_updated_at"] = matching_now.isoformat(timespec="seconds")
    snapshot["items"], matching_audit = match_recommendations(snapshot["items"], public, overrides=overrides, now=matching_now)
    if matching_audit.get("unused_review_ids"):
        raise CollectionError("Reviewed recommendation IDs no longer exist in the complete source")
    snapshot["quality"]["match_statuses"] = dict(Counter(row["match_status"] for row in snapshot["items"]))
    snapshot["quality"]["business_types"] = dict(Counter(row["business_type"] for row in snapshot["items"]))
    snapshot["source_versions"].append({"path": relative(args.public_input), "sha256": sha256(args.public_input),
                                        "date": public.get("date"), "updated_at": public.get("updated_at")})
    if args.overrides.exists():
        snapshot["source_versions"].append({"kind": "reviewed_matching_config", "path": relative(args.overrides),
                                            "sha256": sha256(args.overrides)})
    validation = validate(snapshot, public)
    write_json(args.work_dir / "matching_audit.json", matching_audit)
    write_json(args.work_dir / "collection_validation.json", validation)
    reviewed_path = args.work_dir / "collection_reviewed_snapshot.json"
    write_json(reviewed_path, snapshot)
    run_manifest.update(public_snapshot={"path": relative(args.public_input), "sha256": sha256(args.public_input)},
                        reviewed_workpaper={"path": relative(reviewed_path), "sha256": sha256(reviewed_path)},
                        normalized_workpaper={"path": relative(args.work_dir / "collection_normalized.json"),
                                              "sha256": sha256(args.work_dir / "collection_normalized.json")},
                        match_review={"path": relative(args.overrides), "sha256": sha256(args.overrides)} if args.overrides.exists() else None,
                        output_path=relative(args.output), validation=validation)
    run_manifest["snapshot_sha256"] = sha256(reviewed_path)
    write_json(ROOT / "data/source_manifest/ndrc" / (run_id + ".json"), run_manifest)
    # Replace the public snapshot only after full pagination, matching and validation.
    write_json(args.output, snapshot)
    write_json(ROOT / "snapshots/ndrc" / (run_id + ".json"), snapshot)
    print(json.dumps(validation, ensure_ascii=False))


if __name__ == "__main__":
    main()
