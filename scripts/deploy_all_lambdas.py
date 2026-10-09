#!/usr/bin/env python3
r"""Deploy every zip-packaged Python Lambda in this account. Cross-platform.

Why this exists
---------------
The historical deploy-all entrypoints were PowerShell (``_deploy_all.ps1``,
``deploy_all.ps1``) and used ``\``-separated paths, so they only ran on Windows.
On macOS/Linux there was no way to deploy the fleet. This script is the portable
replacement and, since those scripts were deleted on 2026-09-20, the only one.

It also fixed two defects they carried, recorded here because the packages they
produced are still live:

* ``Compress-Archive`` writes zip entry names with ``\`` separators (visible in
  the live packages for ``wecare-contacts`` and ``wecare-whatsapp-business-api``
  as ``lambda_utils\response.py``). Lambda happens to tolerate it, but
  ``zipfile`` here writes proper ``/`` entries.
* The PowerShell deploy-all copied ``flows\*.py`` only, dropping the
  ``flows/*.json`` flow definitions that ``wecare-whatsapp-business-api``
  serves. Extra directories are copied whole here.

Packaging layout (unchanged from the PowerShell scripts)
-------------------------------------------------------
    handler.py                     <- the function's handler
    lambda_utils/*.py              <- amplify/functions/shared/lambda_utils
    static_knowledge_base.py       <- amplify/functions/shared
    modules/                       <- if the function has one
    <extra dirs>/                  <- e.g. flows/ for whatsapp-business-api
    <extra files>                  <- e.g. service_api.py

Zips are built deterministically (fixed mtimes, sorted entries) so redeploying
unchanged code produces an identical ``CodeSha256``. That matters because the
SnapStart publisher keys off "does the alias sha match $LATEST": stable shas
mean unchanged functions do not accumulate pointless versions.

SnapStart / alias
-----------------
``update_function_code`` only moves ``$LATEST``. The HTTP API invokes the
``live`` alias, so nothing reaches production until a version is published and
the alias moves. That is ``scripts/snapstart_publish.py``, which this script
invokes at the end unless ``--no-publish`` is passed. See
``.kiro/steering/lambda-snapstart-deploy.md``.

Usage
-----
    python scripts/deploy_all_lambdas.py                    # whole fleet, then publish
    python scripts/deploy_all_lambdas.py wecare-contacts    # named functions only
    python scripts/deploy_all_lambdas.py --dry-run          # build + validate, upload nothing
    python scripts/deploy_all_lambdas.py --no-publish       # update $LATEST, leave aliases
    python scripts/deploy_all_lambdas.py --list             # show the function map

Exit codes: 0 everything succeeded, 1 at least one function failed.
"""

from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import io
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:  # pragma: no cover
    sys.exit("boto3 is required: pip install boto3  (or use .venv/bin/python)")

REGION = "us-east-1"
ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS = ROOT / "amplify" / "functions"
SHARED = FUNCTIONS / "shared"
LAMBDA_UTILS = SHARED / "lambda_utils"
STATIC_KB = SHARED / "static_knowledge_base.py"

# Fixed timestamp so identical content yields an identical CodeSha256.
ZIP_DATE = (2026, 1, 1, 0, 0, 0)

# Directories never worth shipping.
EXCLUDE_DIRS = {"__pycache__", "tests", ".pytest_cache"}

# Modules the python3.12 runtime provides without bundling.
RUNTIME_PROVIDED = {"boto3", "botocore", "urllib3", "dateutil", "s3transfer", "jmespath", "six"}


class Spec:
    """How one Lambda is assembled."""

    def __init__(
        self,
        name: str,
        source: str,
        *,
        standalone: bool = False,
        extra_dirs: Sequence[str] = (),
        extra_files: Sequence[str] = (),
        provisioned_by: str = "",
    ) -> None:
        self.name = name
        self.source = FUNCTIONS / source
        # provisioned_by: the script that must CREATE this function before this
        # one can update it. When set and the function is absent, that is
        # "awaiting provisioning", not a deploy failure.
        #
        # This matters because the two were indistinguishable. Every deploy-all run
        # ended `failed=1` for wecare-customer-whatsapp-auth, which has never been
        # created - so a genuinely broken deploy would have arrived in a report that
        # already said failed=1, and the habit of ignoring it was already trained.
        # A counter that is never zero is not a signal.
        self.provisioned_by = provisioned_by
        # standalone: handler.py only. Used where the handler imports nothing
        # from lambda_utils, and where the live package is handler.py alone
        # (url-shortener, site-language — see scripts/deploy_site_language.py).
        self.standalone = standalone
        self.extra_dirs = list(extra_dirs)
        self.extra_files = list(extra_files)

    @property
    def handler_file(self) -> Path:
        return self.source / "handler.py"


