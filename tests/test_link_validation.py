"""Offline identity checks for per-project official detail links."""

from contextlib import redirect_stderr
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from collectors import institutional as collector
from tests.test_institutional import sse_raw, szse_raw


def snapshot_fixture():
    return {
        "items": [
            collector.normalize_sse(sse_raw(), "机构间REIT"),
            collector.normalize_szse(szse_raw(), "机构间REIT"),
        ],
        "coverage": {"complete": True, "count": 2},
        "quality": {},
    }


def matching_request(snapshot):
    by_id = {row["source_id"]: row for row in snapshot["items"]}
    def request(url, params, referer):
        if "audit_id" in params:
            row = by_id[params["audit_id"]]
            return {"result": [{"BOND_NUM": row["source_id"], "AUDIT_NAME": row["name"]}]}
        row = by_id[params["xmbh"]]
        return [{"data": [{"zqmc": row["name"]}]}]
    return request


class OfficialLinkIdentityTests(unittest.TestCase):
    def setUp(self):
        no_network = patch.object(
            collector, "http_get_json",
            side_effect=AssertionError("Offline test attempted a network request"),
        )
        no_network.start()
        self.addCleanup(no_network.stop)

    def test_both_exchanges_verify_exact_official_identity(self):
        snapshot = snapshot_fixture()
        checked = collector.verify_project_links(snapshot, request=matching_request(snapshot), workers=2)
        self.assertIs(checked, snapshot)
        self.assertTrue(all(row["link_status"] == "verified" for row in snapshot["items"]))
        self.assertTrue(all(row["link_checked_at"] for row in snapshot["items"]))
        self.assertEqual(snapshot["quality"]["link_validation"]["verified"], 2)
        self.assertEqual(snapshot["quality"]["link_validation"]["total"], 2)
        expected = hashlib.sha256(json.dumps(snapshot["items"], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        self.assertEqual(snapshot["quality"]["content_sha256"], expected)

    def test_sse_wrong_id_cannot_verify_merely_matching_name(self):
        snapshot = snapshot_fixture()
        original = copy.deepcopy(snapshot)
        correct = matching_request(snapshot)
        def request(url, params, referer):
            packet = correct(url, params, referer)
            if "audit_id" in params:
                packet["result"][0]["BOND_NUM"] = "00000000000000000000000000000000"
            return packet
        with self.assertRaises(collector.CollectionError):
            collector.verify_project_links(snapshot, request=request, workers=2)
        self.assertEqual(snapshot, original)

    def test_wrong_project_name_rejects_either_exchange(self):
        for exchange in ("上交所", "深交所"):
            with self.subTest(exchange=exchange):
                snapshot = snapshot_fixture()
                original = copy.deepcopy(snapshot)
                correct = matching_request(snapshot)
                def request(url, params, referer):
                    packet = correct(url, params, referer)
                    if exchange == "上交所" and "audit_id" in params:
                        packet["result"][0]["AUDIT_NAME"] = "另一个完全不同的项目"
                    if exchange == "深交所" and "xmbh" in params:
                        packet[0]["data"][0]["zqmc"] = "另一个完全不同的项目"
                    return packet
                with self.assertRaises(collector.CollectionError):
                    collector.verify_project_links(snapshot, request=request, workers=2)
                self.assertEqual(snapshot, original)

    def test_one_detail_timeout_does_not_partially_mark_rows_verified(self):
        snapshot = snapshot_fixture()
        original = copy.deepcopy(snapshot)
        correct = matching_request(snapshot)
        def request(url, params, referer):
            if "xmbh" in params:
                raise OSError("simulated detail API timeout")
            return correct(url, params, referer)
        with self.assertRaises((collector.CollectionError, OSError)):
            collector.verify_project_links(snapshot, request=request, workers=2)
        self.assertEqual(snapshot, original)

    def test_cli_link_failure_keeps_old_snapshot_and_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "institutional.json"
            archive = Path(folder) / "snapshots"
            original = b'{"date":"2026-10-13","items":[{"id":"last-good"}]}\n'
            output.write_bytes(original)
            with patch.object(collector, "collect_snapshot", return_value=snapshot_fixture()), patch.object(
                collector, "verify_project_links", side_effect=collector.CollectionError("detail identity mismatch")
            ), redirect_stderr(io.StringIO()) as errors:
                code = collector.main(["--output", str(output), "--archive-dir", str(archive), "--verify-links"])
            self.assertEqual(code, 1)
            self.assertEqual(output.read_bytes(), original)
            self.assertFalse(archive.exists())
            self.assertIn("previous complete snapshot retained", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
