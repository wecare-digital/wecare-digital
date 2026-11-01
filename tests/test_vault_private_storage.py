"""Regression tests for the paid Vault S3 prefix and its CDN denial.

Run: python -m unittest discover -s tests -p 'test_vault_private_storage.py'
These tests do not require AWS credentials or customer file bytes.
"""
from __future__ import annotations

import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


paths = load_module("vault_media_paths", "amplify/functions/shared/lambda_utils/media_paths.py")
edge = load_module("vault_edge_gate", "amplify/functions/edge/get-miss-redirect/handler.py")


class VaultPrivateStorageTests(unittest.TestCase):
    def test_exact_customer_selected_prefix(self):
        self.assertEqual(paths.VAULT_UPLOAD_PREFIX, "secure/d/public/valut/")

    def test_python_public_url_never_exposes_vault_objects(self):
        key = paths.VAULT_UPLOAD_PREFIX + "wecare-digital-test.pdf"
        self.assertTrue(paths.is_gated(key))
        self.assertEqual(paths.public_url(key), "")

    def test_edge_refuses_the_entire_vault_prefix(self):
        for uri in (
            "/secure/d/public/valut/secret.pdf",
            "/secure/d/public/%76alut/secret.pdf",
            "/secur%65/d/public/valut/secret.pdf",
        ):
            with self.subTest(uri=uri):
                self.assertTrue(edge._is_denied(uri))

    def test_edge_removes_object_bytes_even_if_s3_returns_200(self):
        body = "confidential-file-content"
        response = {
            "status": "200", "body": body,
            "headers": {
                "content-length": [{"key": "Content-Length", "value": str(len(body))}],
                "etag": [{"key": "ETag", "value": "sensitive-etag"}],
            },
        }
        event = {"Records": [{"cf": {
            "request": {"uri": "/secure/d/public/valut/secret.pdf"},
            "response": response,
        }}]}
        denied = edge.handler(event, None)
        self.assertEqual(denied["status"], "302")
        self.assertEqual(denied["body"], "")
        self.assertNotIn("etag", denied["headers"])
        self.assertEqual(denied["headers"]["content-length"][0]["value"], "0")

    def test_edge_and_canonical_private_prefixes_match(self):
        self.assertEqual(
            set(edge.PRIVATE_DELIVERABLE_PREFIXES),
            set(paths.PRIVATE_DELIVERABLE_PREFIXES),
        )

    def test_approved_public_asset_remains_public(self):
        key = "secure/d/public/whatsapp/wa-tpl/whatsapp-header.png"
        self.assertFalse(edge._is_denied("/" + key))
        self.assertFalse(paths.is_gated(key))

    def test_other_customer_private_prefixes_stay_gated(self):
        for key in (
            "secure/u/dropdocs/file.pdf",
            "secure/d/public/Invoice/customer_invoice/receipt.png",
            "secure/d/public/whatsapp/incoming/file.jpg",
        ):
            with self.subTest(key=key):
                self.assertTrue(edge._is_denied("/" + key))
                self.assertTrue(paths.is_gated(key))


if __name__ == "__main__":
    unittest.main()
