"""Secure-file-sharing invariants that must not regress.

These pin the decisions that are easy to undo by accident, not the happy path:

* an opaque S3 key that leaks nothing about the customer or the file
* one refusal message shared by "not yours" and "does not exist"
* payment disabled by default, and no Razorpay contact while it is disabled
* entitlement written only by the signature-verified webhook
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FUNC_DIR = ROOT / "amplify" / "functions" / "core" / "secure-files"
SHARED = ROOT / "amplify" / "functions" / "shared"

for path in (str(FUNC_DIR), str(SHARED)):
    if path not in sys.path:
        sys.path.insert(0, path)


@pytest.fixture()
def mod(monkeypatch):
    """Load secure-files' handler by PATH, under a name of its own.

    `importlib.import_module("handler")` is what this used to do, and it is unsafe in
    this repo: there are 64 files called handler.py and seven test modules that import a
    bare `handler`, so whichever runs first owns sys.modules["handler"] and every later
    import gets that one back. Running this file alone passed; running the full suite
    handed these tests messaging/outbound-whatsapp/handler.py and 20 of them failed on
    AttributeError. CI runs the full suite, so they were failing there and passing here.

    spec_from_file_location with a unique module name removes the shared key entirely,
    so this file no longer depends on - or affects - collection order.
    """
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.delenv("SECURE_FILES_PAYMENT_ENABLED", raising=False)

    spec = importlib.util.spec_from_file_location(
        "wecare_secure_files_handler", FUNC_DIR / "handler.py"
    )
    module = importlib.util.module_from_spec(spec)
    # Registered before exec so any self-referential import resolves to this instance.
    sys.modules["wecare_secure_files_handler"] = module
    spec.loader.exec_module(module)
    return module


# ── the opaque key ────────────────────────────────────────────────────────────

def test_key_is_two_uuids_and_leaks_nothing(mod):
    """The key must not contain the customer's number or the original filename."""
    import re
    import uuid

    phone = "918100640044"
    original = "Trade-Licence-Ramesh.pdf"

    file_id = f"{uuid.uuid4().hex}-{uuid.uuid4().hex}"
    key = f"{mod.SECURE_PREFIX}wecare-digital-{file_id}{mod._safe_extension(original)}"

    assert key.startswith("secure/wecare-digital-")
    assert re.fullmatch(r"secure/wecare-digital-[0-9a-f]{32}-[0-9a-f]{32}\.pdf", key)
    assert phone not in key
    assert "Ramesh" not in key
    assert "Licence" not in key


def test_extension_is_whitelisted_not_sanitised(mod):
    assert mod._safe_extension("a.pdf") == ".pdf"
    assert mod._safe_extension("a.PNG") == ".png"
    # anything odd is dropped rather than cleaned, because it lands in an S3 key
    assert mod._safe_extension("a.tar.gz") == ".gz"
    assert mod._safe_extension("noextension") == ""
    assert mod._safe_extension("a.verylongextension") == ""
    assert mod._safe_extension("a.p df") == ""
    assert mod._safe_extension("a.../../etc") == ""
    assert mod._safe_extension("") == ""


# ── phone handling ────────────────────────────────────────────────────────────

def test_phone_normalisation_matches_the_otp_lambda(mod):
    """If these drift, a customer authenticates and then owns nothing."""
    assert mod.normalise_phone("8100640044") == "918100640044"
    assert mod.normalise_phone("+91 81006 40044") == "918100640044"
    assert mod.normalise_phone("918100640044") == "918100640044"
    for bad in ("", "123", "abc", "9" * 20):
        with pytest.raises(ValueError):
            mod.normalise_phone(bad)


def test_phone_is_masked_to_last_four(mod):
    masked = mod.mask_phone("918100640044")
    assert masked.endswith("0044")
    assert "8100" not in masked
    assert masked == "********0044"


# ── uniform refusal ───────────────────────────────────────────────────────────

def test_wrong_owner_and_missing_file_are_indistinguishable(mod):
    """Any difference here lets a caller probe which file ids exist."""
    a = mod._not_registered("https://wecare.digital")
    b = mod._not_registered("https://wecare.digital")
    assert a == b
    assert a["statusCode"] == 403
    assert "NOT_REGISTERED" in a["body"]
    # must not hint at existence
    for leak in ("not found", "does not exist", "unknown file", "forbidden owner"):
        assert leak.lower() not in a["body"].lower()


# ── payment stays off ─────────────────────────────────────────────────────────

def test_payment_disabled_by_default(mod, monkeypatch):
    monkeypatch.delenv("SECURE_FILES_PAYMENT_ENABLED", raising=False)
    assert mod._payment_enabled() is False


def test_payment_flag_is_read_per_call_not_captured_at_import(mod, monkeypatch):
    """A switch that needs every sandbox to recycle is not a switch."""
    assert mod._payment_enabled() is False
    monkeypatch.setenv("SECURE_FILES_PAYMENT_ENABLED", "true")
    assert mod._payment_enabled() is True
    monkeypatch.setenv("SECURE_FILES_PAYMENT_ENABLED", "off")
    assert mod._payment_enabled() is False


def test_order_creation_refuses_and_never_touches_razorpay_while_disabled(mod, monkeypatch):
    monkeypatch.delenv("SECURE_FILES_PAYMENT_ENABLED", raising=False)

    monkeypatch.setattr(
        mod,
        "_owned_active_file",
        lambda fid, ident: {"fileId": fid, "pricePaise": 4900, "s3Key": "secure/x"},
    )

    def explode(*_a, **_k):  # pragma: no cover - must not be reached
        raise AssertionError("Razorpay must not be contacted while payment is disabled")

    monkeypatch.setitem(
        sys.modules, "razorpay_orders", type(sys)("razorpay_orders")
    )
    sys.modules["razorpay_orders"].create_order = explode

    result = mod._create_order("f1", {"phone": "918100640044"}, "https://wecare.digital")
    assert result["statusCode"] == 503
    assert "PAYMENT_DISABLED" in result["body"]


