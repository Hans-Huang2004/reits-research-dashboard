"""Build the static project library with project data collected from official exchanges."""
from pathlib import Path
import gzip
import shutil
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main():
    root = Path(__file__).resolve().parents[1]
    from scripts.validate_release import validate_release
    validate_release(root)
    from scripts.project_updates import validate
    validate(json.loads((root / 'data/project_updates.json').read_text(encoding='utf-8')))
    target = root / 'dist'
    target.mkdir(exist_ok=True)
    shutil.copy2(root / 'index.html', target / 'index.html')
    shutil.copy2(root / 'LICENSE', target / 'LICENSE.txt')
    shutil.copytree(root / 'assets', target / 'assets', dirs_exist_ok=True)
    (target / 'data').mkdir(exist_ok=True)
    shutil.copy2(root / 'data/institutional.json', target / 'data/institutional.json')
    shutil.copy2(root / 'data/public_reits.json', target / 'data/public_reits.json')
    shutil.copy2(root / 'data/ndrc_recommendations.json', target / 'data/ndrc_recommendations.json')
    shutil.copy2(root / 'data/project_updates.json', target / 'data/project_updates.json')
    ndrc_status = root / 'data/ndrc_refresh_status.json'
    if ndrc_status.exists():
        shutil.copy2(ndrc_status, target / 'data/ndrc_refresh_status.json')
    status = root / 'data/refresh_status.json'
    if status.exists():
        shutil.copy2(status, target / 'data/refresh_status.json')
    (target / 'data/public_reits.json.gz').write_bytes(gzip.compress((root / 'data/public_reits.json').read_bytes(), mtime=0))
    (target / 'data/project_updates.json.gz').write_bytes(gzip.compress((root / 'data/project_updates.json').read_bytes(), mtime=0))
    (target / '.nojekyll').write_text('')
    print(target)


if __name__ == '__main__':
    main()
