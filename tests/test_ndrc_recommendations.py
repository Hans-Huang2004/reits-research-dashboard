import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from collectors.ndrc_recommendations import (
    CollectionError, SourceReader, build_snapshot, collect_pages, normalize_record,
    query_params, stable_id,
)
from scripts.validate_ndrc_data import validate, validate_files

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def record(name="甲产业园项目", **extra):
    return dict({"reitsProName": name, "mainDeclareUnit": "上海市", "industry": "园区基础设施",
                 "fundMoney": 12.34, "reportRecommendTime": "2026-09-10 00:00:00"}, **extra)


def page(rows, page_num=1, total=None, size=50):
    total = len(rows) if total is None else total
    return {"code": "SYS.200", "data": {"list": rows, "total": total, "pageNum": page_num,
            "pageSize": size, "pages": (total + size - 1) // size, "size": len(rows)}}


class Reader:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def request(self, page_num, page_size):
        self.calls.append((page_num, page_size))
        return self.pages[page_num - 1]


def snapshot(rows=None, previous=None, now=NOW):
    rows = rows or [record()]
    records, audit = collect_pages(Reader([page(rows)]))
    manifest = [{"raw_path": "data/raw/ndrc/test/page0001.json", "sha256": "a" * 64, "tls_verified": True}]
    return build_snapshot(records, audit, previous=previous, now=now, source_manifest=manifest)


class NdrcRecommendationTests(unittest.TestCase):
    def test_all_pages_and_official_total_reconcile(self):
        rows = [record("项目" + str(i)) for i in range(5)]
        reader = Reader([page(rows[:2], 1, 5, 2), page(rows[2:4], 2, 5, 2), page(rows[4:], 3, 5, 2)])
        result, audit = collect_pages(reader, 2)
        self.assertEqual(result, rows)
        self.assertEqual(reader.calls, [(1, 2), (2, 2), (3, 2)])
        self.assertEqual(audit["official_total"], 5)

    def test_partial_page_and_changed_total_are_rejected(self):
        rows = [record("项目" + str(i)) for i in range(3)]
        for pages in ([page(rows[:1], 1, 3, 2)],
                      [page(rows[:2], 1, 3, 2), page(rows[2:], 2, 4, 2)]):
            with self.subTest(pages=pages), self.assertRaises(CollectionError):
                collect_pages(Reader(pages), 2)

    def test_ignored_page_number_and_source_error_are_rejected(self):
        rows = [record("项目" + str(i)) for i in range(3)]
        pages = [page(rows[:2], 1, 3, 2), page(rows[:2], 1, 3, 2)]
        with self.assertRaisesRegex(CollectionError, "pagination"):
            collect_pages(Reader(pages), 2)
        for response in ({"code": "SYS.500"}, []):
            with self.assertRaises(CollectionError):
                collect_pages(Reader([response]))

    def test_derived_identity_ignores_amount_industry_and_page_position(self):
        first = normalize_record(record(), NOW)
        revised = normalize_record(record(industry="其他行业", fundMoney=15), NOW)
        self.assertEqual(first["id"], revised["id"])
        self.assertIsNone(first["source_id"])
        self.assertNotEqual(first["id"], normalize_record(record(mainDeclareUnit="江苏省"), NOW)["id"])
        self.assertEqual(first["id"], stable_id(first["name"], first["applicant_region"], first["recommended_date"]))

    def test_first_backfill_not_new_and_first_seen_survives_refresh(self):
        initial = snapshot()
        self.assertTrue(initial["changes"]["baseline"])
        self.assertEqual(initial["changes"]["new_ids"], [])
        refreshed = snapshot([record(), record("乙产业园项目")], previous=initial, now=NOW + timedelta(days=1))
        old_id = initial["items"][0]["id"]
        old = next(row for row in refreshed["items"] if row["id"] == old_id)
        new = next(row for row in refreshed["items"] if row["id"] != old_id)
        self.assertEqual(old["first_seen_at"], initial["items"][0]["first_seen_at"])
        self.assertEqual(old["discovery_type"], "baseline")
        self.assertEqual(new["discovery_type"], "new")
        self.assertEqual(refreshed["changes"]["new_ids"], [new["id"]])
        validate(refreshed)

    def test_amount_revision_audited_without_source_mutation(self):
        raw = record()
        before = deepcopy(raw)
        initial = snapshot([raw])
        refreshed = snapshot([record(fundMoney=15)], previous=initial, now=NOW + timedelta(days=1))
        self.assertEqual(raw, before)
        changes = refreshed["changes"]["field_changes"][0]["fields"]
        self.assertEqual(changes, {"proposed_fund_amount_yi": {"before": 12.34, "after": 15}})
        self.assertEqual(refreshed["changes"]["new_ids"], [])

    def test_duplicate_identity_and_disappearing_history_are_rejected(self):
        with self.assertRaisesRegex(CollectionError, "Duplicate"):
            snapshot([record(), record()])
        initial = snapshot([record(), record("乙产业园项目")])
        with self.assertRaisesRegex(CollectionError, "disappeared"):
            snapshot([record()], previous=initial)

    def test_business_type_requires_evidence_and_acquisition_preserves_label(self):
        self.assertEqual(normalize_record(record(), NOW)["business_type"], "待核实")
        self.assertEqual(normalize_record(record("甲产业园新购入项目"), NOW)["business_type"], "新购入")

    def test_invalid_source_values_rejected(self):
        for values in ({"fundMoney": True}, {"fundMoney": float("nan")}, {"fundMoney": -1},
                       {"reportRecommendTime": "2026-10-17 00:00:00"}, {"reportRecommendTime": "2026-02-30 00:00:00"},
                       {"mainDeclareUnit": ""}):
            with self.subTest(values=values), self.assertRaises(CollectionError):
                normalize_record(record(**values), NOW)

    def test_validator_rejects_false_confirmed_link_missing_raw_or_false_new(self):
        for mutate in (
                lambda data: data["items"][0].update(match_status="confirmed"),
                lambda data: data.update(source_versions=[]),
                lambda data: data["changes"].update(new_ids=[data["items"][0]["id"]]),
                lambda data: data["coverage"].update(official_total=2)):
            data = snapshot()
            mutate(data)
            with self.assertRaises(ValueError):
                validate(data)

    def test_source_reader_keeps_lossless_raw_exact_params_and_hash(self):
        raw = json.dumps(page([record()]), ensure_ascii=False, separators=(",", ":")).encode("utf-8")

        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *unused): return False
            def read(self): return raw

        with tempfile.TemporaryDirectory() as tmp, patch("urllib.request.urlopen", return_value=Response()) as opened, patch("collectors.ndrc_recommendations.PACER.wait"):
            reader = SourceReader(Path(tmp) / "raw", NOW)
            reader.request(1)
            entry = reader.manifest[0]
            self.assertEqual(Path(entry["raw_path"]).read_bytes(), raw)
            self.assertEqual(entry["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(entry["params"], query_params(1))
            self.assertTrue(entry["tls_verified"])
            self.assertTrue(opened.call_args.kwargs["context"].check_hostname)
            with self.assertRaises(FileExistsError):
                SourceReader(Path(tmp) / "raw", NOW)


class NdrcPublicationValidationTests(unittest.TestCase):
    def setUp(self):
        self.data = snapshot()
        self.url = "https://www.sse.com.cn/reits/info/index_detail.shtml?audit_id=123"
        self.data["items"][0].update(match_status="confirmed", business_type="首发", relations=[{
            "exchange_event_id": "SSE_123", "fund_id": "SSE_FUND_508001", "business_type": "首发",
            "source_url": self.url, "evidence_urls": [self.url], "method": "official_project_identity_review",
            "note": "资产与首发申报批次一致", "accepted_date": "2026-09-11", "days_to_acceptance": 1}])
        self.public = {"date": "2026-10-16", "updated_at": NOW.isoformat(timespec="seconds"),
                       "funds": [{"id": "SSE_FUND_508001"}], "events": [{"id": "SSE_123", "fund_id": "SSE_FUND_508001",
                           "business_type": "首发", "source_url": self.url, "accepted_date": "2026-09-11"}]}
        self.public_bytes = (json.dumps(self.public, ensure_ascii=False, indent=2) + "\n").encode()
        self.data["source_versions"].append({"path": "data/public_reits.json", "date": self.public["date"],
                                           "updated_at": self.public["updated_at"],
                                           "sha256": hashlib.sha256(self.public_bytes).hexdigest()})

    def files(self, directory, data=None, public_bytes=None):
        root = Path(directory)
        ndrc, public = root / "ndrc.json", root / "public_reits.json"
        ndrc.write_text(json.dumps(data or self.data, ensure_ascii=False))
        public.write_bytes(public_bytes if public_bytes is not None else self.public_bytes)
        return ndrc, public

    def test_same_public_version_still_runs_strict_cross_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            ndrc, public = self.files(directory)
            result = validate_files(ndrc, public, allow_stale_public=True)
            self.assertTrue(result["matching_public_current"])
            self.data["items"][0]["relations"][0].update(accepted_date="2026-09-12", days_to_acceptance=2)
            ndrc.write_text(json.dumps(self.data))
            with self.assertRaisesRegex(ValueError, "acceptance date differs"):
                validate_files(ndrc, public, allow_stale_public=True)

    def test_stale_public_retains_original_version_and_strict_function_stays_strict(self):
        newer = deepcopy(self.public)
        newer["date"] = "2026-10-17"
        newer["events"][0]["accepted_date"] = "2026-09-12"
        with tempfile.TemporaryDirectory() as directory:
            ndrc, public = self.files(directory, public_bytes=json.dumps(newer).encode())
            before = ndrc.read_bytes()
            with self.assertRaisesRegex(ValueError, "acceptance date differs"):
                validate(self.data, newer)
            with self.assertRaisesRegex(ValueError, "acceptance date differs"):
                validate_files(ndrc, public)
            result = validate_files(ndrc, public, allow_stale_public=True)
            self.assertFalse(result["matching_public_current"])
            self.assertEqual(result["matching_public_date"], "2026-10-16")
            self.assertEqual(result["matching_public_sha256"], hashlib.sha256(self.public_bytes).hexdigest())
            self.assertNotEqual(result["matching_public_sha256"], result["current_public_sha256"])
            self.assertEqual(ndrc.read_bytes(), before)

    def test_stale_public_still_rejects_invalid_retained_recommendations(self):
        self.data["items"][0]["relations"][0]["days_to_acceptance"] = 10
        with tempfile.TemporaryDirectory() as directory:
            ndrc, public = self.files(directory, public_bytes=b'{"date":"2026-10-17"}')
            with self.assertRaisesRegex(ValueError, "interval does not reconcile"):
                validate_files(ndrc, public, allow_stale_public=True)

    def test_missing_or_ambiguous_recorded_public_version_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            for versions in (self.data["source_versions"][:1], self.data["source_versions"] + [self.data["source_versions"][-1]]):
                data = deepcopy(self.data)
                data["source_versions"] = versions
                ndrc, public = self.files(directory, data=data)
                with self.assertRaisesRegex(ValueError, "public input version"):
                    validate_files(ndrc, public, allow_stale_public=True)
            with self.assertRaisesRegex(ValueError, "requires a current public input"):
                validate_files(ndrc, allow_stale_public=True)


if __name__ == "__main__":
    unittest.main()
