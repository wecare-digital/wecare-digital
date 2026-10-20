"""
Invoice Engine Lambda Function

Purpose: Unified invoice service for all 3 payment entry points
- Create invoices from payments
- Generate invoice image (PNG) and PDF
- Internal GST-compliant invoice sequencing
- Admin CRUD operations

DynamoDB Tables:
- stack-wecare-digital-InvoicesTable
- stack-wecare-digital-InvoiceItemsTable
- stack-wecare-digital-InvoiceSequenceTable
- stack-wecare-digital-InvoiceAssetsTable
- stack-wecare-digital-InvoiceDeliveryLogTable

S3 Bucket: wecare-digital-get  (was app.wecare.digital until it was deleted 2026-09-28)
Prefix: secure/stack/invoices/  (GATED - moved off the public `o/` root 2026-09-30, because a
        rendered invoice carries the customer's name, address, amount and GST breakdown.
        Rendered invoices are handed out as short-lived presigned URLs; WhatsApp delivery does
        not use a URL at all, it uploads the bytes to Meta.)
"""

import os
import json
import uuid
import time
import logging
import boto3
import io
from dataclasses import dataclass
from typing import Dict, Any, Optional, List, Tuple
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from lambda_utils.response import cors_response, cors_headers, options_response, extract_origin
from lambda_utils.audit import record_audit
from lambda_utils.logging import get_logger
from lambda_utils.privacy import mask_phone  # a full number must never reach CloudWatch
from lambda_utils import media_paths, shared_tables
# Aliased: `payment_status` is a local parameter in the invoice renderers below, holding the raw
# stored word. `pay_status` is the module that says what the word means.
from lambda_utils import payment_status as pay_status
# A1 — whether this business can currently take a WhatsApp payment, PROVEN against a live Meta
# read and never against a constant in this file. Note the package: `payment_readiness` lives at
# lambda_utils/payment_readiness.py, not under `lambda_utils.ecommerce`.
from lambda_utils import payment_readiness
# Attribution, not mechanics: which surface the order was placed from. One module owns the two
# literals and the one total coercion, so the three render sites below cannot disagree about what
# `channel` means - the same discipline `pay_status` applies to payment words.
from lambda_utils.ecommerce import order_channel, business_identity, checkout_pricing
# Identity reservation for a native WhatsApp collection, and the key prefixes it reserves on.
# `send_payment_link` reserves BEFORE it sends, so a retried send re-sends the same
# `reference_id` instead of minting a second one for one invoice.
from lambda_utils.ecommerce import order_keys, wa_payment_request
# The fulfilment-status vocabulary and legal transitions for a WhatsApp order_status update. A
# SEPARATE lifecycle from the payment's money state — this is what the merchant did (shipped,
# completed), not what the money did. One home for the rules `send_order_status` validates.
from lambda_utils.ecommerce import wa_order_status
# The one, always-on discount: Delight (0.5% up to ₹50), a fixed owner policy computed standalone.
# There is no coupon system and no gift-card system any more — this handler asks `default_coupon`
# for the one figure and writes it onto the invoice like any other line. Nothing here reads a
# table, holds a reservation, or refuses: Delight is pure arithmetic over the collection.
from lambda_utils.ecommerce import default_coupon
from lambda_utils.integrations import razorpay_refund
# The ONE address authority. Imported so this handler reads the canonical `checkoutDeliveryAddress`
# Map a contact carries (with a legacy flat-column fallback) rather than re-deriving the address
# shape here — the same convergence `customer_orders.update_profile` and the WhatsApp Address
# Message writer are on.
from lambda_utils.ecommerce import contact_address, payment_address
# The PUBLIC customer id, and the validator that keeps a junk one off a tax invoice. Only
# `is_customer_uuid` and `ATTRIBUTE` are used here: the engine NEVER mints one, the same rule
# that stops a renderer minting an invoice number.
from lambda_utils.identity import customer_uuid

logger = get_logger(__name__)

IST_OFFSET = 5 * 3600 + 30 * 60  # UTC+5:30

def _ist_strftime(fmt: str, epoch) -> str:
    """Format epoch timestamp in IST (UTC+5:30)."""
    return time.strftime(fmt, time.gmtime(int(epoch) + IST_OFFSET))


def _money_display(value) -> str:
    """A rupee figure as a STRING, for a money value crossing a Lambda or HTTP boundary.

    Deliberately not a float. Every float rupee value in this tree began as a display conversion
    that then got compared, summed or stored - including an invoice match on
    `abs(inv_total - amount_rupees) < 0.02`. A string cannot be arithmetic'd by accident, which
    is the point.

    Falls back to the stored repr for a figure that is not exactly expressible in paise, because
    this is a display field: refusing here would fail a response over a value nothing compares.
    """
    try:
        return pay_status.rupees_str(wa_payment_request.exact_paise(value))
    except Exception:  # noqa: BLE001
        return str(value if value is not None else 0)

dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
# Transactions below already contain DynamoDB AttributeValues. A resource client's
# input transformer would serialize them again, turning string keys into maps.
dynamodb_transaction_client = boto3.client('dynamodb', region_name='us-east-1')
s3 = boto3.client('s3', region_name='us-east-1')
lambda_client = boto3.client('lambda', region_name='us-east-1')

INVOICES_TABLE = shared_tables.invoices_table_name()
INVOICE_ITEMS_TABLE = shared_tables.invoice_items_table_name()
INVOICE_SEQ_TABLE = shared_tables.invoice_sequence_table_name()
INVOICE_ASSETS_TABLE = shared_tables.invoice_assets_table_name()
INVOICE_DELIVERY_TABLE = shared_tables.invoice_delivery_table_name()
PAYMENTS_TABLE = os.environ.get('PAYMENTS_TABLE', 'stack-wecare-digital-PaymentsTable')
REFUND_CASES_TABLE = shared_tables.flow_submissions_table_name()
CONTACTS_TABLE = shared_tables.contacts_table_name()
SYSTEM_CONFIG_TABLE = os.environ.get('SYSTEM_CONFIG_TABLE', 'stack-wecare-digital-SystemConfigTable')
MEDIA_BUCKET = os.environ.get('MEDIA_BUCKET', media_paths.BUCKET)

# ── the two money tables this engine now reserves identity in ──
# Declared here rather than relied on from a code default, so the manifest describes the
# dependency instead of the default hiding it. `reserve` writes both from this function, which
# has never touched either before.
PAYMENT_ATTEMPTS_TABLE = shared_tables.payment_attempts_table_name()
COMMERCE_KEYS_TABLE = shared_tables.commerce_keys_table_name()

#: The approved WhatsApp payment template, with ONE home.
#:
#: A payment travels in `wecarepay_wa` carrying `order_details`, or it does not travel. Env-read
#: so a pre-flight checks the same string the send uses - a gate that checks a different string
#: from the one the send uses can pass while the send fails - and so the value can change without
#: a code deploy if Meta's template registration ever needs it to.
WA_PAY_TEMPLATE = os.environ.get('WA_PAY_TEMPLATE', 'wecarepay_wa')

#: The Meta payment configuration this deployment can PROVE, compared against a live Meta read.
#:
#: EMPTY BY DEFAULT, and the previous literal default is gone. The docstring here used to argue
#: FOR a default - that "the long-standing empty-string path must keep working" because both
#: routed callers can legitimately supply empty, and that a required-with-no-default field would
#: turn a send that works today into a 409. That argument is now wrong, and inverted on purpose:
#: requirements statement 9 forbids a fallback configuration name, and a 409 on an unconfigured
#: deployment is the INTENDED outcome rather than a regression. A send that "works" by falling
#: back to an unproven constant is the defect, not the behaviour to preserve.
#:
#: With the variable unset the resolution chain below yields `''`, and the failure is triply
#: closed: `payment_readiness.evaluate` reports CONFIGURATION_UNVERIFIED on an empty
#: configuration name, `build_request` refuses WA_PAY_CONFIG_NAME_REQUIRED independently, and
#: `payment_attempt.build` refuses an empty configuration outright.
#:
#: This is still NOT a resolution of which configuration a SENDER may use. That stays wholly
#: inside `outbound-whatsapp._build_payment_settings` and the one resolver it shares with the
#: boundary gate. It is an EXPECTATION this handler compares against, and it can never enable a
#: payment - only a successful live readback can.
#:
#: The key name is `WA_PAY_CONFIG_NAME` here and `EXPECTED_CONFIGURATION_NAME` on
#: `wecare-outbound-whatsapp`; `EXPECTED_CONFIGURATION_NAME` is read FIRST so one key can carry
#: the expectation across both gates, with the older key kept as the fallback so no live
#: environment has to change for this to work. A test pins the two manifest values equal, because
#: the drift mode is specific and bad: this handler would prove and reserve against X, send
#: `payment_configuration: X`, and the boundary gate would then refuse because its expectation
#: is Y - a guaranteed reserve-then-refuse on every invoice collection.
WA_PAY_CONFIG_NAME = (os.environ.get('EXPECTED_CONFIGURATION_NAME', '')
                      or os.environ.get('WA_PAY_CONFIG_NAME', ''))

#: The authoritative Razorpay merchant id, as resolved by the owner and recorded in
#: `payment_readiness`. Required on the reservation because "we did not compare the merchant id"
#: must never read the same as "the merchant id matched".
#:
#: EMPTY BY DEFAULT for the same reason as above: `evaluate` blocks on an empty
#: `expected_provider_mid` and `build_request` refuses WA_PAY_PROVIDER_MID_REQUIRED, so an
#: unconfigured deployment refuses instead of proving a merchant id it never compared.
WA_PAY_PROVIDER_MID = os.environ.get('EXPECTED_PROVIDER_MID', '')

#: A1 — the readiness gate's vocabulary. Module scope, not inside the function: a frozenset
#: rebuilt per call on a money path is not what belongs in a request handler.
#:
#: The two states that mean "ask again later". Everything else means a human must act.
_READINESS_TRANSIENT = frozenset({payment_readiness.META_UNAVAILABLE,
                                  payment_readiness.RAZORPAY_UNAVAILABLE})

#: This handler's refusal code for a blocking readiness verdict. Deliberately NOT added to
#: `wa_payment_request.REFUSAL_MESSAGES`: it is not a `PaymentRequestRefused`, and putting it
#: there would pull readiness vocabulary into the reservation module, which holds none.
WA_PAY_NOT_READY = 'WA_PAY_NOT_READY'

#: A configuration this deployment cannot PROVE with a Razorpay merchant id. `WECAREUPI` is a
#: `upi` configuration with a VPA and no MID, so `evaluate` - which compares a merchant id and
#: nothing else - could only ever report it as CONFIGURATION_UNVERIFIED or RAZORPAY_MID_MISMATCH,
#: which read as "something is misconfigured" and send an operator looking for a configuration
#: error that does not exist. Refused by name instead, with a cause, before the provider read.
WA_PAY_CONFIG_NOT_PROVABLE = 'WA_PAY_CONFIG_NOT_PROVABLE'

#: The function that holds the Meta token and owns the Graph reads. A LITERAL, not an env var:
#: it is a function name rather than a Meta-registered string, so the "one home, env-read"
#: argument that justifies `WA_PAY_TEMPLATE` above does not transfer, and a stale env value
#: would surface as META_UNAVAILABLE - the hardest state on this path to tell from an outage.
_PAYMENT_READ_FUNCTION = 'wecare-whatsapp-business-api:live'

# Keys in this handler are rooted, never bare. See lambda_utils/media_paths: the merge moved
# `<X>` to `o/<X>`, so an un-rooted key read one level above the data and returned NoSuchKey —
# which is exactly what happened to the logo and the font. Those shared assets stay PUBLIC and
# are still composed with `media_paths.public` at their call sites.
#
# The invoice output does not. A rendered invoice carries the customer's name, address, the
# amount and the GST breakdown, and `o/` is served by CloudFront with no authentication — so a
# public key here is an unlisted-but-public disclosure: safe from enumeration, not safe once a
# URL leaks. It moved to the gated root, and the timing is the reason it was cheap: measured at
# the time of the change, `o/stack/invoices/` held **0 objects** and `InvoicesTable` held **0
# rows**, so there was nothing to migrate. Once an invoice URL has been sent, it cannot be
# retracted — the same argument media_paths records for the 61 approved WhatsApp template URLs.
#
# Delivery is unaffected: `send_invoice_whatsapp` passes `mediaFile: s3_key` to
# outbound-whatsapp, which reads the object and uploads the bytes to Meta. Meta never fetches
# an invoice by URL, so the gated prefix costs nothing on the path that matters.
INVOICE_PREFIX = media_paths.secure('stack/invoices/')
CDN_DOMAIN = os.environ.get('CDN_DOMAIN', media_paths.CDN_DOMAIN)


def _transparent_receipt_enabled() -> bool:
    """Is the approved transparent torn-paper receipt appearance switched on?

    Default ON following the owner's explicit approval of invoice-sample-real-v6.png.
    Set RECEIPT_TRANSPARENT_BG=false only to restore the legacy appearance.
    Read at call time so warm environments do not cache a layout decision.
    """
    return os.environ.get('RECEIPT_TRANSPARENT_BG', 'true').strip().lower() in (
        '1', 'true', 'yes', 'on')


def _flatten_onto_white(png_img):
    """Drop an RGBA receipt onto white, preserving what the eye sees.

    PIL's `convert('RGB')` does NOT composite — it discards the alpha band and keeps
    the underlying RGB, which for a pixel created as (0, 0, 0, 0) is BLACK. So
    converting a transparent receipt straight to RGB gives the PDF a black border
    instead of a white page. Composite against white using the alpha as the mask.
    """
    from PIL import Image as _PILImage

    if png_img.mode in ('RGBA', 'LA') or (
            png_img.mode == 'P' and 'transparency' in png_img.info):
        rgba = png_img.convert('RGBA')
        flat = _PILImage.new('RGB', rgba.size, (255, 255, 255))
        flat.paste(rgba, (0, 0), rgba)
        return flat
    return png_img.convert('RGB')

# Module-level origin for CORS (set per-invocation in handler)
origin = ''

#: The caller's Cognito `sub` for this invocation, set by `handler` alongside `origin` and
#: read only by `_audit_actor`. Module-level for the same reason `origin` is: the route
#: functions below take `(id, body, request_id)` and threading an actor through all of
#: them to reach two audit calls would be a wider diff than the fix.
_actor_sub = ''


def _audit_actor() -> str:
    """Who to record for an audited refusal. The token's `sub`, never a body field."""
    return _actor_sub or 'unknown'

# Company details for invoice
# GSTIN/PAN appear on issued tax invoices. The PAN is embedded in the GSTIN at
# characters 3-12, so the two MUST stay consistent:
#   19 AAFFW7196L 1 Z 8  ->  state 19 (West Bengal), PAN AAFFW7196L
# Env vars allow override without a redeploy.
COMPANY = {
    **business_identity.invoice_identity(),
    'logo_s3_key': media_paths.public('stream/media/m/wecare-digital.png'),
}


def _load_logo_bytes() -> Optional[bytes]:
    """Load company logo from S3 with /tmp cache for Lambda warm starts."""
    cache_path = '/tmp/_logo_cache.png'
    try:
        with open(cache_path, 'rb') as f:
            return f.read()
    except FileNotFoundError:
        pass
    try:
        obj = s3.get_object(Bucket=MEDIA_BUCKET, Key=COMPANY['logo_s3_key'])
        data = obj['Body'].read()
        try:
            with open(cache_path, 'wb') as f:
                f.write(data)
        except Exception as _e:
            logger.debug(f"Logo cache write failed: {_e}")
        return data
    except Exception as e:
        logger.warning(f"Logo load error: {e}")
        return None


def _load_s3_image(key: str):
    """Load an image from S3 as PIL Image (RGBA) with /tmp cache."""
    import hashlib
    # Defensive: this is the shared read path for every image in the invoice, so rooting
    # here means a caller passing a legacy un-rooted key still finds the object.
    key = media_paths.canonical(key)
    cache_path = f"/tmp/_s3img_{hashlib.md5(key.encode()).hexdigest()}.png"
    try:
        from PIL import Image as PILImage
        return PILImage.open(cache_path).convert('RGBA')
    except Exception as _e:
        logger.debug(f"S3 image cache miss: {_e}")
    try:
        from PIL import Image as PILImage
        obj = s3.get_object(Bucket=MEDIA_BUCKET, Key=key)
        data = obj['Body'].read()
        img = PILImage.open(io.BytesIO(data)).convert('RGBA')
        try:
            img.save(cache_path, 'PNG')
        except Exception as _e:
            logger.debug(f"S3 image cache write failed: {_e}")
        return img
    except Exception as e:
        logger.warning(f"S3 image load error ({key}): {e}")
        return None


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Route invoice engine requests."""
    request_id = context.aws_request_id if context else 'local'
    global origin
    origin = extract_origin(event)
    method = event.get('requestContext', {}).get('http', {}).get('method', 'GET')

    from lambda_utils.middleware import require_auth
    # Viewer on reads, Admin on anything that writes. The read floor is stated explicitly
    # rather than left as None: `require_auth` no longer defaults an ungrouped principal
    # to Viewer, so `required_role=None` would have nothing to check.
    required_role = 'Admin' if method in ('POST', 'PUT', 'DELETE') else 'Viewer'
    _auth = require_auth(event, required_role=required_role)
    if _auth is not None:
        return _auth

    global _actor_sub
    _auth_info = event.get('_auth') or {}
    _actor_sub = str((_auth_info.get('attributes') or {}).get('sub')
                     or _auth_info.get('username') or '')

    path = event.get('rawPath', event.get('path', ''))
    params = event.get('queryStringParameters') or {}
    path_params = event.get('pathParameters') or {}

    logger.info(json.dumps({'event': 'invoice_engine', 'method': method, 'path': path, 'requestId': request_id}))

    try:
        body = json.loads(event.get('body', '{}')) if event.get('body') else {}
    except (json.JSONDecodeError, TypeError, ValueError):
        body = {}

    try:
        # POST /invoices with _action=initiate-refund — irreversible provider command.
        # Uses the existing authenticated invoice collection route so shipping this dormant
        # capability does not create an unaudited API-Gateway route. The feature flag is false
        # by default and the function itself refuses any Lambda-to-Lambda call with no staff actor.
        if method == 'POST' and body.get('_action') == 'initiate-refund':
            return initiate_full_refund(
                body.get('invoiceId', ''), body, request_id, auth=event.get('_auth'))

        # POST /invoices with _action=initiate-partial-refund — irreversible provider command for a
        # browser-proposed, server-capped partial amount. Shares the same authenticated route,
        # feature flag and no-internal-actor refusal as the full-refund action above.
        if method == 'POST' and body.get('_action') == 'initiate-partial-refund':
            return initiate_partial_refund(
                body.get('invoiceId', ''), body, request_id, auth=event.get('_auth'))

        # POST /invoices with _action=clear-all — body-based trigger for cleanup via existing route
        if method == 'POST' and body.get('_action') == 'clear-all':
            return clear_all_invoice_data(request_id)

        # POST /invoices/from-payment — create from payment ID (check BEFORE generic POST)
        if method == 'POST' and 'from-payment' in path:
            return create_invoice_from_payment(body, request_id)

        # POST /invoices/send-pending-by-phone — find & send all pending invoices for a phone
        if method == 'POST' and 'send-pending-by-phone' in path:
            return send_pending_by_phone(body, request_id)

        # POST /invoices/next-sequence — get next invoice number (admin)
        if method == 'POST' and 'next-sequence' in path:
            return get_next_sequence_preview(body, request_id)

        # POST /invoices/{id}/generate-image
        if method == 'POST' and 'generate-image' in path:
            inv_id = path_params.get('invoiceId') or body.get('invoiceId')
            return generate_invoice_image(inv_id, request_id)

        # PDF invoice generation is retired. Keep the route fail-closed while API
        # infrastructure catches up, so an old client cannot silently create a new PDF.
        if method == 'POST' and 'generate-pdf' in path:
            return _resp(410, {
                'error': 'Invoice PDF generation is retired. Use the invoice image.',
                'code': 'INVOICE_IMAGE_ONLY',
            })

        # POST /invoices/{id}/send-whatsapp
        if method == 'POST' and 'send-whatsapp' in path:
            inv_id = path_params.get('invoiceId') or body.get('invoiceId')
            phone = body.get('toWhatsAppNumber')
            phone_number_id = body.get('phoneNumberId')
            # `force` is threaded from the body because the function has no `body` in scope.
            # Absent means False, which is the idempotent direction.
            return send_invoice_whatsapp(inv_id, phone, phone_number_id, request_id,
                                         force=bool(body.get('force')))

        # POST /invoices/{id}/send-payment-link — send WhatsApp interactive payment message
        if method == 'POST' and 'send-payment-link' in path:
            inv_id = path_params.get('invoiceId') or body.get('invoiceId')
            phone_number_id = body.get('phoneNumberId')
            payment_configuration = body.get('paymentConfiguration', '')
            return send_payment_link(inv_id, phone_number_id, payment_configuration, request_id)

        # POST /invoices/{id}/order-status — send a WhatsApp fulfilment status update
        # (shipped/completed/…) for a PAID order. Checked BEFORE 'cancel' because the two share
        # no path token and this one is the more specific route.
        if method == 'POST' and 'order-status' in path:
            inv_id = path_params.get('invoiceId') or body.get('invoiceId')
            return send_order_status(
                inv_id, body.get('orderStatus', ''), body.get('description', ''),
                body.get('phoneNumberId', ''), request_id)

        # POST /invoices/{id}/cancel — cancel/void an invoice
        if method == 'POST' and 'cancel' in path:
            inv_id = path_params.get('invoiceId') or body.get('invoiceId')
            reason = body.get('reason', '')
            return cancel_invoice(inv_id, reason, request_id)

        # POST /invoices/{id}/remark — add remark/refund/credit note
        if method == 'POST' and 'remark' in path:
            inv_id = path_params.get('invoiceId') or body.get('invoiceId')
            # `_auth` is what `require_auth` attached above, and it is the ONLY identity
            # `add_remark` will accept. The author used to come off the request body, so a
            # refund note could be signed with anyone's name by the caller who wrote it.
            # `require_auth` skips an internal Lambda-to-Lambda invoke, so this is absent on
            # that path and `add_remark` labels it server-side rather than trusting the body.
            return add_remark(inv_id, body, request_id, auth=event.get('_auth'))

        # DELETE /invoices/clear-all — wipe all invoice-related tables (admin cleanup)
        if method == 'DELETE' and 'clear-all' in path:
            return clear_all_invoice_data(request_id)

        # POST /invoices/clear-all — alternative POST route for clear-all (when DELETE not in API GW)
        if method == 'POST' and 'clear-all' in path:
            return clear_all_invoice_data(request_id)

        # DELETE /invoices/{id} — hard delete invoice + adjust sequence
        if method == 'DELETE' and path_params.get('invoiceId'):
            return delete_invoice(path_params['invoiceId'], body, request_id)

        # POST /invoices — create invoice (generic, must be LAST POST check)
        if method == 'POST':
            return create_invoice(body, request_id)

        # PUT /invoices/{id} — update invoice
        if method == 'PUT' and path_params.get('invoiceId'):
            return update_invoice(path_params['invoiceId'], body, request_id)

        # GET /invoices/{id}/delivery-log
        if method == 'GET' and 'delivery-log' in path:
            inv_id = path_params.get('invoiceId')
            return get_delivery_log(inv_id, request_id)

        # GET /invoices — list
        if method == 'GET' and not path_params.get('invoiceId'):
            return list_invoices(params, request_id)

        # GET /invoices/{id} — get single
        if method == 'GET' and path_params.get('invoiceId'):
            return get_invoice(path_params['invoiceId'], request_id)

        return _resp(405, {'error': 'Method not allowed'})

    except Exception as e:
        logger.error(json.dumps({'event': 'invoice_engine_error', 'error': str(e), 'requestId': request_id}))
        return _resp(500, {'error': str(e)})


# ─── Invoice Sequencing (GST-compliant, internal only) ───

class InvoiceSequenceUnavailable(RuntimeError):
    """The GST invoice sequence could not be advanced.

    Raised instead of returning a substitute number. See _get_next_invoice_number.
    """


#: How many candidates `_get_next_invoice_number` will walk past before refusing.
#:
#: The cap is the difference between self-healing and wedged. A counter that has been reset sits
#: BELOW numbers that are already out, so the first candidates it offers are all reserved; the
#: loop walks past them and the series continues from the true floor. Refusing on the first
#: collision instead would leave every subsequent invoice failing until an operator ran the
#: reconciliation script. The cap stops the other failure mode - a loop walking thousands of
#: numbers inside one API request - and 25 covers the observed drift (a reset to 0 against four
#: issued numbers) with a wide margin, while `scripts/reconcile_invoice_sequence.py` is the
#: correct tool for a larger gap.
_INVOICE_NUMBER_ATTEMPTS = 25


def _current_fy() -> str:
    """The Indian financial year as `YYYY-YYYY`, which starts in April."""
    now = time.localtime()
    year = now.tm_year
    return f"{year}-{year+1}" if now.tm_mon >= 4 else f"{year-1}-{year}"


def _format_invoice_number(prefix: str, fy: str, seq: int) -> str:
    """`WD/2627/00001` - the one place the GST number's shape is written."""
    fy_short = fy.replace('20', '').replace('-', '')
    return f"{prefix}/{fy_short}/{seq:05d}"


def _get_next_invoice_number(fy: str = None) -> str:
    """Generate next sequential invoice number. Format: WD/FY/NNNNN

    Raises InvoiceSequenceUnavailable if a number cannot be both advanced AND reserved.

    This used to fall back to `WD-PAY-TEMP-<uuid>`, which put a non-sequential
    number into the GST series. Under Rule 46(b) an invoice number has to be part
    of a consecutive series for the financial year; a uuid is not, so the fallback
    did not produce a degraded invoice, it produced an invalid one - and it did so
    silently, at exactly the moment the system had lost the ability to tell what
    the next number should be. Nothing downstream could distinguish it either,
    because it was returned as an ordinary success.

    WHY THE COUNTER ALONE IS NOT ENOUGH
    -----------------------------------
    The `update_item` below is atomic, so two concurrent callers cannot read the
    same `last_seq`. What it cannot do is remember what it gave out: the counter
    is one row on `InvoiceSequenceTable`, `clear_all_invoice_data` wipes that
    table, and a wiped counter restarts at 1. That is not a hypothesis - it is
    how `WD/2627/00001` reached two different customers eight days apart.

    So the number is not the counter's output any more; it is the counter's
    output CONFIRMED by an immutable reservation row (`INVOICENO#<number>` on the
    commerce-keys table, which that wipe does not touch). The reservation is the
    last thing that happens before the number is returned, so no caller can hold
    a number storage has not committed to, and the number can never fall at or
    below one already issued.

    On a collision the counter is advanced and the next candidate tried, up to
    `_INVOICE_NUMBER_ATTEMPTS`. Walking past an already-issued number is the
    series continuing correctly, not a gap - the gap is the erased invoice rows,
    which is data loss, not a numbering fault.

    Failing here is recoverable: the caller returns 503, the client retries, and
    no document is issued. Issuing the wrong number is not recoverable, because a
    GST invoice number cannot be reassigned once it has been sent to a customer.
    """
    fy = fy or _current_fy()

    table = dynamodb.Table(INVOICE_SEQ_TABLE)
    keys_table = dynamodb.Table(COMMERCE_KEYS_TABLE)

    for attempt in range(1, _INVOICE_NUMBER_ATTEMPTS + 1):
        try:
            resp = table.update_item(
                Key={'fy': fy},
                UpdateExpression='SET last_seq = if_not_exists(last_seq, :zero) + :inc, prefix = if_not_exists(prefix, :pfx), updated_at = :now',
                ExpressionAttributeValues={':zero': 0, ':inc': 1, ':pfx': 'WD', ':now': int(time.time())},
                ReturnValues='UPDATED_NEW',
            )
            seq = int(resp['Attributes']['last_seq'])
            prefix = resp['Attributes'].get('prefix', 'WD')
        except Exception as e:
            logger.error(json.dumps({
                'event': 'invoice_sequence_unavailable',
                'fy': fy,
                'table': INVOICE_SEQ_TABLE,
                'error': str(e)[:300],
            }))
            raise InvoiceSequenceUnavailable(
                f"Could not advance the invoice sequence for FY {fy}"
            ) from e

        candidate = _format_invoice_number(prefix, fy, seq)

        try:
            reserved = order_keys.reserve_invoice_number(
                keys_table, invoice_number=candidate, fy=fy)
        except order_keys.OrderIdentityUnavailable as e:
            # A storage error, NOT a lost race - `reserve_invoice_number` keeps those apart on
            # purpose. Retrying here would hand out a number nothing recorded, so this refuses.
            logger.error(json.dumps({
                'event': 'invoice_number_reservation_unavailable',
                'fy': fy,
                'invoiceNumber': candidate,
                'attempt': attempt,
                'error': str(e)[:300],
            }))
            raise InvoiceSequenceUnavailable(
                f"Could not reserve an invoice number for FY {fy}"
            ) from e

        if reserved:
            return candidate

        logger.warning(json.dumps({
            'event': 'invoice_number_already_reserved',
            'fy': fy,
            'invoiceNumber': candidate,
            'attempt': attempt,
            'attemptCap': _INVOICE_NUMBER_ATTEMPTS,
            'note': 'counter was behind the issued series; advancing',
        }))

    logger.error(json.dumps({
        'event': 'invoice_sequence_unavailable',
        'fy': fy,
        'reason': 'every candidate was already reserved',
        'attempts': _INVOICE_NUMBER_ATTEMPTS,
    }))
    raise InvoiceSequenceUnavailable(
        f"Exhausted {_INVOICE_NUMBER_ATTEMPTS} candidates for FY {fy}; "
        "run scripts/reconcile_invoice_sequence.py to realign the counter"
    )


def get_next_sequence_preview(body: Dict, request_id: str) -> Dict:
    """Preview next invoice number without incrementing.

    The counter alone cannot answer this: if it has been reset, `last_seq + 1` is a number that
    is already out, and showing it to staff is how a duplicate gets typed into a conversation.
    So the preview probes the reservation rows forward from the counter and reports the number
    `_get_next_invoice_number` would actually reach, alongside the raw `lastSeq` so the drift is
    visible rather than silently corrected. Point reads only - no scan, nothing written.
    """
    fy = body.get('fy') or _current_fy()

    table = dynamodb.Table(INVOICE_SEQ_TABLE)
    try:
        resp = table.get_item(Key={'fy': fy})
        item = resp.get('Item', {})
        last = int(item.get('last_seq', 0))
        prefix = item.get('prefix', 'WD')

        keys_table = dynamodb.Table(COMMERCE_KEYS_TABLE)
        seq = last + 1
        probes = 0
        while probes < _INVOICE_NUMBER_ATTEMPTS and order_keys.resolve_invoice_number(
                keys_table, _format_invoice_number(prefix, fy, seq)) is not None:
            seq += 1
            probes += 1

        return _resp(200, {
            'nextInvoiceNumber': _format_invoice_number(prefix, fy, seq),
            'fy': fy,
            'lastSeq': last,
            # The highest number known to be issued, counter and reservations combined. Equal to
            # `lastSeq` when they agree; higher when the counter is behind what went out.
            'reservedFloorSeq': seq - 1,
            # True when the probe ran out of attempts, so the floor reported is a lower bound and
            # the counter needs reconciling rather than another preview.
            'reservationProbeExhausted': probes >= _INVOICE_NUMBER_ATTEMPTS,
        })
    except Exception as e:
        return _resp(500, {'error': str(e)})


def _rupees_to_paise(value, *, code: str = 'AMOUNT_MISMATCH') -> int:
    """Rupees to integer paise, ONCE, at the boundary. No float arithmetic anywhere past here.

    `_dec` is the existing rupee quantiser (two decimal places), so multiplying its output by 100
    is exact and an integral result is guaranteed for any well-formed amount. A result that is NOT
    integral means a sub-paise figure reached this point, which cannot be charged and must not be
    rounded into something that can - `0.1 + 0.2` is not `0.3` in binary floating point, and a
    one-paise mismatch against the checkout total has to fail closed rather than be absorbed.
    """
    paise = _dec(value) * 100
    if paise != paise.to_integral_value():
        raise ValueError(code)
    as_int = int(paise)
    if as_int < 0:
        raise ValueError(code)
    return as_int


def _paise_to_rupees(paise: int) -> Decimal:
    """Integer paise back to rupees, ONCE, as an exact `Decimal`. The only conversion back."""
    return Decimal(str(int(paise))) / Decimal('100')


