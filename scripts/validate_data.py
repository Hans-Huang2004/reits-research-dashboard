"""Offline completeness, identity, amounts and official detail URL validation."""
from __future__ import annotations
import json
import math
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs


def validate(snapshot):
    if snapshot.get('schema_version') != 1 or snapshot.get('coverage', {}).get('complete') is not True:
        raise ValueError('A complete schema_version=1 snapshot is required')
    rows = snapshot.get('items')
    if not isinstance(rows, list) or not rows:
        raise ValueError('No project records')
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError('Duplicate project IDs')
    if snapshot['coverage'].get('count') != len(rows):
        raise ValueError('Coverage count mismatch')
    for row in rows:
        if not row.get('name') or not row.get('source_id') or not row.get('match_keywords'):
            raise ValueError('Missing project identity or match provenance')
        prefix = 'SSE_' if row['ex'] == '上交所' else 'SZSE_'
        if row['id'] != prefix + row['source_id']:
            raise ValueError('Canonical project identity mismatch')
        value = row.get('amt')
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
            raise ValueError('Invalid planned amount')
        url = urlparse(row['source_url'])
        query = parse_qs(url.query)
        if url.scheme != 'https':
            raise ValueError('Official source URLs must use HTTPS')
        if row['ex'] == '上交所':
            if url.hostname != 'bond.sse.com.cn' or not url.path.endswith('/information/index_detail.shtml') or query.get('bound_id') != [row['source_id']]:
                raise ValueError('SSE source URL does not identify this project')
        elif row['ex'] == '深交所':
            if url.hostname != 'bond.szse.cn' or url.path != '/disclosure/progressinfo/index.html' or query.get('xmbh') != [row['source_id']] or query.get('CATALOGID') != ['xmjdxx_xq']:
                raise ValueError('SZSE source URL does not identify this project')
        else:
            raise ValueError('Unexpected exchange')
        source = row.get('classification_source', 'unknown')
        evidence = row.get('classification_evidence', [])
        if source not in ('verified', 'inferred', 'manual', 'keyword', 'unknown'):
            raise ValueError('Unexpected classification source')
        if not isinstance(evidence, list) or any(
            not isinstance(e, dict) or not e.get('title') or
            urlparse(e.get('url', '')).scheme not in ('http', 'https') or
            not urlparse(e.get('url', '')).hostname for e in evidence
        ):
            raise ValueError('Invalid classification evidence link')
        if source == 'verified' and (row.get('classification_confidence') != 'confirmed' or not evidence or row.get('psub') == '待分类'):
            raise ValueError('Verified classification must have explicit asset evidence')
    for key, name in [('SSE', '上交所'), ('SZSE', '深交所')]:
        meta = snapshot['source_status'][key]
        if meta.get('ok') is not True or meta.get('total') != sum(r['ex'] == name for r in rows):
            raise ValueError('Exchange completeness/count mismatch')
        if {q.get('keyword') for q in meta.get('queries', [])} != {'持有型不动产', '机构间REIT'}:
            raise ValueError('Both keyword queries are required for each exchange')
    return {'count': len(rows), 'SSE': snapshot['source_status']['SSE']['total'], 'SZSE': snapshot['source_status']['SZSE']['total']}


if __name__ == '__main__':
    result = validate(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')))
    print(json.dumps(result))
