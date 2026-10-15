import unittest
from copy import deepcopy
from scripts.apply_official_enrichment import apply_supplements, sync_offering_phase, reviewed_source, ROOT
from collectors.project_fields import apply_field_scope


SOURCE = {"title": "基金份额发售公告", "url": "https://disc.static.szse.cn/official.pdf", "published_at": "2026-10-01", "page": 2, "excerpt": "本基金发售期限为2026年10月14日至20日"}


class EnrichmentTests(unittest.TestCase):
    def snapshot(self):
        return {"date": "2026-10-15", "quality": {}, "events": [{"id": "e1", "business_type": "首发", "fund_id": "f1", "official_status": "已注册", "updated_date": "2026-10-13", "stage": "获批待发行", "source_url": SOURCE["url"]}, {"id": "e2", "business_type": "扩募", "fund_id": "f1", "official_status": "已受理", "updated_date": "2026-10-14", "stage": "已受理", "source_url": SOURCE["url"]}], "funds": [{"id": "f1", "code": "180107", "event_ids": ["e1", "e2"], "stage": "获批待发行", "source_url": SOURCE["url"]}]}

    def test_first_offering_research_does_not_fill_expansion(self):
        snapshot = self.snapshot()
        supplement = {"events": {"e1": {"fields": {"external_loan_amount_cny_100m": 0}, "sources": {"external_loan_amount_cny_100m": [dict(SOURCE, unit="亿元")]}}}}
        audit = apply_supplements(snapshot, [supplement], "public", "2026-10-15T12:00:00+08:00")
        self.assertFalse(audit["rejected"])
        self.assertEqual(snapshot["funds"][0]["external_loan_amount_cny_100m"], 0)
        self.assertNotIn("external_loan_amount_cny_100m", snapshot["events"][1])

    def test_invalid_source_and_missing_units_are_rejected(self):
        snapshot = self.snapshot()
        supplement = {"events": {"e1": {"fields": {"financial_advisor": "某机构", "sale_amount_cny_100m": 4}, "sources": {"financial_advisor": [dict(SOURCE, url="https://example.com/post")], "sale_amount_cny_100m": [SOURCE]}}}}
        audit = apply_supplements(snapshot, [supplement], "public", "2026-10-15")
        self.assertEqual(len(audit["rejected"]), 2)
        self.assertNotIn("sale_amount_cny_100m", snapshot["events"][0])

    def test_sale_phase_uses_dated_evidence_status_remains_latest_list(self):
        snapshot = self.snapshot()
        supplement = {"events": {"e1": {"fields": {"offering_start_date": "2026-10-14", "offering_end_date": "2026-10-20", "official_status": "已受理"}, "sources": {"offering_start_date": [SOURCE], "offering_end_date": [SOURCE]}}}}
        apply_supplements(snapshot, [supplement], "public", "2026-10-15")
        sync_offering_phase(snapshot)
        self.assertEqual(snapshot["funds"][0]["stage"], "发售中")
        self.assertEqual(snapshot["events"][0]["stage"], "发售中")
        self.assertEqual(snapshot["events"][0]["official_status"], "已注册")
        self.assertEqual(snapshot["events"][1]["stage"], "已受理")

    def test_unknown_issuance_is_not_false_and_refresh_retains_evidence(self):
        snapshot = {"items": [{"id": "SSE_1", "source_url": SOURCE["url"]}]}
        supplement = {"items": {"SSE_1": {"fields": {}, "unavailable": {"is_issued": {"status": "not_found_in_text", "reason": "未取得实际发行证据"}}}}}
        apply_supplements(snapshot, [supplement], "institutional", "2026-10-15")
        self.assertNotIn("is_issued", snapshot["items"][0])
        self.assertEqual(snapshot["items"][0]["field_availability"]["is_issued"]["status"], "unverified")
        fresh = {"items": [{"id": "SSE_1", "status": "已通过", "up": "2026-10-16"}]}
        apply_field_scope(fresh, "institutional", deepcopy(snapshot))
        self.assertIsNone(fresh["items"][0]["is_issued"])
        self.assertEqual(fresh["items"][0]["field_availability"], snapshot["items"][0]["field_availability"])
        self.assertEqual(fresh["items"][0]["up"], "2026-10-16")

    def test_refresh_null_placeholders_keep_verified_values_but_false_zero_are_values(self):
        previous = {"items": [{"id": "SSE_1", "issued_date": "2026-08-01", "is_issued": True, "research_field_sources": {"issued_date": [SOURCE], "is_issued": [SOURCE]}}]}
        fresh = {"items": [{"id": "SSE_1", "issued_date": None, "is_issued": None}]}
        apply_field_scope(fresh, "institutional", previous)
        self.assertEqual(fresh["items"][0]["issued_date"], "2026-08-01")
        self.assertTrue(fresh["items"][0]["is_issued"])
        self.assertTrue(fresh["items"][0]["research_field_sources"]["is_issued"])
        changed = {"items": [{"id": "SSE_1", "is_issued": False}]}
        apply_field_scope(changed, "institutional", previous)
        self.assertFalse(changed["items"][0]["is_issued"])
        self.assertNotIn("is_issued", changed["items"][0]["research_field_sources"])

    def test_raw_relative_path_and_repo_absolute_path_remain_traceable(self):
        for path in ("data/raw/test.pdf", str(ROOT / "data/raw/test.pdf")):
            self.assertEqual(reviewed_source(dict(SOURCE, raw_file=path))["raw_file"], "data/raw/test.pdf")
        self.assertNotIn("raw_file", reviewed_source(dict(SOURCE, raw_file="../../outside.pdf")))

    def test_history_terminal_stage_is_not_replaced_by_sale_dates_or_parent_listing(self):
        snapshot = self.snapshot()
        fund, event = snapshot["funds"][0], snapshot["events"][0]
        fund.update(stage="终止", offering_start_date="2025-01-01", offering_end_date="2025-01-05", research_field_sources={"offering_start_date": [SOURCE]})
        event.update(stage="终止", official_status="终止(撤回)")
        sync_offering_phase(snapshot)
        self.assertEqual(fund["stage"], "终止")
        self.assertEqual(event["stage"], "终止")
        fund["stage"] = "已上市"
        sync_offering_phase(snapshot)
        self.assertEqual(event["stage"], "终止")


if __name__ == "__main__":
    unittest.main()