def _back_calculate_inclusive(total_paise: int, gst_rate: Decimal) -> tuple:
    """Split a GST-INCLUSIVE total into `(taxable_paise, tax_paise)` that sum to it EXACTLY.

    WHY THE TAX IS A REMAINDER AND NOT A SECOND CALCULATION
    ------------------------------------------------------
    The taxable value is `total * 100 / (100 + rate)`, which is almost never a whole number of
    paise: at 18% a 100.01 capture has a taxable value of 8475.42372... paise. Quantising BOTH
    legs independently - taxable rounded one way, tax computed as `taxable * rate / 100` and
    rounded another - lets the two disagree with the figure they came from by a paise, and that
    paise is not cosmetic here. A captured amount is compared against the invoice total with
    exact integer equality, so a one-paise drift refuses a payment that actually settled.

    Taking the tax as `total - taxable` makes the identity `taxable + tax == total` structural
    rather than something each rate has to happen to satisfy. The paise lands on the TAX leg,
    which is the conservative direction for a tax invoice: the taxable value is never overstated.

    `ROUND_HALF_UP` is the quantiser (not banker's rounding) because it is what the rest of this
    tree and the GST rules use for a rupee figure, and because `Decimal`'s default `ROUND_HALF_EVEN`
    would make the taxable value of two adjacent amounts move in different directions.

    A rate of 0 is the identity: the whole amount is taxable and the tax is 0.

    All `Decimal` and `int`. No float touches a money value here - `0.1 + 0.2` is not `0.3` in
    binary floating point and `tests/test_payment_path_has_no_float_money.py` AST-walks this file.
    """
    total = int(total_paise)
    rate = gst_rate if isinstance(gst_rate, Decimal) else Decimal(str(gst_rate))
    if total < 0:
        raise ValueError('a tax-inclusive total cannot be negative')
    if rate < 0:
        raise ValueError('a GST rate cannot be negative')
    taxable_paise = int((Decimal(total) * Decimal(100) / (Decimal(100) + rate)).quantize(
        Decimal('1'), rounding=ROUND_HALF_UP))
    return taxable_paise, total - taxable_paise


def _split_tax_halves(tax_paise: int) -> tuple:
    """Split a tax figure into `(cgst_paise, sgst_paise)` that sum to it EXACTLY.

    An intra-state supply prints CGST and SGST at half the rate each, so the two lines together
    ARE the tax. `tax / 2` twice is the obvious spelling and the wrong one: an odd number of
    paise formatted to two decimals prints two halves that sum to a paise less (or more) than the
    Total Tax row directly above them, and a tax invoice whose own breakdown does not add up is a
    document a GST officer reads as arithmetic they cannot follow.

    The odd paise goes on CGST, deliberately and always the same way, so the figure is a function
    of the amount rather than of which renderer drew it.
    """
    tax = int(tax_paise)
    sgst = tax // 2
    return tax - sgst, sgst


def _tax_halves_rupees(tax_value) -> tuple:
    """`(cgst, sgst)` as exact rupee `Decimal`s for the three renderers, summing to `tax_value`.

    The renderers hold a STORED tax figure off an invoice row that is already final, so this
    converts rather than decides. It falls back to a Decimal halving for a stored figure that is
    not expressible in whole paise, because this is a display path: refusing here would fail the
    rendering of a legacy row over a value nothing compares - the same reason `_money_display`
    falls back. The fallback still takes the second half as the remainder, so the two printed
    lines sum to the printed tax either way.
    """
    try:
        cgst_paise, sgst_paise = _split_tax_halves(
            wa_payment_request.exact_paise(tax_value))
        return _paise_to_rupees(cgst_paise), _paise_to_rupees(sgst_paise)
    except Exception:  # noqa: BLE001 - any unrepresentable stored figure takes the fallback
        tax_dec = Decimal(str(tax_value or 0))
        cgst = (tax_dec / 2).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        return cgst, tax_dec - cgst


# Entry points that record settled money or preserve an exact-price service contract.
_EXACT_PRICE_OR_SETTLED_ENTRY_POINTS = frozenset({
    'webhook', 'website_checkout', 'submit_request_flow', 'flow_payment',
})


def _new_collection_pricing_applies(entry_point: str,
                                    amount_is_tax_inclusive: bool) -> bool:
    """Every fresh collection uses the same fee policy, regardless of its UI origin."""
    return (not amount_is_tax_inclusive
            and entry_point not in _EXACT_PRICE_OR_SETTLED_ENTRY_POINTS)


def _delight_applies(entry_point: str, amount_is_tax_inclusive: bool) -> bool:
    """Only fresh, non-service collections are eligible; manual adjustments are rejected."""
    return _new_collection_pricing_applies(entry_point, amount_is_tax_inclusive)


def _invoice_input_error(body: Dict) -> str:
    """Validate the additive invoice boundary before any money conversion or number allocation."""
    items = body.get('items', [])
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        return 'Invoice items must be a list of objects'
    if body.get('amountIsTaxInclusive'):
        return ''  # the exact captured-total validator owns this separate contract
    try:
        # Keep all arithmetic below the exact integer-paise range of existing float callers.
        maximum = Decimal('45035996273704')
        fees = Decimal('0')
        for key in ('shipping', 'handling', 'greenPacking', 'notificationFee', 'convenienceFee'):
            if key not in body:
                continue
            value = Decimal(str(body[key]))
            if (not value.is_finite() or not 0 <= value <= maximum
                    or value * 100 != (value * 100).to_integral_value()):
                return f'{key} must be a nonnegative amount in whole paise'
            fees += value
        rate = Decimal(str(body.get('gstRate', 18)))
        if not rate.is_finite() or not 0 <= rate <= 100:
            return 'GST rate must be between 0 and 100'
        gross = Decimal('0')
        for item in items:
            amount = Decimal(str(item.get('amount', 0)))
            quantity = Decimal(str(item.get('quantity', 1)))
            item_rate = Decimal(str(item.get('gstRate', rate)))
            if (not amount.is_finite() or not 0 <= amount <= maximum
                    or amount * 100 != (amount * 100).to_integral_value()):
                return 'Item amounts must be nonnegative whole paise'
            if not quantity.is_finite() or quantity != quantity.to_integral_value() or not 1 <= quantity <= 100000:
                return 'Item quantity must be a positive integer'
            if not item_rate.is_finite() or not 0 <= item_rate <= 100:
                return 'Item GST rate must be between 0 and 100'
            gross += amount * quantity * (1 + item_rate / 100)
        if gross + fees > maximum:
            return 'Invoice total exceeds supported amount'
    except (InvalidOperation, ValueError, TypeError):
        return 'Invoice amounts must be finite numbers'
    return ''


# ─── Create Invoice ───

def create_invoice(body: Dict, request_id: str) -> Dict:
    """Create a new invoice from direct input. Includes deduplication by referenceId/paymentId."""
    now = int(time.time())

    # ── Deduplication: check if invoice already exists for this referenceId or paymentId ──
    reference_id = body.get('referenceId', '')
    if str(body.get('giftCardCode') or '').strip():
        return _resp(400, {
            'error': 'Gift cards are retired and are no longer accepted',
            'errorCode': 'GIFT_CARDS_RETIRED',
        })
    if str(body.get('couponCode') or '').strip():
        captured = bool(body.get('amountIsTaxInclusive'))
        return _resp(400, {
            'error': 'Discount codes are retired; eligible orders receive Delight automatically',
            'errorCode': 'AMOUNT_ALREADY_CAPTURED' if captured else 'COUPONS_RETIRED',
        })
    if not body.get('amountIsTaxInclusive'):
        try:
            manual_discount = Decimal(str(body.get('discount') or 0))
        except (InvalidOperation, ValueError, TypeError):
            manual_discount = Decimal('NaN')
        if not manual_discount.is_finite() or manual_discount != 0:
            return _resp(400, {
                'error': 'Manual discounts are retired; eligible orders receive Delight automatically',
                'errorCode': 'MANUAL_DISCOUNTS_RETIRED',
            })
    input_error = _invoice_input_error(body)
    if input_error:
        return _resp(400, {'error': input_error, 'errorCode': 'INVALID_AMOUNT'})

    # ── A physical staff order needs a payable delivery address, refused BEFORE anything is claimed ──
    #
    # `goodsType` for a fresh staff collection is forced to `physical-goods` further down, and the
    # address was previously only checked at `send_payment_link` - so staff could raise a physical
    # order with no deliverable address and discover it only when trying to collect. Refused HERE,
    # alongside the coupon/gift-card refusals and before the dedup claim row and
    # `_get_next_invoice_number`, so a refusal leaves no `claiming` row and burns no GST number.
    # `entryPoint` is read from the body directly (it is resolved into a local further down, after
    # this early-refusal group). Digital/service and captured invoices are unaffected.
    delivery_error = _create_invoice_delivery_error(
        body, body.get('entryPoint', 'manual'), bool(body.get('amountIsTaxInclusive')))
    if delivery_error:
        return delivery_error

    payment_id = body.get('paymentId', '')
    table = dynamodb.Table(INVOICES_TABLE)

    if reference_id or payment_id:
        try:
            filter_parts = []
            expr_values = {}
            if reference_id:
                filter_parts.append('referenceId = :ref')
                expr_values[':ref'] = reference_id
            if payment_id:
                filter_parts.append('paymentId = :pid')
                expr_values[':pid'] = payment_id

            filter_expr = ' OR '.join(filter_parts)
            # Full pagination to avoid DynamoDB Limit bug (Limit = items evaluated, not returned)
            existing = []
            scan_kwargs = {'FilterExpression': filter_expr, 'ExpressionAttributeValues': expr_values}
            while True:
                result = table.scan(**scan_kwargs)
                existing.extend(result.get('Items', []))
                if existing or 'LastEvaluatedKey' not in result:
                    break
                scan_kwargs['ExclusiveStartKey'] = result['LastEvaluatedKey']

            if existing:
                inv = existing[0]
                existing_id = inv.get('invoiceId', '')

                # If caller says this is now paid, update the existing invoice status.
                #
                # Two axes, and only one of them is the payment vocabulary. `status` is the
                # document lifecycle (created -> sent -> paid -> cancelled) so `'paid'` is its own
                # correct literal; `paymentStatus` is what the money did, so it goes canonical.
                #
                # The original demanded `incoming_ps == 'captured'` exactly, which meant a caller
                # sending the equally valid `paymentStatus='paid'` satisfied neither branch - the
                # invoice stayed unpaid, permanently, with no error anywhere.
                incoming_status = body.get('status', '')
                incoming_ps = body.get('paymentStatus', '')
                if (incoming_status == 'paid'
                        and pay_status.canonical(incoming_ps) == pay_status.CAPTURED
                        and inv.get('status') != 'paid'):
                    try:
                        table.update_item(
                            Key={'invoiceId': existing_id},
                            UpdateExpression='SET #st = :st, #ps = :ps, #pa = :pa, #ua = :now',
                            ExpressionAttributeNames={'#st': 'status', '#ps': 'paymentStatus', '#pa': 'paidAt', '#ua': 'updatedAt'},
                            ExpressionAttributeValues={
                                ':st': 'paid', ':ps': 'captured',
                                ':pa': body.get('paidAt', now), ':now': now,
                            },
                        )
                        logger.info(json.dumps({
                            'event': 'invoice_dedup_status_updated',
                            'invoiceId': existing_id,
                            'newStatus': 'paid',
                            'requestId': request_id,
                        }))
                    except Exception as upd_err:
                        logger.warning(json.dumps({
                            'event': 'invoice_dedup_status_update_error',
                            'invoiceId': existing_id,
                            'error': str(upd_err),
                            'requestId': request_id,
                        }))

                logger.info(json.dumps({
                    'event': 'invoice_dedup_hit',
                    'existingInvoiceId': existing_id,
                    'referenceId': reference_id,
                    'paymentId': payment_id,
                    'requestId': request_id,
                }))
                return _resp(200, {
                    'invoiceId': existing_id,
                    'invoiceNumber': inv.get('invoiceNumber', ''),
                    # A money value crossing a Lambda boundary, on the native leg's COMMON path
                    # (dedup is the usual case there). A STRING, so the unit ambiguity cannot be
                    # arithmetic'd by a reader who misses which unit it is in.
                    'total': _money_display(inv.get('total', 0)),
                    'referenceId': inv.get('referenceId', ''),
                    'deduplicated': True,
                })
        except Exception as dedup_err:
            logger.warning(json.dumps({
                'event': 'invoice_dedup_check_error',
                'error': str(dedup_err),
                'requestId': request_id,
            }))

    # ── Atomic claim, so a racing duplicate cannot consume a GST invoice number ──
    #
    # The scan above is the only dedup there was, and a DynamoDB scan is eventually
    # consistent: razorpay-webhook and inbound-whatsapp-handler both invoke this for the
    # same payment, both can scan and miss, and both then insert. `invoiceId` was a fresh
    # uuid4, so the `attribute_not_exists(invoiceId)` on the final put never fired.
    #
    # That mattered more than an ordinary duplicate row, because `_get_next_invoice_number`
    # IS atomic - the loser would have burned a real sequential number out of the GST
    # series. A gap in that series is a compliance artifact, not just untidy data.
    #
    # Deriving `invoiceId` from (referenceId, paymentId) makes the existing condition
    # load-bearing, and claiming a minimal row BEFORE touching the sequence means the
    # loser never increments it. `invoiceId` is opaque to every caller - it is a foreign
    # key in InvoiceItems/InvoiceAssets and an identifier in responses - so deriving it
    # changes no contract.
    dedup_source = reference_id or payment_id
    if dedup_source:
        import hashlib as _hashlib
        invoice_id = 'inv-' + _hashlib.sha256(
            f'invoice\x1f{reference_id}\x1f{payment_id}'.encode('utf-8')
        ).hexdigest()[:32]
        try:
            table.put_item(
                Item={'invoiceId': invoice_id, 'status': 'claiming', 'createdAt': now},
                ConditionExpression='attribute_not_exists(invoiceId)',
            )
        except Exception as claim_err:
            if not order_keys.is_conditional_failure(claim_err):
                logger.error(json.dumps({
                    'event': 'invoice_claim_error', 'error': str(claim_err),
                    'referenceId': reference_id, 'requestId': request_id}))
                return _resp(500, {'error': 'Could not claim invoice'})
            existing_inv = table.get_item(Key={'invoiceId': invoice_id}).get('Item', {})
            logger.info(json.dumps({
                'event': 'invoice_dedup_hit_atomic',
                'existingInvoiceId': invoice_id,
                'referenceId': reference_id, 'paymentId': payment_id,
                'note': 'lost the claim race; no invoice number consumed',
                'requestId': request_id,
            }))
            return _resp(200, {
                'invoiceId': invoice_id,
                'invoiceNumber': existing_inv.get('invoiceNumber', ''),
                # Same boundary, same reason as the dedup-hit response above.
                'total': _money_display(existing_inv.get('total', 0)),
                'referenceId': existing_inv.get('referenceId', reference_id),
                'deduplicated': True,
            })
    else:
        # No reference and no payment id: nothing to dedupe on, so a random id is the
        # honest answer rather than a hash of nothing that would collide every time.
        invoice_id = str(uuid.uuid4())

    # Auto-generate referenceId if not provided (WD-PAY- + 8-char hex)
    if not reference_id:
        reference_id = f"WD-PAY-{uuid.uuid4().hex[:8].upper()}"

    # Validate mandatory fields (relaxed for webhook-originated invoices)
    customer_phone = body.get('customerPhone', '')
    paid_by_phone = body.get('paidByPhone', customer_phone)
    customer_email = body.get('customerEmail', '')
    shipping_address = body.get('shippingAddress', '')
    billing_address = body.get('billingAddress', '')
    entry_point = body.get('entryPoint', 'manual')

    if not customer_phone:
        return _resp(400, {'error': 'Missing mandatory field: customerPhone'})

    # ── Amounts, computed BEFORE a GST invoice number is consumed ──
    #
    # This block used to sit AFTER `_get_next_invoice_number`, so every refusal below - a negative
    # subtotal, an out-of-range GST rate - burned a number out of the consecutive series Rule
    # 46(b) requires and then answered 400. Nothing in it reads the number, so moving it up costs
    # nothing, and it is a precondition for the coupon refusals: a number cannot be
    # reassigned once issued, so a coupon the store refuses must refuse before one exists. The
    # handler already ordered itself this way for `InvoiceSequenceUnavailable`; this extends the
    # same rule to every other refusal.
    items = body.get('items', [])
    subtotal = sum((Decimal(str(i.get('amount', 0))) * int(i.get('quantity', 1)) for i in items), Decimal('0'))
    discount = Decimal(str(body.get('discount', 0)))
    green_packing = Decimal(str(body.get('greenPacking', 0)))
    notification_fee = Decimal(str(body.get('notificationFee', 0)))

    # Detect if Green Packing / Notification Fee are already in items (new frontend sends them inline)
    gp_in_items = Decimal('0')
    nf_in_items = Decimal('0')
    for it in items:
        nm = (it.get('name', '') or '').lower()
        it_total = Decimal(str(it.get('amount', 0))) * int(it.get('quantity', 1))
        if 'green' in nm and 'pack' in nm:
            gp_in_items = it_total
        elif 'notification' in nm or 'alert' in nm:
            nf_in_items = it_total

    # If charge items are in the items array, they're already in subtotal — don't add again
    # If sent as separate fields (legacy), add them to total
    effective_gp = green_packing if gp_in_items == 0 else Decimal('0')
    effective_nf = notification_fee if nf_in_items == 0 else Decimal('0')

    # shipping field = express only (greenPacking + notificationFee stored as line items)
    shipping = Decimal(str(body.get('shipping', 0))) - green_packing - notification_fee
    if shipping < 0: shipping = Decimal('0')
    handling = Decimal(str(body.get('handling', 0)))
    gst_rate = Decimal(str(body.get('gstRate', 18)))

    # ── Validate: no negative amounts ──
    if subtotal < 0:
        return _resp(400, {'error': 'Subtotal cannot be negative'})
    if discount < 0:
        return _resp(400, {'error': 'Discount cannot be negative'})
    if gst_rate < 0 or gst_rate > 100:
        return _resp(400, {'error': 'GST rate must be between 0 and 100'})
    for idx_v, it_v in enumerate(items):
        if Decimal(str(it_v.get('amount', 0))) < 0:
            return _resp(400, {'error': f'Item {idx_v+1} amount cannot be negative'})
        if int(it_v.get('quantity', 1)) < 1:
            return _resp(400, {'error': f'Item {idx_v+1} quantity must be at least 1'})

    # ── Tax-inclusive mode (opt-in): the figure given is ALREADY the total ──
    #
    # WHAT THIS FIXES
    # ---------------
    # The additive path below computes the tax ON TOP of the item amounts, which is right for an
    # invoice somebody is about to pay. It is wrong for an invoice raised FROM a capture: the
    # money has already moved, and `create_invoice_from_payment` sent the captured amount as a
    # single line item with the default 18% rate, so a 100.00 capture became a 118.00 invoice
    # stamped PAID. Eighteen rupees the customer was never charged, on a GST document.
    #
    # D3: a captured amount is GST-INCLUSIVE. So in this mode the rate decides the SPLIT and
    # never the total - the taxable value is back-calculated and the tax is the remainder (see
    # `_back_calculate_inclusive`), and nothing may be added to the figure afterwards.
    #
    # WHY IT IS OPT-IN AND WHY `expectedTotalPaise` IS MANDATORY
    # ----------------------------------------------------------
    # Opt-in because the additive path is correct for every other caller and must stay unchanged
    # byte for byte when the flag is absent. Mandatory because the whole value of the mode is the
    # EXACT comparison further down: without the expected figure there is nothing to compare the
    # computed total against, and a silent fall back to the additive path would reintroduce the
    # defect on exactly the caller that asked not to have it. Absent is therefore a 400.
    #
    # Everything here happens before `_get_next_invoice_number`, so a refusal leaves no document
    # and burns no GST number - the ordering this whole block exists to preserve.
    amount_is_tax_inclusive = bool(body.get('amountIsTaxInclusive'))
    expected_total_paise = 0
    if amount_is_tax_inclusive:
        if body.get('expectedTotalPaise') is None:
            return _resp(400, {
                'error': 'A tax-inclusive amount requires expectedTotalPaise',
                'errorCode': 'EXPECTED_TOTAL_PAISE_REQUIRED',
            })
        try:
            # Integral check rather than `int()`: `int(10000.5)` truncates, and a figure that is
            # not a whole paise cannot be what a provider captured.
            expected_decimal = Decimal(str(body.get('expectedTotalPaise')))
        except (InvalidOperation, ValueError, TypeError):
            expected_decimal = None
        if (expected_decimal is None or not expected_decimal.is_finite()
                or expected_decimal != expected_decimal.to_integral_value()
                or expected_decimal <= 0):
            return _resp(400, {
                'error': 'expectedTotalPaise must be a positive whole number of paise',
                'errorCode': 'EXPECTED_TOTAL_PAISE_INVALID',
            })
        expected_total_paise = int(expected_decimal)

        # A coupon cannot be applied after capture; it would contradict the settled amount.
        if str(body.get('couponCode') or '').strip():
            return _resp(400, {
                'error': 'A coupon cannot be applied to an amount already captured',
                'errorCode': 'AMOUNT_ALREADY_CAPTURED',
            })

        gst_rate_decimal = Decimal(str(gst_rate))
        if not gst_rate_decimal.is_finite():
            return _resp(400, {'error': 'GST rate must be between 0 and 100'})
        taxable_paise, tax_paise = _back_calculate_inclusive(
            expected_total_paise, gst_rate_decimal)
        subtotal = _paise_to_rupees(taxable_paise)
        tax = _paise_to_rupees(tax_paise)
        # Every additive component is forced to zero, not merely left alone: a captured amount
        # cannot grow a charge, a fee or a shipping line after the fact. `Decimal` throughout, so
        # the total below is exact arithmetic on the two figures the split produced.
        discount = Decimal('0')
        shipping = Decimal('0')
        handling = Decimal('0')
        effective_gp = Decimal('0')
        effective_nf = Decimal('0')
        green_packing = Decimal('0')
        notification_fee = Decimal('0')
        # ONE line item, at the TAXABLE amount, so the persisted `InvoiceItems` rows still
        # reconcile to the persisted `subtotal`. Storing the gross figure here is what made the
        # old document self-contradictory: a 100.00 line, a 118.00 total and 18.00 of tax that
        # belonged to neither.
        items = [{
            'name': (items[0].get('name') if items else '') or 'Payment',
            'amount': subtotal,
            'quantity': 1,
            'gstRate': gst_rate,
        }]
    else:
        tax = sum((
            Decimal(str(i.get('amount', 0))) * int(i.get('quantity', 1)) * Decimal(str(i.get('gstRate', gst_rate))) / 100
            for i in items
        ), Decimal('0'))
        tax = tax.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    # ── The always-on Delight discount, applied BEFORE the fee because it is a price change ──
    #
    # There is no coupon code and no manual staff discount any more: the ONLY discount an invoice
    # carries is the fixed Delight policy (0.5% up to ₹50). Applied to eligible fresh collections
    # across entry points (`_delight_applies`), reducing the collection the convenience-fee calculator
    # consumes so a smaller order genuinely costs a smaller fee. The figure comes from
    # `default_coupon.delight_paise` — the SAME standalone computation the website/WhatsApp native
    # path uses — so an invoice and a cart for one order can never disagree. Pure arithmetic: no
    # table, no provider, no hold, no refusal path.
    #
    # `discount` is Delight-only from here on: a tax-inclusive capture already forced it to
    # Decimal('0'), and every other entry point starts at zero because manual discount entry is
    # retired. Delight overwrites it below when it applies.
    discount = discount if amount_is_tax_inclusive else 0
    coupon_discount_rupees = Decimal('0')
    coupon_discount_paise = 0
    redemption_attributes: Dict[str, Any] = {}
    stored_coupon_code = ''

    if _delight_applies(entry_point, amount_is_tax_inclusive):
        # Additive invoice item amounts are GST-exclusive (the tax block above adds tax).
        # Native catalogue prices are inclusive. Gross up only this additive input to
        # compare the same goods value, excluding delivery, handling and fee lines.
        # Packing/notification charges can arrive inline or as separate legacy fields.
        goods_gross = Decimal('0')
        for item in items:
            name = str(item.get('name') or '').lower()
            if ('green' in name and 'pack' in name) or 'notification' in name or 'alert' in name:
                continue
            amount = Decimal(str(item.get('amount', 0))) * int(item.get('quantity', 1))
            rate = Decimal(str(item.get('gstRate', gst_rate)))
            goods_gross += amount * (Decimal('1') + rate / Decimal('100'))
        delight_discount_paise = default_coupon.delight_paise(
            _rupees_to_paise(goods_gross.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)))
        if delight_discount_paise > 0:
            coupon_discount_paise = delight_discount_paise
            coupon_discount_rupees = _paise_to_rupees(coupon_discount_paise)
            stored_coupon_code = default_coupon.DELIGHT_CODE
            discount = coupon_discount_rupees
            # Recorded so the receipt and the Meta discount row can name the "Delight" line, but
            # NOT held: a fixed owner policy has no COUPONHOLD#/COUPONUSE#/COUPONREDEEM# and is
            # exempt from the single-use and per-customer limits a campaign coupon would have had.
            redemption_attributes['couponCode'] = stored_coupon_code
            redemption_attributes['couponDiscount'] = _dec(coupon_discount_rupees)

    # Convenience fee policy has ONE home: checkout_pricing.compute_quote.
    # For new/manual/WhatsApp collections the server derives the fee from the exact post-discount,
    # post-delivery, post-supply-GST collection. Captured/tax-inclusive invoices add no new fee.
    #
    # A legacy client may still send convenienceFee. Zero keeps the historical "server calculate"
    # meaning. A non-zero value is accepted only if it EXACTLY matches the canonical calculator;
    # otherwise refuse before consuming an invoice number. Silently replacing a stale client fee
    # would let the customer preview one amount and receive an invoice for another.
    raw_convenience_fee = body.get('convenienceFee')
    if amount_is_tax_inclusive:
        # The inclusive branch above converted subtotal/tax/additive components to Decimal.
        # Keep this zero Decimal too: Decimal + float is a TypeError and, more importantly,
        # captured-money arithmetic must never leave exact decimal space.
        convenience_fee = Decimal('0')
    elif _new_collection_pricing_applies(entry_point, amount_is_tax_inclusive):
        collection = subtotal - discount + shipping + effective_gp + effective_nf + handling + tax
        quote = checkout_pricing.compute_quote(_rupees_to_paise(collection))
        canonical_fee_paise = quote.convenience_fee_paise + quote.convenience_gst_paise

        if raw_convenience_fee not in (None, ''):
            try:
                supplied_fee_paise = wa_payment_request.exact_paise(raw_convenience_fee)
            except wa_payment_request.PaymentRequestRefused:
                return _resp(400, {
                    'error': 'Convenience fee does not match server pricing',
                    'errorCode': 'CONVENIENCE_FEE_MISMATCH',
                })
            if supplied_fee_paise not in (0, canonical_fee_paise):
                return _resp(400, {
                    'error': 'Convenience fee does not match server pricing',
                    'errorCode': 'CONVENIENCE_FEE_MISMATCH',
                })

        convenience_fee = _paise_to_rupees(canonical_fee_paise)
    else:
        convenience_fee = Decimal(str(raw_convenience_fee or 0))

    total = subtotal - discount + shipping + effective_gp + effective_nf + handling + tax + convenience_fee

    # ── The exact-total invariant: an invoice from a capture IS the capture ──
    #
    # Exact integer equality in paise, on the figure about to be stored, BEFORE a GST number is
    # consumed. Not a tolerance: the old matcher compared rupee floats with
    # `abs(inv_total - amount) < 0.02` and that is how an 18-rupee discrepancy stayed invisible
    # for as long as it did. A one-paise difference here means the two sides genuinely disagree
    # about what was collected, and the honest answer to that is a refusal with nothing written -
    # not a document, and not a number out of the consecutive series.
    #
    # `exact_paise` is the same reader the reservation and the capture comparison use, so a total
    # carrying sub-paise noise fails closed rather than being rounded into agreement.
    if amount_is_tax_inclusive:
        try:
            computed_total_paise = wa_payment_request.exact_paise(total)
        except wa_payment_request.PaymentRequestRefused:
            computed_total_paise = None
        if computed_total_paise != expected_total_paise:
            logger.error(json.dumps({
                'event': 'invoice_total_mismatch',
                'referenceId': reference_id,
                'paymentId': payment_id,
                'expectedTotalPaise': expected_total_paise,
                'computedTotalPaise': computed_total_paise,
                'note': 'no invoice number consumed, nothing written',
                'requestId': request_id,
            }))
            return _resp(400, {
                'error': 'The invoice total does not equal the captured amount',
                'errorCode': 'INVOICE_TOTAL_MISMATCH',
                'expectedTotalPaise': expected_total_paise,
                'computedTotalPaise': computed_total_paise,
            })
    # ── Only now is a GST invoice number consumed ──
    #
    # Every refusal above has already answered. This is the last thing that can fail, and it is
    # the one failure that must not leave a document behind: a number outside the consecutive
    # series is worse than no invoice, because it cannot be reassigned once it has gone out.
    try:
        invoice_number = _get_next_invoice_number(body.get('fy'))
    except InvoiceSequenceUnavailable as exc:
        # 503, not 500: the request is well-formed and will succeed once the
        # sequence counter is reachable again, so the caller should retry rather
        # than treat the payload as bad. Nothing is written - an invoice with a
        # number outside the GST series is worse than no invoice, because the
        # number cannot be reassigned after it has gone to a customer.
        logger.error(json.dumps({
            'event': 'invoice_not_created_sequence_unavailable',
            'referenceId': reference_id,
            'error': str(exc),
            'requestId': request_id,
        }))
        return _resp(503, {
            'error': 'Invoice numbering is temporarily unavailable',
            'errorCode': 'INVOICE_SEQUENCE_UNAVAILABLE',
            'retryable': True,
        })

    # Determine initial status
    status = body.get('status', 'created')
    payment_status = body.get('paymentStatus', 'pending')

    invoice = {
        'invoiceId': invoice_id,
        'invoiceNumber': invoice_number,
        'paymentId': payment_id,
        'orderId': body.get('orderId', ''),
        'referenceId': reference_id,
        'entryPoint': entry_point,
        # Where the customer placed the order, so the invoice can print its own Source line
        # (GST Rule 46 carries no such requirement; this is for the customer and for support).
        # `entryPoint` is NOT a substitute: it records which internal flow minted the invoice
        # (`pay_flow`, `webhook`, `manual`), and a WhatsApp-origin catalogue order is settled by
        # the website leg, so its entryPoint is a website one. Canonicalised on the way in, so the
        # stored word is already one of exactly two and no reader has to coerce it again. Never
        # empty, so the put_item filter below cannot drop it.
        'channel': order_channel.canonical(body.get('channel')),
        'status': status,
        'paymentStatus': payment_status,
        # Customer
        # VALIDATED, not canonicalised, and the difference is the point. `channel` above has a
        # true default so junk degrades to `website`; a customer id has no substitute, so junk
        # must become ABSENT. `is_customer_uuid` refuses a non-canonical spelling and refuses a
        # uuid7 (which would print the customer's record-creation time on the document), so a bad
        # value is dropped here and the renderers draw no Customer ID row - rather than printing
        # whatever arrived on a request body onto a tax invoice.
        customer_uuid.ATTRIBUTE: (
            body.get(customer_uuid.ATTRIBUTE, '')
            if customer_uuid.is_customer_uuid(body.get(customer_uuid.ATTRIBUTE, '')) else ''),
        'contactId': body.get('contactId', ''),
        'customerName': body.get('customerName', ''),
        'customerPhone': customer_phone,
        'paidByPhone': paid_by_phone,
        'customerEmail': customer_email,
        'shippingAddress': shipping_address,
        'billingAddress': billing_address,
        'goodsType': ('physical-goods' if _new_collection_pricing_applies(entry_point, amount_is_tax_inclusive)
                      else body.get('goodsType', 'digital-goods')),
        # Catalog product id (retailer_id) — used by the post-payment flow resolver
        # to open the flow mapped to THIS product (catalog_flow_map).
        'catalogRetailerId': body.get('catalogRetailerId', '') or body.get('retailerId', ''),
        # Amounts (stored in rupees)
        'subtotal': _dec(subtotal),
        'discount': _dec(discount),
        'shipping': _dec(shipping),
        'handling': _dec(handling),
        'gstRate': _dec(gst_rate),
        'tax': _dec(tax),
        'convenienceFee': _dec(convenience_fee),
        'total': _dec(total),
        'currency': body.get('currency', 'INR'),
        'gstin': body.get('gstin', COMPANY['gstin']),
        'purpose': body.get('purpose', ''),
        'notes': body.get('notes', ''),
        # Payment routing — which PG config to use when customer triggers via keyword
        'preferredGateway': body.get('preferredGateway', ''),  # 'razorpay' only
        'paymentConfiguration': body.get('paymentConfiguration', ''),  # exact Meta config name
        # Structured address for WhatsApp Payments shipping_info
        'addressLine1': body.get('addressLine1', ''),
        'addressLine2': body.get('addressLine2', ''),
        'city': body.get('city', ''),
        'state': body.get('state', ''),
        'postalCode': body.get('postalCode', ''),
        'landmark': body.get('landmark', ''),
        # Timestamps
        'createdAt': now,
        'updatedAt': now,
        'paidAt': body.get('paidAt', 0),
    }

    # The Delight discount attributes (couponCode="DELIGHT", couponDiscount), present ONLY when
    # Delight actually applied. Absent rather than zero otherwise, so an invoice that carried no
    # discount stays distinguishable from one discounted by ₹0 — different facts a reader must be
    # able to tell apart.
    invoice.update(redemption_attributes)

    # Unconditional: the claim above already established exclusivity for the derived id,
    # and this write is what replaces the minimal claim row with the real invoice. A
    # condition here would refuse our own claim. For the no-reference path the id is a
    # fresh uuid4, so there is nothing to collide with either.
    table.put_item(Item={k: v for k, v in invoice.items() if v is not None and v != ''})

    # Store invoice items (including greenPacking + notificationFee as line items)
    items_table = dynamodb.Table(INVOICE_ITEMS_TABLE)
    all_items = list(items)

    # Check if Green Packing / Notification Fee already exist as items (new frontend sends them inline)
    existing_names = {(it.get('name', '') or '').lower() for it in all_items}
    has_green = any('green' in n and 'pack' in n for n in existing_names)
    has_notif = any('notification' in n or 'alert' in n for n in existing_names)

    # Legacy support: if sent as separate fields and NOT already in items, append them.
    # Zero in tax-inclusive mode, for the same reason the amounts block zeroed them: a charge
    # line appended here would be a line the capture never paid for, and the stored items would
    # stop reconciling to the stored subtotal.
    green_packing = (Decimal('0') if amount_is_tax_inclusive
                     else Decimal(str(body.get('greenPacking', 0))))
    notification_fee = (Decimal('0') if amount_is_tax_inclusive
                        else Decimal(str(body.get('notificationFee', 0))))
    if green_packing > 0 and not has_green:
        all_items.append({'name': 'Green Packing', 'amount': green_packing, 'quantity': 1, 'isCharge': True})
    if notification_fee > 0 and not has_notif:
        all_items.append({'name': 'Notification Fee', 'amount': notification_fee, 'quantity': 1, 'isCharge': True})
    if all_items:
        for idx, item in enumerate(all_items):
            items_table.put_item(Item={
                'invoiceId': invoice_id,
                'itemIndex': idx,
                'name': item.get('name', 'Item'),
                'amount': Decimal(str(item.get('amount', 0))),
                'quantity': int(item.get('quantity', 1)),
                'gstRate': Decimal(str(item.get('gstRate', gst_rate))),
                'productId': item.get('productId', ''),
                'isCharge': item.get('isCharge', False),
            })

    logger.info(json.dumps({'event': 'invoice_created', 'invoiceId': invoice_id, 'invoiceNumber': invoice_number, 'referenceId': reference_id, 'total': float(total), 'requestId': request_id}))

    # ONE logical order across channels: bind this statutory invoice to the fulfilment OrderTable
    # row it settles, in BOTH directions, so a WhatsApp payment and a website payment resolve to
    # one joinable order identity. The two records stay SEPARATE (an immutable GST document vs a
    # mutable order), which is correct — this is a cross-link, not a merge, and it never touches a
    # financial field or the order's finalization conflict keys.
    _cross_link_invoice_and_order(reference_id, invoice_id, invoice_number, request_id)
    created: Dict[str, Any] = {
        'invoiceId': invoice_id, 'invoiceNumber': invoice_number, 'referenceId': reference_id,
        'total': float(total), 'convenienceFee': float(convenience_fee),
    }
    # The Delight discount the SERVER applied, echoed back so the form renders our figure. Present
    # only when Delight actually discounted this invoice; a fixed policy, so there is no reason
    # code and nothing the browser could have supplied.
    if stored_coupon_code:
        created['couponCode'] = stored_coupon_code
        created['couponDiscount'] = float(coupon_discount_rupees)
    return _resp(201, created)



