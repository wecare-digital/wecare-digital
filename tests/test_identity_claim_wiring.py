"""Every strong ContactsTable writer must reserve identity before mutation."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

WRITERS = (
    "amplify/functions/core/contacts/handler.py",
    "amplify/functions/messaging/inbound-whatsapp-handler/handler.py",
    "amplify/functions/messaging/outbound-whatsapp/handler.py",
    "amplify/functions/ai/ai-generate-response/handler.py",
    "amplify/functions/auth/customer-profile/handler.py",
    "amplify/functions/auth/customer-registration/handler.py",
    "amplify/functions/auth/blog-subscribe/handler.py",
    "amplify/functions/messaging/whatsapp-business-api/flows/subscribe_profile.py",
)


def source(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_every_known_identity_writer_imports_the_registry():
    for rel in WRITERS:
        assert "identity_claims" in source(rel), rel


def test_every_known_identity_writer_claims_before_mutating():
    for rel in WRITERS:
        text = source(rel)
        assert "identity_claims.claim_identities(" in text, rel


def test_current_subscribe_profile_is_claim_backed():
    text = source("amplify/functions/messaging/whatsapp-business-api/flows/subscribe.py")
    assert "profile_version') or '') == '3'" in text
    assert "subscribe_profile.handle_review" in text
    assert "identity_claims.claim_identities(" in source(
        "amplify/functions/messaging/whatsapp-business-api/flows/subscribe_profile.py")
