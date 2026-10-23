"""Regression coverage for public catalog-media path handling."""
import importlib.util
import io
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
HANDLER = ROOT / "amplify/functions/ecommerce/catalog-media/handler.py"


class CatalogMediaDeliveryTest(unittest.TestCase):
    def setUp(self):
        boto3 = types.ModuleType("boto3")
        self.s3 = Mock()
        boto3.client = Mock(return_value=self.s3)
        exceptions = types.ModuleType("botocore.exceptions")
        exceptions.ClientError = type("ClientError", (Exception,), {})
        spec = importlib.util.spec_from_file_location("catalog_media_under_test", HANDLER)
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"boto3": boto3,
                                     "botocore": types.ModuleType("botocore"),
                                     "botocore.exceptions": exceptions}):
            spec.loader.exec_module(self.module)

    def test_known_public_and_gateway_paths_read_only_product_master(self):
        for prefix in ("/catalog-media/", "/prod/catalog-media/", "/api/catalog-media/"):
            with self.subTest(prefix=prefix):
                self.s3.reset_mock()
                self.s3.get_object.return_value = {"Body": io.BytesIO(b"png"), "ETag": '"etag"'}
                result = self.module.handler({"rawPath": prefix + "anew-4096.png"}, None)
                self.assertEqual(result["statusCode"], 200)
                self.assertEqual(result["headers"]["Content-Type"], "image/png")
                self.assertTrue(result["isBase64Encoded"])
                self.assertEqual(result["body"], "cG5n")
                self.s3.get_object.assert_called_once_with(
                    Bucket="wecare-digital-get", Key="secure/catalog/products/anew-4096.png")

    def test_rejects_unrelated_and_traversal_paths_without_s3_read(self):
        paths = (
            "/secure/catalog/catalog-v3-final-manifest.json",
            "/prod/catalog-media/../catalog-v3-final-manifest.json",
            "/api/catalog-media/%2e%2e%2fsecret-4096.png",
            "/catalog-media/a/b-4096.png",
            "/unknown/catalog-media/anew-4096.png",
            "/catalog-media/ANew-4096.png",
            "/catalog-media/anew-4096.jpg",
        )
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(self.module.handler({"rawPath": path}, None)["statusCode"], 404)
        self.s3.get_object.assert_not_called()

    def test_http_api_request_context_fallback(self):
        self.s3.get_object.return_value = {"Body": io.BytesIO(b"png")}
        result = self.module.handler(
            {"requestContext": {"http": {"method": "GET", "path": "/prod/catalog-media/anew-4096.png"}}},
            None)
        self.assertEqual(result["statusCode"], 200)

    def test_rejects_post_without_s3_read(self):
        result = self.module.handler(
            {"rawPath": "/api/catalog-media/anew-4096.png", "httpMethod": "POST"}, None)
        self.assertEqual(result["statusCode"], 405)
        self.s3.get_object.assert_not_called()


if __name__ == "__main__":
    unittest.main()
