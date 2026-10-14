"""Copy the browser app and reviewed data into a static distribution."""
from pathlib import Path
import shutil


def main():
    root = Path(__file__).resolve().parents[1]
    target = root / 'dist'
    target.mkdir(exist_ok=True)
    shutil.copy2(root / 'index.html', target / 'index.html')
    shutil.copytree(root / 'assets', target / 'assets', dirs_exist_ok=True)
    (target / 'data').mkdir(exist_ok=True)
    shutil.copy2(root / 'data/institutional.json', target / 'data/institutional.json')
    (target / '.nojekyll').write_text('')
    print(target)


if __name__ == '__main__':
    main()
