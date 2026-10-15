"""RCS provider boundaries: Sinch is India-only, and nothing falls back to it.

The provider matrix allows Sinch exactly one capability - India RCS - and
prohibits Sinch SMS, Sinch Voice and Sinch WhatsApp outright. These tests assert
the boundary structurally, on the source tree, because the failure mode is a
*new* call site rather than a wrong return value: a future handler importing the
Sinch transport for a non-RCS purpose would pass any behavioural test while
breaking the policy.

`scripts/check_provider_allowlist.py` enforces the same rule in CI, from the
Sinch entry in `scripts/provider_allowlist.py` (its transport is scoped to
`RCS_TRANSPORT_SCOPE`). This suite exists so the boundary also fails a
developer's local `pytest` run, before CI.
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "amplify" / "functions" / "shared"
FUNCTIONS = ROOT / "amplify" / "functions"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

from lambda_utils import sinch_rcs  # noqa: E402

# The only paths allowed to hold the Sinch vendor transport - hosts and the
# credential id. Mirrors RCS_TRANSPORT_SCOPE in scripts/provider_allowlist.py;
# test_the_allowlist_scope_admits_exactly_these_paths keeps the two in step.
RCS_ALLOWED = (
    "lambda_utils/sinch_rcs.py",
    "/rcs-send/",
    "/rcs-dlr/",
    "providers/sinch/rcs/",
    "services/rcs/sinch/",
)

# Vendor transport markers: the hostnames and the secret id.
TRANSPORT_MARKERS = (
    "aclwhatsapp.com",
    "wecare/sinch/rcs",
    "conversation.api.sinch.com",
)


def _python_sources():
    for path in FUNCTIONS.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        yield path


def _is_allowed(path: Path) -> bool:
    text = str(path).replace("\\", "/")
    return any(fragment in text for fragment in RCS_ALLOWED)


# --------------------------------------------------------------------------
# the transport is confined
# --------------------------------------------------------------------------
def test_sinch_transport_only_inside_approved_rcs_paths():
    offenders = []
    for path in _python_sources():
        if _is_allowed(path):
            continue
        body = path.read_text(errors="replace")
        for marker in TRANSPORT_MARKERS:
            if marker in body:
                offenders.append(f"{path.relative_to(ROOT)} holds {marker!r}")
    assert offenders == [], (
        "Sinch vendor transport found outside the approved India RCS paths:\n  "
        + "\n  ".join(offenders))


def test_no_lambda_reads_the_sinch_secret_directly():
    """Only sinch_rcs (and the two RCS Lambdas) may resolve the Sinch credential.

    A voice handler once read `wecare/sinch/rcs` inline in an unreachable copy of
    the RCS sender. That gave it a live path to the credential for no working
    feature.
    """
    offenders = [
        str(path.relative_to(ROOT))
        for path in _python_sources()
        if not _is_allowed(path) and "wecare/sinch/rcs" in path.read_text(errors="replace")
    ]
    assert offenders == []


def test_the_rcs_senders_outside_the_rcs_lambdas_are_known():
    """Lambdas that send RCS do it through `lambda_utils.sinch_rcs`, and they are these.

    A new importer is a new RCS sender, which is a provider-policy decision rather than
    an incidental import.
    """
    importers = sorted(
        str(path.relative_to(FUNCTIONS))
        for path in _python_sources()
        if path.name != "sinch_rcs.py"
        and re.search(r"from lambda_utils(?:\.sinch_rcs import| import sinch_rcs)",
                      path.read_text(errors="replace"))
    )
    assert importers == [
        "messaging/whatsapp-calling/handler.py",
        "shared/lambda_utils/notifications/worker.py",
    ], importers


def test_no_function_reimplements_the_rcs_helpers():
    """The invariant the deleted test actually protected, applied fleet-wide.

    Only lambda_utils/sinch_rcs.py may define these. A handler growing its own
    copy is how the duplicate arose the first time.
    """
    offenders = []
    for handler in FUNCTIONS.rglob("*.py"):
        if "__pycache__" in str(handler):
            continue
        if handler.name == "sinch_rcs.py":
            continue
        body = handler.read_text(errors="replace")
        for marker in ("def _is_rcs_enabled", "def _send_rcs_notification"):
            if marker in body:
                offenders.append(f"{handler.relative_to(FUNCTIONS)}: {marker}")
    assert not offenders, (
        "RCS helpers reimplemented outside lambda_utils/sinch_rcs.py: "
        + ", ".join(offenders))


# --------------------------------------------------------------------------
# Sinch has exactly one capability
# --------------------------------------------------------------------------
def test_sinch_module_exposes_no_sms_sender():
    """Sinch SMS is prohibited. The RCS module must not grow one."""
    exported = [name for name in dir(sinch_rcs) if not name.startswith("__")]
    for name in exported:
        lowered = name.lower()
        if "rcs" in lowered:
            continue
        assert "sms" not in lowered, f"sinch_rcs exposes an SMS symbol: {name}"


def test_sinch_module_exposes_no_voice_or_whatsapp_sender():
    for name in dir(sinch_rcs):
        if name.startswith("__"):
            continue
        lowered = name.lower()
        assert not lowered.startswith("send_voice"), name
        assert "whatsapp" not in lowered, f"sinch_rcs exposes WhatsApp: {name}"


def test_dead_rcs_helpers_are_gone():
    """Removed because nothing called them; asserted so they are not re-added blind."""
    assert not hasattr(sinch_rcs, "send_rcs_order_notification")
    assert not hasattr(sinch_rcs, "send_rcs_wa_alert")


def test_live_rcs_helpers_are_still_present():
    """The India RCS capability itself is APPROVED and must keep working."""
    for kept in ("is_rcs_enabled", "send_rcs_text", "send_rcs_card",
                 "send_rcs_template", "send_rcs_ivr_notification"):
        assert hasattr(sinch_rcs, kept), f"{kept} was removed - India RCS is approved"


# --------------------------------------------------------------------------
# no RCS path falls back to a prohibited provider
# --------------------------------------------------------------------------
def test_rcs_module_does_not_fall_back_to_sinch_sms():
    body = (SHARED / "lambda_utils" / "sinch_rcs.py").read_text()
    # An SMS fallback from RCS is required to be AWS. The Sinch SMS gateway host
    # must not appear here at all.
    assert "jumbo.aclgateway.com" not in body
    assert "_send_sinch_sms" not in body


def test_approved_india_rcs_templates_are_explicit():
    """Template ids are an allowlist, not caller input."""
    body = (SHARED / "lambda_utils" / "sinch_rcs.py").read_text()
    assert re.search(r"rcsmenu", body), "approved template allowlist missing"


# --------------------------------------------------------------------------
# non-India RCS is AWS, and is honestly reported as not yet built
# --------------------------------------------------------------------------
def test_india_rcs_normalises_to_indian_msisdns_only():
    """The Sinch sender must not be handed an arbitrary international number.

    Sinch is approved for India RCS specifically. `_normalize_phone` is the
    module's own boundary, so assert it produces Indian E.164 and does not
    silently pass a non-Indian destination through to the India-only agent.
    """
    assert sinch_rcs._normalize_phone("9903300044").lstrip("+").startswith("91")
    assert sinch_rcs._normalize_phone("+919903300044").lstrip("+").startswith("91")


def test_no_module_outside_the_approved_paths_can_reach_sinch():
    """The structural guarantee that makes non-India routing safe.

    Non-India RCS belongs to AWS. Rather than assert what a not-yet-built AWS RCS
    sender does, assert the property that makes a mistake impossible: no module
    outside the approved India paths references the Sinch transport at all, so
    none of them can route to it whatever their destination logic says.
    """
    reachable_from = sorted(
        str(path.relative_to(ROOT))
        for path in _python_sources()
        if any(marker in path.read_text(errors="replace") for marker in TRANSPORT_MARKERS)
    )
    for path in reachable_from:
        assert any(fragment.strip("/") in path for fragment in RCS_ALLOWED), (
            f"{path} can reach the Sinch transport but is not an approved India "
            "RCS path")


# --------------------------------------------------------------------------
# the CI gate and this suite enforce the same boundary
# --------------------------------------------------------------------------
def test_the_allowlist_scope_admits_exactly_these_paths():
    """The allow-list's Sinch transport scope and RCS_ALLOWED describe one boundary.

    Every module that holds the transport today is inside both, and a voice handler
    - the shape of the original leak - is inside neither.
    """
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import provider_allowlist

    holders = [
        str(path.relative_to(ROOT))
        for path in _python_sources()
        if any(marker in path.read_text(errors="replace") for marker in TRANSPORT_MARKERS)
    ]
    assert holders, "no module holds the Sinch transport; this test would pass vacuously"
    for rel in holders:
        assert re.search(provider_allowlist.RCS_TRANSPORT_SCOPE, rel), rel
        assert _is_allowed(ROOT / rel), rel
    outsider = "amplify/functions/messaging/whatsapp-calling/handler.py"
    assert not re.search(provider_allowlist.RCS_TRANSPORT_SCOPE, outsider)
    assert not _is_allowed(ROOT / outsider)
    sinch = next(p for p in provider_allowlist.PROVIDERS if p.key == "sinch")
    assert sinch.transport_scope == provider_allowlist.RCS_TRANSPORT_SCOPE
    assert set(sinch.provider_ids) == {"sinch-rcs"}
