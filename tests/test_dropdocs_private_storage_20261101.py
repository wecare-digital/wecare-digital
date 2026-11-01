"""Regression checks for private customer Drop Docs storage.

New manual, WhatsApp Flow and service-request uploads must all write under
secure/d/public/drop-docs/. Despite the public/ ancestor, neither the edge nor
public_url may expose these documents. Old secure/u/dropdocs/ keys remain gated
for historical customer document reads.

Run: python -m unittest discover -s tests -p 'test_dropdocs_private_storage_20261101.py'
"""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "amplify/functions/shared/lambda_utils/media_paths.py"
EDGE = ROOT / "amplify/functions/edge/get-miss-redirect/handler.py"
SERVICE_API = ROOT / "amplify/functions/core/service-api/handler.py"
FLOW = ROOT / "amplify/functions/messaging/whatsapp-business-api/flows/drop_docs.py"
PROMOTION = ROOT / "amplify/functions/shared/lambda_utils/ecommerce/dropdocs_storage.py"
VAULT = ROOT / "amplify/functions/core/secure-files/handler.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


paths = load_module("dropdocs_media_paths_test", MEDIA)
edge = load_module("dropdocs_edge_test", EDGE)


class DropDocsPrivateStorageTests(unittest.TestCase):
    def test_exact_separate_customer_and_staff_prefixes(self):
        self.assertEqual(paths.DROP_DOCS_UPLOAD_PREFIX, "secure/d/public/drop-docs/")
        self.assertEqual(paths.VAULT_UPLOAD_PREFIX, "secure/d/public/valut/")
        self.assertNotEqual(paths.DROP_DOCS_UPLOAD_PREFIX, paths.VAULT_UPLOAD_PREFIX)
        self.assertEqual(paths.LEGACY_DROP_DOCS_UPLOAD_PREFIX, "secure/u/dropdocs/")

    def test_public_media_builder_refuses_customer_drop_docs(self):
        key = paths.DROP_DOCS_UPLOAD_PREFIX + "manual/wecare-digital-abc.pdf"
        self.assertTrue(paths.is_gated(key))
        self.assertEqual(paths.public_url(key), "")
        self.assertTrue(paths.is_gated(paths.LEGACY_DROP_DOCS_UPLOAD_PREFIX + "old.pdf"))

    def test_cdn_edge_refuses_customer_docs_even_on_successful_origin_response(self):
        for uri in (
            "/secure/d/public/drop-docs/a.pdf",
            "/secure/d/public/%64rop-docs/a.pdf",
            "/secur%65/d/public/drop-docs/a.pdf",
        ):
            with self.subTest(uri=uri):
                self.assertTrue(edge._is_denied(uri))
        response = {"status": "200", "body": "private-bytes", "headers": {
            "content-length": [{"key": "Content-Length", "value": "13"}],
            "etag": [{"key": "ETag", "value": "sensitive-etag"}],
        }}
        event = {"Records": [{"cf": {
            "request": {"uri": "/secure/d/public/drop-docs/manual/x.pdf"},
            "response": response,
        }}]}
        refused = edge.handler(event, None)
        self.assertEqual(refused["status"], "302")
        self.assertEqual(refused["body"], "")
        self.assertNotIn("etag", refused["headers"])

    def test_edge_and_app_use_identical_private_prefix_lists(self):
        self.assertEqual(
            tuple(edge.PRIVATE_DELIVERABLE_PREFIXES),
            tuple(paths.PRIVATE_DELIVERABLE_PREFIXES),
        )
        self.assertFalse(edge._is_denied("/secure/d/public/drop-docs-public/logo.svg"))
        self.assertFalse(paths.is_gated("secure/d/public/drop-docs-public/logo.svg"))

    def test_all_new_customer_uploads_use_same_private_prefix(self):
        manual = SERVICE_API.read_text(encoding="utf-8")
        flow = FLOW.read_text(encoding="utf-8")
        promotion = PROMOTION.read_text(encoding="utf-8")
        for source in (manual, flow, promotion):
            ast.parse(source)
            self.assertNotIn("VAULT_UPLOAD_PREFIX", source)
        self.assertIn("media_paths.DROP_DOCS_UPLOAD_PREFIX + 'manual/'", manual)
        self.assertIn("replacement_key = media_paths.DROP_DOCS_UPLOAD_PREFIX", manual)
        self.assertIn('key = media_paths.DROP_DOCS_UPLOAD_PREFIX + "flow/', flow)
        self.assertIn("destination = media_paths.DROP_DOCS_UPLOAD_PREFIX", promotion)
        self.assertIn("if not media_paths.is_gated(destination):", promotion)

    def test_old_drop_docs_records_remain_readable_by_stored_key(self):
        docs = SERVICE_API.read_text(encoding="utf-8")
        self.assertIn("storage_key = media_paths.canonical(storage_key)", docs)
        self.assertIn("Params={'Bucket': DOCS_S3_BUCKET, 'Key': storage_key}", docs)
        self.assertIn("DROPDOCS_PREFIX = media_paths.LEGACY_DROP_DOCS_UPLOAD_PREFIX",
                      VAULT.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
