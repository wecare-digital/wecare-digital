"""
System Cleanup Lambda Handler
Previews and clears a NARROW allow-list of cache/analytics tables.
GET previews item counts and mints a confirmation token; POST deletes the resources named
in `selected`, which must match that token's selection exactly.

What actually gates the delete, stated precisely
------------------------------------------------
Four things, all of which have to hold:

1. `require_auth(event, required_role='Admin')` - an Admin on a STAFF-pool token. The
   docstring here used to claim "the caller must be an authenticated admin" while the
   code passed no `required_role` at all, so **any** authenticated caller qualified, and
   before the staff-pool pin in `lambda_utils.middleware` that included a customer-pool
   token.
2. For POST, an enrolled second factor: `event['_auth']['mfaEnrolled'] is True`. Read off
   the auth result rather than off `ADMIN_MFA_REQUIRED`, which is NOT set on
   `wecare-system-cleanup` - so relying on the env var would have been a check that does
   nothing on the one function that needs it most.
3. A server-side confirmation token from `GET`, bound to the exact selection and
   single-use. The word "confirm" used to refer to a dialog in the admin UI, which is a
   client-side courtesy; a direct POST skipped it entirely. It is now a server fact.
4. An explicit `selected` list, every entry of which is on `CLEANUP_ALLOWLIST`. Nothing
   is deleted by default, there is no "all" shorthand, and an empty list deletes nothing.

And one thing that has to be recorded: a durable audit row, written BEFORE the first
delete, and failing CLOSED. `lambda_utils.audit.record_audit` fails open by design; for
an irreversible bulk delete that trade is wrong, so this handler checks the return value
and refuses 503 on `None`. `AuditLogsTable` is in `PROTECTED_TABLES` and matches the
keyword deny list, because an audit trail inside the deletable set is not an audit trail.

What is NO LONGER selectable, and why
-------------------------------------
Auto-discovery is gone. `_discover_tables()` merged every `stack-wecare-digital-*` table
not in a four-entry `PROTECTED_TABLES` into the registry, and `_discover_s3_prefixes()`
did the same for every folder three levels under `o/stack/`. So ContactsTable,
InvoicesTable, PaymentsTable, AuditLogsTable and every future table were selectable, and
a new table became selectable merely by existing. The curated registry was a hole too -
it named contacts, invoices, invoice_items, payments, razorpay_webhook_log, wix_order_ids
and audit_logs outright.

The registry below is kept for DISPLAY, so an operator can still see what exists and how
much is in it, but every entry is now marked `selectable` or `protected` with a reason,
and only `CLEANUP_ALLOWLIST` is selectable. **All S3 prefixes and all SQS queues are
refused**: S3 under `o/stack/` and `secure/stack/` holds customer media, invoice
renditions and product images, and purging a DLQ or the bulk queue discards undelivered
customer work. Neither is a cache. Extending the allow-list is an owner decision, taken
one table at a time with a recorded reason.

No EventBridge rule targets this function, so nothing here runs on a schedule. The
similarly named `wecare-media-cleanup` IS scheduled daily, but it only expires
DynamoDB rows and never touches S3.

**The S3 prefixes below deleted nothing until 2026-09-28.** They all pointed at `stack/`
at the bucket root, which holds zero objects, so every sweep reported success having
removed nothing. Rooting them under `o/` made this path reach real data for the first
time - see lambda_utils/media_paths. Treat changes here as destructive, because now they
are.
"""

import os
import json
import secrets
import time
import logging
import boto3
from typing import Dict, Any, List, Optional
from botocore.exceptions import ClientError

from lambda_utils.response import cors_response, cors_headers, options_response, extract_origin

from lambda_utils.audit import record_audit
from lambda_utils.logging import get_logger
from lambda_utils import media_paths  # one bucket, two roots: o/ public, secure/ gated

logger = get_logger(__name__)

REGION = os.environ.get('AWS_REGION', 'us-east-1')
BUCKET = os.environ.get('MEDIA_BUCKET', media_paths.BUCKET)
#: Where the single-use confirmation token lives. Already in PROTECTED_TABLES, already
#: spoken to by a dozen handlers, and - unlike an HMAC over an env secret - it survives a
#: cold start and needs no env change to deploy.
SYSTEM_CONFIG_TABLE = os.environ.get('SYSTEM_CONFIG_TABLE', 'stack-wecare-digital-SystemConfigTable')
#: How long a preview's token stays usable. Long enough to read the counts and decide,
#: short enough that a token left in a tab is not a standing authorisation.
CONFIRM_TOKEN_TTL_SECONDS = 15 * 60

dynamodb = boto3.resource('dynamodb', region_name=REGION)
dynamodb_client = boto3.client('dynamodb', region_name=REGION)
s3 = boto3.client('s3', region_name=REGION)
sqs = boto3.client('sqs', region_name=REGION)

# CORS headers provided by lambda_utils.response.cors_headers(origin)

