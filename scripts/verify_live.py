"""Verify the published bytes against the exact commit built by Pages."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen

FILES = ('refresh_status.json', 'institutional.json', 'public_reits.json',
         'ndrc_recommendations.json', 'ndrc_refresh_status.json', 'project_updates.json')


def check_site(root, site_url, fetch=None):
    def download(name, expected_hash):
        request = Request(site_url.rstrip('/') + '/data/' + name + '?release=' + expected_hash[:20],
                          headers={'Cache-Control': 'no-cache'})
        with urlopen(request, timeout=20) as response:
            return response.read()
    fetch = fetch or download
    results = []
    for name in FILES:
        path = Path(root) / 'data' / name
        if not path.exists():
            continue
        expected = path.read_bytes()
        digest = hashlib.sha256(expected).hexdigest()
        remote_name = name + '.gz' if name in ('public_reits.json', 'project_updates.json') else name
        body = fetch(remote_name, digest)
        actual = gzip.decompress(body) if remote_name.endswith('.gz') else body
        if actual != expected:
            raise ValueError('Published content differs from the built commit: ' + name)
        results.append({'file': remote_name, 'sha256_uncompressed': digest, 'bytes': len(actual)})
    status = json.loads((Path(root) / 'data/refresh_status.json').read_text())
    batch = status['batch_id']
    for name in ('institutional.json', 'public_reits.json'):
        snapshot = json.loads((Path(root) / 'data' / name).read_text())
        if snapshot.get('refresh_batch', {}).get('id') != batch or snapshot['date'] != status['date']:
            raise ValueError('Published pair does not share the declared batch/date')
    return {'ok': True, 'verified_at': datetime.now(timezone.utc).isoformat(),
            'batch_id': batch, 'date': status['date'], 'status': status['status'], 'files': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--site-url', required=True)
    parser.add_argument('--output', type=Path, default=Path('live-verification.json'))
    parser.add_argument('--attempts', type=int, default=8)
    args = parser.parse_args()
    for attempt in range(args.attempts):
        try:
            result = check_site(args.root, args.site_url)
            args.output.write_text(json.dumps(result, indent=2) + '\n')
            print(json.dumps(result))
            return 0
        except Exception as exc:
            print(f'Live verification {attempt + 1}/{args.attempts}: {exc}', file=sys.stderr, flush=True)
            if attempt + 1 < args.attempts:
                time.sleep(20)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
