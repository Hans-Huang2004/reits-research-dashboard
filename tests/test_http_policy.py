import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from collectors.http_policy import RequestPacer, backoff


class RequestPacingTests(unittest.TestCase):
    def test_one_host_cannot_burst_and_cooldown_applies_to_other_paths(self):
        now = [100.0]
        def sleep(seconds):
            now[0] += seconds
        pacer = RequestPacer(clock=lambda: now[0], sleep=sleep)
        first = 'https://query.sse.com.cn/commonQuery.do'
        second = 'https://query.sse.com.cn/commonSoaQuery.do'
        pacer.wait(first)
        pacer.wait(second)
        self.assertEqual(now[0], 101.0)
        pacer.defer(first, 30)
        pacer.wait(second)
        self.assertEqual(now[0], 131.0)
        pacer.wait('https://reits.szse.cn/api')
        self.assertEqual(now[0], 131.0)

    def test_refused_requests_wait_and_server_retry_after_is_respected(self):
        url = 'https://query.sse.com.cn/commonQuery.do'
        with patch('collectors.http_policy.PACER') as pacer:
            backoff(url, HTTPError(url, 403, 'Forbidden', {}, None), 0)
            pacer.defer.assert_called_with(url, 30)
            backoff(url, HTTPError(url, 429, 'Slow down', {'Retry-After': '120'}, None), 0)
            pacer.defer.assert_called_with(url, 120)


if __name__ == '__main__':
    unittest.main()
