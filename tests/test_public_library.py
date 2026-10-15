import unittest
from copy import deepcopy
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

    def test_acquisition_only_is_audited_out_without_losing_issued_funds(self):
        acquisition = event(id='SSE_789', source_id='789', name='无法匹配的新购入项目', business_type='新购入',
                            documents=[{'title': '新购入披露', 'url': 'https://www.sse.com.cn/acquisition.pdf'}])
        expansion = event(id='SSE_456', source_id='456', business_type='扩募', fund_code='508001')
        catalog_only = fund(code='508002', name='乙封闭式基础设施证券投资基金')
        inputs = source([fund(), catalog_only], [event(), expansion, acquisition])
        original = deepcopy(inputs)
        data, audit = build_snapshot(inputs, now=NOW)
        self.assertEqual(inputs, original)
        self.assertEqual(data['coverage']['event_count'], 2)
        self.assertEqual(data['coverage']['excluded_event_count'], 1)
        self.assertEqual(data['quality']['business_types'], {'首发': 1, '扩募': 1})
        self.assertEqual(data['quality']['scope_exclusions'][0]['record'], acquisition)
        self.assertIn('不纳入', data['quality']['scope_exclusions'][0]['reason'])
        self.assertEqual(data['changes']['excluded_event_ids'], ['SSE_789'])
        self.assertNotIn('SSE_789', {row['event_id'] for row in audit})
        self.assertEqual(validate(data)['issued_funds'], 2)
        self.assertEqual(len(data['funds']), 2)
        linked = {row['id']: row['fund_id'] for row in data['events']}
        self.assertEqual(linked['SSE_123'], linked['SSE_456'])

    def test_scope_exclusion_is_not_a_missing_source_record(self):
        data, _ = build_snapshot(source([fund()], [event()]), now=NOW)
        previous = deepcopy(data)
        previous['events'][0]['business_type'] = '新购入'
        excluded = event(business_type='新购入')
        data, _ = build_snapshot(source([fund()], [excluded]), previous=previous, now=NOW)
        self.assertEqual(data['changes']['missing_event_ids'], [])
        self.assertEqual(data['changes']['excluded_event_ids'], ['SSE_123'])
        self.assertEqual(data['events'], [])
        self.assertEqual(len(data['funds']), 1)

    def test_validation_rejects_acquisition_as_counted_filing(self):
        data, _ = build_snapshot(source([fund()], [event()]), now=NOW)
        data['events'][0]['business_type'] = '新购入'
        with self.assertRaisesRegex(ValueError, 'business type'):
            validate(data)

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

    def test_current_initial_pool_replaces_prior_applicant_pool_with_matching_evidence(self):
        old_evidence = [{'title': '旧申报稿', 'url': 'https://www.sse.com.cn/old'}]
        new_evidence = [{'title': '本次反馈稿', 'url': 'https://www.sse.com.cn/new'}]
        before, _ = build_snapshot(source([], [event(
            asset_type='办公', official_asset_type='写字楼', underlying_assets=['旧资产'],
            research_field_sources={'asset_type': old_evidence, 'underlying_assets': old_evidence})]), now=NOW)
        after, _ = build_snapshot(source([], [event(
            asset_type='消费', official_asset_type='购物中心', underlying_assets=['新资产'],
            updated_date='2026-10-15', research_field_sources={'asset_type': new_evidence, 'underlying_assets': new_evidence})]),
            previous=before, now=NOW)
        self.assertEqual(before['funds'][0]['id'], after['funds'][0]['id'])
        for row in (after['funds'][0], after['events'][0]):
            self.assertEqual((row['asset_type'], row['underlying_assets']), ('消费', ['新资产']))
            self.assertEqual(row['research_field_sources']['underlying_assets'], new_evidence)
            self.assertEqual(row['official_asset_type'], '购物中心')

    def test_missing_initial_disclosures_restore_reviewed_pool_and_metadata(self):
        evidence = [{'title': '首发披露', 'url': 'https://www.sse.com.cn/pool'}]
        before, _ = build_snapshot(source([], [event(
            asset_type='办公', official_asset_type='写字楼', underlying_assets=['首发资产'],
            research_field_sources={'asset_type': evidence, 'underlying_assets': evidence})]), now=NOW)
        after, _ = build_snapshot(source([], [event(asset_type='待分类', underlying_assets=[])]), previous=before, now=NOW)
        for row in (after['funds'][0], after['events'][0]):
            self.assertEqual((row['asset_type'], row['underlying_assets']), ('办公', ['首发资产']))
            self.assertEqual(row['classification_source'], 'official')
            self.assertEqual(row['research_field_sources']['asset_type'], evidence)

    def test_expansion_cannot_fill_missing_initial_pool_or_advisor(self):
        expansion = event(id='SSE_456', source_id='456', business_type='扩募', fund_code='508001',
                          asset_type='消费', official_asset_type='购物中心', underlying_assets=['新增商场'],
                          financial_advisor='扩募财务顾问', manager='扩募管理人')
        data, _ = build_snapshot(source([fund(asset_type='待分类')], [expansion]), now=NOW)
        parent, filing = data['funds'][0], data['events'][0]
        self.assertNotEqual(parent.get('underlying_assets'), ['新增商场'])
        self.assertNotEqual(parent.get('asset_type'), '消费')
        self.assertIsNone(parent.get('financial_advisor'))
        self.assertEqual(filing['underlying_assets'], ['新增商场'])
        self.assertEqual(filing['financial_advisor'], '扩募财务顾问')

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