# ── the customer pool, not the admin pool ─────────────────────────────────────

def test_issuer_is_pinned_to_the_customer_pool(mod):
    """An admin-pool token must not authorise a customer download.

    `get_user` is pool-agnostic, so the issuer check is the only thing separating
    the two pools.
    """
    assert mod.CUSTOMER_POOL_ID != "us-east-1_cSx0RHCIR"
    assert mod.CUSTOMER_POOL_ISSUER.endswith(mod.CUSTOMER_POOL_ID)
    assert mod.CUSTOMER_POOL_ISSUER.startswith("https://cognito-idp.")


def test_unverified_claim_decode_never_raises(mod):
    """It runs on attacker-supplied strings, so it must fail soft."""
    for junk in ("", "a", "a.b", "a.b.c", "...", "x" * 500):
        assert mod._jwt_claims_unverified(junk) == {}


def test_customer_identity_requires_a_token(mod):
    assert mod._customer_identity({"headers": {}}) is None
    assert mod._customer_identity({}) is None


# ── the webhook is the only grantor ───────────────────────────────────────────

def test_only_the_webhook_sets_paid_true():
    """`secure-files` must never write paid=True; that is the webhook's job alone."""
    source = (FUNC_DIR / "handler.py").read_text()
    # the pending grant is written with paid False
    assert '"paid": False' in source
    assert '"paid": True' not in source


def test_redeem_requires_paid_and_unconsumed():
    source = (FUNC_DIR / "handler.py").read_text()
    assert "paid = :true" in source
    assert "consumed = :false" in source
    assert "ConditionalCheckFailedException" in source


WEBHOOK_SOURCE = (
    ROOT / "amplify/functions/payments/razorpay-webhook/handler.py"
).read_text()


def test_webhook_cannot_grant_anything():
    """A valid webhook signature must not be proof of payment.

    The webhook secret that authenticates these callbacks is in this repository's public
    git history. While the webhook could flip a grant to ``paid`` itself, anyone who read
    that history could forge a ``payment.captured`` event and mint a free download.

    Rotation would close that hole. Removing the secret from the decision closes it
    without depending on a rotation ever happening, which is why the webhook now writes
    nothing: it forwards an order id and `secure-files` asks Razorpay.

    So this asserts an absence, and absences are what regress silently.
    """
    assert "secure_file_download" in WEBHOOK_SOURCE
    assert "_dispatch_download_grant_confirmation" in WEBHOOK_SOURCE

    # The old writer is gone, not merely unreferenced.
    assert "_mark_download_grant_paid" not in WEBHOOK_SOURCE

    # No write to the grants table survives anywhere in the webhook.
    assert "DOWNLOAD_GRANTS_TABLE" not in WEBHOOK_SOURCE
    assert "paid = :true" not in WEBHOOK_SOURCE
    assert "'paid': True" not in WEBHOOK_SOURCE
    assert '"paid": True' not in WEBHOOK_SOURCE


def test_webhook_forwards_only_the_order_id():
    """The webhook may not name a file, a recipient, or an amount.

    Everything else is re-derived from the grant this system wrote, so there is no field
    an attacker can populate to influence what gets sent or to whom. Pinning the payload
    shape is the cheap way to keep it that way: adding `amount` here "for convenience"
    would hand a forger a way to set the price.
    """
    body = WEBHOOK_SOURCE.split("def _dispatch_download_grant_confirmation", 1)[1]
    body = body.split("\ndef ", 1)[0]

    assert "'internalAction': 'confirmAndDeliver'" in body
    assert "'orderId': order_id" in body
    for forbidden in ("payment_id", "amount_paise", "notes", "contact", "grantId"):
        assert forbidden not in body, f"{forbidden} must not travel with the hint"


def test_redeem_replay_protection_lives_in_secure_files():
    """The condition that stops a replayed payment reviving a spent grant moved here.

    It used to sit in the webhook. It has to still exist somewhere, or removing it from
    the webhook would have quietly deleted the replay protection along with the write.
    """
    source = (FUNC_DIR / "handler.py").read_text()
    assert source.count("attribute_exists(grantId) AND paid = :false") >= 1


# ── Razorpay's API is the only thing that can grant ───────────────────────────

class _RecordingTable:
    """Minimal grants table that records writes instead of performing them."""

    def __init__(self, item=None, by_order=None):
        self._item = item
        self._by_order = by_order if by_order is not None else ([item] if item else [])
        self.updates = []

    def get_item(self, Key):  # noqa: N803 - boto3 casing
        return {"Item": self._item} if self._item else {}

    def query(self, **_kwargs):
        return {"Items": list(self._by_order)}

    def update_item(self, **kwargs):
        self.updates.append(kwargs)
        return {}


def _grant(**over):
    base = {
        "grantId": "g1",
        "orderId": "order_ABC",
        "fileId": "f1",
        "ownerPhone": "918100640044",
        "paid": False,
        "consumed": False,
        "channel": "web",
    }
    base.update(over)
    return base


def _stub_razorpay(monkeypatch, *, paid, payment_id="pay_1", amount=4900):
    fake = type(sys)("razorpay_orders")
    fake.order_is_paid = lambda order_id: (paid, payment_id, amount)
    monkeypatch.setitem(sys.modules, "razorpay_orders", fake)
    return fake


def test_forged_webhook_grants_nothing(mod, monkeypatch):
    """The whole point of the redesign.

    An attacker holding the leaked webhook secret can produce a perfectly signed
    `payment.captured` for a real order id. They reach exactly here, Razorpay is asked,
    Razorpay says no captured payment, and no grant is written.
    """
    monkeypatch.setenv("SECURE_FILES_PAYMENT_ENABLED", "true")
    table = _RecordingTable(_grant())
    monkeypatch.setattr(mod, "_table", lambda _name: table)
    _stub_razorpay(monkeypatch, paid=False)

    ok, detail = mod.confirm_and_deliver("order_ABC")

    assert ok is False
    assert "no captured payment" in detail
    assert table.updates == [], "a forged event must not write to the grants table"


