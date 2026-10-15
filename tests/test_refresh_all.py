import copy
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest

from collectors.public_reits import build_snapshot
from scripts.refresh_all import publish_candidates, refresh_due
from tests.test_public_library import event, fund


class CombinedRefreshTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.fromisoformat('2026-10-15T10:00:00+08:00')
        root = Path(__file__).resolve().parents[1]
        self.institutional = json.loads((root / 'data/institutional.json').read_text())
        self.institutional.update(date='2026-10-15', updated_at='2026-10-15T08:35:00+08:00')
        self.institutional['quality']['link_validation']['checked_at'] = '2026-10-15T08:36:00+08:00'
        sources = {key: {'source_status': {'ok': True, 'collected_at': '2026-10-15T08:35:00+08:00'},
                         'funds': [fund()] if key == 'SSE' else [], 'events': [event()] if key == 'SSE' else []}
                   for key in ('SSE', 'SZSE')}
        self.public, _ = build_snapshot(sources, now=self.now)
        self.status = {'batch_id': 'batch-1', 'status': 'complete', 'date': '2026-10-15'}
        for snapshot in (self.institutional, self.public):
            snapshot['refresh_batch'] = {'id': 'batch-1'}

    def test_only_a_complete_matching_pair_skips_retry(self):
        self.assertFalse(refresh_due(self.institutional, self.public, self.status, self.now))
        self.public['refresh_batch']['id'] = 'different-batch'
        self.assertTrue(refresh_due(self.institutional, self.public, self.status, self.now))
        self.public['refresh_batch']['id'] = 'batch-1'
        self.assertTrue(refresh_due(self.institutional, self.public, None, self.now))

    def test_one_stale_population_retries_both_and_manual_force_runs(self):
        self.assertTrue(refresh_due(self.institutional, self.public, self.status, self.now, force=True))
        self.public['source_status']['SZSE']['collected_at'] = '2026-10-14T08:35:00+08:00'
        self.assertTrue(refresh_due(self.institutional, self.public, self.status, self.now))

    def test_failure_of_second_population_does_not_replace_either_final_file(self):
        invalid = copy.deepcopy(self.public)
        invalid['coverage']['complete'] = False
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidates = {'institutional': root / 'institutional_candidate.json', 'public': root / 'public_candidate.json'}
            candidates['institutional'].write_text(json.dumps(self.institutional))
            candidates['public'].write_text(json.dumps(invalid))
            output = root / 'output'; output.mkdir()
            for name in ('institutional.json', 'public_reits.json'):
                (output / name).write_text('previous approved snapshot')
            with self.assertRaises(ValueError):
                publish_candidates(candidates, output, 'new-batch', self.now.isoformat(), self.now)
            for name in ('institutional.json', 'public_reits.json'):
                self.assertEqual((output / name).read_text(), 'previous approved snapshot')

    def test_pair_has_one_batch_and_retains_independent_disclosure_dates(self):
        self.public['enrichment'] = {'checked_at': '2026-10-10T09:00:00+08:00'}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidates = {key: root / (key + '_candidate.json') for key in ('public', 'institutional')}
            for key, snapshot in [('public', self.public), ('institutional', self.institutional)]:
                candidates[key].write_text(json.dumps(snapshot))
            output = root / 'output'
            audit = publish_candidates(candidates, output, 'new-batch', self.now.isoformat(), self.now)
            public = json.loads((output / 'public_reits.json').read_text())
            institutional = json.loads((output / 'institutional.json').read_text())
            status = json.loads((output / 'refresh_status.json').read_text())
            self.assertEqual(public['refresh_batch'], institutional['refresh_batch'])
            self.assertEqual(public['enrichment']['checked_at'], '2026-10-10T09:00:00+08:00')
            self.assertFalse(refresh_due(institutional, public, status, self.now))
            self.assertNotEqual(audit['source_snapshot_sha256']['public'], audit['output_sha256']['public'])


if __name__ == '__main__':
    unittest.main()
