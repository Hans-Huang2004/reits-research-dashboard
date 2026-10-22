import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.refresh_all import record_failed_attempt
from scripts.validate_release import validate_release


class ReleaseValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "data").mkdir()
        # Intentionally historical: publication safety is not a freshness gate.
        self.batch = {"id": "last-good", "date": "2026-10-16",
                      "started_at": "2026-10-16T07:40:00+08:00",
                      "completed_at": "2026-10-16T07:50:00+08:00"}
        self.snapshots = {name: {"date": self.batch["date"], "coverage": {"complete": True},
                                  "refresh_batch": copy.deepcopy(self.batch)}
                          for name in ("institutional.json", "public_reits.json")}
        self.status = {"status": "complete", "attempt_ok": True, "date": self.batch["date"],
                       "batch_id": self.batch["id"], "started_at": self.batch["started_at"],
                       "completed_at": self.batch["completed_at"],
                       "last_successful_at": self.batch["completed_at"],
                       "last_attempt_at": self.batch["started_at"]}

    def write(self):
        for name, value in {**self.snapshots, "refresh_status.json": self.status}.items():
            (self.root / "data" / name).write_text(json.dumps(value), encoding="utf-8")

    def test_complete_historical_pair_is_publishable(self):
        self.write()
        report = validate_release(self.root)
        self.assertTrue(report["ok"])
        self.assertEqual(report["batch_id"], "last-good")
        self.assertFalse(report["retained_after_failed_attempt"])

    def test_mixed_batches_are_rejected_even_when_dates_match(self):
        self.snapshots["public_reits.json"]["refresh_batch"]["id"] = "other-batch"
        self.write()
        with self.assertRaisesRegex(ValueError, "refresh_batch metadata"):
            validate_release(self.root)

    def test_both_snapshot_dates_and_status_date_must_match_successful_batch(self):
        for target in (*self.snapshots, "refresh_status.json"):
            with self.subTest(target=target):
                value = self.status if target == "refresh_status.json" else self.snapshots[target]
                old = value["date"]
                value["date"] = "2026-10-17"
                self.write()
                with self.assertRaisesRegex(ValueError, "date differs"):
                    validate_release(self.root)
                value["date"] = old

    def test_all_refresh_batch_metadata_must_match_between_populations(self):
        for key, value in (("date", "2026-10-17"), ("started_at", "2026-10-16T07:41:00+08:00"),
                           ("completed_at", "2026-10-16T07:51:00+08:00")):
            with self.subTest(key=key):
                self.snapshots["public_reits.json"]["refresh_batch"] = {**self.batch, key: value}
                self.write()
                with self.assertRaisesRegex(ValueError, "refresh_batch metadata"):
                    validate_release(self.root)

    def test_missing_metadata_is_rejected_instead_of_accepting_only_the_id(self):
        for key in self.batch:
            with self.subTest(key=key):
                self.snapshots["institutional.json"]["refresh_batch"] = {k: v for k, v in self.batch.items() if k != key}
                self.write()
                with self.assertRaisesRegex(ValueError, "Missing or invalid"):
                    validate_release(self.root)

    def test_status_successful_batch_and_completion_must_match_both_snapshots(self):
        for key, value in (("batch_id", "failed-new-attempt"), ("started_at", "2026-10-16T07:41:00+08:00"),
                           ("completed_at", "2026-10-16T07:51:00+08:00"),
                           ("last_successful_at", "2026-10-17T09:02:00+08:00")):
            with self.subTest(key=key):
                old = self.status[key]
                self.status[key] = value
                self.write()
                with self.assertRaises(ValueError):
                    validate_release(self.root)
                self.status[key] = old

    def test_complete_pair_requires_explicit_complete_coverage_and_attempt_success(self):
        self.status["attempt_ok"] = False
        self.write()
        with self.assertRaisesRegex(ValueError, "attempt_ok=true"):
            validate_release(self.root)
        self.status["attempt_ok"] = True
        for coverage in ({}, {"complete": False}):
            self.snapshots["public_reits.json"]["coverage"] = coverage
            self.write()
            with self.assertRaisesRegex(ValueError, "complete retained snapshot"):
                validate_release(self.root)

    def test_failed_new_attempt_preserves_publishable_old_complete_pair(self):
        from datetime import datetime
        self.write()
        before = {name: (self.root / "data" / name).read_bytes() for name in self.snapshots}
        record_failed_attempt(self.root / "data", "attempt-new", "2026-10-17T09:00:00+08:00",
                              "source unavailable", datetime.fromisoformat("2026-10-17T09:02:00+08:00"))
        report = validate_release(self.root)
        self.assertEqual((report["status"], report["date"], report["batch_id"]),
                         ("failed", "2026-10-16", "last-good"))
        self.assertTrue(report["retained_after_failed_attempt"])
        self.assertEqual(report["last_attempt_batch_id"], "attempt-new")
        for name in self.snapshots:
            self.assertEqual(before[name], (self.root / "data" / name).read_bytes())

    def failed_status(self):
        return {**self.status, "status": "failed", "attempt_ok": False,
                "last_attempt_batch_id": "attempt-new", "last_attempt_at": "2026-10-17T09:00:00+08:00",
                "failed_at": "2026-10-17T09:02:00+08:00", "error": "source unavailable"}

    def test_failed_attempt_cannot_replace_successful_batch_identity_or_date(self):
        for key, value in (("batch_id", "attempt-new"), ("date", "2026-10-17"),
                           ("completed_at", "2026-10-17T09:02:00+08:00"),
                           ("last_successful_at", "2026-10-17T09:02:00+08:00")):
            with self.subTest(key=key):
                self.status = {**self.failed_status(), key: value}
                self.write()
                with self.assertRaises(ValueError):
                    validate_release(self.root)
                self.status = {"status": "complete", "attempt_ok": True, "date": self.batch["date"],
                               "batch_id": self.batch["id"], "started_at": self.batch["started_at"],
                               "completed_at": self.batch["completed_at"],
                               "last_successful_at": self.batch["completed_at"], "last_attempt_at": self.batch["started_at"]}

    def test_failed_status_requires_separate_attempt_metadata_and_failure_details(self):
        baseline = self.failed_status()
        for key in ("last_attempt_batch_id", "last_attempt_at", "failed_at", "error", "attempt_ok"):
            with self.subTest(key=key):
                self.status = {k: v for k, v in baseline.items() if k != key}
                self.write()
                with self.assertRaises(ValueError):
                    validate_release(self.root)

    def test_invalid_calendar_dates_naive_timestamps_and_reversed_times_are_rejected(self):
        for updates in ({"date": "2026-02-30"}, {"completed_at": "2026-10-16T07:50:00"},
                        {"started_at": "2026-10-16T07:51:00+08:00"},
                        {"completed_at": "2026-10-17T07:50:00+08:00"}):
            with self.subTest(updates=updates):
                for snapshot in self.snapshots.values():
                    snapshot["refresh_batch"] = {**self.batch, **updates}
                self.write()
                with self.assertRaises(ValueError):
                    validate_release(self.root)

    def test_failed_attempt_cannot_precede_last_success_or_its_failure_time(self):
        baseline = self.failed_status()
        for updates in ({"last_attempt_at": "2026-10-16T07:45:00+08:00"},
                        {"failed_at": "2026-10-17T08:59:00+08:00"}):
            with self.subTest(updates=updates):
                self.status = {**baseline, **updates}
                self.write()
                with self.assertRaisesRegex(ValueError, "Failed attempt timestamps"):
                    validate_release(self.root)

    def test_missing_input_and_invalid_status_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Cannot read release metadata"):
            validate_release(self.root)
        self.status["status"] = "in_progress"
        self.write()
        with self.assertRaisesRegex(ValueError, "complete or failed"):
            validate_release(self.root)

    def test_cli_returns_nonzero_for_mixed_pair_and_zero_for_complete_pair(self):
        script = Path(__file__).resolve().parents[1] / "scripts/validate_release.py"
        self.write()
        completed = subprocess.run([sys.executable, str(script), "--root", str(self.root)], capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(json.loads(completed.stdout)["ok"])
        self.snapshots["public_reits.json"]["refresh_batch"]["id"] = "mixed"
        self.write()
        completed = subprocess.run([sys.executable, str(script), "--root", str(self.root)], capture_output=True, text=True)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("Release validation failed", completed.stderr)


if __name__ == "__main__":
    unittest.main()
