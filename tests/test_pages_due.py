import unittest
from scripts.pages_due import publication_due


class PublicationRetryTests(unittest.TestCase):
    def test_data_collection_success_does_not_hide_failed_deployment(self):
        current = dict(status='complete', batch_id='today-1', date='2026-10-16', completed_at='2026-10-16T07:40:00+08:00')
        self.assertFalse(publication_due(current, dict(current)))
        for deployed in (None, {}, {**current, 'batch_id': 'yesterday-1'},
                         {**current, 'status': 'failed'}, {**current, 'date': '2026-10-15'}):
            with self.subTest(deployed=deployed):
                self.assertTrue(publication_due(current, deployed))


if __name__ == '__main__':
    unittest.main()
