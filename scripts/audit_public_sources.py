"""Reconcile the published public library to request manifests and a connector check."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):
    sys.path.insert(0, str(ROOT))
from scripts.validate_public_data import validate
from collectors.public_reits import write_json, ISSUED_STAGES


def walk_requests(value):
    if isinstance(value, list):
        for item in value:
            yield from walk_requests(item)
    elif isinstance(value, dict):
        if value.get("file") and value.get("sha256"):
            yield value
        else:
            for item in value.values():
                yield from walk_requests(item)


def audit(raw_dir):
    data = json.loads((ROOT / "data/public_reits.json").read_text(encoding="utf-8"))
    checked = validate(data)
    hashes, failures = [], []
    for manifest in sorted(Path(raw_dir).rglob("manifest*.json")):
        content = json.loads(manifest.read_text(encoding="utf-8"))
        for entry in walk_requests(content):
            file = Path(entry["file"])
            choices = [file] if file.is_absolute() else [manifest.parent / file, ROOT / file]
            file = next((f for f in choices if f.is_file()), choices[0])
            actual = hashlib.sha256(file.read_bytes()).hexdigest() if file.is_file() else None
            ok = actual == entry["sha256"]
            row = {"manifest": str(manifest.relative_to(ROOT)), "raw_file": str(file.relative_to(ROOT)) if file.is_relative_to(ROOT) else str(file),
                   "sha256": actual, "ok": ok, "url": entry.get("request_url") or entry.get("url")}
            hashes.append(row)
            if not ok:
                failures.append(row)
    if failures:
        raise ValueError("Raw hash reconciliation failed: " + json.dumps(failures, ensure_ascii=False))
    connector_file = ROOT / "data/raw/public/2026-10-15/connector/fuyao_reits_tickers.json"
    connector = json.loads(connector_file.read_text(encoding="utf-8"))
    meta_codes = {r["ticker"] for r in connector["data"]["item"]}
    issued_codes = {r["code"] for r in data["funds"] if r.get("code") and r["stage"] in ISSUED_STAGES}
    freshness = []
    for key, info in data["source_status"].items():
        latest = info.get("latest_filing_update") or info.get("latest_project_update")
        fresh = info.get("as_of_date") or info.get("fund_report_date")
        freshness.append({"series": key + "公募REITs完整列表", "source": info.get("exchange"),
                          "collected_at": info.get("collected_at"), "latest_available_date": fresh,
                          "latest_business_update": latest, "expected_date": data["date"],
                          "lagging": fresh != data["date"], "treatment": "业务日期与采集日期分开；无新申报不视为源滞后"})
    result = {"generated_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
              "validation": checked, "raw_hash_count": len(hashes), "raw_hash_failures": [],
              "freshness": freshness, "connector_crosscheck": {"source": "Fuyao MCP代码表", "raw_file": str(connector_file.relative_to(ROOT)),
                  "source_timestamp": connector["data"]["timestamp"], "connector_count": len(meta_codes),
                  "official_issued_count": len(issued_codes), "official_only_codes": sorted(issued_codes - meta_codes),
                  "connector_only_codes": sorted(meta_codes - issued_codes),
                  "treatment": "官方上市名录与合同生效公告控制范围；MCP代码表仅作交叉检查，不决定是否已发行"},
              "raw_hashes": hashes}
    write_json(ROOT / "workpapers/public/source_reconciliation.json", result)
    print(json.dumps({"raw_hash_count": len(hashes), "connector_crosscheck": result["connector_crosscheck"], "freshness": freshness}, ensure_ascii=False))


if __name__ == "__main__":
    audit(ROOT / "data/raw/public/2026-10-15")
