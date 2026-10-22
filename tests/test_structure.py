import importlib
from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TestAppStructure(unittest.TestCase):
    def test_backend_engine_is_importable_from_app_package(self):
        module = importlib.import_module('app.backend.engine')

        self.assertTrue(callable(module.health_check))
        self.assertEqual(module.PROJECT_ROOT, PROJECT_ROOT / 'app')

    def test_runtime_assets_live_under_app(self):
        self.assertTrue((PROJECT_ROOT / 'app' / 'frontend' / 'index.html').exists())
        self.assertTrue((PROJECT_ROOT / 'app' / 'data' / 'transactions.csv').exists())
        self.assertTrue((PROJECT_ROOT / 'app' / 'frontend' / 'assets' / 'css').is_dir())
        self.assertTrue((PROJECT_ROOT / 'app' / 'frontend' / 'assets' / 'js').is_dir())
        self.assertTrue((PROJECT_ROOT / 'app' / 'backend' / 'core').is_dir())
        self.assertTrue((PROJECT_ROOT / 'app' / 'backend' / 'services').is_dir())
        self.assertTrue((PROJECT_ROOT / 'app' / 'backend' / 'workers').is_dir())

    def test_backend_modules_share_application_data_paths(self):
        engine = importlib.import_module('app.backend.engine')
        rules = importlib.import_module('app.backend.core.risk_rules')
        tracing = importlib.import_module('app.backend.core.tracing')
        alerts = importlib.import_module('app.backend.services.alert_service')
        scanner = importlib.import_module('app.backend.workers.auto_scanner')

        self.assertEqual(rules.DATA_FILE, engine.TRANSACTIONS_FILE)
        self.assertEqual(tracing.DATA_FILE, engine.TRANSACTIONS_FILE)
        self.assertEqual(alerts.ALERTS_FILE, PROJECT_ROOT / 'app' / 'data' / 'alerts.json')
        self.assertEqual(scanner.WATCHED_FILES, (engine.TRANSACTIONS_FILE, engine.CASE_ACCOUNTS_FILE))

    def test_old_flat_layout_is_absent(self):
        frontend = PROJECT_ROOT / 'app' / 'frontend'
        self.assertEqual(list(frontend.glob('*.css')), [])
        self.assertEqual([path.name for path in frontend.glob('*.js')], ['sw.js'])
        self.assertFalse((PROJECT_ROOT / 'app' / 'backend' / 'investigation').exists())


if __name__ == '__main__':
    unittest.main()
