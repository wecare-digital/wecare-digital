import ast
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_regeneration_preserves_current_checkout_fee_and_canonical_links(tmp_path):
    spec = importlib.util.spec_from_file_location('faq_sync', ROOT / 'scripts/sync_faq.py')
    sync = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sync)
    sync.PY_OUTPUT = str(tmp_path / 'knowledge.py')
    sync.generate_python(sync.load_config())
    tree = ast.parse(Path(sync.PY_OUTPUT).read_text())
    node = next(node for node in tree.body if isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'FAQ_CONFIG' for t in node.targets))
    published = ast.literal_eval(node.value)
    entries = {entry['id']: entry for entry in published['faqs']}
    assert '2.5%' in entries['convenience-fee']['answer']
    assert entries['track']['answer'].find('https://wecare.digital/orders/') >= 0
    assert 'https://wecare.digital/account/sign-in/' in entries['account']['answer']
    text = json.dumps(published)
    assert 'store.wecare.digital' not in text
    assert '2.2%' not in text and '2% convenience' not in text
    assert 'orders directly through chat' not in text
    assert 'automatically generated after payment' not in entries['invoice']['answer']


def test_public_faq_buttons_target_current_public_pages():
    faq = json.loads((ROOT / 'shared/faq-config.json').read_text())
    public = json.loads((ROOT / 'config/public-pages.json').read_text())
    pages = {item['path'].rstrip('/') or '/' for item in public['pages']}
    spec = importlib.util.spec_from_file_location('faq_redirects', ROOT / 'scripts/provision_legacy_redirects.py')
    redirects = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(redirects)
    # Withdrawn front doors may resolve through an exact permanent redirect.
    # Keep its destination in the generated public-page contract.
    routes = {rule['source']: rule['target'] for rule in redirects.desired_redirects()
              if rule['status'] == '301' and rule['source'].startswith('/')}
    for entry in faq['faqs']:
        if entry.get('ctaPath'):
            path = entry['ctaPath']
            target = routes.get(path, path)
            assert (target.rstrip('/') or '/') in pages, path