def _cross_link_invoice_and_order(reference_id: str, invoice_id: str, invoice_number: str,
                                  request_id: str) -> None:
    """Bind this invoice to the ONE OrderTable row it settles, in both directions. Never raises.

    ONE LOGICAL ORDER ACROSS CHANNELS, as a joinable identity rather than a merged row. A website
    payment and a WhatsApp payment each produce a statutory invoice AND (on the finalised leg) an
    order record; this makes the two directly joinable so a reader does not have to re-derive the
    link from `referenceId` every time, and so the two documents provably describe one order.

    The order id is resolved through the SAME immutable CommerceKeys chain the payment already
    wrote — `PAYREF#<ref>` -> paymentAttemptId -> `PAYMENTATTEMPT#<attempt>` -> orderIdRef — never
    from a client field. The invoice's own `orderId` column historically holds the Razorpay
    PROVIDER order id (a different namespace), so the internal link is written to a distinct
    `internalOrderId` attribute rather than overloading it.

    What it writes:
      * onto the INVOICE row: `internalOrderId` (+ `orderNumber`) — attribution, not a financial
        field, so it does not touch the `_INVOICE_FINANCIAL_FIELDS` immutability contract.
      * onto the ORDER row: `invoiceId` (+ `invoiceNumber`) — conditional on the order existing,
        and never any of the five finalization association-conflict keys.

    A reference that resolves to no order yet (a legacy/pre-commerce invoice, or an attempt with
    no finalised order) is a NO-OP: the invoice stands on its own and there is simply nothing to
    link. All failures are logged and swallowed — the invoice and the order are already the
    authoritative records; a missing cross-link must not fail invoice creation or burden the
    statutory path.
    """
    if not reference_id or not invoice_id:
        return
    try:
        keys = dynamodb.Table(COMMERCE_KEYS_TABLE)
        payref = order_keys.resolve_payment_reference(keys, reference_id)
        attempt_id = str((payref or {}).get('paymentAttemptId') or '')
        claim = order_keys.resolve_order_for_payment(keys, attempt_id) if attempt_id else None
        order_id = str((claim or {}).get('orderIdRef') or '')
        order_number = str((claim or {}).get('orderNumber') or '')
        if not order_id:
            return
        now = int(time.time())
        # Invoice -> order (attribution; the invoice row is ours, written just above).
        try:
            dynamodb.Table(INVOICES_TABLE).update_item(
                Key={'invoiceId': invoice_id},
                UpdateExpression='SET internalOrderId=:oid, orderNumber=:onum, updatedAt=:now',
                ConditionExpression='attribute_exists(invoiceId)',
                ExpressionAttributeValues={':oid': order_id, ':onum': order_number, ':now': now})
        except Exception as inv_err:  # noqa: BLE001
            if not order_keys.is_conditional_failure(inv_err):
                raise
        # Order -> invoice (conditional on the order existing; never creates one, never touches a
        # money/identity key the finalization conflict guard compares).
        try:
            dynamodb.Table(shared_tables.orders_table_name()).update_item(
                Key={'orderId': order_id},
                UpdateExpression='SET invoiceId=:iid, invoiceNumber=:inum, updatedAt=:now',
                ConditionExpression='attribute_exists(orderId)',
                ExpressionAttributeValues={':iid': invoice_id, ':inum': invoice_number or '',
                                           ':now': now})
        except Exception as ord_err:  # noqa: BLE001
            if not order_keys.is_conditional_failure(ord_err):
                raise
        logger.info(json.dumps({'event': 'invoice_order_cross_linked', 'invoiceId': invoice_id,
                                'orderId': order_id, 'referenceId': reference_id,
                                'requestId': request_id}))
    except Exception as link_error:  # noqa: BLE001
        logger.warning(json.dumps({'event': 'invoice_order_cross_link_failed',
                                    'referenceId': reference_id, 'invoiceId': invoice_id,
                                    'error': str(link_error)[:300], 'requestId': request_id}))


def _contact_address_fields(contact: Optional[Dict]) -> Dict[str, str]:
    """The invoice-body address keys for a contact, from the ONE canonical address shape.

    Prefers the structured `checkoutDeliveryAddress` Map via `contact_address.from_contact`
    (never raises; returns None when absent or malformed), and falls back to the legacy flat
    columns for a contact row written before the address convergence. Returns the exact keys the
    invoice body and the `shipping_info` pre-fill downstream read, so the statutory invoice path
    is unchanged in shape — only its SOURCE is unified.

    `addressLine2` maps to the Map's `locality` (the receipt prints it as the landmark line), and
    `shippingAddress`/`billingAddress` carry the composed one-liner so the string readers in
    `receipt_layout` still have a value. `billingAddress` mirrors shipping: we collect one address
    per customer (see `contact_address`'s module docstring), so there is no separate billing one.
    """
    contact = contact or {}
    address = contact_address.from_contact(contact)
    if address is not None:
        one_line = str(address.get('fullAddress') or '')
        return {
            'shippingAddress': one_line,
            'billingAddress': one_line,
            'addressLine1': str(address.get('addressLine1') or ''),
            'addressLine2': str(address.get('locality') or ''),
            'city': str(address.get('city') or ''),
            'state': str(address.get('state') or ''),
            'postalCode': str(address.get('postalCode') or ''),
        }
    # Legacy flat-column fallback (a contact saved before convergence has no Map yet).
    return {
        'shippingAddress': str(contact.get('shippingAddress') or ''),
        'billingAddress': str(contact.get('billingAddress') or ''),
        'addressLine1': str(contact.get('addressLine1') or ''),
        'addressLine2': str(contact.get('landmark') or ''),
        'city': str(contact.get('city') or ''),
        'state': str(contact.get('state') or ''),
        'postalCode': str(contact.get('postalCode') or ''),
    }


def create_invoice_from_payment(body: Dict, request_id: str) -> Dict:
    """Create invoice from a Razorpay payment ID. Called by PostPaymentHandler."""
    payment_id = body.get('paymentId')
    if not payment_id:
        return _resp(400, {'error': 'paymentId required'})

    # Fetch payment record (full pagination to avoid DynamoDB Limit bug)
    payments_table = dynamodb.Table(PAYMENTS_TABLE)
    try:
        items = []
        scan_kwargs = {
            'FilterExpression': boto3.dynamodb.conditions.Attr('paymentId').eq(payment_id),
        }
        while True:
            result = payments_table.scan(**scan_kwargs)
            items.extend(result.get('Items', []))
            if items or 'LastEvaluatedKey' not in result:
                break
            scan_kwargs['ExclusiveStartKey'] = result['LastEvaluatedKey']
        if not items:
            return _resp(404, {'error': f'Payment {payment_id} not found'})
        payment = items[0]
    except Exception as e:
        return _resp(500, {'error': f'Payment lookup failed: {e}'})

    # ── The captured amount, read as the authoritative INTEGER paise ──
    #
    # `payment['amount']` is what `razorpay-webhook` stored - `Decimal(amount_paise)`, in PAISE
    # (razorpay-webhook/handler.py:1978). `amountInRupees` beside it is a DISPLAY STRING, and
    # reading that one is where the 118-for-a-100-capture defect started: the display figure went
    # in as a line item and the 18% default was then applied on top of it.
    #
    # The rupee round trip through `exact_paise` is not ceremony - it is what PROVES the stored
    # figure is a whole paise. A plain `int()` would truncate a drifted value into one that
    # compares equal to nothing, and `exact_paise` is the same reader the capture comparison uses,
    # so both sides of the invariant below agree on what a money value is.
    #
    # A payment row with no usable integer amount is a REFUSAL. The alternative the old code took
    # - `float(payment.get('amountInRupees', 0))`, defaulting to zero - issues a zero-rupee tax
    # invoice against a real capture and burns a GST number doing it.
    try:
        captured_paise = wa_payment_request.exact_paise(
            Decimal(str(payment.get('amount'))) / Decimal('100'))
    except (wa_payment_request.PaymentRequestRefused, InvalidOperation, ValueError, TypeError):
        captured_paise = 0
    if captured_paise <= 0:
        logger.error(json.dumps({
            'event': 'invoice_not_created_payment_amount_unusable',
            'paymentId': payment_id,
            'note': 'no invoice number consumed, nothing written',
            'requestId': request_id,
        }))
        return _resp(400, {
            'error': 'The payment record carries no usable captured amount',
            'errorCode': 'PAYMENT_AMOUNT_UNUSABLE',
        })

    # Fetch contact if available
    contact_phone = payment.get('contact', '')
    contact = _lookup_contact_by_phone(contact_phone)

    # Build invoice body from payment + contact
    inv_body = {
        'paymentId': payment_id,
        'orderId': payment.get('orderId', ''),
        'referenceId': payment.get('referenceId', ''),
        'entryPoint': body.get('entryPoint', 'webhook'),
        # Pass through, not decide: the caller (razorpay-webhook / the post-payment handler) knows
        # the order's channel because it holds the attempt row that carries it. An absent value
        # reaches `create_invoice` as '' and canonicalises to `website`, which is true of every
        # payment that can exist today - no WhatsApp-origin order is reachable yet.
        'channel': body.get('channel', ''),
        # Pass through on the same terms. Taken off the REQUEST BODY (which the webhook filled
        # from its own `PAYREF#` row) and never from the contact the lookup above returned: a
        # contact read here would answer "who has this phone now", and a ported number would
        # move a paid order's customer id to whoever received it next. `create_invoice`
        # re-validates it before storing.
        customer_uuid.ATTRIBUTE: body.get(customer_uuid.ATTRIBUTE, ''),
        'status': 'paid',
        'paymentStatus': 'captured',
        'paidAt': int(float(payment.get('createdAt', time.time()))),
        'contactId': contact.get('contactId', '') if contact else '',
        'customerName': contact.get('name', '') if contact else '',
        'customerPhone': contact_phone,
        'paidByPhone': contact_phone,
        'customerEmail': contact.get('email', payment.get('email', '')) if contact else payment.get('email', ''),
        # ONE address shape: prefer the canonical `checkoutDeliveryAddress` Map, fall back to the
        # legacy flat columns for a contact row written before the convergence. `_contact_address_fields`
        # returns the flat projection the invoice body and the shipping_info pre-fill both consume.
        **_contact_address_fields(contact),
        'items': body.get('items', [{'name': body.get('itemName', 'Payment'),
                                     'amount': _paise_to_rupees(captured_paise),
                                     'quantity': 1}]),
        'discount': float(body.get('discount', 0)),
        'shipping': float(body.get('shipping', 0)),
        # Still configurable and still 18 by default - but the rate now decides the SPLIT of the
        # captured amount, never the total. See `_back_calculate_inclusive`.
        'gstRate': float(body.get('gstRate', 18)),
        'convenienceFee': float(body.get('convenienceFee', 0)),
        # ── D3: what the provider captured IS the GST-inclusive total ──
        # `create_invoice` back-calculates the taxable value and the tax from `gstRate`, forces
        # every additive component to zero, and refuses with `INVOICE_TOTAL_MISMATCH` if the
        # document it is about to write does not equal this figure to the paise - before a GST
        # number is consumed. The three money fields above are therefore zeroed by that mode
        # whatever a caller sends: money already taken cannot grow a charge.
        'amountIsTaxInclusive': True,
        'expectedTotalPaise': captured_paise,
        'gstin': body.get('gstin', contact.get('gstin', '') if contact else '') or COMPANY['gstin'],
        'purpose': body.get('purpose', ''),
        'currency': payment.get('currency', 'INR'),
    }

    return create_invoice(inv_body, request_id)


# ─── Update / Read / List ───

#: The FINANCIAL CONTENT of the document — the fields a tax invoice is read for.
#:
#: Immutable once the invoice is issued (see `_is_issued`). Contact, address, `notes`, `purpose`
#: and `goodsType` are deliberately NOT here: correcting a spelling of the customer's name does
#: not change what was charged, and refusing it would push staff toward cancel-and-reissue for a
#: typo, which burns a GST number for no reason.
#:
#: `orderId` and `referenceId` are in the set because they are the document's identity claims:
#: the reference is what the WhatsApp payment, the rendered asset key and the reconciliation all
#: join on, so re-pointing it after issue re-attributes money that has already moved.
_INVOICE_FINANCIAL_FIELDS = frozenset({
    'subtotal', 'discount', 'shipping', 'handling', 'gstRate', 'tax', 'convenienceFee', 'total',
    'referenceId', 'orderId',
})

#: The two fields a client may never write, on ANY row state. See D5.
#:
#: They are not conditioned on the row's state, and that is the whole point: a field that is
#: only sometimes client-writable is a field whose guard can be bypassed by finding the state
#: where it is permitted. An issued unpaid invoice used to be markable `paid`/`captured` by a
#: PUT with no payment anywhere behind it.
_INVOICE_SERVER_OWNED_FIELDS = frozenset({'status', 'paymentStatus'})

#: The server transitions that DO own them, named in the refusal so the operator is not left
#: guessing which button to press instead.
_INVOICE_STATUS_WRITERS = ('create_invoice (dedup branch)', 'cancel_invoice',
                           'send_payment_link', 'razorpay-webhook capture path')

#: Document-lifecycle statuses that still mean "nothing has been issued".
#:
#: `claiming` is the transient dedup placeholder `create_invoice` writes before it has a number;
#: `created` is a row that exists but has not moved. Everything beyond this set — `sent`,
#: `pending_payment`, `paid`, `cancelled` — is a document that has left the building.
_INVOICE_UNISSUED_STATUSES = frozenset({'', 'claiming', 'created'})


def _is_issued(invoice: Optional[Dict]) -> bool:
    """Whether this row is a DOCUMENT OF RECORD rather than an unissued draft.

    True once the row carries an `invoiceNumber` — the moment a number leaves the GST series is
    the moment the document exists, whatever the row's status says — or once its status has moved
    past the unissued set.

    ONE helper on purpose. The three refusal sites that consult it (the financial-field guard in
    `update_invoice`, and the asset version keys in `generate_invoice_image` /
    `generate_invoice_pdf`) cannot disagree about what "issued" means, which is how a guard gets
    bypassed: refuse the edit but overwrite the asset, or vice versa.

    An absent/unreadable row answers False here. Callers must NOT treat "could not read" as
    "draft" — `update_invoice` refuses before it ever reaches this function on a failed read.
    """
    if not invoice:
        return False
    if str(invoice.get('invoiceNumber', '') or '').strip():
        return True
    return str(invoice.get('status', '') or '').strip() not in _INVOICE_UNISSUED_STATUSES


def update_invoice(invoice_id: str, body: Dict, request_id: str) -> Dict:
    """Update an existing invoice (admin). Blocks amount changes on paid/cancelled invoices."""
    table = dynamodb.Table(INVOICES_TABLE)

    # Defensive 400 for a stale client that still sends a code. There is no coupon system and no
    # gift-card system any more — the only discount is the always-on Delight policy the engine
    # applies at creation — so a code on an update cannot mean anything. REFUSING rather than
    # silently dropping it: a 200 that looked like a code had been applied, while the full amount
    # was still collected, would be the dangerous alternative.
    if 'couponCode' in body or 'giftCardCode' in body:
        return _resp(400, {
            'error': 'A discount code cannot be applied to an invoice; none is supported',
            'errorCode': 'USE_CREATE',
        })

    # A non-zero `discount` is likewise refused, BEFORE the issued-immutability answer below, so
    # the reason a client sees is "discounts are retired" rather than the generic immutability
    # 409 - and so even a hypothetical unissued draft can never carry a client-set discount. The
    # only discount an invoice holds is the server-computed Delight frozen at creation; manual
    # entry is retired here exactly as it is in `create_invoice`. A zero is allowed through as a
    # harmless no-op (a client echoing the stored zero).
    if 'discount' in body:
        try:
            sent_discount = Decimal(str(body.get('discount') or 0))
        except (InvalidOperation, ValueError, TypeError):
            sent_discount = Decimal('NaN')
        if not sent_discount.is_finite() or sent_discount != 0:
            return _resp(400, {
                'error': ('Discounts are not editable; eligible orders carry the automatic '
                          'Delight discount applied by the engine at creation.'),
                'errorCode': 'MANUAL_DISCOUNTS_RETIRED',
            })

    # ── D5: `status` and `paymentStatus` are not client-writable, on any row state ──
    #
    # Refused BEFORE the row is read, because the answer does not depend on the row. A draft is
    # refused as firmly as a paid invoice: the alternative - permitting it while the row is
    # young - is the bypass, since a PUT can simply be sent at the state where the field is
    # allowed. The dangerous case this closes is concrete: an issued unpaid invoice could be
    # PUT to `status: paid` / `paymentStatus: captured` with no payment, no capture and no
    # webhook, and every downstream reader then treated it as money received.
    server_owned = sorted(_INVOICE_SERVER_OWNED_FIELDS & set(body.keys()))
    if server_owned:
        return _resp(400, {
            'error': ('Payment state is not editable. It is set only from verified payment '
                      'evidence. Nothing has been charged.'),
            'errorCode': 'STATUS_NOT_CLIENT_WRITABLE',
            'fields': server_owned,
            'ownedBy': list(_INVOICE_STATUS_WRITERS),
        })

    # ── D4: the financial content of an ISSUED invoice is immutable ──
    financial = sorted(_INVOICE_FINANCIAL_FIELDS & set(body.keys()))
    if financial:
        try:
            existing = table.get_item(Key={'invoiceId': invoice_id}).get('Item', {})
        except Exception as error:  # noqa: BLE001
            # Fails CLOSED, replacing a warn-and-continue. An immutability guard that proceeds
            # when it could not read the row is not a guard: one throttled GetItem was all it
            # took to rewrite the totals on a paid tax invoice. Retryable, because the request
            # is well-formed and will be answered correctly once the read succeeds.
            logger.error(json.dumps({
                'event': 'invoice_immutability_guard_unreadable', 'invoiceId': invoice_id,
                'error': type(error).__name__, 'requestId': request_id,
            }))
            return _resp(503, {
                'error': 'The invoice could not be read, so no change was applied',
                'errorCode': 'INVOICE_STATE_UNREADABLE',
                'retryable': True,
            })

        if _is_issued(existing):
            ex_ps = pay_status.canonical(existing.get('paymentStatus', ''))
            paid = ex_ps in (pay_status.CAPTURED, pay_status.REFUNDED) or \
                existing.get('status', '') == 'paid'
            # The route to use INSTEAD is in the message, because a refusal with no alternative
            # gets worked around. An unpaid issued invoice can be cancelled and reissued under a
            # new number; a paid one cannot, because the document the customer holds is the one
            # the money was taken against, so the correction is an append-only record beside it.
            return _resp(409, {
                'error': ('An issued invoice cannot be rewritten. '
                          + ('Record a credit note or a refund against it instead.' if paid
                             else 'Cancel it and reissue under a new invoice number.')),
                'errorCode': 'INVOICE_ISSUED_IMMUTABLE',
                'fields': financial,
                'invoiceNumber': existing.get('invoiceNumber', ''),
                'useInstead': 'remark' if paid else 'cancel+reissue',
                'editable': ['customerName', 'customerPhone', 'customerEmail',
                             'shippingAddress', 'billingAddress', 'notes'],
            })

        # The original paid/cancelled amount guard, kept as a BACKSTOP rather than deleted.
        # `_is_issued` already covers every row this could catch, but the two tests differ in
        # shape and a row that somehow carries a paid payment state with no number must still
        # be refused. Canonicalised, because `paid` and `captured` are one state and this is a
        # money decision, not a document lifecycle one.
        ex_status = existing.get('status', '')
        ex_ps = pay_status.canonical(existing.get('paymentStatus', ''))
        if ex_status in ('paid', 'cancelled') or ex_ps in (pay_status.CAPTURED,
                                                           pay_status.REFUNDED):
            return _resp(400, {'error': f'Cannot modify amounts on {ex_status} invoice (paymentStatus={ex_ps})'})

    update_parts = []
    values = {}
    names = {}

    # `status` and `paymentStatus` are GONE from this list, not conditioned inside it (D5). The
    # refusal above answers before anything reaches here, so there is no state in which a client
    # body can reach either attribute. The financial fields stay listed because a DRAFT is still
    # fully editable - the issued check above is what removes them once a number exists.
    #
    # `discount` is NOT in this list: it is server-computed Delight (refused above if a client
    # sends a non-zero one), never client-writable. On the live path this is doubly protected -
    # every created invoice is ISSUED (it carries an invoiceNumber), so the immutability guard
    # above already refuses any amount edit; the Delight figure a reopen needs is the one frozen
    # on the row at creation, which the cancel + re-raise path reuses verbatim.
    allowed = ['customerName', 'customerPhone', 'paidByPhone', 'customerEmail',
               'shippingAddress', 'billingAddress', 'goodsType',
               'shipping', 'handling', 'gstRate', 'tax', 'convenienceFee', 'total',
               'gstin', 'purpose', 'notes', 'subtotal', 'orderId', 'referenceId']

    for key in allowed:
        if key in body:
            attr = f"#{key}"
            val = f":{key}"
            update_parts.append(f"{attr} = {val}")
            names[attr] = key
            v = body[key]
            values[val] = _dec(v) if isinstance(v, (int, float)) else v

    if not update_parts:
        return _resp(400, {'error': 'No fields to update'})

    values[':now'] = int(time.time())
    update_parts.append('#updatedAt = :now')
    names['#updatedAt'] = 'updatedAt'

    try:
        table.update_item(
            Key={'invoiceId': invoice_id},
            UpdateExpression='SET ' + ', '.join(update_parts),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )

        # Regenerate image if amount/customer fields changed
        regen_fields = {'subtotal', 'discount', 'shipping', 'tax', 'total', 'convenienceFee',
                        'customerName', 'customerPhone', 'paymentStatus', 'gstRate',
                        'shippingAddress', 'billingAddress', 'purpose'}
        if regen_fields & set(body.keys()):
            try:
                generate_invoice_image(invoice_id, request_id)
                logger.info(json.dumps({'event': 'invoice_image_regenerated', 'invoiceId': invoice_id, 'requestId': request_id}))
            except Exception as regen_err:
                logger.warning(f"Image regen after update failed: {regen_err}")

        return _resp(200, {'invoiceId': invoice_id, 'updated': True})
    except Exception as e:
        return _resp(500, {'error': str(e)})


def get_invoice(invoice_id: str, request_id: str) -> Dict:
    """Get a single invoice with items and assets."""
    table = dynamodb.Table(INVOICES_TABLE)
    resp = table.get_item(Key={'invoiceId': invoice_id})
    invoice = resp.get('Item')
    if not invoice:
        return _resp(404, {'error': 'Invoice not found'})

    # Get items
    items_table = dynamodb.Table(INVOICE_ITEMS_TABLE)
    items_resp = items_table.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key('invoiceId').eq(invoice_id)
    )
    items = sorted(items_resp.get('Items', []), key=lambda x: int(x.get('itemIndex', 0)))

    # Get assets
    assets_table = dynamodb.Table(INVOICE_ASSETS_TABLE)
    assets_resp = assets_table.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key('invoiceId').eq(invoice_id)
    )
    assets = assets_resp.get('Items', [])

    result = _normalize_invoice(invoice)
    result['items'] = [_normalize_item(i) for i in items]
    result['assets'] = [_normalize_asset(a) for a in assets]

    return _resp(200, {'invoice': result})


def list_invoices(params: Dict, request_id: str) -> Dict:
    """List invoices with optional filters. Full pagination to avoid DynamoDB Limit bug."""
    table = dynamodb.Table(INVOICES_TABLE)
    scan_kwargs = {}

    filters = []
    if params.get('status'):
        filters.append(boto3.dynamodb.conditions.Attr('status').eq(params['status']))
    if params.get('contactId'):
        filters.append(boto3.dynamodb.conditions.Attr('contactId').eq(params['contactId']))
    if params.get('paymentId'):
        filters.append(boto3.dynamodb.conditions.Attr('paymentId').eq(params['paymentId']))

    if filters:
        combined = filters[0]
        for f in filters[1:]:
            combined = combined & f
        scan_kwargs['FilterExpression'] = combined

    invoices = []
    while True:
        result = table.scan(**scan_kwargs)
        invoices.extend(result.get('Items', []))
        if 'LastEvaluatedKey' in result:
            scan_kwargs['ExclusiveStartKey'] = result['LastEvaluatedKey']
        else:
            break

    invoices.sort(key=lambda x: int(x.get('createdAt', 0)), reverse=True)

    return _resp(200, {'invoices': [_normalize_invoice(i) for i in invoices], 'count': len(invoices)})


# ─── Invoice Rendering (POS Receipt Style Image + PDF) ───


def _source_label(invoice: Dict) -> str:
    """The word the Source line prints: `Website` or `WhatsApp`.

    One function for all three render sites (HTML/PDF, PNG, WhatsApp caption) so a customer
    cannot be shown two different origins for one order - the same reason `/orders` derives its
    table tag and its detail rung from a single local.

    The stored value is already canonical (`create_invoice` coerces on the way in), but this
    coerces again rather than trusting it: a row written before this field existed carries no
    `channel` at all, and `order_channel.canonical` is total, so an absent or junk value prints
    `Website` instead of raising inside a renderer. Title-cased here and canonical in storage,
    because this is prose for a human and the stored word is a key for a machine.
    """
    if order_channel.canonical(invoice.get('channel')) == order_channel.CHANNEL_WHATSAPP:
        return 'WhatsApp'
    return 'Website'


def _customer_id(invoice: Dict) -> str:
    """The public customer id to print, or `''` meaning PRINT NO ROW AT ALL.

    One function for the same three render sites as `_source_label`, for the same reason - but
    note the opposite default. `_source_label` always answers, because every order genuinely has
    an origin and `website` is true of every row written so far. A customer id has NO true
    default: a row that carries none belongs to a contact created before this attribute existed,
    and the honest rendering is silence.

    So every caller must suppress its whole line on `''`. A label with nothing after it reads as
    a broken renderer, and a MINTED substitute would be worse still: it would print an id on a
    document that matches no record anywhere, which is precisely the failure
    `tests/test_invoice_number_is_rendered.py` pins for the invoice number.

    `from_contact` is reused as the validator because it never raises and re-checks the stored
    value, so a uuid7 or a non-canonical spelling written by some future caller is suppressed
    rather than printed. Reusing it also means there is one definition of "a usable customer id"
    across the CRM, the checkout, the webhook and this engine.
    """
    return customer_uuid.from_contact(invoice)


