"""Validate complete NDRC recommendations and evidence-backed exchange links."""
from __future__ import annotations

import json
import argparse
import hashlib
import math
import re
import sys
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collectors.ndrc_recommendations import BUSINESS_TYPES, MATCH_STATUSES, stable_id
from collectors.ndrc_matching import official_url as official_evidence_url
from collectors.public_reits import official_url


def valid_day(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat() == value
    except (TypeError, ValueError):
        return False


def valid_timestamp(value):
    try:
        date = datetime.fromisoformat(value)
        return date.utcoffset() is not None
    except (TypeError, ValueError):
        return False


def validate(data, public_snapshot=None):
    if data.get("schema_version") != 1 or not valid_day(data.get("date")) or not valid_timestamp(data.get("updated_at")):
        raise ValueError("Invalid NDRC schema/date")
    coverage, items = data.get("coverage", {}), data.get("items")
    if coverage.get("complete") is not True or not isinstance(items, list) or not items:
        raise ValueError("Complete nonempty NDRC snapshot required")
    if not data.get("source_status", {}).get("NDRC", {}).get("complete"):
        raise ValueError("NDRC source status does not establish completeness")
    if any(coverage.get(field) != len(items) for field in ("official_total", "raw_row_count", "item_count")):
        raise ValueError("NDRC coverage counts do not reconcile")
    if coverage.get("pages") != len(coverage.get("pages_checked", [])) or sum(row["row_count"] for row in coverage.get("pages_checked", [])) != len(items):
        raise ValueError("NDRC pagination does not reconcile")
    pages = coverage["pages_checked"]
    page_size = coverage.get("page_size")
    if (not isinstance(page_size, int) or isinstance(page_size, bool) or page_size <= 0 or
            [row.get("page_num") for row in pages] != list(range(1, len(pages) + 1)) or
            any(row["row_count"] != min(page_size, len(items) - (row["page_num"] - 1) * page_size) for row in pages)):
        raise ValueError("NDRC page sequence/sizes do not reconcile")
    identities = [row["id"] for row in items]
    if len(identities) != len(set(identities)):
        raise ValueError("Duplicate derived NDRC identity")
    events, funds = {}, {}
    if public_snapshot is not None:
        events = {row["id"]: row for row in public_snapshot.get("events", [])}
        events.update({row["record"]["id"]: row["record"] for row in public_snapshot.get("quality", {}).get("scope_exclusions", [])})
        funds = {row["id"]: row for row in public_snapshot.get("funds", [])}
    relation_count, relation_keys, lags = 0, set(), []
    for row in items:
        if row.get("source_id") is not None or row["id"] != stable_id(row.get("name"), row.get("applicant_region"), row.get("recommended_date")):
            raise ValueError("Invalid derived NDRC identity/source ID")
        if not all(isinstance(row.get(key), str) and row[key].strip() == row[key] and row[key] for key in ("name", "applicant_region", "industry_official")):
            raise ValueError("Missing official recommendation identity/category")
        if not valid_day(row.get("recommended_date")) or row["recommended_date"] > data["date"]:
            raise ValueError("Invalid recommendation date")
        value = row.get("proposed_fund_amount_yi")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError("Invalid recommendation amount")
        if not all(valid_timestamp(row.get(key)) for key in ("first_seen_at", "last_seen_at")):
            raise ValueError("Missing recommendation discovery timestamps")
        if datetime.fromisoformat(row["first_seen_at"]) > datetime.fromisoformat(row["last_seen_at"]) or datetime.fromisoformat(row["last_seen_at"]) > datetime.fromisoformat(data["updated_at"]):
            raise ValueError("Inconsistent recommendation discovery chronology")
        if row.get("discovery_type") not in ("baseline", "new"):
            raise ValueError("Invalid recommendation discovery type")
        if row.get("business_type") not in BUSINESS_TYPES or row.get("match_status") not in MATCH_STATUSES:
            raise ValueError("Invalid recommendation business/match status")
        source = urlparse(row.get("source_url", ""))
        if source.scheme != "https" or source.hostname not in ("reitsgl.tzxm.gov.cn", "59.252.66.79") or source.username or source.password:
            raise ValueError("Recommendation lacks official source URL")
        relations = row.get("relations")
        if not isinstance(relations, list) or not isinstance(row.get("candidates"), list):
            raise ValueError("Recommendation linkage collections required")
        if bool(relations) != (row["match_status"] == "confirmed"):
            raise ValueError("Confirmed recommendation relations/status do not reconcile")
        for relation in relations:
            eid = relation.get("exchange_event_id")
            if not eid or not official_url(relation.get("source_url")) or not relation.get("method") or not relation.get("note"):
                raise ValueError("Confirmed relation lacks event identity/evidence method")
            evidence = relation.get("evidence_urls", [])
            if relation.get("method") == "user_confirmed_association":
                confirmation = relation.get("confirmation", {})
                if (confirmation.get("source") != "user_confirmation" or
                        not valid_timestamp(confirmation.get("confirmed_at")) or not confirmation.get("scope")):
                    raise ValueError("User-confirmed relation lacks dated confirmation provenance")
            if not evidence or not all(official_evidence_url(url) for url in evidence):
                raise ValueError("Confirmed relation requires official evidence URLs")
            if relation.get("business_type") not in ("首发", "扩募", "新购入"):
                raise ValueError("Confirmed relation lacks exchange business type")
            key = (row["id"], eid)
            if key in relation_keys:
                raise ValueError("Duplicate recommendation-event relation")
            relation_keys.add(key)
            relation_count += 1
            if public_snapshot is not None:
                event = events.get(eid)
                if event is None or event.get("source_url") != relation["source_url"] or event.get("business_type") != relation["business_type"]:
                    raise ValueError("Relation differs from referenced exchange snapshot")
                if relation.get("fund_id") and relation["fund_id"] not in funds:
                    raise ValueError("Relation refers to unknown public fund")
                if event.get("fund_id") and relation.get("fund_id") != event["fund_id"]:
                    raise ValueError("Relation differs from exchange fund linkage")
                if (relation.get("accepted_date") or "") != (event.get("accepted_date") or ""):
                    raise ValueError("Relation acceptance date differs from exchange record")
            accepted = relation.get("accepted_date")
            if accepted:
                if not valid_day(accepted):
                    raise ValueError("Invalid exchange acceptance date")
                lag = (datetime.strptime(accepted, "%Y-%m-%d").date() - datetime.strptime(row["recommended_date"], "%Y-%m-%d").date()).days
                if lag < 0:
                    if (relation.get("days_to_acceptance") is not None or
                            relation.get("chronology_status") != "acceptance_precedes_recommendation" or
                            not relation.get("chronology_note")):
                        raise ValueError("Earlier acceptance requires reviewed chronology and no lead-time value")
                elif relation.get("days_to_acceptance") != lag:
                    raise ValueError("Recommendation-to-acceptance interval does not reconcile")
                lags.append(lag)
            elif relation.get("days_to_acceptance") is not None:
                raise ValueError("Acceptance interval requires acceptance date")
    dates = sorted(row["recommended_date"] for row in items)
    if coverage.get("earliest_recommended_date") != dates[0] or coverage.get("latest_recommended_date") != dates[-1]:
        raise ValueError("Recommendation coverage dates do not reconcile")
    versions = data.get("source_versions", [])
    raw_versions = [row for row in versions if row.get("raw_path")]
    if len(raw_versions) != coverage["pages"] or any(not re.fullmatch(r"[0-9a-f]{64}", row.get("sha256", "")) or row.get("tls_verified") is not True for row in raw_versions):
        raise ValueError("NDRC Raw versions/hashes/TLS evidence do not reconcile")
    quality = data.get("quality", {})
    try:
        normalized_checksum = sum((Decimal(str(row["proposed_fund_amount_yi"])) for row in items), Decimal(0))
        if (quality.get("raw_to_normalized_count_difference") != 0 or
                Decimal(quality.get("raw_amount_checksum_yi", "NaN")) != normalized_checksum or
                Decimal(quality.get("normalized_amount_checksum_yi", "NaN")) != normalized_checksum or
                Decimal(quality.get("raw_to_normalized_amount_difference_yi", "NaN")) != 0):
            raise ValueError("Raw-to-normalized amount/count checksums do not reconcile")
    except (InvalidOperation, TypeError) as exc:
        raise ValueError("Raw-to-normalized checksum required") from exc
    fresh = quality.get("freshness", [])
    if not fresh or fresh[0].get("latest_available_date") != dates[-1] or not all(key in fresh[0] for key in ("expected_latest_date", "is_lagging", "reason", "treatment")):
        raise ValueError("Recommendation freshness check required")
    changes = data.get("changes", {})
    if changes.get("baseline") and (changes.get("new_ids") or any(row["discovery_type"] != "baseline" for row in items)):
        raise ValueError("Initial backfill must not be reported as new")
    if not set(changes.get("new_ids", [])).issubset({row["id"] for row in items if row["discovery_type"] == "new"}):
        raise ValueError("New recommendation IDs do not reconcile")
    return {"ok": True, "items": len(items), "official_total": coverage["official_total"], "pages": coverage["pages"],
            "identities_unique": True, "raw_to_normalized_count_difference": 0, "derived_not_official_ids": True,
            "match_statuses": dict(Counter(row["match_status"] for row in items)), "relations": relation_count,
            "business_types": dict(Counter(row["business_type"] for row in items)),
            "earliest_recommended_date": dates[0], "latest_recommended_date": dates[-1],
            "negative_acceptance_intervals": sum(lag < 0 for lag in lags)}


def validate_files(snapshot_path, public_path=None, allow_stale_public=False):
    """Apply publication-only stale-input handling without weakening validate().

    A retained NDRC snapshot stays bound to the public input it was reviewed
    against. A newer public release can still publish, but is explicitly marked
    as a different version and is never called today's matched input.
    """
    data = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    if allow_stale_public and public_path is None:
        raise ValueError("--allow-stale-public requires a current public input")
    public_bytes = Path(public_path).read_bytes() if public_path else None
    public = json.loads(public_bytes) if public_bytes is not None else None
    if not allow_stale_public:
        return validate(data, public)
    versions = [row for row in data.get("source_versions", [])
                if str(row.get("path", "")).endswith("public_reits.json")]
    if (len(versions) != 1 or not re.fullmatch(r"[0-9a-f]{64}", versions[0].get("sha256", "")) or
            not valid_day(versions[0].get("date"))):
        raise ValueError("Exactly one dated, hashed public input version is required for retained matching")
    version = versions[0]
    current_sha = hashlib.sha256(public_bytes).hexdigest()
    same_version = version["sha256"] == current_sha
    result = validate(data, public if same_version else None)
    return {**result, "matching_public_current": same_version,
            "matching_public_date": version["date"], "matching_public_updated_at": version.get("updated_at"),
            "matching_public_sha256": version["sha256"], "current_public_sha256": current_sha}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("legacy_public_input", type=Path, nargs="?")
    parser.add_argument("--public-input", type=Path)
    parser.add_argument("--allow-stale-public", action="store_true",
                        help="Permit a retained reviewed snapshot against its recorded older public input version")
    args = parser.parse_args(argv)
    public_path = args.public_input or args.legacy_public_input
    if args.allow_stale_public and public_path is None:
        parser.error("--allow-stale-public requires --public-input")
    print(json.dumps(validate_files(args.snapshot, public_path, args.allow_stale_public), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
