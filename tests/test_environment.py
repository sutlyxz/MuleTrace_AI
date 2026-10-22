from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TestEnvironmentTemplate(unittest.TestCase):
    def test_template_settings_are_used_by_compose_with_matching_defaults(self):
        example = PROJECT_ROOT / '.env.example'
        self.assertTrue(example.is_file())
        settings = dict(
            line.split('=', 1)
            for line in example.read_text(encoding='utf-8').splitlines()
            if line.strip() and not line.lstrip().startswith('#')
        )
        self.assertEqual(settings, {'FRONTEND_PORT': '8000', 'SCAN_INTERVAL': '3'})
        compose = (PROJECT_ROOT / 'compose.yaml').read_text(encoding='utf-8')
        for name, default in settings.items():
            self.assertIn('${' + name + ':-' + default + '}', compose)

    def test_docker_build_excludes_local_environment_files(self):
        exclusions = (PROJECT_ROOT / '.dockerignore').read_text(encoding='utf-8').splitlines()
        self.assertIn('.env', exclusions)
        self.assertIn('.env.*', exclusions)


if __name__ == '__main__':
    unittest.main()