def _build_invoice_html(invoice: Dict, items: List[Dict]) -> str:
    """Build POS receipt style HTML matching the PNG receipt design.
    Single delivery address (billing = same), no Order ID shown,
    QR code, amount in words, paper tear zigzag, GST summary."""
    inv_num = invoice.get('invoiceNumber', '')
    cust_name = invoice.get('customerName', 'Customer')
    cust_phone = invoice.get('customerPhone', '')
    cust_email = invoice.get('customerEmail', '')
    ship_addr = invoice.get('shippingAddress', '')
    subtotal = float(invoice.get('subtotal', 0))
    discount = float(invoice.get('discount', 0))
    shipping_amt = float(invoice.get('shipping', 0))
    handling_amt = float(invoice.get('handling', 0))
    tax = float(invoice.get('tax', 0))
    gst_rate = float(invoice.get('gstRate', 0))
    conv_fee = float(invoice.get('convenienceFee', 0))
    total = float(invoice.get('total', 0))
    purpose = invoice.get('purpose', '') or ''
    if purpose.lower().startswith('menu_'):
        purpose = ''
    paid_at = invoice.get('paidAt', 0)
    created_at = invoice.get('createdAt', 0)
    payment_status = invoice.get('paymentStatus', 'pending')

    date_str = _ist_strftime('%d-%m-%Y', int(created_at)) if created_at else ''
    time_str = _ist_strftime('%H:%M IST', int(created_at)) if created_at else ''
    if paid_at and int(paid_at) > 0:
        paid_str = _ist_strftime('%d-%m-%Y %H:%M IST', int(paid_at))
    elif pay_status.canonical(payment_status) == pay_status.CAPTURED:
        paid_str = _ist_strftime('%d-%m-%Y %H:%M IST', int(time.time()))
    else:
        paid_str = ''

    # The two printed tax lines are the EXACT halves of the stored tax, not two independent
    # halvings - see `_split_tax_halves`. Read off the stored row rather than off the `tax` float
    # above, so the breakdown is derived from the figure the document actually carries.
    cgst, sgst = _tax_halves_rupees(invoice.get('tax', 0))
    # The discount line. `couponDiscount` holds the Delight figure; the manual remainder exists
    # only on legacy rows raised before manual entry was retired (`discount - couponDiscount`).
    coupon_discount_dec = Decimal(str(invoice.get('couponDiscount', 0) or 0))
    manual_discount_dec = Decimal(str(invoice.get('discount', 0) or 0)) - coupon_discount_dec

    # Logo as base64 data URI
    logo_html = ''
    try:
        logo_bytes = _load_logo_bytes()
        if logo_bytes:
            import base64
            b64 = base64.b64encode(logo_bytes).decode('ascii')
            logo_html = f'<img src="data:image/png;base64,{b64}" style="width:50px;height:50px;object-fit:contain" alt="Logo">'
    except Exception as _e:
        logger.debug(f"HTML logo embed failed: {_e}")

    # Extract Green Packing and Notification Fee from items
    green_packing_amt = 0.0
    notification_fee_amt = 0.0
    for it in items:
        if it.get('isCharge'):
            nm = (it.get('name', '') or '').lower()
            amt_val = float(it.get('amount', 0)) * int(it.get('quantity', 1))
            if 'green' in nm and 'pack' in nm:
                green_packing_amt = amt_val
            elif 'notification' in nm or 'alert' in nm:
                notification_fee_amt = amt_val

    # Items rows
    items_html = ''
    total_qty = 0
    for i, item in enumerate(items):
        name = item.get('name', 'Item')
        amt = float(item.get('amount', 0))
        qty = int(item.get('quantity', 1))
        total_qty += qty
        line_total = amt * qty
        items_html += f'<tr><td>{i+1}</td><td>{name}</td><td class="r">{qty}</td><td class="r">{amt:,.2f}</td><td class="r">{line_total:,.2f}</td></tr>'

    # Amount in words
    words = _amount_in_words(total)

    # GST breakdown
    gst_html = ''
    if gst_rate > 0:
        half_rate = gst_rate / 2
        taxable = subtotal - discount
        gst_html = f'''<div class="divider"></div>
        <div class="section-title">GST Summary</div>
        <div class="total-row"><span>Taxable Amount</span><span>{taxable:,.2f}</span></div>
        <div class="total-row"><span>CGST @{half_rate:.1f}%</span><span>{cgst:,.2f}</span></div>
        <div class="total-row"><span>SGST @{half_rate:.1f}%</span><span>{sgst:,.2f}</span></div>
        <div class="total-row b"><span>Total Tax</span><span>{tax:,.2f}</span></div>'''

    reference_id = invoice.get('referenceId', '')
    # Ref line removed from the customer copy (owner decision 2026-10-07): it duplicated the
    # Order id. The reference still lives on the stored invoice record; it is simply not printed.
    ref_id_html = ''

    # GST Rule 46(b): the invoice number is a mandatory particular of a tax invoice. `inv_num` has
    # been assigned at the top of this function since the renderer was written and was printed
    # NOWHERE, so every document this engine has ever produced was missing it. Empty renders no
    # row rather than `Invoice No: ` with nothing after it - an unnumbered invoice should look
    # unnumbered, not look like a rendering fault. Only `_get_next_invoice_number` may mint one;
    # a renderer that invented a substitute would advance the GST series from a read path.
    inv_num_html = f'<div class="info-row"><span>Invoice No: {inv_num}</span></div>' if inv_num else ''
    # Source always renders, because every order has an origin: absent means website, and that is
    # measured rather than assumed (see order_channel - no WhatsApp-origin order exists yet).
    source_html = f'<div class="info-row"><span>Source: {_source_label(invoice)}</span></div>'
    # The public customer id, in the Bill To block rather than the meta block: it identifies the
    # person being billed, so it belongs beside their name and not beside the invoice number.
    # Empty renders NO row - see `_customer_id`. Safe to print IN FULL, unlike the phone on the
    # next line: it is ours, opaque, carries no timestamp and is not a credential, which is what
    # lets a support agent quote it instead of reading a number back.
    cust_id = _customer_id(invoice)
    cust_id_html = (f'<div class="addr">Customer ID: {cust_id}</div>'
                    if cust_id else '')

    # Status
    status_upper = payment_status.upper()
    badge_color = '#059669' if status_upper == 'CAPTURED' else '#d97706' if status_upper == 'PENDING' else '#dc2626'
    badge_bg = '#D1FAE5' if status_upper == 'CAPTURED' else '#FEF3C7' if status_upper == 'PENDING' else '#FEE2E2'

    return f'''<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Courier New',Courier,monospace;color:#000;background:#fff;width:420px;padding:18px;font-size:12px;line-height:1.4}}
.center{{text-align:center}}
.r{{text-align:right}}
.b{{font-weight:bold}}
h1{{font-size:17px;margin:2px 0;letter-spacing:1px}}
.subtitle{{font-size:10px;color:#000;margin:1px 0}}
.divider{{border-top:1px dashed #999;margin:8px 0}}
.divider2{{border-top:2px solid #333;margin:8px 0}}
.section-title{{font-size:11px;font-weight:bold;color:#000;margin:4px 0 2px;text-transform:uppercase;letter-spacing:0.5px}}
table{{width:100%;border-collapse:collapse;font-size:11px;margin:4px 0}}
th{{text-align:left;padding:3px 2px;border-bottom:1px solid #333;font-size:10px;text-transform:uppercase;color:#000;font-weight:bold}}
th.r{{text-align:right}}
td{{padding:3px 2px;vertical-align:top;color:#000}}
.info-row{{display:flex;justify-content:space-between;font-size:11px;margin:2px 0;color:#000}}
.addr{{font-size:10px;color:#000;margin:2px 0 4px;line-height:1.3}}
.total-row{{display:flex;justify-content:space-between;font-size:12px;margin:2px 0;color:#000}}
.grand{{font-size:15px;font-weight:bold;background:#f0fdf4;padding:6px 4px;margin:4px -4px;border-top:2px solid #333;border-bottom:2px solid #333}}
.badge{{display:inline-block;padding:2px 10px;font-size:10px;font-weight:bold;border-radius:3px;color:{badge_color};background:{badge_bg};border:1px solid {badge_color}}}
.footer{{margin-top:10px;text-align:center;font-size:10px;color:#000}}
.paid-stamp{{font-size:18px;font-weight:bold;color:#059669;text-align:center;margin:6px 0;letter-spacing:2px}}
.header-row{{display:flex;align-items:flex-start;gap:12px;margin-bottom:4px}}
.header-logo{{flex-shrink:0}}
.header-text{{flex:1;text-align:center}}
.words{{font-size:10px;color:#000;margin:4px 0;padding:0 4px}}
</style></head><body>
<div class="header-row">
    <div class="header-logo">{logo_html}</div>
    <div class="header-text">
        <h1>{COMPANY['legal_name']}</h1>
        <div class="subtitle">Brand: {COMPANY['name']}</div>
        <div class="subtitle">GSTIN: {COMPANY['gstin']}</div>
        <div class="subtitle">PAN: {COMPANY['pan']}</div>
        <div class="subtitle">The W.B.S.I.D.C. Building, Unit 1/20,</div>
        <div class="subtitle">81/2/7, Phears Ln, Kolkata, WB 700012</div>
        <div class="subtitle">one@wecare.digital | +91 93309 94400</div>
    </div>
</div>
<div class="divider2"></div>
<div class="center" style="margin:4px 0"><span style="font-size:13px;font-weight:bold;letter-spacing:1px">TAX INVOICE</span></div>
<div class="divider"></div>
{inv_num_html}
<div class="info-row"><span>Date: {date_str}</span><span>{time_str}</span></div>
{ref_id_html}
{source_html}
{f'<div class="info-row b"><span>PAID: {paid_str}</span></div>' if status_upper == 'CAPTURED' and paid_str else ''}
<div class="divider"></div>
<div class="section-title">Bill To</div>
<div style="font-size:11px;font-weight:bold;color:#000">{cust_name}</div>
{cust_id_html}
<div class="addr">{cust_phone}{(' | ' + cust_email) if cust_email else ''}</div>
{f'<div class="section-title">Address</div><div class="addr">{ship_addr}</div>' if ship_addr else ''}
<div class="divider"></div>
<table>
    <thead><tr><th>#</th><th>Item</th><th class="r">Qty</th><th class="r">Rate</th><th class="r">Amount</th></tr></thead>
    <tbody>{items_html}</tbody>
</table>
<div class="divider"></div>
<div class="total-row"><span>Subtotal</span><span>{subtotal:,.2f}</span></div>
{'<div class="total-row"><span>Promo</span><span>-' + f'{manual_discount_dec:,.2f}' + '</span></div>' if manual_discount_dec else ''}
{'<div class="total-row"><span>Delight</span><span>-' + f'{coupon_discount_dec:,.2f}' + '</span></div>' if coupon_discount_dec else ''}
{'<div class="total-row"><span>Express</span><span>' + f'{shipping_amt:,.2f}' + '</span></div>' if shipping_amt else ''}
{'<div class="total-row"><span>Green Packing</span><span>' + f'{green_packing_amt:,.2f}' + '</span></div>' if green_packing_amt else ''}
{'<div class="total-row"><span>Notification Fee</span><span>' + f'{notification_fee_amt:,.2f}' + '</span></div>' if notification_fee_amt else ''}
{'<div class="total-row"><span>Handling</span><span>' + f'{handling_amt:,.2f}' + '</span></div>' if handling_amt else ''}
<div class="total-row"><span>CGST @{gst_rate/2:.1f}%</span><span>{cgst:,.2f}</span></div>
<div class="total-row"><span>SGST @{gst_rate/2:.1f}%</span><span>{sgst:,.2f}</span></div>
{'<div class="total-row"><span>Conv Fee</span><span>' + f'{conv_fee:,.2f}' + '</span></div>' if conv_fee else ''}
<div class="total-row grand"><span>Total ({total_qty} items)</span><span>&#8377; {total:,.2f}</span></div>
<div class="words">{words}</div>
{gst_html}
<div class="divider2"></div>
{'<div class="paid-stamp">* * *  PAID  * * *</div>' if status_upper == 'CAPTURED' else ''}
{'<div class="center" style="font-size:11px;margin:2px 0">Paid on: ' + paid_str + '</div>' if status_upper == 'CAPTURED' and paid_str else ''}
{'<div class="center b" style="font-size:12px;margin:4px 0">PAYMENT PENDING</div>' if status_upper == 'PENDING' else ''}
<div class="divider2"></div>
<div class="footer">
    <div style="font-size:12px;font-weight:bold;margin:6px 0">Thank You!</div>
    <div>Visit Again!</div>
    <div style="margin-top:2px">wecare.digital/customerservice</div>
</div>
</body></html>'''




# ─── Rendered-asset versioning (D4) ───

#: What separates an asset row's base type from its version. `image` / `image#v2` / `image#v3`.
#:
#: The `InvoiceAssets` key is (invoiceId HASH, assetType RANGE), so a version lives in the SORT
#: KEY and a new rendition is a new ROW rather than an overwrite of the old one. The base row
#: (`image`, `pdf`) keeps pointing at the FIRST rendition - the document of record - which is
#: also what `whatsapp-business-api/flows/customer_invoice.py` compares against by exact key and
#: what `ecommerce/customer-invoice` point-reads. Versioning by overwriting the base row would
#: have broken both of those while claiming to protect the document.
_ASSET_VERSION_SEPARATOR = '#v'


def _next_asset_version(invoice_id: str, asset_type: str, request_id: str) -> int:
    """The next version number for this invoice's `asset_type`, 1 when nothing is on record.

    The base row counts as version 1, so the first render of an issued invoice still writes the
    un-suffixed key and the un-suffixed row.

    A read failure does NOT fall back to 1. Returning 1 would hand back the base key and
    overwrite the issued document of record, which is the exact thing this function exists to
    prevent - so the fallback is the clock, which is monotonic, cannot collide with a small
    version number, and is never the base key. The plan permits either scheme.
    """
    prefix = f'{asset_type}{_ASSET_VERSION_SEPARATOR}'
    try:
        assets_table = dynamodb.Table(INVOICE_ASSETS_TABLE)
        rows = assets_table.query(
            KeyConditionExpression=boto3.dynamodb.conditions.Key('invoiceId').eq(invoice_id)
        ).get('Items', [])
    except Exception as error:  # noqa: BLE001
        logger.warning(json.dumps({
            'event': 'invoice_asset_version_unreadable', 'invoiceId': invoice_id,
            'assetType': asset_type, 'error': type(error).__name__, 'requestId': request_id,
        }))
        return int(time.time())

    highest = 0
    for row in rows:
        stored = str(row.get('assetType', '') or '')
        if stored == asset_type:
            highest = max(highest, 1)
        elif stored.startswith(prefix):
            suffix = stored[len(prefix):]
            if suffix.isdigit():
                highest = max(highest, int(suffix))
    return highest + 1


def _asset_target(invoice: Dict, *, invoice_id: str, asset_type: str, stem: str, extension: str,
                  request_id: str) -> tuple:
    """`(s3_key, asset_row_key)` for this rendition.

    An UNISSUED draft keeps the current behaviour exactly: the base key, overwritten in place.
    There is no document of record yet, so a version history of a draft is noise - and the
    `.png` key of a draft is what the WhatsApp flow expects to find.

    An ISSUED invoice gets a NEW key, so the previous object stays in S3 and the previous
    `InvoiceAssets` row stays untouched. A re-render after issue happens for honest reasons (a
    corrected delivery address, a logo fix) and for dishonest ones; either way the rendition the
    customer was sent must remain retrievable, because it is the document they hold.
    """
    base_key = f'{stem}.{extension}'
    if not _is_issued(invoice):
        return base_key, asset_type
    version = _next_asset_version(invoice_id, asset_type, request_id)
    if version <= 1:
        return base_key, asset_type
    return f'{stem}-v{version}.{extension}', f'{asset_type}{_ASSET_VERSION_SEPARATOR}{version}'


# ─── Generate Invoice Image (PNG) ───
# Image is the sole newly-generated customer invoice asset; PDF generation is retired.

def generate_invoice_image(invoice_id: str, request_id: str) -> Dict:
    """Render invoice as POS receipt PNG using PIL, upload to S3."""
    if not invoice_id:
        return _resp(400, {'error': 'invoiceId required'})

    # Fetch invoice + items
    table = dynamodb.Table(INVOICES_TABLE)
    resp = table.get_item(Key={'invoiceId': invoice_id})
    invoice = resp.get('Item')
    if not invoice:
        return _resp(404, {'error': 'Invoice not found'})

    items_table = dynamodb.Table(INVOICE_ITEMS_TABLE)
    items_resp = items_table.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key('invoiceId').eq(invoice_id)
    )
    items = sorted(items_resp.get('Items', []), key=lambda x: int(x.get('itemIndex', 0)))

    # Render to PNG using pure-Python bitmap font (zero dependencies, proven working)
    png_bytes = _generate_receipt_png(invoice, items)

    # S3 key uses WhatsApp payment reference ID (unguessable, unique), and carries a VERSION
    # once the invoice is issued so a re-render never writes over the document of record.
    ref_id = invoice.get('referenceId', invoice_id)
    s3_key, asset_row_key = _asset_target(
        invoice, invoice_id=invoice_id, asset_type='image',
        stem=f"{INVOICE_PREFIX}wecare-digital-{ref_id}", extension='png',
        request_id=request_id)

    s3.put_object(
        Bucket=MEDIA_BUCKET,
        Key=s3_key,
        Body=png_bytes,
        ContentType='image/png',
        CacheControl='max-age=86400',
    )

    # Signed and expiring, not `https://{CDN_DOMAIN}/{s3_key}`. The key is now under the gated
    # root, so a CDN URL would be a dead link rather than a disclosure — but a dead link is its
    # own bug, and the correct answer is the one that works AND expires.
    image_url = _signed_invoice_url(s3_key, invoice_id, request_id)

    # Store asset record.
    #
    # `s3Key` is the source of truth and `url` is deliberately NOT stored. A presigned URL
    # expires, so persisting one produces a record that is correct when written and quietly
    # broken later — and `send_invoice_whatsapp` reads this row on its second call, so it would
    # have handed out an expired link. The key is permanent; the URL is minted per response.
    assets_table = dynamodb.Table(INVOICE_ASSETS_TABLE)
    assets_table.put_item(Item={
        'invoiceId': invoice_id,
        # `image` for a draft or a first rendition, `image#v<n>` for a re-render after issue —
        # an ADDITIONAL row, so the earlier rendition stays resolvable.
        'assetType': asset_row_key,
        's3Key': s3_key,
        'contentType': 'image/png',
        'version': int(time.time()),
        'generatedAt': int(time.time()),
    })

    # The URL is a bearer grant, so the key is logged and the URL is not.
    logger.info(json.dumps({'event': 'invoice_image_generated', 'invoiceId': invoice_id,
                            's3Key': s3_key, 'assetType': asset_row_key,
                            'signed': bool(image_url), 'requestId': request_id}))
    return _resp(200, {'invoiceId': invoice_id, 'imageUrl': image_url, 's3Key': s3_key})


def _signed_invoice_url(s3_key: str, invoice_id: str, request_id: str) -> str:
    """A short-lived presigned GET for a rendered invoice, or `''`.

    A presigned URL addresses S3 directly, so it works even though CloudFront denies the gated
    root wholesale — which is what makes moving the prefix possible without losing the ability to
    show an invoice to the staff member who asked for it.

    Returns `''` rather than falling back to a CDN URL. `receipt_links` raises instead of
    returning a public fallback for exactly this reason: an invoice that cannot be linked securely
    is an inconvenience, and one served over a permanent public URL is a disclosure.
    """
    if not s3_key:
        return ''
    try:
        from lambda_utils import receipt_links
        return receipt_links.signed_url(s3, bucket=MEDIA_BUCKET, key=s3_key,
                                        filename=f"invoice-{invoice_id}.png")
    except Exception as error:  # noqa: BLE001
        # Type only: a presign failure message can echo the key and the bucket.
        logger.warning(json.dumps({'event': 'invoice_link_sign_failed',
                                   'error': type(error).__name__,
                                   'invoiceId': invoice_id, 'requestId': request_id}))
        return ''


# ─── Receipt PNG Rendering ───
# Uses monospace font, logo + PAID icon from S3, WD reference format.
# Compact POS thermal receipt style for WhatsApp chat visibility.