# All clearable resources grouped by category
CLEANUP_RESOURCES = {
    'whatsapp_inbox': {
        'label': 'WhatsApp Inbox (Inbound)',
        'category': 'Messages',
        'type': 'dynamodb',
        'table': 'stack-wecare-digital-WhatsAppInboundTable',
    },
    'whatsapp_outbox': {
        'label': 'WhatsApp Outbox (Outbound)',
        'category': 'Messages',
        'type': 'dynamodb',
        'table': 'stack-wecare-digital-WhatsAppOutboundTable',
    },
    'contacts': {
        'label': 'Contacts',
        'category': 'Contacts',
        'type': 'dynamodb',
        'table': 'stack-wecare-digital-ContactsTable',
    },
    'media_files': {
        'label': 'Media Files (DB records)',
        'category': 'Media',
        'type': 'dynamodb',
        'table': 'stack-wecare-digital-MediaFilesTable',
    },
    'conversation_history': {
        'label': 'AI Conversation History',
        'category': 'AI',
        'type': 'dynamodb',
        'table': 'stack-wecare-digital-ConversationHistoryTable',
    },
    'ai_interactions': {
        'label': 'AI Interactions Log',
        'category': 'AI',
        'type': 'dynamodb',
        'table': 'stack-wecare-digital-AIInteractionsTable',
    },
    'whatsapp_calling': {
        'label': 'WhatsApp Call Logs',
        'category': 'Voice',
        'type': 'dynamodb',
        'table': 'stack-wecare-digital-WhatsAppCallingTable',
    },
    'voice_cdr': {
        'label': 'Voice CDR Records',
        'category': 'Voice',
        'type': 'dynamodb',
        'table': 'stack-wecare-digital-VoiceCDRTable',
    },
    'voice_calls': {
        'label': 'Voice Calls (Airtel)',
        'category': 'Voice',
        'type': 'dynamodb',
        'table': 'stack-wecare-digital-VoiceCalls',
    },
    'voice_aws': {
        'label': 'Voice AWS (Pinpoint)',
        'category': 'Voice',
        'type': 'dynamodb',
        'table': 'stack-wecare-digital-VoiceAwsTable',
    },
    # sms_aws removed 2026-09-24, for the same reason airtel_sms / airtel_c2c were
    # removed below: it named `stack-wecare-digital-SmsAwsTable`, which is not in
    # the account. SMS rows now live in the canonical MessagesTable under
    # channel='sms', which the `messages_legacy` entry already covers, so nothing
    # became uncleanable - an entry that raises ResourceNotFound on every run just
    # stopped doing that.
    # airtel_sms / airtel_c2c removed 2026-09-20: both tables were deleted from
    # the account with the Airtel retirement. A registry entry for a table that
    # no longer exists makes every cleanup run raise ResourceNotFound.
    'invoices': {
        'label': 'Invoices',
        'category': 'Invoices & Payments',
        'type': 'dynamodb',
        'table': 'stack-wecare-digital-InvoicesTable',
    },
    'invoice_items': {
        'label': 'Invoice Line Items',
        'category': 'Invoices & Payments',
        'type': 'dynamodb',
        'table': 'stack-wecare-digital-InvoiceItemsTable',
    },
    'invoice_assets': {
        'label': 'Invoice Assets (PDFs)',
        'category': 'Invoices & Payments',
        'type': 'dynamodb',
        'table': 'stack-wecare-digital-InvoiceAssetsTable',
    },
    'invoice_delivery_log': {
        'label': 'Invoice Delivery Log',
        'category': 'Invoices & Payments',
        'type': 'dynamodb',
        'table': 'stack-wecare-digital-InvoiceDeliveryLogTable',
    },
    'invoice_sequence': {
        'label': 'Invoice Sequence Counter',
        'category': 'Invoices & Payments',
        'type': 'dynamodb',
        'table': 'stack-wecare-digital-InvoiceSequenceTable',
    },
    'payments': {
        'label': 'Payments',
        'category': 'Invoices & Payments',
        'type': 'dynamodb',
        'table': 'stack-wecare-digital-PaymentsTable',
    },
    'razorpay_webhook_log': {
        'label': 'Razorpay Webhook Log',
        'category': 'Invoices & Payments',
        'type': 'dynamodb',
        'table': 'stack-wecare-digital-RazorpayWebhookLogTable',
    },
    'scheduled_messages': {
        'label': 'Scheduled Messages',
        'category': 'Messages',
        'type': 'dynamodb',
        'table': 'stack-wecare-digital-ScheduledMessagesTable',
    },
    'bulk_jobs': {
        'label': 'Bulk Jobs',
        'category': 'Bulk',
        'type': 'dynamodb',
        'table': 'stack-wecare-digital-BulkJobsTable',
    },
    'bulk_recipients': {
        'label': 'Bulk Recipients',
        'category': 'Bulk',
        'type': 'dynamodb',
        'table': 'stack-wecare-digital-BulkRecipientsTable',
    },
    'whatsapp_voice_log': {
        'label': 'WhatsApp Voice (TTS) Log',
        'category': 'Voice',
        'type': 'dynamodb',
        'table': 'stack-wecare-digital-WhatsAppVoiceTable',
    },
    'obd_campaigns': {
        'label': 'OBD Campaigns',
        'category': 'Voice',
        'type': 'dynamodb',
        'table': 'stack-wecare-digital-OBDCampaigns',
    },
    's3_invoices': {
        'label': 'S3: Invoice Files',
        'category': 'S3 Storage',
        # `secure`, matching where invoice-engine and inbound-whatsapp-handler now write. A
        # rendered invoice carries customer PII, so it moved off the unauthenticated `o/` root.
        # This entry has to move with it or cleanup silently sweeps an empty prefix and the real
        # objects accumulate forever — a counter reading zero looks like success.
        'type': 's3',
        'prefix': media_paths.secure('stack/invoices/'),
    },
    's3_whatsapp_media': {
        'label': 'S3: WhatsApp Media',
        'category': 'S3 Storage',
        'type': 's3',
        'prefix': media_paths.public('stack/whatsapp-media/'),
    },
    's3_voice_recordings': {
        'label': 'S3: Voice Recordings',
        'category': 'S3 Storage',
        'type': 's3',
        'prefix': media_paths.public('stack/voice/'),
    },
    's3_whatsapp_voice': {
        'label': 'S3: WhatsApp Voice (TTS)',
        'category': 'S3 Storage',
        'type': 's3',
        'prefix': media_paths.public('stack/whatsapp-media/voice/'),
    },
    # --- Additional resources (full factory reset coverage) ---
    'dlq_messages': {
        'label': 'DLQ Messages (Failed Retry Queue)',
        'category': 'Messages',
        'type': 'dynamodb',
        'table': 'stack-wecare-digital-DLQMessagesTable',
    },
    'messages_legacy': {
        'label': 'Messages (Legacy Table)',
        'category': 'Messages',
        'type': 'dynamodb',
        'table': 'stack-wecare-digital-MessagesTable',
    },
    'dlt_templates': {
        'label': 'DLT Templates (Airtel SMS)',
        'category': 'SMS',
        'type': 'dynamodb',
        'table': 'stack-wecare-digital-DLTTemplates',
    },
    'wix_products_cache': {
        'label': 'Wix Products Cache',
        'category': 'Ecommerce',
        'type': 'dynamodb',
        'table': 'stack-wecare-digital-WixProductsCache',
    },
    'wix_orders_cache': {
        'label': 'Wix Orders Cache',
        'category': 'Ecommerce',
        'type': 'dynamodb',
        'table': 'stack-wecare-digital-WixOrdersCache',
    },
    'wix_order_ids': {
        'label': 'Wix Order ID Mapping',
        'category': 'Ecommerce',
        'type': 'dynamodb',
        'table': 'stack-wecare-digital-WixOrderIds',
    },
    'template_analytics': {
        'label': 'Template Analytics',
        'category': 'Analytics & Logs',
        'type': 'dynamodb',
        'table': 'stack-wecare-digital-TemplateAnalyticsTable',
    },
    'submit_requests': {
        'label': 'Flow Submit Requests',
        'category': 'Analytics & Logs',
        'type': 'dynamodb',
        'table': 'stack-wecare-digital-SubmitRequestsTable',
    },
    'audit_logs': {
        'label': 'Audit Logs',
        'category': 'Analytics & Logs',
        'type': 'dynamodb',
        'table': 'stack-wecare-digital-AuditLogsTable',
    },
    'rate_limit': {
        'label': 'Rate Limit Trackers',
        'category': 'System',
        'type': 'dynamodb',
        'table': 'stack-wecare-digital-RateLimitTable',
    },
    # sms_in_airtel / payu_webhook_log removed 2026-09-20 with their tables.
    's3_whatsapp_media_incoming': {
        'label': 'S3: WhatsApp Media (Incoming)',
        'category': 'S3 Storage',
        'type': 's3',
        'prefix': media_paths.public('stack/whatsapp-media/incoming/'),
    },
    's3_whatsapp_media_outgoing': {
        'label': 'S3: WhatsApp Media (Outgoing)',
        'category': 'S3 Storage',
        'type': 's3',
        'prefix': media_paths.public('stack/whatsapp-media/outgoing/'),
    },
    's3_template_headers': {
        'label': 'S3: Template Headers',
        'category': 'S3 Storage',
        'type': 's3',
        'prefix': media_paths.public('stack/whatsapp-media/template-headers/'),
    },
    's3_product_images': {
        'label': 'S3: Product Images',
        'category': 'S3 Storage',
        'type': 's3',
        'prefix': media_paths.public('stack/store/products/'),
    },
    's3_reports': {
        'label': 'S3: Reports & Exports',
        'category': 'S3 Storage',
        'type': 's3',
        'prefix': media_paths.public('stack/reports/'),
    },
    's3_whatsapp_calling_ai': {
        'label': 'S3: WhatsApp Calling AI Audio',
        'category': 'S3 Storage',
        'type': 's3',
        'prefix': media_paths.public('stack/whatsapp-media/calling-ai/'),
    },
    's3_whatsapp_downloads': {
        'label': 'S3: WhatsApp Media Downloads',
        'category': 'S3 Storage',
        'type': 's3',
        'prefix': media_paths.public('stack/whatsapp-media/downloads/'),
    },
    # SQS Queues
    'sqs_inbound_dlq': {
        'label': 'SQS: Inbound DLQ',
        'category': 'SQS Queues',
        'type': 'sqs',
        'queue': 'stack-wecare-digital-inbound-dlq',
    },
    'sqs_bulk_dlq': {
        'label': 'SQS: Bulk DLQ',
        'category': 'SQS Queues',
        'type': 'sqs',
        'queue': 'stack-wecare-digital-bulk-dlq',
    },
    'sqs_bulk_queue': {
        'label': 'SQS: Bulk Queue',
        'category': 'SQS Queues',
        'type': 'sqs',
        'queue': 'stack-wecare-digital-bulk-queue',
    },
    'sqs_outbound_dlq': {
        'label': 'SQS: Outbound DLQ',
        'category': 'SQS Queues',
        'type': 'sqs',
        'queue': 'stack-wecare-digital-outbound-dlq',
    },
}

