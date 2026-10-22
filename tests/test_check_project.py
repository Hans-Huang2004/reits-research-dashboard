import contextlib
import io
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts.check_project import check_commands, main, run_checks


class SharedReleaseCheckTests(unittest.TestCase):
    def make_tree(self, root):
        for name in ('assets/app.js', 'assets/nested/helper.mjs', 'assets/legacy.cjs',
                     'assets/styles.css', 'tests/app.test.mjs', 'tests/nested/helpers.test.mjs'):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('')

    def test_checks_discover_all_scripts_and_tests_and_keep_data_gates(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_tree(root)
            commands = check_commands(root)
        self.assertEqual([c[2] for c in commands if c[:2] == ['node', '--check']],
                         ['assets/app.js', 'assets/legacy.cjs', 'assets/nested/helper.mjs'])
        self.assertIn(['node', '--test', 'tests/app.test.mjs', 'tests/nested/helpers.test.mjs'], commands)
        self.assertEqual(commands[0], [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'])
        self.assertEqual(commands[-5:], [
            [sys.executable, 'scripts/validate_data.py', 'data/institutional.json'],
            [sys.executable, 'scripts/validate_public_data.py', 'data/public_reits.json'],
            [sys.executable, 'scripts/validate_ndrc_data.py', 'data/ndrc_recommendations.json',
             '--public-input', 'data/public_reits.json', '--allow-stale-public'],
            [sys.executable, 'scripts/project_updates.py', '--check'],
            [sys.executable, 'scripts/validate_release.py'],
        ])

    def test_failed_frontend_check_stops_the_release_before_building(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_tree(root)
            failed = subprocess.CalledProcessError(1, ['node', '--check', 'assets/app.js'])
            runner = Mock(side_effect=[None, failed])
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(subprocess.CalledProcessError):
                    run_checks(root, runner)
        self.assertEqual(runner.call_count, 2)
        for call in runner.call_args_list:
            self.assertTrue(call.kwargs['check'])
            self.assertEqual(call.kwargs['cwd'], root)

    def test_cli_propagates_a_failed_check_as_a_failure(self):
        failure = subprocess.CalledProcessError(7, ['node', '--test', 'tests/app.test.mjs'])
        with patch('scripts.check_project.run_checks', side_effect=failure):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(), 7)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for the syntax failure integration check')
    def test_actual_invalid_es_module_stops_before_remaining_checks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'assets').mkdir()
            (root / 'tests').mkdir()
            (root / 'assets/app.js').write_text('export const broken = ;\n')
            (root / 'tests/app.test.mjs').write_text('')
            calls = []

            def runner(command, **kwargs):
                calls.append(command)
                return subprocess.run(command, capture_output=True, **kwargs)

            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(subprocess.CalledProcessError) as failure:
                    run_checks(root, runner)
        self.assertEqual(failure.exception.cmd, ['node', '--check', '--input-type=module'])
        self.assertEqual(len(calls), 2)


if __name__ == '__main__':
    unittest.main()
