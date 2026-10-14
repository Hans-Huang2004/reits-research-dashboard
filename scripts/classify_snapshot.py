"""Apply repository asset evidence while preserving the source collection date."""
from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from collectors.institutional import reclassify_snapshot, write_snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', default='data/institutional.json')
    parser.add_argument('--overrides', default='config/classification_overrides.json')
    parser.add_argument('--archive-dir', default='snapshots')
    args = parser.parse_args()
    snapshot = json.loads(Path(args.input).read_text(encoding='utf-8'))
    overrides = json.loads(Path(args.overrides).read_text(encoding='utf-8'))
    reclassify_snapshot(snapshot, overrides)
    write_snapshot(snapshot, args.input, args.archive_dir)
    print(json.dumps(snapshot['quality']['classification_counts'], ensure_ascii=False))


if __name__ == '__main__':
    main()
