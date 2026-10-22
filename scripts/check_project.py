"""Run the same offline release checks in CI and before publishing Pages."""
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def check_commands(root=ROOT):
    root = Path(root)
    assets = sorted(path.relative_to(root).as_posix() for path in (root / 'assets').rglob('*')
                    if path.is_file() and path.suffix in ('.js', '.mjs', '.cjs'))
    javascript_tests = sorted(path.relative_to(root).as_posix()
                              for path in (root / 'tests').rglob('*.test.mjs'))
    if not assets or not javascript_tests:
        raise ValueError('JavaScript assets and regression tests are required for release checks')
    python = sys.executable
    return [
        [python, '-m', 'unittest', 'discover', '-s', 'tests', '-v'],
        *[['node', '--check', path] for path in assets],
        ['node', '--test', *javascript_tests],
        [python, 'scripts/validate_data.py', 'data/institutional.json'],
        [python, 'scripts/validate_public_data.py', 'data/public_reits.json'],
        [python, 'scripts/validate_ndrc_data.py', 'data/ndrc_recommendations.json',
         '--public-input', 'data/public_reits.json', '--allow-stale-public'],
        [python, 'scripts/project_updates.py', '--check'],
        [python, 'scripts/validate_release.py'],
    ]


def run_checks(root=ROOT, runner=None):
    runner = runner or subprocess.run
    root = Path(root)
    for command in check_commands(root):
        print('Checking: ' + shlex.join(command), flush=True)
        if command[:2] == ['node', '--check']:
            # Browser .js files are ES modules. Explicit syntax mode avoids
            # relying on Node's package-type detection for malformed modules.
            path = root / command[-1]
            mode = 'commonjs' if path.suffix == '.cjs' else 'module'
            runner(['node', '--check', '--input-type=' + mode],
                   input=path.read_bytes(), cwd=root, check=True)
        else:
            runner(command, cwd=root, check=True)


def main():
    try:
        run_checks()
    except subprocess.CalledProcessError as exc:
        print('Release check failed: ' + shlex.join(exc.cmd), file=sys.stderr)
        return exc.returncode if exc.returncode > 0 else 1
    except (OSError, ValueError) as exc:
        print('Release checks could not run: ' + str(exc), file=sys.stderr)
        return 1
    print('All offline release checks passed.', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