def test_real_payment_grants_and_records_the_amount_razorpay_reported(mod, monkeypatch):
    """The amount written is Razorpay's, never the caller's."""
    monkeypatch.setenv("SECURE_FILES_PAYMENT_ENABLED", "true")
    table = _RecordingTable(_grant())
    monkeypatch.setattr(mod, "_table", lambda _name: table)
    _stub_razorpay(monkeypatch, paid=True, payment_id="pay_real", amount=4900)

    ok, detail = mod.confirm_and_deliver("order_ABC")

    assert ok is True
    assert detail == "confirmed; web channel collects by redeem"
    assert len(table.updates) == 1
    values = table.updates[0]["ExpressionAttributeValues"]
    assert values[":pid"] == "pay_real"
    assert values[":amt"] == 4900
    assert values[":via"] == "webhook"
    # replay protection travels with the write
    assert "paid = :false" in table.updates[0]["ConditionExpression"]


def test_confirmation_is_inert_while_payments_are_disabled(mod, monkeypatch):
    monkeypatch.delenv("SECURE_FILES_PAYMENT_ENABLED", raising=False)
    table = _RecordingTable(_grant())
    monkeypatch.setattr(mod, "_table", lambda _name: table)

    def explode(*_a, **_k):  # pragma: no cover - must not be reached
        raise AssertionError("Razorpay must not be contacted while payment is disabled")

    fake = type(sys)("razorpay_orders")
    fake.order_is_paid = explode
    monkeypatch.setitem(sys.modules, "razorpay_orders", fake)

    ok, detail = mod.confirm_and_deliver("order_ABC")
    assert ok is False
    assert detail == "payments disabled"
    assert table.updates == []


def test_a_consumed_grant_cannot_be_reconfirmed(mod, monkeypatch):
    """Single-use means single-use. Replaying a real capture must not re-arm a spent
    grant, because the file has already been delivered once."""
    monkeypatch.setenv("SECURE_FILES_PAYMENT_ENABLED", "true")
    table = _RecordingTable(_grant(consumed=True))
    monkeypatch.setattr(mod, "_table", lambda _name: table)
    _stub_razorpay(monkeypatch, paid=True)

    ok, detail = mod.confirm_and_deliver("order_ABC")
    assert ok is False
    assert "consumed" in detail
    assert table.updates == []


def test_an_unknown_order_grants_nothing(mod, monkeypatch):
    """What a forged event for an invented order id looks like."""
    monkeypatch.setenv("SECURE_FILES_PAYMENT_ENABLED", "true")
    table = _RecordingTable(None, by_order=[])
    monkeypatch.setattr(mod, "_table", lambda _name: table)
    _stub_razorpay(monkeypatch, paid=True)

    ok, detail = mod.confirm_and_deliver("order_NOPE")
    assert ok is False
    assert "no grant for that order" in detail
    assert table.updates == []


def test_unreachable_razorpay_fails_closed(mod, monkeypatch):
    """Integrity over availability. A real payment is recoverable by the reconcile
    sweep; a grant handed out on an unverified claim is not, because the file is gone."""
    monkeypatch.setenv("SECURE_FILES_PAYMENT_ENABLED", "true")
    table = _RecordingTable(_grant())
    monkeypatch.setattr(mod, "_table", lambda _name: table)

    fake = type(sys)("razorpay_orders")

    def boom(_order_id):
        raise RuntimeError("connection reset")

    fake.order_is_paid = boom
    monkeypatch.setitem(sys.modules, "razorpay_orders", fake)

    ok, detail = mod.confirm_and_deliver("order_ABC")
    assert ok is False
    assert "could not reach Razorpay" in detail
    assert table.updates == []


def test_confirm_with_razorpay_is_the_only_writer_of_paid(mod):
    """If a second writer appears, the guarantee is gone and nothing else would notice.

    `paid = :true` may appear exactly once in the whole function, inside
    `_confirm_with_razorpay`. The reconcile path deliberately delegates here rather than
    keeping its own copy, which is what this catches if someone re-inlines it.
    """
    source = (FUNC_DIR / "handler.py").read_text()
    assert source.count("paid = :true, paymentId") == 1

    body = source.split("def _confirm_with_razorpay", 1)[1].split("\ndef ", 1)[0]
    assert "paid = :true, paymentId" in body, "the one writer must be _confirm_with_razorpay"

    # the reconcile path delegates rather than duplicating
    reconcile = source.split("def _reconcile_grant", 1)[1].split("\ndef ", 1)[0]
    assert "_confirm_with_razorpay(grant, via=\"reconcile\")" in reconcile
    assert "paid = :true" not in reconcile


def test_internal_actions_are_unreachable_over_http(mod):
    """Both internal branches must require the absence of requestContext.

    API Gateway always supplies one, so this is what keeps `confirmAndDeliver` off the
    public internet. Without it, anyone could POST a confirmation for any order.
    """
    source = (FUNC_DIR / "handler.py").read_text()
    for action in ("deliverOverWhatsApp", "confirmAndDeliver"):
        needle = (
            f'if event.get("internalAction") == "{action}" '
            'and not event.get("requestContext"):'
        )
        assert needle in source, f"{action} branch must be gated on requestContext"


def test_confirm_and_deliver_takes_no_recipient_or_file(mod):
    """Its whole signature is the security argument: one order id, nothing else."""
    import inspect

    params = list(inspect.signature(mod.confirm_and_deliver).parameters)
    assert params == ["order_id"]