# Every zip-packaged function in us-east-1, mapped to its source.
#
# Deliberately excluded:
#   wecare-docs-scraper — PackageType=Image, ships via
#                         .github/workflows/docs-scraper-deploy.yml.
SPECS: List[Spec] = [
    Spec("wecare-customer-session", "ecommerce/customer-session",
         provisioned_by="CloudFormation amplify/infra/customer-sessions.json"),
    # --- core ---
    Spec("wecare-auth-middleware", "core/auth-middleware"),
    Spec("wecare-automation-rules", "core/automation-rules"),
    Spec("wecare-contacts", "core/contacts"),
    Spec("wecare-conversation-meta", "core/conversation-meta"),
    Spec(
        "wecare-secure-files",
        "core/secure-files",
        # Both are imported lazily inside functions rather than at module load, so
        # they must be listed explicitly - nothing at import time reveals them.
        # razorpay_orders     only when paid downloads are enabled
        # whatsapp_delivery   only when sending a payment request or a file
        extra_files=["razorpay_orders.py", "whatsapp_delivery.py"],
        # provisioned_by is deliberately NOT set. The function exists and deploys
        # normally, so marking it would turn a genuine future failure - the function
        # having been deleted - into "awaiting provisioning", which reads as expected.
        # That is exactly what test_exactly_one_spec_is_awaiting_provisioning guards,
        # and it caught this. Its provisioning script is recorded in
        # docs/SECURE-FILE-SHARING.md instead.
    ),
    # Absent until now, which meant provision_crm_api.py could stand wecare-crm up
    # once and nothing could ever redeploy it - the exact failure
    # tests/test_crm_api.py::test_the_function_is_in_the_deploy_map describes as "the
    # first provisioning deploy is also the last one". That test has been failing on
    # stack, and it was right. provision_crm_api.py:115 already documents that deploys
    # "should go through scripts/deploy_all_lambdas.py wecare-crm".
    # No standalone flag: core/crm/handler.py imports lambda_utils.logging, .response,
    # .middleware, .crm.keys and contact_key/payment_status, so it needs the default
    # packaging that bundles them.
    Spec("wecare-crm", "core/crm"),
    Spec("wecare-faq-handler", "core/faq-handler"),
    Spec("wecare-messages-delete", "core/messages-delete"),
    Spec("wecare-messages-read", "core/messages-read"),
    Spec("wecare-service-api", "core/service-api"),
    Spec("wecare-site-language", "core/site-language", standalone=True),
    Spec("wecare-vayulok-environment", "core/vayulok-environment", standalone=True,
         provisioned_by="python scripts/provision_vayulok_environment.py"),
    # --- auth / customer ---
    # First creation is owned by scripts/provision_customer_whatsapp_auth.py.
    # After that, normal code updates use this deploy map.
    Spec(
        "wecare-customer-whatsapp-auth",
        "auth/customer-whatsapp-auth",
        standalone=True,
        provisioned_by="python scripts/provision_customer_whatsapp_auth.py",
    ),
    # Email verification for checkout. Wires otp_challenge + otp_throttle +
    # comms.verification_email into request/verify endpoints. First creation is owned
    # by scripts/provision_email_verification.py, which also creates the OTP pepper
    # secret name (value set separately by the owner, never on a command line) and a
    # least-privilege role. NOT standalone: it imports lambda_utils.otp_challenge,
    # otp_throttle, comms.verification_email, identity.customer, response and logging.
    Spec(
        "wecare-email-verification",
        "auth/email-verification",
        provisioned_by="python scripts/provision_email_verification.py",
    ),
    Spec(
        "wecare-customer-profile",
        "auth/customer-profile",
        provisioned_by="python scripts/provision_customer_profile.py",
    ),
    Spec(
        "wecare-blog-subscribe",
        "auth/blog-subscribe",
        provisioned_by="python scripts/provision_blog_subscribe.py",
    ),
    # Customer registration front door. The HTTP route that proves a phone by WhatsApp OTP and
    # then provisions the Cognito login administratively, so the browser never calls SignUp on a
    # pool that is AllowAdminCreateUserOnly=true. Owns the per-IP throttle that a CUSTOM_AUTH
    # trigger cannot do (a trigger event carries no client IP). First creation is owned by
    # scripts/provision_customer_registration.py; it reuses the OTP pepper secret and the
    # DownloadGrantsTable the email-verification door already uses. NOT standalone: it imports
    # lambda_utils.identity.registration/customer, otp_throttle, otp_challenge, response, logging.
    Spec(
        "wecare-customer-registration",
        "auth/customer-registration",
        provisioned_by="python scripts/provision_customer_registration.py",
    ),
    # Customer checkout for the headless WhatsApp/Razorpay flow. Resolves the authoritative Wix
    # eCom total (integer paise), gates on a live payment-readiness readback, reserves a
    # PaymentAttempt, and hands off to the in-chat order_details path — creating NO order and NO
    # charge (an order exists only after the razorpay-webhook reconciliation verifies a capture).
    # Payment initiation is on by source and remains fail-closed behind live readiness. First
    # creation is owned by scripts/provision_checkout.py. NOT
    # standalone: it imports lambda_utils.customer_auth, payment_readiness, ecommerce.order_keys,
    # ecommerce.payment_attempt, wix_ecom, response and logging.
    Spec(
        "wecare-checkout",
        "ecommerce/checkout",
        provisioned_by="python scripts/provision_checkout.py",
    ),
    # The customer's own order history and profile summary, read-only. One Query on the sparse
    # customerId-createdAt-index, scoped by the Cognito sub from the token rather than by any
    # value in the request. First creation is owned by scripts/provision_customer_orders.py,
    # which also creates that index and the dedicated least-privilege role: the role holds
    # dynamodb:Query on the INDEX ARN only, so a GetItem for purchasedSnapshot is an
    # AccessDeniedException rather than a review finding. NOT standalone: it imports
    # lambda_utils.customer_auth, customer_session, dynamo_reads, payment_status, rate_limit,
    # ecommerce.contact_address, identity.customer, response and logging.
    Spec(
        "wecare-customer-orders",
        "ecommerce/customer-orders",
        provisioned_by="python scripts/provision_customer_orders.py",
    ),
    # Phase O-1 service requests (Submit Request / Request Amendment): the pre-payment intent,
    # the customer's own request list, and activation from the razorpay-webhook hint. It moves
    # no money - it imports no Razorpay, Wix or cart module and reads no secret. First creation
    # is owned by scripts/provision_service_requests.py, which also creates its table, two GSIs
    # and the dedicated least-privilege role. NOT standalone: it imports lambda_utils
    # customer_auth, customer_session, rate_limit, ecommerce.service_request_store/
    # service_requests/order_keys, response and logging.
    Spec(
        "wecare-service-requests",
        "ecommerce/service-requests",
        provisioned_by="python scripts/provision_service_requests.py",
    ),
    # A customer's own invoice, as a 300-second presigned download. A SEPARATE function from
    # wecare-customer-orders deliberately: this route needs dynamodb:GetItem, s3:GetObject
    # and a second dynamodb:Query, and all three are specifically refused by that function's
    # pinned policy and by six EQUALITY assertions in tests/test_customer_orders_iam.py.
    # Putting the route there would mean editing those tests so they assert less, on the one
    # function whose documented security property is its emptiness. Its own least-privilege
    # role holds four reads plus the rate-limit counter increment, and no write verb of any
    # kind - it cannot generate an invoice, which matters because generation advances the GST
    # sequence. First creation is owned by scripts/provision_customer_invoice.py, which
    # creates no table and no index: every resource it reads is owned elsewhere. NOT
    # standalone: it imports lambda_utils.customer_auth, customer_session, rate_limit,
    # receipt_links, ecommerce.customer_receipt, response and logging.
    Spec(
        "wecare-customer-invoice",
        "ecommerce/customer-invoice",
        provisioned_by="python scripts/provision_customer_invoice.py",
    ),
    # Coupon issuance and eligibility. Owns stack-wecare-digital-CouponsTable; creates NO
    # discount amount of its own -- the arithmetic is Wix's Calculate Cart. NOT standalone: it
    # imports lambda_utils.customer_auth, response, logging, ecommerce.coupon_store and
    # ecommerce.wix_coupons.
    Spec(
        "wecare-coupons",
        "ecommerce/coupons",
        provisioned_by="python scripts/provision_coupons_table.py && "
                       "python scripts/provision_coupons_role.py && "
                       "python scripts/provision_coupons_function.py && "
                       "python scripts/provision_coupons_routes.py",
    ),
    # Gift-card issuance, balance and holds. Owns stack-wecare-digital-GiftCardsTable, which is
    # a LIABILITY ledger: the balance of record lives here, never in Wix. NOT standalone.
    Spec(
        "wecare-gift-cards",
        "ecommerce/gift-cards",
        provisioned_by="python scripts/provision_gift_cards_table.py && "
                       "python scripts/provision_gift_cards_roles.py && "
                       "python scripts/provision_gift_card_routes.py",
    ),
    # The Wix Gift Cards Service Plugin endpoint. Wix CALLS this one, with a signed JWT as the
    # request body and no API Gateway authorizer, so JWT verification is the only control --
    # see .agents/tasks/wix-coupons-giftcards-20261001/gift-cards-service-plugin-20261001.md
    # section 5. Needs the cryptography layer attached; provision_gift_cards_roles.py does it.
    Spec(
        "wecare-wix-giftcard-spi",
        "ecommerce/wix-giftcard-spi",
        provisioned_by="python scripts/provision_gift_cards_roles.py && "
                       "python scripts/provision_gift_card_routes.py",
    ),
    # The Wix CATALOGUE webhook receiver. Wix calls this one too, with the same kind of signed
    # JWT as the request body and no API Gateway authorizer, so signature verification in
    # lambda_utils/ecommerce/wix_webhook.py is the only control -- see
    # .agents/tasks/wix-catalog-auto-sync-b2.md step 3 and docs/wix-catalogue-auto-sync.md.
    # It fires a GitHub repository_dispatch and does nothing else: no table, no Wix read.
    # Needs the cryptography layer attached; provision_wix_catalog_webhook.py does it, along
    # with the role, the route and the integration.
    #
    # THE SCHEDULED JOB IS THE BACKSTOP, so this function being absent or failing closed does
    # not break catalogue auto-sync. .github/workflows/catalogue-sync.yml re-reads Wix on a
    # six-hourly cron with no credential at all; this receiver only makes it near-instant.
    Spec(
        "wecare-wix-catalog-webhook",
        "ecommerce/wix-catalog-webhook",
        provisioned_by="python scripts/provision_wix_catalog_webhook.py --apply",
    ),
    # The Wix -> Meta catalogue projection (PHASE W, FEAT-001). Invoked asynchronously by the
    # webhook above after its verification, with a six-hourly EventBridge schedule as the
    # backstop. No HTTP API route and no function URL: it has no public surface at all.
    #
    # IT WRITES TO A CUSTOMER-VISIBLE META COMMERCE CATALOG - an item created there appears in
    # WhatsApp - AND IT SHIPS WITH BOTH GATES CLOSED. `META_CATALOG_SYNC_ENABLED` is "false" and
    # `META_CATALOG_SYNC_DRY_RUN` is "true" - both written out explicitly, so an audit can tell
    # "deliberately closed" from "never configured" - and a deploy of this function computes and
    # logs the diff and sends nothing. Opening either is an owner decision, recorded in
    # config/lambda-env-manifest.json at the safe defaults and asserted by
    # tests/test_meta_catalog_sync_handler.py.
    #
    # Its own least-privilege role: two statements, one GetSecretValue naming two secrets and
    # CloudWatch Logs. wecare-digital-lambda-role is NOT involved, and
    # tests/test_meta_catalog_sync_iam.py pins both halves by equality.
    Spec(
        "wecare-meta-catalog-sync",
        "ecommerce/meta-catalog-sync",
        provisioned_by="python scripts/provision_meta_catalog_sync.py --apply",
    ),
    # Cognito CustomMessage trigger: branded HTML for MFA, verification and
    # recovery email. First creation is owned by
    # scripts/provision_cognito_custom_message.py, which also gives it a
    # least-privilege role of its own rather than the shared secrets-reading one.
    # Standalone: the handler imports nothing from lambda_utils on purpose, so
    # the package is one file and a formatting change cannot drag in a layer.
    Spec(
        "wecare-cognito-custom-message",
        "auth/cognito-custom-message",
        standalone=True,
    ),
    # Both url-shortener functions build from the same source. The HTTP API's
    # /l/* routes integrate `stack-wecare-url-shortener:live`, NOT
    # `wecare-url-shortener`, so the `stack-`prefixed one is the live shortlink
    # service and the other is a leftover. Keep both on the same code.
    #
    # No longer standalone as of 2026-09-21. The /links management routes were
    # anonymously reachable - anyone could enumerate every short link or repoint
    # one at their own destination on a wecare.digital host - so the handler now
    # calls lambda_utils.middleware.require_auth and needs lambda_utils in the
    # package. The import validator caught this correctly on the first attempt and
    # refused to upload code whose import could not resolve.
    #
    # The redirect path stays cheap: the handler imports require_auth lazily
    # inside the management branch, so a customer following a short link never
    # pays for loading the middleware or its Cognito client.
    Spec("wecare-url-shortener", "core/url-shortener"),
    Spec("stack-wecare-url-shortener", "core/url-shortener"),
    # --- messaging / whatsapp ---
    Spec("wecare-inbound-whatsapp", "messaging/inbound-whatsapp-handler"),
    Spec("wecare-outbound-whatsapp", "messaging/outbound-whatsapp"),
    Spec("wecare-whatsapp-voice", "messaging/whatsapp-voice"),
    Spec("wecare-whatsapp-calling", "messaging/whatsapp-calling"),
    Spec("wecare-whatsapp-templates", "messaging/whatsapp-templates"),
    Spec("wecare-whatsapp-template-management", "messaging/whatsapp-template-management"),
    Spec(
        "wecare-whatsapp-business-api",
        "messaging/whatsapp-business-api",
        extra_dirs=["flows"],
        extra_files=["service_api.py"],
    ),
    Spec("wecare-waba-management", "messaging/waba-management"),
    Spec("wecare-media-cleanup", "messaging/media-cleanup"),
    Spec("wecare-template-analytics", "messaging/template-analytics"),
    Spec("wecare-partner-onboarding", "messaging/partner-onboarding"),
    Spec("wecare-partner-token-refresh", "messaging/partner-token-refresh"),
    # --- messaging / sms + email ---
    Spec("wecare-outbound-sms", "messaging/outbound-sms"),
    Spec("wecare-outbound-email", "messaging/outbound-email"),
    Spec("wecare-sms-aws", "messaging/sms-aws"),
    # Removed 2026-09-19: the retired India A2P sender and the retired
    # aggregator's DLR receiver. Their source is deleted, so they are no longer
    # built or deployed. The DEPLOYED functions and their secrets still exist in
    # the account and are removed under separate destructive approval - see
    # docs/provider-retirement-inventory.md.
    # --- messaging / voice ---
    Spec("wecare-voice-aws", "messaging/voice-aws"),
    Spec("wecare-voice-in-c2c", "messaging/voice-in/c2c"),
    Spec("wecare-voice-in-obd", "messaging/voice-in/obd"),
    Spec("wecare-voice-cdr-read", "messaging/voice-cdr-read"),
    # Removed 2026-09-19: wecare-outbound-voice. It was a pure dialler for a
    # retired India voice provider (click-to-call + outbound dialler) with no
    # compliant surface to keep. PSTN voice is Plivo; outbound calling arrives
    # with the Plivo browser softphone behind PSTN_BROWSER_ROUTING_ENABLED.
    # The DEPLOYED function and its secret still exist and are removed under
    # separate destructive approval.
    Spec("wecare-notification-worker", "messaging/notification-worker"),
    Spec("wecare-plivo-answer", "messaging/plivo-answer"),
    # Absent until now, and it serves five live production routes through its
    # `live` alias: GET /pstn/session, POST /pstn/session/events, POST
    # /pstn/session/presence, GET /pstn/diagnostics and POST /pstn/token.
    # scripts/provision_pstn_softphone.py only calls create_function,
    # publish_version and create_alias - there is no update path in it - so
    # without this entry the first provisioning deploy was also the last one,
    # and a fix to the browser-token service could not reach production by any
    # supported route. The same failure was found and fixed for wecare-crm.
    # Not standalone: the handler imports lambda_utils.logging, .response,
    # .middleware and .pstn (browser_token, softphone), so it needs the default
    # packaging that bundles them. No extra_files - there are no lazy imports.
    #
    # provisioned_by is deliberately NOT set, for the same reason it is not set on
    # wecare-secure-files: the function already exists in the account, so marking
    # it would report a future deletion as "awaiting provisioning" instead of as
    # the failure it would be.
    Spec("wecare-pstn-softphone", "messaging/pstn-softphone"),
    # --- messaging / rcs, push, scheduling ---
    Spec("wecare-rcs-send", "messaging/rcs-send"),
    Spec("wecare-rcs-dlr", "messaging/rcs-dlr"),
    Spec("wecare-push-notifications", "messaging/push-notifications"),
    Spec("wecare-scheduled-messages", "messaging/scheduled-messages"),
    # --- messaging / ads + analytics ---
    Spec("wecare-meta-analytics", "messaging/meta-analytics"),
    Spec("wecare-ad-attribution", "messaging/ad-attribution"),
    Spec("wecare-marketing-ads", "messaging/marketing-ads"),
    Spec("wecare-meta-business-agent", "messaging/meta-business-agent"),
    # --- ai ---
    Spec("wecare-ai-query-kb", "ai/ai-query-kb"),
    Spec("wecare-ai-generate-response", "ai/ai-generate-response"),
    Spec("wecare-ai-config-management", "ai/ai-config-management"),
    Spec("wecare-agent-action-group", "ai/agent-action-group"),
    # --- operations ---
    Spec("wecare-billing", "operations/billing"),
    Spec("wecare-bulk-job-create", "operations/bulk-job-create"),
    Spec("wecare-bulk-job-control", "operations/bulk-job-control"),
    Spec("wecare-bulk-worker", "operations/bulk-worker"),
    Spec("wecare-dlq-replay", "operations/dlq-replay"),
    Spec("wecare-sla-engine", "operations/sla-engine"),
    Spec("wecare-system-cleanup", "operations/system-cleanup"),
    # --- payments ---
    Spec("wecare-razorpay-webhook", "payments/razorpay-webhook"),
    Spec("wecare-payments-read", "payments/payments-read"),
    Spec("wecare-invoice-engine", "payments/invoice-engine", extra_dirs=("fonts",),
         extra_files=("receipt_layout.py",)),
    # --- ecommerce ---
    Spec("wecare-wix-store", "ecommerce/wix-store"),
    Spec("wecare-product-image-gen", "ecommerce/product-image-gen"),
    Spec("wecare-catalog-management", "ecommerce/catalog-management"),
]

