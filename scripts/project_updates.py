"""Auditable cumulative project activity from validated, complete library snapshots."""
from __future__ import annotations
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.validate_data import validate as validate_institutional
from scripts.validate_public_data import validate as validate_public
from scripts.validate_ndrc_data import validate as validate_ndrc

BEIJING = ZoneInfo("Asia/Shanghai")
FILES = {"public": "public_reits.json", "institutional": "institutional.json", "ndrc": "ndrc_recommendations.json"}
LABELS = {"public": "公募REITs", "institutional": "机构间REITs", "ndrc": "国家发改委推荐"}
STATUS = {"0": "已申报", "1": "已受理", "2": "已反馈", "3": "已接收反馈意见", "4": "通过", "5": "未通过", "8": "终止", "9": "中止", "10": "已回复意见", "11": "提交注册", "12": "注册生效"}
FIELD_LABELS = {"status": "审核状态", "official_status": "审核状态", "official_sub_status": "审核子状态", "accepted_date": "受理日期", "registered_date": "注册日期", "completion_date": "扩募完成日期", "approved_date": "通过日期", "issued_date": "发行或设立日期", "recommended_date": "推荐日期", "offering_start_date": "发售开始日期", "offering_end_date": "发售结束日期", "established_date": "成立日期", "listing_date": "上市日期", "documents": "披露文件", "timeline": "官方审核节点"}
FIELD_LABELS["establishment_announcement_date"] = "成立公告日期"
FIELD_LABELS["project_presence"] = "项目收录"
FIELD_LABELS.update(name="项目名称", amt="申报金额（亿元）", proposed_fund_amount_yi="拟发售金额（亿元）", applicant_region="主申报地方／中央企业", industry_official="官方行业", related_entity_ids="关联项目")
VALIDATORS = {"public": validate_public, "institutional": validate_institutional, "ndrc": validate_ndrc}


