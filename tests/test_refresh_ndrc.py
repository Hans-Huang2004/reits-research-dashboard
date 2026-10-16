from datetime import datetime
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.refresh_ndrc import refresh_due, run_refresh


class RecommendationRefreshTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.fromisoformat('2026-10-16T10:00:00+08:00')

    @patch('scripts.refresh_ndrc.validate', return_value={'ok': True})
    def test_same_day_failure_or_changed_exchange_input_retries(self, validate):
        snapshot = {'date': '2026-10-16', 'updated_at': '2026-10-16T08:30:00+08:00'}
        status = {'attempt_ok': True, 'status': 'complete', 'public_snapshot_sha256': 'public-1',
                  'snapshot_sha256': 'recommendations-1'}
        self.assertFalse(refresh_due(snapshot, status, 'public-1', self.now,
                                     snapshot_sha='recommendations-1'))
        self.assertTrue(refresh_due(snapshot, status, 'public-2', self.now))
        self.assertTrue(refresh_due(snapshot, {**status, 'attempt_ok': False}, 'public-1', self.now))
        self.assertTrue(refresh_due(snapshot, status, 'public-1', self.now,
                                    snapshot_sha='modified-unvalidated-output'))
        self.assertTrue(refresh_due(snapshot, status, 'public-1', self.now, force=True))
        self.assertTrue(refresh_due(snapshot, status, 'public-1', self.now, review_config_sha='new-review'))
        self.assertTrue(refresh_due(snapshot, status, 'public-1', self.now, implementation_sha='new-code'))
        status.update(review_config_sha256='new-review', implementation_sha256='new-code')
        self.assertFalse(refresh_due(snapshot, status, 'public-1', self.now,
                                     review_config_sha='new-review', implementation_sha='new-code'))

    @patch('scripts.refresh_ndrc.validate', return_value={'ok': True})
    def test_source_failure_preserves_last_complete_snapshot(self, validate):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/public_reits.json').write_text('{"events": [], "funds": []}')
            output = root / 'data/ndrc_recommendations.json'
            output.write_text('{"items": ["last reviewed record"]}')
            before = output.read_bytes()
            def fail(*args, **kwargs):
                raise RuntimeError('Source pagination incomplete')
            with self.assertRaisesRegex(RuntimeError, 'pagination incomplete'):
                run_refresh(root, 'failure-test', True, self.now, runner=fail)
            self.assertEqual(output.read_bytes(), before)
            status = json.loads((root / 'data/ndrc_refresh_status.json').read_text())
            self.assertFalse(status['attempt_ok'])
            self.assertEqual(status['snapshot_sha256'], hashlib.sha256(before).hexdigest())

    @patch('scripts.refresh_ndrc.validate', return_value={'ok': True})
    def test_matching_cannot_publish_against_changed_exchange_version(self, validate):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            public = root / 'data/public_reits.json'
            public.write_text('{"version": 1}')
            output = root / 'data/ndrc_recommendations.json'
            output.write_text('{"items": ["old"]}')
            before = output.read_bytes()
            def change_input(command, **kwargs):
                candidate = Path(command[command.index('--output') + 1])
                candidate.write_text('{"items": ["new"], "coverage": {}}')
                public.write_text('{"version": 2}')
            with self.assertRaisesRegex(ValueError, 'changed during matching'):
                run_refresh(root, 'version-test', True, self.now, runner=change_input)
            self.assertEqual(output.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
