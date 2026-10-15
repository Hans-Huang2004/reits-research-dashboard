import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from collectors.public_reits import build_snapshot, UnresolvedLinks, stage_for_status, classify_asset
from scripts.validate_public_data import validate

NOW = datetime(2026, 10, 15, 11, 0, tzinfo=ZoneInfo('Asia/Shanghai'))


def fund(**extra):
    return dict(dict(id='SSE_FUND_508001', name='甲封闭式基础设施证券投资基金', code='508001',
                     exchange='上交所', listing_date='2021-06-21', source_url='https://www.sse.com.cn/reits/'), **extra)


def event(**extra):
    return dict(dict(id='SSE_123', source_id='123', name='甲封闭式基础设施证券投资基金',
                     exchange='上交所', business_type='首发', official_status='注册生效',
                     updated_date='2021-06-01', source_url='https://www.sse.com.cn/reits/info/index_detail.shtml?audit_id=123'), **extra)


def source(funds, events):
    return {'SSE': {'source_status': {'ok': True}, 'funds': funds, 'events': events}}


class PublicLibraryTests(unittest.TestCase):
    def test_commercial_regime_does_not_imply_retail_asset(self):
        r = classify_asset({'name':'华夏中海封闭式商业不动产证券投资基金'})
        self.assertEqual(r['asset_type'], '待分类')
        r = classify_asset({'name':'华夏产业园封闭式基础设施证券投资基金'})
        self.assertEqual(r['asset_type'], '产业园')
        self.assertEqual(r['classification_source'], 'keyword')

    def test_expansion_does_not_duplicate_fund_or_regress_listing(self):
        initial = event()
        expansion = event(id='SSE_456', source_id='456', business_type='扩募', fund_code='508001', official_status='已反馈')
        data, audit = build_snapshot(source([fund()], [initial, expansion]), now=NOW)
        self.assertEqual(len(data['funds']), 1)
        self.assertEqual(len(data['events']), 2)
        self.assertEqual(data['funds'][0]['stage'], '已上市')
        self.assertEqual(validate(data)['unlinked_events'], 0)

    def test_future_listing_is_a_plan_not_issued(self):
        data, _ = build_snapshot(source([fund(listing_date='2026-11-01', stage='已上市')], [event()]), now=NOW)
        self.assertEqual(data['funds'][0]['planned_listing_date'], '2026-11-01')
        self.assertNotEqual(data['funds'][0]['stage'], '已上市')
        self.assertEqual(validate(data)['issued_funds'], 0)

    def test_completed_expansion_requires_evidence(self):
        e = event(business_type='扩募', fund_code='508001', completed=True,
                  completion_announcement_date='2023-06-13', completion_evidence=[{'url':'https://www.sse.com.cn/reits/'}])
        data, _ = build_snapshot(source([fund()], [e]), now=NOW)
        self.assertEqual(data['events'][0]['stage'], '已完成')

    def test_unknown_expansion_is_not_a_new_fund(self):
        with self.assertRaises(UnresolvedLinks):
            build_snapshot(source([fund()], [event(name='乙基金', business_type='扩募')]), now=NOW)

    def test_applicant_identity_survives_assigned_code(self):
        before, _ = build_snapshot(source([], [event()]), now=NOW)
        after, _ = build_snapshot(source([fund()], [event(fund_code='508001')]), previous=before, now=NOW)
        self.assertEqual(before['funds'][0]['id'], after['funds'][0]['id'])
        self.assertEqual(after['funds'][0]['code'], '508001')

    def test_exchange_identity_does_not_merge_same_name(self):
        sources = source([fund()], [event()])
        sources['SZSE'] = {'source_status': {'ok':True}, 'funds': [fund(exchange='深交所',code='180101')],
                           'events': [event(exchange='深交所',id='SZSE_123',fund_code='180101')]}
        data, _ = build_snapshot(sources, now=NOW)
        self.assertEqual(len(data['funds']), 2)

    def test_duplicate_filing_ids_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate filing'):
            build_snapshot(source([fund()], [event(), event()]), now=NOW)

    def test_registration_not_equivalent_to_issuance(self):
        self.assertEqual(stage_for_status('注册生效'), '获批待发行')
        self.assertEqual(stage_for_status('中止'), '中止审核')
        self.assertEqual(stage_for_status('终止(撤回)'), '终止')

    def test_validation_rejects_orphan_expansion(self):
        data, _ = build_snapshot(source([fund()], [event()]), now=NOW)
        data['events'][0]['fund_id'] = 'missing'
        with self.assertRaisesRegex(ValueError, 'Unlinked'):
            validate(data)


if __name__ == '__main__':
    unittest.main()
