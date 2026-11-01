"""Keep staff Vault storage private and independent of customer Drop Docs.

The retired customer-documents-to-Vault bridge must not be a fallback for new
staff Vault uploads. Existing historical Vault records and paid entitlements
remain readable independently of the customer upload source.
"""

import ast
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECURE_HANDLER = ROOT / "amplify/functions/core/secure-files/handler.py"
MEDIA_PATHS = ROOT / "amplify/functions/shared/lambda_utils/media_paths.py"
EDGE = ROOT / "amplify/functions/edge/get-miss-redirect/handler.py"
VAULT_UI = ROOT / "src/components/workspace/service/SecureFiles.tsx"
DROP_DOCS_UI = ROOT / "src/components/workspace/service/Documents.tsx"
CLIENT = ROOT / "src/api/client.ts"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _function_source(name: str) -> str:
    source = SECURE_HANDLER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
              and node.name == name)
    segment = ast.get_source_segment(source, fn)
    assert segment
    return segment


def test_vault_storage_prefix_is_private_at_edge_and_in_media_paths():
    media = _load_module("vault_media_paths_test", MEDIA_PATHS)
    edge = _load_module("vault_edge_test", EDGE)
    key = "secure/d/public/valut/wecare-digital-example.pdf"
    assert media.VAULT_UPLOAD_PREFIX == "secure/d/public/valut/"
    assert media.is_gated(key)
    assert media.public_url(key) == ""
    assert edge._is_denied("/" + key)
    assert edge._is_denied("/secure/d/public/valut/another.pdf")


def test_staff_vault_upload_sets_exact_private_key_and_confirms_s3_bytes():
    init = _function_source("_upload_init")
    confirm = _function_source("_upload_confirm")
    assert 'key = VAULT_UPLOAD_PREFIX + basename' in init
    assert 'generate_presigned_url(' in init
    assert '"put_object"' in init
    assert '"status": "pending"' in init
    assert 'head = _s3_client().head_object(Bucket=BUCKET, Key=upload_key)' in confirm
    assert 'upload_key.startswith(VAULT_UPLOAD_PREFIX)' in confirm
    assert 'ConditionExpression="#s = :pending"' in confirm
    assert '"status": "active"' in confirm
    assert "DROPDOCS_PREFIX" not in init + confirm
    assert "DOCUMENTS_TABLE" not in init + confirm


def test_dropdocs_publish_endpoint_has_no_active_bridge_side_effect():
    bridge = _function_source("_admin_publish_document")
    assert '"error": "DROP_DOCS_VAULT_PUBLISH_RETIRED"' in bridge
    assert "410" in bridge
    assert "_s3_client()" not in bridge
    assert "copy_object" not in bridge
    assert "_table(" not in bridge
    assert "put_item" not in bridge
    assert "request_payment" not in bridge


def test_customer_dropdocs_ui_does_not_publish_or_send_vault_payments():
    source = DROP_DOCS_UI.read_text(encoding="utf-8")
    client = CLIENT.read_text(encoding="utf-8")
    vault = VAULT_UI.read_text(encoding="utf-8")
    assert "initDocumentUpload" in source
    assert "confirmDocumentUpload" in source
    assert "publishDocumentToVault" not in source
    assert "requestSecureFilePayment" not in source
    assert "sendSecureFileAccess" not in source
    assert "Upload & send Review & Pay" not in source
    assert "publishDocumentToVault" not in client
    assert "initVaultFileUpload" in client and "confirmVaultFileUpload" in client
    assert "initVaultFileUpload" in vault
    assert "confirmVaultFileUpload" in vault


def test_direct_vault_intake_is_default_off_until_secure_prod_release():
    source = SECURE_HANDLER.read_text(encoding="utf-8")
    assert 'os.environ.get("VAULT_DIRECT_UPLOAD_ENABLED", "false")' in source
