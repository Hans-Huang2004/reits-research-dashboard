"""Evidence-reviewed NDRC recommendation to exchange filing relationships.

Name similarity only produces candidates. Confirmed relationships are an explicit,
versioned review of the recommendation identity and exact exchange filing batch.
One recommendation may link to several filings, and one filing to several
recommendations. Standalone acquisitions remain separate from expansion offers.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
LINKS_PATH = ROOT / "config/ndrc_exchange_links.json"
GENERIC = ("封闭式", "基础设施", "证券投资基金", "商业不动产", "保障性", "新购入", "项目", "消费", "产业园", "仓储物流", "物流仓储", "新能源", "清洁能源", "高速公路", "租赁住房", "集团", "股份", "投资", "有限公司", "有限责任公司", "产业", "发展")


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def official_url(value):
    parsed = urlparse(str(value or ""))
    return parsed.scheme in {"https", "http"} and not parsed.username and not parsed.password and any(
        parsed.hostname == domain or (parsed.hostname or "").endswith("." + domain)
        for domain in ("sse.com.cn", "szse.cn", "csrc.gov.cn", "ndrc.gov.cn", "gov.cn")
    )


def identity(item):
    return {key: item.get(key, "") for key in ("name", "applicant_region", "recommended_date")}


def _public_evidence(evidence):
    """Keep the website evidence compact; full passages remain in workpapers."""
    keys = {"url", "title", "page", "asset_anchor", "note", "document_date"}
    return [{key: value for key, value in row.items() if key in keys} for row in evidence]


def _distinctive(value):
    value = re.sub(r"[\s\W_]+", "", str(value or ""))
    for word in GENERIC:
        value = value.replace(word, "")
    return value


def _grams(value, n=3):
    return {value[i:i+n] for i in range(max(0, len(value)-n+1))}


def exchange_records(snapshot, extra_events=None):
    rows = {row["id"]: deepcopy(row) for row in snapshot.get("events", [])}
    for exclusion in snapshot.get("quality", {}).get("scope_exclusions", []):
        row = exclusion.get("record", {})
        if row.get("id") and row.get("business_type") == "新购入":
            rows.setdefault(row["id"], deepcopy(row))
    for row in extra_events or []:
        if row.get("business_type") not in {"首发", "扩募", "新购入"}:
            raise ValueError("Unsupported extra exchange event business type")
        rows.setdefault(row["id"], deepcopy(row))
    return rows


def _candidate(item, event, fund=None):
    acquisition = item.get("business_type") == "新购入" or "新购入" in item.get("name", "")
    if acquisition and event.get("business_type") == "首发":
        return None
    if not acquisition and event.get("business_type") != "首发":
        return None
    if event.get("product_type") == "商业不动产REITs":
        # Older infrastructure recommendations must not drift to a later renamed
        # commercial property offering. Explicit reviewed evidence can link them.
        return None
    needle = _distinctive(item.get("name"))
    hay = _distinctive(" ".join(str(event.get(k, "")) for k in ("name", "origin", "underlying_assets")))
    grams = _grams(needle)
    shared = sorted(grams & _grams(hay))
    short_exact = 2 <= len(needle) <= 5 and needle in hay
    if not shared and not short_exact:
        return None
    ratio = 1.0 if short_exact else len(shared) / max(len(grams), 1)
    if ratio < .2 and len(shared) < 2:
        return None
    return {"exchange_event_id": event["id"], "event_name": event.get("name", ""),
            "fund_id": event.get("fund_id", ""), "fund_name": (fund or {}).get("name", ""),
            "fund_code": event.get("fund_code", ""), "exchange": event.get("exchange", ""),
            "business_type": event.get("business_type", ""), "accepted_date": event.get("accepted_date", ""),
            "current_stage": event.get("stage", event.get("official_status", "")),
            "source_url": event.get("source_url", ""), "score": round(ratio, 4),
            "method": "distinctive_name_or_asset_tokens_candidate_only",
            "shared_tokens": shared, "note": "名称或资产词仅用于筛选候选，尚未确认同一资产及申报批次。"}


def _relation(item, link, event, fund, checked_at):
    method = link.get("method", "official_document_asset_and_batch_review")
    if method not in {"official_document_asset_and_batch_review", "official_project_identity_review", "official_explicit_recommendation_reference", "user_confirmed_association"}:
        raise ValueError("Confirmation requires a declared evidence review method")
    confirmation = link.get("confirmation", {})
    if method == "user_confirmed_association":
        try:
            stamp = datetime.fromisoformat(confirmation.get("confirmed_at", ""))
        except (TypeError, ValueError) as exc:
            raise ValueError("User confirmation requires a dated provenance record") from exc
        if confirmation.get("source") != "user_confirmation" or stamp.utcoffset() is None or not confirmation.get("scope"):
            raise ValueError("User confirmation requires explicit provenance and scope")
    if not link.get("note", "").strip():
        raise ValueError("Confirmed link lacks its identity and batch explanation")
    evidence = link.get("evidence", [])
    if not evidence or any(not official_url(e.get("url")) or not e.get("note", "").strip() for e in evidence):
        raise ValueError("Confirmed link requires locatable official evidence and explanation")
    if link.get("business_type") != event.get("business_type"):
        raise ValueError("Reviewed business type changed for " + event["id"])
    if "expected_accepted_date" in link and link["expected_accepted_date"] != event.get("accepted_date", ""):
        raise ValueError("Reviewed acceptance date changed for " + event["id"])
    acquisition = "新购入" in item.get("name", "") or item.get("business_type") == "新购入"
    if acquisition and event.get("business_type") == "首发":
        raise ValueError("A new acquisition cannot be linked to the fund's initial filing")
    if not acquisition and event.get("business_type") != "首发":
        raise ValueError("An initial recommendation cannot be linked to a later acquisition batch")
    rec_date, accepted = item.get("recommended_date", ""), event.get("accepted_date", "")
    days = (date.fromisoformat(accepted) - date.fromisoformat(rec_date)).days if rec_date and accepted else None
    chronology = "normal" if days is None or days >= 0 else "acceptance_precedes_recommendation"
    chronology_note = link.get("chronology_note", "")
    if days is not None and days < 0:
        if not chronology_note:
            raise ValueError("Earlier acceptance requires an explicit chronology review: " + event["id"])
        # A negative interval is not an ex ante lead-time observation.
        days = None
    stage = event.get("stage", event.get("official_status", ""))
    if event.get("business_type") == "首发" and (fund or {}).get("stage") in {"已上市", "成立待上市"}:
        stage = fund["stage"]
    return {"exchange_event_id": event["id"], "event_name": event.get("name", ""),
            "exchange": event.get("exchange", ""), "fund_id": event.get("fund_id", ""),
            "fund_name": (fund or {}).get("name", ""), "fund_code": event.get("fund_code", ""),
            "business_type": event.get("business_type", ""), "accepted_date": accepted,
            "current_stage": stage, "official_status": event.get("official_status", ""),
            "source_url": event.get("source_url", ""), "evidence_urls": list(dict.fromkeys(e["url"] for e in evidence)),
            "evidence": _public_evidence(evidence), "method": method, "note": link["note"],
            "days_to_acceptance": days, "chronology_status": chronology,
            "chronology_note": chronology_note, "reviewed_at": link.get("reviewed_at", checked_at),
            **({"confirmation": {key: confirmation[key] for key in ("source", "confirmed_at", "scope")}}
               if method == "user_confirmed_association" else {})}


def match_recommendations(items, public_snapshot, overrides=None, extra_events=None, now=None):
    """Return ``(enriched_items, audit)`` without modifying any input.

    ``overrides`` contains ``reviews`` keyed by recommendation ID; every review
    includes an exact three-field ``identity`` guard and zero or more ``links``.
    Passing None loads the versioned repository review configuration.
    """
    now = now or datetime.now(ZoneInfo("Asia/Shanghai"))
    checked_at = now.isoformat(timespec="seconds") if hasattr(now, "isoformat") else str(now)
    if overrides is None:
        overrides = json.loads(LINKS_PATH.read_text()) if LINKS_PATH.exists() else {"reviews": {}}
    reviews = overrides.get("reviews", {})
    events = exchange_records(public_snapshot, extra_events)
    funds = {row["id"]: row for row in public_snapshot.get("funds", [])}
    ids = [row["id"] for row in items]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate recommendation identity")
    result, unused_reviews, chronology = [], sorted(set(reviews) - set(ids)), []
    for original in items:
        item = deepcopy(original)
        review = reviews.get(item["id"])
        if review and review.get("identity") != identity(item):
            raise ValueError("Recommendation identity changed after review: " + item["id"])
        relations, excluded = [], set((review or {}).get("rejected_event_ids", []))
        for link in (review or {}).get("links", []):
            eid = link.get("exchange_event_id")
            if eid not in events:
                raise ValueError("Reviewed exchange event missing: " + str(eid))
            event = events[eid]
            relation = _relation(item, link, event, funds.get(event.get("fund_id")), checked_at)
            relations.append(relation)
            if relation["chronology_status"] != "normal":
                chronology.append({"recommendation_id": item["id"], **relation})
        if len({row["exchange_event_id"] for row in relations}) != len(relations):
            raise ValueError("Duplicate reviewed relation: " + item["id"])
        linked = {row["exchange_event_id"] for row in relations}
        candidates = [row for event in events.values()
                      if event["id"] not in linked | excluded
                      for row in [_candidate(item, event, funds.get(event.get("fund_id")))] if row]
        for candidate_link in (review or {}).get("candidate_links", []):
            event = events.get(candidate_link.get("exchange_event_id"))
            if event is None or not candidate_link.get("note"):
                raise ValueError("Reviewed candidate lacks an exchange identity or explanation")
            fund = funds.get(event.get("fund_id"), {})
            candidates = [candidate for candidate in candidates if candidate["exchange_event_id"] != event["id"]]
            candidates.append({"exchange_event_id": event["id"], "event_name": event.get("name", ""),
                               "fund_id": event.get("fund_id", ""), "fund_name": fund.get("name", ""),
                               "fund_code": event.get("fund_code", ""), "exchange": event.get("exchange", ""),
                               "business_type": event.get("business_type", ""), "accepted_date": event.get("accepted_date", ""),
                               "current_stage": event.get("stage", event.get("official_status", "")),
                               "source_url": event.get("source_url", ""), "score": 1.0,
                               "method": "official_asset_identity_pending_recommendation_link",
                               "evidence": _public_evidence(candidate_link.get("evidence", [])), "note": candidate_link["note"]})
        candidates.sort(key=lambda row: (-row["score"], row["exchange_event_id"]))
        if review and review.get("outcome") == "unmatched":
            if relations or not review.get("note"):
                raise ValueError("Invalid reviewed unmatched decision")
            # A reviewed absence must not silently suppress a newly arrived event.
            candidates = [row for row in candidates if row["exchange_event_id"] not in review.get("reviewed_event_ids", [])]
        item["matched_business_types"] = sorted({relation["business_type"] for relation in relations})
        item["related_fund_clues"] = deepcopy((review or {}).get("related_fund_clues", []))
        for clue in item["related_fund_clues"]:
            if clue.get("fund_id") not in funds or not clue.get("note"):
                raise ValueError("Related fund clue lacks a known fund or explanation")
        if relations and item.get("business_type") == "待核实" and item["matched_business_types"] == ["首发"]:
            item.update(business_type="首发", business_type_basis="已核对关联交易所首发申报；推荐名单本身未单列业务类型。")
        elif "新购入" in item.get("name", ""):
            item["business_type_basis"] = "推荐项目名称明确包含新购入；关联交易所业务另列。"
        item.update(match_status="confirmed" if relations else "candidate" if candidates else "unmatched",
                    relations=relations, candidates=candidates[:5],
                    match_review={"status": "reviewed" if review else "pending", "note": (review or {}).get("note", ""),
                                  "reviewed_at": (review or {}).get("reviewed_at", "")})
        result.append(item)
    audit = {"schema_version": 1, "generated_at": checked_at,
             "input_recommendations_sha256": fingerprint(items), "input_public_snapshot_sha256": fingerprint(public_snapshot),
             "review_config_sha256": fingerprint(overrides), "extra_events_sha256": fingerprint(extra_events or []),
             "recommendation_count": len(result), "unique_recommendation_count": len(set(ids)),
             "exchange_event_count": len(events), "exchange_business_types": dict(Counter(e.get("business_type") for e in events.values())),
             "match_status_counts": dict(Counter(row["match_status"] for row in result)),
             "review_status_counts": dict(Counter(row["match_review"]["status"] for row in result)),
             "confirmed_relation_count": sum(len(row["relations"]) for row in result),
             "confirmation_basis_counts": dict(Counter(rel["method"] for row in result for rel in row["relations"])),
             "confirmed_exchange_event_count": len({rel["exchange_event_id"] for row in result for rel in row["relations"]}),
             "chronology_exceptions": chronology, "unused_review_ids": unused_reviews,
             "checks": {"unique_recommendation_ids": True, "exact_reviewed_recommendation_identity": True,
                        "official_asset_sources_for_every_relation": True,
                        "explicit_provenance_for_user_confirmations": True, "separate_initial_expansion_acquisition": True,
                        "negative_intervals_excluded_from_lead_time": True},
             "definition": "推荐记录与交易所具体申报事件多对多关联；名称相似仅生成候选；新购入单独保留；提前量只计算非负的推荐日至正式受理日间隔。"}
    return result, audit
