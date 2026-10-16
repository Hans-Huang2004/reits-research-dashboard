"""Polite host-level request pacing for public exchange endpoints."""
import threading
import time
from urllib.parse import urlsplit


class RequestPacer:
    def __init__(self, interval=1.0, clock=time.monotonic, sleep=time.sleep):
        self.interval, self.clock, self.sleep = interval, clock, sleep
        self.lock = threading.Lock()
        self.next_at = {}

    def wait(self, url):
        host = urlsplit(url).netloc
        with self.lock:
            delay = self.next_at.get(host, 0) - self.clock()
            if delay > 0:
                self.sleep(delay)
            self.next_at[host] = self.clock() + self.interval

    def defer(self, url, seconds):
        host = urlsplit(url).netloc
        with self.lock:
            self.next_at[host] = max(self.next_at.get(host, 0), self.clock() + seconds)


PACER = RequestPacer()


def backoff(url, error, attempt):
    delay = 30 * (attempt + 1) if getattr(error, 'code', None) in (403, 429, 503) else 2 * (attempt + 1)
    headers = getattr(error, 'headers', None)
    if headers:
        try:
            delay = max(delay, float(headers.get('Retry-After', 0)))
        except (TypeError, ValueError):
            pass
    PACER.defer(url, delay)