# The stack's table-name prefix. All that is left of the "dynamic discovery config" block:
# `S3_ROOT_PREFIX` and `S3_MAX_DEPTH` went with `_discover_s3_prefixes`, and
# `_discover_tables` went with them, because a registry that grows by itself is a
# destructive surface that grows by itself.
TABLE_PREFIX = 'stack-wecare-digital-'

# Tables that must NEVER be wiped by factory reset (config + durable assets).
# Short links are permanent by design — they are printed on materials, embedded in
# messages, and shared externally, so a factory reset must NEVER break them. They can
# only be removed manually via the URL-shortener DELETE.
#
# The same reasoning applies to the HOSTS they were issued under, not just the rows.
# New links are minted under wecare.digital/r since 2026-09-26, but r.wecare.digital
# keeps resolving every code ever issued, for exactly the reason stated above: a link
# printed on a physical card cannot be edited or recalled. Retiring that host would
# break links this comment already promises never to break.
PROTECTED_TABLES = {
    'stack-wecare-digital-SystemConfigTable',
    'stack-wecare-digital-SystemConfig',
    'stack-wecare-digital-ShortLinksTable',   # short links — manual-delete only
    'stack-wecare-digital-LinkClicksTable',   # short-link click analytics
    # The audit sink. It was the `audit_logs` registry entry below, i.e. this handler
    # could delete the record of its own deletions. An audit trail inside the deletable
    # set is not an audit trail.
    'stack-wecare-digital-AuditLogsTable',
}

