"""Fallbacks must retry stale/failed collections without collecting twice daily."""
import copy
from datetime import datetime
import json
from pathlib import Path
import unittest

from scripts.refresh_due import refresh_due


class RefreshDueTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = json.loads((Path(__file__).resolve().parents[1] / "data/institutional.json").read_text())
        self.snapshot["date"] = "2026-10-15"
        self.snapshot["updated_at"] = "2026-10-15T08:18:00+08:00"
        self.snapshot["quality"]["link_validation"]["checked_at"] = "2026-10-15T08:19:00+08:00"
        self.now = datetime.fromisoformat("2026-10-15T09:15:00+08:00")

    def test_complete_today_skips_fallback(self):
        self.assertFalse(refresh_due(self.snapshot, self.now))

    def test_beijing_day_not_runner_utc_day(self):
        self.assertFalse(refresh_due(self.snapshot, datetime.fromisoformat("2026-10-15T01:15:00+00:00")))
        self.assertTrue(refresh_due(self.snapshot, datetime.fromisoformat("2026-10-15T16:01:00+00:00")))

    def test_stale_collection_cannot_be_hidden_by_classification(self):
        self.snapshot["updated_at"] = "2026-10-14T16:18:00+08:00"
        self.snapshot["classification_updated_at"] = "2026-10-15T08:30:00+08:00"
        self.assertTrue(refresh_due(self.snapshot, self.now))

    def test_invalid_missing_or_incomplete_snapshot_retries(self):
        cases = [None, {}, copy.deepcopy(self.snapshot), copy.deepcopy(self.snapshot)]
        cases[2]["coverage"]["complete"] = False
        cases[3]["items"].append(copy.deepcopy(cases[3]["items"][0]))
        for snapshot in cases:
            with self.subTest(snapshot_type=type(snapshot)):
                self.assertTrue(refresh_due(snapshot, self.now))

    def test_unverified_or_stale_links_retry(self):
        for change in ("count", "row", "date"):
            snapshot = copy.deepcopy(self.snapshot)
            if change == "count":
                snapshot["quality"]["link_validation"]["verified"] -= 1
            elif change == "row":
                snapshot["items"][0]["link_status"] = "constructed"
            else:
                snapshot["quality"]["link_validation"]["checked_at"] = "2026-10-14T08:19:00+08:00"
            with self.subTest(change=change):
                self.assertTrue(refresh_due(snapshot, self.now))

    def test_future_or_timezone_missing_retries(self):
        for value in ("2026-10-16T08:18:00+08:00", "2026-10-15T08:18:00"):
            self.snapshot["updated_at"] = value
            self.assertTrue(refresh_due(self.snapshot, self.now))

    def test_manual_force_can_refresh_today(self):
        self.assertTrue(refresh_due(self.snapshot, self.now, force=True))
