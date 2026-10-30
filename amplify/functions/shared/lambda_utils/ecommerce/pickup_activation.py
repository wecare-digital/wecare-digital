"""Fail-closed rollout switch for paid Pickup Request checkout and WhatsApp sending.

The previous Meta-published F005 pickup asset had a cloned F004 completion marker
and omitted the pickup fields. Source fixes alone cannot safely authorize money.
Enable only after a live Meta asset readback matches the corrected source JSON,
both WhatsApp Lambdas are deployed/tested, and staff have performed a paid
end-to-end test (including idempotent completion) on an authorized account.

No remote writes or reads here: checkout_preflight stays pure. Operators set
these TWO Lambda environment variables together on commerce and the sender:
  PICKUP_SERVICE_ENABLED=true
  PICKUP_PUBLISHED_ASSET_SHA_PREFIX=9d37ad0dce3cecb0

The second value is an explicit release attestation, not an API-level Meta
verification. It must never be set based solely on an APPROVED template or
PUBLISHED Flow badge: inspect the actual Flow JSON before releasing.
"""
from __future__ import annotations

import os

# SHA-256 of the exact UTF-8 JSON file in flows/published/request-pickup.json
# after PR #1967 (full hash 9d37ad0dce3cecb09f6788ab54295d954287dad849fd5f2fe220759482c7c6ca).
EXPECTED_META_ASSET_SHA_PREFIX = "9d37ad0dce3cecb0"
FEATURE_FLAG = "PICKUP_SERVICE_ENABLED"
ASSET_ATTESTATION = "PICKUP_PUBLISHED_ASSET_SHA_PREFIX"


def enabled() -> bool:
    """Strict explicit opt-in; missing, stale or mistyped evidence keeps payments off."""
    return (
        os.environ.get(FEATURE_FLAG, "").strip().lower() == "true"
        and os.environ.get(ASSET_ATTESTATION, "").strip().lower()
        == EXPECTED_META_ASSET_SHA_PREFIX
    )


__all__ = ["enabled", "FEATURE_FLAG", "ASSET_ATTESTATION",
           "EXPECTED_META_ASSET_SHA_PREFIX"]