# ── The allow-list. Nothing outside this is deletable, by anybody, ever. ──
#
# Four tables, each one a cache or a derived aggregate that rebuilds itself. The test for
# membership is not "is this low value" but "if this were empty in five minutes, would the
# system repopulate it without anyone intervening".
#
# This deliberately removes most of what "Factory Reset" used to do. That is the point:
# the previous registry named contacts, invoices, payments and audit_logs, and
# auto-discovery added every table that merely existed. Extending this is an owner
# decision, taken one table at a time, with the reason recorded in this comment block.
CLEANUP_ALLOWLIST = {
    # ephemeral throttle counters, rebuilt inside one rate-limit window
    'stack-wecare-digital-RateLimitTable',
    # derived analytics; re-fetchable from Meta's template insights API
    'stack-wecare-digital-TemplateAnalyticsTable',
    # pure cache, rebuilt by the catalogue sync
    'stack-wecare-digital-WixProductsCache',
    # Airtel SMS DLT template cache; Airtel is retired
    'stack-wecare-digital-DLTTemplates',
}

#: Empty on purpose, and the reason is in `_protected_reason`: S3 under `o/stack/` and
#: `secure/stack/` holds customer media, invoice renditions and product images. None of it
#: is a cache. Kept as a set so a future narrowing is one line of data with a reason next
#: to it, in the same shape as CLEANUP_ALLOWLIST.
S3_PREFIX_ALLOWLIST: set = set()
#: Empty on purpose. Purging a DLQ or the bulk queue discards undelivered customer work.
SQS_QUEUE_ALLOWLIST: set = set()

# ── The independent second layer. ──
#
# Two layers because the registry and this guard fail differently: the allow-list protects
# against auto-discovery and a mis-typed id, and this keyword predicate protects against a
# future careless allow-list edit. A name that matches any of these can never be selected,
# even by an MFA'd Admin, even if someone adds it to CLEANUP_ALLOWLIST.
#
# `wixorder` is here because AUDIT-REPORT.md records `stack-wecare-digital-WixOrderIds`'
# `PAYREF#` / `PAYMENTATTEMPT#` / `INVOICECOLLECT#` rows as the canonical payment
# idempotency anchors — losing them makes a replayed webhook charge twice.
PROTECTED_NAME_KEYWORDS = (
    'contact', 'customer', 'order', 'wixorder', 'invoice', 'payment', 'paymentattempt',
    'servicerequest', 'document', 'securefile', 'downloadgrant', 'entitlement',
    'flowsubmission', 'submitrequest', 'message', 'inbound', 'outbound', 'audit',
    'conversation',
)


