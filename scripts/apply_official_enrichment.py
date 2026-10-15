"""Review official disclosure supplements, then generate both site snapshots.

The exchange lists control status. PDF supplements can only update the declared
research fields on an exact event ID; first-offering data is never used to fill
an expansion. Original candidate evidence stays in the workpapers.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import sys
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from collectors.project_fields import PUBLIC_RESEARCH_FIELDS, apply_field_scope
from collectors.public_reits import build_snapshot, official_url, write_json, sync_offering_phase
from collectors.institutional import update_classification_quality, _inherit_classification, CLASSIFICATION_FIELDS
from scripts.validate_data import validate as validate_institutional
from scripts.validate_public_data import validate as validate_public

PUBLIC_FIELDS = set(PUBLIC_RESEARCH_FIELDS) | {"underlying_assets", "asset_type", "offering_start_date", "offering_end_date", "established_date"}
INSTITUTIONAL_FIELDS = {"origin", "writer", "underlying_assets", "asset_type", "approved_date", "issued_date", "is_issued"}
PUBLIC_TARGETS = tuple(PUBLIC_RESEARCH_FIELDS) + ("underlying_assets", "asset_type")
INSTITUTIONAL_TARGETS = tuple(sorted(INSTITUTIONAL_FIELDS))
AVAILABILITY = {"not_disclosed", "not_available", "not_applicable", "unverified", "pending", "conflict"}
DISCLOSURE_HOSTS = set(json.loads((ROOT / "config/official_disclosure_hosts.json").read_text())["reviewed_hosts"])


def present(value):
    return value is not None and value != "" and value != []


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def reviewed_source(source):
    source = copy.deepcopy(source)
    url = source.get("url") or source.get("source_url")
    parsed = urlparse(str(url or ""))
    reviewed_host = parsed.scheme == "https" and parsed.hostname in DISCLOSURE_HOSTS and not parsed.username and not parsed.password
    if not (official_url(url) or reviewed_host) or not source.get("title"):
        raise ValueError("Field evidence must identify an official disclosure")
    if not (source.get("excerpt") or source.get("api_fields") or source.get("calculation") or source.get("basis")):
        raise ValueError("Evidence lacks a text or API locator")
    source["url"] = url
    for key, alias in (("unit", "normalized_unit"), ("source_unit", "raw_unit"), ("source_value", "raw_amount"), ("checked_at", "reviewed_at")):
        if key not in source and alias in source:
            source[key] = source[alias]
    # Keep local absolute paths in the audit companion, outside the public site.
    for key in ("raw_file", "text_file", "raw_path", "manifest_path", "page_image"):
        path = source.get(key)
        if path:
            parsed_path = Path(path)
            if not parsed_path.is_absolute():
                if ".." in parsed_path.parts:
                    source.pop(key, None)
                continue
            try:
                source[key] = str(parsed_path.relative_to(ROOT))
            except ValueError:
                source.pop(key, None)
    return source


def availability(value, checked_at, source_url, key=None):
    result = copy.deepcopy(value or {})
    status = result.get("status", "unverified")
    if status not in AVAILABILITY:
        result["original_status"] = status
        result["status"] = "not_available" if any(s in status for s in ("failed", "unavailable", "not_access")) else "unverified"
    result.setdefault("status", "unverified")
    result.setdefault("checked_at", checked_at)
    result.setdefault("source_url", source_url)
    result.setdefault("reason", "已核查官方披露，尚未取得可用于本字段的明确值。")
    display = {"issuer": "已核查资料未单列发行人。", "approved_date": "尚未取得明确记载审核通过日的官方文件。", "issued_date": "尚未取得本次申报对应的发行或设立日期。", "is_issued": "尚未取得本次申报对应的实际发行或设立证据。", "underlying_assets": "已取得资料尚未明确本批次资产清单。", "proposed_sale_amount_feedback_cny_100m": "未取得明确标注反馈稿的拟募集金额。"}
    result["display_reason"] = "官方文件暂无法读取，待补充核查。" if result["status"] == "not_available" else display.get(key, result["reason"])
    return result


def apply_supplements(snapshot, supplements, population, checked_at):
    containers = ("events", "funds") if population == "public" else ("items",)
    allowed = PUBLIC_FIELDS if population == "public" else INSTITUTIONAL_FIELDS
    targets = PUBLIC_TARGETS if population == "public" else INSTITUTIONAL_TARGETS
    audit = {"population": population, "checked_at": checked_at, "changes": [], "rejected": [], "coverage": {}}
    for container in containers:
        rows = snapshot[container]
        by_id = {str(row.get("code") if container == "funds" else row["id"]): row for row in rows}
        for supplement in supplements:
            for identity, candidate in supplement.get(container, {}).items():
                row = by_id.get(str(identity))
                if row is None:
                    audit["rejected"].append({"id": identity, "container": container, "reason": "no_exact_identity"})
                    continue
                row.setdefault("research_field_sources", {})
                row.setdefault("field_availability", {})
                for key, value in candidate.get("fields", {}).items():
                    if key not in allowed or not present(value):
                        continue
                    try:
                        if key.endswith("_cny_100m"):
                            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or value > 10000:
                                raise ValueError("Invalid amount in billions of CNY")
                        if key == "is_issued" and not isinstance(value, bool):
                            raise ValueError("Issuance is a tri-state boolean")
                        if key.endswith("_date") and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value)):
                            raise ValueError("Disclosure date must use YYYY-MM-DD")
                        if key in ("issued_date", "approved_date", "established_date") and value > snapshot.get("date", checked_at[:10]):
                            raise ValueError("Future milestone cannot be recorded as completed")
                        sources = candidate.get("sources", {}).get(key, [])
                        if isinstance(sources, dict):
                            sources = [sources]
                        if not sources:
                            raise ValueError("Missing field-specific official evidence")
                        sources = [dict(reviewed_source(source), checked_at=source.get("checked_at") or checked_at) for source in sources]
                        if key.endswith("_cny_100m") and not all(source.get("unit") or source.get("source_unit") or source.get("calculation") for source in sources):
                            raise ValueError("Amount evidence lacks its original unit or calculation")
                        if key.endswith("_cny_100m"):
                            for source in sources:
                                amount, unit = str(source.get("source_value", "")), source.get("source_unit")
                                if unit in ("元", "万元", "亿元") and re.fullmatch(r"\d[\d,]*(?:\.\d+)?", amount):
                                    expected = float(Decimal(amount.replace(",", "")) * {"元": Decimal("0.00000001"), "万元": Decimal("0.0001"), "亿元": Decimal(1)}[unit])
                                    if not math.isclose(expected, value, rel_tol=1e-8, abs_tol=1e-9):
                                        raise ValueError("Normalized amount differs from original value/unit")
                        if container == "events" and row.get("business_type") != "首发" and any(source.get("inherited_from_initial") for source in sources):
                            raise ValueError("Expansion cannot inherit a first-offering value")
                    except ValueError as exc:
                        audit["rejected"].append({"id": identity, "container": container, "field": key, "reason": str(exc)})
                        continue
                    before = row.get(key)
                    row[key] = copy.deepcopy(value)
                    row["research_field_sources"][key] = [{k: v for k, v in source.items() if k != "excerpt"} for source in sources]
                    row["field_availability"].pop(key, None)
                    if population == "public" and key == "asset_type":
                        row.update(classification_source="official", classification_confidence="confirmed", classification_evidence=sources, official_asset_type=value)
                    if before != value:
                        audit["changes"].append({"id": row["id"], "container": container, "field": key, "before": before, "after": value, "evidence": sources})
                if population == "institutional" and candidate.get("fields", {}).get("classification_source") == "verified" and row.get("research_field_sources", {}).get("asset_type"):
                    override = {key: candidate["fields"][key] for key in CLASSIFICATION_FIELDS if key in candidate["fields"]}
                    before = {key: row.get(key) for key in CLASSIFICATION_FIELDS}
                    _inherit_classification(row, None, {row["id"]: override})
                    if any(row.get(key) != value for key, value in before.items()):
                        audit["changes"].append({"id": row["id"], "container": container, "field": "reviewed_asset_classification", "before": before, "after": override})
                for key, value in candidate.get("unavailable", {}).items():
                    if key in allowed and not present(row.get(key)):
                        row["field_availability"][key] = availability(value, checked_at, row["source_url"], key)
        if container == "funds":
            events = {item["id"]: item for item in snapshot["events"]}
            for row in rows:
                initial = sorted((events[eid] for eid in row["event_ids"] if events[eid]["business_type"] == "首发"), key=lambda item: item.get("updated_date", ""))
                if not initial:
                    continue
                first = initial[-1]
                for key in PUBLIC_FIELDS:
                    if not present(row.get(key)) and present(first.get(key)) and first.get("research_field_sources", {}).get(key):
                        row[key] = copy.deepcopy(first[key])
                        row.setdefault("research_field_sources", {})[key] = [dict(copy.deepcopy(source), scope="首发披露，不含后续扩募") for source in first["research_field_sources"][key]]
                        row.setdefault("field_availability", {}).pop(key, None)
        # Add provenance for values already present in the refreshed exchange API.
        for row in rows:
            evidence = row.setdefault("research_field_sources", {})
            unknowns = row.setdefault("field_availability", {})
            aliases = {"manager": "writer", "exchange": "ex", "declared_amount_cny_100m": "amt", "accepted_date": "acc", "updated_date": "up", "project_status": "official_status"}
            for key in ("origin", "manager", "updated_date", "project_status", "accepted_date", "declared_amount_cny_100m"):
                raw_key = key if present(row.get(key)) else aliases.get(key, key)
                if present(row.get(raw_key)) and key not in evidence:
                    evidence[key] = [{"title": "交易所项目基本信息", "url": row["source_url"], "published_at": row.get("updated_date") or row.get("up"), "checked_at": checked_at, "api_fields": {raw_key: row[raw_key]}}]
            if population == "public":
                for key in ("manager", "asset_type", "underlying_assets"):
                    if present(row.get(key)) and key not in evidence and (key != "asset_type" or row.get("classification_source") == "official"):
                        evidence[key] = [{"title": "交易所基金或申报信息", "url": row["source_url"], "published_at": row.get("updated_date"), "checked_at": checked_at, "api_fields": {key: row[key]}}]
                if container == "funds" and present(row.get("initial_raise_cny_100m")) and "initial_raise_cny_100m" not in evidence:
                    evidence["initial_raise_cny_100m"] = [{"title": "交易所基金首发募集信息", "url": row["source_url"], "published_at": row.get("established_date") or row.get("listing_date"), "checked_at": checked_at, "unit": "亿元", "calculation": row.get("initial_raise_basis") or "交易所首发募集金额；不包含后续扩募", "api_fields": {"initial_raise_cny_100m": row["initial_raise_cny_100m"]}}]
            for key in targets:
                if not present(row.get(key)) and key not in unknowns:
                    unknowns[key] = availability({"status": "unverified", "reason": "本次核查尚未取得该字段可直接使用的官方披露值。"}, checked_at, row["source_url"], key)
            if population == "institutional" and "writer" in evidence:
                evidence["manager"] = copy.deepcopy(evidence["writer"])
        audit["coverage"][container] = {"records": len(rows), "fields": {key: {"filled": sum(present(row.get(key)) for row in rows), "with_field_evidence": sum(bool(row.get("research_field_sources", {}).get(key)) for row in rows), "availability": dict(Counter(row.get("field_availability", {}).get(key, {}).get("status", "filled") for row in rows))} for key in targets}}
    snapshot["enrichment"] = {"checked_at": checked_at, "source": "沪深交易所官方项目详情、公开招募说明书及发行公告", "status_policy": "审核状态与更新时间采用本次完整刷新交易所清单；历史文件不覆盖当前审核状态", "first_and_expansion_separate": True, "coverage": audit["coverage"], "audit_path": "workpapers/enrichment/integration/latest_audit.json"}
    if population == "institutional":
        update_classification_quality(snapshot)
    return audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", action="store_true", help="Write reviewed candidates to workpapers without replacing site data")
    args = parser.parse_args()
    stamp = datetime.now(ZoneInfo("Asia/Shanghai"))
    checked_at = stamp.isoformat(timespec="seconds")
    run_dir = ROOT / "workpapers/enrichment/integration" / stamp.strftime("%Y%m%dT%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=False)
    source_root = ROOT / "workpapers/enrichment"
    previous_public, previous_institutional = read(ROOT / "data/public_reits.json"), read(ROOT / "data/institutional.json")
    inputs = {key: source_root / key / name for key, name in (("public_sse", "latest_source.json"), ("public_szse", "latest_source.json"), ("institutional", "latest_source.json"))}
    public, linkage = build_snapshot({"SSE": read(inputs["public_sse"]), "SZSE": read(inputs["public_szse"])}, previous_public, read(ROOT / "config/public_fund_links.json"), stamp)
    institutional = read(inputs["institutional"])
    apply_field_scope(institutional, "institutional", previous_institutional)
    supplements = {key: read(source_root / key / "supplement.json") if (source_root / key / "supplement.json").exists() else {} if args.preview else read(source_root / key / "supplement.json") for key in inputs}
    audits = {"public": apply_supplements(public, [supplements["public_sse"], supplements["public_szse"]], "public", checked_at), "institutional": apply_supplements(institutional, [supplements["institutional"]], "institutional", checked_at)}
    sync_offering_phase(public)
    checks = {"public": validate_public(public), "institutional": validate_institutional(institutional)}
    status_deltas = {"public": public["changes"], "institutional": institutional.get("changes", {})}
    audit = {"generated_at": checked_at, "validation": checks, "status_changes": status_deltas, "field_review": audits, "linkage": linkage, "inputs": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs.values()}, "supplement_hashes": {key: digest(value) for key, value in supplements.items()}, "output_hashes": {"public": digest(public), "institutional": digest(institutional)}}
    write_json(run_dir / "audit.json", audit)
    write_json(run_dir / "public_reits.json", public)
    write_json(run_dir / "institutional.json", institutional)
    write_json(source_root / "integration/latest_audit.json", audit)
    write_json(ROOT / "data/source_manifest/enrichment" / (stamp.strftime("%Y%m%dT%H%M%S") + ".json"), {"generated_at": checked_at, "workpaper": str((run_dir / "audit.json").relative_to(ROOT)), "inputs": audit["inputs"], "supplement_hashes": audit["supplement_hashes"], "outputs": audit["output_hashes"], "raw_storage": "data/raw/enrichment/；大型PDF保留实际读取的原始字节区间及偏移、响应版本、哈希；范围见各来源manifest"})
    if not args.preview:
        overrides = read(ROOT / "config/classification_overrides.json")
        for identity, candidate in supplements["institutional"].get("items", {}).items():
            if candidate.get("fields", {}).get("classification_source") == "verified":
                row = next(item for item in institutional["items"] if item["id"] == identity)
                if row.get("research_field_sources", {}).get("asset_type"):
                    overrides[identity] = {key: row[key] for key in CLASSIFICATION_FIELDS if key in row}
        write_json(ROOT / "config/classification_overrides.json", overrides)
        write_json(ROOT / "data/public_reits.json", public)
        write_json(ROOT / "data/institutional.json", institutional)
    print(json.dumps({"validation": checks, "changes": {key: len(value["changes"]) for key, value in audits.items()}, "rejected": {key: value["rejected"] for key, value in audits.items()}, "workpaper": str(run_dir.relative_to(ROOT)), "published_snapshot_replaced": not args.preview}, ensure_ascii=False))


if __name__ == "__main__":
    main()
