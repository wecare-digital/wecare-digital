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


def test_every_awaiting_function_declares_a_script_that_exists(deploy_module):
    """Each `provisioned_by` must name a real file, or the message sends someone nowhere.

    Asserted for every awaiting function rather than one pinned example, so the check
    does not rot the next time a specific function goes live and its marker is dropped.
    """
    awaiting = [s for s in deploy_module.SPECS if s.provisioned_by]
    assert awaiting, "expected at least one function awaiting first provisioning"
    for s in awaiting:
        referenced = s.provisioned_by.split()[-1]
        assert (ROOT / referenced).exists(), (
            f"{s.name}: provisioned_by names {referenced}, which does not exist"
        )


def test_exactly_one_spec_is_awaiting_provisioning(deploy_module):
    """The awaiting-provisioning set is pinned exactly, so every change is deliberate.

    (The name is historical - the set started at one. It is now the explicit list
    below.) Marking a function `provisioned_by` is how a real deploy failure could be
    made to look expected, so the set stays small and explicit on purpose. When a
    function goes live and is captured in config/lambda-env-manifest.json, its marker
    must be dropped here in the same change - enforced by
    test_awaiting_provisioning_functions_are_absent_from_the_live_manifest.
    """
    waiting = [s.name for s in deploy_module.SPECS if s.provisioned_by]
    # NOW LIVE - markers dropped 2026-10-23 after confirming each is recorded in
    # config/lambda-env-manifest.json with real captured env (concrete table names,
    # KMS key ids, Meta/Razorpay ids): wecare-customer-session, wecare-checkout,
    # wecare-customer-whatsapp-auth and wecare-meta-catalog-sync. A function that is
    # recorded live cannot also be awaiting its first provisioning; the invariant is
    # pinned by test_awaiting_provisioning_functions_are_absent_from_the_live_manifest.
    # The entries below are the functions still genuinely awaiting first provisioning.
    #
    # wecare-email-verification added 2026-09-30: a genuinely new function that does not yet
    # exist in AWS, so it is legitimately awaiting its first provisioning deploy. A deliberate
    # addition to this list, which is exactly the "conscious decision" this count guards.
    # wecare-customer-registration added 2026-09-30: the registration front door (the WhatsApp-OTP
    # HTTP door that provisions the Cognito login), also genuinely new and awaiting first provision.
    # wecare-customer-orders added 2026-10-03: the customer's own order history and profile
    # summary. Never created in AWS - its sparse customerId-createdAt-index on OrderTable, its
    # own least-privilege role and its one route are all first-provisioned by
    # scripts/provision_customer_orders.py, so a deploy-all run before that is legitimately
    # awaiting provisioning rather than failing. A code update cannot create the index, and
    # without the index the function answers 503.
    # wecare-coupons was REMOVED 2026-10-18: the coupon system is retired entirely (no coupon
    # Lambda, no CouponsTable, no /coupons routes). The only discount is the standalone Delight
    # policy, which is pure arithmetic in default_coupon.py and provisions nothing.
    # wecare-blog-subscribe added 2026-10-02: the public OTP-gated blog subscriber front door.
    # It intentionally has its own least-privilege role/routes and must be first-created by
    # provision_blog_subscribe.py before deploy-all can update its code.
    # wecare-vayulok-environment added 2026-10-05: public VayuLok needs Weather/Air
    # without publishing the web-service key. Its role, server-key grant, live alias,
    # exact POST/OPTIONS routes and per-route throttle are first-created by
    # scripts/provision_vayulok_environment.py.
    # wecare-customer-invoice added 2026-10-06: a customer's own invoice as a 300-second
    # presigned download. Never created in AWS - its own least-privilege role (four reads
    # plus the rate-limit counter, no write verb of any kind) and its one route are
    # first-provisioned by scripts/provision_customer_invoice.py, so a deploy-all run before
    # that is legitimately awaiting provisioning rather than failing. It is a SEPARATE
    # function from wecare-customer-orders on purpose: the route needs dynamodb:GetItem,
    # s3:GetObject and a second dynamodb:Query, and all three are specifically refused by
    # that function's pinned policy and by six equality assertions in
    # tests/test_customer_orders_iam.py. Its absence costs the page NOTHING today:
    # featureFlags.invoiceDownload ships false, so /orders/ renders "No invoice yet" and
    # issues no request to this route at all.
    # wecare-service-requests added 2026-10-06 (Phase O-1): Submit Request / Request Amendment
    # intents, the customer's own request list, and activation from the razorpay-webhook hint.
    # Never created in AWS - its table + two GSIs, its own least-privilege role, its two routes
    # and its alarm are first-provisioned by scripts/provision_service_requests.py.
    assert waiting == ["wecare-vayulok-environment", "wecare-email-verification",
                       "wecare-customer-profile", "wecare-blog-subscribe",
                       "wecare-customer-registration", "wecare-customer-orders",
                       "wecare-service-requests", "wecare-customer-invoice"]


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


@pytest.mark.parametrize('name', ['wecare-invoice-engine', 'wecare-outbound-whatsapp'])
def test_payment_deploy_refuses_missing_expectations_without_explicit_sync(deploy_module, name):
    from unittest.mock import MagicMock
    lam = MagicMock()
    with pytest.raises(ValueError, match='payment expectations missing'):
        deploy_module.prepare_payment_environment(lam, name, {'Environment': {'Variables': {}}},
            sync_from_checkout=False, dry_run=False)
    lam.update_function_configuration.assert_not_called()


