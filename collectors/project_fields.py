"""Versioned project research fields, separate from raw exchange records."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

CATALOG_FILE = Path(__file__).resolve().parents[1] / "config/project_field_scope.json"
PUBLIC_RESEARCH_FIELDS = (
    "issuer", "financial_advisor", "proposed_sale_amount_application_cny_100m",
    "proposed_sale_amount_feedback_cny_100m", "proposed_sale_amount_inquiry_cny_100m",
    "sale_amount_cny_100m", "external_loan_amount_cny_100m", "project_return_forecast", "guarantee_support",
)
INSTITUTIONAL_RESEARCH_FIELDS = ("approved_date", "issued_date", "is_issued")
DISCLOSURE_FIELDS = ("underlying_assets", "asset_type", "offering_start_date", "offering_end_date", "established_date")


def apply_field_scope(snapshot, population, previous=None):
    """Add explicit unknowns and retain prior research only on the same stable ID."""
    catalog = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    previous = previous or {}
    containers = ("funds", "events") if population == "public" else ("items",)
    fields = PUBLIC_RESEARCH_FIELDS if population == "public" else INSTITUTIONAL_RESEARCH_FIELDS
    for container in containers:
        old = {r["id"]: r for r in previous.get(container, [])}
        for record in snapshot.get(container, []):
            prior = old.get(record["id"], {})
            for key in fields:
                if record.get(key) is None or record.get(key) == "" or record.get(key) == []:
                    record[key] = prior.get(key)
            # Daily list refreshes do not erase reviewed disclosures. Core status
            # and source dates always remain those of the newly collected list.
            for key in DISCLOSURE_FIELDS:
                prefer_disclosed_asset = key == "asset_type" and record.get("classification_source") in (None, "keyword", "unknown")
                if prior.get("research_field_sources", {}).get(key) and (not record.get(key) or prefer_disclosed_asset):
                    record[key] = prior.get(key)
            if prior.get("research_field_sources"):
                retained = {key: value for key, value in prior["research_field_sources"].items()
                            if key in fields + DISCLOSURE_FIELDS and record.get(key) == prior.get(key)}
                record["research_field_sources"] = dict(retained, **record.get("research_field_sources", {}))
            if "field_availability" not in record and prior.get("field_availability"):
                record["field_availability"] = prior["field_availability"]
    if previous.get("enrichment") and "enrichment" not in snapshot:
        snapshot["enrichment"] = previous["enrichment"]
    snapshot["field_scope"] = {"version": catalog["schema_version"], "population": population,
                               "field_count": len(catalog[population]), "fields": catalog[population],
                               "updated_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")}
    if population == "institutional":
        snapshot.setdefault("quality", {})["content_sha256"] = hashlib.sha256(
            json.dumps(snapshot["items"], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return snapshot
