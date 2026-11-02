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
``.kiro/steering/lambda-snapstart-deploy.md`` (retired 2026-10-09, af7858fa).

Shared checkout, concurrent deployers
-------------------------------------
Many sessions share this checkout, and other deployers (CodeBuild, MCP clients) write the
same functions. Packaging reads whatever is on disk, and nothing serialises deploys, so:

* A real deploy refuses when a file it would package differs from HEAD (modified, staged or
  untracked): it would ship another session's unfinished edit. Commit first, or deploy a
  pinned commit from an export (``git archive <ref> amplify/functions scripts | tar -x -C
  <dir>``, then run ``<dir>/scripts/deploy_all_lambdas.py``). A dry run only warns.
* The upload carries the ``RevisionId`` this run read, and the publish step gets
  ``--expect <function>=<CodeSha256>``, so a function another deploy touched in between fails
  instead of being overwritten or published with the other run's code.

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
# v3 (2026-10-27): Pillow 13.0.0 from manylinux wheels, zipped with `/` separators. v2 carried
# Pillow 12.1.1 (59 OSV advisories, 5 critical) in a Windows-built zip. product-image-gen also
# uses this layer now instead of the third-party Klayers one.
PILLOW_LAYER_ARN = "arn:aws:lambda:us-east-1:775261844268:layer:pillow-python312:3"

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
        external_dirs: Sequence[Tuple[str, str]] = (),
        external_files: Sequence[Tuple[str, str]] = (),
        required_layers: Sequence[str] = (),
        required_memory: Optional[int] = None,
        required_timeout: Optional[int] = None,
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
        # (source path relative to amplify/functions, destination path in the zip).
        # Used only when two runtimes temporarily share an exact implementation/asset
        # during a strangler migration; avoids source copies that can drift.
        self.external_dirs = list(external_dirs)
        self.external_files = list(external_files)
        self.required_layers = list(required_layers)
        self.required_memory = required_memory
        self.required_timeout = required_timeout

    @property
    def handler_file(self) -> Path:
        return self.source / "handler.py"