class CleanupRefused(Exception):
    """A destination the guard will not touch.

    Raised rather than returning 0, because "deleted 0 rows" and "refused to look" are
    different outcomes and a caller that cannot tell them apart will read a refusal as a
    finished sweep.
    """


def _matched_keyword(name: str) -> Optional[str]:
    """The first protected keyword `name` contains, or None. Case- and separator-blind."""
    flat = ''.join(ch for ch in (name or '').lower() if ch.isalnum())
    for keyword in PROTECTED_NAME_KEYWORDS:
        if keyword in flat:
            return keyword
    return None


def _table_protected_reason(table_name: str) -> Optional[str]:
    """Why `table_name` may not be wiped, or None if it may be. The single authority."""
    if table_name in PROTECTED_TABLES:
        return 'Protected: configuration, durable assets or the audit trail'
    keyword = _matched_keyword(table_name)
    if keyword:
        return f'Protected: customer, financial or message history (matched "{keyword}")'
    if table_name not in CLEANUP_ALLOWLIST:
        return 'Not on the cleanup allow-list'
    return None


def _protected_reason(res: Dict[str, Any]) -> Optional[str]:
    """Why this resource may not be selected, or None if it may be."""
    if res.get('type') == 'dynamodb':
        return _table_protected_reason(res.get('table', ''))
    if res.get('type') == 's3':
        return ('S3 is never cleared here: these prefixes hold customer media, invoice '
                'renditions and product images, none of which rebuild themselves')
    if res.get('type') == 'sqs':
        return ('SQS is never purged here: a DLQ or the bulk queue holds undelivered '
                'customer work, not cache')
    return 'Unknown resource type'


def _build_resources() -> Dict[str, Dict[str, Any]]:
    """
    Build the id -> resource map from the CURATED registry only, each entry marked
    `selectable` / `protected` / `protectedReason`.

    Auto-discovery is deliberately absent — see the module docstring. A new
    `stack-wecare-digital-*` table therefore does NOT become deletable by appearing in
    `list_tables`; it has to be added to CLEANUP_ALLOWLIST on purpose.

    Used by both preview (counts) and cleanup (delete) so ids always resolve consistently.
    """
    resources: Dict[str, Dict[str, Any]] = {}
    for key, value in CLEANUP_RESOURCES.items():
        entry = dict(value)
        reason = _protected_reason(entry)
        entry['protected'] = reason is not None
        entry['selectable'] = reason is None
        entry['protectedReason'] = reason or ''
        resources[key] = entry
    return resources


# Module-level origin for CORS (set per-invocation in handler)
origin = ''


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """System cleanup handler — preview counts or delete selected resources."""
    global origin
    origin = extract_origin(event)
    # Support both API Gateway v1 (REST) and v2 (HTTP) event formats
    rc = event.get('requestContext', {})
    method = rc.get('http', {}).get('method', event.get('httpMethod', 'GET')).upper()

    if method == 'OPTIONS':
        return options_response(origin)

    from lambda_utils.middleware import require_auth
    # Admin, and only from a STAFF-pool token. Passing `required_role` is also what makes
    # `require_auth` populate `_auth['mfaEnrolled']` - it only runs the enrolment lookup
    # when Admin is actually required.
    _auth = require_auth(event, required_role='Admin')
    if _auth is not None:
        return _auth

    if method == 'GET':
        return _preview(event)
    elif method == 'POST':
        # Fails CLOSED on an unknown answer: `mfaEnrolled` is True / False / None, and
        # None means the Cognito lookup could not answer. Read off the auth result rather
        # than off `ADMIN_MFA_REQUIRED`, which is not set on this function - deferring to
        # the env var would be a second factor that is not required on the one route that
        # can empty a table.
        if (event.get('_auth') or {}).get('mfaEnrolled') is not True:
            logger.warning(json.dumps({'event': 'cleanup_refused_no_mfa'}))
            return cors_response(403, {
                'error': 'MFA required',
                'detail': ('Deleting data requires a second factor. Enrol an '
                           'authenticator app in your account settings, sign in again, '
                           'and retry.'),
            }, origin)
        return _cleanup(event)
    else:
        return {'statusCode': 405, 'headers': cors_headers(origin), 'body': json.dumps({'error': 'Method not allowed'})}


# ─── Confirmation token (single-use, bound to one exact selection) ──────────
#
# D4: a row in SystemConfigTable rather than an HMAC over an env secret. No env change is
# needed to deploy it, and a per-container secret would not survive a cold start. Single
# use gives idempotency for free - a replayed POST finds no row and is refused, so a retry
# cannot double-delete.


def _actor(event: Dict[str, Any]) -> str:
    """The Cognito `sub` of the caller, falling back to the username. Never a body field."""
    auth = event.get('_auth') or {}
    return str((auth.get('attributes') or {}).get('sub') or auth.get('username') or 'unknown')


