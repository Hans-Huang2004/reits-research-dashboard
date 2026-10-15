"""Apply display field scope without changing any existing project values or source timestamps."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):
    sys.path.insert(0, str(ROOT))
from collectors.project_fields import apply_field_scope
from collectors.public_reits import write_json
from scripts.validate_data import validate as validate_institutional
from scripts.validate_public_data import validate as validate_public


def main():
    audits = []
    for name, filename, validator in (("public", "public_reits.json", validate_public),
                                       ("institutional", "institutional.json", validate_institutional)):
        path = ROOT / "data" / filename
        before_bytes = path.read_bytes()
        before = json.loads(before_bytes)
        after = apply_field_scope(deepcopy(before), name)
        containers = ("funds", "events") if name == "public" else ("items",)
        for container in containers:
            if [r["id"] for r in before[container]] != [r["id"] for r in after[container]]:
                raise ValueError("Field scope must not change identities, record counts or order")
            for old, new in zip(before[container], after[container]):
                if any(new.get(key) != value for key, value in old.items()):
                    raise ValueError("Existing project value changed during field scope migration")
        if before["updated_at"] != after["updated_at"]:
            raise ValueError("Field scope revision must retain source collection time")
        check = validator(after)
        write_json(path, after)
        audits.append({"population": name, "input_file": str(path.relative_to(ROOT)),
                       "input_sha256": hashlib.sha256(before_bytes).hexdigest(),
                       "output_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                       "preserved_source_timestamp": after["updated_at"], "field_count": after["field_scope"]["field_count"],
                       "existing_project_values_changed": 0, "project_values_imported_from_workbook": 0,
                       "validation": check})
    audit = {"generated_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"), "results": audits}
    write_json(ROOT / "workpapers/field_scope/migration_validation.json", audit)
    print(json.dumps(audit, ensure_ascii=False))


if __name__ == "__main__":
    main()
