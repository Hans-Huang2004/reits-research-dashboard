"""Validate public REIT fund/filing identities and explicit expansion linkage."""
from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collectors.public_reits import INCLUDED_BUSINESS_TYPES, ISSUED_STAGES, official_url


def validate(data):
    if data.get("schema_version") != 1 or data.get("coverage", {}).get("complete") is not True:
        raise ValueError("Complete public snapshot required")
    funds, events = data.get("funds"), data.get("events")
    if not isinstance(funds, list) or not funds or not isinstance(events, list) or not events:
        raise ValueError("Official fund and filing populations are required")
    by_id = {f["id"]: f for f in funds}
    event_ids = {e["id"] for e in events}
    if len(by_id) != len(funds) or len(event_ids) != len(events):
        raise ValueError("Duplicate fund/filing identity")
    keys = [(f["exchange"], f["code"]) for f in funds if f.get("code")]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate official fund code")
    if data["coverage"].get("fund_count") != len(funds) or data["coverage"].get("event_count") != len(events):
        raise ValueError("Coverage counts do not reconcile")
    exclusions = data.get("quality", {}).get("scope_exclusions", [])
    excluded_ids = [row.get("record", {}).get("id") for row in exclusions]
    if (data["coverage"].get("excluded_event_count", 0) != len(exclusions) or
            len(excluded_ids) != len(set(excluded_ids)) or event_ids.intersection(excluded_ids) or
            any(row.get("record", {}).get("business_type") != "新购入" or not row.get("reason") for row in exclusions)):
        raise ValueError("Scope exclusions do not reconcile")
    for f in funds:
        if not f.get("name") or f["exchange"] not in ("上交所", "深交所") or not official_url(f.get("source_url")):
            raise ValueError("Missing official fund identity/source")
        if f.get("code") and not re.fullmatch(r"\d{6}", f["code"]):
            raise ValueError("Invalid fund code")
        if f.get("stage") == "已上市" and (not f.get("code") or not f.get("listing_date") or f["listing_date"] > data["date"]):
            raise ValueError("Listed fund lacks completed listing evidence")
        established = f.get("established_date") and f["established_date"] <= data["date"]
        announced = f.get("establishment_announcement_date") and f["establishment_announcement_date"] <= data["date"] and official_url(f.get("issuance_evidence_url"))
        if f.get("stage") == "成立待上市" and not (established or announced):
            raise ValueError("Established fund lacks completed establishment evidence")
        value = f.get("initial_raise_cny_100m")
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
            raise ValueError("Invalid actual initial offering amount")
        for eid in f.get("event_ids", []):
            if eid not in event_ids:
                raise ValueError("Fund refers to unknown filing")
    for e in events:
        f = by_id.get(e.get("fund_id"))
        if f is None or e["id"] not in f["event_ids"]:
            raise ValueError("Unlinked filing/expansion")
        if e["exchange"] != f["exchange"] or str(e.get("fund_code") or "") != str(f.get("code") or ""):
            raise ValueError("Cross-exchange or mismatched fund linkage")
        if e.get("business_type") not in INCLUDED_BUSINESS_TYPES or not e.get("official_status"):
            raise ValueError("Filing lacks business type or exact official status")
        if not official_url(e.get("source_url")) or not e.get("source_id"):
            raise ValueError("Filing lacks official identity/source")
    if data.get("quality", {}).get("unresolved_expansion_links"):
        raise ValueError("Unresolved expansion linkage")
    return {"ok": True, "funds": len(funds), "issued_funds": sum(f["stage"] in ISSUED_STAGES for f in funds),
            "filings": len(events), "business_types": dict(Counter(e["business_type"] for e in events)),
            "excluded_filings": len(exclusions),
            "fund_codes_unique": True, "filing_ids_unique": True, "unlinked_events": 0}


if __name__ == "__main__":
    # Also works as `python scripts/validate_public_data.py` from the checkout.
    print(json.dumps(validate(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))), ensure_ascii=False))
