"""Guard the one-card Vault workspace and the read-only journey contract.

These are source-level checks; they do not send WhatsApp messages or charge customers.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_vault_workspace_has_single_customer_and_file_composer():
    page = read("src/components/workspace/service/SecureFiles.tsx")
    assert "api.listContacts()" in page
    assert "chooseCustomer" in page
    assert "sf-workbench" in page
    assert "sf-document-mode" in page
    assert "VaultJourneyPreview" in page
    assert "Upload & publish" in page
    assert "Send Access Vault (no charge)" in page
    assert "sf-review-backdrop" not in page


def test_whatsapp_preview_is_read_only_and_uses_backend_authorities():
    page = read("src/components/workspace/service/SecureFiles.tsx")
    preview = read("src/components/workspace/service/VaultJourneyPreview.tsx")
    assert "getSystemConfigResult( 'vault_whatsapp_template_journey_v1' )" in page
    assert "fetchServicePrices()" in page
    assert "PREVIEW · NOT ISSUED" in preview
    assert "normalMessageCountOnFullManualPath" in preview
    assert "Server-generated signed offer token" in preview
    assert "Vault link plus an optional WhatsApp document" in preview
    assert "read-only reference previews" in preview
    assert "https://wecare.digital/vault/?file=" in preview


def test_vault_registry_key_is_read_only_through_staff_config():
    handler = read("amplify/functions/ai/ai-config-management/handler.py")
    assert "'vault_whatsapp_template_journey_v1'" in handler
    get_block = handler.split("if http_method == 'GET':", 1)[1].split("elif http_method == 'PUT':", 1)[0]
    put_block = handler.split("elif http_method == 'PUT':", 1)[1].split("elif http_method == 'POST':", 1)[0]
    assert "SETTINGS_CONFIG_KEYS | READONLY_REFERENCE_CONFIG_KEYS" in get_block
    assert "cfg_key not in SETTINGS_CONFIG_KEYS:" in put_block
    assert "READONLY_REFERENCE_CONFIG_KEYS" not in put_block


def test_manual_offer_has_an_api_gateway_route():
    script = read("scripts/provision_secure_files_api.py")
    assert '("POST", "/secure-files/{fileId}/send-offer")' in script