# wecare-seo-tools uses a different in-zip layout (a shim at the root importing
# operations/seo-tools, with lambda_utils under shared/). scripts/deploy_seo_tools.py
# owns it, along with its table and IAM policy, so it is delegated rather than
# reimplemented here.
#
# wecare-mcp ships `config/public-pages.json` beside its handler, and `extra_files`
# cannot express that: it resolves relative to the function directory, and it is skipped
# entirely for a standalone spec. The alternatives were a second checked-in copy of the
# catalogue (the drift src/test/PublicAiSurface.test.ts exists to prevent) or a symlink
# (breaks on a Windows checkout). Its script also owns the Amplify Hosting rewrite that
# makes /mcp reachable on the apex at all, which has no equivalent here.
# CAUTION ON wecare-seo-tools: THE SCRIPT IS NOT THE ONLY OWNER.
# `.github/workflows/seo-tools-deploy.yml` also deploys it, on every push to `stack`
# touching `amplify/functions/operations/seo-tools/**`, `seo_tools_handler.py`,
# `amplify/functions/shared/lambda_utils/**`, `static_knowledge_base.py`,
# `tests/test_task12_seo.py` or `scripts/deploy_seo_tools.py`.
#
# That `lambda_utils/**` trigger is the wide one, and it means ANY commit touching shared
# code redeploys seo-tools from the COMMITTED tree. Proved on 2026-09-28: a local
# `deploy_seo_tools.py` run at 15:35 was verified working live, then overwritten at 15:40
# and again at 15:44 by the workflow, because another session pushed commits while the
# local changes were still uncommitted. CloudTrail shows all three UpdateFunctionCode calls
# - one from `user/wecare-admin` via Boto3, two from the `bharat-stack-seo-tools` CI role.
#
# So for this function CI is the authority and a local deploy from a dirty tree is
# TRANSIENT. Commit first, then push, and let the workflow deploy. Running the script
# locally is still correct for a fast iteration loop - just do not treat the result as
# durable until it is committed.
DELEGATED = {
    "wecare-seo-tools": "scripts/deploy_seo_tools.py  (also .github/workflows/seo-tools-deploy.yml on push)",
    "wecare-mcp": "scripts/deploy_mcp_server.py",
    # Bundles its own pinned SDK and policy; generic packaging would omit both.
    "wecare-workspace-mcp": "scripts/build_workspace_mcp.py + scripts/deploy_workspace_mcp.py (CloudFormation, after merge)",
}
SKIPPED = {"wecare-docs-scraper": "PackageType=Image, deploys via GitHub Actions"}


