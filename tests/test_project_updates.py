from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from scripts.project_updates import (FILES, build, build_payload, digest, entities, event_id, official_url,
                                     source_time, validate)

ROOT = Path(__file__).resolve().parents[1]


def integration_time(root, minutes=0):
    # Integration inputs are live repository snapshots. Their test clock must
    # advance with them; the unit fixtures above retain their fixed dates.
    latest = max(datetime.fromisoformat(source_time(json.loads((root / "data" / name).read_text())))
                 for name in FILES.values())
    return (latest + timedelta(days=1, minutes=minutes)).isoformat(timespec="seconds")


def example():
    fund = {"id": "SSE_FUND_508001", "code": "508001", "name": "甲基金", "exchange": "上交所",
            "source_url": "https://www.sse.com.cn/reits/", "event_ids": ["SSE_a"], "stage": "审核中"}
    filing = {"id": "SSE_a", "name": "甲基金", "exchange": "上交所", "business_type": "首发",
              "fund_id": fund["id"], "fund_code": "508001", "official_status": "已受理",
              "accepted_date": "2026-10-01", "updated_date": "2026-10-01",
              "source_url": "https://www.sse.com.cn/reits/info/index_detail.shtml?audit_id=a",
              "documents": []}
    institutional = {"id": "SSE_i", "name": "乙机构间REIT", "source_id": "i", "ex": "上交所",
                     "acc": "2026-10-01", "up": "2026-10-01", "status": "1",
                     "source_url": "https://bond.sse.com.cn/bridge/information/index_detail.shtml?bound_id=i"}
    recommendation = {"id": "NDRC_r", "name": "甲项目", "recommended_date": "2026-09-01",
                      "industry_official": "产业园", "business_type": "首发", "relations": [],
                      "source_url": "https://reitsgl.tzxm.gov.cn:8881/atom-ui/reits/"}
    base = {"date": "2026-10-14", "updated_at": "2026-10-14T09:00:00+08:00", "source_status": {}}
    public = dict(deepcopy(base), funds=[fund], events=[filing])
    inst = dict(deepcopy(base), items=[institutional])
    ndrc = dict(deepcopy(base), items=[recommendation], source_versions=[])
    ndrc["source_status"] = {"NDRC": {"source_url": recommendation["source_url"]}}
    return {"public": public, "institutional": inst, "ndrc": ndrc}


def version(population, snapshot, number, current=False):
    return {"population": population, "path": "snapshots/" + population + "/" + str(number) + ".json",
            "retained_path": "workpapers/project_updates/inputs/" + population + "/" + str(number) + ".json",
            "sha256": digest(snapshot), "collected_at": source_time(snapshot), "sequence": number,
            "snapshot": snapshot, "is_current": current}


def calculate(before, after=None):
    after = deepcopy(after or before)
    versions = {p: [version(p, before[p], 0, after[p] == before[p])] for p in FILES}
    for population in FILES:
        if after[population] != before[population]:
            versions[population].append(version(population, after[population], 1, True))
    return build_payload(versions, after, "2026-10-16T15:00:00+08:00")


def advance(snapshot, when="2026-10-15"):
    snapshot.update(date=when, updated_at=when + "T09:00:00+08:00")


