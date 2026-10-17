"""Retry publication when the public website has not received the complete pair."""
import argparse
import json
import hashlib
from pathlib import Path
from urllib.request import Request, urlopen


def publication_due(expected, deployed, ndrc_expected=None, ndrc_deployed=None,
                    updates_expected=None, updates_deployed=None):
    if not isinstance(expected, dict) or expected.get('status') not in ('complete', 'failed') or not expected.get('batch_id'):
        return True
    pair_current = (isinstance(deployed, dict) and deployed.get('status') == expected.get('status')
                and deployed.get('batch_id') == expected['batch_id']
                and deployed.get('date') == expected.get('date')
                and deployed.get('completed_at') == expected.get('completed_at')
                and all(deployed.get(key) == expected.get(key) for key in
                        ('attempt_ok', 'last_attempt_batch_id', 'last_attempt_at', 'failed_at', 'error')))
    if updates_expected is not None and updates_expected != updates_deployed:
        return True
    # A recommendation refresh has its own publication identity. The exchange
    # pair may already be live when new recommendations or a failure notice arrive.
    if ndrc_expected is not None:
        return not pair_current or not isinstance(ndrc_deployed, dict) or any(
            ndrc_expected.get(key) != ndrc_deployed.get(key)
            for key in ('batch_id', 'snapshot_sha256', 'attempt_ok', 'last_attempt_at'))
    return not pair_current


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected', default='data/refresh_status.json')
    parser.add_argument('--site-url', required=True)
    parser.add_argument('--ndrc-status', default='data/ndrc_refresh_status.json')
    parser.add_argument('--updates', default='data/project_updates.json')
    args = parser.parse_args()
    try:
        expected = json.loads(Path(args.expected).read_text())
    except (OSError, ValueError):
        expected = None
    deployed = None
    ndrc_expected, ndrc_deployed = None, None
    try:
        ndrc_expected = json.loads(Path(args.ndrc_status).read_text())
    except (OSError, ValueError):
        pass
    try:
        batch = expected.get('batch_id', '') if expected else ''
        request = Request(args.site_url.rstrip('/') + '/data/refresh_status.json?batch=' + batch,
                          headers={'Cache-Control': 'no-cache', 'User-Agent': 'reits-publication-check'})
        with urlopen(request, timeout=20) as response:
            deployed = json.load(response)
    except (OSError, ValueError):
        pass  # Missing/unreachable live status must cause a deployment retry.
    if ndrc_expected is not None:
        try:
            batch = ndrc_expected.get('batch_id', '')
            request = Request(args.site_url.rstrip('/') + '/data/ndrc_refresh_status.json?batch=' + batch,
                              headers={'Cache-Control': 'no-cache', 'User-Agent': 'reits-publication-check'})
            with urlopen(request, timeout=20) as response:
                ndrc_deployed = json.load(response)
        except (OSError, ValueError):
            pass
    updates_expected, updates_deployed = None, None
    def updates_digest(value):
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                         separators=(',', ':')).encode()).hexdigest()
    try:
        updates_expected = updates_digest(json.loads(Path(args.updates).read_text()))
        request = Request(args.site_url.rstrip('/') + '/data/project_updates.json?v=' + updates_expected[:16],
                          headers={'Cache-Control': 'no-cache', 'User-Agent': 'reits-publication-check'})
        with urlopen(request, timeout=20) as response:
            updates_deployed = updates_digest(json.load(response))
    except (OSError, ValueError):
        pass
    print('due=' + str(publication_due(expected, deployed, ndrc_expected, ndrc_deployed,
                                      updates_expected, updates_deployed)).lower())


if __name__ == '__main__':
    main()
