"""Read only the reference headers, then generate the site's field catalog.

No project-level values from the reference workbook enter site data.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = [
    ("sequence", "integer", "基本资料", True),
    ("name", "text", "基本资料", True),
    ("business_type", "text", "基本资料", True),
    ("exchange", "text", "基本资料", True),
    ("product_type", "text", "基本资料", True),
    ("issuer", "text", "基本资料", True),
    ("manager", "text", "基本资料", True),
    ("financial_advisor", "text", "基本资料", False),
    ("proposed_sale_amount_application_cny_100m", "amount", "融资规模", False),
    ("proposed_sale_amount_feedback_cny_100m", "amount", "融资规模", False),
    ("proposed_sale_amount_inquiry_cny_100m", "amount", "融资规模", False),
    ("sale_amount_cny_100m", "amount", "融资规模", True),
    ("external_loan_amount_cny_100m", "amount", "融资规模", False),
    ("asset_type", "text", "资产与收益", True),
    ("underlying_assets", "text", "资产与收益", False),
    ("project_return_forecast", "text", "资产与收益", False),
    ("project_status", "text", "进度与增信", True),
    ("updated_date", "date", "进度与增信", True),
    ("guarantee_support", "text", "进度与增信", False),
]
INSTITUTIONAL = [
    ("sequence", "integer", "基本资料", True),
    ("name", "text", "基本资料", True),
    ("status", "text", "进度与发行", True),
    ("exchange", "text", "基本资料", True),
    ("declared_amount_cny_100m", "amount", "融资规模", True),
    ("asset_type", "text", "资产资料", True),
    ("underlying_assets", "text", "资产资料", False),
    ("origin", "text", "基本资料", True),
    ("manager", "text", "基本资料", True),
    ("accepted_date", "date", "进度与发行", True),
    ("approved_date", "date", "进度与发行", False),
    ("issued_date", "date", "进度与发行", False),
    ("is_issued", "boolean", "进度与发行", True),
]


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", type=Path)
    args = parser.parse_args()
    import openpyxl
    source = args.workbook.resolve()
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    now = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
    workbook = openpyxl.load_workbook(source, read_only=True, data_only=False)
    raw = []
    catalog = {"schema_version": 1, "public": [], "institutional": []}
    mapping = []
    for sheet_name, category, definitions in (("公募REITs项目", "public", PUBLIC), ("私募REITs项目", "institutional", INSTITUTIONAL)):
        sheet = workbook[sheet_name]
        sheet.reset_dimensions()
        cells = list(next(sheet.iter_rows(min_row=1, max_row=1)))
        populated = [cell for cell in cells if cell.value is not None]
        if len(populated) != len(definitions):
            raise ValueError("Reference header count changed: " + sheet_name)
        for cell, (key, value_type, group, core) in zip(populated, definitions):
            raw.append({"sheet": sheet_name, "coordinate": cell.coordinate, "value": cell.value,
                        "data_type": cell.data_type, "number_format": cell.number_format})
            label = str(cell.value).replace("\n", "").strip()
            if value_type == "amount" and "亿元" not in label:
                label += "（亿元）"
            spec = {"key": key, "label": label, "type": value_type, "unit": "亿元" if value_type == "amount" else "",
                    "group": group, "core": core}
            catalog[category].append(spec)
            mapping.append({"category": category, "sheet": sheet_name, "source_cell": cell.coordinate,
                            "source_header": cell.value, **spec,
                            "unit_policy": "站点规范单位为亿元；参考公募表头未显式写金额单位，不导入其数值" if category == "public" and value_type == "amount" else "按字段原意映射",
                            "value_policy": "只调整字段范围；原工作簿项目值不导入"})
    workbook.close()
    raw_path = ROOT / "data/raw/field_scope" / digest[:12] / "headers.json"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    if raw_path.exists():
        if json.loads(raw_path.read_text()) != raw:
            raise ValueError("Immutable header extraction differs from existing Raw version")
    else:
        write(raw_path, raw)
    write(ROOT / "data/source_manifest/field_scope" / (digest[:12] + ".json"), {
        "source_path": str(source), "source_sha256": digest, "source_bytes": source.stat().st_size,
        "extracted_at": now, "selected_ranges": ["公募REITs项目!A1:S1", "私募REITs项目!A1:M1"],
        "raw_path": str(raw_path.relative_to(ROOT)), "import_project_values": False})
    write(ROOT / "workpapers/field_scope" / digest[:12] / "mapping.json", mapping)
    write(ROOT / "config/project_field_scope.json", catalog)
    module = "/* Generated from config/project_field_scope.json; display fields only. */\n"
    module += "export const PUBLIC_FIELDS = " + json.dumps(catalog["public"], ensure_ascii=False, indent=2) + ";\n"
    module += "export const INSTITUTIONAL_FIELDS = " + json.dumps(catalog["institutional"], ensure_ascii=False, indent=2) + ";\n"
    (ROOT / "assets/project-field-catalog.js").write_text(module, encoding="utf-8")
    print(json.dumps({"public_fields": len(catalog["public"]), "institutional_fields": len(catalog["institutional"]),
                      "source_sha256": digest, "project_values_imported": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