def _mint_confirmation(selectable_ids: List[str], counts: Dict[str, int],
                       actor: str) -> Optional[str]:
    """Store a token bound to this exact selection. None if the row could not be written.

    Returning None rather than raising, because a preview is still worth showing: the
    operator sees the counts, and POST then refuses for want of a token. The failure
    direction is "cannot delete", not "delete unconfirmed".
    """
    token = secrets.token_urlsafe(24)
    try:
        dynamodb.Table(SYSTEM_CONFIG_TABLE).put_item(Item={
            'id': f'cleanup_confirm_{token}',
            'selection': sorted(selectable_ids),
            'counts': {k: int(v) for k, v in counts.items()},
            'actor': actor,
            'createdAt': int(time.time()),
            'expiresAt': int(time.time()) + CONFIRM_TOKEN_TTL_SECONDS,
        })
        return token
    except Exception as e:  # noqa: BLE001
        logger.warning(json.dumps({'event': 'cleanup_token_write_failed', 'error': str(e)[:160]}))
        return None


def _consume_confirmation(token: str, selection: List[str]) -> Dict[str, Any]:
    """Read, verify and DELETE the token row. `{'ok': True, ...}` or `{'error': ..., 'status': ...}`.

    The row is consumed before anything is deleted, so two concurrent POSTs cannot both
    proceed: the second one's conditional delete fails and it is refused.
    """
    key = {'id': f'cleanup_confirm_{token}'}
    table = dynamodb.Table(SYSTEM_CONFIG_TABLE)
    try:
        row = table.get_item(Key=key).get('Item')
    except Exception as e:  # noqa: BLE001
        logger.error(json.dumps({'event': 'cleanup_token_read_failed', 'error': str(e)[:160]}))
        return {'error': 'Confirmation store unavailable', 'status': 503}

    if not row:
        # Covers both "never existed" and "already used" - deliberately one message, so a
        # caller probing tokens learns nothing from the difference.
        return {'error': 'Confirmation token is invalid or already used', 'status': 409}

    if int(row.get('expiresAt') or 0) < int(time.time()):
        return {'error': 'Confirmation token has expired — preview again', 'status': 409}

    # Exact match, order-insensitive. One extra id is a different request.
    if sorted(str(s) for s in (row.get('selection') or [])) != sorted(selection):
        logger.warning(json.dumps({'event': 'cleanup_selection_mismatch'}))
        return {'error': 'Selection does not match the confirmed preview', 'status': 409}

    try:
        table.delete_item(Key=key, ConditionExpression='attribute_exists(id)')
    except Exception as e:  # noqa: BLE001
        logger.warning(json.dumps({'event': 'cleanup_token_consume_failed', 'error': str(e)[:160]}))
        return {'error': 'Confirmation token is invalid or already used', 'status': 409}

    return {'ok': True, 'counts': {k: int(v) for k, v in (row.get('counts') or {}).items()}}



def _get_table_count(table_name: str) -> int:
    """Get actual item count for a DynamoDB table via scan."""
    try:
        table = dynamodb.Table(table_name)
        count = 0
        scan_kwargs = {'Select': 'COUNT'}
        while True:
            resp = table.scan(**scan_kwargs)
            count += resp.get('Count', 0)
            if 'LastEvaluatedKey' not in resp:
                break
            scan_kwargs['ExclusiveStartKey'] = resp['LastEvaluatedKey']
        return count
    except Exception as e:
        logger.warning(f'{{"event":"table_count_error","table":"{table_name}","error":"{e}"}}')
        return -1


def _get_s3_count(prefix: str) -> int:
    """Get content file count under an S3 prefix (excludes folder markers)."""
    try:
        count = 0
        paginator = s3.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix):
            for obj in page.get('Contents', []):
                if not obj['Key'].endswith('/'):
                    count += 1
        return count
    except Exception as e:
        logger.warning(f'{{"event":"s3_count_error","prefix":"{prefix}","error":"{e}"}}')
        return -1


def _get_sqs_count(queue_name: str) -> int:
    """Get approximate message count in an SQS queue."""
    try:
        url = sqs.get_queue_url(QueueName=queue_name)['QueueUrl']
        attrs = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=['ApproximateNumberOfMessages', 'ApproximateNumberOfMessagesNotVisible'])
        return int(attrs['Attributes'].get('ApproximateNumberOfMessages', 0)) + int(attrs['Attributes'].get('ApproximateNumberOfMessagesNotVisible', 0))
    except Exception as e:
        logger.warning(f'{{"event":"sqs_count_error","queue":"{queue_name}","error":"{e}"}}')
        return -1


