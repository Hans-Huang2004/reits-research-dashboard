import unittest

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
