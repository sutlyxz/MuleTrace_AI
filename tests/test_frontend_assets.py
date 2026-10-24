from html.parser import HTMLParser
from pathlib import Path
import re
import unittest


FRONTEND_ROOT = Path(__file__).resolve().parents[1] / 'app' / 'frontend'


class AssetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.assets = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == 'script' and attributes.get('src'):
            self.assets.append(attributes['src'])
        if tag == 'link' and attributes.get('rel') == 'stylesheet':
            self.assets.append(attributes['href'])


class TestFrontendAssets(unittest.TestCase):
    def test_html_assets_exist_under_assets_directory(self):
        parser = AssetParser()
        parser.feed((FRONTEND_ROOT / 'index.html').read_text(encoding='utf-8'))
        self.assertEqual(len(parser.assets), 9)
        for asset in parser.assets:
            with self.subTest(asset=asset):
                self.assertTrue(asset.startswith('assets/'))
                self.assertTrue((FRONTEND_ROOT / asset).is_file())

    def test_service_worker_caches_existing_files_and_all_html_assets(self):
        parser = AssetParser()
        parser.feed((FRONTEND_ROOT / 'index.html').read_text(encoding='utf-8'))
        source = (FRONTEND_ROOT / 'sw.js').read_text(encoding='utf-8')
        files_block = source.split('const FILES = [', 1)[1].split('];', 1)[0]
        cached_files = re.findall(r'[\x22\x27](\./[^\x22\x27]*)[\x22\x27]', files_block)
        self.assertTrue(cached_files)
        for cached_file in cached_files:
            with self.subTest(cached_file=cached_file):
                self.assertTrue((FRONTEND_ROOT / cached_file).exists())
        for asset in parser.assets:
            self.assertIn('./' + asset, cached_files)


if __name__ == '__main__':
    unittest.main()
