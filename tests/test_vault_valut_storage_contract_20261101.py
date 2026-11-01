"""Vault paid files are copied to the owner's private valut prefix before publishing.

The public/d prefix is not public for Vault: CloudFront must be denied by
both the media-prefix contract and the edge, and by production bucket policy.
"""

import ast
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECURE_HANDLER = ROOT / "amplify/functions/core/secure-files/handler.py"
MEDIA_PATHS = ROOT / "amplify/functions/shared/lambda_utils/media_paths.py"
EDGE = ROOT / "amplify/functions/edge/get-miss-redirect/handler.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_vault_storage_prefix_is_private_at_both_edge_and_media_paths():
    media = _load_module("vault_media_paths_test", MEDIA_PATHS)
    edge = _load_module("vault_edge_test", EDGE)
    key = "secure/d/public/valut/wecare-digital-doc-abc123.pdf"
    assert media.VAULT_UPLOAD_PREFIX == "secure/d/public/valut/"
    assert media.is_gated(key)
    assert media.public_url(key) == ""
    assert edge._is_denied("/" + key)
    assert edge._is_denied("/secure/d/public/valut/another.pdf")


def test_publish_copies_and_verifies_private_vault_bytes_before_database_write():
    source = SECURE_HANDLER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
              and node.name == "_admin_publish_document")
    segment = ast.get_source_segment(source, fn)
    assert segment is not None

    assert 'vault_key = VAULT_UPLOAD_PREFIX + "wecare-digital-" + file_id' in segment
    assert '"CopySource": {"Bucket": BUCKET, "Key": source_key}' in segment
    assert 'copy_args["CopySourceIfMatch"] = head["ETag"]' in segment
    assert 'copied = _s3_client().head_object(Bucket=BUCKET, Key=vault_key)' in segment
    assert '"s3Key": vault_key' in segment
    assert 'delivery_key = vault_key if deliverable in ("pdf", "image") else ""' in segment

    # No success-shaped Vault row may be persisted before the S3 copy is confirmed.
    assert segment.index("_s3_client().copy_object(**copy_args)") < segment.index("copied = _s3_client().head_object")
    assert segment.index("copied = _s3_client().head_object") < segment.index("files.put_item(")

    # A failed copy stops publication; never fall back to the deleted Drop Docs key.
    assert '"error": "VAULT_STORAGE_COPY_FAILED"' in segment
    assert '"error": "VAULT_STORAGE_VERIFICATION_FAILED"' in segment
    assert '"s3Key": source_key' not in segment


def test_direct_vault_intake_remains_disabled_without_explicit_feature_flag():
    source = SECURE_HANDLER.read_text(encoding="utf-8")
    assert 'os.environ.get("VAULT_DIRECT_UPLOAD_ENABLED", "false")' in source