def test_order_creation_reads_the_api_secret_not_the_webhook_secret():
    """The two Razorpay secrets hold different fields and are not interchangeable.

        wecare/razorpay/api        key_id + key_secret
        wecare/razorpay-webhook    webhook_secret only

    partner-onboarding already shipped this bug once: it read the API pair out of
    the webhook secret, got two empty strings, and returned 501 on every top-up.
    This pins the correct one so the same mistake cannot land twice.
    """
    source = (FUNC_DIR / "razorpay_orders.py").read_text()
    assert 'RAZORPAY_SECRET_ID = os.environ.get("RAZORPAY_SECRET_ID", "wecare/razorpay/api")' in source

    provisioner = (ROOT / "scripts/provision_secure_files_api.py").read_text()
    assert 'RAZORPAY_SECRET_NAME = "wecare/razorpay/api"' in provisioner
    # and the IAM grant must follow the same secret, or the read 403s at runtime
    assert "secret:{RAZORPAY_SECRET_NAME}-*" in provisioner


def test_no_razorpay_sdk_is_bundled():
    """razorpay==2.0.1 is dev-only; the Lambda runtime does not have it."""
    source = (FUNC_DIR / "razorpay_orders.py").read_text()
    assert "import razorpay" not in source
    assert "urllib.request" in source

    dev_requirements = (ROOT / "requirements-dev.txt").read_text()
    assert "razorpay==" in dev_requirements, "expected the SDK pinned for dev use"


def test_razorpay_orders_reads_the_secret_lazily_not_at_import():
    """A module-scope secret read is frozen for the sandbox's life."""
    source = (FUNC_DIR / "razorpay_orders.py").read_text()
    assert "_cached" in source
    # no top-level get_secret_value call
    for line in source.splitlines():
        if line.startswith("get_secret_value") or line.startswith("_sm.get_secret_value"):
            raise AssertionError("secret is read at import scope")
    assert "def _credentials()" in source


def test_no_credential_is_logged_or_returned():
    source = (FUNC_DIR / "razorpay_orders.py").read_text()
    assert "key_secret" in source  # it is used
    # but never printed, logged or put in an exception message
    for bad in ("print(", "logger.info(creds", "logger.warning(creds", f'{{creds}}'):
        assert bad not in source


def test_generated_password_is_never_logged_or_returned():
    """The random permanent password exists only to reach CONFIRMED status."""
    source = (FUNC_DIR / "handler.py").read_text()
    assert "admin_set_user_password" in source
    assert "token_urlsafe" in source
    # it must not be returned to the admin or logged anywhere
    assert "password" not in source.split("def _upload_init")[1].lower()


# ── the OTP send shape, proven against the live WABA ──────────────────────────

def test_otp_button_is_url_not_copy_code():
    """`wecare_otp` is an AUTHENTICATION template and its button is type URL.

    Meta materialises the copy-code affordance as a real URL button:

        https://www.whatsapp.com/otp/code/?...&code=otp{{1}}

    so the OTP is a text substitution into that URL. Sending
    `sub_type: "copy_code"` with a `coupon_code` parameter is refused:

        (#132018) buttons: Button at index 0 must be of type Url

    and the caller sees only "sender returned HTTP 400", which is why this was
    invisible until a live round trip was run. Verified 2026-09-25: copy_code
    fails, url succeeds.
    """
    source = (
        ROOT / "amplify/functions/auth/customer-whatsapp-auth/handler.py"
    ).read_text()

    # Assert on the payload, not on the whole file: the comment above the fix names
    # the rejected shape, so a bare substring search for "copy_code" matches the
    # explanation rather than any real code.
    code_lines = [
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    ]
    code = "\n".join(code_lines)

    assert '"sub_type": "url"' in code
    assert '"sub_type": "copy_code"' not in code
    assert '"coupon_code"' not in code
    # the OTP substitutes {{1}} as text
    assert '{"type": "text", "text": otp}' in code


def test_otp_template_name_and_language_are_not_drifted():
    """The live template is `wecare_otp` / `en`. A mismatch fails at the Meta call."""
    source = (
        ROOT / "amplify/functions/auth/customer-whatsapp-auth/handler.py"
    ).read_text()
    assert '"OTP_TEMPLATE_NAME", "wecare_otp"' in source
    assert '"OTP_TEMPLATE_LANGUAGE", "en"' in source


def test_otp_is_never_logged():
    """The handler prints metadata about a send but must never include the code."""
    source = (
        ROOT / "amplify/functions/auth/customer-whatsapp-auth/handler.py"
    ).read_text()
    logged = source.split("customer_whatsapp_otp_sent")[1][:400]
    assert "otp" not in logged.lower().replace("otp_sent", "")


# ── the customer loop in the browser ──────────────────────────────────────────

CLIENT_TS = ROOT / "src/api/client.ts"
# The collection page lives at /get, the URL originally specified. It was briefly at
# /files while working around /get/<*> being rewritten to CloudFront.
FILES_PAGE = ROOT / "src/pages/get.tsx"
CUSTOMER_AUTH = ROOT / "src/lib/customerAuth.ts"


def _strip_comments(source: str) -> str:
    """Drop TS comments before asserting.

    These files document the shape they deliberately avoid - "sessionStorage, not
    localStorage", "must NOT go through authFetch" - so a naive substring search
    matches the explanation and fails on correct code.
    """
    out = []
    in_block = False
    for line in source.splitlines():
        stripped = line.strip()
        if in_block:
            if "*/" in stripped:
                in_block = False
            continue
        if stripped.startswith("/*"):
            if "*/" not in stripped:
                in_block = True
            continue
        if stripped.startswith("*") or stripped.startswith("//"):
            continue
        out.append(line.split("//")[0] if "://" not in line else line)
    return "\n".join(out)


