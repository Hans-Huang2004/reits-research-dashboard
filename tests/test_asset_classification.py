"""Regression cases for asset-name evidence versus issuer-name hints."""
import unittest

from collectors.institutional import classify_by_name


class AssetNameClassificationTests(unittest.TestCase):
    def test_explicit_ski_resort_is_tourism(self):
        row = classify_by_name("首创证券-河北旅投崇礼滑雪场不动产资产支持专项计划（机构间REIT）")
        self.assertEqual((row["ptype"], row["psub"]), ("产权类", "文旅类"))
        self.assertIn("滑雪场", row["pnote"])

    def test_yiwu_market_has_specific_commercial_name_evidence(self):
        row = classify_by_name("中信证券-义乌市场集团持有型不动产资产支持专项计划（乡村振兴）")
        self.assertEqual(row["psub"], "消费")
        self.assertIn("义乌市场", row["pnote"])

    def test_issuer_anju_does_not_override_named_shopping_mall(self):
        row = classify_by_name("吴兴安居织里吾悦广场持有型不动产资产支持专项计划")
        self.assertEqual(row["psub"], "消费")
        self.assertNotIn("安居", row["pnote"])

    def test_two_explicit_asset_types_still_need_review(self):
        row = classify_by_name("吴兴安居吾悦广场及租赁住房持有型不动产资产支持专项计划")
        self.assertEqual(row["classification_source"], "unknown")

    def test_capital_market_word_is_not_a_commercial_property(self):
        row = classify_by_name("资本市场集团持有型不动产资产支持专项计划")
        self.assertEqual(row["psub"], "待分类")

    def test_policy_label_and_company_name_do_not_prove_asset_type(self):
        for name in ("财通资管-阿特斯持有型不动产资产支持专项计划（碳中和）",
                     "元联苏园产城持有型不动产资产支持专项计划"):
            with self.subTest(name=name):
                row = classify_by_name(name)
                self.assertEqual(row["classification_source"], "unknown")
                self.assertNotEqual(row["psub"], "综合业态")


if __name__ == "__main__":
    unittest.main()
