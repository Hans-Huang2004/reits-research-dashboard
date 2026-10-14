"""Network-free regression tests for the institutional REIT collector.

Run from the repository root: python -m unittest discover -s tests -v
"""

from __future__ import annotations

import copy
from contextlib import redirect_stderr
import io
import itertools
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from collectors import institutional as collector


FIXTURES = Path(__file__).parent / "fixtures"


def fixture(filename):
    return json.loads((FIXTURES / filename).read_text(encoding="utf-8"))


def sse_raw(source_id="213e64e05b2a4db8a98568e1740b5101", **changes):
    record = fixture("sse_institutional_page.json")["result"][0]
    record["BOND_NUM"] = source_id
    record.update(changes)
    return record


def szse_raw(source_id="5CCD030CB38E4250904A2C05D85E0342", **changes):
    record = fixture("szse_institutional_page.json")[0]["data"][0]
    record["zqmc"] = record["zqmc"].replace(
        "5CCD030CB38E4250904A2C05D85E0342", source_id
    )
    record.update(changes)
    return record


def requested_page(params):
    for field in ("pageHelp.pageNo", "pageNo", "pageno", "PAGENO"):
        if field in params:
            return int(params[field])
    raise AssertionError(f"No page number in parameters: {params!r}")


def sse_response(records, page=1, page_size=100):
    start = (page - 1) * page_size
    return {
        "result": copy.deepcopy(records[start:start + page_size]),
        "pageHelp": {
            "pageNo": page,
            "pageCount": (len(records) + page_size - 1) // page_size,
            "pageSize": page_size,
            "total": len(records),
        },
    }


def szse_response(records, page=1, page_size=20):
    start = (page - 1) * page_size
    return [{
        "metadata": {
            "catalogid": "xmjdxx",
            "pageno": page,
            "pagecount": (len(records) + page_size - 1) // page_size,
            "pagesize": page_size,
            "recordcount": len(records),
        },
        "data": copy.deepcopy(records[start:start + page_size]),
        "error": None,
    }]


class OfflineCase(unittest.TestCase):
    def setUp(self):
        self.no_network = patch.object(
            collector, "http_get_json",
            side_effect=AssertionError("Offline test attempted a network request"),
        )
        self.no_network.start()
        self.addCleanup(self.no_network.stop)


class NameAndIdentityTests(OfflineCase):
    def test_both_keywords_are_detected_without_double_counting(self):
        name = "某新能源持有型不动产资产支持专项计划（机构间REIT）"
        self.assertEqual(
            set(collector.matching_keywords(name)),
            {"持有型不动产", "机构间REIT"},
        )

    def test_institutional_match_accepts_spaces_and_case(self):
        for name in ("专项计划（机构间REITs）", "专项计划（机构间 reit）",
                     "专项计划（机构间\u3000REITS）"):
            with self.subTest(name=name):
                self.assertIn("机构间REIT", collector.matching_keywords(name))

    def test_unrelated_abs_does_not_match(self):
        self.assertEqual(collector.matching_keywords("某应收账款资产支持专项计划"), [])

    def test_szse_identity_comes_from_detail_attribute(self):
        raw = szse_raw()
        self.assertEqual(
            collector.parse_szse_identity(raw["zqmc"]),
            "5CCD030CB38E4250904A2C05D85E0342",
        )

    def test_szse_identity_unescapes_html_entities_and_normalizes_case(self):
        encoded = szse_raw()["zqmc"].replace("&", "&amp;").replace(
            "5CCD030CB38E4250904A2C05D85E0342",
            "5ccd030cb38e4250904a2c05d85e0342",
        )
        self.assertEqual(
            collector.parse_szse_identity(encoded),
            "5CCD030CB38E4250904A2C05D85E0342",
        )

    def test_missing_szse_identity_is_rejected(self):
        with self.assertRaises(ValueError):
            collector.parse_szse_identity("<a href='javascript:void(0)'>项目名称</a>")

    def test_unknown_asset_is_left_for_review(self):
        result = collector.classify_by_name("某集团持有型不动产资产支持专项计划")
        self.assertNotEqual(result["psub"], "综合业态")
        self.assertTrue("待" in result["psub"] or "待" in result["ptype"])
        self.assertIn("classification_source", result)
        self.assertNotEqual(result["classification_source"].lower(), "ai")

    def test_explicit_asset_keyword_provides_classification_reason(self):
        result = collector.classify_by_name("某光伏新能源持有型不动产资产支持专项计划")
        self.assertNotIn("待", result["psub"])
        self.assertTrue(result["pnote"])