def _ts_function(source: str, name: str) -> str:
    """One function's own source, and nothing after it.

    Two approaches that do not work here, both tried:

    * cutting at the next ``\\n}`` - these signatures carry multi-line generic return
      types like ``Promise<ApiResult<{ ... }>>``, so the first closing brace belongs
      to the type rather than the body;
    * cutting at the next ``\\nexport`` - ``customerApiCall`` is an unexported helper
      sitting between two exported functions, so it got swallowed into the preceding
      one and every assertion about which fetch path is used became meaningless.

    Cutting at the first column-zero ``}`` ends at the function's own closing brace,
    since everything nested is indented.
    """
    # The name must end at a non-identifier character, or a prefix match wins: looking
    # for `sendWhatsAppPayment` found the pre-existing `sendWhatsAppPaymentMessage`
    # further up the file and asserted against the wrong function entirely.
    match = re.search(
        rf"export async function {re.escape(name)}(?![A-Za-z0-9_])", source
    )
    if not match:
        raise AssertionError(f"no exported function named exactly {name}")
    start = match.start()
    lines = source[start:].splitlines()
    body = []
    for index, line in enumerate(lines):
        body.append(line)
        if index > 0 and line == "}":
            break
    return "\n".join(body)


def test_customer_routes_use_the_customer_token_not_the_staff_token():
    """The three customer routes must not go through apiCall/authFetch.

    authFetch attaches the Amplify session, which belongs to the STAFF pool. A staff
    token on a customer route does not fail cleanly: the backend validates it, sees
    the wrong issuer and returns 401, which is indistinguishable from an expired
    customer session - so the customer would be sent round the verification loop
    forever with no indication why.
    """
    source = _strip_comments(CLIENT_TS.read_text())

    for fn in (
        "listMySecureFiles",
        "createSecureFileOrder",
        "redeemSecureFileDownload",
    ):
        body = _ts_function(source, fn)
        assert "customerApiCall" in body, f"{fn} must use the customer token"
        assert "apiCallResult(" not in body, f"{fn} must not use the staff token path"
        assert "authFetch(" not in body, f"{fn} must not use the staff token path"


def test_admin_routes_still_use_the_staff_token():
    source = _strip_comments(CLIENT_TS.read_text())
    for fn in ("initSecureUpload", "listSecureFiles", "revokeSecureFile", "confirmSecureUpload"):
        body = _ts_function(source, fn)
        assert "apiCallResult" in body, f"{fn} is an admin route and needs the staff token"
        assert "customerApiCall" not in body, f"{fn} must not use a customer token"


def test_the_page_never_handles_payment_itself():
    """Payment and delivery both happen on WhatsApp, so the browser is out of the loop.

    The page asks the backend to send the approved wecare_pay template and stops. The
    customer pays through the template's ORDER_DETAILS button and the file arrives as a
    WhatsApp document, so nothing here can grant anything.
    """
    source = FILES_PAGE.read_text()
    assert "requestFilePaymentOnWhatsApp" in source

    # No Razorpay Checkout machinery on the page at all. This is a stronger guarantee
    # than the earlier "do not trust the success callback": there is no callback,
    # because the browser is no longer in the payment path.
    for gone in ("checkout.razorpay.com", "window.Razorpay", "loadCheckout", "order_id"):
        assert gone not in source, f"{gone} should have left with Checkout"

    # and nothing polls for or triggers a download
    assert "pollForDownload" not in source
    assert "downloadUrl" not in source


def test_the_page_does_not_choose_the_recipient():
    """Accepting a phone number from the client would make this a way to send WhatsApp
    messages to arbitrary people. The backend uses the verified token's number."""
    body = _ts_function(_strip_comments(CLIENT_TS.read_text()), "requestFilePaymentOnWhatsApp")
    assert "whatsapp-pay" in body
    assert "customerApiCall" in body
    assert "phone" not in body.lower()


def test_presigned_upload_does_not_get_a_bearer_header():
    """A presigned URL carries its own SigV4; adding our bearer makes S3 refuse."""
    source = CLIENT_TS.read_text()
    body = source.split("export async function uploadSecureFileBytes")[1].split("\n}")[0]
    assert "Authorization" not in body
    assert "authFetch" not in body


def test_frontend_phone_normalisation_matches_the_backend():
    """Drift here means a customer signs in and owns nothing."""
    source = CUSTOMER_AUTH.read_text()
    # same rule as normalise_phone: 10 digits starting 6-9 gets 91 prefixed
    assert "length === 10" in source
    assert "[6-9]" in source
    assert "91${digits}" in source


def test_customer_token_is_not_in_localstorage():
    """Only a non-credential CSRF/expiry hint may survive in localStorage."""
    source = _strip_comments(CUSTOMER_AUTH.read_text())
    assert "sessionStorage" in source
    writes = [line.strip() for line in source.splitlines() if 'localStorage.setItem' in line]
    assert writes == ['window.localStorage.setItem( SESSION_HINT_KEY, JSON.stringify( hint ) );']
    assert 'window.sessionStorage.setItem( TOKEN_KEY, accessToken );' in source
    assert 'interface SessionHint { csrfToken: string; expiresAt: number; persistent: boolean; }' in source


def test_provisioner_preserves_a_manually_enabled_payment_flag():
    """Re-provisioning must not silently switch live payments back off."""
    source = (ROOT / "scripts/provision_secure_files_api.py").read_text()
    assert "keep_payment = current_payment_flag() if exists else False" in source
    assert "environment(payment_enabled=keep_payment)" in source


