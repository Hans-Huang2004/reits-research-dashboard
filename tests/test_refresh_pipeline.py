import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.request import Request
from urllib.error import HTTPError, URLError
from subprocess import CompletedProcess

from collectors.http_transport import curl_response
from collectors.project_fields import apply_field_scope
from scripts.audit_refresh_fields import audit_retention
from scripts.verify_live import check_site, FILES
from scripts.pages_due import publication_due


class PipelineRegressionTests(unittest.TestCase):
    def curl_stub(self, command, **kwargs):
        Path(command[command.index('--output') + 1]).write_bytes(b'{"rows":[]}')
        Path(command[command.index('--dump-header') + 1]).write_text('HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n')
        self.command, self.input = command, kwargs['input']
        return CompletedProcess(command, 0, b'{"http_code":200,"url_effective":"https://query.sse.com.cn/example","remote_ip":"192.0.2.1"}', b'')

    def test_cloud_transport_preserves_post_headers_and_exact_response(self):
        request = Request('https://query.sse.com.cn/example', data=b'{"page":2}', headers={'Referer': 'https://www.sse.com.cn/'})
        with patch('collectors.http_transport.subprocess.run', side_effect=self.curl_stub):
            with curl_response(request, 30) as response:
                self.assertEqual(response.read(), b'{"rows":[]}')
                self.assertEqual(response.headers['Content-Type'], 'application/json')
        self.assertIn('--ipv4', self.command)
        self.assertEqual(self.input, b'{"page":2}')
        self.assertIn('Referer: https://www.sse.com.cn/', self.command)

    def test_transport_does_not_accept_http_rejection_as_data(self):
        with patch('collectors.http_transport.subprocess.run', return_value=CompletedProcess([], 0, b'{"http_code":403}', b'')):
            with self.assertRaises(HTTPError) as error:
                curl_response(Request('https://query.sse.com.cn/example'), 30)
            self.assertEqual(error.exception.code, 403)
        with patch('collectors.http_transport.subprocess.run', return_value=CompletedProcess([], 7, b'{"http_code":0}', b'Connection failed')):
            with self.assertRaisesRegex(URLError, 'curl exit=7'):
                curl_response(Request('https://query.sse.com.cn/example'), 30)

    def test_disclosed_issuer_roles_keep_value_date_and_source_by_exact_id(self):
        old = {'items': [{'id': 'SSE_a', 'origin': '原始权益人甲', 'writer': '承销商乙',
                         'research_field_sources': {'origin': [{'url': 'https://bond.sse.com.cn/a', 'checked_at': '2026-10-15'}],
                                                    'writer': [{'url': 'https://bond.sse.com.cn/a', 'checked_at': '2026-10-15'}]}}]}
        new = {'items': [{'id': 'SSE_a', 'origin': '', 'writer': ''}, {'id': 'SSE_b', 'origin': '', 'writer': ''}]}
        apply_field_scope(new, 'institutional', old)
        audit = audit_retention(old, new, 'institutional')
        self.assertEqual(audit['checked_fields'], 2)
        self.assertEqual(new['items'][0]['research_field_sources'], old['items'][0]['research_field_sources'])
        self.assertFalse(new['items'][1]['origin'])
        new['items'][0]['research_field_sources'] = {}
        with self.assertRaisesRegex(ValueError, 'evidence lost'):
            audit_retention(old, new, 'institutional')

    def test_published_failure_notice_does_not_redeploy_forever(self):
        status = dict(status='failed', batch_id='last-good', date='2026-10-16',
                      failed_at='2026-10-17T09:30:00+08:00', last_attempt_batch_id='attempt-2')
        self.assertFalse(publication_due(status, dict(status)))
        self.assertTrue(publication_due(status, {**status, 'last_attempt_batch_id': 'attempt-1'}))

    def test_live_verification_reads_both_populations_and_detects_stale_body(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / 'data').mkdir()
            batch = {'id': 'batch-a', 'date': '2026-10-17',
                     'started_at': '2026-10-17T07:30:00+08:00',
                     'completed_at': '2026-10-17T07:45:00+08:00'}
            for name in FILES:
                data = {'date': batch['date'], 'refresh_batch': batch,
                        'coverage': {'complete': True}}
                if name == 'refresh_status.json':
                    data = {'batch_id': batch['id'], 'date': batch['date'], 'status': 'complete',
                            'attempt_ok': True, 'started_at': batch['started_at'],
                            'completed_at': batch['completed_at'],
                            'last_successful_at': batch['completed_at'],
                            'last_attempt_at': batch['started_at']}
                (root / 'data' / name).write_text(json.dumps(data))
            requests = []
            def fetch(name, sha):
                requests.append(name)
                body = (root / 'data' / name.removesuffix('.gz')).read_bytes()
                return gzip.compress(body) if name.endswith('.gz') else body
            self.assertTrue(check_site(root, 'https://example.com/', fetch)['ok'])
            self.assertIn('institutional.json', requests)
            self.assertIn('public_reits.json.gz', requests)
            with self.assertRaisesRegex(ValueError, 'differs'):
                check_site(root, 'https://example.com/', lambda name, sha: b'{}')
            public_path = root / 'data/public_reits.json'
            mixed = json.loads(public_path.read_text())
            mixed['refresh_batch']['id'] = 'unpublished-batch'
            public_path.write_text(json.dumps(mixed))
            requests.clear()
            with self.assertRaisesRegex(ValueError, 'same complete refresh_batch'):
                check_site(root, 'https://example.com/', fetch)
            self.assertEqual(requests, [], 'A mixed local pair must fail before any network requests')


if __name__ == '__main__':
    unittest.main()
