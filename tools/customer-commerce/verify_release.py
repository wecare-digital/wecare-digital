"""Run the same security contracts against the exact compiled Lambda artifact."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit('Usage: python3 tools/customer-commerce/verify_release.py /absolute/path/to/index.py')
    packed = load('packed_customer_commerce', Path(sys.argv[1]))
    conversation = load('conversation_contract', HERE / 'verify.py')
    oauth = load('oauth_contract', HERE / 'verify_oauth.py')
    conversation.app = packed
    oauth.auth = packed
    suite = unittest.TestSuite([
        unittest.defaultTestLoader.loadTestsFromTestCase(conversation.ConversationContract),
        unittest.defaultTestLoader.loadTestsFromTestCase(oauth.OAuthContract),
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == '__main__': main()