# Every zip-packaged function in us-east-1, mapped to its source.
#
# Deliberately excluded:
#   wecare-docs-scraper — PackageType=Image; deploy separately with its container deployment path.
SPECS: List[Spec] = [
    # Function shell/table/role remain owned by CloudFormation
    # amplify/infra/customer-sessions.json. Code publishing and the live alias are
    # operational deployment concerns owned by deploy_all_lambdas.py + snapstart_publish.py.
    Spec("wecare-customer-session", "ecommerce/customer-session"),
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
        # razorpay_orders     only when settling a historical paid-download order
        # whatsapp_delivery   only when delivering a file or a download link
        extra_files=["razorpay_orders.py", "whatsapp_delivery.py"],
        # provisioned_by is deliberately NOT set. The function exists and deploys
        # normally, so marking it would turn a genuine future failure - the function
        # having been deleted - into "awaiting provisioning", which reads as expected. A deleted live function must remain a deployment failure, not be reported as expected provisioning drift. Its provisioning script is recorded in
        # docs/SECURE-FILE-SHARING.md instead.
    ),
    # Absent until now, which meant provision_crm_api.py could stand wecare-crm up
    # once and nothing could ever redeploy it - the exact failure Without this entry the first provisioning deploy would also be the last one. provision_crm_api.py:115 already documents that deploys
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
    # Now LIVE and recorded in the env manifest, so the awaiting-provisioning marker
    # was dropped. First creation was owned by
    # scripts/provision_customer_whatsapp_auth.py.
    Spec(
        "wecare-customer-whatsapp-auth",
        "auth/customer-whatsapp-auth",
        standalone=True,
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
    # Customer checkout for the headless WhatsApp/Razorpay flow. Resolves the authoritative
    # ProductsTable total (integer paise), gates on a live payment-readiness readback, reserves a
    # PaymentAttempt, and hands off to the in-chat order_details path — creating NO order and NO
    # charge (an order exists only after the razorpay-webhook reconciliation verifies a capture).
    # Payment initiation is on by source and remains fail-closed behind live readiness. First
    # creation is owned by scripts/provision_checkout.py. NOT
    # standalone: it imports lambda_utils.customer_auth, payment_readiness, ecommerce.order_keys,
    # ecommerce.payment_attempt, the ecommerce.native_* pricing modules, response and logging.
    Spec(
        "wecare-checkout",
        "ecommerce/checkout",
        # The invoice engine ships as `invoice_engine.py` from its ONE source,
        # payments/invoice-engine/handler.py, rather than from a byte-identical copy under
        # ecommerce/checkout/. receipt_layout.py and the fonts already ship the same external way,
        # so there is one engine to maintain and nothing to drift.
        external_files=[
            ("payments/invoice-engine/handler.py", "invoice_engine.py"),
            ("payments/invoice-engine/receipt_layout.py", "receipt_layout.py"),
        ],
        external_dirs=[("payments/invoice-engine/fonts", "fonts")],
        required_layers=[PILLOW_LAYER_ARN],
        required_memory=512,
        required_timeout=60,
        # Now LIVE and recorded in the env manifest, so the awaiting-provisioning
        # marker was dropped. First creation was owned by scripts/provision_checkout.py.
    ),
    # Strangler target for the checkout + invoice runtime. It intentionally packages the SAME
    # proven source closure as wecare-checkout while caller/API cutover remains separate.
    # Razorpay settlement verification stays in wecare-razorpay-webhook as an independent
    # provider-evidence boundary. First creation has NO API routes and is owned by
    # scripts/provision_commerce.py; production callers move only after shadow verification.
    Spec(
        "wecare-commerce",
        "ecommerce/checkout",
        # Byte-for-byte the wecare-checkout package: the engine ships from its one source.
        external_files=[
            ("payments/invoice-engine/handler.py", "invoice_engine.py"),
            ("payments/invoice-engine/receipt_layout.py", "receipt_layout.py"),
        ],
        external_dirs=[("payments/invoice-engine/fonts", "fonts")],
        required_layers=[PILLOW_LAYER_ARN],
        required_memory=512,
        required_timeout=60,
        provisioned_by="python scripts/provision_commerce.py",
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
    # no money - it imports no Razorpay or cart module and reads no secret. First creation
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
    # wecare-customer-orders deliberately: this route needs dynamodb:GetItem, s3:GetObject and a second dynamodb:Query; the customer-orders function's pinned policy deliberately refuses those permissions. Its own least-privilege
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
    # The AWS-native catalogue -> Meta projection (formerly PHASE W). Invoked by the ProductsTable
    # change stream through an event-source mapping on its `live` alias, with a six-hourly
    # EventBridge schedule as the backstop. No HTTP API route and no function URL: it has no
    # public surface at all.
    #
    # IT WRITES TO A CUSTOMER-VISIBLE META COMMERCE CATALOG - an item created there appears in
    # WhatsApp. Product-level metaEnabled owns desired publication scope. Production intentionally
    # keeps `META_CATALOG_SYNC_ENABLED=true` with `META_CATALOG_SYNC_DRY_RUN=true`: inspect and
    # exact-plan approval remain available while normal runs cannot write. The dedicated deploy
    # workflow refuses to leave dry-run and also removes the retired forced-out-of-stock control.
    #
    # Its own least-privilege role: two statements, one GetSecretValue naming two secrets and
    # CloudWatch Logs. wecare-digital-lambda-role is NOT involved.
    # Now LIVE and recorded in the env manifest, so the awaiting-provisioning marker
    # was dropped. First creation was owned by
    # scripts/provision_meta_catalog_sync.py --apply.
    Spec(
        "wecare-meta-catalog-sync",
        "ecommerce/meta-catalog-sync",
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
    # The HTTP API short-link routes integrate the single live function
    # `stack-wecare-url-shortener:live`.
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
    Spec("stack-wecare-url-shortener", "core/url-shortener"),
    # --- messaging / whatsapp ---
    Spec("wecare-inbound-whatsapp", "messaging/inbound-whatsapp-handler"),
    Spec("wecare-outbound-whatsapp", "messaging/outbound-whatsapp"),
    Spec("wecare-whatsapp-voice", "messaging/whatsapp-voice"),
    Spec("wecare-whatsapp-calling", "messaging/whatsapp-calling"),
    Spec("wecare-whatsapp-template-management", "messaging/whatsapp-template-management"),
    Spec(
        "wecare-whatsapp-business-api",
        "messaging/whatsapp-business-api",
        extra_dirs=["flows"],
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
    Spec("wecare-marketing-ads", "messaging/marketing-ads"),
    Spec("wecare-meta-business-agent", "messaging/meta-business-agent"),
    # --- ai ---
    Spec("wecare-ai-query-kb", "ai/ai-query-kb"),
    Spec("wecare-ai-config-management", "ai/ai-config-management"),
    Spec("wecare-agent-action-group", "ai/agent-action-group"),
    # --- operations ---
    Spec("wecare-billing", "operations/billing"),
    Spec("wecare-bulk-job-create", "operations/bulk-job-create"),
    Spec("wecare-bulk-job-control", "operations/bulk-job-control"),
    Spec("wecare-bulk-worker", "operations/bulk-worker"),
    Spec("wecare-dlq-replay", "operations/dlq-replay"),
    Spec("wecare-system-cleanup", "operations/system-cleanup"),
    # --- payments ---
    Spec("wecare-razorpay-webhook", "payments/razorpay-webhook"),
    Spec("wecare-payments-read", "payments/payments-read"),
    Spec("wecare-invoice-engine", "payments/invoice-engine", extra_dirs=("fonts",),
         extra_files=("receipt_layout.py",), required_layers=[PILLOW_LAYER_ARN]),
    # --- ecommerce ---
    Spec("wecare-product-image-gen", "ecommerce/product-image-gen", required_layers=[PILLOW_LAYER_ARN]),
    Spec("wecare-catalog-management", "ecommerce/catalog-management"),
]

# wecare-seo-tools uses a different in-zip layout (a shim at the root importing
# operations/seo-tools, with lambda_utils under shared/). scripts/deploy_seo_tools.py
# owns it, along with its table and IAM policy, so it is delegated rather than
# reimplemented here.
#
# wecare-mcp ships config/public-pages.json beside its handler, so its dedicated
# scripts/deploy_mcp_server.py owns that package and the Amplify Hosting rewrite.
# wecare-seo-tools likewise remains owned by scripts/deploy_seo_tools.py. These
# delegated deployment paths are explicit; no GitHub workflow is an owner.
DELEGATED = {
    "wecare-blog-public": "scripts/build_blog_public.py (dedicated three-file read-only package; code-only deployment with revision/hash preconditions)",
    "wecare-seo-tools": "scripts/deploy_seo_tools.py",
    "wecare-mcp": "scripts/deploy_mcp_server.py",
    # Bundles its own pinned SDK and policy; generic packaging would omit both.
    "wecare-workspace-mcp": "scripts/build_workspace_mcp.py + scripts/deploy_workspace_mcp.py (CloudFormation, after merge)",
    # Inline in its own template; see amplify/functions/ai/customer-commerce-mcp/README.md.
    "wecare-customer-commerce-mcp": "CloudFormation stack wecare-customer-commerce-mcp (amplify/functions/ai/customer-commerce-mcp/template.json)",
}
SKIPPED = {"wecare-docs-scraper": "PackageType=Image; deploy separately from the zip Lambda fleet"}


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

        for source_rel, dest_rel in spec.external_dirs:
            extra = FUNCTIONS / source_rel
            if not extra.is_dir():
                raise FileNotFoundError(f"missing external dir: {extra}")
            for path in _iter_dir(extra):
                members[f"{dest_rel}/{path.relative_to(extra).as_posix()}"] = path.read_bytes()

        for source_rel, dest_rel in spec.external_files:
            extra = FUNCTIONS / source_rel
            if not extra.is_file():
                raise FileNotFoundError(f"missing external file: {extra}")
            members[dest_rel] = extra.read_bytes()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for arcname in sorted(members):
            info = zipfile.ZipInfo(arcname, date_time=ZIP_DATE)
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, members[arcname])
    return buf.getvalue(), members


def uncommitted_sources() -> Optional[List[str]]:
    """Repository paths under amplify/functions that differ from HEAD (modified, staged, untracked).

    None when this copy of the script is not at the top of its own git checkout: it is running
    from an exported tree (``git archive``), which is one commit's content by construction.
    Raises RuntimeError when the checkout's status cannot be read, so a deploy can refuse.
    """
    try:
        top = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    if Path(top).resolve() != ROOT:
        return None
    # --no-optional-locks: never take the index lock the other sessions in this checkout need.
    result = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(ROOT), "status", "--porcelain=v1", "-z",
         "--untracked-files=all", "--", FUNCTIONS.relative_to(ROOT).as_posix()],
        capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", "replace").strip() or "git status failed")
    fields = result.stdout.decode("utf-8", "surrogateescape").split("\0")
    paths: List[str] = []
    index = 0
    while index < len(fields):
        entry = fields[index]
        index += 1
        if len(entry) < 4:
            continue
        paths.append(entry[3:])
        if {"R", "C"} & set(entry[:2]) and index < len(fields):
            paths.append(fields[index])  # -z prints a rename/copy as "XY new\0old"
            index += 1
    return paths


def dirty_sources_for(spec: Spec, dirty: Iterable[str]) -> List[str]:
    """The uncommitted paths build_zip would read for this spec."""
    roots = [spec.source]
    if not spec.standalone:
        roots += [LAMBDA_UTILS, STATIC_KB]
        roots += [FUNCTIONS / source for source, _ in (*spec.external_dirs, *spec.external_files)]
    hits = []
    for rel in dirty:
        parts = Path(rel).parts
        if Path(rel).suffix in {".pyc", ".pyo"} or any(part in EXCLUDE_DIRS for part in parts):
            continue
        path = ROOT / rel
        if any(path == root or root in path.parents for root in roots):
            hits.append(rel)
    return sorted(hits)


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


def _module_file(members: Dict[str, bytes], dotted: str) -> Optional[str]:
    """The package member ``import <dotted>`` executes; None if absent or a namespace package."""
    base = dotted.replace(".", "/")
    for arcname in (f"{base}.py", f"{base}/__init__.py"):
        if arcname in members:
            return arcname
    return None


def _package_directories(members: Dict[str, bytes]) -> frozenset:
    """Every directory holding a packaged .py file: the packages, namespace ones included."""
    directories: set = set()
    for name in members:
        if name.endswith(".py"):
            parts = name.split("/")[:-1]
            directories.update("/".join(parts[:depth]) for depth in range(1, len(parts) + 1))
    return frozenset(directories)


def _absolute_module(arcname: str, node: ast.ImportFrom) -> Optional[str]:
    """The module an ImportFrom in ``arcname`` names; None for a relative import past the top."""
    if not node.level:
        return node.module
    package = arcname.removesuffix(".py").split("/")[:-1]
    if node.level - 1 >= len(package):
        return None
    base = package[: len(package) - (node.level - 1)]
    return ".".join(base + (node.module.split(".") if node.module else []))


#: Module bindings by sha256 of the source. lambda_utils ships in nearly every package,
#: so a fleet run would otherwise recompute the same modules once per function.
_BINDINGS_CACHE: Dict[bytes, Tuple[frozenset, bool]] = {}


def _module_bindings(source: bytes, tree: ast.Module) -> Tuple[frozenset, bool]:
    """(names a module defines once imported, whether it can define names not visible here).

    Deliberately generous, because a false "not defined" refuses a correct deploy: any
    module-level binding in any branch counts, as do ``global`` declarations and walrus
    targets anywhere in the file. A module-level ``__getattr__``, a star import or a call
    to ``globals()``/``exec`` makes the set unknowable, and callers then check nothing.
    """
    key = hashlib.sha256(source).digest()
    if key in _BINDINGS_CACHE:
        return _BINDINGS_CACHE[key]
    names: set = set()
    dynamic = False

    def bind(target: ast.AST) -> None:
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                bind(element)
        elif isinstance(target, ast.Starred):
            bind(target.value)

    def visit(body: Sequence[ast.stmt]) -> None:
        nonlocal dynamic
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
                dynamic = dynamic or node.name == "__getattr__"
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    bind(target)
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                bind(node.target)
            elif isinstance(node, ast.Import):
                names.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "*":
                        dynamic = True
                    else:
                        names.add(alias.asname or alias.name)
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                bind(node.target)
                visit(node.body)
                visit(node.orelse)
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                for item in node.items:
                    if item.optional_vars is not None:
                        bind(item.optional_vars)
                visit(node.body)
            elif isinstance(node, (ast.If, ast.While)):
                visit(node.body)
                visit(node.orelse)
            elif isinstance(node, (ast.Try, ast.TryStar)):
                visit(node.body)
                for handler in node.handlers:
                    if handler.name:
                        names.add(handler.name)
                    visit(handler.body)
                visit(node.orelse)
                visit(node.finalbody)
            elif isinstance(node, ast.Match):
                for case in node.cases:
                    visit(case.body)

    visit(tree.body)
    for node in ast.walk(tree):
        if isinstance(node, ast.Global):
            names.update(node.names)
        elif isinstance(node, ast.NamedExpr) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            names.add(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            names.add(node.rest)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id in {"globals", "exec"}):
            dynamic = True
    _BINDINGS_CACHE[key] = (frozenset(names), dynamic)
    return _BINDINGS_CACHE[key]


def _rebound_names(tree: ast.AST) -> set:
    """Every name a file binds other than by import; any of them may shadow an import alias."""
    names: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load):
            names.add(node.id)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            names.add(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            names.add(node.rest)
    return names


def _attribute_error_guarded(tree: ast.AST) -> set:
    """ids of the nodes inside a try body with a handler that names AttributeError.

    Only that handler is a fallback for a missing attribute. ``except Exception``
    around a handler body is not one: it turns the missing name into a send that
    silently never happens, which is worse than the crash.
    """
    def names_attribute_error(kind: Optional[ast.expr]) -> bool:
        if isinstance(kind, ast.Tuple):
            return any(names_attribute_error(element) for element in kind.elts)
        return isinstance(kind, ast.Name) and kind.id == "AttributeError"

    guarded: set = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Try, ast.TryStar)) and any(
                names_attribute_error(handler.type) for handler in node.handlers):
            for statement in node.body:
                guarded.update(id(child) for child in ast.walk(statement))
    return guarded