def test_payment_environment_sync_preserves_other_settings_and_revision(deploy_module):
    from unittest.mock import MagicMock
    lam = MagicMock()
    old = {'RevisionId':'revision-1','Environment':{'Variables':{'SEND_MODE':'LIVE'}}}
    expected = {'SEND_MODE':'LIVE','EXPECTED_CONFIGURATION_NAME':'verified-config',
                'EXPECTED_PROVIDER_MID':'verified-mid'}
    lam.get_function_configuration.side_effect = [
        {'Environment':{'Variables':{'EXPECTED_CONFIGURATION_NAME':'verified-config',
            'EXPECTED_PROVIDER_MID':'verified-mid','DO_NOT_COPY_SECRET':'never-copied'}}},
        {'Environment':{'Variables':expected}},
    ]
    deploy_module.prepare_payment_environment(lam,'wecare-invoice-engine',old,
        sync_from_checkout=True,dry_run=False)
    lam.update_function_configuration.assert_called_once_with(FunctionName='wecare-invoice-engine',
        RevisionId='revision-1',Environment={'Variables':expected})
    lam.get_waiter.return_value.wait.assert_called_once_with(FunctionName='wecare-invoice-engine')


def test_payment_environment_dry_run_never_mutates_aws(deploy_module):
    from unittest.mock import MagicMock
    lam = MagicMock()
    lam.get_function_configuration.return_value = {'Environment':{'Variables':{
        'EXPECTED_CONFIGURATION_NAME':'verified-config','EXPECTED_PROVIDER_MID':'verified-mid'}}}
    deploy_module.prepare_payment_environment(lam,'wecare-outbound-whatsapp',{},
        sync_from_checkout=True,dry_run=True)
    lam.update_function_configuration.assert_not_called()


def test_payment_sync_refuses_an_unconfigured_source(deploy_module):
    from unittest.mock import MagicMock
    lam=MagicMock()
    lam.get_function_configuration.return_value={'Environment':{'Variables':{}}}
    with pytest.raises(ValueError,match='incomplete payment expectations'):
        deploy_module.prepare_payment_environment(lam,'wecare-invoice-engine',{},
            sync_from_checkout=True,dry_run=False)
    lam.update_function_configuration.assert_not_called()


# ---------------------------------------------------------------------------
# Manifest <-> awaiting-provisioning consistency
# ---------------------------------------------------------------------------
# A function marked `provisioned_by` is asserting "I do not exist in AWS yet; my
# first creation is owned by a provision_*.py script." `config/lambda-env-manifest.json`
# asserts the opposite for any function it lists: "this is the recorded LIVE
# environment." Both cannot be true at once. When a provisioned function finally
# goes live and its env is captured by `scripts/env_manifest.py --export`, the
# `provisioned_by` marker in deploy_all_lambdas.py has become stale and must be
# dropped - otherwise the awaiting-provisioning count in
# test_exactly_one_spec_is_awaiting_provisioning carries a false entry, and that
# count is the signal a real missing function is supposed to trip. Nothing checked
# this, so five markers (checkout, customer-session, customer-whatsapp-auth,
# meta-catalog-sync, secure-files) sat stale while those functions were already
# live and fully recorded in the manifest. This pins the invariant so the drift
# cannot recur silently.

import json

MANIFEST = ROOT / "config" / "lambda-env-manifest.json"


def _manifest_functions() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["functions"]


def test_awaiting_provisioning_functions_are_absent_from_the_live_manifest(deploy_module):
    """A function cannot be awaiting its first deploy AND recorded as live.

    If it is in the manifest, `env_manifest.py --export` read its live environment
    from AWS, so it exists and the `provisioned_by` marker is stale. Drop the marker
    (and the matching entry in test_exactly_one_spec_is_awaiting_provisioning) in the
    same change that records the function live.
    """
    manifest = _manifest_functions()
    waiting = {s.name for s in deploy_module.SPECS if s.provisioned_by}
    both = sorted(name for name in waiting if name in manifest)
    assert not both, (
        "These functions are marked `provisioned_by` (awaiting first provisioning) "
        "yet appear in config/lambda-env-manifest.json as live. One assertion is "
        "stale - drop the provisioned_by marker now that the function is recorded "
        f"live: {both}"
    )


def test_every_manifest_function_is_a_known_deploy_target(deploy_module):
    """Nothing should be recorded live that no deploy path owns.

    The manifest is regenerated from live AWS, so a name here that is in neither the
    generic SPECS list nor the known named/standalone deploys is an orphan: a live
    function the repo no longer describes, or a rename that left the old name behind.
    Either way it is drift worth surfacing rather than a value to enshrine.
    """
    manifest = set(_manifest_functions())
    spec_names = {s.name for s in deploy_module.SPECS}
    # The script's own records of functions deployed OUTSIDE the generic SPECS list:
    # DELEGATED (owned by a dedicated deploy_*.py), SKIPPED (container image via CI).
    delegated = set(getattr(deploy_module, "DELEGATED", {}))
    skipped = set(getattr(deploy_module, "SKIPPED", {}))
    # wecare-get-miss-redirect is a Lambda@Edge function. It is not a SPECS/DELEGATED/
    # SKIPPED target because edge functions cannot carry environment variables at all,
    # so env_manifest.py records it with an empty env rather than as a deploy target.
    EDGE = {"wecare-get-miss-redirect"}
    known = spec_names | delegated | skipped | EDGE
    orphans = sorted(manifest - known)
    assert not orphans, (
        "Functions recorded live in the manifest but owned by no deploy path "
        f"(not in SPECS, not a known named/standalone deploy): {orphans}"
    )