# --------------------------------------------------------------------------- #
# packaging
# --------------------------------------------------------------------------- #

def _iter_dir(root: Path) -> Iterable[Path]:
    """Every shippable file under root, excluding junk directories."""
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in EXCLUDE_DIRS for part in path.relative_to(root).parts):
            continue
        if path.suffix in {".pyc", ".pyo"}:
            continue
        yield path


def build_zip(spec: Spec) -> Tuple[bytes, Dict[str, bytes]]:
    """Return (zip bytes, {arcname: content}). Deterministic."""
    members: Dict[str, bytes] = {}

    if not spec.handler_file.exists():
        raise FileNotFoundError(f"missing handler: {spec.handler_file}")
    members["handler.py"] = spec.handler_file.read_bytes()

    if not spec.standalone:
        if not LAMBDA_UTILS.is_dir():
            raise FileNotFoundError(f"missing {LAMBDA_UTILS}")
        for path in _iter_dir(LAMBDA_UTILS):
            if path.suffix == ".py":
                members[f"lambda_utils/{path.relative_to(LAMBDA_UTILS).as_posix()}"] = path.read_bytes()
        if len(members) - 1 < 3:
            raise RuntimeError(f"lambda_utils looks incomplete ({len(members) - 1} files)")
        if STATIC_KB.exists():
            members["static_knowledge_base.py"] = STATIC_KB.read_bytes()

        modules = spec.source / "modules"
        if modules.is_dir():
            for path in _iter_dir(modules):
                members[f"modules/{path.relative_to(modules).as_posix()}"] = path.read_bytes()

        for rel in spec.extra_dirs:
            extra = spec.source / rel
            if not extra.is_dir():
                raise FileNotFoundError(f"missing extra dir: {extra}")
            for path in _iter_dir(extra):
                members[f"{rel}/{path.relative_to(extra).as_posix()}"] = path.read_bytes()

        for rel in spec.extra_files:
            extra = spec.source / rel
            if not extra.is_file():
                raise FileNotFoundError(f"missing extra file: {extra}")
            members[rel] = extra.read_bytes()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for arcname in sorted(members):
            info = zipfile.ZipInfo(arcname, date_time=ZIP_DATE)
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, members[arcname])
    return buf.getvalue(), members


