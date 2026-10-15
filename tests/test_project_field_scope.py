import unittest
from copy import deepcopy
from collectors.project_fields import apply_field_scope


class FieldScopeTests(unittest.TestCase):
    def test_research_fields_survive_refresh_only_on_same_filing(self):
        old = {'events': [{'id':'a', 'guarantee_support':'明确支持条款'}, {'id':'b','external_loan_amount_cny_100m':0}], 'funds':[]}
        new = {'events': [{'id':'a'}, {'id':'c'}, {'id':'b'}], 'funds':[]}
        apply_field_scope(new, 'public', old)
        self.assertEqual(new['events'][0]['guarantee_support'], '明确支持条款')
        self.assertIsNone(new['events'][1]['guarantee_support'])
        self.assertEqual(new['events'][2]['external_loan_amount_cny_100m'], 0)

    def test_approved_is_not_issued_and_update_is_not_approval_date(self):
        data = {'updated_at':'2026-10-15T09:24:22+08:00', 'items':[{'id':'SSE_a','status':'4','up':'2026-10-15'}]}
        original = deepcopy(data)
        apply_field_scope(data, 'institutional')
        self.assertIsNone(data['items'][0]['is_issued'])
        self.assertIsNone(data['items'][0]['approved_date'])
        self.assertIsNone(data['items'][0]['issued_date'])
        self.assertEqual(data['updated_at'], original['updated_at'])
        self.assertEqual(data['field_scope']['field_count'], 13)

    def test_current_asset_evidence_wins_over_previous_asset_and_evidence(self):
        old_source = [{'title': '旧发行披露', 'url': 'https://www.sse.com.cn/old'}]
        new_source = [{'title': '新申报披露', 'url': 'https://www.sse.com.cn/new'}]
        old = {'events': [{'id': 'e1', 'asset_type': '办公',
                          'research_field_sources': {'asset_type': old_source}}]}
        fresh = {'events': [{'id': 'e1', 'asset_type': '消费', 'classification_source': 'keyword',
                            'research_field_sources': {'asset_type': new_source}}]}
        apply_field_scope(fresh, 'public', old)
        self.assertEqual(fresh['events'][0]['asset_type'], '消费')
        self.assertEqual(fresh['events'][0]['research_field_sources']['asset_type'], new_source)

    def test_current_official_asset_marker_does_not_inherit_old_asset(self):
        old = {'events': [{'id': 'e1', 'asset_type': '办公',
                          'research_field_sources': {'asset_type': [{'title': '旧发行披露'}]}}]}
        fresh = {'events': [{'id': 'e1', 'asset_type': '消费', 'official_asset_type': '购物中心'}]}
        apply_field_scope(fresh, 'public', old)
        self.assertEqual(fresh['events'][0]['asset_type'], '消费')
        self.assertNotIn('asset_type', fresh['events'][0]['research_field_sources'])

    def test_restored_disclosed_asset_keeps_its_classification_metadata(self):
        prior = {'id': 'e1', 'asset_type': '办公', 'official_asset_type': '写字楼',
                 'classification_source': 'official', 'classification_confidence': 'confirmed',
                 'classification_evidence': [{'title': '项目公告'}],
                 'research_field_sources': {'asset_type': [{'title': '项目公告'}]}}
        fresh = {'events': [{'id': 'e1', 'asset_type': '消费', 'classification_source': 'keyword',
                             'classification_confidence': 'likely', 'classification_note': '名称含商业',
                             'official_status': '已反馈', 'updated_date': '2026-10-16'}]}
        apply_field_scope(fresh, 'public', {'events': [prior]})
        row = fresh['events'][0]
        self.assertEqual((row['asset_type'], row['official_asset_type']), ('办公', '写字楼'))
        self.assertEqual((row['classification_source'], row['classification_confidence']), ('official', 'confirmed'))
        self.assertEqual(row['classification_evidence'], prior['classification_evidence'])
        self.assertNotIn('classification_note', row)
        self.assertEqual((row['official_status'], row['updated_date']), ('已反馈', '2026-10-16'))


if __name__ == '__main__':
    unittest.main()
