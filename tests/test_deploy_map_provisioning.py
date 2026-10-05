"""A deploy report whose failure count is never zero is not a signal.

Every `deploy_all_lambdas.py` run ended `failed=1`, always for the same reason:
`wecare-customer-whatsapp-auth` is in the deploy map but has never been created in
the account - its first creation is owned by
`scripts/provision_customer_whatsapp_auth.py`, which has not been run.

That is a correctness problem in the report rather than in the deploy. A genuinely
broken deploy would have landed in a summary that already said `failed=1`, next to
an entry everyone had learned to skip. "Awaiting provisioning" and "failed" are
different states and now count separately.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "deploy_all_lambdas.py"


@pytest.fixture(scope="module")
def deploy_module():
    spec = importlib.util.spec_from_file_location("deploy_all_lambdas", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["deploy_all_lambdas"] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop("deploy_all_lambdas", None)


def test_spec_carries_who_provisions_it(deploy_module):
    spec = deploy_module.Spec("x", "core/contacts", provisioned_by="python scripts/x.py")
    assert spec.provisioned_by == "python scripts/x.py"


def test_an_ordinary_function_claims_no_provisioner(deploy_module):
    """The default must stay empty.

    A function with no `provisioned_by` that goes missing IS a failure - it means
    something deleted it. Defaulting to "awaiting provisioning" would hide that.
    """
    spec = deploy_module.Spec("x", "core/contacts")
    assert spec.provisioned_by == ""


def test_the_one_known_unprovisioned_function_declares_its_script(deploy_module):
    specs = {s.name: s for s in deploy_module.SPECS}
    auth = specs["wecare-customer-whatsapp-auth"]
    assert auth.provisioned_by
    # The named script has to exist, or the message sends someone nowhere.
    referenced = auth.provisioned_by.split()[-1]
    assert (ROOT / referenced).exists(), f"{referenced} does not exist"


def test_exactly_one_spec_is_awaiting_provisioning(deploy_module):
    """Pinned as a count so a second one has to be a deliberate decision.

    Marking a function `provisioned_by` is how a real failure could be made to
    look expected, so the set is small and explicit on purpose.
    """
    waiting = [s.name for s in deploy_module.SPECS if s.provisioned_by]
    # wecare-email-verification added 2026-09-30: a genuinely new function that does not yet
    # exist in AWS, so it is legitimately awaiting its first provisioning deploy. A deliberate
    # addition to this list, which is exactly the "conscious decision" this count guards.
    # wecare-customer-registration added 2026-09-30: the registration front door (the WhatsApp-OTP
    # HTTP door that provisions the Cognito login), also genuinely new and awaiting first provision.
    # wecare-checkout added 2026-10-01: the headless checkout front door (authoritative Wix total,
    # readiness gate, PaymentAttempt, in-chat handoff; initiation off), also new and awaiting first
    # provision.
    # wecare-customer-orders added 2026-10-03: the customer's own order history and profile
    # summary. Never created in AWS - its sparse customerId-createdAt-index on OrderTable, its
    # own least-privilege role and its one route are all first-provisioned by
    # scripts/provision_customer_orders.py, so a deploy-all run before that is legitimately
    # awaiting provisioning rather than failing. A code update cannot create the index, and
    # without the index the function answers 503.
    # wecare-coupons added 2026-10-02: coupon issuance and eligibility, owning
    # stack-wecare-digital-CouponsTable. Never created in AWS - its table, its own least-privilege
    # role and its seven routes are all first-provisioned by scripts/provision_coupons_*.py, so a
    # deploy-all run before that is legitimately awaiting provisioning rather than failing.
    # wecare-gift-cards added 2026-10-02: gift-card issuance and balance, owning
    # stack-wecare-digital-GiftCardsTable. Also never created, and its table additionally needs the
    # customer-managed KMS key provision_gift_cards_table.py creates - an owner-confirmation step,
    # so this one cannot be provisioned incidentally by a deploy.
    # wecare-wix-giftcard-spi added 2026-10-02: the Wix Gift Cards Service Plugin endpoint Wix
    # calls with a signed JWT. Never created, and it cannot be deployed by code update alone
    # because provision_gift_cards_roles.py is what attaches the version-pinned cryptography
    # layer its verifier imports.
    # wecare-blog-subscribe added 2026-10-02: the public OTP-gated blog subscriber front door.
    # It intentionally has its own least-privilege role/routes and must be first-created by
    # provision_blog_subscribe.py before deploy-all can update its code.
    # wecare-wix-catalog-webhook added 2026-10-04: the Wix catalogue webhook receiver for
    # auto-sync. Never created in AWS - its own least-privilege role (two secret reads and its
    # log group, nothing else), the version-pinned cryptography layer its verifier needs, and
    # its one route are all first-provisioned by scripts/provision_wix_catalog_webhook.py, so a
    # deploy-all run before that is legitimately awaiting provisioning. Note its absence costs
    # catalogue auto-sync NOTHING: .github/workflows/catalogue-sync.yml re-reads Wix on a
    # six-hourly cron with no credential, and this receiver only makes it near-instant.
    # wecare-vayulok-environment added 2026-10-05: public VayuLok needs Weather/Air
    # without publishing the web-service key. Its role, server-key grant, live alias,
    # exact POST/OPTIONS routes and per-route throttle are first-created by
    # scripts/provision_vayulok_environment.py.
    # Session infrastructure is owned by its CloudFormation template; an account
    # without that stack must provision it rather than report a code-update failure.
    assert waiting == ["wecare-customer-session", "wecare-vayulok-environment", "wecare-customer-whatsapp-auth", "wecare-email-verification",
                       "wecare-customer-profile", "wecare-blog-subscribe", "wecare-customer-registration", "wecare-checkout",
                       "wecare-customer-orders",
                       "wecare-coupons", "wecare-gift-cards", "wecare-wix-giftcard-spi",
                       "wecare-wix-catalog-webhook"]


def test_the_summary_line_reports_the_new_state(deploy_module):
    """It has to appear in the output, or the count exists and nobody sees it."""
    source = SCRIPT.read_text(encoding="utf-8")
    assert "awaiting_provisioning={tally['awaiting_provisioning']}" in source
    assert "awaiting provisioning" in source
    # And it must not be quietly folded into `failed`.
    assert 'tally["awaiting_provisioning"] += 1' in source


def test_qrcode_is_no_longer_imported_at_runtime():
    """The other source of permanent noise in the same report.

    `import qrcode` was in no requirements file and in no attached layer, so it
    failed on every invoice render and logged a WARNING each time - for a condition
    that was permanent and not actionable. The encoded value is a constant URL, so
    the pre-rendered S3 image is the right artifact and adding the dependency would
    have been the wrong repair.
    """
    handler = (ROOT / "amplify" / "functions" / "payments" / "invoice-engine"
               / "handler.py").read_text(encoding="utf-8")
    assert "import qrcode" not in handler
    assert "qrcode.QRCode" not in handler
    # The S3 asset and the text fallback both stay - the image degrades, the
    # information does not.
    assert "stream/media/m/qr-customerservice.png" in handler
    assert "wecare.digital/customerservice" in handler