_LAYER_CACHE: Dict[str, frozenset] = {}


def layer_modules(lam, arn: str) -> frozenset:
    """Top-level module names a layer version contributes to sys.path.

    Resolved by reading the layer zip rather than assuming, because several of
    these functions rely entirely on layers for PIL / cryptography and a purely
    package-local import check would flag them as broken.
    """
    if arn in _LAYER_CACHE:
        return _LAYER_CACHE[arn]

    import urllib.request

    names: set = set()
    try:
        location = lam.get_layer_version_by_arn(Arn=arn)["Content"]["Location"]
        with urllib.request.urlopen(location, timeout=120) as response:
            blob = response.read()
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            for entry in archive.namelist():
                # Layer zips built on Windows carry `\` separators.
                path = entry.replace("\\", "/")
                for prefix in ("python/lib/python3.12/site-packages/", "python/"):
                    if path.startswith(prefix):
                        rest = path[len(prefix):]
                        break
                else:
                    continue
                top = rest.split("/")[0]
                if not top or top.endswith((".dist-info", ".egg-info")):
                    continue
                names.add(top.removesuffix(".py").removesuffix(".so").split(".")[0])
    except Exception as exc:  # noqa: BLE001
        print(f"    warning: could not read layer {arn.split(':')[-2]}: {exc}")

    _LAYER_CACHE[arn] = frozenset(names)
    return _LAYER_CACHE[arn]