class NormalizeAndMergeTests(OfflineCase):
    def test_real_sse_fixture_retains_project_identity_and_amount(self):
        result = collector.normalize_sse(sse_raw(), "机构间REIT")
        self.assertEqual(result["source_id"], "213e64e05b2a4db8a98568e1740b5101")
        self.assertEqual(result["amt"], 76.26)
        self.assertIn("铜陵长江公铁大桥", result["name"])
        self.assertIn("机构间REIT", result["match_keywords"])
        self.assertIn("bound_id=213e64e05b2a4db8a98568e1740b5101", result["source_url"])

    def test_real_szse_fixture_preserves_name_without_markup(self):
        result = collector.normalize_szse(szse_raw(), "机构间REIT")
        self.assertEqual(result["source_id"], "5CCD030CB38E4250904A2C05D85E0342")
        self.assertIn("TCL新能源", result["name"])
        self.assertNotIn("<a", result["name"])
        self.assertNotIn("<a", result["writer"])
        self.assertEqual(result["amt"], 9.72)
        self.assertIn("机构间REIT", result["match_keywords"])

    def test_missing_amount_remains_missing_instead_of_zero(self):
        result = collector.normalize_sse(sse_raw(PLAN_ISSUE_AMOUNT="-"), "机构间REIT")
        self.assertIsNone(result["amt"])

    def test_keyword_overlap_is_one_record_and_preserves_provenance(self):
        raw = sse_raw(AUDIT_NAME="某持有型不动产专项计划（机构间REIT）")
        holding = collector.normalize_sse(raw, "持有型不动产")
        institutional = collector.normalize_sse(raw, "机构间REIT")
        rows = collector.merge_records([holding, institutional, copy.deepcopy(holding)])
        self.assertEqual(len(rows), 1)
        self.assertEqual(set(rows[0]["match_keywords"]), {"持有型不动产", "机构间REIT"})
        self.assertEqual(set(rows[0]["query_keywords"]), {"持有型不动产", "机构间REIT"})

    def test_exchange_is_part_of_identity(self):
        shared_id = "5CCD030CB38E4250904A2C05D85E0342"
        rows = collector.merge_records([
            collector.normalize_sse(sse_raw(source_id=shared_id), "机构间REIT"),
            collector.normalize_szse(szse_raw(source_id=shared_id), "机构间REIT"),
        ])
        self.assertEqual(len(rows), 2)
        self.assertEqual(len({row["id"] for row in rows}), 2)

    def test_duplicate_retains_newest_status(self):
        old = collector.normalize_sse(sse_raw(AUDIT_NAME="某持有型不动产专项计划（机构间REIT）", PUBLISH_DATE="2026-09-01", AUDIT_STATUS="1"), "持有型不动产")
        new = collector.normalize_sse(sse_raw(AUDIT_NAME="某持有型不动产专项计划（机构间REIT）", PUBLISH_DATE="2026-10-01", AUDIT_STATUS="4"), "机构间REIT")
        for records in ([old, new], [new, old]):
            with self.subTest(order=[r["up"] for r in records]):
                rows = collector.merge_records(records)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["up"], "2026-10-01")
                self.assertEqual(rows[0]["status"], new["status"])
                self.assertEqual(set(rows[0]["match_keywords"]), {"持有型不动产", "机构间REIT"})

    def test_sort_and_keyword_order_are_deterministic(self):
        rows = [
            collector.normalize_sse(sse_raw(source_id="00000000000000000000000000000001", PUBLISH_DATE="2026-08-01"), "机构间REIT"),
            collector.normalize_sse(sse_raw(source_id="00000000000000000000000000000002", PUBLISH_DATE="2026-10-01"), "机构间REIT"),
            collector.normalize_sse(sse_raw(source_id="00000000000000000000000000000003", PUBLISH_DATE="2026-10-01"), "机构间REIT"),
        ]
        expected = collector.merge_records(rows)
        self.assertEqual(expected[0]["up"], "2026-10-01")
        self.assertEqual(expected[-1]["up"], "2026-08-01")
        for permutation in itertools.permutations(rows):
            self.assertEqual(collector.merge_records(list(permutation)), expected)


