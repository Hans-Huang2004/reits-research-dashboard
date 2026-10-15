"""Join independently collected official fund and filing records into a public REIT library.

Raw responses are immutable inputs; identity decisions and quality checks are written
to workpapers before the validated presentation snapshot is atomically replaced.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from collectors.project_fields import PUBLIC_RESEARCH_FIELDS, ASSET_CLASSIFICATION_FIELDS

ROOT = Path(__file__).resolve().parents[1]
ISSUED_STAGES = {"已上市", "成立待上市"}
TERMINAL_STAGES = {"终止", "撤回", "未通过"}
INCLUDED_BUSINESS_TYPES = {"首发", "扩募"}


def canonical_name(value):
    """Strip only declared business suffixes, never issuer/asset identity tokens."""
    value = re.sub(r"\s+", "", str(value or ""))
    value = value.replace("（", "(").replace("）", ")")
    value = re.sub(r"\((?:扩募|新购入项目|首次申报|首发)\)", "", value)
    value = re.sub(r"(?:20\d{2}年(?:度)?第[一二三四五六七八九十\d]+次)?(?:扩募并新购入.*|扩募.*|新购入.*)$", "", value)
    return value.rstrip("-—_：:()")


def official_url(value):
    u = urlparse(str(value or ""))
    return u.scheme == "https" and not u.username and not u.password and any(
        u.hostname == host or (u.hostname or "").endswith("." + host)
        for host in ("sse.com.cn", "szse.cn", "csrc.gov.cn")
    )


def stage_for_status(status):
    status = str(status or "")
    if "终止" in status:
        return "终止"
    if "撤回" in status:
        return "撤回"
    if any(x in status for x in ("未通过", "不通过", "不予注册")):
        return "未通过"
    if "中止" in status or "暂停" in status:
        return "中止审核"
    if any(x in status for x in ("注册生效", "准予注册", "注册通过", "已注册")):
        return "获批待发行"
    if "通过" in status or "提交注册" in status:
        return "审核通过待注册"
    if "受理" in status:
        return "已受理"
    return "审核中"


def date_not_future(value, date):
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value or "")) and value <= date)


def sync_offering_phase(snapshot):
    """Dated sale evidence updates business phase, never the exchange audit status."""
    today = snapshot["date"]
    events = {row["id"]: row for row in snapshot["events"]}
    for fund in snapshot["funds"]:
        initial = [events[eid] for eid in fund["event_ids"] if events[eid]["business_type"] == "首发"]
        active = [event for event in initial if stage_for_status(event.get("official_status")) not in TERMINAL_STAGES | {"中止审核"}]
        if initial and not active and fund.get("stage") not in ISSUED_STAGES:
            fund["stage"] = stage_for_status(max(initial, key=lambda event: event.get("updated_date", "")).get("official_status"))
        if active and fund.get("stage") not in ISSUED_STAGES | TERMINAL_STAGES | {"中止审核"}:
            if date_not_future(fund.get("established_date"), today) and fund.get("research_field_sources", {}).get("established_date"):
                fund["stage"] = "成立待上市"
            elif fund.get("offering_start_date") and fund.get("research_field_sources", {}).get("offering_start_date"):
                start, end = fund["offering_start_date"], fund.get("offering_end_date")
                fund["stage"] = "待发售" if start > today else "发售中" if end and end >= today else "发售结束待成立" if end else "发售中"
        if fund.get("stage") in ISSUED_STAGES | {"待发售", "发售中", "发售结束待成立"}:
            for event in active:
                event["stage"] = fund["stage"]
    snapshot["quality"]["stages"] = dict(Counter(row["stage"] for row in snapshot["funds"]))


def unique_documents(rows):
    result = {}
    for item in rows:
        if item and item.get("url"):
            result.setdefault(item["url"], item)
    return list(result.values())


def classify_asset(record):
    record = dict(record)
    if record.get("asset_type") not in (None, "", "待分类"):
        record.setdefault("classification_source", "official" if record.get("official_asset_type") else "unknown")
        return record
    from collectors.institutional import classify_by_name
    # A commercial REIT's regime does not identify its property use.
    name = re.sub(r"封闭式(?:商业不动产|基础设施)证券投资基金", "", record.get("name", ""))
    result = classify_by_name(name)
    if result["psub"] != "待分类":
        record.update(asset_type=result["psub"], classification_source="keyword",
                      classification_confidence="likely", classification_note=result["pnote"])
    else:
        record.update(asset_type="待分类", classification_source="unknown",
                      classification_confidence="unknown", classification_note=result["pnote"])
    return record


def build_snapshot(sources, previous=None, overrides=None, now=None):
    now = now or datetime.now(ZoneInfo("Asia/Shanghai"))
    today = now.date().isoformat()
    previous = previous or {}
    overrides = overrides or {}
    funds, events, audit = {}, {}, []
    scope_exclusions = []
    source_event_ids = set()
    status = {}
    old_by_code = {(f["exchange"], f["code"]): f for f in previous.get("funds", []) if f.get("code")}
    old_by_event = {e["id"]: e["fund_id"] for e in previous.get("events", [])}
    old_funds = {f["id"]: f for f in previous.get("funds", [])}

    for exchange_key, source in sources.items():
        meta = source.get("source_status", {})
        if meta.get("ok") is False or meta.get("complete") is False:
            raise ValueError(exchange_key + " did not collect a complete source")
        status[exchange_key] = dict(meta, ok=True)
        for source_fund in source.get("funds", []):
            f = classify_asset(source_fund)
            code = str(f.get("code") or "")
            if not code or not re.fullmatch(r"\d{6}", code):
                raise ValueError("Official fund catalog record lacks a six digit code")
            exchange = f["exchange"]
            old = old_by_code.get((exchange, code))
            if old is None:
                official_initial_ids = [e["id"] for e in source.get("events", []) if e.get("business_type") == "首发" and
                                        str((overrides.get(e["id"]) or {}).get("fund_code") or e.get("fund_code") or "") == code]
                old_event_candidates = {old_by_event[eid] for eid in official_initial_ids if eid in old_by_event and old_by_event[eid] in old_funds}
                if len(old_event_candidates) == 1:
                    old = old_funds[next(iter(old_event_candidates))]
            if old is None:
                names = {canonical_name(n) for n in [f.get("name"), *f.get("aliases", [])] if n}
                old_candidates = [item for item in old_funds.values() if item["exchange"] == exchange and not item.get("code") and
                                  names.intersection(canonical_name(n) for n in [item.get("name"), *item.get("aliases", [])] if n)]
                if len(old_candidates) > 1:
                    raise ValueError("Ambiguous previous applicant identity for " + code)
                old = old_candidates[0] if old_candidates else None
            fid = old["id"] if old else f"{exchange_key}_FUND_{code}"
            f.update(id=fid, code=code, event_ids=[], documents=unique_documents(f.get("documents", [])))
            # Scheduled dates remain visible as plans, never completed milestones.
            if f.get("listing_date") and not date_not_future(f["listing_date"], today):
                f["planned_listing_date"] = f.pop("listing_date")
            if f.get("established_date") and not date_not_future(f["established_date"], today):
                f["planned_established_date"] = f.pop("established_date")
            if date_not_future(f.get("listing_date"), today):
                f["stage"] = "已上市"
            elif date_not_future(f.get("established_date"), today) or (
                    f.get("status") in ("已成立待上市", "成立待上市") and
                    date_not_future(f.get("establishment_announcement_date"), today) and
                    official_url(f.get("issuance_evidence_url"))):
                f["stage"] = "成立待上市"
            else:
                f["stage"] = f.get("stage") if f.get("stage") not in ISSUED_STAGES else "获批待发行"
                f["stage"] = f["stage"] or "获批待发行"
            key = (exchange, code)
            if key in [(x["exchange"], x["code"]) for x in funds.values()]:
                raise ValueError("Duplicate official fund code " + code)
            funds[fid] = f
        for source_event in source.get("events", []):
            if source_event["id"] in source_event_ids:
                raise ValueError("Duplicate filing ID " + source_event["id"])
            source_event_ids.add(source_event["id"])
            if source_event.get("business_type") == "新购入":
                # Preserve the source record and its attachments in the audit;
                # acquisition alone does not establish an expansion offering.
                scope_exclusions.append({"source_exchange": exchange_key, "record": deepcopy(source_event),
                                         "reason": "单独新购入未归为扩募，不纳入首发及扩募申报范围"})
                continue
            if source_event.get("business_type") not in INCLUDED_BUSINESS_TYPES:
                raise ValueError("Unsupported official filing business type for " + source_event["id"])
            e = classify_asset(source_event)
            events[e["id"]] = e

    def name_candidates(e):
        target = canonical_name(e["name"])
        return [f for f in funds.values() if f["exchange"] == e["exchange"] and
                target in {canonical_name(n) for n in [f.get("name"), *f.get("aliases", [])] if n}]

    unresolved = []
    # Resolve first offerings first, so expansions can refer to newly linked names.
    for e in sorted(events.values(), key=lambda row: (row.get("business_type") != "首发", row["id"])):
        override = overrides.get(e["id"])
        code = str(e.get("fund_code") or "")
        method = "official_fund_code" if code else ""
        if override:
            if not official_url(override.get("source_url")) or not override.get("note"):
                raise ValueError("Manual linkage requires an official evidence URL and note")
            code = str(override["fund_code"])
            method = "reviewed_official_evidence"
        candidates = [f for f in funds.values() if f["exchange"] == e["exchange"] and f["code"] == code] if code else name_candidates(e)
        if len(candidates) > 1:
            raise ValueError("Ambiguous official filing identity " + e["id"])
        if candidates:
            f = candidates[0]
            method = method or "exact_official_fund_name"
        elif e.get("business_type") == "首发":
            old_id = old_by_event.get(e["id"])
            fid = old_id or e["id"].replace("_", "_APPLICANT_", 1)
            f = {"id": fid, "code": code, "exchange": e["exchange"], "name": e["name"],
                 "short_name": "", "manager": e.get("manager", ""), "origin": e.get("origin", ""),
                 "source_url": e["source_url"], "event_ids": [], "documents": [], "stage": stage_for_status(e.get("official_status"))}
            funds[fid] = f
            method = "official_initial_filing"
        else:
            unresolved.append({"event_id": e["id"], "name": e["name"], "fund_code": code,
                               "source_url": e["source_url"], "reason": "No unique official fund match"})
            continue
        e["fund_id"] = f["id"]
        e["fund_code"] = f["code"]
        e["linkage_method"] = method
        if override:
            e["linkage_evidence"] = override
        f["event_ids"].append(e["id"])
        f["aliases"] = sorted(set(f.get("aliases", []) + ([e["name"]] if e["name"] != f["name"] else [])))
        # The fund record describes its initial pool. Expansion disclosures stay
        # on their own event even when the initial catalog omits these fields.
        if e.get("business_type") == "首发":
            event_asset_official = e.get("official_asset_type") or e.get("research_field_sources", {}).get("asset_type") or e.get("classification_source") == "official"
            fund_asset_official = f.get("official_asset_type") or f.get("research_field_sources", {}).get("asset_type") or f.get("classification_source") == "official"
            if event_asset_official and not fund_asset_official and e.get("asset_type") not in (None, "", "待分类"):
                f["asset_type"] = e["asset_type"]
                for field in ASSET_CLASSIFICATION_FIELDS:
                    if field in e:
                        f[field] = deepcopy(e[field])
                    else:
                        f.pop(field, None)
            for field in ("manager", "origin", "asset_type", "product_type", "underlying_assets", "province", "city", *ASSET_CLASSIFICATION_FIELDS, *PUBLIC_RESEARCH_FIELDS):
                if f.get(field) in (None, "", [], "待分类", "待核实") and e.get(field) not in (None, "", [], "待分类", "待核实"):
                    f[field] = deepcopy(e[field])
                    if e.get("research_field_sources", {}).get(field):
                        f.setdefault("research_field_sources", {})[field] = deepcopy(e["research_field_sources"][field])
            if event_asset_official and f.get("asset_type") == e.get("asset_type") and e.get("research_field_sources", {}).get("asset_type") and not f.get("research_field_sources", {}).get("asset_type"):
                f.setdefault("research_field_sources", {})["asset_type"] = deepcopy(e["research_field_sources"]["asset_type"])
        f["documents"] = unique_documents(f.get("documents", []) + e.get("documents", []))
        if f.get("initial_raise_cny_100m") is not None and not f.get("initial_raise_basis") and f.get("initial_copies_100m") is not None:
            f["initial_raise_basis"] = "首发发售价格×官方首发募集份额（不含扩募）"
        e["stage"] = e.get("stage") or stage_for_status(e.get("official_status"))
        if (e.get("completion_date") and date_not_future(e["completion_date"], today)) or (
                e.get("completed") is True and e.get("completion_evidence") and
                date_not_future(e.get("completion_announcement_date"), today)):
            e["stage"] = "已完成"
        if e.get("business_type") == "首发":
            if f["stage"] in ISSUED_STAGES and stage_for_status(e.get("official_status")) not in TERMINAL_STAGES | {"中止审核"}:
                e["stage"] = f["stage"]
            elif f["stage"] in (None, "获批待发行"):
                f["stage"] = e["stage"]
        audit.append({"event_id": e["id"], "fund_id": f["id"], "fund_code": f["code"], "method": method,
                      "source_url": e["source_url"]})
    if unresolved:
        raise UnresolvedLinks(unresolved)
    for f in funds.values():
        linked = [events[eid] for eid in f["event_ids"]]
        f["updated_date"] = max([str(f.get("updated_date") or ""), str(f.get("listing_date") or ""),
                                 str(f.get("establishment_announcement_date") or ""),
                                 *[e.get("updated_date", "") for e in linked]])
        f.setdefault("asset_type", "待分类")
        f.setdefault("product_type", "待核实")
        if not f.get("stage"):
            initial = sorted([e for e in linked if e.get("business_type") == "首发"], key=lambda x:x.get("updated_date", ""))
            f["stage"] = initial[-1]["stage"] if initial else "待核实"
    fund_rows = sorted(funds.values(), key=lambda f:(f.get("updated_date", ""), f["id"]), reverse=True)
    event_rows = sorted(events.values(), key=lambda e:(e.get("updated_date", ""), e["id"]), reverse=True)
    old_events = {e["id"]: e for e in previous.get("events", [])}
    excluded_event_ids = {item["record"]["id"] for item in scope_exclusions}
    changes = {"new_fund_ids": sorted(set(funds) - set(old_funds)), "new_event_ids": sorted(set(events) - set(old_events)),
               "changed_event_ids": sorted(eid for eid in set(events).intersection(old_events) if
                                           any(events[eid].get(k) != old_events[eid].get(k) for k in ("official_status", "stage", "updated_date", "fund_id"))),
               "missing_event_ids": sorted(set(old_events) - set(events) - excluded_event_ids),
               "excluded_event_ids": sorted(excluded_event_ids),
               "identity_consolidations": [{"event_id": eid, "previous_fund_id": old_events[eid]["fund_id"], "fund_id": events[eid]["fund_id"]}
                                            for eid in set(events).intersection(old_events) if old_events[eid].get("fund_id") != events[eid].get("fund_id")]}
    result = {"schema_version": 1, "date": today, "updated_at": now.isoformat(timespec="seconds"), "changes": changes,
              "source_status": status, "coverage": {"complete": True, "fund_count": len(funds), "event_count": len(events),
                  "excluded_event_count": len(scope_exclusions),
                  "population": "沪深交易所公募REITs已发行基金及公开首发、扩募申报", "scope": "基础设施REITs及商业不动产REITs；单独新购入不计入申报"},
              "quality": {"unresolved_expansion_links": [], "funds_by_exchange": dict(Counter(f["exchange"] for f in fund_rows)),
                  "events_by_exchange": dict(Counter(e["exchange"] for e in event_rows)),
                  "stages": dict(Counter(f["stage"] for f in fund_rows)),
                  "business_types": dict(Counter(e["business_type"] for e in event_rows)),
                  "scope_exclusions": scope_exclusions},
              "funds": fund_rows, "events": event_rows}
    from collectors.project_fields import apply_field_scope
    apply_field_scope(result, "public", previous)
    sync_offering_phase(result)
    return result, audit


class UnresolvedLinks(ValueError):
    def __init__(self, rows):
        self.rows = rows
        super().__init__(f"{len(rows)} expansion filings require official fund linkage review")


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reuse-sources", action="store_true", help="Rebuild only from separately saved reviewed source workpapers")
    p.add_argument("--raw-dir", type=Path)
    p.add_argument("--output", type=Path, default=ROOT / "data/public_reits.json")
    p.add_argument("--work-dir", type=Path, default=ROOT / "workpapers/public")
    p.add_argument("--szse-input", type=Path, help="Explicit reviewed SZSE workpaper version, for --reuse-sources only")
    p.add_argument("--sse-input", type=Path, help="Explicit reviewed SSE workpaper version, for --reuse-sources only")
    args = p.parse_args()
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    raw_root = args.raw_dir or ROOT / "data/raw/public" / now.date().isoformat() / now.strftime("%H%M%S")
    sources = {}
    papers = {}
    for key, name in (("SSE", "sse"), ("SZSE", "szse")):
        explicit_input = args.szse_input if key == "SZSE" else args.sse_input
        paper = (explicit_input if args.reuse_sources and explicit_input else args.work_dir / (name + "_collected.json")).resolve()
        papers[name] = paper
        if args.reuse_sources:
            sources[key] = json.loads(paper.read_text(encoding="utf-8"))
        else:
            if key == "SSE":
                from collectors.public_sse import collect
            else:
                from collectors.public_szse import collect
            sources[key] = collect(raw_root / name)
            write_json(paper, sources[key])
    previous = json.loads(args.output.read_text(encoding="utf-8")) if args.output.exists() else {}
    override_file = ROOT / "config/public_fund_links.json"
    overrides = json.loads(override_file.read_text(encoding="utf-8")) if override_file.exists() else {}
    try:
        snapshot, audit = build_snapshot(sources, previous, overrides, now)
    except UnresolvedLinks as exc:
        write_json(args.work_dir / "unresolved_links.json", exc.rows)
        raise
    from scripts.validate_public_data import validate
    validation = validate(snapshot)
    write_json(args.work_dir / "linkage_audit.json", audit)
    write_json(args.work_dir / "scope_exclusions.json", snapshot["quality"]["scope_exclusions"])
    write_json(args.work_dir / "validation.json", validation)
    manifest = {"generated_at": now.isoformat(timespec="seconds"), "source_workpapers": {},
                "raw_manifests": {key: value.get("manifest", []) for key, value in sources.items()},
                "snapshot_sha256": hashlib.sha256((json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n").encode()).hexdigest(),
                "scope_exclusions": snapshot["quality"]["scope_exclusions"],
                "definition": "基金与首发、扩募申报事件分别计数；单独新购入按范围排除并保留原记录；首发募集金额与扩募金额分开；无公开证据不补值"}
    for name in ("sse", "szse"):
        paper = papers[name]
        manifest["source_workpapers"][str(paper.relative_to(ROOT))] = hashlib.sha256(paper.read_bytes()).hexdigest()
    write_json(ROOT / "data/source_manifest/public" / (now.strftime("%Y%m%d-%H%M%S") + ".json"), manifest)
    write_json(args.output, snapshot)
    write_json(ROOT / "snapshots/public" / (now.strftime("%Y%m%d-%H%M%S") + ".json"), snapshot)
    print(json.dumps(validation, ensure_ascii=False))


if __name__ == "__main__":
    main()
