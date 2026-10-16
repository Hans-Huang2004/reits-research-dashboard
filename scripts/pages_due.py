"""Retry publication when the public website has not received the complete pair."""
import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen


def publication_due(expected, deployed):
    if not isinstance(expected, dict) or expected.get('status') != 'complete' or not expected.get('batch_id'):
        return True
    return not (isinstance(deployed, dict) and deployed.get('status') == 'complete'
                and deployed.get('batch_id') == expected['batch_id']
                and deployed.get('date') == expected.get('date')
                and deployed.get('completed_at') == expected.get('completed_at'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected', default='data/refresh_status.json')
    parser.add_argument('--site-url', required=True)
    args = parser.parse_args()
    try:
        expected = json.loads(Path(args.expected).read_text())
    except (OSError, ValueError):
        expected = None
    deployed = None
    try:
        batch = expected.get('batch_id', '') if expected else ''
        request = Request(args.site_url.rstrip('/') + '/data/refresh_status.json?batch=' + batch,
                          headers={'Cache-Control': 'no-cache', 'User-Agent': 'reits-publication-check'})
        with urlopen(request, timeout=20) as response:
            deployed = json.load(response)
    except (OSError, ValueError):
        pass  # Missing/unreachable live status must cause a deployment retry.
    print('due=' + str(publication_due(expected, deployed)).lower())


if __name__ == '__main__':
    main()