def _check_package_names(
    members: Dict[str, bytes], trees: Dict[str, ast.Module]
) -> Tuple[List[str], List[str]]:
    """Resolve imports of the package's own modules down to the names they use.

    The root check in ``validate`` passes ``from lambda_utils.template_media import X``
    once ``lambda_utils`` is packaged, whatever X is. On 2026-10-25 #1567 renamed
    ORDER_CATALOG_HEADER_IMAGE without updating its users. Outbound's module-level
    import of it passed ``--dry-run`` and would have failed every cold start with
    ImportError; the invoice engine's ``template_media.ORDER_CATALOG_HEADER_IMAGE``
    would have failed every payment-request send with AttributeError. With SnapStart
    off, publishing a version runs none of this code either, so nothing else stood
    between the rename and the first production invocation.

    For the package's own modules, then: an imported module must exist, a name
    imported from one must be defined there or be a submodule, and ``alias.name``
    read through an import alias must be defined in that module. As in the root
    check, an import inside try/except is a warning; for a read, only a handler that
    names AttributeError makes it one.
    """
    errors: List[str] = []
    warnings: List[str] = []
    local = {name.split("/")[0].removesuffix(".py") for name in members if name.endswith(".py")}
    directories = _package_directories(members)
    bindings_by_file: Dict[str, Tuple[frozenset, bool]] = {}

    def exists(dotted: str) -> bool:
        return (_module_file(members, dotted) is not None
                or dotted.replace(".", "/") in directories)

    def bindings(arcname: str) -> Tuple[frozenset, bool]:
        if arcname not in bindings_by_file:
            bindings_by_file[arcname] = _module_bindings(members[arcname], trees[arcname])
        return bindings_by_file[arcname]

    def defines(module: str, name: str) -> bool:
        if exists(f"{module}.{name}"):
            return True
        arcname = _module_file(members, module)
        if arcname is None:  # a namespace package binds nothing but its submodules
            return False
        if arcname not in trees:  # unparseable, already reported as a syntax error
            return True
        names, dynamic = bindings(arcname)
        return dynamic or name in names

    def module_of(expr: ast.expr, modules: Dict[str, str]) -> Optional[str]:
        """The package module an expression like ``alias`` or ``alias.sub`` evaluates to."""
        if isinstance(expr, ast.Name):
            return modules.get(expr.id)
        if isinstance(expr, ast.Attribute):
            parent = module_of(expr.value, modules)
            if parent and exists(f"{parent}.{expr.attr}"):
                return f"{parent}.{expr.attr}"
        return None

    for arcname, tree in trees.items():
        # Only computed once a file has a finding: problems are rare, walks are not free.
        guards: Dict[str, set] = {}

        def report(node: ast.AST, problem: str, guard: str) -> None:
            if guard not in guards:
                guards[guard] = (_guarded_import_lines(tree) if guard == "import"
                                 else _attribute_error_guarded(tree))
            message = f"{arcname}:{node.lineno} {problem}"
            key = node.lineno if guard == "import" else id(node)
            if key in guards[guard]:
                warnings.append(message + " (guarded by try/except)")
            else:
                errors.append(message)

        # local name -> the package modules imports bind it to. A name an import binds
        # to anything else ("other") is ambiguous, so reads through it are not checked.
        aliases: Dict[str, set] = {}
        other: set = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    bound = alias.asname or root
                    if root not in local:
                        other.add(bound)
                    elif not exists(alias.name):
                        report(node, f"imports '{alias.name}', which is not in the package", "import")
                    else:
                        aliases.setdefault(bound, set()).add(alias.name if alias.asname else root)
            elif isinstance(node, ast.ImportFrom):
                module = _absolute_module(arcname, node)
                if not module or module.split(".")[0] not in local:
                    other.update(alias.asname or alias.name for alias in node.names)
                    continue
                if not exists(module):
                    report(node, f"imports from '{module}', which is not in the package", "import")
                    continue
                parent = _module_file(members, module)
                parent_names = bindings(parent)[0] if parent in trees else frozenset()
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    bound = alias.asname or alias.name
                    submodule = f"{module}.{alias.name}"
                    if alias.name not in parent_names and exists(submodule):
                        aliases.setdefault(bound, set()).add(submodule)
                        continue
                    other.add(bound)
                    if not defines(module, alias.name):
                        report(node, f"imports '{alias.name}' from '{module}', which does not define it",
                               "import")

        modules = {name: next(iter(targets)) for name, targets in aliases.items()
                   if len(targets) == 1 and name not in other}
        if not modules:
            continue
        suspects = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute) or not isinstance(node.ctx, ast.Load):
                continue
            if node.attr.startswith("__") and node.attr.endswith("__"):
                continue  # module dunders (__name__, __file__, ...) always exist
            module = module_of(node.value, modules)
            if module is not None and not defines(module, node.attr):
                suspects.append((node, module))
        if not suspects:
            continue
        # A suspect read is only a finding if its alias really is the module: not shadowed
        # by a local of the same name anywhere in the file, and the attribute not assigned
        # onto it here.
        rebound = _rebound_names(tree)
        assigned = {(node.value.id, node.attr) for node in ast.walk(tree)
                    if isinstance(node, ast.Attribute) and not isinstance(node.ctx, ast.Load)
                    and isinstance(node.value, ast.Name)}
        for node, module in suspects:
            base = node.value
            while isinstance(base, ast.Attribute):
                base = base.value
            if not isinstance(base, ast.Name) or base.id in rebound:
                continue
            if isinstance(node.value, ast.Name) and (node.value.id, node.attr) in assigned:
                continue
            report(node, f"reads '{module}.{node.attr}', which that module does not define", "read")

    return errors, warnings


