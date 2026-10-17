"""Shared exchange transport with bounded IPv4 requests and byte-level evidence.

Collectors retain their pagination/schema validation and host pacing. Transport
failures never fall back to an old snapshot or change the requested endpoint.
"""
import io
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request
from datetime import datetime
from email.parser import Parser
from zoneinfo import ZoneInfo

LOCK = threading.Lock()


class Response(io.BytesIO):
    def __init__(self, body, url, headers, status):
        super().__init__(body)
        self.url, self.headers, self.status = url, headers, status

    def geturl(self):
        return self.url


def archive(request, transport, body=None, headers=None, status=None, error=None, final_url=None):
    directory = os.environ.get('REITS_HTTP_AUDIT_DIR')
    if not directory:
        return
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    entry = {'requested_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds'),
             'url': request.full_url, 'method': request.get_method(),
             'request_body': request.data.decode('utf-8') if request.data else None,
             'transport': transport, 'response_url': final_url, 'status': status,
             'content_type': (headers or {}).get('Content-Type', ''), 'error': error}
    with LOCK:
        if body is not None:
            digest = hashlib.sha256(body).hexdigest()
            path = root / (digest + '.bin')
            if not path.exists():
                path.write_bytes(body)
            entry.update(file=path.name, sha256=digest, bytes=len(body))
        with (root / 'requests.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + '\n')


def curl_response(request, timeout):
    with tempfile.TemporaryDirectory(prefix='reits-http-') as directory:
        body_file, header_file = Path(directory) / 'body', Path(directory) / 'headers'
        command = ['curl', '--silent', '--show-error', '--location', '--ipv4',
                   '--proto', '=https', '--proto-redir', '=https',
                   '--connect-timeout', '10', '--max-time', str(timeout),
                   '--output', str(body_file), '--dump-header', str(header_file),
                   '--write-out', '%{json}']
        for key, value in request.header_items():
            command.extend(['--header', key + ': ' + value])
        if request.data is not None:
            command.extend(['--request', request.get_method(), '--data-binary', '@-'])
        command.extend(['--url', request.full_url])
        result = subprocess.run(command, input=request.data, capture_output=True, timeout=timeout + 5)
        meta = json.loads(result.stdout or b'{}')
        body = body_file.read_bytes() if body_file.exists() else b''
        blocks = header_file.read_text(errors='replace').strip().split('\n\n') if header_file.exists() else []
        headers = Parser().parsestr(blocks[-1].partition('\n')[2] if blocks else '')
        status = int(meta.get('http_code') or 0)
        error = None if result.returncode == 0 and 200 <= status < 400 else (
            f"curl exit={result.returncode} http={status} remote_ip={meta.get('remote_ip', '')} "
            + result.stderr.decode(errors='replace').strip())
        archive(request, 'curl-ipv4', body, headers, status, error, meta.get('url_effective'))
        if result.returncode:
            raise urllib.error.URLError(error)
        if not 200 <= status < 400:
            raise urllib.error.HTTPError(request.full_url, status, error, headers, io.BytesIO(body))
        return Response(body, meta.get('url_effective') or request.full_url, headers, status)


def urlopen(request, timeout=40):
    if isinstance(request, str):
        request = urllib.request.Request(request)
    transport = os.environ.get('REITS_HTTP_TRANSPORT', 'urllib')
    if transport == 'curl-ipv4':
        return curl_response(request, timeout)
    if transport != 'urllib':
        raise ValueError('Unknown HTTP transport: ' + transport)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
            archive(request, transport, body, response.headers, response.status, final_url=response.url)
            return Response(body, response.url, response.headers, response.status)
    except Exception as exc:
        archive(request, transport, error=str(exc))
        raise