class ProjectUpdateTests(unittest.TestCase):
    def test_initial_import_has_no_increment_and_never_invents_prior_status_chain(self):
        payload = calculate(example())
        self.assertTrue(payload["events"])
        self.assertTrue(all(e["is_baseline"] for e in payload["events"]))
        self.assertTrue(all(not e["is_incremental"] for e in payload["events"]))
        self.assertTrue(all(e["event_date"] == e["official_date"] for e in payload["events"]))
        self.assertFalse(any(e["event_type"] == "status_change" for e in payload["events"]))
        self.assertEqual(payload["audit"]["observed_event_count"], 0)

    def test_updated_date_alone_is_not_a_status_change(self):
        before = example(); after = deepcopy(before)
        advance(after["institutional"])
        after["institutional"]["items"][0]["up"] = "2026-10-15"
        self.assertEqual(calculate(before, after)["audit"]["observed_event_count"], 0)

    def test_real_status_transition_preserves_before_after_and_two_input_versions(self):
        before = example(); after = deepcopy(before)
        advance(after["institutional"])
        after["institutional"]["items"][0].update(status="2", up="2026-10-15")
        observed = [e for e in calculate(before, after)["events"] if not e["is_baseline"]]
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0]["before"], {"status": "已受理"})
        self.assertEqual(observed[0]["after"], {"status": "已反馈"})
        self.assertEqual(observed[0]["official_date"], "2026-10-15")
        self.assertEqual(observed[0]["event_date"], "2026-10-15")
        self.assertNotEqual(observed[0]["source_version"]["sha256"], observed[0]["previous_source_version"]["sha256"])

    def test_old_dated_status_transition_is_incremental_with_official_archive_date(self):
        before = example(); after = deepcopy(before)
        advance(after["institutional"])
        after["institutional"]["items"][0]["status"] = "4"
        revisions = [e for e in calculate(before, after)["events"] if e["event_type"] == "status_change"]
        self.assertEqual(len(revisions), 1)
        self.assertTrue(revisions[0]["is_incremental"])
        self.assertEqual(revisions[0]["official_date"], "2026-10-01")
        self.assertEqual(revisions[0]["event_date"], "2026-10-01")

    def test_same_day_repeated_status_transition_is_not_swallowed_by_fact_dedup(self):
        before = example(); current = deepcopy(before)
        inst_versions = []
        for index, status in enumerate(("1", "2", "1", "2")):
            snapshot = deepcopy(before["institutional"])
            snapshot["updated_at"] = "2026-10-14T" + str(9 + index).zfill(2) + ":00:00+08:00"
            snapshot["items"][0].update(status=status, up="2026-10-14")
            inst_versions.append(version("institutional", snapshot, index, index == 3))
        current["institutional"] = inst_versions[-1]["snapshot"]
        versions = {p: [version(p, before[p], 0, True)] for p in FILES}
        versions["institutional"] = inst_versions
        payload = build_payload(versions, current, "2026-10-16T15:00:00+08:00")
        observed = [e for e in payload["events"] if not e["is_baseline"]]
        self.assertEqual(len(observed), 3)
        self.assertEqual(len({e["id"] for e in observed}), 3)
        self.assertEqual(sum(e["after"].get("status") == "已反馈" for e in observed), 2)

    def test_new_project_without_official_date_remains_undated(self):
        before = example(); after = deepcopy(before)
        advance(after["institutional"])
        new = deepcopy(after["institutional"]["items"][0])
        new.update(id="SSE_missing_date", source_id="missing_date", acc="", up="2026-10-15")
        after["institutional"]["items"].append(new)
        observed = [e for e in calculate(before, after)["events"] if not e["is_baseline"]]
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0]["event_type"], "new_project")
        self.assertEqual(observed[0]["official_date"], "")
        self.assertEqual(observed[0]["event_date"], "")
        self.assertTrue(observed[0]["is_incremental"])
        self.assertEqual(observed[0]["detected_at"], "2026-10-15T09:00:00+08:00")

    def test_new_project_with_only_nonworkflow_prospectus_is_still_undated_increment(self):
        before = example(); after = deepcopy(before); advance(after["public"])
        new = deepcopy(after["public"]["events"][0])
        new.update(id="SSE_prospectus_only", accepted_date="", timeline=[], documents=[{
            "title": "基金招募说明书", "url": "https://static.sse.com.cn/prospectus.pdf", "date": "2026-10-01"}])
        after["public"]["events"].append(new)
        events = [e for e in calculate(before, after)["events"] if e["entity_id"] == new["id"]]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "new_project")
        self.assertTrue(events[0]["is_incremental"])
        self.assertEqual(events[0]["official_date"], "")
        self.assertEqual(events[0]["event_date"], "")

    def test_first_crawled_old_document_is_incremental_but_archives_official_date(self):
        before = example(); after = deepcopy(before)
        advance(after["public"])
        after["public"]["events"][0]["documents"] = [{"title": "关于问询函的回复", "url": "https://static.sse.com.cn/old.pdf", "date": "2026-10-01"}]
        event = next(e for e in calculate(before, after)["events"] if e["event_type"] == "documents_added")
        self.assertTrue(event["is_incremental"])
        self.assertEqual(event["official_date"], "2026-10-01")
        self.assertEqual(event["event_date"], "2026-10-01")
        self.assertEqual(event["detected_at"], "2026-10-15T09:00:00+08:00")

    def test_document_date_completion_or_correction_moves_only_its_own_archive_entry(self):
        for original_date in ("", "2026-10-01"):
            with self.subTest(original_date=original_date):
                before = example()
                before["public"]["events"][0]["documents"] = [
                    {"title": "关于问询函的回复甲", "url": "https://static.sse.com.cn/reply-a.pdf", "date": original_date},
                    {"title": "关于问询函的回复乙", "url": "https://static.sse.com.cn/reply-b.pdf", "date": original_date}]
                after = deepcopy(before); advance(after["public"])
                after["public"]["events"][0]["documents"][0]["date"] = "2026-10-03"
                payload = calculate(before, after)
                documents = [e for e in payload["events"] if e["event_type"] == "documents_added"]
                self.assertEqual(len(documents), 2)
                revised = next(e for e in documents if e["documents"][0]["url"].endswith("reply-a.pdf"))
                unchanged = next(e for e in documents if e["documents"][0]["url"].endswith("reply-b.pdf"))
                self.assertEqual(revised["official_date"], "2026-10-03")
                self.assertEqual(revised["event_date"], "2026-10-03")
                self.assertTrue(revised["is_incremental"])
                self.assertEqual(revised["detected_at"], "2026-10-15T09:00:00+08:00")
                self.assertEqual(revised["first_detected_at"], "2026-10-14T09:00:00+08:00")
                self.assertEqual(unchanged["official_date"], original_date)
                self.assertFalse(unchanged["is_incremental"])
                audit = payload["audit"]["document_revisions"]
                self.assertEqual(len(audit), 1)
                self.assertEqual(audit[0]["before"]["date"], original_date)
                self.assertEqual(audit[0]["after"]["date"], "2026-10-03")
                self.assertEqual(audit[0]["previous_event"]["source_version"]["sha256"], digest(before["public"]))
                self.assertEqual(audit[0]["source_version"]["sha256"], digest(after["public"]))
                versions = {p: [version(p, before[p], 0, p != "public")] for p in FILES}
                versions["public"].append(version("public", after["public"], 1))
                repeated = deepcopy(after); repeated["public"]["updated_at"] = "2026-10-16T09:00:00+08:00"
                repeated["public"]["date"] = "2026-10-16"
                versions["public"].append(version("public", repeated["public"], 2, True))
                rebuilt = build_payload(versions, repeated, "2026-10-16T15:00:00+08:00")
                self.assertEqual(rebuilt["events"], payload["events"])
                self.assertEqual(rebuilt["audit"]["document_revisions"], audit)

    def test_same_document_on_fund_and_filing_is_only_counted_on_filing(self):
        data = example()
        doc = {"title": "关于问询函的回复", "url": "https://static.sse.com.cn/reply.pdf", "date": "2026-10-01"}
        data["public"]["funds"][0]["documents"] = [doc]
        data["public"]["events"][0]["documents"] = [doc]
        events = [e for e in calculate(data)["events"] if e["event_type"] == "documents_added"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["entity_kind"], "filing")

    def test_old_timeline_and_new_entity_facts_all_enter_first_crawl_increment(self):
        before = example(); after = deepcopy(before); advance(after["public"])
        after["public"]["events"][0]["timeline"] = [{"title": "已反馈", "date": "2026-10-03"}]
        new = deepcopy(after["public"]["events"][0])
        new.update(id="SSE_b", name="新增申报", accepted_date="2026-09-10", updated_date="2026-10-01",
                   timeline=[], documents=[{"title": "关于反馈意见的回复", "url": "https://static.sse.com.cn/new-old.pdf", "date": "2026-09-20"}])
        after["public"]["events"].append(new)
        events = [e for e in calculate(before, after)["events"] if e["is_incremental"]]
        self.assertEqual(len(events), 3)
        self.assertEqual({e["official_date"] for e in events}, {"2026-10-03", "2026-09-10", "2026-09-20"})
        self.assertTrue(all(e["event_date"] == e["official_date"] for e in events))
        self.assertTrue(all(e["detected_at"] == "2026-10-15T09:00:00+08:00" for e in events))

    def test_reappearing_facts_and_unrelated_snapshot_edits_do_not_duplicate_events(self):
        before = example(); current = deepcopy(before)
        snapshots = []
        doc = {"title": "关于问询函的回复", "url": "https://static.sse.com.cn/reply.pdf", "date": "2026-10-01"}
        for index in range(4):
            snapshot = deepcopy(before["public"])
            snapshot["updated_at"] = "2026-10-15T" + str(9 + index).zfill(2) + ":00:00+08:00"
            snapshot["date"] = "2026-10-15"
            snapshot["funds"][0]["research_note"] = "无关资料" + str(index)
            if index in (1, 3):
                snapshot["funds"][0]["established_date"] = "2026-10-02"
                snapshot["events"][0]["documents"] = [deepcopy(doc)]
            if index == 1:
                snapshot["funds"][0]["offering_start_date"] = "2026-10-02"
            snapshots.append(version("public", snapshot, index, index == 3))
        current["public"] = snapshots[-1]["snapshot"]
        versions = {p: [version(p, before[p], 0, True)] for p in FILES}
        versions["public"] = snapshots
        payload = build_payload(versions, current, "2026-10-16T15:00:00+08:00")
        increments = [e for e in payload["events"] if e["is_incremental"]]
        self.assertEqual(len(increments), 2)
        self.assertEqual(sum("established_date" in e["after"] for e in payload["events"]), 1)
        self.assertEqual({e["detected_at"] for e in increments}, {"2026-10-15T10:00:00+08:00"})
        self.assertEqual(len({e["id"] for e in payload["events"]}), len(payload["events"]))

    def test_rebuild_does_not_redate_existing_crawl_increments_to_migration_day(self):
        before = example(); after = deepcopy(before); advance(after["public"])
        after["public"]["events"][0]["documents"] = [{"title": "关于问询函的回复", "url": "https://static.sse.com.cn/old.pdf", "date": "2026-10-01"}]
        versions = {p: [version(p, before[p], 0, p != "public")] for p in FILES}
        versions["public"].append(version("public", after["public"], 1, True))
        first = build_payload(versions, after, "2026-10-16T15:00:00+08:00")
        migrated = build_payload(versions, after, "2026-10-18T15:00:00+08:00")
        self.assertEqual(first["events"], migrated["events"])
        self.assertFalse(any(e["detected_at"].startswith("2026-10-18") for e in migrated["events"]))

    def test_validation_rejects_collection_date_fallback_and_nonboolean_increment(self):
        payload = calculate(example())
        forged = deepcopy(payload)
        forged["events"][0]["event_date"] = "2026-10-14"
        with self.assertRaisesRegex(ValueError, "archive date"):
            validate(forged)
        forged = deepcopy(payload)
        forged["events"][0]["is_incremental"] = 0
        with self.assertRaisesRegex(ValueError, "increment flag"):
            validate(forged)

    def test_fund_identity_consolidation_does_not_create_new_fund(self):
        before = example(); after = deepcopy(before)
        before["public"]["funds"][0].update(id="SSE_APPLICANT_a", code="")
        before["public"]["events"][0].update(fund_id="SSE_APPLICANT_a", fund_code="")
        advance(after["public"])
        payload = calculate(before, after)
        self.assertEqual(payload["audit"]["observed_event_count"], 0)
        self.assertFalse(any(e["event_type"] == "new_fund" for e in payload["events"]))
        funds = [p for p in payload["projects"] if p["entity_kind"] == "fund"]
        self.assertEqual(len(funds), 1)
        self.assertEqual(funds[0]["id"], "SSE_FUND_508001")

    def test_research_fields_and_matching_edits_do_not_generate_progress(self):
        before = example(); after = deepcopy(before)
        advance(after["public"]); advance(after["ndrc"])
        after["public"]["events"][0].update(asset_type="消费", proposed_sale_amount_application_cny_100m=9.0)
        after["ndrc"]["items"][0]["relations"] = [{"exchange_event_id": "SSE_a", "fund_id": "SSE_FUND_508001"}]
        self.assertEqual(calculate(before, after)["audit"]["observed_event_count"], 0)

    def test_official_name_and_institutional_amount_change_is_separate_revision_with_units(self):
        before = example(); before["institutional"]["items"][0]["amt"] = 10
        after = deepcopy(before); advance(after["institutional"])
        after["institutional"]["items"][0].update(name="乙机构间REIT更新名称", amt=12, up="2026-10-15")
        observed = [e for e in calculate(before, after)["events"] if not e["is_baseline"]]
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0]["event_type"], "revision")
        self.assertEqual(observed[0]["title"], "资料修订")
        self.assertEqual(observed[0]["before"]["amt"], 10)
        self.assertEqual(observed[0]["after"]["amt"], 12)
        self.assertIn("亿元", next(c["label"] for c in observed[0]["changes"] if c["field"] == "amt"))

    def test_old_dated_ndrc_core_change_is_incremental_official_revision(self):
        before = example()
        before["ndrc"]["items"][0].update(proposed_fund_amount_yi=10, applicant_region="甲市")
        after = deepcopy(before); advance(after["ndrc"])
        after["ndrc"]["items"][0].update(proposed_fund_amount_yi=12, applicant_region="乙市", industry_official="租赁住房")
        revisions = [e for e in calculate(before, after)["events"] if e["event_type"] == "revision"]
        self.assertEqual(len(revisions), 1)
        self.assertTrue(revisions[0]["is_incremental"])
        self.assertEqual(revisions[0]["event_date"], "2026-09-01")
        self.assertEqual(set(revisions[0]["after"]), {"proposed_fund_amount_yi", "applicant_region", "industry_official"})

    def test_later_matching_review_is_audit_metadata_without_business_event(self):
        before = example(); after = deepcopy(before); advance(after["ndrc"])
        after["ndrc"]["matching_updated_at"] = "2026-10-15T10:00:00+08:00"
        after["ndrc"]["items"][0]["relations"] = [{"exchange_event_id": "SSE_a", "fund_id": "SSE_FUND_508001"}]
        versions = {p: [dict(version(p, before[p], 0, p != "ndrc"), first_retained_at="2026-10-14T12:00:00+08:00")] for p in FILES}
        versions["ndrc"].append(dict(version("ndrc", after["ndrc"], 1, True), first_retained_at="2026-10-15T12:00:00+08:00"))
        payload = build_payload(versions, after, "2026-10-16T15:00:00+08:00")
        self.assertFalse(any(e["is_incremental"] for e in payload["events"]))
        self.assertFalse(any("related_entity_ids" in e["after"] for e in payload["events"]))
        audit = next(row for row in payload["audit"]["metadata_revisions"] if row["field"] == "related_entity_ids")
        self.assertEqual(audit["reviewed_at"], "2026-10-15T10:00:00+08:00")
        self.assertEqual(audit["collected_at"], "2026-10-15T09:00:00+08:00")

    def test_missing_entity_does_not_imply_termination(self):
        before = example(); after = deepcopy(before)
        advance(after["institutional"]); after["institutional"]["items"] = []
        payload = calculate(before, after)
        self.assertEqual(payload["audit"]["observed_event_count"], 0)
        self.assertEqual(payload["audit"]["missing_entities"][0]["ids"], ["SSE_i"])
        self.assertFalse(any("终止" in e["title"] for e in payload["events"]))

    def test_establishment_announcement_does_not_become_establishment_date(self):
        before = example(); after = deepcopy(before)
        advance(after["public"])
        after["public"]["funds"][0]["establishment_announcement_date"] = "2026-10-15"
        events = [e for e in calculate(before, after)["events"] if not e["is_baseline"]]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["after"], {"establishment_announcement_date": "2026-10-15"})
        self.assertNotIn("established_date", events[0]["after"])

    def test_future_listing_not_completed_and_source_latest_includes_current_announcement(self):
        before = example()
        before["public"]["funds"][0].update(listing_date="2026-10-20", establishment_announcement_date="2026-10-14")
        payload = calculate(before)
        self.assertFalse(any("listing_date" in e["after"] for e in payload["events"]))
        self.assertEqual(payload["sources"]["public"]["latest_official_date"], "2026-10-14")

    def test_new_recommendation_is_incremental_independent_of_official_date(self):
        before = example(); after = deepcopy(before)
        advance(after["ndrc"])
        new = deepcopy(after["ndrc"]["items"][0]); new.update(id="NDRC_new", recommended_date="2026-08-01")
        after["ndrc"]["items"].append(new)
        observed = [e for e in calculate(before, after)["events"] if not e["is_baseline"]]
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0]["title"], "新增国家发改委推荐项目")
        self.assertTrue(observed[0]["is_incremental"])
        self.assertEqual(observed[0]["event_date"], "2026-08-01")

    def test_official_timeline_duplicate_rows_are_deduplicated(self):
        data = example()
        data["public"]["events"][0]["timeline"] = [{"title": "已问询", "date": "2026-10-12"}] * 2
        events = [e for e in calculate(data)["events"] if e["after"].get("timeline")]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["after"]["timeline"], "已问询")

    def test_official_url_excludes_embedded_credentials_and_spoofed_domains(self):
        self.assertTrue(official_url("https://static.sse.com.cn/a.pdf"))
        self.assertFalse(official_url("https://username:password@static.sse.com.cn/a.pdf"))
        self.assertFalse(official_url("https://sse.com.cn.attacker.example/a.pdf"))

    def test_real_input_build_is_idempotent_check_is_readonly_and_detects_stale_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / "data").mkdir()
            for name in FILES.values():
                shutil.copy2(ROOT / "data" / name, root / "data" / name)
            generated = integration_time(root)
            payload = build(root, generated)
            original = (root / "data/project_updates.json").read_bytes()
            rebuilt = build(root, integration_time(root, 10), rebuild=True)
            self.assertEqual(payload, rebuilt)
            self.assertEqual(original, (root / "data/project_updates.json").read_bytes())
            self.assertTrue(validate(payload, root)["current_input_hashes_match"])
            data = json.loads((root / "data/institutional.json").read_text())
            data["date"] = (datetime.fromisoformat(generated) + timedelta(days=1)).date().isoformat()
            (root / "data/institutional.json").write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "stale"):
                validate(payload, root)

    def test_failed_current_input_does_not_replace_previously_audited_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / "data").mkdir()
            for name in FILES.values():
                shutil.copy2(ROOT / "data" / name, root / "data" / name)
            generated = integration_time(root)
            build(root, generated)
            original = (root / "data/project_updates.json").read_bytes()
            data = json.loads((root / "data/public_reits.json").read_text())
            data["coverage"]["complete"] = False
            (root / "data/public_reits.json").write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                build(root, integration_time(root, 10))
            self.assertEqual(original, (root / "data/project_updates.json").read_bytes())

    def test_forged_timeline_and_document_titles_fail_even_with_recomputed_event_id(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / "data").mkdir()
            for name in FILES.values():
                shutil.copy2(ROOT / "data" / name, root / "data" / name)
            generated = integration_time(root)
            payload = build(root, generated)
            forged = deepcopy(payload)
            event = next(e for e in forged["events"] if "timeline" in e["after"])
            event["changes"][0]["after"] = "伪造审核通过"
            event["after"]["timeline"] = "伪造审核通过"
            event["id"] = event_id(event)
            with self.assertRaisesRegex(ValueError, "timeline title/date"):
                validate(forged, root)
            forged = deepcopy(payload)
            event = next(e for e in forged["events"] if e["documents"])
            event["documents"][0]["title"] = "伪造文件标题"
            event["after"]["documents"] = [d["title"] for d in event["documents"]]
            event["changes"][0]["after"] = event["after"]["documents"]
            event["id"] = event_id(event)
            with self.assertRaisesRegex(ValueError, "document metadata"):
                validate(forged, root)

    def test_failed_latest_attempt_preserves_success_but_exposes_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / "data").mkdir()
            for name in FILES.values():
                shutil.copy2(ROOT / "data" / name, root / "data" / name)
            (root / "data/ndrc_refresh_status.json").write_text(json.dumps({"status": "failed", "last_attempt_at": integration_time(root), "error": "source unavailable"}))
            generated = integration_time(root)
            payload = build(root, generated)
            self.assertEqual(payload["sources"]["ndrc"]["status"], "failed")
            self.assertTrue(payload["sources"]["ndrc"]["complete"])
            self.assertEqual(payload["sources"]["ndrc"]["error"], "source unavailable")


if __name__ == "__main__":
    unittest.main()