class PaginationTests(OfflineCase):
    def test_sse_reads_third_page_above_original_200_limit(self):
        records = [sse_raw(source_id=f"sse-{n:03d}") for n in range(205)]
        pages = []
        def request(url, params, referer):
            page = requested_page(params)
            pages.append(page)
            return sse_response(records, page=page)
        rows, metadata = collector.fetch_sse("持有型不动产", request=request)
        self.assertEqual(pages, [1, 2, 3])
        self.assertEqual(len(rows), 205)
        self.assertEqual(rows[-1]["BOND_NUM"], "sse-204")

    def test_szse_uses_server_pagination_not_requested_100(self):
        records = [szse_raw(source_id=f"{n:032X}") for n in range(121)]
        pages = []
        def request(url, params, referer):
            page = requested_page(params)
            pages.append(page)
            return szse_response(records, page=page, page_size=20)
        rows, metadata = collector.fetch_szse("机构间REIT", request=request)
        self.assertEqual(pages, list(range(1, 8)))
        self.assertEqual(len(rows), 121)
        self.assertEqual(collector.parse_szse_identity(rows[-1]["zqmc"]), f"{120:032X}")

    def test_sse_pagination_failure_raises_instead_of_truncating(self):
        records = [sse_raw(source_id=f"sse-{n:03d}") for n in range(205)]
        def request(url, params, referer):
            page = requested_page(params)
            if page == 2:
                raise OSError("simulated page timeout")
            return sse_response(records, page=page)
        with self.assertRaises((collector.CollectionError, OSError)):
            collector.fetch_sse("持有型不动产", request=request)

    def test_sse_repeated_first_page_is_rejected(self):
        records = [sse_raw(source_id=f"{n:032x}") for n in range(205)]
        def request(url, params, referer):
            return sse_response(records, page=1)
        with self.assertRaises(collector.CollectionError):
            collector.fetch_sse("持有型不动产", request=request)

    def test_total_changing_during_pagination_is_rejected(self):
        records = [sse_raw(source_id=f"{n:032x}") for n in range(205)]
        def request(url, params, referer):
            page = requested_page(params)
            response = sse_response(records, page=page)
            if page == 2:
                response["pageHelp"]["total"] += 1
            return response
        with self.assertRaises(collector.CollectionError):
            collector.fetch_sse("持有型不动产", request=request)

    def test_short_page_cannot_claim_complete_coverage(self):
        records = [sse_raw(source_id=f"{n:032x}") for n in range(205)]
        def request(url, params, referer):
            response = sse_response(records, page=requested_page(params))
            if requested_page(params) == 3:
                response["result"] = response["result"][:1]
            return response
        with self.assertRaises(collector.CollectionError):
            collector.fetch_sse("持有型不动产", request=request)

    def test_szse_error_payload_is_not_an_empty_success(self):
        def request(url, params, referer):
            return [{"metadata": {"pagecount": 1, "recordcount": 0},
                     "data": [], "error": "service unavailable"}]
        with self.assertRaises(collector.CollectionError):
            collector.fetch_szse("机构间REIT", request=request)


class SourceLinkTests(OfflineCase):
    def test_sse_source_is_exact_official_project_detail(self):
        link = collector.source_url("SSE", "213e64e05b2a4db8a98568e1740b5101")
        parsed = urlparse(link)
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "bond.sse.com.cn")
        self.assertIn(parsed.path, {"/bridge/information/index_detail.shtml", "/bridge2/information/index_detail.shtml"})
        self.assertEqual(parse_qs(parsed.query)["bound_id"], ["213e64e05b2a4db8a98568e1740b5101"])

    def test_szse_source_is_bound_to_project_id(self):
        source_id = "5CCD030CB38E4250904A2C05D85E0342"
        link = collector.source_url("SZSE", source_id)
        parsed = urlparse(link)
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "bond.szse.cn")
        self.assertEqual(parsed.path, "/disclosure/progressinfo/index.html")
        query = parse_qs(parsed.query)
        self.assertEqual(query["CATALOGID"], ["xmjdxx_xq"])
        self.assertEqual(query["TABKEY"], ["tab1"])
        self.assertEqual(query["xmbh"], [source_id])
        self.assertEqual(query["type"], ["2"])
        self.assertNotIn("javascript:", link)