def _preview(event: Dict[str, Any]) -> Dict[str, Any]:
    """Live counts for every registry resource, each marked selectable or protected.

    Protected rows are still listed WITH their counts. Hiding them would answer "what is
    in this system" with a lie, and the operator needs to see that ContactsTable has rows
    and that those rows are not reachable from here.

    Also mints the confirmation token POST requires, bound to the selectable ids and their
    counts at this moment.
    """
    resources = []
    selectable_ids: List[str] = []
    counts: Dict[str, int] = {}

    for key, res in _build_resources().items():
        entry = {
            'id': key,
            'label': res['label'],
            'category': res['category'],
            'type': res['type'],
            'selectable': bool(res.get('selectable')),
            'protected': bool(res.get('protected')),
            'protectedReason': res.get('protectedReason', ''),
        }
        if res['type'] == 'dynamodb':
            entry['table'] = res['table']
            entry['count'] = _get_table_count(res['table'])
        elif res['type'] == 's3':
            entry['prefix'] = res['prefix']
            entry['count'] = _get_s3_count(res['prefix'])
        elif res['type'] == 'sqs':
            entry['queue'] = res['queue']
            entry['count'] = _get_sqs_count(res['queue'])
        resources.append(entry)
        if entry['selectable']:
            selectable_ids.append(key)
            counts[key] = int(entry.get('count') or 0)

    token = _mint_confirmation(selectable_ids, counts, _actor(event))
    body: Dict[str, Any] = {
        'resources': resources,
        'selectableIds': selectable_ids,
        'confirmationToken': token or '',
    }
    if token is None:
        body['warning'] = ('Confirmation store unavailable — counts are live but nothing '
                           'can be deleted until it recovers.')

    return {
        'statusCode': 200,
        'headers': cors_headers(origin),
        'body': json.dumps(body),
    }


def _wipe_table(table_name: str) -> int:
    """Delete all items from an allow-listed DynamoDB table.

    The guard is re-asked here, not only in the registry, and it is the single authority
    `_table_protected_reason`. The previous version checked only the four-entry
    `PROTECTED_TABLES` and returned 0, which read as "nothing to delete".
    """
    reason = _table_protected_reason(table_name)
    if reason:
        logger.warning(json.dumps({
            'event': 'wipe_blocked_protected', 'table': table_name, 'reason': reason,
        }))
        raise CleanupRefused(reason)
    try:
        key_schema = dynamodb_client.describe_table(TableName=table_name)['Table']['KeySchema']
    except Exception as e:
        logger.warning(f"Cannot describe {table_name}: {e}")
        return 0

    key_names = [k['AttributeName'] for k in key_schema]
    table = dynamodb.Table(table_name)
    deleted = 0

    proj_aliases = {f'#k{i}': name for i, name in enumerate(key_names)}
    scan_kwargs = {
        'ProjectionExpression': ', '.join(proj_aliases.keys()),
        'ExpressionAttributeNames': proj_aliases,
    }

    while True:
        resp = table.scan(**scan_kwargs)
        items = resp.get('Items', [])
        if not items:
            break
        with table.batch_writer() as batch:
            for item in items:
                key = {k: item[k] for k in key_names}
                batch.delete_item(Key=key)
                deleted += 1
        if 'LastEvaluatedKey' not in resp:
            break
        scan_kwargs['ExclusiveStartKey'] = resp['LastEvaluatedKey']

    return deleted


def _wipe_s3_prefix(prefix: str) -> int:
    """Delete content files under an allow-listed S3 prefix. The allow-list is EMPTY.

    Folder markers (0-byte keys ending with /) are preserved by the filter below, which
    `scripts/create_s3_prefix.py` and `tests/test_create_s3_prefix.py` both depend on.

    Had no guard at all until now, while `_wipe_table` did. Expressed as an empty
    allow-list rather than an unconditional `raise` so that narrowing the refusal to one
    specific prefix later is a data change with a recorded reason, in the same shape as
    `CLEANUP_ALLOWLIST`, rather than a rewrite of this function.
    """
    if prefix not in S3_PREFIX_ALLOWLIST:
        logger.warning(json.dumps({'event': 'wipe_blocked_s3', 'prefix': prefix}))
        raise CleanupRefused(
            'S3 is never cleared here: these prefixes hold customer media, invoice '
            'renditions and product images, none of which rebuild themselves')

    deleted = 0
    paginator = s3.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix):
        objects = page.get('Contents', [])
        if not objects:
            continue
        # Only delete actual files — skip folder markers (keys ending with "/" and size <= 3)
        delete_keys = [{'Key': obj['Key']} for obj in objects if not obj['Key'].endswith('/')]
        if not delete_keys:
            continue
        for i in range(0, len(delete_keys), 1000):
            batch = delete_keys[i:i + 1000]
            s3.delete_objects(Bucket=BUCKET, Delete={'Objects': batch})
            deleted += len(batch)
    return deleted


def _purge_sqs_queue(queue_name: str) -> int:
    """Purge an allow-listed SQS queue. The allow-list is EMPTY. See `_wipe_s3_prefix`."""
    if queue_name not in SQS_QUEUE_ALLOWLIST:
        logger.warning(json.dumps({'event': 'purge_blocked_sqs', 'queue': queue_name}))
        raise CleanupRefused(
            'SQS is never purged here: a DLQ or the bulk queue holds undelivered '
            'customer work, not cache')
    try:
        url = sqs.get_queue_url(QueueName=queue_name)['QueueUrl']
        attrs = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=['ApproximateNumberOfMessages'])
        count = int(attrs['Attributes'].get('ApproximateNumberOfMessages', 0))
        sqs.purge_queue(QueueUrl=url)
        return count
    except Exception as e:
        logger.warning(f"Cannot purge SQS queue {queue_name}: {e}")
        return 0


