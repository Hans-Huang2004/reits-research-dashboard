import tempfile
import unittest
from unittest.mock import patch

from collectors import public_szse as szse


class Reader:
    def __init__(self, packets):
        self.packets = iter(packets)
        self.requests = []

    def request(self, key, url, params=None, body=None):
        self.requests.append((key, url, params, body))
        return next(self.packets)


def projects(data, total=None, page=0, size=100):
    total = len(data) if total is None else total
    return {"data":data, "totalSize":total, "pageSize":size,
            "totalPage":(total + size - 1) // size, "pageIndex":page}


def report(data, total=None, page=1, size=20):
    total = len(data) if total is None else total
    return [{"data":data, "metadata":{"recordcount":total, "pagesize":size,
             "pagecount":(total + size - 1) // size, "pageno":page,
             "subname":"2026-10-15"}, "error":None}]


class PublicSzseTests(unittest.TestCase):
    def test_regular_collect_keeps_real_offering_codes_without_establishing_funds(self):
        # Published exchange metadata for three offerings absent from the
        # established/listed reports at this snapshot; no PDF text is needed.
        identities = [
            (5000039, "180107", "平安西安高科产业园封闭式基础设施证券投资基金", "2026-09-30",
             "/disc/disk03/finalpage/2026-09-30/112fe54b-776e-4ef2-ab60-3a290e94402f.PDF"),
            (5000060, "181002", "华泰紫金华住安住封闭式商业不动产证券投资基金", "2026-09-29",
             "/disc/disk03/finalpage/2026-09-29/ed016f38-e64e-4369-b945-4c8fc670a360.PDF"),
            (5000055, "180702", "银华粤海水务水利封闭式基础设施证券投资基金", "2026-09-24",
             "/disc/disk03/finalpage/2026-09-24/70b940d4-c6cd-45b8-bf47-636763b12bef.PDF"),
        ]
        first = [{"prjid":pid, "cmpnm":name, "biztypsb":21, "prjst":"注册生效",
                  "acptdt":"2026-01-01", "updtdt":"2026-09-24"}
                 for pid, code, name, published, url in identities]
        followon = {"prjid":6000001, "cmpnm":identities[0][2], "biztypsb":23,
                    "acptdt":"2026-10-01", "updtdt":"2026-10-01"}
        sale = [{"id":"sale-" + code, "annId":"official-" + code,
                 "title":name + "基金份额发售公告", "secCode":[code], "secName":[code + "REIT"],
                 "publishTime":published + " 00:00:00", "attachPath":url}
                for pid, code, name, published, url in identities]
        sale.append(dict(sale[0], id="expansion-sale", secCode=["180999"],
                         title=identities[0][2] + "2026年度扩募基金份额发售公告"))
        all_rows = first + [followon]
        class MetadataReader:
            def __init__(self):
                self.manifest = []
                self.urls = []
            def request(self, key, url, params=None, body=None):
                self.urls.append(url)
                if url != szse.DETAIL:
                    raise AssertionError("Unexpected data or PDF request: " + url)
                return {"data":next(row for row in all_rows if str(row["prjid"]) == params["id"])}
        reader = MetadataReader()
        def fetch_projects(_reader, business=None):
            rows = all_rows if business is None else first if business == 21 else [followon]
            return rows, {"advertised_total":len(rows), "raw_count":len(rows), "pages":1}
        def announcements(_reader, keyword, label, stock=None):
            self.assertIsNone(stock)
            rows = sale if keyword == "基金份额发售公告" else []
            return rows, {"advertised_total":len(rows), "raw_count":len(rows), "pages":1}
        with tempfile.TemporaryDirectory() as raw, \
             patch.object(szse, "SourceReader", return_value=reader), \
             patch.object(szse, "fetch_fund_report", return_value=([], {"report_date":"2026-10-15"})), \
             patch.object(szse, "fetch_projects", side_effect=fetch_projects), \
             patch.object(szse, "fetch_announcements", side_effect=announcements):
            result = szse.collect(raw)
        funds = {fund["code"]:fund for fund in result["funds"]}
        self.assertEqual(set(funds), {"180107", "181002", "180702"})
        for pid, code, name, published, url in identities:
            fund = funds[code]
            self.assertEqual(fund["name"], name)
            self.assertEqual(fund["status"], "发售准备")
            self.assertEqual(fund["listing_date"], "")
            self.assertEqual(fund["established_date"], "")
            self.assertEqual(fund["establishment_announcement_date"], "")
            self.assertEqual(fund["issuance_evidence_url"], "")
            self.assertIsNone(fund["initial_raise_cny_100m"])
            self.assertEqual(fund["offering_announcements"][0]["date"], published)
            self.assertEqual(fund["offering_announcements"][0]["url"], "https://disc.static.szse.cn/download" + url)
            event = next(event for event in result["events"] if event["source_id"] == str(pid))
            self.assertEqual(event["fund_code"], code)
            self.assertEqual(event["fund_link_evidence"][0]["date"], published)
        expansion = next(event for event in result["events"] if event["source_id"] == "6000001")
        self.assertEqual(expansion["fund_code"], "")
        self.assertNotIn("fund_link_evidence", expansion)
        self.assertEqual(result["source_status"]["issued_fund_count"], 0)
        self.assertEqual(result["source_status"]["issued_pending_listing_codes"], [])
        self.assertEqual(result["source_status"]["disclosed_fund_count"], 3)
        self.assertEqual(result["source_status"]["offering_only_codes"], sorted(funds))
        self.assertEqual(result["source_status"]["pagination_checks"]["sale_announcements"]["raw_count"], 4)
        self.assertTrue(all(url == szse.DETAIL for url in reader.urls))

    def test_offering_link_requires_unique_exact_first_issuance_and_consistent_code(self):
        event = {"id":"SZSE_1", "name":"甲封闭式基础设施证券投资基金", "business_type":"首发", "fund_code":""}
        announcement = {"id":"sale-a", "title":event["name"] + "基金份额发售公告", "secCode":["180107"],
                        "publishTime":"2026-09-30", "attachPath":"/official.PDF"}
        for events, notice in [
            ([event, dict(event, id="SZSE_2")], announcement),
            ([dict(event, name="甲二期封闭式基础设施证券投资基金")], announcement),
            ([event], dict(announcement, secCode=["180107", "181002"])),
            ([event], dict(announcement, title=event["name"] + "扩募基金份额发售公告")),
            ([dict(event, business_type="扩募")], announcement),
        ]:
            with self.subTest(events=events, notice=notice):
                matched, audit = szse.match_first_offering_announcements(events, [notice])
                self.assertEqual(matched, {})
                self.assertEqual(len(audit["skipped_announcements"]), 1)
        with self.assertRaises(szse.CollectionError):
            szse.match_first_offering_announcements([dict(event, fund_code="180702")], [announcement])
        with self.assertRaises(szse.CollectionError):
            szse.match_first_offering_announcements([event], [announcement, dict(announcement, id="sale-b", secCode=["181002"])])

    def test_report_uses_uppercase_pageno_and_reconciles_both_pages(self):
        reader = Reader([report([{"sys_key":"180101"}], 2, 1, 1),
                         report([{"sys_key":"181001"}], 2, 2, 1)])
        rows, checks = szse.fetch_fund_report(reader)
        self.assertEqual([row["sys_key"] for row in rows], ["180101", "181001"])
        self.assertEqual(checks["raw_count"], checks["advertised_total"])
        self.assertEqual([r[2]["PAGENO"] for r in reader.requests], [1, 2])
        self.assertNotIn("pageNo", reader.requests[0][2])

    def test_report_repeated_first_page_aborts(self):
        reader = Reader([report([{"sys_key":"180101"}], 2, 1, 1),
                         report([{"sys_key":"180101"}], 2, 1, 1)])
        with self.assertRaises(szse.CollectionError):
            szse.fetch_fund_report(reader)

    def test_report_duplicate_codes_abort(self):
        reader = Reader([report([{"sys_key":"180101"}, {"sys_key":"180101"}])])
        with self.assertRaises(szse.CollectionError):
            szse.fetch_fund_report(reader)

    def test_project_completeness_and_zero_based_pages(self):
        reader = Reader([projects([{"prjid":1}], 2, 0, 1), projects([{"prjid":2}], 2, 1, 1)])
        rows, checks = szse.fetch_projects(reader, 21)
        self.assertEqual(len(rows), 2)
        self.assertEqual(checks["pages"], 2)
        self.assertEqual([r[2]["pageIndex"] for r in reader.requests], [0, 1])

    def test_incomplete_and_changed_lists_abort(self):
        for packets in ([projects([], 1)],
                        [projects([{"prjid":1}], 2, 0, 1), projects([{"prjid":2}], 3, 1, 1)]):
            with self.subTest(packets=packets), self.assertRaises(szse.CollectionError):
                szse.fetch_projects(Reader(packets))

    def test_announcement_count_and_identity_are_required(self):
        reader = Reader([{"announceCount":2, "data":[{"id":"a"}]}])
        with self.assertRaises(szse.CollectionError):
            szse.fetch_announcements(reader, "基金合同生效", "effective")

    def test_official_business_label_is_preserved_when_expansion_is_verified(self):
        row = {"prjid":5000019, "cmpnm":"甲封闭式基础设施证券投资基金", "biztypsb":23,
               "biztypsbName":"新购入项目", "prjst":"注册生效", "prjstatus":70,
               "acptdt":"2022-09-29", "updtdt":"2023-04-04"}
        detail = dict(row, acctfm="甲基金", primitiveInterestsor="甲公司", bizcategorynm="基础设施",
                      fundProvinceName="北京",
                      issueTargetName="产业园区", prjprogs=[{"caption":"注册生效", "value":70,
                      "date":"2023-03-31 00:00"}], enquiryResponseAttachment=[
                      {"dfid":61, "dfnm":"甲基金产品变更暨扩募份额上市的审核问询函.pdf",
                       "dfpth":"/UpFiles/reitsinfodisc/REITS_TEST.pdf", "ddt":"2022-12-07"}])
        event = szse.normalize_event(row, detail)
        self.assertEqual(event["id"], "SZSE_5000019")
        self.assertEqual(event["official_business_type"], "新购入项目")
        self.assertEqual(event["business_type"], "扩募")
        self.assertEqual(event["registered_date"], "2023-03-31")
        self.assertEqual(event["fund_code"], "")
        self.assertEqual(event["manager_location"], "北京")
        self.assertEqual(event["asset_location"], "")
        self.assertNotIn("completed", event)
        self.assertIn("reportdocs.static.szse.cn", event["documents"][0]["url"])

    def test_detail_identity_mismatch_aborts(self):
        with self.assertRaises(szse.CollectionError):
            szse.normalize_event({"prjid":5000019}, {"prjid":5000017})

    def test_name_extraction_and_disclosed_asset_mapping(self):
        self.assertEqual(szse.fund_name_from_title("中航REIT：中航基金管理有限公司关于中航甲封闭式基础设施证券投资基金基金合同生效公告"),
                         "中航甲封闭式基础设施证券投资基金")
        self.assertEqual(szse.asset_type("垃圾处理及生物质发电"), "市政生态")
        self.assertEqual(szse.asset_type("港口仓储物流"), "物流仓储")
        self.assertEqual(szse.asset_type("商业零售、办公"), "综合业态")
        self.assertEqual(szse.asset_type("新资产类别"), "待分类")


    def test_effective_date_comes_from_label_not_announcement_or_payment_date(self):
        text = """基金名称中金菜鸟仓储物流封闭式基础设施证券投资基金
        基金简称中金菜鸟REIT 基金主代码180307 公告送出日期2026年9月29日
        募集资金划入基金托管专户的日期2026年9月27日
        基金合同生效日2026年9月28日
        募集期间净认购金额（单位：人民币元）1,490,000,000.00
        认购资金在募集期间产生的利息1,977,258.21
        有效认购份额500,000,000"""
        parsed = szse.parse_effective_announcement_text(text, "180307")
        self.assertEqual(parsed["established_date"], "2026-09-28")
        self.assertEqual(parsed["initial_raise_cny_100m"], 14.9)
        self.assertEqual(parsed["initial_units"], 500000000)
        self.assertEqual(parsed["initial_raise_basis"], "募集期间净认购金额（不含认购利息）")
        with self.assertRaises(szse.CollectionError):
            szse.parse_effective_announcement_text(text, "180505")


if __name__ == "__main__":
    unittest.main()