def validate(
    spec: Spec, members: Dict[str, bytes], provided: frozenset
) -> Tuple[List[str], List[str]]:
    """Static import check. Returns (errors, warnings).

    Catches the failure this fleet is prone to: a handler importing a shared
    module the packaging step forgot to include. Being static, it cannot report
    a false failure over missing env vars the way actually importing would.

    An unresolved import inside try/except is a warning, not an error, because
    the code has a documented fallback path for it.

    Imports of the package's own modules are then resolved down to the names
    they use (``_check_package_names``): a packaged module is no proof that the
    name imported from it exists.
    """
    errors: List[str] = []
    warnings: List[str] = []

    available = {name.split("/")[0].removesuffix(".py") for name in members}
    known = available | provided | RUNTIME_PROVIDED | set(sys.stdlib_module_names)

    trees: Dict[str, ast.Module] = {}
    for arcname in sorted(members):
        if not arcname.endswith(".py"):
            continue
        try:
            tree = ast.parse(members[arcname].decode("utf-8"), filename=arcname)
        except SyntaxError as exc:
            errors.append(f"{arcname}: syntax error: {exc}")
            continue
        trees[arcname] = tree

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

    package_errors, package_warnings = _check_package_names(members, trees)
    errors += package_errors
    warnings += package_warnings
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