def _cleanup(event: Dict[str, Any]) -> Dict[str, Any]:
    """Delete selected resources. Admin + MFA is already proven by `handler`.

    Order matters and is the whole design:

      parse -> require a token -> consume the token -> partition selectable/protected
            -> write the audit record (fail CLOSED) -> delete -> report

    The token is consumed before anything is deleted, so a concurrent or replayed POST is
    refused rather than deleting twice. The audit row is written before the first delete,
    so there is no window in which data is gone and nothing says who did it.
    """
    try:
        body = json.loads(event.get('body', '{}'))
    except Exception:
        return {'statusCode': 400, 'headers': cors_headers(origin), 'body': json.dumps({'error': 'Invalid JSON body'})}

    selected = [str(s) for s in (body.get('selected') or [])]
    if not selected:
        return {'statusCode': 400, 'headers': cors_headers(origin), 'body': json.dumps({'error': 'No resources selected'})}

    token = str(body.get('confirmationToken') or '').strip()
    if not token:
        # This is the UI-bypass case: a direct POST that never called GET has no token and
        # therefore cannot delete, whatever it names in `selected`.
        logger.warning(json.dumps({'event': 'cleanup_refused_no_token'}))
        return {'statusCode': 400, 'headers': cors_headers(origin), 'body': json.dumps({
            'error': 'confirmationToken required — call GET /system-cleanup first',
        })}

    consumed = _consume_confirmation(token, selected)
    if not consumed.get('ok'):
        return {'statusCode': consumed.get('status', 409), 'headers': cors_headers(origin),
                'body': json.dumps({'error': consumed.get('error', 'Confirmation failed')})}

    all_resources = _build_resources()
    results: List[Dict[str, Any]] = []
    deletable: List[str] = []
    protected_count = 0

    # Partition first, so the audit record states exactly what was about to be deleted and
    # what was refused — not what a second pass later decided.
    for key in selected:
        res = all_resources.get(key)
        if not res:
            results.append({'id': key, 'error': 'Unknown resource', 'deleted': 0})
            continue
        if res.get('protected'):
            protected_count += 1
            results.append({'id': key, 'label': res['label'], 'deleted': 0,
                            'protected': True, 'protectedReason': res.get('protectedReason', '')})
            continue
        deletable.append(key)

    actor = _actor(event)
    if deletable:
        log_id = record_audit(
            action='system.cleanup',
            actor=actor,
            resource_type='system-cleanup',
            resource_id=','.join(sorted(deletable))[:256],
            details={
                'selection': sorted(deletable),
                'requested': sorted(selected),
                'protected': sorted(k for k in selected if (all_resources.get(k) or {}).get('protected')),
                'previewCounts': consumed.get('counts', {}),
            },
        )
        if not log_id:
            # `record_audit` fails open by design. For an irreversible bulk delete that
            # trade is wrong: if we cannot record who did it, we do not do it.
            logger.error(json.dumps({'event': 'cleanup_refused_audit_unavailable', 'actor': actor}))
            return {'statusCode': 503, 'headers': cors_headers(origin), 'body': json.dumps({
                'error': 'Audit log unavailable — nothing was deleted',
            })}

    total_deleted = 0
    for key in deletable:
        res = all_resources[key]
        t0 = time.time()
        try:
            if res['type'] == 'dynamodb':
                count = _wipe_table(res['table'])
            elif res['type'] == 's3':
                count = _wipe_s3_prefix(res['prefix'])
            elif res['type'] == 'sqs':
                count = _purge_sqs_queue(res['queue'])
            else:
                raise CleanupRefused('Unknown resource type')
            elapsed = round(time.time() - t0, 1)
            results.append({'id': key, 'label': res['label'], 'deleted': count, 'elapsed': elapsed})
            total_deleted += count
        except CleanupRefused as refusal:
            # The second layer caught something the registry let through. Reported as
            # protected, not as an error: refusing is the correct outcome.
            protected_count += 1
            results.append({'id': key, 'label': res['label'], 'deleted': 0,
                            'protected': True, 'protectedReason': str(refusal)})
        except Exception as e:
            logger.error(f"Cleanup error for {key}: {e}")
            results.append({'id': key, 'label': res['label'], 'error': str(e), 'deleted': 0})

    logger.info(json.dumps({'event': 'system_cleanup', 'actor': actor, 'selected': selected,
                            'deleted': sorted(deletable), 'protected': protected_count,
                            'totalDeleted': total_deleted}))

    return {
        'statusCode': 200,
        'headers': cors_headers(origin),
        'body': json.dumps({
            'success': True,
            'results': results,
            'totalDeleted': total_deleted,
            'protected': protected_count,
            'skipped': len(selected) - len(deletable),
        }),
    }
