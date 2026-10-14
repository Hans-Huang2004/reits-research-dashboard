"""Evidence must survive refresh and never become a false confirmed label."""
import copy
import unittest

from collectors.institutional import (
    CollectionError, _inherit_classification, classify_by_name, reclassify_snapshot,
)


class ClassificationEvidenceTests(unittest.TestCase):
    def row(self):
        row = {'id':'SSE_abc123', 'source_id':'abc123', 'name':'某集团持有型不动产资产支持专项计划'}
        row.update(classify_by_name(row['name']))
        return row

    def evidence(self):
        return {'ptype':'产权类', 'psub':'办公', 'pnote':'官方公告披露写字楼',
                'classification_confidence':'confirmed',
                'underlying_assets':'写字楼及配套停车位',
                'classification_evidence':[{'title':'项目公告', 'url':'https://example.org/disclosure'}]}

    def test_exact_project_evidence_survives_refresh(self):
        row = self.row()
        override = self.evidence()
        _inherit_classification(row, {}, {row['id']:override})
        self.assertEqual(row['classification_source'], 'verified')
        self.assertEqual(row['classification_evidence'], override['classification_evidence'])
        refreshed = self.row()
        _inherit_classification(refreshed, row, {})
        self.assertEqual(refreshed['underlying_assets'], row['underlying_assets'])
        self.assertEqual(refreshed['classification_source'], 'verified')

    def test_confirmed_requires_asset_evidence(self):
        override = self.evidence()
        override['classification_evidence'] = []
        with self.assertRaises(CollectionError):
            _inherit_classification(self.row(), {}, {'SSE_abc123':override})

    def test_javascript_evidence_link_is_rejected(self):
        override = self.evidence()
        override['classification_evidence'][0]['url'] = 'javascript:alert(1)'
        with self.assertRaises(CollectionError):
            _inherit_classification(self.row(), {}, {'SSE_abc123':override})

    def test_issuer_does_not_transfer_evidence_to_new_project(self):
        row = self.row()
        row['id'] = 'SSE_other'
        row['source_id'] = 'other'
        _inherit_classification(row, {}, {'SSE_abc123':self.evidence()})
        self.assertEqual(row['classification_source'], 'unknown')

    def test_unknown_review_can_keep_search_evidence(self):
        override = {'ptype':'待分类', 'psub':'待分类', 'classification_confidence':'unknown',
                    'pnote':'未公开资产清单', 'classification_evidence':[]}
        row = self.row()
        _inherit_classification(row, {}, {row['id']:override})
        self.assertEqual((row['classification_source'], row['pflag']), ('unknown', '待分类'))

    def test_taxonomy_conflict_is_rejected(self):
        override = self.evidence()
        override['ptype'] = '经营权类'
        with self.assertRaises(CollectionError):
            _inherit_classification(self.row(), {}, {'SSE_abc123':override})

    def test_likely_evidence_stays_provisional(self):
        override = self.evidence()
        override['classification_confidence'] = 'likely'
        row = self.row()
        _inherit_classification(row, {}, {row['id']:override})
        self.assertEqual(row['classification_source'], 'inferred')

    def test_reclassification_preserves_collection_timestamp(self):
        snapshot = {'updated_at':'2026-10-14T16:18:03+08:00', 'items':[self.row()], 'quality':{}}
        previous_date = snapshot['updated_at']
        reclassify_snapshot(snapshot, {'SSE_abc123':self.evidence()})
        self.assertEqual(snapshot['updated_at'], previous_date)
        self.assertEqual(snapshot['quality']['unknown_classification'], 0)
        self.assertEqual(snapshot['quality']['classification_counts']['verified'], 1)
        self.assertIn('classification_updated_at', snapshot)


if __name__ == '__main__':
    unittest.main()