def _guarded_import_lines(tree: ast.AST) -> set:
    """Line numbers of imports wrapped in try/except, i.e. optional ones."""
    guarded: set = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for child in ast.walk(node):
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                guarded.add(child.lineno)
    return guarded


def validate_handler(members: Dict[str, bytes], handler_string: str) -> List[str]:
    """Check the function's configured Handler resolves inside the package.

    The import check below cannot catch this: a package can have every import
    satisfied and still be unbootable because AWS is configured to call a
    symbol that does not exist. Two functions in this fleet define
    ``lambda_handler`` rather than ``handler`` (messaging/marketing-ads,
    messaging/meta-business-agent) and neither has a ``resource.ts``, so the
    only record of their entry point is the live configuration. Renaming a
    handler function would deploy cleanly and then fail on the first
    invocation with ``Runtime.HandlerNotFound``.

    Returns a list of errors (empty when the handler resolves).
    """
    module_path, _, symbol = handler_string.rpartition(".")
    if not module_path or not symbol:
        return [f"unparseable Handler {handler_string!r}"]

    arcname = module_path.replace(".", "/") + ".py"
    if arcname not in members:
        return [f"Handler {handler_string!r} needs {arcname}, which is not in the package"]

    try:
        tree = ast.parse(members[arcname].decode("utf-8"), filename=arcname)
    except SyntaxError as exc:
        return [f"{arcname}: syntax error: {exc}"]

    defined = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    } | {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    if symbol not in defined:
        return [f"Handler {handler_string!r}: {arcname} defines no top-level {symbol!r}"]
    return []


def validate(
    spec: Spec, members: Dict[str, bytes], provided: frozenset
) -> Tuple[List[str], List[str]]:
    """Static import check. Returns (errors, warnings).

    Catches the failure this fleet is prone to: a handler importing a shared
    module the packaging step forgot to include. Being static, it cannot report
    a false failure over missing env vars the way actually importing would.

    An unresolved import inside try/except is a warning, not an error, because
    the code has a documented fallback path for it.
    """
    errors: List[str] = []
    warnings: List[str] = []

    available = {name.split("/")[0].removesuffix(".py") for name in members}
    known = available | provided | RUNTIME_PROVIDED | set(sys.stdlib_module_names)

    for arcname in sorted(members):
        if not arcname.endswith(".py"):
            continue
        try:
            tree = ast.parse(members[arcname].decode("utf-8"), filename=arcname)
        except SyntaxError as exc:
            errors.append(f"{arcname}: syntax error: {exc}")
            continue

        guarded = _guarded_import_lines(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = [(a.name.split(".")[0], node.lineno) for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:  # relative import, resolves within the package
                    continue
                roots = [((node.module or "").split(".")[0], node.lineno)]
            else:
                continue
            for root, lineno in roots:
                if not root or root in known:
                    continue
                message = f"{arcname}:{lineno} imports '{root}', not in package or layers"
                if lineno in guarded:
                    warnings.append(message + " (guarded by try/except)")
                else:
                    errors.append(message)

    return sorted(set(errors)), sorted(set(warnings))


# --------------------------------------------------------------------------- #
# deploy
# --------------------------------------------------------------------------- #

#: Errors that mean "try again", not "this deploy is broken".
#: ResourceConflictException is raised when an update is already in flight on the
#: function - which happens routinely across a 58-function fleet deploy. On
#: 2026-09-20 wecare-product-image-gen was reported failed for exactly this
#: reason and succeeded unchanged on an immediate manual retry, so the run
#: reported a false failure and a human had to go and disprove it.
_RETRYABLE = (
    "ResourceConflictException",
    "TooManyRequestsException",
    "ThrottlingException",
    "ServiceException",
    "RequestTimeout",
)


def _update_with_retry(lam, spec: Spec, zip_bytes: bytes, attempts: int = 5):
    """update_function_code with exponential backoff on transient errors.

    Returns the API result, or raises the last ClientError. A retry is only
    attempted for the codes in _RETRYABLE; a genuine error (bad zip, missing
    function, denied) still fails immediately, because retrying it would just
    slow the run down and bury the message.
    """
    delay = 2.0
    last: ClientError | None = None
    for attempt in range(1, attempts + 1):
        try:
            return lam.update_function_code(
                FunctionName=spec.name, ZipFile=zip_bytes, Publish=False
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code not in _RETRYABLE or attempt == attempts:
                raise
            last = exc
            print(f"    {code}, retrying in {delay:.0f}s "
                  f"(attempt {attempt}/{attempts - 1})")
            time.sleep(delay)
            delay *= 2
    if last:
        raise last
    raise RuntimeError("unreachable")


def deploy(lam, spec: Spec, zip_bytes: bytes, current: dict) -> str:
    """'updated', 'unchanged', or 'failed'."""
    try:
        result = _update_with_retry(lam, spec, zip_bytes)
    except ClientError as exc:
        print(f"    update_function_code failed: {exc}")
        return "failed"

    try:
        lam.get_waiter("function_updated_v2").wait(FunctionName=spec.name)
    except Exception as exc:  # noqa: BLE001
        print(f"    function never settled after update: {exc}")
        return "failed"

    if result["CodeSha256"] == current.get("CodeSha256"):
        print(f"    unchanged (sha {result['CodeSha256'][:12]}...)")
        return "unchanged"
    print(f"    $LATEST -> sha {result['CodeSha256'][:12]}... "
          f"({result['CodeSize']} bytes)")
    return "updated"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("functions", nargs="*", help="function names; default is all")
    ap.add_argument("--dry-run", action="store_true",
                    help="build and validate packages, upload nothing")
    ap.add_argument("--no-publish", action="store_true",
                    help="skip snapstart_publish.py (leaves the `live` alias on old code)")
    ap.add_argument("--list", action="store_true", help="print the function map and exit")
    args = ap.parse_args()

    if args.list:
        for spec in SPECS:
            flags = []
            if spec.standalone:
                flags.append("standalone")
            if spec.extra_dirs:
                flags.append(f"dirs={','.join(spec.extra_dirs)}")
            if spec.extra_files:
                flags.append(f"files={','.join(spec.extra_files)}")
            print(f"{spec.name:40s} {spec.source.relative_to(FUNCTIONS)}"
                  f"{'  [' + ' '.join(flags) + ']' if flags else ''}")
        for name, why in {**DELEGATED, **SKIPPED}.items():
            print(f"{name:40s} -> {why}")
        return 0

    selected = SPECS
    if args.functions:
        wanted = set(args.functions)
        selected = [s for s in SPECS if s.name in wanted]
        unknown = wanted - {s.name for s in selected}
        for name in sorted(unknown):
            if name in DELEGATED:
                print(f"{name}: run {DELEGATED[name]} instead")
            elif name in SKIPPED:
                print(f"{name}: skipped — {SKIPPED[name]}")
            else:
                print(f"{name}: not in the function map")
        if not selected:
            return 1

    lam = boto3.client("lambda", region_name=REGION)
    print(f"region={REGION} targets={len(selected)} dry_run={args.dry_run}")
    print()

    tally = {"updated": 0, "unchanged": 0, "failed": 0, "awaiting_provisioning": 0,
             # dry-run only: packaged bytes differ from what is live
             "would_update": 0}
    failures: List[str] = []
    deployed: List[str] = []
    awaiting: List[str] = []
    all_warnings: List[str] = []

    for spec in selected:
        print(f"  {spec.name}")
        try:
            zip_bytes, members = build_zip(spec)
        except Exception as exc:  # noqa: BLE001
            print(f"    package failed: {exc}")
            tally["failed"] += 1
            failures.append(spec.name)
            continue

        try:
            current = lam.get_function_configuration(FunctionName=spec.name)
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ResourceNotFoundException":
                if spec.provisioned_by:
                    # Expected: creation is owned elsewhere and has not happened
                    # yet. Counted separately so `failed` stays a real signal.
                    print(f"    not provisioned yet — create it with "
                          f"{spec.provisioned_by}")
                    tally["awaiting_provisioning"] += 1
                    awaiting.append(f"{spec.name} ({spec.provisioned_by})")
                    continue
                print(f"    not found in {REGION} — refusing to create it here")
            else:
                print(f"    get_function_configuration failed: {exc}")
            tally["failed"] += 1
            failures.append(spec.name)
            continue

        provided: frozenset = frozenset()
        for layer in current.get("Layers") or []:
            provided |= layer_modules(lam, layer["Arn"])

        errors, warnings = validate(spec, members, provided)
        errors += validate_handler(members, current.get("Handler", ""))
        for warning in warnings:
            print(f"    warning: {warning}")
            all_warnings.append(f"{spec.name}: {warning}")
        if errors:
            for error in errors:
                print(f"    ERROR: {error}")
            tally["failed"] += 1
            failures.append(spec.name)
            continue

        print(f"    packaged {len(members)} files, {len(zip_bytes)} bytes")

        if args.dry_run:
            # Compare, rather than assume. This branch used to do
            # `tally["unchanged"] += 1` unconditionally, so a dry run always
            # reported every target as unchanged whatever the packaged bytes
            # were - and that number was then quoted as evidence that a
            # function already matched production. It never established that.
            #
            # The comparison is sound because the zip is built deterministically
            # (fixed timestamps, see the packaging note at the top), and
            # CodeSha256 is exactly base64(sha256(zip)).
            packaged_sha = base64.b64encode(
                hashlib.sha256(zip_bytes).digest()).decode()
            if packaged_sha == current.get("CodeSha256"):
                print(f"    would not update: sha matches live "
                      f"({packaged_sha[:12]}...)")
                tally["unchanged"] += 1
            else:
                print(f"    WOULD UPDATE: {current.get('CodeSha256', '?')[:12]}..."
                      f" -> {packaged_sha[:12]}...")
                tally["would_update"] += 1
            continue

        outcome = deploy(lam, spec, zip_bytes, current)
        tally[outcome] += 1
        if outcome == "failed":
            failures.append(spec.name)
        else:
            deployed.append(spec.name)

    print()
    summary = (f"updated={tally['updated']} unchanged={tally['unchanged']} "
               f"failed={tally['failed']} "
               f"awaiting_provisioning={tally['awaiting_provisioning']}")
    if args.dry_run:
        # Named separately so a dry run cannot be read as a deployment result.
        summary += f" would_update={tally['would_update']}"
    print(summary)
    if failures:
        print(f"failed: {', '.join(failures)}")
    if awaiting:
        print(f"awaiting provisioning ({len(awaiting)}), not a failure:")
        for entry in awaiting:
            print(f"  {entry}")
    if all_warnings:
        print(f"\n{len(all_warnings)} import warning(s):")
        for warning in all_warnings:
            print(f"  {warning}")

    if args.dry_run:
        print("\ndry run: nothing uploaded")
        return 1 if failures else 0

    publish_rc = 0
    if args.no_publish:
        print("\n--no-publish: `live` aliases still point at the previous code.")
        print("Run `python scripts/snapstart_publish.py` to actually ship.")
    elif deployed:
        print("\nPublishing versions + moving the `live` alias "
              "(the API invokes :live, not $LATEST)...\n")
        publish_rc = subprocess.call(
            [sys.executable, str(ROOT / "scripts" / "snapstart_publish.py"),
             "--only-stale", *deployed]
        )

    return 1 if (failures or publish_rc) else 0


if __name__ == "__main__":
    sys.exit(main())
