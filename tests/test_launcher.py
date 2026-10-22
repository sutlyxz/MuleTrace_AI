import importlib
import hashlib
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def launcher(self):
        self.assertTrue((PROJECT_ROOT / 'scripts' / 'run.py').is_file())
        return importlib.import_module('scripts.run')

    def test_missing_env_is_copied_but_existing_env_is_never_overwritten(self):
        launcher = self.launcher()
        (self.root / '.env.example').write_text('FRONTEND_PORT=8000\n', encoding='utf-8')
        launcher.ensure_environment_file(self.root)
        self.assertEqual((self.root / '.env').read_text(), 'FRONTEND_PORT=8000\n')
        (self.root / '.env').write_text('PRIVATE_TEST_KEY=fake-local-only\n', encoding='utf-8')
        launcher.ensure_environment_file(self.root)
        self.assertEqual((self.root / '.env').read_text(), 'PRIVATE_TEST_KEY=fake-local-only\n')

    def test_local_commands_use_current_paths_and_settings(self):
        launcher = self.launcher()
        settings = Mock(frontend_port=8081, scan_interval=5.0)
        frontend, scanner = launcher.local_commands(self.root, settings)
        self.assertIn(str(self.root / 'app' / 'frontend'), frontend)
        self.assertIn('8081', frontend)
        self.assertIn('127.0.0.1', frontend)
        self.assertIn('app.backend.workers.auto_scanner', scanner)
        self.assertEqual(scanner[-2:], ['--interval', '5.0'])

    def test_stopping_children_waits_and_kills_only_if_needed(self):
        launcher = self.launcher()
        process = Mock()
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired('fake-child', 5), 0]
        launcher.stop_processes([process])
        process.terminate.assert_called_once()
        process.kill.assert_called_once()
        self.assertEqual(process.wait.call_count, 2)

    def test_requirements_are_synchronized_and_stamp_is_written_after_success(self):
        launcher = self.launcher()
        executable = self.root / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        executable.parent.mkdir(parents=True)
        executable.touch()
        requirements = self.root / 'requirements.txt'
        requirements.write_text('example-package==1\n', encoding='utf-8')
        stamp = self.root / '.venv' / '.requirements.sha256'
        with patch.object(launcher.subprocess, 'run', return_value=Mock(returncode=0)) as run:
            self.assertEqual(launcher.prepare_runtime(self.root), executable)
            self.assertIn('--no-cache-dir', run.call_args.args[0])
        self.assertEqual(stamp.read_text(), hashlib.sha256(requirements.read_bytes()).hexdigest())
        old_stamp = stamp.read_text()
        requirements.write_text('example-package==2\n', encoding='utf-8')
        with patch.object(launcher.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'fake-pip')):
            with self.assertRaises(subprocess.CalledProcessError):
                launcher.prepare_runtime(self.root)
        self.assertEqual(stamp.read_text(), old_stamp)

    def test_frontend_gets_no_private_keys_and_children_are_cleaned_on_failure(self):
        launcher = self.launcher()
        settings = Mock(frontend_port=8081, scan_interval=5.0)
        frontend = Mock()
        scanner = Mock()
        frontend.poll.return_value = 1
        scanner.poll.return_value = None
        environment = {'PATH': os.defpath, 'AWS_SECRET_ACCESS_KEY': 'fake-private', 'OTHER_PRIVATE_KEY': 'fake-other'}
        with patch.object(launcher.subprocess, 'Popen', side_effect=[frontend, scanner]) as spawn, patch('sys.stdout', new_callable=io.StringIO):
            result = launcher.run_local(self.root, settings, environment, open_browser=False)
        self.assertEqual(result, 1)
        self.assertNotIn('AWS_SECRET_ACCESS_KEY', spawn.call_args_list[0].kwargs['env'])
        self.assertNotIn('OTHER_PRIVATE_KEY', spawn.call_args_list[0].kwargs['env'])
        self.assertEqual(spawn.call_args_list[1].kwargs['env']['AWS_SECRET_ACCESS_KEY'], 'fake-private')
        scanner.terminate.assert_called_once()


class PrivateConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def configuration(self):
        self.assertTrue((PROJECT_ROOT / 'app' / 'backend' / 'config.py').is_file())
        return importlib.import_module('app.backend.config')

    def test_no_env_uses_local_defaults_and_requires_no_keys(self):
        config = self.configuration()
        settings = config.RuntimeSettings.from_environment(config.load_environment(self.root, {}))
        self.assertEqual(settings.frontend_port, 8000)
        self.assertEqual(settings.scan_interval, 3.0)

    def test_reload_picks_up_changes_and_drops_removed_private_keys(self):
        config = self.configuration()
        path = self.root / '.env'
        path.write_text('FRONTEND_PORT=8081\nPRIVATE_TEST_KEY=fake-first\n', encoding='utf-8')
        first = config.load_environment(self.root, {})
        path.write_text('FRONTEND_PORT=8082\n', encoding='utf-8')
        second = config.load_environment(self.root, {})
        self.assertEqual(first['PRIVATE_TEST_KEY'], 'fake-first')
        self.assertEqual(second['FRONTEND_PORT'], '8082')
        self.assertNotIn('PRIVATE_TEST_KEY', second)

    def test_local_file_overrides_parent_and_preserves_literal_key_characters(self):
        config = self.configuration()
        (self.root / '.env').write_text("FRONTEND_PORT=8082\nPRIVATE_TEST_KEY='fake-${VALUE}#=%value%'\n", encoding='utf-8')
        environment = config.load_environment(self.root, {'FRONTEND_PORT': '8001', 'VALUE': 'not-for-expansion'})
        self.assertEqual(environment['FRONTEND_PORT'], '8082')
        self.assertEqual(environment['PRIVATE_TEST_KEY'], 'fake-${VALUE}#=%value%')

    def test_invalid_public_settings_do_not_echo_values(self):
        config = self.configuration()
        for name in ('FRONTEND_PORT', 'SCAN_INTERVAL'):
            with self.subTest(name=name):
                with self.assertRaises(ValueError) as raised:
                    config.RuntimeSettings.from_environment({name: 'fake-private-value'})
                self.assertNotIn('fake-private-value', str(raised.exception))
        for value in ('0', '-1', 'nan', 'inf'):
            with self.subTest(interval=value), self.assertRaises(ValueError):
                config.RuntimeSettings.from_environment({'SCAN_INTERVAL': value})

    def test_direct_scanner_rejects_non_finite_intervals_before_scanning(self):
        scanner = importlib.import_module('app.backend.workers.auto_scanner')
        for interval in ('nan', 'inf', '-inf'):
            with self.subTest(interval=interval):
                with patch('sys.argv', ['scanner', '--interval=' + interval, '--once']), patch('sys.stderr'), patch.object(scanner, 'scan_risk_alerts') as scan:
                    with self.assertRaises(SystemExit) as raised:
                        scanner.main()
                self.assertEqual(raised.exception.code, 2)
                scan.assert_not_called()


if __name__ == '__main__':
    unittest.main()