def _provisioner_module():
    """The provisioner, imported by path under a name of its own.

    Importing is safe and does not touch AWS: every client is built inside `iam()`,
    `lam()` and `api()` at call time, never at module scope.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "wecare_secure_files_provisioner", ROOT / "scripts/provision_secure_files_api.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_provisioner_requires_an_explicit_apply(monkeypatch):
    """A bare invocation must be a DRY RUN. This one is not a style preference.

    This script publishes a Lambda version and moves the production ``live`` alias. It used
    to do that with no flag, and on 2026-10-07 it did: run from a build loop whose own
    instruction said "DRY RUN ONLY", it put unmerged worktree code behind
    ``wecare-secure-files:live`` for about six minutes
    (``docs/execution/change-authority-matrix.md``).

    Asserted by DRIVING `main`, not by reading the argparse line, because what matters is
    the value each write step receives. No AWS call is made: every step is replaced with a
    recorder first.
    """
    module = _provisioner_module()
    seen = {}

    def _record(name, value):
        seen.setdefault(name, []).append(value)
        return f"{name}: recorded"

    monkeypatch.setattr(module, "package", lambda: b"zip")
    monkeypatch.setattr(module, "ensure_role", lambda dry: _record("role", dry))
    monkeypatch.setattr(module, "ensure_function", lambda _zip, dry: _record("function", dry))
    monkeypatch.setattr(module, "ensure_alias", lambda dry: _record("alias", dry))
    monkeypatch.setattr(module, "ensure_routes", lambda dry: [_record("routes", dry)])
    monkeypatch.setattr(module, "ensure_webhook_access", lambda dry: _record("webhook", dry))
    monkeypatch.setattr(module, "verify", lambda: 0)

    assert module.main([]) == 0
    assert set(seen) == {"role", "function", "alias", "routes", "webhook"}
    assert all(value is True for values in seen.values() for value in values), \
        "a bare invocation reached a write step with dry_run=False"

    seen.clear()
    assert module.main(["--dry-run"]) == 0
    assert all(value is True for values in seen.values() for value in values)

    # and the write path still exists, behind the flag that has to be typed
    seen.clear()
    assert module.main(["--apply"]) == 0
    assert all(value is False for values in seen.values() for value in values)

    # contradicting yourself is refused rather than resolved in either direction
    seen.clear()
    assert module.main(["--apply", "--dry-run"]) == 2
    assert seen == {}


# ── webhook-independence, so a missing subscription cannot strand a payment ────

def test_reconcile_only_accepts_a_captured_payment():
    """`authorized` means held, not taken. Granting on it hands over the file for a
    payment that can still fail.

    Asserts the PROPERTY, not one spelling of it. This used to pin the literal source text
    `payment.get("status") == "captured"`, which made it fail when that comparison was routed
    through `lambda_utils.payment_status.canonical` - a change that strictly widened what
    counts as captured (Razorpay saying `paid` now also grants) while leaving `authorized`
    denied, which is the thing this test actually cares about.

    A test pinned to a spelling blocks the correct fix and calls it a regression.
    """
    import sys

    shared = ROOT / "amplify" / "functions" / "shared"
    if str(shared) not in sys.path:
        sys.path.insert(0, str(shared))
    from lambda_utils import payment_status

    source = (FUNC_DIR / "razorpay_orders.py").read_text()
    # The decision must go through the shared vocabulary rather than a bare string compare.
    assert "payment_status.canonical" in source
    assert "payment_status.CAPTURED" in source

    # No raw comparison against the word. Checked on the AST, not the text: the comment
    # explaining why not to compare it raw necessarily contains the comparison, so a
    # substring search flags its own explanation. (This test learned that the hard way one
    # line above.)
    import ast

    raw_compares = [
        node.lineno
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Compare)
        and any(isinstance(operand, ast.Constant) and operand.value == "captured"
                for operand in (node.left, *node.comparators))
    ]
    assert not raw_compares, (
        f"raw comparison against 'captured' at line(s) {raw_compares}; that pins an access "
        f"decision to one provider spelling")

    # And the property itself: held funds never grant, received funds always do.
    assert payment_status.canonical("authorized") != payment_status.CAPTURED
    assert payment_status.canonical("created") != payment_status.CAPTURED
    assert payment_status.canonical("failed") != payment_status.CAPTURED
    assert payment_status.canonical("captured") == payment_status.CAPTURED
    assert payment_status.canonical("paid") == payment_status.CAPTURED


def test_reconcile_cannot_replay_a_spent_grant():
    """The fallback may only change whether a grant is payable, never unspend it."""
    source = (FUNC_DIR / "handler.py").read_text()
    body = source.split("def _reconcile_grant")[1].split("\ndef ")[0]
    assert 'grant.get("consumed")' in body
    assert "return False" in body
    # it is inert while payments are off
    assert "_payment_enabled()" in body
    # It no longer writes `paid` itself. It delegates to the single writer, which carries
    # the conditional guard - asserted in
    # test_confirm_with_razorpay_is_the_only_writer_of_paid. Keeping a second copy of the
    # write here is exactly what that test forbids.
    assert "_confirm_with_razorpay(" in body
    assert "paid = :true" not in body


def test_reconcile_verifies_ownership_before_paying():
    source = (FUNC_DIR / "handler.py").read_text()
    body = source.split("def _reconcile_grant")[1].split("\ndef ")[0]
    assert 'grant.get("fileId") != file_id' in body
    assert 'grant.get("ownerPhone") != identity["phone"]' in body


def test_redeem_after_reconcile_is_still_single_use():
    source = (FUNC_DIR / "handler.py").read_text()
    body = source.split("def _redeem_after_reconcile")[1].split("\ndef ")[0]
    assert "consumed = :false" in body
    assert "paid = :true" in body


def test_reconciliation_is_flagged_in_logs_for_visibility():
    """If this path ever fires, the webhook is not doing its job and that should be
    findable rather than silent."""
    source = (FUNC_DIR / "handler.py").read_text()
    assert "WEBHOOK_MAY_NOT_BE_SUBSCRIBED" in source
    # provenance is now an argument to the shared writer rather than an inline literal,
    # so both callers record which path granted without duplicating the write
    assert 'via="reconcile"' in source
    assert 'via: str = "webhook"' in source
    assert '":via": via' in source


# ── the u/ and d/ split ───────────────────────────────────────────────────────

def test_upload_and_delivery_prefixes_are_both_under_secure(mod):
    """Both must sit under secure/, because that is the prefix the edge denies.

    A delivery rendition outside secure/ would be publicly downloadable and would
    quietly defeat the entire paywall.
    """
    assert mod.UPLOAD_PREFIX == "secure/u/"
    assert mod.DELIVER_PREFIX == "secure/d/"
    assert mod.UPLOAD_PREFIX.startswith(mod.SECURE_PREFIX)
    assert mod.DELIVER_PREFIX.startswith(mod.SECURE_PREFIX)


def test_uploads_land_in_the_upload_prefix(mod):
    source = (FUNC_DIR / "handler.py").read_text()
    assert "key = UPLOAD_PREFIX + basename" in source


def test_only_pdf_and_image_are_deliverable(mod):
    """WhatsApp recipients can open these inline; everything else needs a link."""
    assert mod._classify_delivery("application/pdf", 1000) == "pdf"
    assert mod._classify_delivery("image/jpeg", 1000) == "image"
    assert mod._classify_delivery("image/png", 1000) == "image"
    # charset suffixes must not defeat the match
    assert mod._classify_delivery("application/pdf; charset=binary", 1000) == "pdf"
    # anything else falls back to a link rather than arriving unopenable
    for ct in ("text/plain", "application/zip", "application/msword", "", "video/mp4"):
        assert mod._classify_delivery(ct, 1000) == "link"


def test_oversize_files_fall_back_to_a_link(mod):
    """Meta caps images at 5MB and documents at 100MB. Over that, send a link."""
    assert mod._classify_delivery("image/png", mod.MAX_IMAGE_BYTES + 1) == "link"
    assert mod._classify_delivery("image/png", mod.MAX_IMAGE_BYTES) == "image"
    assert mod._classify_delivery("application/pdf", mod.MAX_DOCUMENT_BYTES + 1) == "link"
    assert mod._classify_delivery("application/pdf", mod.MAX_DOCUMENT_BYTES) == "pdf"


def test_delivery_type_is_judged_on_s3_not_the_browser():
    """The browser's Content-Type is a hint; a wrong one would only surface when a
    paying customer received something unopenable."""
    source = (FUNC_DIR / "handler.py").read_text()
    body = source.split("def _upload_confirm")[1].split("\ndef ")[0]
    assert 'head.get("ContentType")' in body
    assert "_classify_delivery(content_type, size)" in body


def test_a_failed_delivery_copy_downgrades_rather_than_failing_the_upload():
    source = (FUNC_DIR / "handler.py").read_text()
    body = source.split("def _upload_confirm")[1].split("\ndef ")[0]
    assert 'deliverable, delivery_key = "link", ""' in body
    assert "delivery_copy_failed" in body


# ── WhatsApp template delivery ────────────────────────────────────────────────

WA_DELIVERY = FUNC_DIR / "whatsapp_delivery.py"


def test_delivery_uses_approved_templates():
    """Both defaults must name a template Meta has APPROVED, so a send never depends on
    an approval that has not landed.

    wd_file_delivery replaced 01_wecare_doc once Meta approved it; 01_wecare_doc remains
    a valid rollback value for WA_DOC_TEMPLATE.
    """
    source = WA_DELIVERY.read_text()
    assert '"WA_PAY_TEMPLATE", "wecare_pay"' in source
    assert '"WA_DOC_TEMPLATE", "wd_file_delivery"' in source
    # and the parameterised template must be declared as such, or Meta rejects the send
    assert '"wd_file_delivery"' in source.split("TEMPLATES_WITH_BODY_VARS")[1][:80]


def test_the_document_goes_by_media_id_not_a_url():
    """The secure/ prefix is refused at the edge, so there is no URL to give Meta.

    Passing bytes inline as base64 would also cap near 4.4MB inside a synchronous
    invoke payload, well under the 100MB Meta accepts.
    """
    source = WA_DELIVERY.read_text()
    body = source.split("def upload_to_meta")[1].split("\ndef ")[0]
    assert '"s3Key": delivery_key' in body
    assert '"s3Bucket": BUCKET' in body
    assert "fileData" not in body
    # the header carries the media id
    send = source.split("def send_document")[1].split("\ndef ")[0]
    assert '"id": media_id' in send


def test_delivery_reads_the_d_rendition_not_the_original():
    """s3Key is the original of any type; deliveryKey is the openable rendition."""
    source = WA_DELIVERY.read_text()
    body = source.split("def upload_to_meta")[1].split("\ndef ")[0]
    assert 'file_row.get("deliveryKey")' in body
    assert 'file_row.get("s3Key")' not in body


def test_payment_request_is_digital_goods_so_no_address_is_collected():
    """physical-goods makes WhatsApp demand a delivery address, which is nonsense for
    a file and was a real bug in the invoice flow."""
    source = WA_DELIVERY.read_text()
    assert '"type": "digital-goods"' in source
    # the dict KEY, not the word: the comment above it explains why the key is absent
    assert '"shipping_info"' not in source
    assert "'shipping_info'" not in source


def test_payment_configuration_is_not_hardcoded():
    """outbound-whatsapp resolves it per phone number; hardcoding would silently
    diverge when that mapping changes."""
    source = WA_DELIVERY.read_text()
    assert "WECAREDIGITAL" not in source


def test_whatsapp_pay_sends_only_to_the_verified_number():
    """Taking a number from the request body would turn this route into a way to send
    WhatsApp messages to arbitrary people."""
    source = (FUNC_DIR / "handler.py").read_text()
    body = source.split("def _send_whatsapp_payment")[1].split("\ndef ")[0]
    assert 'phone=identity["phone"]' in body
    # never from the request
    assert "json.loads(event" not in body
    assert "_owned_active_file" in body
    assert "_payment_enabled()" in body


def test_grant_is_written_before_the_send():
    """If the send fails the grant just expires; the reverse order would let a customer
    pay against a grant that does not exist."""
    source = (FUNC_DIR / "handler.py").read_text()
    body = source.split("def _send_whatsapp_payment")[1].split("\ndef ")[0]
    assert body.index("put_item") < body.index("send_payment_request(")


def test_delivery_requires_a_paid_grant_and_matching_owner():
    source = (FUNC_DIR / "handler.py").read_text()
    body = source.split("def deliver_over_whatsapp")[1].split("\ndef ")[0]
    assert 'not grant.get("paid")' in body
    assert 'item.get("ownerPhone") != grant.get("ownerPhone")' in body
    assert 'item.get("status") != "active"' in body


def test_internal_dispatch_is_unreachable_over_http():
    """It requires the ABSENCE of requestContext, which API Gateway always supplies."""
    source = (FUNC_DIR / "handler.py").read_text()
    assert 'not event.get("requestContext")' in source
    assert '"deliverOverWhatsApp"' in source


def test_the_webhook_cannot_trigger_a_send_directly():
    """Delivery is no longer the webhook's decision.

    It used to read the grant, see `channel == 'whatsapp'`, and dispatch the send itself.
    That put two trusted judgements in the webhook: whether payment happened, and who to
    send to. Both now live in `secure-files`, downstream of a Razorpay API confirmation,
    so the webhook cannot cause a file to be sent to anyone.
    """
    assert "deliverOverWhatsApp" not in WEBHOOK_SOURCE
    assert "channel" not in WEBHOOK_SOURCE.split(
        "def _dispatch_download_grant_confirmation", 1
    )[1].split("\ndef ", 1)[0]
    # still async, so a slow confirmation cannot make Razorpay retry the whole webhook
    assert "'confirmAndDeliver'" in WEBHOOK_SOURCE
    assert "'Event'" in WEBHOOK_SOURCE


def test_media_source_buckets_are_an_allowlist():
    """A free s3Bucket parameter would hand every caller of this widely-invoked
    function a read-any-object primitive."""
    source = (
        ROOT / "amplify/functions/messaging/whatsapp-business-api/handler.py"
    ).read_text()
    assert "MEDIA_SOURCE_BUCKETS" in source
    assert "s3_bucket not in MEDIA_SOURCE_BUCKETS" in source


# ── resolutions for the ranked improvements ───────────────────────────────────

AUTH_HANDLER = ROOT / "amplify/functions/auth/customer-whatsapp-auth/handler.py"


def test_otp_probe_limit_reads_username_from_the_event_root():
    """`userName` is top-level on a Cognito trigger event, not inside `request`.

    Reading it from `request` silently yielded an empty string, the budget check was
    skipped, and eight consecutive probes all got the reveal. Verified live after the
    fix: reveal for five, then 'unknown'.
    """
    source = AUTH_HANDLER.read_text()
    body = source.split("def _create_auth_challenge")[1].split("\ndef ")[0]
    assert 'event.get("userName")' in body
    assert 'request.get("userName")' not in body


def test_otp_probe_limit_fails_open():
    """A counter that cannot be read must not lock a paying customer out of their files.

    Failing open risks not enforcing the enumeration budget during a DynamoDB problem,
    which is far smaller harm than refusing legitimate verification.
    """
    source = AUTH_HANDLER.read_text()
    body = source.split("def _probe_budget_exhausted")[1].split("\ndef ")[0]
    assert "return False" in body
    assert "except Exception" in body


def test_exhausted_probe_budget_stops_revealing(mod=None):
    """Past the budget the answer must stop distinguishing registered from not."""
    source = AUTH_HANDLER.read_text()
    assert '"registered"] = "unknown"' in source
    assert "_probe_budget_exhausted" in source


def test_whatsapp_link_ttl_is_longer_than_the_web_one(mod):
    """A person taps a message link when they read it, not within 60 seconds. Sending a
    URL that has already expired is worse than useless once they have paid."""
    assert mod.WHATSAPP_LINK_TTL > mod.DOWNLOAD_URL_TTL
    assert mod.DOWNLOAD_URL_TTL <= 120
    # SigV4 with temporary Lambda credentials cannot outlive the role session
    assert mod.WHATSAPP_LINK_TTL <= 24 * 3600


def test_link_delivery_uses_the_long_ttl(mod):
    source = (FUNC_DIR / "handler.py").read_text()
    body = source.split("def deliver_over_whatsapp")[1].split("\ndef ")[0]
    assert "ttl=WHATSAPP_LINK_TTL" in body


def test_delivery_outcome_is_recorded_on_the_grant():
    """Without this a failed send was only a log line while the customer had paid, so
    nothing could answer "who is owed a file"."""
    source = (FUNC_DIR / "handler.py").read_text()
    body = source.split("def deliver_over_whatsapp")[1].split("\ndef ")[0]
    for attr in ("delivered", "deliveryDetail", "deliveryAttempts", "deliveryAttemptedAt"):
        assert attr in body


def test_reconciliation_ignores_probe_rows_and_web_grants():
    """The grants table doubles as the OTP probe counter, and web grants are collected
    by redeem rather than owed a send."""
    source = (ROOT / "scripts/reconcile_file_deliveries.py").read_text()
    assert 'startswith("otpprobe#")' in source
    assert '!= "whatsapp"' in source
    # consumed must NOT discharge a WhatsApp delivery
    assert 'item.get("consumed")' not in source


def test_delivery_template_body_params_follow_the_template_name():
    """Sending body params to a template without placeholders is a Meta parameter
    mismatch, so the two must move together."""
    source = (FUNC_DIR / "whatsapp_delivery.py").read_text()
    assert "TEMPLATES_WITH_BODY_VARS" in source
    assert "DOC_TEMPLATE in TEMPLATES_WITH_BODY_VARS" in source
    # wd_file_delivery was APPROVED 2026-09-25 and is now the default; 01_wecare_doc
    # remains a safe rollback because the parameter shape follows the template name.
    assert '"WA_DOC_TEMPLATE", "wd_file_delivery"' in source


def test_resumable_upload_sends_appsecret_proof():
    """Meta refuses server-side calls without it, so template media headers could never
    be created. Every other Graph call in that file computes it; this one did not."""
    source = (
        ROOT / "amplify/functions/messaging/whatsapp-business-api/handler.py"
    ).read_text()
    body = source.split("def _meta_resumable_upload")[1].split("\ndef ")[0]
    assert "appsecret_proof" in body
