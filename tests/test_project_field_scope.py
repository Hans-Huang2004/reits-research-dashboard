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


if __name__ == '__main__':
    unittest.main()