def _update_with_retry(lam, spec: Spec, zip_bytes: bytes, attempts: int = 5,
                       read: Optional[dict] = None):
    """update_function_code with exponential backoff on transient errors.

    Returns the API result, or raises the last ClientError. A retry is only
    attempted for the codes in _RETRYABLE; a genuine error (bad zip, missing
    function, denied) still fails immediately, because retrying it would just
    slow the run down and bury the message.

    ``read`` is the configuration this run read before packaging. The upload
    carries its RevisionId, so if another deploy uploaded different code in the
    meantime, PreconditionFailedException is raised rather than overwriting it.
    A revision moved without a code change (a configuration edit, or Lambda
    settling a previous update) is re-read and retried.
    """
    request = {"FunctionName": spec.name, "ZipFile": zip_bytes, "Publish": False}
    if read and read.get("RevisionId"):
        request["RevisionId"] = read["RevisionId"]
    delay = 2.0
    last: ClientError | None = None
    for attempt in range(1, attempts + 1):
        try:
            return lam.update_function_code(**request)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code == "PreconditionFailedException" and read and attempt < attempts:
                fresh = lam.get_function_configuration(FunctionName=spec.name)
                if fresh.get("CodeSha256") != read.get("CodeSha256"):
                    raise
                request["RevisionId"] = fresh["RevisionId"]
                last = exc
                continue
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
        result = _update_with_retry(lam, spec, zip_bytes, read=current)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "PreconditionFailedException":
            print("    refused: another deploy uploaded different code after this run read "
                  "the function; not uploading over it")
        else:
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