def read(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def digest(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(value).hexdigest()


def day(value):
    if not isinstance(value, str):
        return ""
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date().isoformat()
    except ValueError:
        return ""


def timestamp(value):
    try:
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is not None:
            return stamp.astimezone(BEIJING).isoformat(timespec="seconds")
    except (ValueError, TypeError):
        pass
    return ""


def official_url(value):
    parsed = urlparse(str(value or ""))
    host = parsed.hostname or ""
    return parsed.scheme == "https" and not parsed.username and not parsed.password and any(host == suffix or host.endswith("." + suffix) for suffix in ("sse.com.cn", "szse.cn", "szse.com.cn", "tzxm.gov.cn", "ndrc.gov.cn", "csrc.gov.cn"))


def source_time(snapshot):
    stamps = [timestamp(snapshot.get("updated_at"))]
    stamps.extend(timestamp(meta.get("collected_at") or meta.get("updated_at")) for meta in snapshot.get("source_status", {}).values())
    return max(filter(None, stamps), default="")


def normalize_documents(rows, as_of):
    docs = {}
    for row in rows or []:
        if not isinstance(row, dict) or not official_url(row.get("url")):
            continue
        when = day(row.get("date") or row.get("published_at"))
        if when and when > as_of:
            continue
        key = row["url"]
        docs[key] = {"title": str(row.get("title") or "官方披露文件"), "url": key, "date": when,
                     **({"source_id": str(row["source_id"])} if row.get("source_id") else {})}
    return sorted(docs.values(), key=lambda row: (row["date"], row["url"]))


def workflow_document(doc):
    return bool(re.search(r"问询|反馈|回复|答复|注册|批复|无异议|发售公告|发行公告|合同生效|上市交易|扩募.*结果|成立公告|审核.*结果|终止|中止", doc["title"]))


def aliases_for_current(current):
    funds = current["public"]["funds"]
    by_code = {(f["exchange"], f["code"]): f["id"] for f in funds if f.get("code")}
    by_event = {eid: f["id"] for f in funds for eid in f.get("event_ids", [])}
    return by_code, by_event


def entities(population, snapshot, aliases):
    """Normalize official workflow fields; research and matching edits are not progress."""
    result = {}
    by_code, by_event = aliases
    as_of = snapshot["date"]
    if population == "public":
        local_funds = {}
        for fund in snapshot["funds"]:
            canonical = by_code.get((fund["exchange"], fund.get("code")))
            canonical = canonical or next((by_event[e] for e in fund.get("event_ids", []) if e in by_event), None) or fund["id"]
            local_funds[fund["id"]] = canonical
            docs = normalize_documents((fund.get("documents") or []) + (fund.get("offering_announcements") or []), as_of)
            dates = {"offering_start_date": fund.get("offering_start_date") or fund.get("initial_issue_start"), "offering_end_date": fund.get("offering_end_date") or fund.get("initial_issue_end"), "established_date": fund.get("established_date"), "establishment_announcement_date": fund.get("establishment_announcement_date"), "listing_date": fund.get("listing_date")}
            milestones = {key: day(value) for key, value in dates.items() if day(value) and day(value) <= as_of}
            result[canonical] = {"id": canonical, "population": population, "entity_kind": "fund", "project_name": fund["name"], "exchange": fund["exchange"], "asset_type": fund.get("asset_type") or "待分类", "business_type": "首发", "manager": fund.get("manager") or "", "origin": fund.get("origin") or "", "fund_id": canonical, "fund_code": fund.get("code") or "", "related_entity_ids": sorted(set(fund.get("event_ids", []))), "status": fund.get("stage") or fund.get("status") or "", "source_url": fund["source_url"], "state": dict(milestones), "documents": docs, "timeline": [], "milestones": milestones, "official_updated_date": day(fund.get("updated_date"))}
        for row in snapshot["events"]:
            fund_id = local_funds.get(row.get("fund_id"), row.get("fund_id") or "")
            milestones = {key: day(row.get(key)) for key in ("accepted_date", "registered_date", "completion_date") if day(row.get(key)) and day(row.get(key)) <= as_of}
            timeline = [{"title": item["title"], "date": day(item.get("date"))} for item in row.get("timeline", []) if item.get("title") and day(item.get("date")) and day(item.get("date")) <= as_of]
            result[row["id"]] = {"id": row["id"], "population": population, "entity_kind": "filing", "project_name": row["name"], "exchange": row["exchange"], "asset_type": row.get("asset_type") or "待分类", "business_type": row["business_type"], "manager": row.get("manager") or "", "origin": row.get("origin") or "", "fund_id": fund_id, "fund_code": row.get("fund_code") or "", "related_entity_ids": [fund_id] if fund_id else [], "status": row["official_status"], "source_url": row["source_url"], "state": {"official_status": row["official_status"], "official_sub_status": row.get("official_sub_status") or "", **milestones}, "documents": normalize_documents(row.get("documents"), as_of), "timeline": timeline, "milestones": milestones, "official_updated_date": day(row.get("updated_date"))}
    else:
        for row in snapshot["items"]:
            institutional = population == "institutional"
            milestones = {"accepted_date": day(row.get("acc"))} if institutional else {"recommended_date": day(row.get("recommended_date"))}
            if institutional:
                for key in ("approved_date", "issued_date"):
                    if row.get("research_field_sources", {}).get(key) and day(row.get(key)):
                        milestones[key] = day(row[key])
            milestones = {k: v for k, v in milestones.items() if v and v <= as_of}
            relations = row.get("relations", []) if not institutional else []
            related = sorted({value for rel in relations for value in (rel.get("exchange_event_id"), rel.get("fund_id")) if value})
            status = STATUS.get(str(row.get("status")), str(row.get("status") or "")) if institutional else "已推荐"
            result[row["id"]] = {"id": row["id"], "population": population, "entity_kind": "filing" if institutional else "recommendation", "project_name": row["name"], "exchange": row.get("ex") or "", "asset_type": row.get("psub") or row.get("industry_official") or "待分类", "business_type": ("扩募" if row.get("is_expansion") else "首发") if institutional else row.get("business_type") or "待核实", "manager": row.get("writer") or row.get("mgr") or "", "origin": row.get("origin") or row.get("applicant_region") or "", "fund_id": next((rel.get("fund_id") for rel in relations if rel.get("fund_id")), ""), "fund_code": next((rel.get("fund_code") for rel in relations if rel.get("fund_code")), ""), "related_entity_ids": related, "status": status, "source_url": row["source_url"], "state": {**({"status": status} if institutional else {}), **milestones}, "documents": normalize_documents(row.get("documents"), as_of), "timeline": [], "milestones": milestones, "official_updated_date": day(row.get("up") if institutional else row.get("recommended_date"))}
    if population == "public":
        # Fund detail pages repeat the filing attachments. Keep those on their
        # exact official filing batch, avoiding duplicate fund/feed entries.
        filing_docs = {doc["url"] for entity in result.values() if entity["entity_kind"] == "filing" for doc in entity["documents"]}
        for entity in result.values():
            if entity["entity_kind"] == "fund":
                entity["documents"] = [doc for doc in entity["documents"] if doc["url"] not in filing_docs]
    # Keep the exact official core fields separate from research enrichment.
    original = snapshot["funds"] + snapshot["events"] if population == "public" else snapshot["items"]
    original_by_id = {row["id"]: row for row in original}
    for identity, entity in result.items():
        entity["state"]["name"] = entity["project_name"]
        row = original_by_id.get(identity, {})
        if population == "institutional":
            entity["state"]["amt"] = row.get("amt")
        elif population == "ndrc":
            entity["state"].update({field: row.get(field) for field in ("proposed_fund_amount_yi", "applicant_region", "industry_official")})
            entity["state"]["related_entity_ids"] = list(entity["related_entity_ids"])
            reviewed = [timestamp(relation.get("reviewed_at")) for relation in row.get("relations", [])]
            entity["relation_revision_at"] = timestamp(snapshot.get("matching_updated_at")) or max(filter(None, reviewed), default="")
    return result


def version_ref(version):
    return {key: version[key] for key in ("path", "sha256", "collected_at", "retained_path")}


def event_id(event):
    identity = {"population": event["population"], "entity_id": event["entity_id"], "type": event["event_type"], "official_date": event["official_date"] or "", "changes": event["changes"], "documents": [d["url"] for d in event["documents"]]}
    if not event["is_baseline"]:
        # The same A→B transition can legitimately recur within one day.
        # Baseline facts deduplicate by evidence; observed transitions bind the batch.
        identity["observation_sha256"] = event["source_version"]["sha256"]
    return "UPDATE_" + digest(identity)[:24]


def make_event(entity, version, event_type, title, official_date, changes, documents=None, discovery_type="baseline"):
    before = {c["field"]: c["before"] for c in changes}
    after = {c["field"]: c["after"] for c in changes}
    docs = documents or []
    baseline = discovery_type == "baseline"
    event = {"population": entity["population"], "population_label": LABELS[entity["population"]], "entity_id": entity["id"], "entity_kind": entity["entity_kind"], **{key: deepcopy(entity[key]) for key in ("project_name", "exchange", "asset_type", "business_type", "manager", "origin", "fund_id", "fund_code", "related_entity_ids", "source_url")}, "event_type": event_type, "title": title, "before": before, "after": after, "official_date": official_date or "", "detected_at": version["collected_at"], "event_date": (official_date or day(version["collected_at"])) if baseline else day(version["collected_at"]), "discovery_type": discovery_type, "is_baseline": baseline, "documents": docs, "changes": changes, "source_version": version_ref(version), "batch_key": entity["population"] + "|" + entity["id"] + "|" + version["sha256"]}
    event["id"] = event_id(event)
    return event


def change(field, before, after):
    return {"field": field, "label": FIELD_LABELS.get(field, field), "before": before, "after": after}


def newer_fact(official_date, previous_version):
    """Same-day source changes are observable; older dates are historical backfill."""
    return bool(official_date and official_date >= day(previous_version["collected_at"]))


def entity_events(entity, old, version, previous_version):
    events = []
    milestones = {k: v for k, v in entity["milestones"].items() if not old or old["milestones"].get(k) != v}
    by_date = {}
    for key, value in milestones.items():
        by_date.setdefault(value, []).append(change(key, old["milestones"].get(key) if old else None, value))
    for when, changes in sorted(by_date.items()):
        observed = old is not None and previous_version is not None and newer_fact(when, previous_version)
        title = "、".join(c["label"].removesuffix("日期") for c in changes)
        if entity["population"] == "ndrc":
            title = "国家发改委推荐"
        events.append(make_event(entity, version, "recommendation" if entity["population"] == "ndrc" else "milestone", title, when, changes, discovery_type="observed" if observed else "baseline"))
    old_timeline = {(r["date"], r["title"]) for r in old["timeline"]} if old else set()
    for when, title in sorted({(r["date"], r["title"]) for r in entity["timeline"]} - old_timeline):
        observed = old is not None and previous_version is not None and newer_fact(when, previous_version)
        events.append(make_event(entity, version, "milestone", title, when, [change("timeline", None, title)], discovery_type="observed" if observed else "baseline"))
    old_docs = {doc["url"] for doc in old["documents"]} if old else set()
    new_docs = [doc for doc in entity["documents"] if doc["url"] not in old_docs and workflow_document(doc)]
    for when in sorted({doc["date"] for doc in new_docs}):
        docs = [doc for doc in new_docs if doc["date"] == when]
        observed = old is not None and previous_version is not None and newer_fact(when, previous_version)
        title = "新增回复文件" if any(re.search("回复|答复", doc["title"]) for doc in docs) else "新增披露文件"
        events.append(make_event(entity, version, "documents_added", title, when, [change("documents", None, [doc["title"] for doc in docs])], docs, "observed" if observed else "baseline"))
    if old:
        fields = ("official_status", "official_sub_status") if entity["population"] == "public" else ("status",) if entity["population"] == "institutional" else ()
        changes = [change(key, old["state"].get(key), entity["state"].get(key)) for key in fields if old["state"].get(key) != entity["state"].get(key)]
        if changes:
            when = entity["official_updated_date"]
            observed = newer_fact(when, previous_version)
            events.append(make_event(entity, version, "status_change" if observed else "revision", "审核状态更新" if observed else "历史状态资料修订", when, changes, discovery_type="observed" if observed else "baseline"))
        revision_fields = ("name", "amt") if entity["population"] == "institutional" else ("name", "proposed_fund_amount_yi", "applicant_region", "industry_official") if entity["population"] == "ndrc" else ("name",)
        revisions = [change(field, old["state"].get(field), entity["state"].get(field)) for field in revision_fields if old["state"].get(field) != entity["state"].get(field)]
        if revisions:
            when = entity["official_updated_date"]
            observed = newer_fact(when, previous_version)
            events.append(make_event(entity, version, "revision", "资料修订", when, revisions, discovery_type="observed" if observed else "baseline"))
        if entity["population"] == "ndrc" and old["state"].get("related_entity_ids") != entity["state"].get("related_entity_ids"):
            reviewed_at = entity.get("relation_revision_at") or ""
            # Existing manually reviewed history is not launched as fresh progress.
            # Subsequent reviews get an explicitly separate metadata revision.
            observed = bool(reviewed_at and version.get("tracking_epoch") and reviewed_at >= version["tracking_epoch"])
            event = make_event(entity, version, "revision", "关联资料修订", "", [change("related_entity_ids", old["state"].get("related_entity_ids"), entity["state"].get("related_entity_ids"))], discovery_type="observed" if observed else "baseline")
            event["reviewed_at"] = reviewed_at
            if reviewed_at:
                event["detected_at"] = reviewed_at
                event["event_date"] = day(reviewed_at)
            events.append(event)
    elif previous_version and entity["entity_kind"] != "fund":
        when = entity["milestones"].get("accepted_date") or entity["milestones"].get("recommended_date")
        if newer_fact(when, previous_version):
            for event in events:
                if event["official_date"] == when and event["event_type"] in ("milestone", "recommendation"):
                    event.update(discovery_type="observed", is_baseline=False, event_date=day(version["collected_at"]))
                    event["title"] = "新增受理项目" if entity["population"] != "ndrc" else "新增国家发改委推荐项目"
                    event["id"] = event_id(event)
                    break
        elif not when and not entity["timeline"] and not entity["documents"]:
            # Official lists can expose a new project without a business date.
            # Preserve the first observed appearance without inventing its date.
            events.append(make_event(entity, version, "new_project", "首次发现项目", "", [change("project_presence", None, "已公开")], discovery_type="observed"))
    return events


def source_meta(population, snapshot, version, coverage_start):
    rows = snapshot["events"] if population == "public" else snapshot["items"]
    dates = [day(row.get("updated_date") or row.get("up") or row.get("recommended_date")) for row in rows]
    if population == "public":
        for row in snapshot["funds"] + snapshot["events"]:
            dates.extend(day(row.get(field)) for field in ("accepted_date", "registered_date", "completion_date", "offering_start_date", "offering_end_date", "initial_issue_start", "initial_issue_end", "established_date", "establishment_announcement_date", "listing_date"))
            dates.extend(doc["date"] for doc in normalize_documents(row.get("documents"), snapshot["date"]))
    dates = [value for value in dates if value and value <= snapshot["date"]]
    raw = [{key: row[key] for key in ("raw_path", "sha256", "url") if key in row} for row in snapshot.get("source_versions", []) if row.get("raw_path")]
    entrypoints = {"public": ["https://www.sse.com.cn/reits/", "https://reits.szse.cn/"], "institutional": ["https://bond.sse.com.cn/bridge/information/", "https://bond.szse.cn/disclosure/progressinfo/index.html"], "ndrc": [snapshot.get("source_status", {}).get("NDRC", {}).get("source_url", "")]}
    return {"label": LABELS[population], "checked_at": version["collected_at"], "collected_at": version["collected_at"], "latest_official_date": max(dates, default=""), "coverage_start": coverage_start, "complete": True, "record_count": len(rows), "source_url": entrypoints[population][0], "source_urls": entrypoints[population], "snapshot_path": version["path"], "snapshot_sha256": version["sha256"], "raw_versions": raw, "source_versions": snapshot.get("source_versions", []), "refresh_batch": snapshot.get("refresh_batch"), "source_status": snapshot["source_status"], "status": "complete", "error": None, "last_successful_at": version["collected_at"], "revision_status": "官方来源当前完整快照；来源未统一提供初值或修订标识", "expected_latest_date": None, "is_lagging": None, "freshness_reason": "交易所及推荐名单不定期更新；完整成功核查时间和最新公开业务日期分别展示"}


def build_payload(versions, current, generated_at):
    """Pure calculation over validated retained input versions; no filesystem writes."""
    aliases = aliases_for_current(current)
    tracking_epoch = min((v["first_retained_at"] for rows in versions.values() for v in rows if v.get("first_retained_at")), default="")
    ledger, latest, sources, populations = {}, {}, {}, {}
    missing, revisions = [], []
    for population in FILES:
        previous_entities, previous_entity_versions, previous_version = {}, {}, None
        sequence = sorted(versions[population], key=lambda v: (v["collected_at"], v["sequence"]))
        for version in sequence:
            version = dict(version, tracking_epoch=tracking_epoch)
            rows = entities(population, version["snapshot"], aliases)
            if previous_version:
                absent = sorted(set(previous_entities) - set(rows))
                if absent:
                    missing.append({"population": population, "input_sha256": version["sha256"], "ids": absent, "treatment": "retain earlier evidence; absence does not imply termination"})
            for identity, entity in rows.items():
                old = previous_entities.get(identity)
                old_version = previous_entity_versions.get(identity) or previous_version
                for event in entity_events(entity, old, version, old_version):
                    event["previous_source_version"] = version_ref(old_version) if old and old_version else None
                    ledger.setdefault(event["id"], event)
                if old and old["project_name"] != entity["project_name"]:
                    revisions.append({"population": population, "entity_id": identity, "field": "name", "before": old["project_name"], "after": entity["project_name"], "input_sha256": version["sha256"], "treatment": "metadata revision, excluded from activity counts"})
                # Source pages can temporarily omit an attachment. Previously
                # disclosed files/nodes remain known when they return later.
                if old:
                    entity["documents"] = list({d["url"]: d for d in old["documents"] + entity["documents"]}.values())
                    entity["timeline"] = list({(r["date"], r["title"]): r for r in old["timeline"] + entity["timeline"]}.values())
                previous_entities[identity] = entity
                previous_entity_versions[identity] = version
            previous_version = version
        current_rows = entities(population, current[population], aliases)
        latest.update({population + "|" + key: {k: deepcopy(v) for k, v in row.items() if k not in ("state", "documents", "timeline", "milestones", "official_updated_date", "relation_revision_at")} for key, row in current_rows.items()})
        current_version = next(v for v in reversed(sequence) if v.get("is_current"))
        sources[population] = source_meta(population, current[population], current_version, sequence[0]["collected_at"])
        populations[population] = {"input_versions": len(sequence), "baseline_at": sequence[0]["collected_at"], "current_entities": len(current_rows)}
    # Only verified relation edges are attached. Matching changes create no events.
    for row in list(latest.values()):
        for related_id in list(row["related_entity_ids"]):
            for population in FILES:
                target = latest.get(population + "|" + related_id)
                if target is not None and row["id"] not in target["related_entity_ids"]:
                    target["related_entity_ids"].append(row["id"])
    matched_versions = [row for row in current["ndrc"].get("source_versions", []) if str(row.get("path", "")).endswith("public_reits.json")]
    sources["ndrc"]["matching_public_current"] = len(matched_versions) == 1 and matched_versions[0].get("sha256") == sources["public"]["snapshot_sha256"]
    sources["ndrc"]["matching_public_sha256"] = matched_versions[0].get("sha256") if len(matched_versions) == 1 else None
    events = sorted(ledger.values(), key=lambda e: (e["event_date"], e["detected_at"], e["id"]), reverse=True)
    for event in events:
        row = latest.get(event["population"] + "|" + event["entity_id"])
        if row:
            event["related_entity_ids"] = sorted(set(row["related_entity_ids"]))
    audit = {"tracking_started_at": min(meta["coverage_start"] for meta in sources.values()), "baseline_at": min(meta["coverage_start"] for meta in sources.values()), "populations": populations, "event_count": len(events), "observed_event_count": sum(not e["is_baseline"] for e in events), "baseline_event_count": sum(e["is_baseline"] for e in events), "event_counts_by_population": dict(Counter(e["population"] for e in events)), "event_counts_by_type": dict(Counter(e["event_type"] for e in events)), "missing_entities": missing, "metadata_revisions": revisions, "policy": {"baseline": "Initial and older-dated disclosures are timeline backfills, excluded from default activity feed", "official_dates": "Source business/publication date differs from first successful snapshot detection time", "status": "Updated date alone and derived stages are never status transitions", "fund_identity": "Canonical current code or exact filing linkage; identity consolidation is not a new fund", "absence": "Missing records never imply termination", "research_fields": "Classification, matching, research fields and review dates are excluded from progress", "history": "Explicit dates, official timelines and official workflow documents only; no inferred historical status chain"}}
    payload = {"schema_version": 1, "generated_at": generated_at, "as_of_date": day(generated_at), "sources": sources, "events": events, "projects": sorted(latest.values(), key=lambda r: (r["population"], r["id"])), "audit": audit}
    validate(payload)
    return payload


def validate(snapshot, root=None):
    if snapshot.get("schema_version") != 1 or not timestamp(snapshot.get("generated_at")) or not day(snapshot.get("as_of_date")):
        raise ValueError("Invalid project update schema or generation date")
    events, projects = snapshot.get("events"), snapshot.get("projects")
    if not isinstance(events, list) or not isinstance(projects, list):
        raise ValueError("Project events and current entities are required")
    if len({e["id"] for e in events}) != len(events):
        raise ValueError("Duplicate project update ID")
    if len({(p["population"], p["id"]) for p in projects}) != len(projects):
        raise ValueError("Duplicate current project identity")
    for event in events:
        if event.get("population") not in FILES or event.get("discovery_type") not in ("baseline", "observed") or event.get("is_baseline") != (event.get("discovery_type") == "baseline"):
            raise ValueError("Invalid event population/baseline classification")
        if not official_url(event.get("source_url")) or not timestamp(event.get("detected_at")) or not day(event.get("event_date")):
            raise ValueError("Event lacks official evidence or dated detection")
        if event.get("official_date") and (not day(event["official_date"]) or event["official_date"] > day(event["detected_at"])):
            raise ValueError("Future or invalid official event date")
        if not event.get("changes") or not re.fullmatch(r"[0-9a-f]{64}", event.get("source_version", {}).get("sha256", "")):
            raise ValueError("Missing event changes or input hash")
        if event["before"] != {c["field"]: c["before"] for c in event["changes"]} or event["after"] != {c["field"]: c["after"] for c in event["changes"]}:
            raise ValueError("Event before/after values do not reconcile to changes")
        if event["id"] != event_id(event):
            raise ValueError("Event identity does not reconcile to its evidence")
        if not all(official_url(doc.get("url")) for doc in event.get("documents", [])):
            raise ValueError("Nonofficial activity document")
    for population, filename in FILES.items():
        meta = snapshot.get("sources", {}).get(population, {})
        if meta.get("complete") is not True or not timestamp(meta.get("checked_at")) or not re.fullmatch(r"[0-9a-f]{64}", meta.get("snapshot_sha256", "")):
            raise ValueError("Missing complete bound source metadata")
        if root is not None and digest((Path(root) / "data" / filename).read_bytes()) != meta["snapshot_sha256"]:
            raise ValueError("Project updates are stale against current " + population + " snapshot")
    if root is not None:
        root = Path(root).resolve()
        current = {p: read(root / "data" / name) for p, name in FILES.items()}
        aliases = aliases_for_current(current)
        expected_projects = {(p, identity) for p in FILES for identity in entities(p, current[p], aliases)}
        if expected_projects != {(p["population"], p["id"]) for p in projects}:
            raise ValueError("Current project identities do not reconcile to source snapshots")
        checked_versions = {}
        for event in events:
            reference = event["source_version"]
            key = event["population"] + "|" + reference["sha256"]
            if key not in checked_versions:
                retained = (root / reference.get("retained_path", "")).resolve()
                if not retained.is_relative_to(root / "workpapers/project_updates/inputs") or not retained.is_file() or digest(retained.read_bytes()) != reference["sha256"]:
                    raise ValueError("Event source version is missing or its retained hash differs")
                checked_versions[key] = entities(event["population"], read(retained), aliases)
            entity = checked_versions[key].get(event["entity_id"])
            if entity is None:
                raise ValueError("Event entity differs from referenced source snapshot")
            for field, value in event["after"].items():
                if field in entity["state"] and value != entity["state"][field]:
                    raise ValueError("Event after value differs from referenced official source")
                if field == "timeline" and (event["official_date"], value) not in {(r["date"], r["title"]) for r in entity["timeline"]}:
                    raise ValueError("Event timeline title/date differs from referenced official source")
                if field == "documents" and (not isinstance(value, list) or value != [doc["title"] for doc in event["documents"]]):
                    raise ValueError("Event document titles differ from referenced disclosure documents")
            if any(doc["url"] not in {d["url"] for d in entity["documents"]} for doc in event["documents"]):
                raise ValueError("Event document differs from referenced official source")
            by_url = {doc["url"]: doc for doc in entity["documents"]}
            if any(doc != by_url[doc["url"]] for doc in event["documents"]):
                raise ValueError("Event document metadata differs from referenced official source")
            previous = event.get("previous_source_version")
            if previous:
                old_key = event["population"] + "|" + previous["sha256"]
                if old_key not in checked_versions:
                    retained = (root / previous.get("retained_path", "")).resolve()
                    if not retained.is_relative_to(root / "workpapers/project_updates/inputs") or not retained.is_file() or digest(retained.read_bytes()) != previous["sha256"]:
                        raise ValueError("Previous event source version is missing or its hash differs")
                    checked_versions[old_key] = entities(event["population"], read(retained), aliases)
                old_entity = checked_versions[old_key].get(event["entity_id"])
                if old_entity is None:
                    raise ValueError("Previous event entity differs from referenced source snapshot")
                if any(value is not None and field in old_entity["state"] and value != old_entity["state"][field] for field, value in event["before"].items()):
                    raise ValueError("Event before value differs from referenced official source")
    audit = snapshot.get("audit", {})
    if audit.get("event_count") != len(events) or audit.get("observed_event_count") != sum(not e["is_baseline"] for e in events) or audit.get("baseline_event_count") != sum(e["is_baseline"] for e in events):
        raise ValueError("Activity audit counts do not reconcile")
    return {"ok": True, "events": len(events), "observed_events": audit["observed_event_count"], "baseline_events": sum(e["is_baseline"] for e in events), "projects": len(projects), "unique_events": True, "official_sources_only": True, "current_input_hashes_match": root is not None}


def discover(root, population):
    paths = list((root / "snapshots").glob("*.json")) if population == "institutional" else list((root / "snapshots" / population).glob("*.json"))
    daily = root / "workpapers/daily_refresh"
    paths.extend(daily.glob("*/collected/" + FILES[population]))
    if population == "institutional":
        paths.extend(daily.glob("*/institutional_snapshots/*.json"))
    elif population == "public":
        paths.extend(daily.glob("*/public/snapshots/*.json"))
    return sorted(set(paths))


def build(root=ROOT, generated_at=None, rebuild=False):
    """Validate inputs and save immutable input registry, audited ledger and manifest.

    Rebuild replays retained successful input versions and repository snapshots;
    it never discards earlier successful source evidence.
    """
    root = Path(root).resolve()
    generated_at = timestamp(generated_at) if generated_at else datetime.now(BEIJING).isoformat(timespec="seconds")
    if not generated_at:
        raise ValueError("Timezone-aware generation time required")
    current = {}
    for population, filename in FILES.items():
        current[population] = read(root / "data" / filename)
        if current[population] is None:
            raise ValueError("Current complete snapshot is missing: " + filename)
        VALIDATORS[population](current[population])
    directory = root / "workpapers/project_updates"
    registry = read(directory / "input_index.json", {"schema_version": 1, "versions": []})
    records = {row["population"] + "|" + row["sha256"]: dict(row) for row in registry["versions"]}
    rejected, versions = [], {population: [] for population in FILES}
    for population, filename in FILES.items():
        for path in discover(root, population) + [root / "data" / filename]:
            data = path.read_bytes()
            sha, snapshot = digest(data), read(path)
            key = population + "|" + sha
            try:
                VALIDATORS[population](snapshot)
                collected_at = source_time(snapshot)
                if not collected_at:
                    raise ValueError("Missing timezone-aware collection timestamp")
                if day(collected_at) > day(generated_at):
                    raise ValueError("Input collection occurs after generation date")
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                if path == root / "data" / filename:
                    raise
                rejected.append({"population": population, "path": str(path.relative_to(root)), "sha256": sha, "reason": str(exc)})
                continue
            if key not in records:
                retained = "workpapers/project_updates/inputs/" + population + "/" + sha + ".json"
                destination = root / retained
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists() and digest(destination.read_bytes()) != sha:
                    raise ValueError("Retained input hash mismatch")
                if not destination.exists():
                    destination.write_bytes(data)
                records[key] = {"population": population, "path": str(path.relative_to(root)), "retained_path": retained, "sha256": sha, "collected_at": collected_at, "sequence": len(records), "first_retained_at": generated_at}
            if path == root / "data" / filename:
                records[key]["current_path"] = "data/" + filename
        current_sha = digest((root / "data" / filename).read_bytes())
        for record in records.values():
            if record["population"] != population:
                continue
            retained = root / record["retained_path"]
            if not retained.exists() or digest(retained.read_bytes()) != record["sha256"]:
                raise ValueError("Retained input is missing or changed: " + record["retained_path"])
            snapshot = read(retained)
            VALIDATORS[population](snapshot)
            version = dict(record, snapshot=snapshot, is_current=record["sha256"] == current_sha)
            if version["is_current"]:
                version["path"] = "data/" + filename
            versions[population].append(version)
    payload = build_payload(versions, current, generated_at)
    payload["audit"].update(rejected_inputs=rejected, retained_input_count=len(records))
    # Link exact source manifests, including collector batch records restored
    # from Actions artifacts, rather than calling normalized snapshots Raw.
    manifests = []
    for path in sorted((root / "data/source_manifest").rglob("*.json")):
        if "project_updates" in path.parts:
            continue
        manifest = read(path, {})
        if isinstance(manifest, dict):
            manifests.append((path, manifest))
    raw_checks = {}
    for population, meta in payload["sources"].items():
        matches = [(path, manifest) for path, manifest in manifests if meta["snapshot_sha256"] in (
            manifest.get("snapshot_sha256"), manifest.get("output_sha256", {}).get(population),
            manifest.get("source_snapshot_sha256", {}).get(population))]
        meta["source_manifest_paths"] = [str(path.relative_to(root)) for path, _ in matches]
        raw_references = {row["raw_path"]: row["sha256"] for row in meta["raw_versions"]}
        for _, manifest in matches:
            raw_references.update(manifest.get("raw_sha256", {}))
        verified, missing_raw, mismatched_raw = [], [], []
        for raw_path, expected_sha in raw_references.items():
            path = root / raw_path
            if not path.is_file():
                missing_raw.append(raw_path)
            elif digest(path.read_bytes()) != expected_sha:
                mismatched_raw.append(raw_path)
            else:
                verified.append(raw_path)
        if mismatched_raw:
            raise ValueError("Original Raw hash mismatch: " + ", ".join(mismatched_raw))
        meta["raw_retention"] = {"referenced_files": len(raw_references), "verified_local_files": len(verified), "missing_local_files": len(missing_raw), "status": "verified" if raw_references and not missing_raw else "partial" if raw_references else "original_collector_archive"}
        raw_checks[population] = {"referenced_files": len(raw_references), "verified_local_files": len(verified), "missing_local_paths": missing_raw, "mismatched_paths": mismatched_raw, "source_manifest_paths": meta["source_manifest_paths"], "treatment": "Retain exact validated input and collector provenance; missing original Raw must be retrieved from the named collector archive before claiming full Raw retention" if missing_raw or not raw_references else "Original Raw hashes verified against source manifests"}
    payload["audit"]["raw_retention"] = raw_checks
    # A failed latest attempt does not erase the last successful complete snapshot.
    for population in FILES:
        status_file = "ndrc_refresh_status.json" if population == "ndrc" else "refresh_status.json"
        status = read(root / "data" / status_file, {})
        attempted = timestamp(status.get("failed_at") or status.get("last_attempt_at") or status.get("completed_at") or status.get("started_at"))
        if status.get("status") not in (None, "complete") and attempted and attempted >= payload["sources"][population]["collected_at"]:
            payload["sources"][population].update(status=status["status"], error=status.get("error") or "最近一次核查未完成", last_attempted_at=attempted)
    audit = validate(payload, root)
    source_id = digest({p: [v["sha256"] for v in sorted(values, key=lambda v: (v["collected_at"], v["sequence"]))] for p, values in versions.items()})[:20]
    audit_path = "workpapers/project_updates/runs/" + source_id + "/audit.json"
    payload["audit"].update(audit_path=audit_path, input_index_path="workpapers/project_updates/input_index.json")
    audit.update({"generated_at": generated_at, "input_versions": [{k: v[k] for k in ("population", "path", "retained_path", "sha256", "collected_at")} for v in records.values()], "rejected_inputs": rejected, "missing_entities": payload["audit"]["missing_entities"], "metadata_revisions": payload["audit"]["metadata_revisions"], "raw_retention": raw_checks, "freshness": payload["sources"], "transformation": "scripts/project_updates.py: build_payload; official workflow fields and documents only", "output_path": "data/project_updates.json", "raw_trail": ["data/source_manifest/", "data/raw/", "raw/"], "exceptions": ["Historical snapshots failing current validators are rejected and listed", "Missing precise official status dates remain blank; collection time is shown separately", "NDRC matching can reference a prior public input; relation review creates no progress"]})
    # Preserve generated_at and byte identity when inputs/events/health are unchanged.
    old_payload = read(root / "data/project_updates.json")
    if old_payload:
        comparison = deepcopy(payload)
        comparison["generated_at"] = old_payload.get("generated_at")
        comparison["as_of_date"] = old_payload.get("as_of_date")
        if comparison == old_payload:
            return old_payload
    write(directory / "input_index.json", {"schema_version": 1, "versions": list(records.values()), "rejected_inputs": rejected})
    write(root / audit_path, audit)
    write(root / "data/project_updates.json", payload)
    write(root / "data/source_manifest/project_updates" / (source_id + ".json"), {"schema_version": 1, "generated_at": generated_at, "output_path": "data/project_updates.json", "output_sha256": digest((root / "data/project_updates.json").read_bytes()), "audit_path": audit_path, "input_index_path": "workpapers/project_updates/input_index.json", "sources": {key: {field: value for field, value in meta.items() if field in ("snapshot_path", "snapshot_sha256", "collected_at", "latest_official_date", "raw_versions")} for key, meta in payload["sources"].items()}})
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--check", action="store_true", help="Validate saved ledger against all three current snapshot hashes")
    args = parser.parse_args(argv)
    result = validate(read(args.root / "data/project_updates.json", {}), args.root) if args.check else validate(build(args.root, rebuild=args.rebuild), args.root)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