def _generate_receipt_png(invoice: Dict, items: List[Dict]) -> bytes:
    """Generate POS thermal receipt as PNG image.

    Layout: Logo left + company header, invoice meta, bill/ship to,
    items table, totals, GST summary, PAID icon, footer.
    Monospace font, 2x scaled for WhatsApp readability.
    """
    from PIL import Image, ImageDraw, ImageFont

    # Read the flag once, here, rather than at module scope — see
    # `_transparent_receipt_enabled` for why. False keeps today's grey-backdrop output
    # byte-for-byte.
    transparent = _transparent_receipt_enabled()

    if transparent:
        from pathlib import Path
        import receipt_layout
        return receipt_layout.render(
            invoice, items, company=COMPANY,
            font_path=Path(__file__).parent / 'fonts' / 'DotGothic16-Regular.ttf',
            ist_strftime=_ist_strftime, canonical_status=pay_status.canonical,
            amount_in_words=_amount_in_words, customer_id=_customer_id(invoice),
            source_label=_source_label(invoice))

    # ── Font setup (monospace — download DejaVu Sans Mono from S3 on Lambda) ──
    _font_cache = getattr(_generate_receipt_png, '_font_cache', {})
    _generate_receipt_png._font_cache = _font_cache

    def _get_font_bytes(bold=False):
        key = 'bold' if bold else 'regular'
        if key not in _font_cache:
            s3_key = media_paths.public(
                f"stream/media/fonts/DejaVuSansMono{'-Bold' if bold else ''}.ttf")
            try:
                obj = s3.get_object(Bucket=MEDIA_BUCKET, Key=s3_key)
                _font_cache[key] = obj['Body'].read()
            except Exception as _e:
                logger.debug(f"Font S3 load failed ({s3_key}): {_e}")
                _font_cache[key] = None
        return _font_cache[key]

    def _mono(size, bold=False):
        # 1. Try S3-hosted DejaVu Sans Mono
        fb = _get_font_bytes(bold)
        if fb:
            try:
                return ImageFont.truetype(io.BytesIO(fb), size)
            except Exception as _e:
                logger.debug(f"Font truetype from S3 bytes failed: {_e}")
        # 2. Try system fonts (Windows dev)
        names = ['consolab.ttf', 'courbd.ttf'] if bold else ['consola.ttf', 'cour.ttf']
        for n in names:
            try:
                return ImageFont.truetype(n, size)
            except Exception as _e:
                logger.debug(f"System font {n} not available: {_e}")
                continue
        # 3. Pillow 10.1+ built-in default at requested size
        try:
            return ImageFont.load_default(size=size)
        except TypeError:
            return ImageFont.load_default()

    FONT_SZ = 14
    F    = _mono(FONT_SZ)           # Body — regular
    FB   = _mono(FONT_SZ, True)     # Labels/headings — bold
    FLG  = _mono(FONT_SZ + 3, True) # Title — bold large
    FSM  = _mono(FONT_SZ - 2)       # Secondary — regular small
    FXS  = _mono(FONT_SZ - 4)       # Extra small — regular

    CHARS  = 48
    LINE_H = 18
    PX     = 14
    PY     = 10

    def _tw(draw, text, font):
        try:
            bb = draw.textbbox((0, 0), text, font=font)
            return bb[2] - bb[0]
        except Exception as _e:
            logger.debug(f"textbbox fallback: {_e}")
            return len(text) * 8

    # ── Build receipt lines ──
    # Each: (content, font, align)  align: L/C/LR/LOGO/PAID_ICON
    lines = []

    def L(t, f=F):    lines.append((t, f, 'L'))
    def C(t, f=F):    lines.append((t, f, 'C'))
    def LR(l, r, f=F): lines.append(((l, r), f, 'LR'))
    def SEP():         lines.append(('-' * CHARS, F, 'C'))
    def DSEP():        lines.append(('=' * CHARS, F, 'C'))
    def BL():          lines.append(('', F, 'L'))

    # ── Extract invoice data ──
    created_at = invoice.get('createdAt', 0)
    date_str = _ist_strftime('%d-%m-%Y', int(created_at)) if created_at else ''
    time_str = _ist_strftime('%H:%M IST', int(created_at)) if created_at else ''
    order_id = invoice.get('orderId', '')
    reference_id = invoice.get('referenceId', '')
    payment_id = invoice.get('paymentId', '')
    purpose = invoice.get('purpose', '') or ''
    # Clean up raw menu action IDs stored as purpose (e.g. "Menu_Pay")
    if purpose.lower().startswith('menu_'):
        purpose = ''
    cust_name = invoice.get('customerName', 'Customer')
    cust_phone = invoice.get('customerPhone', '')
    cust_email = invoice.get('customerEmail', '')
    bill_addr = invoice.get('billingAddress', '')
    ship_addr = invoice.get('shippingAddress', '')
    subtotal = float(invoice.get('subtotal', 0))
    discount_val = float(invoice.get('discount', 0))
    shipping_amt = float(invoice.get('shipping', 0))
    tax = float(invoice.get('tax', 0))
    gst_rate = float(invoice.get('gstRate', 0))
    conv_fee = float(invoice.get('convenienceFee', 0))
    total = float(invoice.get('total', 0))
    cgst = tax / 2
    sgst = tax / 2
    payment_status = invoice.get('paymentStatus', 'pending').upper()
    paid_at = invoice.get('paidAt', 0)

    # Extract Green Packing and Notification Fee from items (stored as charge line items)
    green_packing_amt = 0.0
    notification_fee_amt = 0.0
    for it in items:
        if it.get('isCharge'):
            nm = (it.get('name', '') or '').lower()
            amt_val = float(it.get('amount', 0)) * int(it.get('quantity', 1))
            if 'green' in nm and 'pack' in nm:
                green_packing_amt = amt_val
            elif 'notification' in nm or 'alert' in nm:
                notification_fee_amt = amt_val

    # ═══════════════════════════════════════════════
    # ═══ REDESIGNED RECEIPT — consistent design system
    # ═══════════════════════════════════════════════
    # Font tiers: Title=17px, Body=14px, Small=12px (no tiny 10px)
    # Line heights: Title=24, Body=20, Small=17
    # Section gap: 6px extra after separators

    # ── Extract invoice data ──
    created_at = invoice.get('createdAt', 0)
    date_str = _ist_strftime('%d-%m-%Y', int(created_at)) if created_at else ''
    time_str = _ist_strftime('%H:%M IST', int(created_at)) if created_at else ''
    reference_id = invoice.get('referenceId', '')
    purpose = invoice.get('purpose', '') or ''
    if purpose.lower().startswith('menu_'):
        purpose = ''
    cust_name = invoice.get('customerName', 'Customer')
    cust_phone = invoice.get('customerPhone', '')
    cust_email = invoice.get('customerEmail', '')
    ship_addr = invoice.get('shippingAddress', '')
    subtotal = float(invoice.get('subtotal', 0))
    discount_val = float(invoice.get('discount', 0))
    shipping_amt = float(invoice.get('shipping', 0))
    tax = float(invoice.get('tax', 0))
    gst_rate = float(invoice.get('gstRate', 0))
    conv_fee = float(invoice.get('convenienceFee', 0))
    total = float(invoice.get('total', 0))
    cgst = tax / 2
    sgst = tax / 2
    payment_status = invoice.get('paymentStatus', 'pending').upper()
    paid_at = invoice.get('paidAt', 0)

    green_packing_amt = 0.0
    notification_fee_amt = 0.0
    for it in items:
        if it.get('isCharge'):
            nm = (it.get('name', '') or '').lower()
            amt_val = float(it.get('amount', 0)) * int(it.get('quantity', 1))
            if 'green' in nm and 'pack' in nm:
                green_packing_amt = amt_val
            elif 'notification' in nm or 'alert' in nm:
                notification_fee_amt = amt_val

    # ── Calculate canvas width ──
    tmp_draw = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    try:
        bb = tmp_draw.textbbox((0, 0), 'M', font=F)
        CW = bb[2] - bb[0]
    except Exception:
        CW = 9

    W = CHARS * CW + PX * 2
    est_h = 1200  # generous estimate, will crop
    # (252, 252, 250) is the paper colour measured on the owner-approved specimen; plain
    # white stays the default so the flag-off output is unchanged.
    img = Image.new('RGB', (W, est_h), (252, 252, 250) if transparent else (255, 255, 255))
    draw = ImageDraw.Draw(img)
    logo_bytes = _load_logo_bytes()

    y = PY + 4
    CLR_BLK = (0, 0, 0)
    CLR_GRY = (0, 0, 0)  # All text black — no grey

    def _center(txt, font, color=CLR_BLK):
        nonlocal y
        tw = _tw(draw, txt, font)
        draw.text(((W - tw) // 2, y), txt, fill=color, font=font)

    def _left(txt, font, color=CLR_BLK):
        nonlocal y
        draw.text((PX, y), txt, fill=color, font=font)

    def _lr(lt, rt, font, color=CLR_BLK):
        nonlocal y
        draw.text((PX, y), lt, fill=color, font=font)
        rw = _tw(draw, rt, font)
        draw.text((W - PX - rw, y), rt, fill=color, font=font)

    def _sep():
        nonlocal y
        _center('-' * CHARS, F, CLR_GRY)
        y += LINE_H

    def _dsep():
        nonlocal y
        _center('=' * CHARS, F, CLR_GRY)
        y += LINE_H

    # ═══ HEADER — logo left-aligned, company info centered in remaining space ═══
    LOGO_SZ = 50
    if logo_bytes:
        try:
            logo_img = Image.open(io.BytesIO(logo_bytes)).convert('RGBA')
            logo_img = logo_img.resize((LOGO_SZ, LOGO_SZ), Image.LANCZOS)
            img.paste(logo_img, (PX, y - 2), logo_img)
        except Exception:
            pass

    tx = PX + LOGO_SZ + 12  # text area starts after logo + gap
    avail_w = W - tx - PX   # available width for centered text

    def _hdr_center(txt, font, color=CLR_BLK):
        """Center text within the header area (right of logo)."""
        tw = _tw(draw, txt, font)
        x = tx + max(0, (avail_w - tw) // 2)
        draw.text((x, y), txt, fill=color, font=font)

    # Legal name — centered in header area, bold (owner-approved mockup 2026-10-07)
    _hdr_center(COMPANY['legal_name'], FLG)
    y += 22
    # Fixed brand line, always "WECARE.DIGITAL", never derived from entryPoint.
    _hdr_center(f"Brand: {COMPANY['name']}", FSM)
    y += LINE_H
    # GSTIN — regular, grey
    _hdr_center(f"GSTIN: {COMPANY['gstin']}", FSM, CLR_GRY)
    y += LINE_H
    # PAN — regular, grey (GST Rule / owner mockup: PAN under GSTIN)
    _hdr_center(f"PAN: {COMPANY['pan']}", FSM, CLR_GRY)
    y += LINE_H
    # Address — 2 fixed lines, regular, grey
    _hdr_center("The W.B.S.I.D.C. Building, Unit 1/20,", FSM, CLR_GRY)
    y += LINE_H
    _hdr_center("81/2/7, Phears Ln, Kolkata, WB 700012", FSM, CLR_GRY)
    y += LINE_H
    # Contact — single line, regular, grey
    _hdr_center(f"one@wecare.digital | +91 93309 94400", FSM, CLR_GRY)
    y += LINE_H + 2

    # ═══ INVOICE TITLE ═══
    _dsep()
    _center("TAX INVOICE", FLG)
    y += LINE_H + 4
    _sep()

    # ═══ INVOICE META ═══
    # GST Rule 46(b) first: the invoice number leads the meta block, which is where a reader
    # looks for it. The PNG never read `invoiceNumber` at all before this, so the image sent to
    # the customer on WhatsApp carried no number. Read here rather than in the extraction block
    # above so this line and the two render sites that match it stay in one place.
    # `str(... or '')` because DynamoDB hands back whatever was stored and an f-string would
    # happily print `None`.
    inv_num = str(invoice.get('invoiceNumber', '') or '')
    if inv_num:
        _left(f"Invoice No: {inv_num}", FB)
        y += LINE_H
    _lr(f"Date: {date_str}", time_str, F)
    y += LINE_H
    # Ref line removed (owner decision 2026-10-07): it duplicated the Order id on the customer
    # copy. Order id is shown below; the reference still lives on the stored record.
    # Source per docs/invoice-layout.md section 2. Unconditional: every order has an origin, and
    # `_source_label` is total, so there is no empty-label case to guard.
    _left(f"Source: {_source_label(invoice)}", F)
    y += LINE_H
    # Brand is now the FIXED header line "Brand: WECARE.DIGITAL" (set in the header block),
    # never derived from entryPoint. The old entryPoint-derived Brand line is removed.
    # Note line: show request/submission reference (clean format, no #)
    notes = invoice.get('notes', '')
    if notes:
        # Strip "Request #" prefix → just show the reference number
        clean_note = notes.replace('Request #', '').replace('Request#', '').strip()
        _left(f"Note: {clean_note[:40]}", FSM)
        y += LINE_H
    if payment_status == 'CAPTURED':
        if paid_at and int(paid_at) > 0:
            paid_str = _ist_strftime('%d-%m-%Y %H:%M IST', int(paid_at))
        else:
            paid_str = _ist_strftime('%d-%m-%Y %H:%M IST', int(time.time()))
        _left(f"PAID: {paid_str}", FB)
        y += LINE_H
    elif payment_status not in ('PENDING', ''):
        _left(f"Status: {payment_status}", FB)
        y += LINE_H
    _sep()

    # ═══ BILL TO ═══
    _left("Bill To:", FB)
    y += LINE_H
    _left(f"  {cust_name}", F)
    y += LINE_H
    # The public customer id, between the name and the phone, exactly as in the HTML - one
    # layout, two renderers. Skipped entirely when absent (see `_customer_id`), which is why the
    # `y += LINE_H` is inside the branch: advancing the cursor for a line that was never drawn
    # would leave a blank gap in the receipt.
    _cust_id = _customer_id(invoice)
    if _cust_id:
        _left(f"  Customer ID: {_cust_id}", FSM)
        y += LINE_H
    contact_line = f"  {cust_phone}"
    if cust_email:
        contact_line += f" | {cust_email}"
    _left(contact_line[:CHARS], F)
    y += LINE_H

    # Address: try invoice fields first, then shippingAddress string, then contact lookup
    display_addr = ''
    addr_line1 = invoice.get('addressLine1', '')
    addr_city = invoice.get('city', '')
    addr_state = invoice.get('state', '')
    addr_postal = invoice.get('postalCode', '')
    if addr_line1 and addr_city:
        addr_parts = [addr_line1]
        if invoice.get('addressLine2'):
            addr_parts.append(invoice['addressLine2'])
        addr_parts.append(f"{addr_city}, {addr_state or ''} {addr_postal or ''}".strip().rstrip(','))
        display_addr = ', '.join(p for p in addr_parts if p)
    elif ship_addr:
        # Try parsing JSON address
        try:
            import json as _json
            addr_obj = _json.loads(ship_addr) if ship_addr.strip().startswith('{') else {}
            if addr_obj.get('city'):
                parts = [addr_obj.get('address', ''), addr_obj.get('city', ''),
                         addr_obj.get('state', ''), addr_obj.get('in_pin_code', '')]
                display_addr = ', '.join(p for p in parts if p)
        except Exception:
            display_addr = ship_addr
    elif bill_addr:
        display_addr = bill_addr

    # Fallback: look up address from contact record
    if not display_addr and cust_phone:
        try:
            contacts_tbl = dynamodb.Table(CONTACTS_TABLE)
            clean_ph = cust_phone.replace('+', '').replace(' ', '').replace('-', '')
            for variant in [f'+{clean_ph}', clean_ph]:
                try:
                    cr = contacts_tbl.query(
                        IndexName='phone-index',
                        KeyConditionExpression='phone = :p',
                        ExpressionAttributeValues={':p': variant},
                        Limit=1,
                    )
                    c_items = cr.get('Items', [])
                    if c_items:
                        c = c_items[0]
                        c_parts = [c.get('addressLine1', ''), c.get('addressLine2', ''),
                                   c.get('city', ''), c.get('state', ''), c.get('pincode', '')]
                        c_addr = ', '.join(p for p in c_parts if p)
                        if c_addr and len(c_addr) > 5:
                            display_addr = c_addr
                        break
                except Exception:
                    pass
        except Exception:
            pass

    if display_addr:
        _left("Address:", FB)
        y += LINE_H
        for addr_line in _wrap_text(display_addr, CHARS - 2):
            _left(f"  {addr_line}", F)
            y += LINE_H
    _sep()

    # ═══ ITEMS TABLE ═══
    _left(f"{'#':<3}{'Item':<22}{'Qty':>4}{'Rate':>10}{'Amt':>9}", FB)
    y += LINE_H
    _sep()
    total_qty = 0
    for idx, item in enumerate(items):
        name = item.get('name', 'Item')[:20]
        amt = float(item.get('amount', 0))
        qty = int(item.get('quantity', 1))
        total_qty += qty
        line_total = amt * qty
        _left(f"{idx+1:<3}{name:<22}{qty:>4}{amt:>10,.2f}{line_total:>9,.2f}", F)
        y += LINE_H
    _sep()

    # ═══ TOTALS ═══
    #
    # The discount line. `couponDiscount` holds the Delight figure; the manual remainder exists
    # only on legacy rows raised before manual entry was retired (`discount - couponDiscount`).
    coupon_discount_dec = Decimal(str(invoice.get('couponDiscount', 0) or 0))
    manual_discount_dec = Decimal(str(invoice.get('discount', 0) or 0)) - coupon_discount_dec

    _lr("Subtotal", f"{subtotal:,.2f}", F)
    y += LINE_H
    if manual_discount_dec:
        _lr("Promo", f"-{manual_discount_dec:,.2f}", F)
        y += LINE_H
    if coupon_discount_dec:
        _lr("Delight", f"-{coupon_discount_dec:,.2f}", F)
        y += LINE_H
    if shipping_amt:
        _lr("Express", f"{shipping_amt:,.2f}", F)
        y += LINE_H
    if green_packing_amt:
        _lr("Green Packing", f"{green_packing_amt:,.2f}", F)
        y += LINE_H
    if notification_fee_amt:
        _lr("Notification Fee", f"{notification_fee_amt:,.2f}", F)
        y += LINE_H
    if gst_rate > 0:
        _lr(f"CGST @{gst_rate/2:.0f}%", f"{cgst:,.2f}", F)
        y += LINE_H
        _lr(f"SGST @{gst_rate/2:.0f}%", f"{sgst:,.2f}", F)
        y += LINE_H
    if conv_fee:
        _lr("Conv Fee", f"{conv_fee:,.2f}", F)
        y += LINE_H
    _dsep()

    # ═══ GRAND TOTAL ═══
    # Highlight background
    draw.rectangle([(PX - 4, y - 2), (W - PX + 4, y + LINE_H + 4)], fill=(240, 253, 244))
    _lr(f"TOTAL ({total_qty} items)", f"\u20b9 {total:,.2f}", FLG)
    y += LINE_H + 8

    # Amount in words
    words = _amount_in_words(total)
    for wline in _wrap_text(words, CHARS - 2):
        _left(f"  {wline}", FSM)
        y += LINE_H - 2
    y += 4
    _dsep()

    # ═══ GST SUMMARY ═══
    if gst_rate > 0:
        taxable = subtotal - discount_val
        _center("GST Summary", FB)
        y += LINE_H
        _lr("Taxable Amount", f"{taxable:,.2f}", F)
        y += LINE_H
        _lr(f"CGST @{gst_rate/2:.1f}%", f"{cgst:,.2f}", F)
        y += LINE_H
        _lr(f"SGST @{gst_rate/2:.1f}%", f"{sgst:,.2f}", F)
        y += LINE_H
        _lr("Total Tax", f"{tax:,.2f}", FB)
        y += LINE_H
        _sep()

    # ═══ PAID STAMP + PAYMENT DETAILS ═══
    if payment_status == 'CAPTURED':
        _center("* * *  PAID  * * *", FLG)
        y += LINE_H + 2
        if paid_at and int(paid_at) > 0:
            paid_str = _ist_strftime('%d-%m-%Y %H:%M IST', int(paid_at))
        else:
            paid_str = _ist_strftime('%d-%m-%Y %H:%M IST', int(time.time()))
        _center(f"Paid on: {paid_str}", F)
        y += LINE_H
    elif payment_status == 'PENDING':
        _center("PAYMENT PENDING", FB)
        y += LINE_H
    elif payment_status:
        _center(f"Status: {payment_status}", FB)
        y += LINE_H

    # ═══ QR CODE — links to customerservice ═══
    #
    # Served from a pre-rendered S3 object, not generated. The runtime `import
    # qrcode` branch that used to lead this block was removed on 2026-09-24:
    #
    #   * `qrcode` was in no requirements file and in no attached layer (the only
    #     layer on this function is pillow-python312), so the import failed on
    #     every single invoice and the code always fell through to here anyway.
    #   * It logged at WARNING each time, for a condition that was permanent and
    #     not actionable. A warning that always fires trains people to ignore
    #     warnings.
    #   * The encoded value is the constant `[retired public path]`.
    #     Every invoice would have produced a byte-identical image, so generating
    #     it per render was work to reproduce a fixed asset.
    #
    # Adding the dependency would have been the wrong repair for the same reason:
    # the right artifact for a constant is a file. `stream/media/m/qr-customerservice.png`
    # is present (459 bytes, image/png, verified 2026-09-24).
    qr_rendered = False
    try:
        qr_s3_img = _load_s3_image(media_paths.public('stream/media/m/qr-customerservice.png'))
        if qr_s3_img:
            qr_s3_img = qr_s3_img.resize((80, 80), Image.LANCZOS).convert('RGB')
            qr_x = (W - 80) // 2
            img.paste(qr_s3_img, (qr_x, y))
            y += 84
            qr_rendered = True
    except Exception as qr_err:
        # Debug, not warning: the text fallback below is a complete substitute, so
        # a missing image degrades the invoice rather than breaking it.
        logger.debug(f"QR image load failed: {qr_err}")

    # If the image is unavailable, the URL in text carries the same information.
    if not qr_rendered:
        _center("Scan QR or visit:", FSM, CLR_GRY)
        y += LINE_H
        _center("wecare.digital/customerservice", F)
        y += LINE_H

    # ═══ FOOTER ═══
    _sep()
    _center("Thank You!", FLG)
    y += LINE_H + 2
    _center("Visit Again!", F, CLR_GRY)
    y += LINE_H
    _center("wecare.digital/customerservice", FSM, CLR_GRY)
    y += LINE_H
    _dsep()

    # ═══ CROP + ZIGZAG + SCALE ═══
    y += PY
    img = img.crop((0, 0, W, y))

    if transparent:
        # ── Owner-approved appearance: irregular torn paper on a TRANSPARENT canvas ──
        # Reference specimen (approved 2026-10-08):
        #   https://wecare.digital/get/o/public/wa-tpl/img/invoice-receipt.png
        # Measured on it, and pinned by tests/test_receipt_transparent_background.py:
        # corner alpha 0, paper (252, 252, 250, 255). The grey (200, 200, 200) backdrop
        # in the branch below is the grey the owner asked to remove.
        import random as _random  # noqa: PLC0415
        from PIL import ImageFilter  # noqa: PLC0415

        TEAR_H = 12  # vertical room the torn edge is allowed to wander in

        # Seeded deliberately: the tear is APPEARANCE ONLY and must be reproducible, so
        # re-rendering one invoice does not produce a different edge. `random` is never
        # used for an identifier here — `secrets` remains mandatory for anything that
        # must be unique per call (.kiro/steering/lambda-snapstart-deploy.md).
        rnd = _random.Random(7)

        def _rough_edge(base: int):
            """(x, y) points across the width forming an irregular torn edge at `base`."""
            pts = []
            x = 0
            while x <= W:
                jitter = rnd.randint(-TEAR_H + 6, TEAR_H - 6)
                micro = rnd.randint(-2, 2)
                pts.append((x, base + jitter + micro))
                x += 7 + rnd.randint(-2, 3)
            pts.append((W, base + rnd.randint(-TEAR_H + 6, TEAR_H - 6)))
            return pts

        strip_h = img.height + TEAR_H * 2

        # The alpha channel IS the torn paper: 255 inside the polygon, 0 outside.
        mask = Image.new('L', (W, strip_h), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.polygon(
            _rough_edge(TEAR_H) + list(reversed(_rough_edge(strip_h - TEAR_H))),
            fill=255)
        mask = mask.filter(ImageFilter.GaussianBlur(0.6))  # soften the torn fibres

        paper = Image.new('RGBA', (W, strip_h), (252, 252, 250, 255))
        paper.paste(img.convert('RGBA'), (0, TEAR_H))
        paper.putalpha(mask)
        img = paper
    else:
        # ── Add paper tear zigzag effect (top and bottom) ──
        ZIGZAG_H = 8  # height of zigzag teeth
        ZIGZAG_W = 12  # width of each tooth
        tear_img = Image.new('RGB', (W, img.height + ZIGZAG_H * 2), (200, 200, 200))  # grey background
        tear_draw = ImageDraw.Draw(tear_img)

        # Top zigzag — white teeth on grey
        for x in range(0, W, ZIGZAG_W):
            tear_draw.polygon([
                (x, ZIGZAG_H),
                (x + ZIGZAG_W // 2, 0),
                (x + ZIGZAG_W, ZIGZAG_H),
            ], fill=(255, 255, 255))

        # Bottom zigzag — white teeth on grey
        bottom_y = img.height + ZIGZAG_H
        for x in range(0, W, ZIGZAG_W):
            tear_draw.polygon([
                (x, bottom_y),
                (x + ZIGZAG_W // 2, bottom_y + ZIGZAG_H),
                (x + ZIGZAG_W, bottom_y),
            ], fill=(255, 255, 255))

        # Paste the receipt content between the zigzag edges
        tear_img.paste(img, (0, ZIGZAG_H))
        img = tear_img

    # Scale 2x for WhatsApp readability
    final_w = W * 2
    final_h = img.height * 2
    img = img.resize((final_w, final_h), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def _amount_in_words(amount: float) -> str:
    """Convert amount to Indian English words. e.g. 628.94 → 'Rupees Six Hundred Twenty-Eight and Ninety-Four Paise Only'"""
    ones = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine',
            'Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen',
            'Seventeen', 'Eighteen', 'Nineteen']
    tens = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']

    def _two_digits(n):
        if n < 20:
            return ones[n]
        return (tens[n // 10] + '-' + ones[n % 10]).rstrip('-')

    def _three_digits(n):
        if n == 0:
            return ''
        if n < 100:
            return _two_digits(n)
        return ones[n // 100] + ' Hundred' + (' ' + _two_digits(n % 100) if n % 100 else '')

    def _indian_number(n):
        """Indian numbering: lakhs and crores."""
        if n == 0:
            return 'Zero'
        parts = []
        if n >= 10000000:
            parts.append(_two_digits(n // 10000000) + ' Crore')
            n %= 10000000
        if n >= 100000:
            parts.append(_two_digits(n // 100000) + ' Lakh')
            n %= 100000
        if n >= 1000:
            parts.append(_two_digits(n // 1000) + ' Thousand')
            n %= 1000
        if n > 0:
            parts.append(_three_digits(n))
        return ' '.join(parts)

    rupees = int(amount)
    paise = round((amount - rupees) * 100)

    result = 'Rupees ' + _indian_number(rupees)
    if paise > 0:
        result += ' and ' + _two_digits(paise) + ' Paise'
    result += ' Only'
    return result


def _wrap_text(text, max_chars):
    """Wrap text to max characters per line."""
    words = text.split()
    lines = []
    current = ''
    for word in words:
        if len(current) + len(word) + 1 <= max_chars:
            current = current + ' ' + word if current else word
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [text[:max_chars]]


# ─── Generate Invoice PDF ───

def generate_invoice_pdf(invoice_id: str, request_id: str) -> Dict:
    """Generate invoice PDF and upload to S3."""
    if not invoice_id:
        return _resp(400, {'error': 'invoiceId required'})

    table = dynamodb.Table(INVOICES_TABLE)
    resp = table.get_item(Key={'invoiceId': invoice_id})
    invoice = resp.get('Item')
    if not invoice:
        return _resp(404, {'error': 'Invoice not found'})

    items_table = dynamodb.Table(INVOICE_ITEMS_TABLE)
    items_resp = items_table.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key('invoiceId').eq(invoice_id)
    )
    items = sorted(items_resp.get('Items', []), key=lambda x: int(x.get('itemIndex', 0)))

    # Primary: render receipt PNG and convert to PDF via PIL
    try:
        from PIL import Image as PILImage
        png_bytes = _generate_receipt_png(invoice, items)
        # Flatten, do not just convert: with RECEIPT_TRANSPARENT_BG on, the PNG is RGBA
        # and `convert('RGB')` would keep the black underneath its transparent pixels.
        png_img = _flatten_onto_white(PILImage.open(io.BytesIO(png_bytes)))
        pdf_buf = io.BytesIO()
        png_img.save(pdf_buf, format='PDF', resolution=150)
        pdf_bytes = pdf_buf.getvalue()
    except Exception as exc:
        # An incomplete document must never become a successful PDF asset. Log
        # only the failure type: render exceptions can include customer fields.
        logger.warning(json.dumps({
            'event': 'invoice_pdf_render_failed',
            'errorType': type(exc).__name__,
            'requestId': request_id,
        }))
        return _resp(503, {
            'error': 'Invoice PDF rendering is temporarily unavailable',
            'code': 'INVOICE_PDF_RENDER_FAILED',
            'retryable': True,
            'help': 'Retry PDF generation, or use the existing invoice HTML or image view.',
        })

    # Versioned on the same terms as the PNG: an issued invoice's PDF is re-rendered beside the
    # previous one, never over it.
    ref_id = invoice.get('referenceId', invoice_id)
    s3_key, asset_row_key = _asset_target(
        invoice, invoice_id=invoice_id, asset_type='pdf',
        stem=f"{INVOICE_PREFIX}wecare-digital-{ref_id}", extension='pdf',
        request_id=request_id)

    s3.put_object(
        Bucket=MEDIA_BUCKET,
        Key=s3_key,
        Body=pdf_bytes,
        ContentType='application/pdf',
        CacheControl='max-age=86400',
    )

    # Signed and expiring, for the same reason as the PNG above: `s3_key` is under
    # `INVOICE_PREFIX`, which is now the gated root, so a CDN URL would be a dead link.
    pdf_url = _signed_invoice_url(s3_key, invoice_id, request_id)

    # Store asset record. `url` is deliberately not persisted — a presigned URL expires, and a
    # stored one is correct when written and silently broken afterwards.
    assets_table = dynamodb.Table(INVOICE_ASSETS_TABLE)
    assets_table.put_item(Item={
        'invoiceId': invoice_id,
        'assetType': asset_row_key,
        's3Key': s3_key,
        'contentType': 'application/pdf',
        'version': int(time.time()),
        'generatedAt': int(time.time()),
    })

    logger.info(json.dumps({'event': 'invoice_pdf_generated', 'invoiceId': invoice_id,
                            'assetType': asset_row_key, 'url': pdf_url,
                            'requestId': request_id}))
    return _resp(200, {'invoiceId': invoice_id, 'pdfUrl': pdf_url, 's3Key': s3_key})


# ─── Send Pending Invoices by Phone (instant pay flow) ───

def send_pending_by_phone(body: Dict, request_id: str) -> Dict:
    """Find all pending invoices for a customer phone.
    Sequential pay: sends payment link for the FIRST (oldest) invoice only.
    Returns the full list so the inbound handler can show a summary.
    After each payment is captured, _check_and_notify_balance_due auto-sends the next one.
    """
    customer_phone = body.get('customerPhone', '')
    phone_number_id = body.get('phoneNumberId', '')
    if not customer_phone:
        return _resp(400, {'error': 'customerPhone required'})

    # Normalize phone for matching — strip everything except digits
    clean = customer_phone.replace(' ', '').replace('-', '').replace('(', '').replace(')', '').replace('+', '')
    # For Indian numbers: normalize to 10-digit local number for matching
    # This handles: +919876543210, 919876543210, 09876543210, 9876543210
    if clean.startswith('91') and len(clean) == 12:
        local10 = clean[2:]  # Strip country code
    elif clean.startswith('0') and len(clean) == 11:
        local10 = clean[1:]  # Strip leading 0
    elif len(clean) == 10:
        local10 = clean
    else:
        local10 = clean[-10:] if len(clean) >= 10 else clean

    # Scan InvoicesTable for pending invoices matching this phone
    table = dynamodb.Table(INVOICES_TABLE)
    pending_statuses = ('created', 'pending_payment', 'sent')
    all_pending = []

    try:
        scan_kwargs = {
            'FilterExpression': (
                boto3.dynamodb.conditions.Attr('status').is_in(list(pending_statuses))
            ),
        }
        while True:
            resp = table.scan(**scan_kwargs)
            for item in resp.get('Items', []):
                inv_phone_raw = (item.get('customerPhone', '') or '').replace('+', '').replace(' ', '').replace('-', '')
                # Normalize invoice phone to 10-digit local number
                if inv_phone_raw.startswith('91') and len(inv_phone_raw) == 12:
                    inv_local10 = inv_phone_raw[2:]
                elif inv_phone_raw.startswith('0') and len(inv_phone_raw) == 11:
                    inv_local10 = inv_phone_raw[1:]
                elif len(inv_phone_raw) == 10:
                    inv_local10 = inv_phone_raw
                else:
                    inv_local10 = inv_phone_raw[-10:] if len(inv_phone_raw) >= 10 else inv_phone_raw
                # STRICT match: full 10-digit local number must match exactly
                if inv_local10 == local10 and len(local10) == 10:
                    all_pending.append(item)
            if 'LastEvaluatedKey' in resp:
                scan_kwargs['ExclusiveStartKey'] = resp['LastEvaluatedKey']
            else:
                break
    except Exception as e:
        logger.error(json.dumps({'event': 'send_pending_scan_error', 'error': str(e), 'requestId': request_id}))
        return _resp(500, {'error': f'Failed to query invoices: {e}'})

    if not all_pending:
        return _resp(200, {'sent': 0, 'total': 0, 'message': 'No pending invoices', 'invoices': []})

    # Sort by createdAt ascending (oldest first)
    all_pending.sort(key=lambda x: int(x.get('createdAt', 0)))

    # Build invoice list for summary
    invoice_list = []
    for inv in all_pending:
        purpose = inv.get('purpose', '') or ''
        # Clean up raw menu action IDs stored as purpose
        if purpose.lower().startswith('menu_'):
            purpose = ''
        invoice_list.append({
            'invoiceId': inv.get('invoiceId', ''),
            'referenceId': inv.get('referenceId', ''),
            'total': float(inv.get('total', 0)),
            'purpose': purpose,
            'orderId': inv.get('orderId', ''),
            'status': 'pending',
        })

    # Send payment link for FIRST invoice only (sequential pay)
    first = all_pending[0]
    first_id = first.get('invoiceId', '')
    # Use the PG config stored on the invoice (set by admin at creation time)
    # Falls back to empty string → outbound handler uses phone's default Razorpay
    first_pg_config = first.get('paymentConfiguration', '') or ''
    send_error = ''
    try:
        result = send_payment_link(first_id, phone_number_id, first_pg_config, request_id,
                                   verify_phone=customer_phone)
        result_code = result.get('statusCode', 0)
        if result_code == 200:
            invoice_list[0]['status'] = 'sent'
        else:
            invoice_list[0]['status'] = 'failed'
            # Extract error from response body for debugging
            try:
                err_body = json.loads(result.get('body', '{}'))
                send_error = err_body.get('error', f'statusCode={result_code}')
            except Exception:
                send_error = f'statusCode={result_code}'
            logger.error(json.dumps({'event': 'send_first_link_failed', 'invoiceId': first_id, 'statusCode': result_code, 'error': send_error, 'requestId': request_id}))
    except Exception as e:
        logger.error(json.dumps({'event': 'send_first_link_error', 'invoiceId': first_id, 'error': str(e), 'requestId': request_id}))
        invoice_list[0]['status'] = 'failed'
        send_error = str(e)

    logger.info(json.dumps({'event': 'send_pending_complete', 'phone': mask_phone(customer_phone), 'total': len(all_pending), 'firstSent': first_id, 'sendError': send_error, 'requestId': request_id}))

    return _resp(200, {
        'sent': 1 if invoice_list[0]['status'] == 'sent' else 0,
        'total': len(invoice_list),
        'invoices': invoice_list,
        'error': send_error,
    })


# ─── Send Payment Link (WhatsApp Interactive Payment Message) ───

def _fetch_payment_configurations(waba_id: str) -> Dict[str, Any]:
    """Live Meta read of `GET /{waba}/payment_configurations`, via the business-API Lambda.

    Injected into `payment_readiness.evaluate` so this handler holds no Meta credential: the
    business-API Lambda already owns the Graph token and the read. Modelled on the working
    equivalent in `checkout/handler.py`.

    The read must stay UNFILTERED. A `fields` filter makes Meta return `data: []`, the measured
    false negative that once blocked every payment. `/payment-config/list` returns the flattened
    `{data:[config,...]}` shape `evaluate` consumes.

    Returning `{}` is NOT a pass: `evaluate` reads an absent `data` key as META_UNAVAILABLE, and
    any exception raised here is caught by `evaluate` and reported the same way — the module is
    explicit that an unreachable provider and a misconfigured one are indistinguishable from its
    position and both must block.

    No caching. Requirements statement 9 requires a live readback, and a cached verdict is a
    constant with a timestamp.
    """
    # The module-level `lambda_client`, which is the seam every test in this file already
    # patches. A client built inline here would be unpatchable and would make the gate
    # network-dependent offline.
    response = lambda_client.invoke(
        FunctionName=_PAYMENT_READ_FUNCTION,
        InvocationType='RequestResponse',
        Payload=json.dumps({
            'httpMethod': 'GET',
            'path': '/wa-business/payment-config/list',
            'queryStringParameters': {'wabaId': waba_id},
        }).encode('utf-8'),
    )
    raw = response['Payload'].read()
    if response.get('FunctionError'):
        raise RuntimeError('payment-config read Lambda failed')
    result = json.loads(raw.decode('utf-8')) if raw else {}
    body = result.get('body')
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except (ValueError, TypeError):
            body = {}
    return body if isinstance(body, dict) else {}


def _is_physical_staff_collection(entry_point: str, goods_type: str,
                                  amount_is_tax_inclusive: bool) -> bool:
    """A fresh staff-raised physical collection that will need a payable delivery address.

    A captured/tax-inclusive invoice (`create_invoice_from_payment`) is NOT included: the money
    already moved, there is nothing left to deliver-gate, and demanding an address there would
    refuse a legitimate receipt. Mirrors how `goodsType` itself is derived at create time and how
    `_payment_delivery_info`/`send_payment_link` treat a staff collection, so the create-time gate
    and the send-time gate agree on scope.
    """
    if amount_is_tax_inclusive:
        return False
    if entry_point in ('manual', 'pay_flow', 'whatsapp'):
        return True
    return goods_type == 'physical-goods'


def _create_invoice_delivery_error(body: Dict, entry_point: str,
                                   amount_is_tax_inclusive: bool) -> Optional[Dict]:
    """Refuse a physical staff invoice with no payable delivery address, BEFORE a number is minted.

    Returns a `_resp(400, ...)` dict to return, or None to proceed. The address is read from the
    create BODY (the invoice row does not exist yet), validated through the same
    `payment_address` checks the WhatsApp send path uses, so a physical order that could never be
    shipped/settled is refused at creation rather than after a GST number is consumed and only
    discovered at `send_payment_link`. Completeness is checked first so a blank address is a
    DELIVERY_REQUIRED (missing) rather than an INVALID_PIN (malformed). Digital/service and
    captured invoices pass straight through.
    """
    goods_type = body.get('goodsType', 'digital-goods')
    if not _is_physical_staff_collection(entry_point, goods_type, amount_is_tax_inclusive):
        return None
    address = {
        'addressLine1': str(body.get('addressLine1') or '').strip(),
        'addressLine2': str(body.get('addressLine2') or '').strip(),
        'city': str(body.get('city') or '').strip(),
        'state': str(body.get('state') or '').strip(),
        'postalCode': str(body.get('postalCode') or '').strip(),
        'countryCode': str(body.get('countryCode') or 'IN').upper(),
    }
    try:
        for key in ('addressLine1', 'city', 'state', 'postalCode'):
            if not address[key]:
                raise payment_address.UnpayableAddress('DELIVERY_REQUIRED', key)
        payment_address.assert_payable(
            address, channel=payment_address.WHATSAPP_ORDER_DETAILS)
    except payment_address.UnpayableAddress as exc:
        return _resp(400, {
            'error': ('A physical order needs a complete, payable delivery address before it '
                      'can be raised. Nothing has been charged and no invoice was created.'),
            'errorCode': exc.code,
            'field': exc.field,
        })
    return None


def _payment_delivery_info(invoice: Dict, contact: Optional[Dict], phone: str) -> Optional[Dict]:
    """Validate delivery before reserving a physical payment; never collect it after pricing."""
    staff_collection = invoice.get('entryPoint') in ('manual', 'pay_flow', 'whatsapp')
    if not staff_collection and invoice.get('goodsType', 'digital-goods') != 'physical-goods':
        return None
    contact = contact or {}
    fields = invoice if invoice.get('addressLine1') else _contact_address_fields(contact)
    stored = contact.get('checkoutDeliveryAddress') or {}
    stored = stored if isinstance(stored, dict) else {}
    country = str(invoice.get('countryCode') or stored.get('countryCode')
                  or contact.get('countryCode') or 'IN').upper()
    address = {key: str(fields.get(key) or '').strip()
               for key in ('addressLine1', 'addressLine2', 'city', 'state', 'postalCode')}
    address['countryCode'] = country
    if any(not address[key] for key in ('addressLine1', 'city', 'state', 'postalCode')):
        raise payment_address.UnpayableAddress('DELIVERY_REQUIRED')
    payment_address.for_meta_beneficiary(address, recipient_name=str(
        invoice.get('customerName') or contact.get('contactBookName') or contact.get('name') or 'Customer'))
    return {'country': country, 'addresses': [{
        'name': invoice.get('customerName') or contact.get('contactBookName') or contact.get('name') or 'Customer',
        'phone_number': phone.replace('+', ''), 'address': address['addressLine1'],
        'city': address['city'], 'state': address['state'], 'in_pin_code': address['postalCode'],
        'landmark_area': address['addressLine2'],
    }]}


def send_payment_link(invoice_id: str, phone_number_id: str, payment_configuration: str,
                      request_id: str, verify_phone: str = '') -> Dict:
    """Send WhatsApp interactive payment message for a pending invoice.
    Creates the order_details message with review_and_pay action.
    payment_configuration: optional PG config name ('WECAREDIGITAL' or 'WECAREUPI').
    If empty, outbound handler uses the phone's default Razorpay config.
    verify_phone: if provided, blocks sending if invoice doesn't belong to this phone.
    """
    if not invoice_id:
        return _resp(400, {'error': 'invoiceId required'})

    table = dynamodb.Table(INVOICES_TABLE)
    resp = table.get_item(Key={'invoiceId': invoice_id})
    invoice = resp.get('Item')
    if not invoice:
        return _resp(404, {'error': 'Invoice not found'})

    # Don't send payment link for already paid/cancelled invoices.
    #
    # Two fields, checked both ways on purpose. `status` is the document lifecycle; the ranked
    # `paymentStatus` is what the MONEY did. A capture writes `paymentStatus='captured'`, and if
    # `status` was not also flipped to `'paid'` (a divergence the cancel path documents), a guard
    # that read `status` alone would let this function run on an already-paid invoice and overwrite
    # `status` back to `pending_payment` - showing a paid customer a fresh "pay now" request. The
    # ranked check refuses anything at or past CAPTURED (captured/paid/refunded/disputed) exactly
    # as the reconciliation paths do, so the paid state is preserved regardless of which field
    # carries it.
    status = invoice.get('status', '')
    if status in ('paid', 'cancelled'):
        return _resp(400, {'error': f'Invoice is {status}, cannot send payment link'})
    current_ps = invoice.get('paymentStatus', '')
    if pay_status.rank(current_ps) >= pay_status.STATUS_RANK[pay_status.CAPTURED]:
        return _resp(400, {
            'error': 'Invoice is already paid; cannot send a payment request.',
            'paymentStatus': pay_status.canonical(current_ps),
        })

    customer_phone = invoice.get('customerPhone', '')
    if not customer_phone:
        return _resp(400, {'error': 'No customer phone on invoice'})

    # SAFETY: Verify the payment link is being sent to the invoice's actual customer
    # This prevents sending customer A's invoice to customer B
    if verify_phone:
        req_clean = verify_phone.replace('+', '').replace(' ', '').replace('-', '')
        inv_clean = customer_phone.replace('+', '').replace(' ', '').replace('-', '')
        # Normalize both to 10-digit local
        req_local = req_clean[2:] if req_clean.startswith('91') and len(req_clean) == 12 else (req_clean[-10:] if len(req_clean) >= 10 else req_clean)
        inv_local = inv_clean[2:] if inv_clean.startswith('91') and len(inv_clean) == 12 else (inv_clean[-10:] if len(inv_clean) >= 10 else inv_clean)
        if req_local != inv_local:
            logger.error(json.dumps({
                'event': 'invoice_phone_mismatch_blocked',
                'invoiceId': invoice_id,
                # MASKED, both of them. This log used to carry two full E.164 numbers, eight
                # lines from the code this change edits. Its purpose - which invoice, which
                # request, that a mismatch occurred - survives masking intact, and the two
                # masked suffixes still distinguish the mismatch it exists to record.
                'invoicePhone': mask_phone(customer_phone),
                'requestedPhone': mask_phone(verify_phone),
                'requestId': request_id,
            }))
            return _resp(403, {'error': 'Invoice does not belong to this customer'})

    # The invoice's own reference. ADOPTED by the reservation below, never replaced: every
    # invoice gets one at `create_invoice` time, so on the live path the id already exists before
    # collection is raised, and replacing it would strand every payment request already in a
    # customer's hands - their tap produces a capture whose reference resolves nowhere.
    #
    # This 400 is load-bearing and stays exactly as it is: an invoice with no reference cannot
    # reach collection at all.
    reference_id = invoice.get('referenceId', '')
    if not reference_id:
        return _resp(400, {'error': 'No referenceId on invoice'})

    # Get invoice items
    items_table = dynamodb.Table(INVOICE_ITEMS_TABLE)
    items_resp = items_table.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key('invoiceId').eq(invoice_id)
    )
    items = sorted(items_resp.get('Items', []), key=lambda x: int(x.get('itemIndex', 0)))

    # Build order items for WhatsApp interactive message (amounts in INTEGER PAISE).
    #
    # Every money read below goes through `_paise`, which is `Decimal(str(v)) * 100` plus an
    # integral check - no `round()`, no `float()`, no epsilon. The reason is specific rather than
    # stylistic: the figure computed here is RESERVED as the attempt's `amountPaise`, and a
    # capture is compared against it with exact integer equality. So a rounding artefact would
    # not be cosmetic, it would refuse a legitimate payment - and a total carrying sub-paise
    # noise cannot be compared exactly at all, so it fails closed here rather than truncating
    # 599.999 to 59999 and matching a rounded-down expectation.
    #
    # The convenience fee IS added here, as a transparent line item. The old comment claiming
    # "the outbound-whatsapp handler auto-calculates and adds it" is wrong for this path -
    # measured, `skipConvenienceFee` is read only in the native-interactive branch, not in the
    # checkout-template branch this send reaches.
    # Green Packing & Notification Fee are pushed to the end of the items list.
    _paise = wa_payment_request.exact_paise
    CHARGE_ITEM_NAMES = {'green packing', 'notification fee', 'notification/alert fee'}
    regular_items = []
    charge_items = []
    # A RATE, not money. It takes part in no arithmetic in this function - the tax AMOUNT comes
    # off the invoice's own `tax` field - and Meta strips per-item `gstRate` from the
    # `order_details` item schema anyway, so this value is informational on our side of the wire.
    # Carried as a `Decimal` so it is exact, and emitted below as an integer when it is integral
    # (every live Indian GST rate is) or as an exact string when it is not. Either way no float
    # appears on a payment payload.
    try:
        gst_rate = Decimal(str(invoice.get('gstRate', 18) or 0))
    except Exception:  # noqa: BLE001
        gst_rate = Decimal('18')
    gst_rate_wire = (int(gst_rate) if gst_rate == gst_rate.to_integral_value()
                     else str(gst_rate))
    try:
        for item in items:
            qty = int(item.get('quantity', 1))
            amt_paise = _paise(item.get('amount', 0))
            entry = {
                'name': item.get('name', 'Item'),
                'amount': {'value': amt_paise, 'offset': 100},
                'quantity': qty,
            }
            if item.get('name', '').strip().lower() in CHARGE_ITEM_NAMES:
                charge_items.append(entry)
            else:
                regular_items.append(entry)
        # Merge: regular items first, then charge items (Green Packing, Notification Fee) last
        merged_items = regular_items + charge_items
        order_items = []
        subtotal_paise = 0
        for i, entry in enumerate(merged_items):
            entry['retailer_id'] = f'ITEM_{i+1}'
            line_paise = entry['amount']['value'] * entry['quantity']
            subtotal_paise += line_paise
            order_items.append(entry)

        discount_paise = _paise(invoice.get('discount', 0))
        shipping_paise = _paise(invoice.get('shipping', 0))
        # GST (tax) and convenience fee are already computed on the invoice. The
        # checkout-template send path does NOT recompute them, so we MUST populate the
        # order_details here — otherwise the customer sees only the bare item price
        # (missing GST + convenience fee, and a total that mismatches the invoice).
        gst_paise = _paise(invoice.get('tax', 0))
        conv_paise = _paise(invoice.get('convenienceFee', 0))
        # Meta's order_details has no dedicated fee field, so add the convenience fee as
        # a transparent line item (its own GST is already baked into convenienceFee).
        if conv_paise > 0:
            order_items.append({
                'name': 'Convenience Fee',
                'amount': {'value': conv_paise, 'offset': 100},
                'quantity': 1,
                'retailer_id': f'ITEM_{len(order_items) + 1}',
            })
            subtotal_paise += conv_paise
        # Internally-consistent total, as an INTEGER SUM (Meta validates
        # total == subtotal + tax + shipping - discount).
        total_paise = subtotal_paise + gst_paise + shipping_paise - discount_paise
    except wa_payment_request.PaymentRequestRefused as refused:
        # The FIELD NAME and the invoice id, never the value. An invoice total that cannot be
        # expressed in exact paise has to be corrected before it can be collected against.
        logger.error(json.dumps({
            'event': 'payment_link_money_unreadable', 'invoiceId': invoice_id,
            'code': refused.code, 'detail': refused.detail, 'requestId': request_id,
        }))
        return _resp(refused.status_code, {'error': refused.message, 'code': refused.code})

    order_id = invoice.get('orderId', 'Offline')

    # Look up contact
    contact = _lookup_contact_by_phone(customer_phone)
    contact_id = (contact.get('contactId') or contact.get('id', '')) if contact else ''
    try:
        shipping_info = _payment_delivery_info(invoice, contact, customer_phone)
    except payment_address.UnpayableAddress as exc:
        return _resp(400, {'error': 'Save complete payable delivery details before requesting payment. Nothing has been charged.',
                           'code': 'DELIVERY_REQUIRED', 'field': exc.field})


    # ── Payment messages go from the SAME phone the customer is chatting with ──
    # CRITICAL: Never cross-WABA — WABA 1 configs only work on WABA 1, WABA 2 on WABA 2.
    # If no phone_number_id was passed (e.g. dashboard send without phone selection),
    # we MUST still pick the right phone. Use the invoice's stored config to infer.
    if not phone_number_id:
        # The payment configuration name CANNOT identify the WABA any more. Before
        # 2026-08-23 WABA1 used hyphenated names (WECARE-DIGITAL, WECARE-UPIVPA)
        # and WABA2 used its own, so a 'WECARE-'/'UPIVPA' substring test worked.
        # Meta rebuilt the configs that day and both WABAs now expose the
        # IDENTICAL pair WECAREDIGITAL / WECAREUPI - neither contains a hyphen and
        # neither contains 'UPIVPA', so that test matched nothing and every
        # unresolved invoice fell through to Phone 2 regardless of origin.
        #
        # Use the authoritative record instead: awsPhoneNumberId is written onto
        # the invoice at send time (see the update below), which is the same field
        # razorpay-webhook._resolve_originating_phone trusts first.
        phone_number_id = invoice.get('awsPhoneNumberId') or invoice.get('phoneNumberId') or ''
        if not phone_number_id:
            # Fall back to the PRIMARY identity, not the secondary.
            #
            # This default used to be Phone 2. That was wrong on two counts.
            # Phone 1 (+919330994400, WABA 2094615664435155) is the documented
            # primary business identity. More importantly Phone 2 is marked
            # `paymentProtected: true` in src/config/constants.ts, and the UI
            # gates it behind "Admin authorization required for this number"
            # before an operator may send payments from it. Defaulting to it
            # server-side meant any path that omitted a phone id bypassed that
            # admin check entirely - an authorization inconsistency, not just an
            # odd choice of sender.
            # One home for the literal: `wa_payment_request.PHONE_NUMBER_ID_1`, already imported
            # above and already the set `PAYMENT_SENDERS` is built from. The reasoning in the
            # comment above is what matters here, not a retyped string.
            phone_number_id = wa_payment_request.PHONE_NUMBER_ID_1  # Phone 1 (primary)
            logger.warning(json.dumps({
                'event': 'invoice_phone_unresolved_using_primary',
                'invoiceId': invoice.get('invoiceId', ''),
                'paymentConfiguration': payment_configuration or invoice.get('paymentConfiguration', ''),
                'phoneId': phone_number_id,
                'note': 'config name cannot identify a WABA; both expose '
                        'WECAREDIGITAL/WECAREUPI. Defaulting to the primary '
                        'identity; never to the admin-gated secondary.',
            }))

    # ══ RESERVE BEFORE SEND ══════════════════════════════════════════════════════════════
    #
    # Four conditional writes in ONE transaction, before the sender is invoked: the
    # `REQUESTKEY#` resolve-before-generate anchor, the `PAYREF#` row the webhook reconciles on,
    # the `INVOICECOLLECT#` interlock, and the PaymentAttempt that holds the authoritative money
    # fields. A retried send resolves the anchor and re-sends the SAME `reference_id`; it never
    # mints a second one.
    #
    # The interlock matters because five independent callers reach this function - the operator
    # UI, the business-API route, a Flow completion, the inbound auto-send and the auto-send
    # chain - and without it one pending invoice can receive a payment request from two of them
    # concurrently, producing two references, two captures and two orders.
    configuration_name = (payment_configuration
                          or invoice.get('paymentConfiguration', '')
                          or WA_PAY_CONFIG_NAME)

    # ══ A1: READINESS BEFORE RESERVATION ═════════════════════════════════════════════════════
    #
    # Position is forced, not stylistic. Readiness needs the resolved sender (to derive the WABA
    # id) and the resolved configuration name, so it cannot run earlier; and it must precede the
    # four-write transaction below, so a refusal leaves NO `PAYREF#` row, NO `REQUESTKEY#`
    # anchor, NO `INVOICECOLLECT#` interlock and NO attempt row behind it.
    #
    # This path is deliberately gated TWICE - here, and again at the `outbound-whatsapp`
    # boundary. They answer different questions at different costs: this one refuses BEFORE
    # identity is reserved; the boundary one refuses after the caller has reserved, and its job
    # is to be unbypassable rather than cheap. Removing either would mean trusting the other,
    # and the boundary gate exists precisely because callers cannot be trusted to carry a gate.
    # A caller-supplied "already proven" flag is NOT an option: that is a bypass.
    #
    # Only WABA1 may take a payment, refused by name and with its existing code. First on the
    # path, and BEFORE the readiness evaluation on purpose: an
    # unmapped sender yields an empty WABA id, which `evaluate` reports as
    # CONFIGURATION_UNVERIFIED — closed, but under a name that reads as "something is
    # misconfigured" and sends an operator looking for a configuration error that does not exist.
    # `build_request` refuses the same case one layer down with the same code; this is the earlier
    # and better-named of the two, and it costs one set membership.
    if phone_number_id not in wa_payment_request.PAYMENT_SENDERS:
        logger.error(json.dumps({'event': 'wa_payment_sender_not_permitted',
                                 'invoiceId': invoice_id,
                                 'code': wa_payment_request.WA_PAY_SENDER_NOT_PERMITTED,
                                 'requestId': request_id}))
        return _resp(409, {'error': wa_payment_request.REFUSAL_MESSAGES[
                               wa_payment_request.WA_PAY_SENDER_NOT_PERMITTED],
                           'code': wa_payment_request.WA_PAY_SENDER_NOT_PERMITTED})

    # A configuration this deployment cannot prove is refused by name, with a cause, before the
    # provider read. In practice this refuses `WECAREUPI`; nothing live sends it. With
    # `WA_PAY_CONFIG_NAME` unset both sides are `''`, so this check passes and `evaluate` then
    # reports CONFIGURATION_UNVERIFIED on the empty name — still closed, one branch later.
    if configuration_name != WA_PAY_CONFIG_NAME:
        logger.error(json.dumps({'event': 'wa_payment_config_not_provable',
                                 'invoiceId': invoice_id,
                                 'configurationName': configuration_name,
                                 'code': WA_PAY_CONFIG_NOT_PROVABLE,
                                 'requestId': request_id}))
        return _resp(409, {'error': 'That payment configuration cannot be verified on this '
                                    'path. Nothing has been charged.',
                           'code': WA_PAY_CONFIG_NOT_PROVABLE})

    # `evaluate`, not `evaluate_for_delivery`. The send is unconditionally template-only
    # (`isCheckoutTemplate` + `WA_PAY_TEMPLATE`), so the 24-hour window is irrelevant to
    # deliverability, and the template-approval question is owned by the boundary gate, which is
    # the one layer that sees the template name on every surface. Duplicating a second Graph read
    # here buys nothing.
    #
    # The WABA id is derived from the SENDER through `wa_payment_request.PHONE_ID_TO_WABA`, whose
    # own comment records that the value is derived from the sender and never read from a request
    # body, because a caller-supplied WABA id on a money path is a caller-supplied routing
    # decision. An unmapped sender yields `''`, which `evaluate` reports as
    # CONFIGURATION_UNVERIFIED — the correct fail-closed direction, agreeing with
    # `PAYMENT_SENDERS` one layer down. No `PAYMENT_WABA_ID` env var is added: deriving from the
    # already-resolved sender is strictly stronger than a second variable that could disagree.
    readiness = payment_readiness.evaluate(
        expected_waba_id=wa_payment_request.PHONE_ID_TO_WABA.get(phone_number_id, ''),
        expected_configuration_name=configuration_name,
        expected_provider_mid=WA_PAY_PROVIDER_MID,
        fetch_configurations=_fetch_payment_configurations,
    )
    # Membership in `BLOCKING_STATES`, not `not readiness.ready`. Equivalent today, but the
    # enumerated form is what the module asks for in its own words, so a state added later
    # without being classified cannot become permissive by omission.
    if readiness.state in payment_readiness.BLOCKING_STATES:
        # ERROR, not INFO. `_blocked` already emits its own WARNING; this line is the
        # discoverable signal because it carries the invoice id and the request id — and on the
        # inbound auto-send leg, which invokes with InvocationType='Event' and never reads the
        # response, it is the ONLY signal a refusal happened at all.
        logger.error(json.dumps({'event': 'wa_payment_readiness_refused',
                                 'invoiceId': invoice_id, 'readiness': readiness.state,
                                 'code': WA_PAY_NOT_READY, 'requestId': request_id,
                                 'detail': readiness.as_dict()}))
        # 503 for the two availability states, 409 for the other eight: a 409 tells the staff UI
        # "this will not succeed", and the two availability states will. A literal message ending
        # "Nothing has been charged.", never `readiness.customer_message()` — that method carries
        # no no-charge assurance and exists to WITHHOLD the cause from a shopper, of which there
        # is none on this route. `as_dict()` is the operator projection: logged, never returned.
        return _resp(503 if readiness.state in _READINESS_TRANSIENT else 409,
                     {'error': 'WhatsApp payment is not ready. Nothing has been charged.',
                      'code': WA_PAY_NOT_READY, 'readiness': readiness.state})

    customer_id = str(invoice.get('contactId') or invoice.get('customerId') or contact_id or '')
    # The COLLECTION SEQUENCE, so a cancelled collection is re-raisable. `cancel_invoice`
    # records `seq + 1`, which makes the next collection compose a different request key: the old
    # reservation stays immutable and the old `PAYREF#` row stays resolvable.
    collection_seq = int(invoice.get(order_keys.INVOICE_COLLECT_SEQ_ATTR, 0) or 0)
    # E.164 for validation. The recipient comes off the INVOICE row and never from the request -
    # that is the real control on who receives a payment request, and it is unconditional.
    _digits = ''.join(ch for ch in str(customer_phone) if ch.isdigit())
    if len(_digits) == 10:
        _digits = '91' + _digits
    phone_e164 = '+' + _digits

    keys_table = dynamodb.Table(COMMERCE_KEYS_TABLE)
    attempts_table = dynamodb.Table(PAYMENT_ATTEMPTS_TABLE)
    try:
        reservation = wa_payment_request.build_request(
            invoice_id=invoice_id, customer_id=customer_id,
            customer_uuid=str(invoice.get(customer_uuid.ATTRIBUTE) or ''),
            phone_e164=phone_e164, phone_number_id=phone_number_id,
            amount_paise=total_paise, configuration_name=configuration_name,
            provider_mid=WA_PAY_PROVIDER_MID,
            item_name=(order_items[0]['name'] if order_items else 'Payment')[
                :wa_payment_request.MAX_ITEM_NAME_LENGTH],
            collection_seq=collection_seq, now=int(time.time()))
        attempt, freshly_reserved = wa_payment_request.reserve(
            dynamodb_transaction_client, keys_table, attempts_table,
            keys_name=COMMERCE_KEYS_TABLE, attempts_name=PAYMENT_ATTEMPTS_TABLE,
            request=reservation, invoice_reference_id=reference_id)
    except wa_payment_request.PaymentRequestRefused as refused:
        # Codes only. Nothing was written and nothing was sent.
        logger.info(json.dumps({
            'event': 'wa_payment_request_refused', 'invoiceId': invoice_id,
            'code': refused.code, 'requestId': request_id,
        }))
        return _resp(refused.status_code, {'error': refused.message, 'code': refused.code})
    except Exception as e:  # noqa: BLE001
        logger.error(json.dumps({
            'event': 'wa_payment_reserve_error', 'invoiceId': invoice_id,
            'error': type(e).__name__, 'requestId': request_id,
        }))
        return _resp(503, {'error': wa_payment_request.REFUSAL_MESSAGES[
            wa_payment_request.WA_PAY_IDENTITY_UNAVAILABLE],
            'code': wa_payment_request.WA_PAY_IDENTITY_UNAVAILABLE})

    # The RESERVED reference is what travels, replacing the invoice read. On the adopt path they
    # are the same string; the reservation is nonetheless the authority, because it is the row
    # the webhook resolves against.
    reference_id = str(attempt['referenceId'])
    payment_attempt_id = str(attempt['paymentAttemptId'])

    # The durable boundary BEFORE the sender is invoked. A loser never sends: a second
    # `order_details` message for one reservation would show the customer two payment requests.
    if not wa_payment_request.claim_send(attempts_table,
                                         payment_attempt_id=payment_attempt_id):
        # The claim is held by someone, and WHY it is held decides the answer. Read off the
        # resolved attempt row, which on the resume path is the stored one.
        held_as = str(attempt.get('sendStatus') or '')
        logger.info(json.dumps({
            'event': 'wa_payment_send_already_claimed', 'invoiceId': invoice_id,
            'referenceId': reference_id, 'paymentAttemptId': payment_attempt_id,
            'sendStatus': held_as, 'requestId': request_id,
        }))
        if held_as == 'REJECTED':
            # A claim held under REJECTED is NOT a send in progress, and answering 200
            # 'send_in_progress' for it is the same lie this feature exists to remove. The
            # downstream already said this request will not succeed, so the next step is a
            # corrected invoice and a fresh collection, not another invoke.
            return _resp(409, {
                'error': 'This payment request was refused and was not sent. Cancel and raise '
                         'the collection again. Nothing has been charged.',
                'invoiceId': invoice_id, 'referenceId': reference_id,
                'paymentAttemptId': payment_attempt_id,
                'status': 'payment_link_rejected', 'sendStatus': 'REJECTED'})
        # 200, not 409. A 409 reads as "nothing happened" and invites a retry, and a second
        # invoke is the one thing this claim exists to prevent. `sendStatus` is resolved by
        # reading the OutboundTable row, never by sending again.
        return _resp(200, {'invoiceId': invoice_id, 'referenceId': reference_id,
                           'status': 'send_in_progress', 'deduplicated': True})

    # Build payload for outbound-whatsapp Lambda
    # Determine goods type: use stored value from invoice creation.
    # Staff collections always confirm delivery as physical orders.
    ship_addr = invoice.get('shippingAddress', '')
    bill_addr = invoice.get('billingAddress', '')
    cust_name = invoice.get('customerName', 'Customer')
    goods_type = ('physical-goods' if invoice.get('entryPoint') in ('manual', 'pay_flow', 'whatsapp')
                  else invoice.get('goodsType', 'digital-goods'))

    order_type = 'physical-goods' if goods_type == 'physical-goods' else 'digital-goods'

    order_details_obj = {
        # The RESERVED reference, not the invoice read. Those are the same string on the adopt
        # path, and the reservation is still the one that travels, because it is the row the
        # webhook resolves against.
        'reference_id': reference_id,
        'type': order_type,
        # The SAME string the reservation recorded, by construction - which is what makes the
        # attempt's `configurationName` usable as the Meta binding's configuration source.
        'payment_configuration': configuration_name,
        'currency': 'INR',
        'itemName': order_items[0]['name'] if order_items else 'Payment',
        'quantity': 1,
        'gstRate': gst_rate_wire,
        'gstin': invoice.get('gstin', COMPANY['gstin']),
        'orderId': order_id,
        'total_amount': {'value': total_paise, 'offset': 100},
        'order': {
            'status': 'pending',
            'items': order_items,
            'subtotal': {'value': subtotal_paise, 'offset': 100},
            # Name the one current automatic discount truthfully. Legacy invoice rows with a
            # non-Delight discount keep the generic label rather than being misrepresented.
            'discount': {'value': discount_paise, 'offset': 100,
                         'description': ('Delight'
                                         if invoice.get('couponCode') == default_coupon.DELIGHT_CODE
                                         else 'Discount')},
            'shipping': {'value': shipping_paise, 'offset': 100, 'description': 'Express'},
            'tax': {'value': gst_paise, 'offset': 100, 'description': f'GSTIN: {COMPANY["gstin"]}'},
        },
    }

    if shipping_info is not None:
        order_details_obj['shipping_info'] = shipping_info

    wa_payload = {
        'body': json.dumps({
            'contactId': contact_id,
            'recipientPhone': customer_phone,
            'phoneNumberId': phone_number_id,
            # ALWAYS use checkout button template (wecarepay_wa) for ALL payments.
            # Reuse the approved payment template with the frozen invoice and delivery details.
            'isCheckoutTemplate': True,
            'isTemplate': True,
            # ONE home for the approved template name, read from the environment. A gate that
            # checks a different string from the one the send uses can pass while the send fails.
            'templateName': WA_PAY_TEMPLATE,
            'templateParams': [],  # wecarepay_wa has no body variables
            'checkoutOrderDetails': order_details_obj,
            # FIXED company-logo header on EVERY payment. Do not vary per order.
            'headerImageUrl': 'https://wecare.digital/get/o/public/wa-tpl/img/wecarepay-header.png',
        })
    }

    # ══ THE DELIVERY LOG, ONE HOME, EVERY OUTCOME ════════════════════════════════════════════
    #
    # It used to be a single write at the bottom of the function, reached only by the paths that
    # fell through to it: the ambiguous path returned 502 above it and left NO record at all, and
    # every row it did write carried `waMessageId: ''` and the word `sent`.
    #
    # Nested rather than module-level because the row is composed almost entirely of this send's
    # locals; `status` is the only thing the three call sites disagree about, which is exactly
    # what makes one home worth having.
    def _log_delivery(status: str, *, wa_message_id: str = '', error: str = '') -> None:
        try:
            dynamodb.Table(INVOICE_DELIVERY_TABLE).put_item(Item={
                'invoiceId': invoice_id,
                'timestamp': int(time.time()),
                'channel': 'whatsapp_payment',
                'toNumber': customer_phone,
                'waMessageId': wa_message_id,
                'status': status,
                'imageUrl': '',
                'phoneNumberId': phone_number_id,
                'contactId': contact_id,
                'error': error,
            })
        except Exception as log_error:  # noqa: BLE001
            # This row is the staff-VISIBLE record of a send, not the authority on it (the
            # `PAYREF#` row and `sendStatus` are). So a failed log is logged and swallowed: a
            # storage error here must not replace a truthful rejection with a 500, which is the
            # one answer that would send an operator looking in the wrong place.
            logger.error(json.dumps({
                'event': 'payment_delivery_log_failed', 'invoiceId': invoice_id,
                'status': status, 'error': type(log_error).__name__, 'requestId': request_id,
            }))

    try:
        wa_response = lambda_client.invoke(
            FunctionName='wecare-outbound-whatsapp:live',
            InvocationType='RequestResponse',
            Payload=json.dumps(wa_payload),
        )
        wa_result = json.loads(wa_response['Payload'].read())
        wa_status_code = int(wa_result.get('statusCode', wa_response.get('StatusCode', 0)) or 0)
    except Exception as e:
        # ══ AMBIGUOUS ════════════════════════════════════════════════════════════════════════
        #
        # A timeout, an unreadable response, a transport failure: we do not know whether Meta
        # took the message. The reservation exists and no send is replayed - `sendStatus` stays
        # PENDING and the claim is deliberately NOT released, because network acceptance cannot
        # be inferred from a timeout and a second message would show the customer two payment
        # requests. Releasing here would invite exactly the double-send the claim exists to stop.
        #
        # What changes is that the row is written BEFORE the return, labelled `unknown`. An
        # ambiguous send that leaves no record is indistinguishable from a send that never
        # happened, and the two need opposite actions from staff.
        logger.error(json.dumps({
            'event': 'wa_payment_send_unknown', 'invoiceId': invoice_id,
            'referenceId': reference_id, 'error': type(e).__name__, 'requestId': request_id,
        }))
        _log_delivery('unknown', error=f'send outcome unknown: {type(e).__name__}')
        return _resp(502, {'error': 'The payment request could not be confirmed as sent. '
                                    'Reconcile this collection before raising it again.',
                           'referenceId': reference_id, 'sendStatus': 'PENDING'})

    if wa_status_code >= 400:
        # ══ DEFINITE REJECTION ═══════════════════════════════════════════════════════════════
        #
        # The downstream parsed our request and refused it. Nothing is in the customer's hands,
        # so this function must not write `pending_payment`, must not advance the attempt, and
        # must never answer 200 `payment_link_sent` - which is what it did until now, logging the
        # failure and continuing as though the message had gone out.
        #
        # The CODE, not the raw body: the refusal codes are stable machine strings, and the body
        # is downstream text this log has no reason to carry verbatim.
        downstream = ''
        try:
            parsed = wa_result.get('body')
            if isinstance(parsed, str):
                parsed = json.loads(parsed or '{}')
            if isinstance(parsed, dict):
                downstream = str(parsed.get('error') or parsed.get('message') or '')[:200]
        except (ValueError, TypeError):
            downstream = ''
        logger.error(json.dumps({
            'event': 'payment_link_outbound_error', 'invoiceId': invoice_id,
            'statusCode': wa_status_code, 'code': downstream,
            'referenceId': reference_id, 'paymentAttemptId': payment_attempt_id,
            'requestId': request_id,
        }))
        _log_delivery('rejected',
                      error=(f'outbound {wa_status_code}: {downstream}' if downstream
                             else f'outbound {wa_status_code}'))
        # A downstream 409 is that layer's own "this will not succeed" - a sender that may not
        # take payments, a configuration it cannot prove, an envelope it refuses. Re-invoking the
        # identical request would be refused identically, so the claim is left HELD under
        # REJECTED and staff are told to raise the collection again. Any other rejection (a
        # malformed request, a downstream 5xx) is one a staff member can fix and retry, so the
        # claim is RELEASED and the same reservation re-sends.
        terminal = wa_status_code == 409
        if terminal:
            wa_payment_request.record_send_rejected(attempts_table,
                                                    payment_attempt_id=payment_attempt_id,
                                                    now=int(time.time()))
        else:
            wa_payment_request.release_send_claim(attempts_table,
                                                  payment_attempt_id=payment_attempt_id)
        # `sendStatus: 'REJECTED'` describes THIS send's outcome, which is the thing the caller
        # asked about; `retryable` is what the stored claim now permits. They are two different
        # questions and conflating them is how "rejected" came to read as "sent".
        return _resp(409 if terminal else 502, {
            'error': 'The payment request was refused and was NOT sent. '
                     'Nothing has been charged.',
            'invoiceId': invoice_id,
            'referenceId': reference_id,
            'paymentAttemptId': payment_attempt_id,
            'status': 'payment_link_rejected',
            'sendStatus': 'REJECTED',
            'downstreamStatusCode': wa_status_code,
            'retryable': not terminal,
        })

    if wa_status_code not in (200, 202):
        # Neither a rejection nor an acceptance: a response shape this function cannot read as
        # either (a 0 from a missing `statusCode`, a redirect, anything new). Treated as the
        # AMBIGUOUS outcome rather than as success - the old code fell through here and wrote
        # `pending_payment` plus a `failed` delivery row, which is a contradiction in one invoice.
        logger.error(json.dumps({
            'event': 'wa_payment_send_unreadable', 'invoiceId': invoice_id,
            'statusCode': wa_status_code, 'referenceId': reference_id,
            'requestId': request_id,
        }))
        _log_delivery('unknown', error=f'unreadable outbound status {wa_status_code}')
        return _resp(502, {'error': 'The payment request could not be confirmed as sent. '
                                    'Reconcile this collection before raising it again.',
                           'referenceId': reference_id, 'sendStatus': 'PENDING'})

    # ══ ACCEPTANCE ═══════════════════════════════════════════════════════════════════════════
    #
    # The attempt advances only after a send Meta accepted. Monotonic by condition, and a failure
    # to advance is logged rather than raised: the customer already has the message.
    wa_payment_request.record_sent(attempts_table,
                                   payment_attempt_id=payment_attempt_id,
                                   now=int(time.time()))

    # The REAL message id, read out of the outbound response the way `send_invoice_whatsapp`
    # already reads it. Every row on this path used to carry `''`, which left the delivery log
    # unjoinable to the message it claims to record. Parsed defensively: an id we cannot read is
    # an empty id, never a failed send - the send was accepted either way.
    wa_message_id = ''
    try:
        accepted_body = wa_result.get('body')
        if isinstance(accepted_body, str):
            accepted_body = json.loads(accepted_body or '{}')
        if isinstance(accepted_body, dict):
            wa_message_id = str(accepted_body.get('whatsappMessageId')
                                or accepted_body.get('messageId') or '')
    except (ValueError, TypeError):
        wa_message_id = ''

    # Update invoice status to pending_payment
    try:
        # Persist the sending business phone id on the invoice so the Razorpay
        # webhook can reply + open the post-payment flow from the SAME WABA
        # (never cross-WABA). This is the most reliable phone source.
        #
        # `referenceId` is written with `if_not_exists` under an equality-or-absent condition, so
        # this path can NEVER overwrite an invoice's reference even if the adopt branch above is
        # later bypassed. On the adopt path it is a no-op that proves the two agree; on the mint
        # path it is the first assignment.
        _upd_names = {'#st': 'status', '#ua': 'updatedAt'}
        _upd_vals = {':st': 'pending_payment', ':now': int(time.time()), ':ref': reference_id}
        if collection_seq > 0:
            # A RE-RAISE after a cancel. The reservation minted a fresh reference (the old
            # `PAYREF#` row is retained and still resolvable, carrying the pre-edit amount), so
            # the invoice must now name the new one or the invoice-dedup join points at the
            # superseded request.
            #
            # The overwrite is permitted EXACTLY when `collectionSeq` on the row equals the
            # sequence this collection reserved against - i.e. when `cancel_invoice` recorded it.
            # So an ordinary send can still never overwrite a reference: at sequence 0 the
            # `if_not_exists` arm below applies instead.
            _upd_expr = 'SET #st = :st, #ua = :now, referenceId = :ref, previousReferenceId = :prev'
            _upd_vals[':prev'] = str(invoice.get('referenceId') or '')
            _upd_vals[':seq'] = collection_seq
            _upd_names['#seq'] = order_keys.INVOICE_COLLECT_SEQ_ATTR
            _condition = '#seq = :seq'
        else:
            _upd_expr = ('SET #st = :st, #ua = :now, '
                         'referenceId = if_not_exists(referenceId, :ref)')
            _condition = 'attribute_not_exists(referenceId) OR referenceId = :ref'
        if phone_number_id:
            _upd_expr += ', awsPhoneNumberId = :ph'
            _upd_vals[':ph'] = phone_number_id
        table.update_item(
            Key={'invoiceId': invoice_id},
            UpdateExpression=_upd_expr,
            ConditionExpression=_condition,
            ExpressionAttributeNames=_upd_names,
            ExpressionAttributeValues=_upd_vals,
        )
    except Exception as e:
        # The `PAYREF#` row is what the webhook reconciles on, so a failed write-back does not
        # break settlement - it only breaks the invoice-dedup join, which degrades to creating a
        # second invoice row rather than losing a payment. ERROR so it is repaired rather than
        # discovered.
        logger.error(json.dumps({
            'event': 'invoice_reference_writeback_failed', 'invoiceId': invoice_id,
            'referenceId': reference_id, 'error': type(e).__name__, 'requestId': request_id,
        }))

    # NOTE: Do NOT send invoice image here — receipt with PAID stamp
    # is generated and sent AFTER payment is captured (in inbound handler).

    # `accepted`, never `sent` and never `delivered`. Meta accepting an `order_details` message
    # is not the customer receiving it: delivery and read are separate webhook events on the
    # message, and this row records only what we actually observed - that the request was taken
    # for sending.
    _log_delivery('accepted', wa_message_id=wa_message_id)

    logger.info(json.dumps({
        'event': 'payment_link_sent', 'invoiceId': invoice_id,
        # `referenceId` is logged IN FULL, deliberately: it is not a secret and not a phone
        # number, it is the correlation id that lets this money path be traced with no masked
        # field. The phone is masked on the same line.
        'referenceId': reference_id, 'toPhone': mask_phone(customer_phone),
        'paymentAttemptId': payment_attempt_id,
        'freshlyReserved': freshly_reserved,
        # INTEGER paise and a display STRING. A string cannot be arithmetic'd by accident.
        'totalPaise': total_paise, 'total': pay_status.rupees_str(total_paise),
        'requestId': request_id,
    }))

    return _resp(200, {
        'invoiceId': invoice_id,
        'referenceId': reference_id,
        'paymentAttemptId': payment_attempt_id,
        'status': 'payment_link_sent',
        'deduplicated': not freshly_reserved,
        'toPhone': customer_phone,
        'totalPaise': total_paise,
        'total': pay_status.rupees_str(total_paise),
    })


# ─── Send Order Status (fulfilment lifecycle) ───

def send_order_status(invoice_id: str, target_status: str, description: str,
                      phone_number_id: str, request_id: str) -> Dict:
    """Send a WhatsApp order_status fulfilment update (shipped / completed / …) for a PAID order.

    Separate from the payment path on purpose. `send_payment_link` asks the customer to PAY;
    this one tells a customer who ALREADY PAID what happened to their order next. Meta owns the
    order's real lifecycle, so this validates the requested transition against the status this
    invoice last recorded (`wa_order_status.can_transition`) and refuses locally what Meta would
    refuse with 2046/2047 — keeping a bad request off the wire and giving staff a named reason —
    then invokes `outbound-whatsapp` with the `isOrderStatus` envelope.

    Guards, in order:
      * the invoice must exist and be PAID. A fulfilment update on an unpaid order is meaningless,
        and `canceled` on a paid order is Meta error 2047 — the unpaid-cancel path is
        `cancel_invoice`, never this one.
      * the target must be a staff-drivable fulfilment status (`wa_order_status.STAFF_FULFILMENT_TARGETS`).
      * the transition from the invoice's current `orderStatus` (defaulting to `processing`,
        which capture set) to the target must be legal.
      * the sender must be a permitted payment WABA, reusing the one allowlist the payment path
        uses, so a status update cannot leave from a number the order was never sent from.
    """
    if not invoice_id:
        return _resp(400, {'error': 'invoiceId required'})

    target = wa_order_status.normalise(target_status)
    if target not in wa_order_status.STAFF_FULFILMENT_TARGETS:
        return _resp(400, {
            'error': ('That is not a fulfilment status staff can send. Allowed: '
                      + ', '.join(sorted(wa_order_status.STAFF_FULFILMENT_TARGETS))
                      + '. A cancellation of an unpaid order is done through Cancel Invoice.'),
            'code': 'ORDER_STATUS_NOT_ALLOWED',
        })

    phone_number_id = phone_number_id or wa_payment_request.PHONE_NUMBER_ID_1
    if phone_number_id not in wa_payment_request.PAYMENT_SENDERS:
        return _resp(409, {
            'error': wa_payment_request.REFUSAL_MESSAGES[
                wa_payment_request.WA_PAY_SENDER_NOT_PERMITTED],
            'code': wa_payment_request.WA_PAY_SENDER_NOT_PERMITTED,
        })

    table = dynamodb.Table(INVOICES_TABLE)
    resp = table.get_item(Key={'invoiceId': invoice_id})
    invoice = resp.get('Item')
    if not invoice:
        return _resp(404, {'error': 'Invoice not found'})

    # Paid-ness, ranked (not `== 'captured'`): a fulfilment update only makes sense once money
    # moved, and `refunded`/`disputed` are past capture too. An unpaid order has nothing to ship.
    current_payment = invoice.get('paymentStatus', '')
    if pay_status.rank(current_payment) < pay_status.STATUS_RANK[pay_status.CAPTURED]:
        return _resp(400, {
            'error': 'This order is not paid yet, so it has no fulfilment status to update.',
            'code': 'ORDER_NOT_PAID',
            'paymentStatus': pay_status.canonical(current_payment),
        })

    customer_phone = invoice.get('customerPhone', '')
    if not customer_phone:
        return _resp(400, {'error': 'No customer phone on invoice'})
    reference_id = invoice.get('referenceId', '')
    if not reference_id:
        return _resp(400, {'error': 'No referenceId on invoice'})

    # Capture sets the order to `processing` (razorpay-webhook), so an invoice with no recorded
    # fulfilment status is treated as `processing` — the first forward step from there is legal.
    current_status = wa_order_status.normalise(invoice.get('orderStatus', '')) \
        or wa_order_status.PROCESSING
    if current_status == target:
        return _resp(409, {
            'error': f'This order is already marked {target}.',
            'code': 'ORDER_STATUS_UNCHANGED',
            'orderStatus': current_status,
        })
    if not wa_order_status.can_transition(current_status, target):
        return _resp(409, {
            'error': (f'An order that is {current_status} cannot move to {target}. '
                      'WhatsApp refuses an out-of-order fulfilment transition.'),
            'code': 'ORDER_STATUS_TRANSITION_INVALID',
            'orderStatus': current_status,
        })

    body_text = (description or '').strip() or wa_order_status.default_body(target)
    contact = _lookup_contact_by_phone(customer_phone)
    contact_id = (contact.get('contactId') or contact.get('id', '')) if contact else ''

    wa_payload = {
        'body': json.dumps({
            'contactId': contact_id,
            'recipientPhone': customer_phone,
            'phoneNumberId': phone_number_id,
            'isOrderStatus': True,
            'orderStatusDetails': {
                'reference_id': reference_id,
                # The wire spelling Meta expects; `status_action.order.status` carries it through.
                'order_status': target,
                'description': body_text,
            },
        })
    }

    try:
        wa_response = lambda_client.invoke(
            FunctionName=os.environ.get('OUTBOUND_FUNCTION', 'wecare-outbound-whatsapp'),
            InvocationType='RequestResponse',
            Payload=json.dumps(wa_payload),
        )
        wa_result = json.loads(wa_response['Payload'].read())
        wa_status_code = int(wa_result.get('statusCode', wa_response.get('StatusCode', 0)) or 0)
    except Exception as e:  # noqa: BLE001
        logger.error(json.dumps({
            'event': 'order_status_invoke_error', 'invoiceId': invoice_id,
            'targetStatus': target, 'error': type(e).__name__, 'requestId': request_id,
        }))
        return _resp(502, {'error': 'Could not send the order status update.',
                           'code': 'ORDER_STATUS_SEND_FAILED'})

    if wa_status_code != 200:
        # Meta refused (e.g. 2046 bad transition, 2047 cancel-after-pay) or the send failed.
        # The order's recorded status is NOT advanced: the wire is the authority, and marking it
        # shipped locally when Meta rejected the message would be a lie on the invoice row.
        logger.warning(json.dumps({
            'event': 'order_status_send_rejected', 'invoiceId': invoice_id,
            'targetStatus': target, 'waStatus': wa_status_code, 'requestId': request_id,
        }))
        return _resp(502, {'error': 'WhatsApp did not accept the order status update.',
                           'code': 'ORDER_STATUS_REJECTED', 'waStatus': wa_status_code})

    # The send succeeded, so record the new fulfilment status on the invoice row. `orderStatus`
    # is NOT a financial field — it does not touch the issued-invoice immutability contract — so
    # advancing it on a paid, issued invoice is correct.
    now = int(time.time())
    try:
        table.update_item(
            Key={'invoiceId': invoice_id},
            UpdateExpression='SET orderStatus = :os, orderStatusUpdatedAt = :now, updatedAt = :now',
            ExpressionAttributeValues={':os': target, ':now': now},
        )
    except Exception as e:  # noqa: BLE001
        # The customer already got the message; a failed row update must not read as a failed
        # send. Logged and swallowed, like the delivery-log writes elsewhere on this path.
        logger.error(json.dumps({
            'event': 'order_status_row_update_failed', 'invoiceId': invoice_id,
            'targetStatus': target, 'error': type(e).__name__, 'requestId': request_id,
        }))

    try:
        dynamodb.Table(INVOICE_DELIVERY_TABLE).put_item(Item={
            'invoiceId': invoice_id,
            'timestamp': now,
            'channel': 'whatsapp_order_status',
            'toNumber': customer_phone,
            'waMessageId': str((wa_result.get('body') and json.loads(wa_result['body']).get(
                'whatsappMessageId')) or '') if isinstance(wa_result.get('body'), str) else '',
            'status': target,
            'imageUrl': '',
            'phoneNumberId': phone_number_id,
            'contactId': contact_id,
            'error': '',
        })
    except Exception:  # noqa: BLE001
        pass

    logger.info(json.dumps({
        'event': 'order_status_sent', 'invoiceId': invoice_id, 'referenceId': reference_id,
        'fromStatus': current_status, 'toStatus': target, 'requestId': request_id,
    }))
    return _resp(200, {'invoiceId': invoice_id, 'referenceId': reference_id,
                       'orderStatus': target, 'previousStatus': current_status,
                       'status': 'order_status_sent'})


# ─── Cancel Invoice ───

def cancel_invoice(invoice_id: str, reason: str, request_id: str) -> Dict:
    """Cancel/void an unpaid invoice without racing a concurrent capture.

    Cancellation preserves the invoice row and GST number. The write is conditional on the exact
    payment/document/notes/collection state read above, so a webhook or another operator cannot be
    overwritten by a stale admin request.
    """
    if not invoice_id:
        return _resp(400, {'error': 'invoiceId required'})

    reason = str(reason or '').strip()
    if len(reason) > 500 or any(
            (ord(ch) < 32 and ch not in '\\r\\n\\t') or ord(ch) == 127
            for ch in reason):
        return _resp(400, {
            'error': 'Cancellation reason is overlong or contains invalid control characters',
            'errorCode': 'INVOICE_CANCEL_REASON_INVALID',
        })

    table = dynamodb.Table(INVOICES_TABLE)
    try:
        invoice = table.get_item(
            Key={'invoiceId': invoice_id}, ConsistentRead=True
        ).get('Item')
    except Exception as exc:  # noqa: BLE001
        logger.error(json.dumps({
            'event': 'invoice_cancel_read_failed', 'invoiceId': invoice_id,
            'error': type(exc).__name__, 'requestId': request_id,
        }))
        return _resp(503, {
            'error': 'Invoice state could not be verified',
            'errorCode': 'INVOICE_CANCEL_READ_FAILED',
            'retryable': True,
        })
    if not invoice:
        return _resp(404, {'error': 'Invoice not found'})

    def _is_cancelled(row: Dict[str, Any]) -> bool:
        return any(
            str(row.get(field) or '').strip().lower() in ('cancelled', 'canceled')
            for field in ('status', 'paymentStatus')
        )

    def _money_status(row: Dict[str, Any]) -> str:
        # Legacy invoices may lack paymentStatus but still carry a money word in status.
        return str(row.get('paymentStatus') or row.get('status') or '')

    current_payment = _money_status(invoice)
    if pay_status.rank(current_payment) >= pay_status.STATUS_RANK[pay_status.CAPTURED]:
        return _resp(400, {
            'error': 'Cannot cancel a paid invoice. Use refund instead.',
            'errorCode': 'INVOICE_CANCEL_MONEY_MOVED',
            'paymentStatus': pay_status.canonical(current_payment),
        })

    idempotent = _is_cancelled(invoice)
    next_seq = int(invoice.get(order_keys.INVOICE_COLLECT_SEQ_ATTR, 0) or 0)

    if not idempotent:
        existing_notes = str(invoice.get('notes') or '')
        cancel_note = f"Cancelled: {reason}" if reason else 'Cancelled by admin'
        new_notes = f"{existing_notes}\\n{cancel_note}".strip() if existing_notes else cancel_note
        next_seq += 1
        now = int(time.time())

        expr_names = {
            '#st': 'status',
            '#ps': 'paymentStatus',
            '#ua': 'updatedAt',
            '#notes': 'notes',
            '#seq': order_keys.INVOICE_COLLECT_SEQ_ATTR,
        }
        expr_values = {
            ':st': 'cancelled',
            ':ps': 'cancelled',
            ':now': now,
            ':notes': new_notes,
            ':seq': next_seq,
        }
        condition_parts = ['attribute_exists(invoiceId)']
        for guard_name, field, alias in (
            ('status', 'status', '#st'),
            ('payment', 'paymentStatus', '#ps'),
            ('notes', 'notes', '#notes'),
            ('sequence', order_keys.INVOICE_COLLECT_SEQ_ATTR, '#seq'),
        ):
            if field in invoice:
                value_alias = f':expected_{guard_name}'
                expr_values[value_alias] = invoice.get(field)
                condition_parts.append(f'{alias} = {value_alias}')
            else:
                condition_parts.append(f'attribute_not_exists({alias})')

        try:
            table.update_item(
                Key={'invoiceId': invoice_id},
                UpdateExpression=('SET #st = :st, #ps = :ps, #ua = :now, #notes = :notes, '
                                  '#seq = :seq'),
                ConditionExpression=' AND '.join(condition_parts),
                ExpressionAttributeNames=expr_names,
                ExpressionAttributeValues=expr_values,
            )
        except Exception as exc:  # noqa: BLE001
            if not order_keys.is_conditional_failure(exc):
                return _resp(500, {'error': str(exc)})

            # The row changed after our verified read. Re-read before deciding whether that means
            # another cancel already won, a payment capture won, or a harmless edit requires retry.
            try:
                latest = table.get_item(
                    Key={'invoiceId': invoice_id}, ConsistentRead=True
                ).get('Item')
            except Exception as read_exc:  # noqa: BLE001
                logger.error(json.dumps({
                    'event': 'invoice_cancel_reread_failed', 'invoiceId': invoice_id,
                    'error': type(read_exc).__name__, 'requestId': request_id,
                }))
                return _resp(503, {
                    'error': 'Invoice changed and its latest state could not be verified',
                    'errorCode': 'INVOICE_CANCEL_READ_FAILED',
                    'retryable': True,
                })

            if not latest:
                return _resp(409, {
                    'error': 'Invoice changed while cancellation was being applied',
                    'errorCode': 'INVOICE_CANCEL_STALE',
                })

            latest_payment = _money_status(latest)
            if pay_status.rank(latest_payment) >= pay_status.STATUS_RANK[pay_status.CAPTURED]:
                return _resp(409, {
                    'error': 'Payment completed while cancellation was being applied; invoice was not cancelled',
                    'errorCode': 'INVOICE_CANCEL_PAYMENT_CHANGED',
                    'paymentStatus': pay_status.canonical(latest_payment),
                })

            if _is_cancelled(latest):
                invoice = latest
                next_seq = int(latest.get(order_keys.INVOICE_COLLECT_SEQ_ATTR, 0) or 0)
                idempotent = True
            else:
                return _resp(409, {
                    'error': 'Invoice changed while cancellation was being applied; reload and retry',
                    'errorCode': 'INVOICE_CANCEL_STALE_RETRY',
                    'retryable': True,
                })

    # Release the collection claim only after cancellation is known committed. This is safe on an
    # idempotent retry too: a missing claim simply means the first cancellation already released it.
    released = False
    try:
        released = order_keys.release_invoice_collection(
            dynamodb.Table(COMMERCE_KEYS_TABLE), invoice_id=invoice_id)
    except Exception as exc:  # noqa: BLE001
        logger.error(json.dumps({
            'event': 'invoice_collection_release_failed', 'invoiceId': invoice_id,
            'error': type(exc).__name__, 'requestId': request_id,
        }))

    logger.info(json.dumps({
        'event': 'invoice_cancelled', 'invoiceId': invoice_id,
        'reason': reason, 'collectionSeq': next_seq, 'collectionReleased': released,
        'idempotent': idempotent, 'requestId': request_id,
    }))

    return _resp(200, {
        'invoiceId': invoice_id,
        'status': 'cancelled',
        'collectionSeq': next_seq,
        'idempotent': idempotent,
    })


# ─── Delete Invoice — REFUSED. Cancel instead. ───

def delete_invoice(invoice_id: str, body: Dict, request_id: str) -> Dict:
    """Refuses 410. Hard-deleting a GST invoice is not safe at any role.

    WHY A REFUSAL RATHER THAN A NARROWED DELETE
    -------------------------------------------
    The obvious fix was "refuse when the invoice is issued or paid, allow it otherwise".
    There is no otherwise. `create_invoice` assigns `invoiceNumber` from the consecutive
    GST series to EVERY invoice at creation — it is the last thing that can fail there,
    and that code already states the rule this refusal enforces:

        "a number outside the consecutive series is worse than no invoice, because it
         cannot be reassigned once it has gone out"

    So every row this function can reach is an issued, numbered tax document and there is
    no draft state to permit. What it used to do, in one call:

      * hard-deleted the invoice row, paid or not — no status guard of any kind, unlike
        `update_invoice` (blocks amount edits past `captured`) and `cancel_invoice`
        (blocks voiding past `captured`). This route was the hole in a rule the other two
        already enforced.
      * deleted the rendered PDF/PNG from S3 — the artefact the customer was sent.
      * with `adjustSequence`, DECREMENTED the GST sequence counter, so the next invoice
        reused a number that had already gone out. Two documents, one number.

    `cancel_invoice` is the supported void: it keeps the row and the number, records the
    reason, refuses once money has moved, and bumps the collection sequence so a re-raise
    composes a fresh payment reservation. That already exists and is what a void should be.

    410 rather than 403 because the caller's role is not the problem and a better token
    will not help — the capability is withdrawn, and the body names its replacement.
    """
    if not invoice_id:
        return _resp(400, {'error': 'invoiceId required'})

    # Best effort, not fail-closed: nothing is being deleted, so a missing audit row costs
    # a log line rather than an unrecorded destruction. Recorded at all because an attempt
    # to hard-delete a tax document is worth knowing about.
    record_audit(
        action='invoice.delete',
        actor=_audit_actor(),
        resource_type='invoice',
        resource_id=invoice_id,
        details={'outcome': 'refused', 'reason': 'gst_invoice_immutable',
                 'adjustSequenceRequested': bool((body or {}).get('adjustSequence')),
                 'requestId': request_id},
    )
    logger.warning(json.dumps({
        'event': 'invoice_delete_refused', 'invoiceId': invoice_id, 'requestId': request_id,
    }))
    return _resp(410, {
        'error': 'Invoices cannot be deleted',
        'errorCode': 'INVOICE_IMMUTABLE',
        'detail': ('Every invoice carries a number from the consecutive GST series, and '
                   'that number cannot be reassigned once issued. Cancel the invoice '
                   'instead — it is voided, the reason is recorded, and the number is '
                   'preserved.'),
        'use': f'POST /invoices/{invoice_id}/cancel',
    })


def _delete_invoice_withdrawn(invoice_id: str, body: Dict, request_id: str) -> Dict:
    """UNREACHABLE. The former hard-delete, kept as the record of what was withdrawn.

    Here rather than deleted outright so a reader can see exactly which operations this
    PR removed — the S3 asset delete and the sequence decrement in particular — without
    reconstructing them from history. Nothing calls this.
    """
    table = dynamodb.Table(INVOICES_TABLE)
    resp = table.get_item(Key={'invoiceId': invoice_id})
    invoice = resp.get('Item')
    if not invoice:
        return _resp(404, {'error': 'Invoice not found'})

    inv_number = invoice.get('invoiceNumber', '')
    ref_id = invoice.get('referenceId', '')

    # Delete associated S3 assets (images, PDFs)
    try:
        assets_resp = table.query(
            IndexName='invoiceId-index',
            KeyConditionExpression=boto3.dynamodb.conditions.Key('invoiceId').eq(invoice_id),
        ) if False else {'Items': []}  # Assets are in same table as nested or separate
    except Exception as e:
        logger.warning(f'Invoice asset query failed for {invoice_id}: {e}')

    # Try to delete S3 files for this invoice
    try:
        prefix = f'{INVOICE_PREFIX}wecare-digital-{ref_id or invoice_id}'
        s3_resp = s3.list_objects_v2(Bucket=MEDIA_BUCKET, Prefix=prefix, MaxKeys=20)
        for obj in s3_resp.get('Contents', []):
            s3.delete_object(Bucket=MEDIA_BUCKET, Key=obj['Key'])
            logger.info(json.dumps({'event': 'invoice_s3_deleted', 'key': obj['Key']}))
    except Exception as s3_err:
        logger.warning(json.dumps({'event': 'invoice_s3_delete_error', 'error': str(s3_err)}))

    # Delete the invoice record
    try:
        table.delete_item(Key={'invoiceId': invoice_id})
    except Exception as e:
        return _resp(500, {'error': str(e)})

    # Adjust sequence counter if requested
    adjust_seq = body.get('adjustSequence', False)
    if adjust_seq and inv_number:
        try:
            # Extract FY and sequence from invoice number (format: WD/25-26/000042)
            parts = inv_number.split('/')
            if len(parts) == 3:
                fy = parts[1]
                seq_table = dynamodb.Table(INVOICES_TABLE.replace('InvoicesTable', 'SystemConfigTable'))
                seq_table.update_item(
                    Key={'id': f'invoice_seq_{fy}'},
                    UpdateExpression='SET lastSeq = lastSeq - :one',
                    ConditionExpression='lastSeq > :zero',
                    ExpressionAttributeValues={':one': 1, ':zero': 0},
                )
        except Exception as seq_err:
            logger.warning(json.dumps({'event': 'seq_adjust_error', 'error': str(seq_err)}))

    logger.info(json.dumps({
        'event': 'invoice_deleted', 'invoiceId': invoice_id,
        'invoiceNumber': inv_number, 'requestId': request_id,
    }))

    return _resp(200, {'invoiceId': invoice_id, 'deleted': True, 'invoiceNumber': inv_number})


# ─── Clear All Invoice Data — REFUSED. ───

def clear_all_invoice_data(request_id: str) -> Dict:
    """Refuses 410. There is no safe version of this operation.

    WHY A REFUSAL RATHER THAN A GUARDED WIPE
    ----------------------------------------
    Every table it emptied is a record this business is required to keep, and the set is
    not separable into "history" and "scratch":

      InvoicesTable          issued GST documents (see `delete_invoice` — all of them are
                             numbered from the consecutive series at creation)
      InvoiceSequenceTable   the GST counter itself. Emptying it restarts numbering at 1,
                             so the next invoice reuses a number already sent to a
                             customer — the same defect as `adjustSequence`, applied to
                             the whole series at once.
      PaymentsTable          money of record
      RazorpayWebhookLogTable  the provider's account of what it charged, i.e. the
                             evidence in a chargeback
      InvoiceItems / Assets / DeliveryLog  the line items, the rendered documents and the
                             proof of delivery for the above

    Narrowing it to "unpaid only" does not help: unpaid invoices are still issued numbered
    documents, and the sequence counter and the webhook log are not per-invoice, so they
    would be wiped wholesale or not at all. Any version that deletes something deletes
    financial history, and a version that deletes nothing is this refusal.

    It was also reachable three ways — `DELETE /invoices/clear-all`,
    `POST /invoices/clear-all`, and `POST /invoices` with `_action=clear-all`, which ran
    BEFORE every other POST arm. All three now land here.

    Cancel an individual invoice with `POST /invoices/{id}/cancel`. Genuine cache clearing
    lives in `operations/system-cleanup`, whose allow-list deliberately excludes every
    table named above.
    """
    record_audit(
        action='invoice.clear_all',
        actor=_audit_actor(),
        resource_type='invoice',
        resource_id='clear-all',
        details={'outcome': 'refused', 'reason': 'financial_history_immutable',
                 'requestId': request_id},
    )
    logger.warning(json.dumps({'event': 'invoice_clear_all_refused', 'requestId': request_id}))
    return _resp(410, {
        'error': 'Bulk invoice deletion has been withdrawn',
        'errorCode': 'INVOICE_HISTORY_IMMUTABLE',
        'detail': ('This cleared issued GST invoices, the GST sequence counter, payments '
                   'and the provider webhook log — all records that must be retained. '
                   'Cancel individual invoices instead; cache clearing lives in '
                   'system-cleanup, which cannot select any of these tables.'),
        'use': 'POST /invoices/{invoiceId}/cancel',
    })


def _clear_all_invoice_data_withdrawn(request_id: str) -> Dict:
    """UNREACHABLE. The former bulk wipe, kept as the record of what was withdrawn."""
    tables_to_clear = {
        'invoices': (INVOICES_TABLE, 'invoiceId'),
        'invoice_items': (INVOICE_ITEMS_TABLE, None),
        'invoice_assets': (INVOICE_ASSETS_TABLE, None),
        'invoice_delivery_log': (INVOICE_DELIVERY_TABLE, None),
        'invoice_sequence': (INVOICE_SEQ_TABLE, None),
        'payments': (PAYMENTS_TABLE, 'id'),
        'razorpay_webhook_log': ('stack-wecare-digital-RazorpayWebhookLogTable', 'id'),
    }
    results = {}
    total = 0
    ddb_client = boto3.client('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

    for key, (table_name, known_pk) in tables_to_clear.items():
        try:
            # Discover key schema
            desc = ddb_client.describe_table(TableName=table_name)
            key_names = [k['AttributeName'] for k in desc['Table']['KeySchema']]
            table = dynamodb.Table(table_name)
            deleted = 0
            scan_kwargs = {'ProjectionExpression': ', '.join([f'#{chr(97+i)}' for i in range(len(key_names))]),
                           'ExpressionAttributeNames': {f'#{chr(97+i)}': n for i, n in enumerate(key_names)}}
            while True:
                resp = table.scan(**scan_kwargs)
                items = resp.get('Items', [])
                if not items:
                    break
                with table.batch_writer() as batch:
                    for item in items:
                        batch.delete_item(Key={k: item[k] for k in key_names})
                        deleted += 1
                if 'LastEvaluatedKey' not in resp:
                    break
                scan_kwargs['ExclusiveStartKey'] = resp['LastEvaluatedKey']
            results[key] = deleted
            total += deleted
        except Exception as e:
            logger.warning(f"Clear {key} error: {e}")
            results[key] = 0

    # Clear S3 invoices/ prefix
    s3_deleted = 0
    try:
        paginator = s3.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=MEDIA_BUCKET, Prefix=INVOICE_PREFIX):
            objects = page.get('Contents', [])
            if objects:
                s3.delete_objects(Bucket=MEDIA_BUCKET, Delete={'Objects': [{'Key': o['Key']} for o in objects]})
                s3_deleted += len(objects)
        results['s3_invoices'] = s3_deleted
        total += s3_deleted
    except Exception as e:
        logger.warning(f"Clear S3 invoices error: {e}")
        results['s3_invoices'] = 0

    logger.info(json.dumps({'event': 'clear_all_invoice_data', 'results': results, 'total': total, 'requestId': request_id}))
    return _resp(200, {'success': True, 'results': results, 'totalDeleted': total})



# ─── Provider Refund Initiation (dormant unless explicitly enabled) ───

def _refund_staff_actor(auth: Optional[Dict]) -> str:
    """Refund initiation requires a real authenticated staff principal.

    Unlike harmless internal invoice jobs, an internal Lambda invoke with no API identity is
    NOT accepted here. That keeps an irreversible provider action behind Admin+MFA even though
    require_auth intentionally permits trusted Lambda-to-Lambda calls elsewhere in this handler.
    """
    if not isinstance(auth, dict):
        return ''
    for key in ('username', 'email'):
        value = str(auth.get(key) or '').strip()
        if value:
            return value
    return ''


def _validate_refund_reason(reason: object) -> Tuple[str, Optional[Dict]]:
    """Bound the operator refund reason the same way cancel_invoice bounds its reason.

    The reason is operator audit metadata, never a money input: the server stays authoritative
    on the cap and eligibility regardless of what it says. It is required (the UI demands it for
    the audit record), trimmed, capped at 500 characters, and rejected if it carries control
    characters, so a malformed justification never reaches the durable case / audit row.
    """
    text = str(reason or '').strip()
    if not text:
        return '', _resp(400, {
            'error': 'A refund reason is required for the audit record',
            'errorCode': 'REFUND_REASON_REQUIRED',
        })
    if len(text) > 500 or any(
            (ord(ch) < 32 and ch not in '\r\n\t') or ord(ch) == 127
            for ch in text):
        return '', _resp(400, {
            'error': 'Refund reason is overlong or contains invalid control characters',
            'errorCode': 'REFUND_REASON_INVALID',
        })
    return text, None


def _record_refund_audit_safely(*, actor: str, invoice_id: str,
                                outcome: str, submission_id: str,
                                request_id: str, refund_id: str = '',
                                reason: str = '') -> None:
    """Best-effort secondary audit after the durable return-case state write.

    The return case is the strict idempotency/audit authority. Once a provider call may have
    moved money, failure to append the generic AuditLogs row must never change the operator
    response into a retry-shaped 500.
    """
    try:
        details = {
            'outcome': outcome,
            'returnSubmissionId': submission_id,
            'requestId': request_id,
        }
        if refund_id:
            details['refundId'] = refund_id
        if reason:
            details['reason'] = reason
        record_audit(
            action='payment.refund',
            actor=actor,
            resource_type='invoice',
            resource_id=invoice_id,
            details=details,
        )
    except Exception as exc:  # noqa: BLE001 - secondary audit cannot reopen provider action
        logger.error(json.dumps({
            'event': 'refund_secondary_audit_failed',
            'invoiceId': invoice_id,
            'returnSubmissionId': submission_id,
            'outcome': outcome,
            'error': type(exc).__name__,
            'requestId': request_id,
        }))


def initiate_full_refund(invoice_id: str, body: Dict, request_id: str,
                         *, auth: Optional[Dict] = None) -> Dict:
    """Submit one full Razorpay refund for a verified refund-eligible return case.

    Eligibility is derived from durable server records only:
    returnSubmissionId -> Return / Refund case -> refund_eligible -> linked internal order
    -> invoice -> payment row. The browser cannot choose paymentId or amount. The provider
    webhook remains authoritative for the final REFUNDED state.
    """
    reason, reason_error = _validate_refund_reason(body.get('reason'))
    if reason_error is not None:
        return reason_error
    context, error = _resolve_refund_context(invoice_id, body, auth)
    if error is not None:
        return error
    assert context is not None  # noqa: S101 - narrow the type; error is None implies a context
    return _execute_refund(
        context=context,
        amount_paise=context.max_refundable_paise,
        partial=False,
        request_id=request_id,
        reason=reason,
    )


@dataclass(frozen=True)
class _RefundContext:
    """Server-derived, browser-unforgeable facts needed to post one refund.

    Every field here comes from durable records (invoice -> return case -> payment), never
    from the request body. ``captured_paise`` is the authoritative captured total and
    ``already_refunded_paise`` is whatever the webhook has already recorded as returned, so
    ``max_refundable_paise`` is the hard server cap a browser amount can never exceed.
    """
    actor: str
    invoice_id: str
    submission_id: str
    payment_id: str
    internal_order_id: str
    captured_paise: int
    already_refunded_paise: int

    @property
    def max_refundable_paise(self) -> int:
        return self.captured_paise - self.already_refunded_paise


def _resolve_refund_context(invoice_id: str, body: Dict, auth: Optional[Dict]
                            ) -> Tuple[Optional['_RefundContext'], Optional[Dict]]:
    """Derive refund eligibility from durable records only.

    Returns (context, None) when the case is eligible and nothing is yet refunded, or
    (None, response) carrying the exact HTTP response to return otherwise. An already-confirmed
    refund is reported as the idempotent success response rather than an error. The browser may
    supply returnSubmissionId but never the paymentId, order id, captured amount, or cap.
    """
    if not razorpay_refund.enabled():
        return None, _resp(409, {
            'error': 'Provider refund initiation is disabled in this deployment',
            'errorCode': 'REFUND_INITIATION_DISABLED',
        })

    actor = _refund_staff_actor(auth)
    if not actor:
        return None, _resp(403, {
            'error': 'Authenticated Admin staff actor required',
            'errorCode': 'REFUND_ACTOR_REQUIRED',
        })

    invoice_id = str(invoice_id or '').strip()
    submission_id = str(body.get('returnSubmissionId') or '').strip()
    if not invoice_id or not submission_id:
        return None, _resp(400, {
            'error': 'invoiceId and returnSubmissionId are required',
            'errorCode': 'REFUND_LINK_REQUIRED',
        })

    invoice = dynamodb.Table(INVOICES_TABLE).get_item(
        Key={'invoiceId': invoice_id}, ConsistentRead=True).get('Item') or {}
    if not invoice:
        return None, _resp(404, {'error': 'Invoice not found'})

    payment_id = str(invoice.get('paymentId') or '').strip()
    internal_order_id = str(invoice.get('internalOrderId') or '').strip()
    if not payment_id or not internal_order_id:
        return None, _resp(409, {
            'error': 'Invoice is not safely linked to an internal paid order',
            'errorCode': 'REFUND_INVOICE_LINK_REQUIRED',
        })
    if pay_status.canonical(invoice.get('paymentStatus')) != pay_status.CAPTURED:
        return None, _resp(409, {
            'error': 'Invoice is not in captured payment state',
            'errorCode': 'REFUND_INVOICE_NOT_CAPTURED',
        })

    case_table = dynamodb.Table(REFUND_CASES_TABLE)
    return_case = case_table.get_item(
        Key={'submissionId': submission_id}, ConsistentRead=True).get('Item') or {}
    if not return_case:
        return None, _resp(404, {'error': 'Return request not found'})
    if str(return_case.get('requestType') or '').strip() != 'Return / Refund':
        return None, _resp(409, {
            'error': 'Request is not a Return / Refund case',
            'errorCode': 'REFUND_RETURN_CASE_REQUIRED',
        })
    if str(return_case.get('returnStage') or '').strip().lower() != 'refund_eligible':
        return None, _resp(409, {
            'error': 'Return case is not refund eligible',
            'errorCode': 'REFUND_NOT_ELIGIBLE',
        })
    if str(return_case.get('orderId') or '').strip() != internal_order_id:
        return None, _resp(409, {
            'error': 'Return case does not belong to this invoice order',
            'errorCode': 'REFUND_ORDER_MISMATCH',
        })

    payment = dynamodb.Table(PAYMENTS_TABLE).get_item(
        Key={'id': payment_id}, ConsistentRead=True).get('Item') or {}
    if not payment:
        return None, _resp(409, {
            'error': 'Authoritative payment record is unavailable',
            'errorCode': 'REFUND_PAYMENT_REQUIRED',
        })

    payment_state = pay_status.canonical(payment.get('status'))
    # SINGLE REFUND PER PAYMENT (by design). razorpay-webhook._handle_refund marks the payment
    # REFUNDED (a monotonic rank that then blocks any later refund.* write) and SETs — does not
    # sum — refundAmountPaise on the FIRST processed refund. So once any refund (full or the
    # first partial) has settled, this branch reports the idempotent success and no second
    # partial can proceed: in practice a payment receives one refund. The cap arithmetic below
    # (captured − already_refunded) is the server authority within that single refund and fails
    # safe — it can only block or under-refund, never over-refund. Supporting multiple partials
    # per payment would require revisiting the webhook's refunded-state/accumulation semantics,
    # which stays the sole authoritative setter and is deliberately out of scope here.
    if payment_state == pay_status.REFUNDED and str(payment.get('refundId') or '').strip():
        return None, _resp(200, {
            'submitted': True,
            'webhookConfirmed': True,
            'refundId': str(payment.get('refundId')),
            'paymentId': payment_id,
            'idempotent': True,
        })
    if payment_state != pay_status.CAPTURED:
        return None, _resp(409, {
            'error': 'Payment is not in captured state',
            'errorCode': 'REFUND_PAYMENT_NOT_CAPTURED',
        })

    raw_amount = payment.get('amount')
    try:
        captured_paise = pay_status.paise(raw_amount)
        if Decimal(str(raw_amount)) != Decimal(str(captured_paise)):
            captured_paise = 0
    except (ValueError, InvalidOperation):
        captured_paise = 0
    if captured_paise <= 0:
        return None, _resp(409, {
            'error': 'Captured payment amount is unusable',
            'errorCode': 'REFUND_AMOUNT_UNUSABLE',
        })

    # Whatever the webhook has already recorded as returned on this payment row. The field is
    # written by razorpay-webhook._handle_refund (refundAmountPaise); absent/unusable degrades
    # to 0 so a missing field never inflates the remaining cap.
    try:
        already_refunded_paise = pay_status.paise(payment.get('refundAmountPaise'))
    except ValueError:
        already_refunded_paise = 0
    if already_refunded_paise >= captured_paise:
        return None, _resp(409, {
            'error': 'Captured payment is already fully refunded',
            'errorCode': 'REFUND_ALREADY_SETTLED',
        })

    return _RefundContext(
        actor=actor,
        invoice_id=invoice_id,
        submission_id=submission_id,
        payment_id=payment_id,
        internal_order_id=internal_order_id,
        captured_paise=captured_paise,
        already_refunded_paise=already_refunded_paise,
    ), None


def initiate_partial_refund(invoice_id: str, body: Dict, request_id: str,
                            *, auth: Optional[Dict] = None) -> Dict:
    """Submit one PARTIAL Razorpay refund of a browser-proposed amount, server-capped.

    Shares every eligibility and idempotency guarantee with initiate_full_refund. The browser
    proposes amountPaise, but the server is the sole authority on the cap: the amount must be a
    positive integer no greater than the authoritative captured total minus whatever the webhook
    has already recorded as refunded. Anything <=0 or over the cap is rejected before the claim,
    and the irreversible POST happens only after the case is durably claimed.
    """
    reason, reason_error = _validate_refund_reason(body.get('reason'))
    if reason_error is not None:
        return reason_error
    context, error = _resolve_refund_context(invoice_id, body, auth)
    if error is not None:
        return error
    assert context is not None  # noqa: S101 - narrow the type; error is None implies a context

    raw = body.get('amountPaise')
    if isinstance(raw, bool) or not isinstance(raw, int):
        try:
            raw = int(raw)
        except (TypeError, ValueError):
            return _resp(400, {
                'error': 'A positive integer amountPaise is required for a partial refund',
                'errorCode': 'REFUND_AMOUNT_REQUIRED',
            })
    requested_paise = raw
    if requested_paise <= 0:
        return _resp(400, {
            'error': 'Partial refund amount must be a positive integer in paise',
            'errorCode': 'REFUND_AMOUNT_INVALID',
        })
    if requested_paise > context.max_refundable_paise:
        return _resp(409, {
            'error': 'Requested amount exceeds the refundable remainder on this payment',
            'errorCode': 'REFUND_AMOUNT_OVER_CAP',
            'maxRefundablePaise': context.max_refundable_paise,
        })

    return _execute_refund(
        context=context,
        amount_paise=requested_paise,
        partial=True,
        request_id=request_id,
        reason=reason,
    )


def _execute_refund(*, context: '_RefundContext', amount_paise: int,
                    partial: bool, request_id: str, reason: str = '') -> Dict:
    """Claim the case idempotently, then post exactly one refund for ``amount_paise``.

    This is the shared tail of the full and partial paths. By the time it runs, eligibility and
    the server cap are already proven, so it owns only the durable claim, the single
    non-retried provider call, and the truthful submitted/ambiguous/rejected state writes. It
    never marks the payment refunded — the webhook remains authoritative for that.
    """
    actor = context.actor
    invoice_id = context.invoice_id
    submission_id = context.submission_id
    payment_id = context.payment_id
    internal_order_id = context.internal_order_id
    case_table = dynamodb.Table(REFUND_CASES_TABLE)
    mode = 'partial' if partial else 'full'

    now = int(time.time())
    try:
        case_table.update_item(
            Key={'submissionId': submission_id},
            UpdateExpression=(
                'SET refundInitiationState = :submitting, refundInitiationPaymentId = :pid, '
                'refundInitiationAmountPaise = :amount, refundInitiationMode = :mode, '
                'refundInitiationReason = :reason, '
                'refundInitiatedBy = :actor, refundInitiatedAt = :now'
            ),
            ConditionExpression=(
                'returnStage = :eligible AND orderId = :order '
                'AND attribute_not_exists(refundInitiationState)'
            ),
            ExpressionAttributeValues={
                ':submitting': 'submitting',
                ':pid': payment_id,
                ':amount': Decimal(str(amount_paise)),
                ':mode': mode,
                ':reason': reason,
                ':actor': actor,
                ':now': Decimal(str(now)),
                ':eligible': 'refund_eligible',
                ':order': internal_order_id,
            },
        )
    except Exception as exc:  # noqa: BLE001
        if order_keys.is_conditional_failure(exc):
            fresh = case_table.get_item(
                Key={'submissionId': submission_id}, ConsistentRead=True).get('Item') or {}
            state = str(fresh.get('refundInitiationState') or '').strip()
            if state == 'submitted' and fresh.get('providerRefundId'):
                return _resp(202, {
                    'submitted': True,
                    'webhookConfirmed': False,
                    'refundId': str(fresh.get('providerRefundId')),
                    'paymentId': payment_id,
                    'idempotent': True,
                })
            return _resp(409, {
                'error': 'Refund initiation was already claimed; reconcile provider evidence before any retry',
                'errorCode': 'REFUND_INITIATION_ALREADY_CLAIMED',
                'state': state or 'changed',
                'retryable': False,
            })
        raise

    refund_call = (
        razorpay_refund.create_partial_refund if partial
        else razorpay_refund.create_full_refund
    )
    try:
        result = refund_call(
            payment_id=payment_id,
            amount_paise=amount_paise,
            return_submission_id=submission_id,
            order_id=internal_order_id,
            request_id=request_id,
        )
    except razorpay_refund.RefundRejected as exc:
        case_table.update_item(
            Key={'submissionId': submission_id},
            UpdateExpression=(
                'SET refundInitiationState = :state, refundProviderHttpStatus = :status, '
                'refundInitiationUpdatedAt = :now'
            ),
            ConditionExpression='refundInitiationState = :submitting',
            ExpressionAttributeValues={
                ':state': 'provider_rejected',
                ':status': Decimal(str(exc.status)),
                ':now': Decimal(str(int(time.time()))),
                ':submitting': 'submitting',
            },
        )
        _record_refund_audit_safely(
            actor=actor, invoice_id=invoice_id, outcome='provider_rejected',
            submission_id=submission_id, request_id=request_id, reason=reason)
        return _resp(409, {
            'error': 'Provider rejected the refund request; review before another attempt',
            'errorCode': 'REFUND_PROVIDER_REJECTED',
            'retryable': False,
        })
    except razorpay_refund.RefundAmbiguous:
        case_table.update_item(
            Key={'submissionId': submission_id},
            UpdateExpression=(
                'SET refundInitiationState = :state, refundInitiationUpdatedAt = :now'
            ),
            ConditionExpression='refundInitiationState = :submitting',
            ExpressionAttributeValues={
                ':state': 'provider_outcome_unknown',
                ':now': Decimal(str(int(time.time()))),
                ':submitting': 'submitting',
            },
        )
        _record_refund_audit_safely(
            actor=actor, invoice_id=invoice_id, outcome='provider_outcome_unknown',
            submission_id=submission_id, request_id=request_id, reason=reason)
        return _resp(503, {
            'error': 'Provider outcome is unknown; reconcile Razorpay/webhook evidence before retry',
            'errorCode': 'REFUND_PROVIDER_OUTCOME_UNKNOWN',
            'retryable': False,
        })

    try:
        case_table.update_item(
            Key={'submissionId': submission_id},
            UpdateExpression=(
                'SET refundInitiationState = :submitted, providerRefundId = :rid, '
                'providerRefundAmountPaise = :amount, refundInitiationUpdatedAt = :now'
            ),
            ConditionExpression='refundInitiationState = :submitting',
            ExpressionAttributeValues={
                ':submitted': 'submitted',
                ':rid': result.refund_id,
                ':amount': Decimal(str(result.amount_paise)),
                ':now': Decimal(str(int(time.time()))),
                ':submitting': 'submitting',
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(json.dumps({
            'event': 'refund_provider_submitted_audit_pending',
            'invoiceId': invoice_id,
            'returnSubmissionId': submission_id,
            'refundId': result.refund_id,
            'error': type(exc).__name__,
            'requestId': request_id,
        }))
        return _resp(503, {
            'error': 'Provider accepted the refund but local submission state needs reconciliation',
            'errorCode': 'REFUND_PROVIDER_SUBMITTED_AUDIT_PENDING',
            'refundId': result.refund_id,
            'paymentId': payment_id,
            'retryable': False,
        })

    _record_refund_audit_safely(
        actor=actor, invoice_id=invoice_id, outcome='provider_submitted',
        submission_id=submission_id, request_id=request_id,
        refund_id=result.refund_id, reason=reason)
    logger.warning(json.dumps({
        'event': 'refund_provider_submitted',
        'invoiceId': invoice_id,
        'refundId': result.refund_id,
        'requestId': request_id,
    }))
    return _resp(202, {
        'submitted': True,
        'webhookConfirmed': False,
        'refundId': result.refund_id,
        'paymentId': payment_id,
        'amountPaise': result.amount_paise,
        'mode': mode,
        'awaitWebhook': True,
    })



# ─── Add Remark / Refund / Credit Note ───

#: The author a remark carries when no API Gateway identity exists.
#:
#: `require_auth` SKIPS authentication for an internal Lambda-to-Lambda invoke, so there is no
#: token to read on that path. The label names THIS FUNCTION rather than anything out of the
#: payload: on an internal invoke the only unforgeable fact about the writer is which function
#: performed the write, and a caller-supplied name is precisely what this change removes.
_SYSTEM_REMARK_AUTHOR = 'system:invoice-engine'


def _remark_author(auth: Optional[Dict]) -> str:
    """Who the stored remark says wrote it — from the TOKEN, never from the body.

    `body['author']` is ignored entirely. It used to default to `'admin'`, so every remark in
    the table was signed by whoever the browser said, and a refund note - the record of money
    leaving - was attributable to nobody.
    """
    if isinstance(auth, dict):
        for attribute in ('username', 'email'):
            name = str(auth.get(attribute, '') or '').strip()
            if name:
                return name
    return _SYSTEM_REMARK_AUTHOR


def _resolve_refund_evidence(*, invoice: Dict, body: Dict, request_id: str) -> Optional[str]:
    """The provider refund id, PROVEN against `PaymentsTable`, or `None`.

    A refund is money leaving. `type='refund'` used to write `paymentStatus='refunded'` on the
    strength of a request body alone, so an invoice could read as refunded with nothing refunded
    anywhere - unreconcilable in the direction that loses money twice (the customer is told they
    were refunded, and the capture still sits with the provider).

    The evidence is the provider's own record as `razorpay-webhook._handle_refund` stored it: a
    `refund.processed` event writes `refundId` onto the payment row and moves its status to
    `refunded` under the rank condition. So the bar here is "the webhook has seen this refund",
    which is the same fact a human would check in the Razorpay dashboard.

    The webhook LOG table is deliberately not consulted: it is keyed by the dedup id, so
    resolving a refund id there needs a scan, and it carries no fact the payment row does not
    already carry by then.
    """
    refund_id = str(body.get('refundId') or body.get('providerRefundId') or '').strip()
    payment_id = str(body.get('paymentId') or invoice.get('paymentId') or '').strip()
    if not refund_id or not payment_id:
        return None

    try:
        # A POINT READ: `PaymentsTable`'s key attribute is `id` and `razorpay-webhook` writes
        # `id = payment_id`, so no scan is needed on this path.
        payment = dynamodb.Table(PAYMENTS_TABLE).get_item(
            Key={'id': payment_id}).get('Item') or {}
    except Exception as error:  # noqa: BLE001
        # Fails toward NO refund state. An unreadable payment row is "we could not prove it",
        # which must never read the same as "it was refunded".
        logger.error(json.dumps({
            'event': 'refund_evidence_unreadable', 'paymentId': payment_id,
            'error': type(error).__name__, 'requestId': request_id,
        }))
        return None

    if str(payment.get('refundId', '') or '').strip() != refund_id:
        logger.warning(json.dumps({
            'event': 'refund_evidence_not_on_record', 'paymentId': payment_id,
            'requestId': request_id,
        }))
        return None

    if pay_status.canonical(payment.get('status', '')) != pay_status.REFUNDED:
        logger.warning(json.dumps({
            'event': 'refund_evidence_payment_not_refunded', 'paymentId': payment_id,
            'storedStatus': pay_status.canonical(payment.get('status', '')),
            'requestId': request_id,
        }))
        return None

    return refund_id


def add_remark(invoice_id: str, body: Dict, request_id: str,
               *, auth: Optional[Dict] = None) -> Dict:
    """Add a remark, refund note, or credit note to an invoice.

    `auth` is KEYWORD-ONLY and defaults to `None`, which resolves to the server-side system
    label - so a caller that does not pass an identity cannot accidentally inherit one from the
    request body.
    """
    if not invoice_id:
        return _resp(400, {'error': 'invoiceId required'})

    remark_type = body.get('type', 'remark')  # remark | refund | credit_note
    text = body.get('text', '')
    # A refund or credit-note amount is MONEY OF RECORD: it is persisted onto the invoice and
    # becomes `refundAmount` / `creditNoteAmount`. So it is read as exact integer paise and a
    # figure that cannot be expressed in paise is a 400 rather than a silent float.
    try:
        amount_paise = wa_payment_request.exact_paise(body.get('amount', 0))
    except wa_payment_request.PaymentRequestRefused:
        return _resp(400, {'error': 'amount must be an exact rupee figure (two decimal places)'})
    author = _remark_author(auth)

    if not text and remark_type == 'remark':
        return _resp(400, {'error': 'text required for remarks'})

    table = dynamodb.Table(INVOICES_TABLE)
    resp = table.get_item(Key={'invoiceId': invoice_id})
    invoice = resp.get('Item')
    if not invoice:
        return _resp(404, {'error': 'Invoice not found'})

    # Resolved BEFORE anything is written, so the remark and the payment state are decided from
    # one answer rather than two reads that could disagree.
    refund_evidence = (_resolve_refund_evidence(invoice=invoice, body=body, request_id=request_id)
                       if remark_type == 'refund' else None)

    now = int(time.time())
    remark_entry = {
        'id': str(uuid.uuid4())[:8],
        'type': remark_type,
        'text': text,
        # INTEGER paise is the stored fact; the rupee figure beside it is a display STRING.
        'amountPaise': amount_paise,
        'amount': pay_status.rupees_str(amount_paise),
        'author': author,
        # The evidence trail, empty when there is none: a reader can tell a proven refund from a
        # note that someone intended one.
        'providerRefundId': refund_evidence or '',
        'createdAt': now,
    }

    # Append to remarks list
    existing_remarks = invoice.get('remarks', [])
    if isinstance(existing_remarks, str):
        existing_remarks = json.loads(existing_remarks) if existing_remarks else []
    existing_remarks.append(remark_entry)

    update_expr = 'SET remarks = :r, updatedAt = :now'
    expr_values = {
        ':r': json.dumps(existing_remarks),
        ':now': now,
    }

    # For a PROVEN refund, also update status
    if remark_type == 'refund' and refund_evidence:
        # The rupee column stays for the existing readers, derived EXACTLY from the integer
        # rather than from a float; the paise column beside it is the comparable one.
        update_expr += (', refundAmount = :ra, refundAmountPaise = :rap, refundAt = :rat, '
                        'refundId = :rid, paymentStatus = :ps')
        expr_values[':ra'] = Decimal(amount_paise) / 100
        expr_values[':rap'] = amount_paise
        expr_values[':rat'] = now
        expr_values[':rid'] = refund_evidence
        # The vocabulary's own word, not a local spelling of it.
        expr_values[':ps'] = pay_status.for_storage(pay_status.REFUNDED)
    elif remark_type == 'credit_note':
        update_expr += (', creditNoteAmount = :cna, creditNoteAmountPaise = :cnap, '
                        'creditNoteAt = :cnt')
        expr_values[':cna'] = Decimal(amount_paise) / 100
        expr_values[':cnap'] = amount_paise
        expr_values[':cnt'] = now

    try:
        table.update_item(
            Key={'invoiceId': invoice_id},
            UpdateExpression=update_expr,
            ExpressionAttributeValues=expr_values,
        )
    except Exception as e:
        return _resp(500, {'error': str(e)})

    logger.info(json.dumps({
        'event': f'invoice_{remark_type}_added', 'invoiceId': invoice_id,
        'remarkType': remark_type, 'amountPaise': amount_paise,
        'amount': pay_status.rupees_str(amount_paise), 'author': author,
        'refundEvidence': bool(refund_evidence), 'requestId': request_id,
    }))

    if remark_type == 'refund' and not refund_evidence:
        # The remark IS recorded - the operator's note of what they believe happened is worth
        # keeping, and discarding it would push them to record it somewhere we cannot see - but
        # the payment state is untouched and the answer is a refusal, not a 200. A 200 here is
        # what let the invoice read `refunded` with no refund behind it.
        logger.warning(json.dumps({
            'event': 'invoice_refund_evidence_required', 'invoiceId': invoice_id,
            'note': 'remark recorded, paymentStatus unchanged', 'requestId': request_id,
        }))
        return _resp(400, {
            'error': ('A refund needs the provider refund id. The remark was recorded and the '
                      'payment state is unchanged. Nothing has been refunded.'),
            'errorCode': 'REFUND_EVIDENCE_REQUIRED',
            'help': ('Refund in Razorpay first, then record it here with `refundId` (and '
                     '`paymentId` if the invoice carries none) once the refund webhook has '
                     'landed.'),
            'invoiceId': invoice_id,
            'remark': remark_entry,
            'paymentStatus': invoice.get('paymentStatus', ''),
        })

    return _resp(200, {
        'invoiceId': invoice_id,
        'remark': remark_entry,
        'totalRemarks': len(existing_remarks),
    })


# ─── Send Invoice on WhatsApp ───

def send_invoice_whatsapp(invoice_id: str, to_phone: str, phone_number_id: str,
                          request_id: str, *, force: bool = False) -> Dict:
    """Send the approved invoice as a PNG image via outbound-whatsapp.

    `force` is KEYWORD-ONLY and defaults to `False`, and that shape is the whole safety property:
    a caller that has never heard of `force` gets the idempotent behaviour, which is every caller
    today including the operator UI. An operator genuinely does sometimes need to resend - the
    customer deleted the chat, the first send failed at Meta - so the escape exists, but it is an
    explicit decision with a WARNING log behind it rather than the default.

    A customer receiving two identical GST invoices for one payment is a compliance artifact, not
    merely untidy, which is why the claim lives HERE rather than at any call site: the webhook,
    the operator button and any future caller all pass through this function.
    """
    if not invoice_id:
        return _resp(400, {'error': 'invoiceId required'})
    if not to_phone:
        return _resp(400, {'error': 'toWhatsAppNumber required'})

    table = dynamodb.Table(INVOICES_TABLE)
    invoice = table.get_item(Key={'invoiceId': invoice_id}, ConsistentRead=True).get('Item')
    if not invoice:
        return _resp(404, {'error': 'Invoice not found'})
    from lambda_utils.comms.numbers import to_e164
    try:
        recipient = to_e164(to_phone)
        saved_recipient = to_e164(str(invoice.get('customerPhone') or ''))
    except (ValueError, TypeError):
        return _resp(400, {'error': 'Valid invoice recipient required'})
    if not saved_recipient or recipient != saved_recipient:
        return _resp(403, {'error': 'Invoice does not belong to this recipient'})
    to_phone = saved_recipient

    # ── the delivery claim, taken BEFORE any render ──
    keys_table = dynamodb.Table(COMMERCE_KEYS_TABLE)
    if not force:
        try:
            claimed = order_keys.claim_invoice_delivery(
                keys_table, invoice_id=invoice_id, channel='whatsapp',
                extra={'requestId': request_id})
        except order_keys.OrderIdentityUnavailable:
            # Fails CLOSED toward NOT sending, and that direction is correct: an undelivered
            # invoice is recoverable by resending, a duplicate GST invoice is not.
            logger.error(json.dumps({
                'event': 'invoice_delivery_claim_unavailable', 'invoiceId': invoice_id,
                'requestId': request_id,
            }))
            return _resp(503, {'error': 'Delivery claim unavailable; nothing was sent'})
        if not claimed:
            logger.info(json.dumps({
                'event': 'invoice_delivery_already_claimed', 'invoiceId': invoice_id,
                'channel': 'whatsapp', 'requestId': request_id,
            }))
            known = order_keys.resolve_invoice_delivery(keys_table, invoice_id)
            confirmed = bool(known and known.get('deliveryStatus') == order_keys.DELIVERY_CONFIRMED)
            return _resp(200 if confirmed else 202, {
                'invoiceId': invoice_id,
                'status': 'already_delivered' if confirmed else 'delivery_pending',
                'deduplicated': True,
                'waMessageId': (known or {}).get('waMessageId', '')})
    else:
        logger.warning(json.dumps({
            'event': 'invoice_delivery_forced', 'invoiceId': invoice_id,
            'channel': 'whatsapp', 'requestId': request_id,
        }))

    def _release_claim(why: str) -> None:
        """Give the slot back when the claim produced no delivery.

        Conditional on `deliveryStatus = CLAIMED` inside `order_keys`, so it can never undo a
        CONFIRMED delivery - which is what stops this being usable to duplicate an invoice. Not
        taken on the `force` path, because no claim was taken there.
        """
        if force:
            return
        try:
            order_keys.release_invoice_delivery(keys_table, invoice_id=invoice_id,
                                                channel='whatsapp')
        except Exception as exc:  # noqa: BLE001
            logger.error(json.dumps({
                'event': 'invoice_delivery_release_failed', 'invoiceId': invoice_id,
                'error': type(exc).__name__, 'requestId': request_id,
            }))
            return
        logger.error(json.dumps({
            'event': 'invoice_delivery_failed_claim_released', 'invoiceId': invoice_id,
            'why': why, 'requestId': request_id,
        }))

    # Owner-approved delivery is PNG for both receipt layouts. PDF remains an optional
    # download generated by the same engine; it is never selected for WhatsApp delivery.
    asset_type = 'image'
    assets_table = dynamodb.Table(INVOICE_ASSETS_TABLE)
    try:
        asset_resp = assets_table.get_item(Key={'invoiceId': invoice_id, 'assetType': asset_type})
        asset = asset_resp.get('Item')
    except Exception:
        asset = None

    if not asset or not asset.get('s3Key'):
        # Generate image first
        # NOTE: an absent asset row is NOT a refusal. The engine renders it here and proceeds -
        # that behaviour is correct and must not be "fixed" into a refusal, because it is what
        # makes a perfectly deliverable invoice deliverable.
        gen_result = generate_invoice_image(invoice_id, request_id)
        gen_body = json.loads(gen_result.get('body', '{}'))
        if gen_result.get('statusCode') != 200:
            _release_claim('render_failed')
            return _resp(500, {'error': 'Failed to generate invoice image', 'detail': gen_body})
        image_url = gen_body.get('imageUrl', '')
        s3_key = gen_body.get('s3Key', '')
    else:
        # A previously rendered asset. `url` is no longer stored, because a presigned one expires
        # and this is the read that would have served the stale copy - so the link is re-signed
        # from the key on every send.
        s3_key = asset.get('s3Key', '')
        image_url = _signed_invoice_url(s3_key, invoice_id, request_id)

    # Guard on `s3_key`, which is what delivery actually needs. It used to guard on `image_url`
    # and then send `mediaFile: s3_key`, so it tested one variable and used another: a row with a
    # URL but no key passed the check and sent a message with no media, and a row with a key but
    # no URL was refused despite being perfectly deliverable.
    if not s3_key:
        _release_claim('no_image_key')
        return _resp(500, {'error': 'No invoice image available'})

    # Fetch invoice for caption
    table = dynamodb.Table(INVOICES_TABLE)
    inv_resp = table.get_item(Key={'invoiceId': invoice_id})
    invoice = inv_resp.get('Item', {})
    # Rendered through integer paise and a display STRING, so the caption figure cannot be
    # arithmetic'd by a later reader. A total that is not exactly expressible in paise falls back
    # to the stored value rather than refusing: this is a caption, not a comparison.
    try:
        total_display = pay_status.rupees_str(wa_payment_request.exact_paise(
            invoice.get('total', 0)))
    except wa_payment_request.PaymentRequestRefused:
        total_display = str(invoice.get('total', 0))
    order_id = invoice.get('orderId', '')
    reference_id = invoice.get('referenceId', '')
    invoice_number = str(invoice.get('invoiceNumber', '') or '')
    order_line = f"\nOrder: {order_id}" if order_id and order_id != 'Offline' else ''
    ref_line = f"\nRef: {reference_id}" if reference_id else ''
    # The caption is the only part of this message a customer can search, forward or read without
    # opening the image, so the invoice number belongs in it as well as on the document. Omitted
    # entirely when absent, like the Order and Ref lines above - a label with nothing after it
    # reads as a bug.
    invoice_line = f"\nInvoice: {invoice_number}" if invoice_number else ''
    # Every line here is an identifier or a label. NO PERSONAL DATA: no phone, no name, no
    # address. A WhatsApp caption is rendered in notification previews and in forwards, so it is
    # the least private surface this engine writes to, and the document inside the image already
    # carries the bill-to details for the one recipient entitled to them.
    source_line = f"\nOrdered on: {_source_label(invoice)}"
    # The public customer id belongs here and the phone does not, and that distinction is the
    # whole rule this caption is written to: the id is OURS, opaque, carries no timestamp and
    # identifies nobody to a stranger reading a notification preview, whereas the phone, the name
    # and the address identify the recipient to whoever is holding the handset. So this line is
    # an identifier joining the ones already here, not an exception to the no-personal-data
    # property. Omitted when absent, like the Invoice, Order and Ref lines above.
    customer_id = _customer_id(invoice)
    customer_id_line = f"\nCustomer ID: {customer_id}" if customer_id else ''
    caption = (f"Invoice \u20b9{total_display}{invoice_line}{order_line}{ref_line}{source_line}"
               f"{customer_id_line}"
               f"\nThank you for your payment!")

    # Look up contact by phone
    contact = _lookup_contact_by_phone(to_phone)
    contact_id = (contact.get('contactId') or contact.get('id', '')) if contact else ''

    # Default phone number ID — one home for the literal, same as the payment path above.
    if not phone_number_id:
        phone_number_id = wa_payment_request.PHONE_NUMBER_ID_1

    # Call outbound-whatsapp Lambda to send image
    wa_payload = {
        'body': json.dumps({
            'contactId': contact_id,
            'recipientPhone': to_phone,
            'content': caption,
            'phoneNumberId': phone_number_id,
            'mediaFile': s3_key,
            'mediaType': 'image',
        })
    }

    try:
        wa_response = lambda_client.invoke(
            FunctionName='wecare-outbound-whatsapp:live',
            InvocationType='RequestResponse',
            Payload=json.dumps(wa_payload),
        )
        wa_result = json.loads(wa_response['Payload'].read())
        wa_body = json.loads(wa_result.get('body', '{}'))
        wa_message_id = wa_body.get('whatsappMessageId', wa_body.get('messageId', ''))
        wa_status = wa_body.get('status', 'unknown')
        if wa_response.get('FunctionError'):
            wa_status = 'unknown'
    except Exception as e:
        logger.error(json.dumps({'event': 'invoice_send_uncertain',
            'invoiceId': invoice_id, 'error': type(e).__name__, 'requestId': request_id}))
        wa_message_id = ''
        wa_status = 'unknown'

    # Log delivery
    delivery_table = dynamodb.Table(INVOICE_DELIVERY_TABLE)
    delivery_table.put_item(Item={
        'invoiceId': invoice_id,
        'timestamp': int(time.time()),
        'channel': 'whatsapp',
        'toNumber': to_phone,
        'waMessageId': wa_message_id,
        'status': wa_status,
        'imageUrl': image_url,
        'phoneNumberId': phone_number_id,
        'contactId': contact_id,
        'error': '' if wa_status != 'failed' else 'WhatsApp send failed',
    })

    # ── the claim becomes EVIDENCE only here ──
    #
    # It was taken before the render as an INTENT. `send_invoice_whatsapp` swallows a Meta
    # failure into `wa_status='failed'` and still returns 200, so a claim never released on
    # failure would consume the only slot and every non-forced caller thereafter would get
    # `already_delivered` - silently losing a GST invoice with nothing above INFO in the logs.
    delivered = bool(wa_message_id and wa_status in ('accepted', 'sent', 'delivered', 'read'))
    if delivered:
        if not force:
            order_keys.confirm_invoice_delivery(
                keys_table, invoice_id=invoice_id, channel='whatsapp',
                wa_message_id=wa_message_id)
    elif wa_status in ('failed', 'rejected'):
        _release_claim('send_failed')

    # Update invoice status
    if delivered:
        table.update_item(
            Key={'invoiceId': invoice_id},
            UpdateExpression='SET receiptStatus = :st, receiptSentAt = :now',
            ExpressionAttributeValues={':st': wa_status, ':now': int(time.time())},
        )

    logger.info(json.dumps({
        'event': 'invoice_whatsapp_sent', 'invoiceId': invoice_id,
        'waMessageId': wa_message_id, 'status': wa_status,
        'toNumber': mask_phone(to_phone), 'requestId': request_id,
    }))

    return _resp(200 if delivered else (502 if wa_status in ('failed', 'rejected') else 202), {
        'invoiceId': invoice_id,
        'waMessageId': wa_message_id,
        'status': wa_status,
        'imageUrl': image_url,
    })


# ─── Delivery Log ───

def get_delivery_log(invoice_id: str, request_id: str) -> Dict:
    """Get delivery log for an invoice."""
    if not invoice_id:
        return _resp(400, {'error': 'invoiceId required'})

    table = dynamodb.Table(INVOICE_DELIVERY_TABLE)
    resp = table.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key('invoiceId').eq(invoice_id)
    )
    logs = resp.get('Items', [])
    logs.sort(key=lambda x: int(x.get('timestamp', 0)), reverse=True)

    return _resp(200, {
        'invoiceId': invoice_id,
        'deliveryLogs': [{
            'timestamp': int(l.get('timestamp', 0)),
            'channel': l.get('channel', ''),
            'toNumber': l.get('toNumber', ''),
            'waMessageId': l.get('waMessageId', ''),
            'status': l.get('status', ''),
            'error': l.get('error', ''),
            'imageUrl': l.get('imageUrl', ''),
        } for l in logs],
        'count': len(logs),
    })


# ─── Helper Functions ───

def _lookup_contact_by_phone(phone: str) -> Optional[Dict]:
    """Look up a contact by phone number."""
    if not phone:
        return None
    try:
        table = dynamodb.Table(CONTACTS_TABLE)
        # Normalize phone
        clean = phone.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
        if not clean.startswith('+'):
            clean = '+' + clean

        # Fast path: exact-match via the phone-index GSI (avoids a table scan).
        try:
            from boto3.dynamodb.conditions import Key
            q = table.query(IndexName='phone-index', KeyConditionExpression=Key('phone').eq(clean))
            if q.get('Items'):
                return q['Items'][0]
        except Exception as e:
            logger.debug(f"phone-index query failed, falling back to scan: {e}")

        # Fallback: paginated fuzzy scan (last-10-digit contains) for numbers
        # not stored in normalized E.164 form.
        scan_kwargs = {'FilterExpression': boto3.dynamodb.conditions.Attr('phone').contains(clean[-10:])}
        items = []
        while True:
            result = table.scan(**scan_kwargs)
            items = result.get('Items', [])
            if items or 'LastEvaluatedKey' not in result:
                break
            scan_kwargs['ExclusiveStartKey'] = result['LastEvaluatedKey']
        return items[0] if items else None
    except Exception as e:
        logger.warning(f"Contact lookup error: {e}")
        return None


def _normalize_invoice(item: Dict) -> Dict:
    """Normalize invoice record for API response."""
    return {
        'invoiceId': item.get('invoiceId', ''),
        'invoiceNumber': item.get('invoiceNumber', ''),
        'paymentId': item.get('paymentId', ''),
        'orderId': item.get('orderId', ''),
        'referenceId': item.get('referenceId', ''),
        'entryPoint': item.get('entryPoint', ''),
        'status': item.get('status', ''),
        'paymentStatus': item.get('paymentStatus', ''),
        'contactId': item.get('contactId', ''),
        'customerName': item.get('customerName', ''),
        'customerPhone': item.get('customerPhone', ''),
        'paidByPhone': item.get('paidByPhone', ''),
        'customerEmail': item.get('customerEmail', ''),
        'shippingAddress': item.get('shippingAddress', ''),
        'billingAddress': item.get('billingAddress', ''),
        'goodsType': item.get('goodsType', 'digital-goods'),
        'subtotal': float(item.get('subtotal', 0)),
        'discount': float(item.get('discount', 0)),
        'couponCode': item.get('couponCode', ''),
        'couponDiscount': float(item.get('couponDiscount', 0)),
        'shipping': float(item.get('shipping', 0)),
        'handling': float(item.get('handling', 0)),
        'gstRate': float(item.get('gstRate', 0)),
        'tax': float(item.get('tax', 0)),
        'convenienceFee': float(item.get('convenienceFee', 0)),
        'total': float(item.get('total', 0)),
        'currency': item.get('currency', 'INR'),
        'gstin': item.get('gstin', ''),
        'purpose': item.get('purpose', ''),
        'notes': item.get('notes', ''),
        'createdAt': int(item.get('createdAt', 0)),
        'updatedAt': int(item.get('updatedAt', 0)),
        'paidAt': int(item.get('paidAt', 0)),
    }


def _normalize_item(item: Dict) -> Dict:
    """Normalize invoice item for API response."""
    return {
        'invoiceId': item.get('invoiceId', ''),
        'itemIndex': int(item.get('itemIndex', 0)),
        'name': item.get('name', ''),
        'amount': float(item.get('amount', 0)),
        'quantity': int(item.get('quantity', 1)),
        'productId': item.get('productId', ''),
    }


def _normalize_asset(item: Dict) -> Dict:
    """Normalize invoice asset for API response.

    `url` is minted from `s3Key` rather than read from the row. Two reasons, and the first is
    why this function had to change at all: the row no longer carries a `url`, so reading one
    would return `''` for every asset — an API that silently answers "no link" rather than
    erroring. And a stored presigned URL would be worse than absent, since it is correct when
    written and quietly expired afterwards.

    Presigning is a local signature computation, not an S3 call, so doing it per row in a list
    response costs nothing on the wire.
    """
    s3_key = item.get('s3Key', '')
    invoice_id = item.get('invoiceId', '')
    return {
        'invoiceId': invoice_id,
        'assetType': item.get('assetType', ''),
        's3Key': s3_key,
        # Falls back to a legacy stored value only if signing yields nothing, so rows written
        # before the gated move still render. Those legacy URLs point at the public root and
        # will 404 there now, which is the correct failure: a dead link, not a disclosure.
        'url': _signed_invoice_url(s3_key, invoice_id, 'normalize') or item.get('url', ''),
        'contentType': item.get('contentType', ''),
        'version': int(item.get('version', 0)),
        'generatedAt': int(item.get('generatedAt', 0)),
    }


def _dec(value) -> Decimal:
    """Convert to Decimal for DynamoDB storage."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(round(float(value), 2)))


def _resp(status_code: int, body: Dict) -> Dict[str, Any]:
    """Return HTTP response with CORS headers."""
    return {
        'statusCode': status_code,
        'headers': cors_headers(origin),
        'body': json.dumps(body, default=str),
    }