PAYMENT_CONFIG_TARGETS = frozenset({'wecare-invoice-engine', 'wecare-outbound-whatsapp'})
PAYMENT_CONFIG_KEYS = ('EXPECTED_CONFIGURATION_NAME', 'EXPECTED_PROVIDER_MID')


def prepare_payment_environment(lam, name: str, current: dict, *,
                                sync_from_checkout: bool, dry_run: bool) -> dict:
    """Keep payment callers aligned with the published checkout's expected merchant.

    Copies only two non-secret expectations, never credentials or feature flags. Runtime
    readiness still verifies the configuration against Meta before sending any payment.
    RevisionId prevents overwriting a concurrent configuration edit.
    """
    if name not in PAYMENT_CONFIG_TARGETS:
        return current
    environment = dict(current.get('Environment', {}).get('Variables', {}))
    if not sync_from_checkout:
        if any(not str(environment.get(key, '')).strip() for key in PAYMENT_CONFIG_KEYS):
            raise ValueError('payment expectations missing; use --sync-payment-config after '
                             'verifying the published checkout merchant configuration')
        return current
    source = lam.get_function_configuration(FunctionName='wecare-checkout', Qualifier='live')
    source_environment = source.get('Environment', {}).get('Variables', {})
    if any(not str(source_environment.get(key, '')).strip() for key in PAYMENT_CONFIG_KEYS):
        raise ValueError('published checkout has incomplete payment expectations')
    desired = {**environment, **{key: source_environment[key] for key in PAYMENT_CONFIG_KEYS}}
    if desired == environment:
        return current
    if dry_run:
        print('    WOULD SYNC payment expectations from wecare-checkout:live')
        return {**current, 'Environment': {'Variables': desired}}
    revision = current.get('RevisionId')
    if not revision:
        raise ValueError('configuration read did not return RevisionId')
    lam.update_function_configuration(FunctionName=name, RevisionId=revision,
                                      Environment={'Variables': desired})
    lam.get_waiter('function_updated_v2').wait(FunctionName=name)
    updated = lam.get_function_configuration(FunctionName=name)
    actual = updated.get('Environment', {}).get('Variables', {})
    if any(actual.get(key) != value for key, value in desired.items()) or set(actual) != set(desired):
        raise ValueError('payment environment readback differs from the requested configuration')
    return updated


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("functions", nargs="*", help="function names; default is all")
    ap.add_argument("--dry-run", action="store_true",
                    help="build and validate packages, upload nothing")
    ap.add_argument("--no-publish", action="store_true",
                    help="skip snapstart_publish.py (leaves the `live` alias on old code)")
    ap.add_argument("--sync-payment-config", action="store_true",
                    help="copy payment expectations from checkout:live to invoice/outbound before publishing")
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

    try:
        dirty = uncommitted_sources()
    except RuntimeError as exc:
        print(f"cannot read the checkout's status: {exc}")
        if not args.dry_run:
            return 1
        dirty = []
    if dirty is None:
        print(f"packaging an exported tree: {ROOT}")
    else:
        unclean = sorted({path for spec in selected for path in dirty_sources_for(spec, dirty)})
        if unclean:
            print(("WARNING" if args.dry_run else "REFUSING")
                  + f": {len(unclean)} uncommitted file(s) would be packaged:")
            for path in unclean:
                print(f"  {path}")
            if not args.dry_run:
                print("Commit them first, or deploy a pinned commit from an export:\n"
                      "  git archive <ref> amplify/functions scripts | tar -x -C <dir>\n"
                      "  python <dir>/scripts/deploy_all_lambdas.py <functions>")
                return 1
            print("A real deploy refuses this tree.\n")

    lam = boto3.client("lambda", region_name=REGION)
    print(f"region={REGION} targets={len(selected)} dry_run={args.dry_run}")
    print()

    tally = {"updated": 0, "unchanged": 0, "failed": 0, "awaiting_provisioning": 0,
             # dry-run only: packaged bytes differ from what is live
             "would_update": 0}
    failures: List[str] = []
    deployed: List[str] = []
    uploaded: Dict[str, str] = {}  # name -> CodeSha256 of the zip this run uploaded
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

        current_layer_arns = [layer["Arn"] for layer in (current.get("Layers") or [])]
        missing_layers = [arn for arn in spec.required_layers if arn not in current_layer_arns]
        if missing_layers:
            if args.dry_run:
                print("    WOULD ADD LAYER(S): " + ", ".join(missing_layers))
            else:
                wanted_layers = current_layer_arns + missing_layers
                lam.update_function_configuration(FunctionName=spec.name, Layers=wanted_layers)
                lam.get_waiter("function_updated_v2").wait(FunctionName=spec.name)
                current = lam.get_function_configuration(FunctionName=spec.name)
                current_layer_arns = [layer["Arn"] for layer in (current.get("Layers") or [])]

        runtime_changes = {}
        if spec.required_memory is not None and current.get("MemorySize") != spec.required_memory:
            runtime_changes["MemorySize"] = spec.required_memory
        if spec.required_timeout is not None and current.get("Timeout") != spec.required_timeout:
            runtime_changes["Timeout"] = spec.required_timeout
        if runtime_changes:
            if args.dry_run:
                print("    WOULD UPDATE RUNTIME: " + ", ".join(
                    f"{key}={value}" for key, value in sorted(runtime_changes.items())))
            else:
                lam.update_function_configuration(FunctionName=spec.name, **runtime_changes)
                lam.get_waiter("function_updated_v2").wait(FunctionName=spec.name)
                current = lam.get_function_configuration(FunctionName=spec.name)

        provided: frozenset = frozenset()
        for arn in sorted(set(current_layer_arns) | set(spec.required_layers)):
            provided |= layer_modules(lam, arn)

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

        try:
            current = prepare_payment_environment(
                lam, spec.name, current, sync_from_checkout=args.sync_payment_config,
                dry_run=args.dry_run)
        except Exception as exc:  # configuration failure must prevent code publication
            print(f"    payment configuration failed: {exc}")
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
            uploaded[spec.name] = base64.b64encode(hashlib.sha256(zip_bytes).digest()).decode()

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
    elif deployed and not failures:
        print("\nPublishing versions + moving the `live` alias "
              "(the API invokes :live, not $LATEST)...\n")
        publish_rc = subprocess.call(
            [sys.executable, str(ROOT / "scripts" / "snapstart_publish.py"), "--only-stale",
             *(f"--expect={name}={sha}" for name, sha in uploaded.items()), *deployed]
        )

    if failures and deployed and not args.no_publish:
        print("Refusing to move live aliases: at least one selected function failed validation/update.")
    return 1 if (failures or publish_rc) else 0


if __name__ == "__main__":
    sys.exit(main())
