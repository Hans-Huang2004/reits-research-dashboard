"""Export the validated recommendation/matching snapshot and its delivery receipt."""
import argparse
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.validate_ndrc_data import validate

LABELS = {'confirmed': '已确认匹配', 'candidate': '候选待核实', 'unmatched': '未匹配'}
HEADERS = ['推荐记录ID', '推荐项目名称', '主申报地方／中央企业', '官方行业分类',
           '拟发售基金总额（亿元）', '国家发展改革委推荐日期', '推荐业务类型', '匹配状态',
           '关联交易所申报ID', '关联申报名称', '关联业务类型', '关联基金ID', '关联基金代码',
           '交易所受理日期', '推荐至受理天数', '日期异常说明', '匹配依据', '证据链接',
           '候选申报ID', '候选说明', '核查说明', '推荐来源', '首次发现时间', '发现类型']


def join(values):
    return ' | '.join(str(value) for value in values if value is not None and value != '')


def cell(value):
    # Preserve names as text when opened in a spreadsheet program.
    if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
        return "'" + value
    return value


def row(item):
    relations = item['relations'] if item['match_status'] == 'confirmed' else []
    candidates = item['candidates']
    return [item['id'], item['name'], item['applicant_region'], item['industry_official'],
            item['proposed_fund_amount_yi'], item['recommended_date'], item['business_type'],
            LABELS[item['match_status']], join(r['exchange_event_id'] for r in relations),
            join(r['event_name'] for r in relations), join(r['business_type'] for r in relations),
            join(r.get('fund_id') for r in relations), join(r.get('fund_code') for r in relations),
            join(r.get('accepted_date') for r in relations), join(r.get('days_to_acceptance') for r in relations),
            join(r.get('chronology_note') for r in relations), join(r.get('note') for r in relations),
            join(dict.fromkeys(url for r in relations for url in r.get('evidence_urls', []))),
            join(r['exchange_event_id'] for r in candidates), join(r.get('note') for r in candidates),
            item.get('match_review', {}).get('note', ''), item['source_url'], item['first_seen_at'],
            '历史回填' if item.get('discovery_type') == 'baseline' else '后续新增']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=ROOT / 'data/ndrc_recommendations.json')
    parser.add_argument('--public-input', type=Path, default=ROOT / 'data/public_reits.json')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'outputs/ndrc')
    args = parser.parse_args()
    snapshot = json.loads(args.input.read_text())
    public = json.loads(args.public_input.read_text())
    audit = validate(snapshot, public)
    input_sha = hashlib.sha256(args.input.read_bytes()).hexdigest()
    manifests = []
    for path in (ROOT / 'data/source_manifest/ndrc').glob('*.json'):
        entry = json.loads(path.read_text())
        if entry.get('snapshot_sha256') == input_sha and entry.get('reviewed_workpaper'):
            manifests.append((path, entry))
    if not manifests:
        raise ValueError('No approved matching workpaper found for this snapshot')
    manifest_path, manifest = sorted(manifests, key=lambda item: item[1].get('generated_at', ''))[-1]
    reviewed_path = ROOT / manifest['reviewed_workpaper']['path']
    if hashlib.sha256(reviewed_path.read_bytes()).hexdigest() != input_sha:
        raise ValueError('Published snapshot and approved workpaper do not reconcile')
    snapshot = json.loads(reviewed_path.read_text())
    args.output_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    for label, items in [('全部推荐及历史匹配', snapshot['items']),
                         ('待核实与未匹配', [item for item in snapshot['items'] if item['match_status'] != 'confirmed'])]:
        path = args.output_dir / f'{label}_{snapshot["date"]}.csv'
        with path.open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(HEADERS)
            writer.writerows([cell(value) for value in row(item)] for item in items)
        with path.open(encoding='utf-8-sig', newline='') as stream:
            actual = list(csv.reader(stream))
        if len(actual) != len(items) + 1 or any(len(r) != len(HEADERS) for r in actual):
            raise ValueError('CSV export row/column reconciliation failed')
        outputs.append({'path': str(path.relative_to(ROOT)), 'rows': len(items),
                        'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    receipt = {'generated_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds'),
               'data_date': snapshot['date'], 'collected_at': snapshot['updated_at'], 'version': snapshot['schema_version'],
               'snapshot_path': str(args.input.relative_to(ROOT)),
               'snapshot_sha256': input_sha,
               'public_input_path': str(args.public_input.relative_to(ROOT)),
               'public_input_sha256': hashlib.sha256(args.public_input.read_bytes()).hexdigest(),
               'source_versions': snapshot['source_versions'], 'validation': audit,
               'source_manifest': {'path': str(manifest_path.relative_to(ROOT)),
                                   'sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest()},
               'reviewed_workpaper': manifest['reviewed_workpaper'],
               'matching_audit_workpaper': str(reviewed_path.parent / 'matching_audit.json'),
               'outputs': outputs, 'amount_unit': '亿元', 'amount_basis': '拟发售基金总额',
               'unmatched_basis': '尚未确认关联当前交易所记录，不推断未申报或发行概率'}
    path = args.output_dir / 'delivery_manifest.json'
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'validation': audit, 'outputs': outputs}, ensure_ascii=False))


if __name__ == '__main__':
    main()
