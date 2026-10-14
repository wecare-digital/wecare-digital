"""Subscriber ID and creation-lock contract tests (offline)."""
import ast
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
from lambda_utils.identity import subscriber_id as sid  # noqa: E402


def test_new_contact_fields_are_unique_and_protected():
    one = sid.new_contact_fields(now=100)
    two = sid.new_contact_fields(now=101)
    assert one["subscriberId"] != two["subscriberId"]
    assert one["workspaceId"] == "wecare-digital"
    assert sid.is_subscriber_id(one["subscriberId"], workspace_id="wecare-digital")
    assert one["locked"] is True
    assert one["lockedReason"] == "created"
    assert one["lockedAt"] == 100
    assert uuid.UUID(one["subscriberId"][-36:]).version == 4


def test_untrusted_subscriber_values_are_rejected():
    assert not sid.is_subscriber_id("WD-wecare-digital-not-a-uuid")
    assert not sid.is_subscriber_id("WD-other-workspace-" + str(uuid.uuid4()))
    assert not sid.is_subscriber_id("WD-wecare-digital-" + str(uuid.uuid5(uuid.NAMESPACE_URL, "test")))


def test_every_known_contact_creation_path_spreads_defaults():
    paths = [
        "core/contacts/handler.py",
        "auth/blog-subscribe/handler.py",
        "auth/customer-profile/handler.py",
        "messaging/inbound-whatsapp-handler/handler.py",
        "messaging/outbound-whatsapp/handler.py",
        "messaging/whatsapp-business-api/flows/subscribe.py",
        "ai/ai-generate-response/handler.py",
    ]
    for path in paths:
        source = (ROOT / "amplify/functions" / path).read_text()
        ast.parse(source)
        assert "new_contact_fields(now=" in source, path


def test_identity_and_lock_not_client_editable():
    source = (ROOT / "amplify/functions/core/contacts/handler.py").read_text()
    allowed = source.split("ALLOWED_UPDATE_FIELDS = {", 1)[1].split("}", 1)[0]
    for forbidden in ("subscriberId", "workspaceId", "locked", "lockedReason", "lockedAt"):
        assert forbidden not in allowed


def test_admin_unlock_and_conditional_archive():
    source = (ROOT / "amplify/functions/core/contacts/handler.py").read_text()
    assert "required_role='Admin'" in source
    assert "attribute_not_exists(#locked) OR #locked = :false" in source
    assert "DELETE_REFUSED_LOCKED = 'CONTACT_LOCKED'" in source


def test_ai_cannot_clear_locked_contact_history():
    source = (ROOT / "amplify/functions/ai/ai-generate-response/handler.py").read_text()
    body = source.split("def _tool_clear_all_contact_data(", 1)[1].split("\ndef ", 1)[0]
    assert "CONTACT_RETENTION_PROTECTION" in body[:250]