class SnapshotSafetyTests(OfflineCase):
    def test_complete_collection_unions_four_queries_with_correct_counts(self):
        sse_common = sse_raw(source_id="00000000000000000000000000000001", AUDIT_NAME="新能源持有型不动产专项计划（机构间REIT）")
        sse_holding = sse_raw(source_id="00000000000000000000000000000002", AUDIT_NAME="新能源持有型不动产专项计划")
        sse_institutional = sse_raw(source_id="00000000000000000000000000000003", AUDIT_NAME="新能源专项计划（机构间REIT）")
        szse_common = szse_raw(source_id="00000000000000000000000000000004")
        szse_common["zqmc"] = szse_common["zqmc"].replace("不动产资产支持专项计划", "持有型不动产资产支持专项计划")
        szse_institutional = szse_raw(source_id="00000000000000000000000000000005")
        calls = []
        def request(url, params, referer):
            if "key" in params:
                keyword = params["key"]
                calls.append(("SSE", keyword))
                records = [sse_common, sse_holding] if keyword == "持有型不动产" else [sse_common, sse_institutional]
                return sse_response(records)
            if params.get("CATALOGID") == "xmjdxx_xq":
                return [{"data": [{"cxsqc": "测试计划管理人", "fxr": "测试原始权益人"}]}]
            keyword = params["txtZqmc"]
            calls.append(("SZSE", keyword))
            records = [szse_common] if keyword == "持有型不动产" else [szse_common, szse_institutional]
            return szse_response(records)
        snapshot = collector.collect_snapshot(request=request)
        self.assertEqual(calls, [("SSE", "持有型不动产"), ("SSE", "机构间REIT"),
                                 ("SZSE", "持有型不动产"), ("SZSE", "机构间REIT")])
        self.assertTrue(snapshot["coverage"]["complete"])
        self.assertEqual(snapshot["coverage"]["count"], 5)
        self.assertEqual(len(snapshot["items"]), 5)
        self.assertEqual(snapshot["source_status"]["SSE"]["total"], 3)
        self.assertEqual(snapshot["source_status"]["SZSE"]["total"], 2)
        by_source_id = {row["source_id"]: row for row in snapshot["items"]}
        self.assertEqual(set(by_source_id["00000000000000000000000000000001"]["query_keywords"]), {"持有型不动产", "机构间REIT"})
        self.assertEqual(set(by_source_id["00000000000000000000000000000004"]["match_keywords"]), {"持有型不动产", "机构间REIT"})
        self.assertTrue(all(row["source_url"] for row in snapshot["items"]))
        self.assertEqual(snapshot["quality"]["detail_warnings"], [])

    def test_partial_snapshot_cannot_overwrite_last_complete_file(self):
        partial = {
            "date": "2026-10-14", "items": [],
            "coverage": {"complete": False},
        }
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "institutional.json"
            original = b'{"date":"2026-10-13","records":[{"id":"last-good"}]}\n'
            path.write_bytes(original)
            with self.assertRaises(collector.CollectionError):
                collector.write_snapshot(partial, path)
            self.assertEqual(path.read_bytes(), original)

    def test_failed_keyword_refresh_rejects_collection(self):
        previous = {"date": "2026-10-13", "coverage": {"complete": True},
                    "items": [{"id": "last-good"}]}
        unchanged = copy.deepcopy(previous)
        calls = []
        def request(url, params, referer):
            calls.append(params.get("key"))
            if params.get("key") == "持有型不动产":
                records = [sse_raw(AUDIT_NAME="某持有型不动产专项计划")]
                return sse_response(records)
            raise OSError("simulated second keyword outage")
        with self.assertRaises(collector.CollectionError):
            collector.collect_snapshot(request=request, previous=previous)
        self.assertEqual(calls, ["持有型不动产", "机构间REIT"])
        self.assertEqual(previous, unchanged)

    def test_cli_failure_keeps_published_snapshot_and_creates_no_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "institutional.json"
            archive = Path(folder) / "snapshots"
            original = b'{"date":"2026-10-13","items":[{"id":"last-good"}]}\n'
            path.write_bytes(original)
            with patch.object(collector, "collect_snapshot", side_effect=collector.CollectionError("SZSE keyword query failed")), redirect_stderr(io.StringIO()) as errors:
                code = collector.main(["--output", str(path), "--archive-dir", str(archive)])
            self.assertEqual(code, 1)
            self.assertEqual(path.read_bytes(), original)
            self.assertFalse(archive.exists())
            self.assertIn("previous complete snapshot retained", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
