import unittest
from scripts.pages_due import publication_due


class PublicationRetryTests(unittest.TestCase):
    def test_new_update_ledger_publishes_even_with_unchanged_source_batches(self):
        pair = dict(status='complete', batch_id='pair', date='2026-10-16', completed_at='today')
        self.assertFalse(publication_due(pair, pair, updates_expected='same', updates_deployed='same'))
        self.assertTrue(publication_due(pair, pair, updates_expected='new', updates_deployed='old'))
        self.assertTrue(publication_due(pair, pair, updates_expected='new', updates_deployed=None))

    def test_recommendation_changes_publish_even_when_exchange_pair_is_live(self):
        pair = dict(status='complete', batch_id='pair-1', date='2026-10-16', completed_at='today')
        ndrc = dict(batch_id='ndrc-1', snapshot_sha256='a', attempt_ok=True, last_attempt_at='today')
        self.assertFalse(publication_due(pair, pair, ndrc, dict(ndrc)))
        self.assertTrue(publication_due(pair, pair, ndrc, None))
        self.assertTrue(publication_due(pair, pair, ndrc, {**ndrc, 'snapshot_sha256': 'old'}))
        failed = {**ndrc, 'attempt_ok': False, 'last_attempt_at': 'later'}
        self.assertTrue(publication_due(pair, pair, failed, ndrc))

    def test_data_collection_success_does_not_hide_failed_deployment(self):
        current = dict(status='complete', batch_id='today-1', date='2026-10-16', completed_at='2026-10-16T07:40:00+08:00')
        self.assertFalse(publication_due(current, dict(current)))
        for deployed in (None, {}, {**current, 'batch_id': 'yesterday-1'},
                         {**current, 'status': 'failed'}, {**current, 'date': '2026-10-15'}):
            with self.subTest(deployed=deployed):
                self.assertTrue(publication_due(current, deployed))


if __name__ == '__main__':
    unittest.main()
