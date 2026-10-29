"""Run source security contracts against the exact modular Lambda zip."""
from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

HERE = Path(__file__).resolve().parent


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(
            'Usage: python3 tools/customer-commerce/verify_release.py '
            '/absolute/path/to/customer-commerce-runtime.zip'
        )
    archive = Path(sys.argv[1]).resolve()
    if not archive.is_file():
        raise SystemExit(f'Runtime archive not found: {archive}')

    with tempfile.TemporaryDirectory() as raw:
        target = Path(raw)
        with zipfile.ZipFile(archive) as zipped:
            names = set(zipped.namelist())
            required = {
                'index.py', 'handler.py', 'customer_oauth.py',
                'customer_oauth_config.py', 'customer_oauth_store.py',
                'customer_oauth_web.py', 'customer_oauth_authorize.py',
                'connection_assets.py',
            }
            if names != required:
                raise SystemExit(
                    f'Unexpected runtime file set; missing={sorted(required - names)} '
                    f'extra={sorted(names - required)}'
                )
            zipped.extractall(target)

        sys.path.insert(0, str(target))
        try:
            packed = load('packed_customer_commerce', target / 'index.py')
            packed_handler = importlib.import_module('handler')
            packed_auth = importlib.import_module('customer_oauth')
            packed_config = importlib.import_module('customer_oauth_config')
            packed_store = importlib.import_module('customer_oauth_store')
            packed_web = importlib.import_module('customer_oauth_web')
            packed_authorize = importlib.import_module('customer_oauth_authorize')

            conversation = load('conversation_contract', HERE / 'verify.py')
            oauth = load('oauth_contract', HERE / 'verify_oauth.py')
            conversation.app = packed_handler
            oauth.auth = packed_auth
            oauth.auth_config = packed_config
            oauth.auth_store = packed_store
            oauth.auth_web = packed_web
            oauth.auth_authorize = packed_authorize

            suite = unittest.TestSuite([
                unittest.defaultTestLoader.loadTestsFromTestCase(
                    conversation.ConversationContract
                ),
                unittest.defaultTestLoader.loadTestsFromTestCase(
                    oauth.OAuthContract
                ),
            ])
            result = unittest.TextTestRunner(verbosity=2).run(suite)
            if not result.wasSuccessful():
                raise SystemExit(1)
            if not callable(packed.handler):
                raise SystemExit('index.handler is not callable')
        finally:
            sys.path.remove(str(target))


if __name__ == '__main__':
    main()
