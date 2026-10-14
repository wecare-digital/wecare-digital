"""SEO lists published page data without calling the removed legacy page inventory."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_page_inventory_matches_generated_native_catalog():
    spec = importlib.util.spec_from_file_location('page_catalog', ROOT / 'amplify/functions/operations/seo-tools/page_catalog.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    catalog = json.loads((ROOT / 'config/public-pages.json').read_text())['pages']
    result = module.list_site_pages()
    assert [p['path'] for p in result] == [p['path'] for p in catalog]
    assert all(p['url'] == 'https://wecare.digital' + p['path'] for p in result)
    assert [p['metaDescription'] for p in result] == [p['description'] for p in catalog]
