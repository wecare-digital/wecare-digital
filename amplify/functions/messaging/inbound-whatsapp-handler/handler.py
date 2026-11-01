"""
Inbound WhatsApp Handler Lambda Function

Purpose: Process SNS notifications for WhatsApp messages
Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 5.12, 15.4, 15.7

Parses Meta webhook event format, stores messages, downloads media,
updates contact timestamps for 24-hour customer service window.
Tracks which WABA/phone number received the message.
Integrates with AI automation when enabled in SystemConfig.
"""

import os
import re
import json
import uuid
import time
import logging
import hmac
import hashlib
import boto3
import urllib.request
import urllib.error
import urllib.parse  # explicit: `_handoff_url` quotes a token into a link
from typing import Dict, Any, Optional, Tuple
from decimal import Decimal

# Configure logging
from lambda_utils.logging import get_logger
from lambda_utils.response import extract_origin
from lambda_utils.privacy import mask_phone, mask_flow_token, mask_contact_id, redact_pii  # contactId is `wa` + the customer's digits
# Aliased because `payment_status` is a local variable throughout the payment handlers below,
# holding Meta's raw word. `pay_status` is the module that says what that word means.
from lambda_utils import payment_status as pay_status
from lambda_utils.validation import normalize_phone
from lambda_utils.message_store import put_message, query_by_contact  # unified MessagesTable: dual-write + contactId-index read
from lambda_utils.automation import evaluate_rules  # cross-channel auto-reply rules
from lambda_utils import meta_signature  # raw-body X-Hub-Signature-256 on the public route
from lambda_utils import graph_errors  # log-safe fields of a Meta error, never the raw body
from lambda_utils import whatsapp_templates  # which templates automation depends on
from lambda_utils import wa_status  # monotonic status ordering (no backward transitions)
from lambda_utils import wa_internal_event  # typed ingress -> worker contract
from lambda_utils import contact_key, identity_claims
from lambda_utils import contact_store  # one contact row per person, whichever channel minted it
from lambda_utils import shared_tables  # one name per shared store (contacts, orders, flows)
from lambda_utils.identity import subscriber_id
from lambda_utils.identity import customer_uuid  # public Customer ID display code for `my id`
from lambda_utils import customer_ideas, request_amendment_response, submit_request_response, track_shipping_response, pickup_request_response, referral_response
from lambda_utils.canonical_flows import canonical_flow_id, canonical_contract, published_flow_by_id  # one source of truth for WABA 1 flow ids
# F001 Subscribe launch door: one entry-policy decision, server-issued Flow sessions, the
# Workspace-managed opening copy and per-day funnel counters.
from lambda_utils import flow_launch, flow_sessions, flow_funnel, subscribe_messages
from lambda_utils import media_paths  # one bucket, two roots: o/ public, secure/ gated
from lambda_utils.ecommerce import order_keys  # reference_id contract; never truncate a join key
# The catalogue-order hand-off: lines and quantities, no money. Pure, so every rule it holds is
# tested without a client, and this handler stays wiring. See `_handle_cart_order`.
from lambda_utils.ecommerce import whatsapp_basket, short_purchase
from lambda_utils import live_smoke  # the WA_LIVE_SMOKE_TEST lockdown applies to direct sends too
from lambda_utils import thread_ownership  # Conversation Routing: derive ownership, never query it
from lambda_utils.system_events import record_system_event
from botocore.exceptions import ClientError
try:
    from lambda_utils import partner_billing  # per-tenant prepaid metering (optional)
except Exception:  # noqa: BLE001
    partner_billing = None

# Sub-modules (monolith decomposition)
from modules.content import extract_content as _extract_content_v2
from modules.content import extract_unsupported_content as _extract_unsupported_content_v2
from modules.content import extract_contacts_payload as _extract_contacts_payload
from modules.content import KNOWN_TYPES as _KNOWN_TYPES
from modules.content import UNSUPPORTED_DISAPPEARING, UNSUPPORTED_UNKNOWN

logger = get_logger(__name__)

# AWS clients
dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
sqs = boto3.client('sqs', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
s3 = boto3.client('s3', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
lambda_client = boto3.client('lambda', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

# Environment variables - use actual table names. The shared stores (contacts, flow
# responses, drafts) resolve through `lambda_utils.shared_tables`, so the inbox writes the same
# contact and flow-response rows the WhatsApp Flows, catalog orders and website checkout use.
CONTACTS_TABLE = shared_tables.contacts_table_name()
MESSAGES_TABLE = os.environ.get('MESSAGES_TABLE', 'stack-wecare-digital-WhatsAppInboundTable')
# Canonical unified message table (status mirror target).
UNIFIED_MESSAGES_TABLE = os.environ.get('UNIFIED_MESSAGES_TABLE', 'stack-wecare-digital-MessagesTable')
MEDIA_FILES_TABLE = os.environ.get('MEDIA_FILES_TABLE', 'stack-wecare-digital-MediaFilesTable')
SYSTEM_CONFIG_TABLE = os.environ.get('SYSTEM_CONFIG_TABLE', 'stack-wecare-digital-SystemConfigTable')
FLOW_SUBMISSIONS_TABLE = shared_tables.flow_submissions_table_name()
# Same table and same `{phone}#{flowCode}` key contract `flows/common.py` uses, named
# identically there as DRAFTS_TABLE. Phase R parks a review's order reference here under
# the Phase-R-only `WD_REV_REF` suffix so it survives the hop from this Lambda to the
# Flow data-exchange callback in `wecare-whatsapp-business-api`.
FLOW_DRAFTS_TABLE = shared_tables.flow_drafts_table_name()
AI_INTERACTIONS_TABLE = os.environ.get('AI_INTERACTIONS_TABLE', 'stack-wecare-digital-AIInteractionsTable')
INVOICES_TABLE = os.environ.get('INVOICES_TABLE', 'stack-wecare-digital-InvoicesTable')
INBOUND_DLQ_URL = wa_internal_event.inbound_dlq_url()  # was '' when unset, so nothing was parked
MEDIA_BUCKET = os.environ.get('MEDIA_BUCKET', media_paths.BUCKET)
# The PUBLIC host, deliberately separate from the bucket name. The media URL below
# was built from MEDIA_BUCKET, which only produced a valid URL while the bucket was
# named app.wecare.digital. See voice-in/obd for the same correction.
MEDIA_CDN_DOMAIN = os.environ.get('MEDIA_CDN_DOMAIN', media_paths.CDN_DOMAIN)
# Customer uploads are private from their first S3 write. Existing public media
# remains readable through its persisted key; no migration or public fallback here.
MEDIA_PREFIX = media_paths.WHATSAPP_INCOMING_PREFIX
SEND_MODE = os.environ.get('SEND_MODE', 'LIVE')

# AI Lambda function names. Every invoke target is the `live` alias: an unqualified name runs
# $LATEST, which an upload reaches before it is published and verified.
AI_QUERY_KB_FUNCTION = os.environ.get('AI_QUERY_KB_FUNCTION', 'wecare-ai-query-kb:live')
AI_GENERATE_RESPONSE_FUNCTION = os.environ.get('AI_GENERATE_RESPONSE_FUNCTION', 'wecare-ai-generate-response:live')

# Outbound WhatsApp Lambda function name
OUTBOUND_WHATSAPP_FUNCTION = os.environ.get('OUTBOUND_WHATSAPP_FUNCTION', 'wecare-outbound-whatsapp:live')

# WhatsApp Voice Lambda function name (TTS via Amazon Polly)
WHATSAPP_VOICE_FUNCTION = os.environ.get('WHATSAPP_VOICE_FUNCTION', 'wecare-whatsapp-voice:live')

# The unified checkout Lambda. The native WhatsApp cart money leg reaches its `prepareNativeCart`
# internal action through this name - the SAME machinery the website and the catalog-service leg
# use - so pricing, the single attempt + PAYREF# reservation and the approved-template send all
# live in one place. `:live` pins the alias the service leg also invokes.
CHECKOUT_FUNCTION = os.environ.get('CHECKOUT_FUNCTION', 'wecare-commerce:live')

# The prepareNativeCart invoke must reach checkout AT MOST ONCE per cart message. botocore's
# default client retries a Lambda invoke on a read timeout (60s), and a retried invoke is a second
# checkout execution - a second PaymentAttempt, PAYREF# and payment template for one cart. So this
# invoke uses its own client: no SDK retries, and a read timeout above wecare-checkout's 60s
# function timeout, so the call always returns the function's own answer (or its timeout error).
CHECKOUT_INVOKE_READ_TIMEOUT_SECONDS = 75
_checkout_lambda_client = None


def _checkout_invoke_client():
    global _checkout_lambda_client
    if _checkout_lambda_client is None:
        import botocore.config
        _checkout_lambda_client = boto3.client(
            'lambda', region_name=os.environ.get('AWS_REGION', 'us-east-1'),
            config=botocore.config.Config(read_timeout=CHECKOUT_INVOKE_READ_TIMEOUT_SECONDS,
                                          retries={'max_attempts': 0}))
    return _checkout_lambda_client

# ── the WhatsApp catalogue-order hand-off (see `_handle_cart_order`) ──────────
#
# The commerce-keys table, which holds the `WABASKET#` hand-off row beside `PAYREF#` and
# `ORDERNO#`. Defaulted through `order_keys.commerce_keys_table_name()` rather than re-typed, so
# this function and `ecommerce/checkout` cannot end up pointed at two different tables. TTL must
# stay disabled on it: it holds immutable financial and idempotency records, and the basket's own
# expiry is enforced in application code for exactly that reason.
COMMERCE_KEYS_TABLE = os.environ.get('COMMERCE_KEYS_TABLE',
                                     order_keys.commerce_keys_table_name())
# OFF unless deliberately switched on, and the only default that is safe: this is the gate in
# front of a new commerce path that writes a row and sends a customer a message. A SystemConfig
# row can override it at runtime - see `_catalog_orders_enabled`.
WA_CATALOG_ORDERS_ENABLED = os.environ.get(
    'WA_CATALOG_ORDERS_ENABLED', 'false').strip().lower() in ('true', '1', 'yes', 'on')
# The one checkout page owns the phone-bound basket claim. Never link to a retired
# cart route: it is removed, not redirected. Keep the environment override for rollout.
CART_HANDOFF_URL = os.environ.get('CART_HANDOFF_URL', 'https://wecare.digital/checkout/')
# The reply copy. NO PRICE, NO TOTAL, NO ITEM COUNT IN MONEY TERMS - the website checkout prices
# the basket from ProductsTable when the customer opens it (`checkout_pricing.compute_quote`), and
# a figure here would be a second total with a different authority.
CART_HANDOFF_BUTTON = 'Review checkout'
CART_HANDOFF_BODY = ('Your cart is saved. Open it on our website to review it and pay securely. '
                     'Sign in with this same WhatsApp number and the items will be waiting.')

# ── replies for a cart that did not become a payment request ──
# A cart answered with silence reads as "it worked". Every reply says what happened, what the
# customer can do, and that nothing was charged. No price and no total: those belong to the
# ORDER_DETAILS message checkout sends, which is the only priced message on this path.
CART_SIGN_IN_URL = 'https://wecare.digital/account/sign-in/'
CART_SHOP_URL = 'https://wecare.digital/shop/'
CART_REPLY_SIGN_IN = ('Please sign in to your WECARE.DIGITAL customer account and verify this '
                      'WhatsApp number, then send your cart again. Nothing has been charged.')
CART_REPLY_ADDRESS = ('To deliver your order, please share your delivery address. Your payment '
                      'request follows as soon as it is saved.')
CART_REPLY_ADDRESS_UNUSABLE = ('We could not use that address. Please check it and share it '
                               'again. Nothing has been charged.')
# The form opens on the address already on file, because every WhatsApp cart confirms where it
# ships (checkout's DELIVERY_CONFIRMATION_REQUIRED): the payment request shows that address but
# cannot change it.
CART_REPLY_ADDRESS_CONFIRM = ('Please confirm the delivery address for this order. Your saved '
                              'address is filled in: check it, change anything you need, then '
                              'send it. Your payment request follows.')
CART_REPLY_ADDRESS_FIX = ('We cannot deliver to the address we have on file. Please correct it '
                          'and send it. Your payment request follows.')
# A cart from a number outside India that needs an address: Meta sends the address form to +91
# numbers only, so the website takes the address and the order instead.
CART_REPLY_ADDRESS_WEB = ('We need a delivery address for this order, and WhatsApp can collect '
                          'one only from Indian (+91) numbers. Nothing has been charged. You can '
                          'complete this order on wecare.digital.')
CART_REPLY_ALREADY_REQUESTED = ('We have already sent you a payment request for this cart. '
                                'Please use that message to pay. Nothing new has been charged.')
CART_REPLY_PARTIAL = ('Some items in this cart cannot be ordered on WhatsApp. Nothing has been '
                      'charged. Please remove them and send your cart again.')
CART_REPLY_SHORT_ONLY = ('Short checkout accepts one item with quantity one. Nothing has been '
                         'charged. Choose one product in the catalog and send it again.')
CART_REPLY_ITEMS_UNAVAILABLE = ('Items in this cart are no longer available. Nothing has been '
                                'charged. Please open the catalog again and send a new cart.')
CART_REPLY_SERVICE = ('This service cannot be bought from the WhatsApp catalog yet. Nothing has '
                      'been charged. You can start it on wecare.digital.')
# Only reachable while the catalog-service leg is on: the service is one this leg sells, but the
# cart also held other lines, more than one service, or a quantity other than 1.
CART_REPLY_SERVICE_ALONE = ('A service has to be ordered on its own, one at a time. Nothing has '
                            'been charged. Please send it in a separate cart, or start it on '
                            'wecare.digital.')
CART_REPLY_NOT_HERE = ('Payment on WhatsApp is not available from this number. Nothing has been '
                       'charged. You can complete this order on wecare.digital.')
CART_REPLY_TRY_LATER = ('We could not prepare a payment request for this cart right now. Nothing '
                        'has been charged. Please try again in a few minutes.')
# A cart refused ONLY for its delivery address (missing, unpayable, or not yet confirmed for this
# order) waits here, so the India Address Message submission resumes it instead of asking the
# customer to send the cart again. One row per contact (the latest such cart wins); expiry is
# compared in code because CommerceKeys has no TTL.
CART_PENDING_PREFIX = 'WABASKETPENDING#'
CART_PENDING_LIFETIME_SECONDS = 24 * 3600

# Fix #6: Circuit breaker for AI failures  -  skip AI if too many consecutive failures
_ai_fail_count = 0
_ai_fail_reset_time = 0
AI_CIRCUIT_BREAKER_THRESHOLD = 5   # failures before tripping
AI_CIRCUIT_BREAKER_COOLDOWN = 300  # seconds (5 min) before retrying

# WhatsApp Phone Number IDs - Map Meta phone number IDs to phone number IDs
PHONE_NUMBER_ID_1 = os.environ.get('WHATSAPP_PHONE_NUMBER_ID_1', 'phone-number-id-waba1-direct-1016149501586345')
PHONE_NUMBER_ID_2 = os.environ.get('WHATSAPP_PHONE_NUMBER_ID_2', 'phone-number-id-waba-t-direct-1055232054343117')

# Map display phone numbers to phone number IDs for reference
PHONE_NUMBER_MAP = {
    '919330994400': PHONE_NUMBER_ID_1,  # +91 93309 94400 (WABA1, Direct API)
    '919903300044': PHONE_NUMBER_ID_2,  # +91 99033 00044 (WABA-T, Direct API)
}

# Meta phone number ID to phone number ID mapping
META_PHONE_ID_MAP = {
    '1016149501586345': PHONE_NUMBER_ID_1,  # +91 93309 94400 (Direct API)
    '1055232054343117': PHONE_NUMBER_ID_2,  # +91 99033 00044 (Direct API)
}

# All phones use Direct API
DIRECT_API_PHONE_IDS = {PHONE_NUMBER_ID_1, PHONE_NUMBER_ID_2}

# Platform-owned Meta WABA ids. Any OTHER WABA hitting our webhook is an
# Embedded-Signup partner tenant — tag its messages with partnerWabaId so the
# tenant-scoped customer inbox can query the partnerWabaId GSI.
PLATFORM_WABAS = {'2094615664435155', '2513394156072604'}

# How far back a revoke may be inferred to reach. A revoke payload carries no reference
# to the message it deleted (see _apply_revoke), so outside an exact id the join is a
# recency inference, and an inference across days would mis-mark. One hour covers the
# overwhelming majority of real deletions — people delete what they just sent — and
# keeps a false positive near zero. WhatsApp permits delete-for-everyone well beyond an
# hour, so this deliberately UNDER-covers rather than over-claims: widening it trades
# correctness for coverage, and the `revoke_target_unresolved` log line is the evidence
# for whether it should be.
REVOKE_CORRELATION_WINDOW_SECONDS = 3600
# Keys Meta might one day populate with the revoked message's id, in preference order.
# All three are checked because the exact join is strictly better than the inference and
# costs one dict lookup; today none of them is present in a measured payload.
_REVOKE_TARGET_ID_KEYS = ('revoked_message_id', 'id', 'message_id')





def _get_welcome_config_key(phone_number_id: str) -> str:
    """Return the SystemConfig key for welcome message based on phone number.
    Phone 1 uses 'welcome_message', Phone 2 uses 'welcome_message_2'."""
    if phone_number_id == PHONE_NUMBER_ID_2:
        return 'welcome_message_2'
    return 'welcome_message'


DEFAULT_FALLBACK_MESSAGE = "Thanks for your message! Type 'menu' to see available options, or 'subscribe' to get started."

# The degraded fallback when the Graph list send fails (no token, HTTP error). It is
# NOT the menu any more — see WD_LISTS below — but it must stay: a greeting / QR
# prefill / ice-breaker tap has to get an answer rather than silence or a crash even
# when Meta refuses the list. The string is pinned byte-for-byte against the
# `whatsapp-calling` Lambda's own copy by tests/test_calling_menu_template_is_gone.py.
MENU_PLACEHOLDER_TEXT = "We're refreshing our menu - please type *menu* and we'll help you."


# ── The WECARE.DIGITAL site menu, as WhatsApp interactive lists ──────────────
# Owner-approved structure, 2026-10-03. It mirrors the public site mega-menu in
# src/components/Header.tsx, so a path here and a path there must not drift.
#
# SHOP IS EXCLUDED BY OWNER DECISION. There is no Shop row anywhere, and there must
# not be one. (`STORE_KEYWORDS` further down still answers a *typed* `shop` with a
# CTA button; that is a live inbound alias, not a menu row, and it stays.)
#
# Meta's interactive-list limits, which `_send_wd_list` also enforces defensively so
# a future edit to this data cannot produce a 400:
#   rows per list <= 10 · row title <= 24 chars · row description <= 72
#   button text <= 20 · header <= 60 · body <= 1024
# Trailing slashes in the paths are LOAD-BEARING (the site has trailingSlash on);
# dropping one turns a link into a redirect at best and a 404 at worst.
WD_SITE_BASE = 'https://wecare.digital'

# leaf row id -> (display name, site path or absolute external URL). Tapping any of these sends a text reply
# with the link, not another list.
WD_LEAF_LINKS: Dict[str, Tuple[str, str]] = {
    'wd_home': ('About / Home', '/'),
    # Products
    'wd_grahak_os': ('Grahak OS', '/grahak-os/'),
    'wd_vayulok': ('VayuLok', '/vayulok/'),
    'wd_bharat_rx': ('Bharat Rx', '/bharat-rx/'),
    # Elsewhere children. There is no Elsewhere category landing page any more (it became a category
    # on 2026-10-15, mirroring the Header), so `wd_elsewhere` is a submenu, not a leaf.
    'wd_elsewhere_visa': ('Visa', '/elsewhere/visa/'),
    'wd_elsewhere_trip': ('Trip', '/elsewhere/trip/'),
    'wd_elsewhere_activities': ('Activities', '/elsewhere/activities/'),
    'wd_expo_week': ('Expo Week', '/expo-week/'),
    # Family labels have no page; their concrete destinations are leaves below.
    'wd_dastavez_drafting': ('Drafting', '/dastavez/drafting/'),
    'wd_dastavez_registration': ('Registration', '/dastavez/registration/'),
    'wd_dastavez_legal_reference': ('Legal Reference', '/dastavez/legal-reference/'),
    'wd_clear_guided_resolution': ('Guided Resolution', '/shop/guided-resolution/'),
    'wd_clear_case_submission': ('Case Submission', '/shop/file-assist/'),
    'wd_clear_paperwork': ('Paperwork', '/shop/paperwork/'),
    'wd_ritual_puja_guidance': ('Puja Guidance', '/ritual-guru/puja-guidance/'),
    'wd_ritual_diy_kit': ('DIY Puja Kit', '/ritual-guru/diy-puja-kit/'),
    'wd_anew': ('Anew', '/anew/'),
    'wd_hunar_kaushal': ('Kaushal', '/hunar/kaushal/'),
    'wd_hunar_prastuti': ('Prastuti', '/hunar/prastuti/'),
    'wd_niji_setu': ('Niji Setu', '/niji-setu/'),
    # Request
    'wd_orders': ('Orders', '/orders/'),
    'wd_submit': ('Submit Request', '/submit-request/'),
    'wd_amend': ('Request Amendment', '/request-amendment/'),
    'wd_drop_docs': ('Drop Docs', '/drop-docs/'),
    'wd_vault': ('Vault', '/vault/'),
    'wd_track': ('Track', '/shipments/track/'),
    'wd_pickup': ('Pickup Request', '/request-pickup/'),
    'wd_review': ('Leave Review', 'https://wa.me/message/ZM74K2H2BIFOA1'),
    # Refer & Earn children
    'wd_merchandise': ('Merchandise', '/shop/merchandise/'),
    'wd_kiosk': ('Kiosk', '/shop/kiosk/'),
    'wd_referral': ('Referral', 'https://wa.me/message/S6A2QEXZSYXTG1'),
    'wd_contact': ('Contact us', '/contact/'),
    'wd_perks': ('Perks', 'https://wa.me/message/377GALDW4E26F1'),
    # Legal
    'wd_terms': ('Terms', '/terms/'),
    'wd_privacy': ('Privacy', '/privacy/'),
}

# list key -> the list to send. `wd_main` is the only one with a header. Every
# submenu ends with wd_back so a customer is never stranded one level down.
WD_LISTS: Dict[str, Dict[str, Any]] = {
    'wd_main': {
        'header': 'WECARE.DIGITAL',
        'body': 'Everyday AI, built for Bharat. What do you need?',
        'button': 'Open Menu',
        'section': 'Menu',
        'rows': [
            {'id': 'wd_home', 'title': '\U0001f3e0 About / Home', 'description': 'Who we are and what we do'},
            {'id': 'wd_products', 'title': '\U0001f4e6 Products', 'description': 'Explore our products'},
            {'id': 'wd_request', 'title': '\U0001f9fe Request', 'description': 'Orders, requests, documents'},
            {'id': 'wd_work', 'title': '\U0001f91d Work with us', 'description': 'Refer, contact, perks'},
            {'id': 'wd_legal', 'title': '\U0001f4c4 Legal & Extras', 'description': 'Terms, privacy, perks'},
        ],
    },
    # Eleven products do not fit in one 10-row list, so the chooser splits them.
    'wd_products': {
        'body': 'Products — choose a set',
        'button': 'Open Menu',
        'section': 'Products',
        'rows': [
            {'id': 'wd_products_1', 'title': 'Products (1 of 2)', 'description': 'Grahak OS, VayuLok, Bharat Rx…'},
            {'id': 'wd_products_2', 'title': 'Products (2 of 2)', 'description': 'Clear Closure, Anew, Hunar…'},
            {'id': 'wd_back', 'title': '\u2b05\ufe0f Back to menu'},
        ],
    },
    'wd_products_1': {
        'body': 'Products (1 of 2)',
        'button': 'Open Menu',
        'section': 'Products',
        'rows': [
            {'id': 'wd_grahak_os', 'title': 'Grahak OS'},
            {'id': 'wd_vayulok', 'title': 'VayuLok'},
            {'id': 'wd_bharat_rx', 'title': 'Bharat Rx'},
            {'id': 'wd_elsewhere', 'title': 'Elsewhere'},
            {'id': 'wd_expo_week', 'title': 'Expo Week'},
            {'id': 'wd_dastavez', 'title': 'Dastavez'},
            {'id': 'wd_back', 'title': '\u2b05\ufe0f Back to menu'},
        ],
    },
    'wd_products_2': {
        'body': 'Products (2 of 2)',
        'button': 'Open Menu',
        'section': 'Products',
        'rows': [
            {'id': 'wd_clear_closure', 'title': 'Clear Closure'},
            {'id': 'wd_ritual_guru', 'title': 'Ritual Guru'},
            {'id': 'wd_anew', 'title': 'Anew'},
            {'id': 'wd_hunar', 'title': 'Hunar'},
            {'id': 'wd_niji_setu', 'title': 'Niji Setu'},
            {'id': 'wd_back', 'title': '\u2b05\ufe0f Back to menu'},
        ],
    },
    'wd_request': {
        'body': 'Request — orders, requests and documents',
        'button': 'Open Menu',
        'section': 'Request',
        'rows': [
            {'id': 'wd_orders', 'title': 'Orders'},
            {'id': 'wd_submit', 'title': 'Submit Request'},
            {'id': 'wd_amend', 'title': 'Request Amendment'},
            {'id': 'wd_drop_docs', 'title': 'Drop Docs'},
            {'id': 'wd_vault', 'title': 'Vault'},
            {'id': 'wd_shipments', 'title': 'Shipments'},
            {'id': 'wd_review', 'title': 'Leave Review'},
            {'id': 'wd_back', 'title': '\u2b05\ufe0f Back to menu'},
        ],
    },
    # Elsewhere has no parent page (Header.tsx renders it as a label over three
    # children), so the row opens its children instead of linking a 404.
    'wd_elsewhere': {
        'body': 'Elsewhere',
        'button': 'Open Menu',
        'section': 'Elsewhere',
        'rows': [
            {'id': 'wd_elsewhere_visa', 'title': 'Visa'},
            {'id': 'wd_elsewhere_trip', 'title': 'Trip'},
            {'id': 'wd_elsewhere_activities', 'title': 'Activities'},
            {'id': 'wd_back', 'title': '\u2b05\ufe0f Back to menu'},
        ],
    },
    'wd_dastavez': {
        'body': 'Dastavez',
        'button': 'Open Menu',
        'section': 'Dastavez',
        'rows': [
            {'id': 'wd_dastavez_drafting', 'title': 'Drafting'},
            {'id': 'wd_dastavez_registration', 'title': 'Registration'},
            {'id': 'wd_dastavez_legal_reference', 'title': 'Legal Reference'},
            {'id': 'wd_back', 'title': '\u2b05\ufe0f Back to menu'},
        ],
    },
    'wd_clear_closure': {
        'body': 'Clear Closure',
        'button': 'Open Menu',
        'section': 'Clear Closure',
        'rows': [
            {'id': 'wd_clear_guided_resolution', 'title': 'Guided Resolution'},
            {'id': 'wd_clear_case_submission', 'title': 'Case Submission'},
            {'id': 'wd_clear_paperwork', 'title': 'Paperwork'},
            {'id': 'wd_back', 'title': '\u2b05\ufe0f Back to menu'},
        ],
    },
    'wd_ritual_guru': {
        'body': 'Ritual Guru',
        'button': 'Open Menu',
        'section': 'Ritual Guru',
        'rows': [
            {'id': 'wd_ritual_puja_guidance', 'title': 'Puja Guidance'},
            {'id': 'wd_ritual_diy_kit', 'title': 'DIY Puja Kit'},
            {'id': 'wd_back', 'title': '\u2b05\ufe0f Back to menu'},
        ],
    },
    'wd_hunar': {
        'body': 'Hunar',
        'button': 'Open Menu',
        'section': 'Hunar',
        'rows': [
            {'id': 'wd_hunar_kaushal', 'title': 'Kaushal'},
            {'id': 'wd_hunar_prastuti', 'title': 'Prastuti'},
            {'id': 'wd_back', 'title': '\u2b05\ufe0f Back to menu'},
        ],
    },
    'wd_shipments': {
        'body': 'Shipments',
        'button': 'Open Menu',
        'section': 'Shipments',
        'rows': [
            {'id': 'wd_track', 'title': 'Track'},
            {'id': 'wd_pickup', 'title': 'Pickup Request'},
            {'id': 'wd_back', 'title': '\u2b05\ufe0f Back to menu'},
        ],
    },
    'wd_work': {
        'body': 'Refer, perks and contact',
        'button': 'Open Menu',
        'section': 'More',
        'rows': [
            {'id': 'wd_refer', 'title': 'Refer & Earn'},
            {'id': 'wd_perks', 'title': 'Perks'},
            {'id': 'wd_contact', 'title': 'Contact us'},
            {'id': 'wd_back', 'title': '\u2b05\ufe0f Back to menu'},
        ],
    },
    'wd_refer': {
        'body': 'Refer & Earn',
        'button': 'Open Menu',
        'section': 'Refer & Earn',
        'rows': [
            {'id': 'wd_partner', 'title': 'Partner'},
            {'id': 'wd_back', 'title': '\u2b05\ufe0f Back to menu'},
        ],
    },
    'wd_partner': {
        'body': 'Partner',
        'button': 'Open Menu',
        'section': 'Partner',
        'rows': [
            {'id': 'wd_merchandise', 'title': 'Merchandise'},
            {'id': 'wd_kiosk', 'title': 'Kiosk'},
            {'id': 'wd_referral', 'title': 'Referral'},
            {'id': 'wd_back', 'title': '\u2b05\ufe0f Back to menu'},
        ],
    },
    'wd_legal': {
        'body': 'Legal & Extras',
        'button': 'Open Menu',
        'section': 'Legal & Extras',
        'rows': [
            {'id': 'wd_terms', 'title': 'Terms'},
            {'id': 'wd_privacy', 'title': 'Privacy'},
            {'id': 'wd_back', 'title': '\u2b05\ufe0f Back to menu'},
        ],
    },
}

# The leaf reply. Exact copy — it is customer-facing and the only thing a tap
# produces.
WD_LEAF_TEMPLATE = "{name}\nOpen it here \U0001f449 {url}\n\nOr just tell me what you need and I'll help."


# Deterministic-trigger keywords for the Meta Business Agent hybrid. When the AI
# holds control (standby), we take control + run OUR flow only for these; free-form
# text is left to the AI.
_DETERMINISTIC_KEYWORDS = {
    'hi', 'hello', 'hey', 'menu', 'main menu', 'show menu', 'browse menu', '/menu',
    'start', 'get started', 'need help!', 'subscribe', 'help',
    # Our own QR / widget prefills — see the HI_KEYWORDS comment. These must take
    # control from the Meta AI agent, not be treated as free-form questions.
    'get help', 'hi 👋',
}
_DETERMINISTIC_CONTAINS = (
    'get started', 'main menu', 'subscribe', 'track request', 'track', 'submit request',
    'amend request', 'appointment', 'rx slot', 'drop docs', 'enterprise', 'leave review',
    'catalog', 'catalogue', 'pay', 'payment', 'invoice', 'faq',
)


_routing_cache = {'v': None, 't': 0.0}


def _get_routing_config() -> Dict:
    """Load the AI hybrid routing config (which triggers the bot handles vs the AI)
    from SystemConfigTable id='ai_hybrid_routing'. Cached 60s. Falls back to the
    built-in defaults so behaviour is safe if unset."""
    import time as _t
    now = _t.time()
    if _routing_cache['v'] is not None and (now - _routing_cache['t']) < 60:
        return _routing_cache['v']
    # ── These defaults REPRODUCE the deleted hardcoded _is_deterministic_trigger ──
    # Until 2026-10-06 a second definition of that function shadowed the config-driven
    # one below, so the config-driven one was dead code and its defaults had never run.
    # Deleting the shadow without changing these would have been a BEHAVIOUR CHANGE, in
    # three measured ways:
    #
    #   types     the live function also accepted 'nfm_reply' (flow + address submissions)
    #   keywords  it matched _STANDBY_TEXT_TRIGGERS, which does NOT contain 'help'
    #   contains  it had no substring matching at all, whereas _DETERMINISTIC_CONTAINS
    #             would have claimed any body containing 'pay', 'track', 'faq', …
    #
    # So the defaults are the standby trigger set with substring matching OFF.
    # _DETERMINISTIC_KEYWORDS / _DETERMINISTIC_CONTAINS stay in the module as the
    # *optional widening* a seeded config row can opt into; they are no longer the
    # default. tests/test_deterministic_trigger_equivalence.py is the proof, and it
    # retypes its expectations from the deleted function rather than from this code.
    cfg = {
        'enabled': True,
        'keywords': sorted(_STANDBY_TEXT_TRIGGERS),
        'contains': [],
        'types': ['button', 'interactive', 'order', 'nfm_reply'],
        'commandPrefix': '/',
    }
    try:
        item = dynamodb.Table(SYSTEM_CONFIG_TABLE).get_item(Key={'id': 'ai_hybrid_routing'}).get('Item')
        if item:
            raw = item.get('configValue')
            data = json.loads(raw) if isinstance(raw, str) else (raw or {})
            for k in ('enabled', 'keywords', 'contains', 'types', 'commandPrefix'):
                if k in data and data[k] is not None:
                    cfg[k] = data[k]
    except Exception:
        pass
    _routing_cache['v'] = cfg
    _routing_cache['t'] = now
    return cfg


# General review entry uses the published private v2 Flow. Order-attributed
# `review <reference>` remains a separate route below the exact keyword loop.
CUSTOMER_IDEA_KEYWORDS = frozenset({
    'leave review', 'leave a review', 'review', 'feedback', 'leave feedback',
    'share feedback', 'share your experience', 'rate', 'rating', 'testimonial',
    'share an idea', 'share idea', '/idea', '/review', 'feature request',
    'suggest an idea', 'suggestion', 'suggest a feature', '⭐ leave review',
})


def _is_deterministic_trigger(message: Dict) -> bool:
    """True if the message should be handled by OUR deterministic flows (menu,
    lists, flows, catalog/cart, commands) rather than the Meta AI agent.

    The ONLY definition of this name since 2026-10-06, when the hardcoded second copy
    that shadowed it was deleted. Driven by the `ai_hybrid_routing` row in
    SystemConfigTable, whose defaults reproduce the deleted copy exactly — so this is a
    live kill switch (`enabled: false` stops every standby reply with no deploy) rather
    than the dead code it had been.

    Deciding that our flow HANDLES a message is not the same as deciding a reply is
    SENT. The send decision is `_standby_reply_enabled()` plus `_may_send()`.
    """
    cfg = _get_routing_config()
    if not cfg.get('enabled', True):
        return False  # hybrid off → everything goes to the AI
    # `or {}` because the deleted definition tolerated None and this one has to as well,
    # or removing the shadow would turn a no-op into an AttributeError on the webhook path.
    message = message or {}
    t = message.get('type')
    if t in set(cfg.get('types') or ['button', 'interactive', 'order', 'nfm_reply']):
        return True  # ice-breaker taps, list/flow replies, catalog cart orders
    if t == 'text':
        body = ((message.get('text', {}) or {}).get('body', '') or '').strip().lower()
        if not body:
            return False
        prefix = cfg.get('commandPrefix', '/')
        if prefix and body.startswith(prefix):
            return True  # slash commands
        kws = {k.lower() for k in (cfg.get('keywords') or [])} | CUSTOMER_IDEA_KEYWORDS
        kws |= {'orders', 'my orders', 'order history', 'all orders', 'customer id',
                'my customer id', 'customer uuid', 'vault', 'my vault',
                'request amendment', 'drop docs', 'shipments', 'submit request'}
        if re.fullmatch(r'orders page [1-9][0-9]{0,2}', body):
            return True
        if body in kws or strip_decorative_edges(body) in kws:
            return True
        return any(kw.lower() in body for kw in (cfg.get('contains') or []))
    return False


# ── Which standby messages our deterministic flow claims ──
# When another responder holds control, the customer's messages arrive on the
# `standby` field as copies. This is the set `_get_routing_config` defaults its
# `keywords` to, so it remains the decision set in force — it is now READ through the
# config loader instead of being hardcoded into a second copy of the decision function.
#
# A SECOND definition of `_is_deterministic_trigger` used to sit here and shadow the
# config-driven one above, which the file's own docstring called out as a known defect.
# It was deleted on 2026-10-06. The consequence of the shadowing was not cosmetic: the
# `ai_hybrid_routing` kill switch could never work, because the function that reads it
# was never the function being called. There was no runtime way to stop replying from
# standby without a code deploy.
#
# Note what this set does and does not decide. It decides whether OUR deterministic flow
# handles a standby message. Whether a reply is then actually SENT from standby is
# `STANDBY_REPLY_ENABLED`'s decision, not this set's — see `_standby_reply_enabled`.
_STANDBY_TEXT_TRIGGERS = {
    'hi', 'hello', 'hey', 'menu', 'main menu', 'show menu', 'start', 'get started',
    'browse menu', '/menu', 'need help!', 'subscribe', 'pay', '/pay', 'catalog',
    'view catalog', 'submit request', 'track request', 'track', 'amend request',
    'appointment', 'rx slot', 'drop docs', 'enterprise', 'leave review', 'faq',
    # Our own QR / widget prefills — see the HI_KEYWORDS comment.
    'get help', 'hi 👋',
}


def _standby_reply_enabled() -> bool:
    """Whether a deterministic standby message falls through into a real reply.

    **Defaults TRUE, which is today's exact behaviour.** Shipped true deliberately: the
    ingress invokes `wecare-inbound-whatsapp` UNQUALIFIED, so `$LATEST` is production and
    this code is live the instant `update-function-code` returns, before any alias move.
    There is no staging gap, so a behaviour change cannot be landed and then verified —
    it has to default to what already happens.

    Read per call rather than cached at module scope, following `_auto_thumb_enabled`:
    a module-scope read is frozen for the life of the execution environment, so a
    configuration change would not take effect until every warm sandbox recycled.

    Setting it false stores standby messages as context but sends nothing from standby,
    which is the correct behaviour under an active Conversation Routing configuration
    where we are a standby partner — Meta rejects a Service message from a non-owner.
    The flip waits on the owner confirming such a configuration exists.
    """
    return os.environ.get('STANDBY_REPLY_ENABLED', 'true').strip().lower() \
        not in ('false', '0', 'no', 'off')


# ── Per-message send context, for the standby ownership guard ──
# A module-level dict following the existing `_current_direct_api_phone` precedent
# (declared `global` in `_process_message`): the handler processes messages serially
# within an invocation, so this is the established pattern here rather than a new one.
# RESET at the top of `_process_message` on every message — a `standby` flag leaking
# across two messages in one invocation is the one way `_may_send` can misfire.
_send_context = {'standby': False, 'phone_number_id': '', 'bsuid': '', 'wa_id': ''}


def _may_send(purpose: str) -> bool:
    """May we send, given who owns this thread?

    **With `STANDBY_REPLY_ENABLED` at its shipped `true` default this is unconditionally
    `True`**, so every call site is a no-op and behaviour is identical to before this
    guard existed. That is the whole design: the ingress invokes this function unqualified,
    so `$LATEST` is production and there is no staging gap in which to verify a behaviour
    change — it has to ship inert.

    When the flag is false, a message that arrived as a **standby copy** is checked against
    derived ownership. Messages that arrived on the normal `messages` field are never
    checked, because receiving one is itself the documented proof that we own the thread.

    `thread_ownership.may_send` fails OPEN on unknown or unreadable state, so even with
    the flag off a DynamoDB blip does not silence a customer.
    """
    if _standby_reply_enabled() or not _send_context.get('standby'):
        return True
    ok = thread_ownership.may_send(_send_context.get('phone_number_id', ''),
                                  bsuid=_send_context.get('bsuid', ''),
                                  wa_id=_send_context.get('wa_id', ''))
    if not ok:
        logger.info(json.dumps({
            'event': 'send_suppressed_not_owner',
            'purpose': purpose,
            'bsuid': _send_context.get('bsuid', ''),
            'waId': mask_phone(_send_context.get('wa_id', '') or ''),
        }))
    return ok


def _thread_identity(value: Dict, message: Optional[Dict] = None) -> Tuple[str, str, str]:
    """`(phone_number_id, bsuid, wa_id)` for a webhook `value`, optionally narrowed to
    one message.

    One helper rather than four copies, because the three identifiers are spelled
    differently depending on where they are read from and getting one of them wrong is
    silent: `from_user_id` on a message, `user_id` on a contact, both meaning BSUID.

    BSUID is preferred over `wa_id` by `thread_ownership.thread_key`, not here — this
    returns both and lets the key contract decide, so there is one place that rule lives.
    """
    message = message or {}
    phone_number_id = str((value.get('metadata') or {}).get('phone_number_id') or '')
    contacts = value.get('contacts')
    if not isinstance(contacts, list):
        contacts = (value.get('standby') or {}).get('contacts') \
            if isinstance(value.get('standby'), dict) else None
    contact = contacts[0] if isinstance(contacts, list) and contacts \
        and isinstance(contacts[0], dict) else {}
    bsuid = str(message.get('from_user_id') or contact.get('user_id')
                or contact.get('from_user_id') or '')
    wa_id = str(message.get('from') or contact.get('wa_id') or '')
    return phone_number_id, bsuid, wa_id


# ── Decorative-edge stripping for menu keyword matching ────────────────────
# Every keyword set in this file is EXACT-MATCH, which is why two of our own QR
# prefills reached production matching nothing at all:
#
#   "Get Help"  (WABA1 QR APDM5HUWH26SG1)  -> not 'get help' in any set
#   "Hi 👋"     (WABA2 QR DPESCFW7U4FXO1)  -> not 'hi', because of the emoji
#
# Adding those two literals fixed those two strings and nothing else. The failure
# mode is the exact-match itself: "Hi 👋🏽", "menu 🙏", "❓ FAQs" and the next
# prefill somebody sets on Meta all miss for the identical reason. So the edges
# are normalised instead, and the MENU-ish sets are matched against the stripped
# form as a FALLBACK after the raw form misses.
#
# Deliberately narrow, on three counts:
#
#  * Explicit codepoint ranges, not Unicode categories. `So`/`Mn` would have been
#    shorter and would also strip Devanagari combining marks off the edges of
#    Hindi input - PAY_KEYWORDS carries 'भुगतान', 'बिल', 'पेमेंट' and 'बाकी', and
#    silently truncating those would be a worse bug than the one being fixed.
#  * ASCII punctuation is NOT stripped, because '/menu' must survive intact.
#  * Applied ONLY to the greeting / customer-service / commands sets, where a false
#    positive costs a stray reply. NOT to PAY_KEYWORDS (money), DEFAULT_FLOW_TRIGGERS
#    (creates records) or MY_ID_KEYWORDS (discloses subscriber details).
#
# The ranges cover every emoji this codebase actually puts in a menu row or a
# keyword: 🚀🔔🆔💳🛍️🎁🇮🇳❓💛📋🔍✏️📅🩺📄🏢⭐👋🧭🫶 plus VS16 and ZWJ.
_DECORATIVE_RANGES = (
    (0x1F000, 0x1FAFF),  # emoji, pictographs, flags, enclosed alphanumerics
    (0x2600, 0x27BF),    # misc symbols + dingbats (❓ ✏ ✂ ✅)
    (0x2B00, 0x2BFF),    # misc symbols and arrows (⭐)
    (0xFE00, 0xFE0F),    # variation selectors
    (0x200D, 0x200D),    # zero-width joiner
)


def _is_decorative(ch: str) -> bool:
    cp = ord(ch)
    return ch.isspace() or any(lo <= cp <= hi for lo, hi in _DECORATIVE_RANGES)


def strip_decorative_edges(text: str) -> str:
    """Trim emoji, variation selectors, ZWJ and whitespace off both ends.

    'Hi 👋' -> 'hi' style normalisation for keyword matching. Leaves the interior
    untouched and leaves ASCII punctuation alone, so '/menu' and 'need help!' are
    unchanged. Returns '' for input that is nothing but decoration.
    """
    if not text:
        return ''
    start, end = 0, len(text)
    while start < end and _is_decorative(text[start]):
        start += 1
    while end > start and _is_decorative(text[end - 1]):
        end -= 1
    return text[start:end]


def _load_fallback_message(phone_number_id: str) -> str:
    """Load configurable fallback message from SystemConfigTable."""
    try:
        config_table = dynamodb.Table(SYSTEM_CONFIG_TABLE)
        response = config_table.get_item(Key={'id': 'wa_auto_response'})
        if 'Item' in response:
            config_value = response['Item'].get('configValue', '{}')
            config = json.loads(config_value) if isinstance(config_value, str) else config_value
            return config.get('fallbackMessage', DEFAULT_FALLBACK_MESSAGE)
        return DEFAULT_FALLBACK_MESSAGE
    except Exception:
        return DEFAULT_FALLBACK_MESSAGE


def _load_welcome_text(phone_number_id: str, default_text: str) -> str:
    """Load custom welcome text from SystemConfigTable for the given phone."""
    try:
        config_key = _get_welcome_config_key(phone_number_id)
        _wc = dynamodb.Table(SYSTEM_CONFIG_TABLE).get_item(Key={'id': config_key}).get('Item')
        if _wc:
            _wc_val = json.loads(_wc.get('configValue', '{}')) if isinstance(_wc.get('configValue'), str) else _wc.get('configValue', {})
            if _wc_val.get('textMessage'):
                return _wc_val['textMessage']
    except Exception:
        pass
    return default_text


def _is_direct_api_phone(phone_number_id: str) -> bool:
    """Check if a phone number ID belongs to a Direct API WABA."""
    return phone_number_id in DIRECT_API_PHONE_IDS


# ── Direct API support ──────────────────────────────────────────────
# All WABAs use Direct Meta Graph API for messaging.
# Token loaded from Secrets Manager (same secret as calling handler).
META_TOKEN_SECRET = os.environ.get('META_TOKEN_SECRET', 'wecare/meta-system-user-token')
from lambda_utils.meta_version import META_API_VERSION  # one source; validated at import
PHONE1_META_ID = '1016149501586345'  # +91 93309 94400 (WABA1, Direct API)
_direct_api_token_cache = {}
secrets_client = boto3.client('secretsmanager', region_name=os.environ.get('AWS_REGION', 'us-east-1'))


def _load_direct_api_token() -> str:
    """Load Meta access token for Direct API calls (cached)."""
    if 'token' in _direct_api_token_cache:
        return _direct_api_token_cache['token']
    try:
        resp = secrets_client.get_secret_value(SecretId=META_TOKEN_SECRET)
        secret = resp.get('SecretString', '')
        try:
            data = json.loads(secret)
            _direct_api_token_cache['token'] = (data.get('access_token') or '').strip()
            _direct_api_token_cache['app_secret'] = (data.get('app_secret') or '').strip()
            # WABA2's app has its own secret; a webhook may be signed by either.
            _direct_api_token_cache['app_secret_waba2'] = (
                data.get('app_secret_waba2') or ''
            ).strip()
        except (json.JSONDecodeError, TypeError):
            _direct_api_token_cache['token'] = secret.strip()
            _direct_api_token_cache['app_secret'] = ''
            _direct_api_token_cache['app_secret_waba2'] = ''
        return _direct_api_token_cache.get('token', '')
    except Exception as e:
        logger.error(f"Failed to load Direct API token: {e}")
        return ''


def _meta_app_secrets() -> list:
    """Candidate Meta app secrets for webhook signature verification."""
    if 'app_secret' not in _direct_api_token_cache:
        _load_direct_api_token()
    return [
        _direct_api_token_cache.get('app_secret', ''),
        _direct_api_token_cache.get('app_secret_waba2', ''),
    ]


def _get_meta_phone_id_for_direct_api(aws_phone_id: str) -> str:
    """Get the Meta phone ID for a Direct API phone number."""
    DIRECT_API_META_MAP = {
        PHONE_NUMBER_ID_1: '1016149501586345',  # +91 93309 94400 (WABA1)
        PHONE_NUMBER_ID_2: '1055232054343117',  # +91 99033 00044 (WABA-T)
    }
    meta_id = DIRECT_API_META_MAP.get(aws_phone_id)
    if meta_id:
        return meta_id
    # Fallback: extract from direct format phone-number-id-*-direct-{meta_id}
    if '-direct-' in aws_phone_id:
        return aws_phone_id.split('-direct-')[-1]
    # Last resort: use WABA-T phone (confirmed working)
    return '1055232054343117'


# Track current phone context for Direct API calls
_current_direct_api_phone = None

# Auto 👍 reaction toggle. Applies to outbound messages sent from THIS handler
# (AI auto-replies, IVR responses) and to inbound received-message reactions.
# Resolved at runtime from SystemConfig (id='whatsapp_auto_thumb', cached) with the
# env var as the default. Default ON.
AUTO_THUMB_REACTION_ENABLED = os.environ.get('AUTO_THUMB_REACTION_ENABLED', 'true').strip().lower() in ('true', '1', 'yes', 'on')
AUTO_THUMB_EMOJI = os.environ.get('AUTO_THUMB_EMOJI', '\U0001F44D')
_auto_thumb_cache = {'value': None, 'ts': 0.0}
_AUTO_THUMB_CACHE_TTL = 300  # seconds — admin toggles propagate within 5 min


def _auto_thumb_enabled() -> bool:
    """Runtime auto 👍 toggle. Reads SystemConfig 'whatsapp_auto_thumb' at most once
    per _AUTO_THUMB_CACHE_TTL seconds (cached); falls back to the env default."""
    now = time.time()
    if _auto_thumb_cache['value'] is not None and (now - _auto_thumb_cache['ts']) < _AUTO_THUMB_CACHE_TTL:
        return _auto_thumb_cache['value']
    val = AUTO_THUMB_REACTION_ENABLED
    try:
        item = dynamodb.Table(SYSTEM_CONFIG_TABLE).get_item(Key={'id': 'whatsapp_auto_thumb'}).get('Item')
        if item and 'configValue' in item:
            val = str(item.get('configValue')).lower() in ('true', '1', 'yes', 'on')
    except Exception as e:
        logger.warning(f"auto_thumb config read failed (using default {val}): {e}")
    _auto_thumb_cache['value'] = val
    _auto_thumb_cache['ts'] = now
    return val


def _send_direct_api_message(to_number: str, message_payload: Dict, meta_phone_id: str = None) -> Dict:
    """Send a WhatsApp message via Meta Graph API for Direct API phones."""
    token = _load_direct_api_token()
    if not token:
        return {'error': True, 'detail': 'No Direct API token available'}

    if not to_number.startswith('+'):
        to_number = f'+{to_number}'
    message_payload['to'] = to_number
    message_payload['messaging_product'] = 'whatsapp'

    phone_id = meta_phone_id or _current_direct_api_phone or PHONE1_META_ID
    url = f"https://graph.facebook.com/{META_API_VERSION}/{phone_id}/messages"
    app_secret = _direct_api_token_cache.get('app_secret', '')
    if app_secret:
        proof = hmac.new(app_secret.encode(), token.encode(), hashlib.sha256).hexdigest()
        url = f"{url}?appsecret_proof={proof}"

    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }
    data = json.dumps(message_payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode('utf-8')
            result = json.loads(body) if body else {}
            msg_id = ''
            messages = result.get('messages', [])
            if messages:
                msg_id = messages[0].get('id', '')
            # Auto 👍 on outbound messages sent from this handler (auto-replies, IVR).
            # Skip reaction-type payloads to prevent recursion. React from the SAME
            # phone (phone_id) that sent the message so the wamid resolves.
            if (msg_id and message_payload.get('type') != 'reaction'
                    and _auto_thumb_enabled()):
                try:
                    _send_direct_api_message(to_number, {
                        'type': 'reaction',
                        'reaction': {'message_id': msg_id, 'emoji': AUTO_THUMB_EMOJI},
                    }, meta_phone_id=phone_id)
                except Exception:
                    pass  # reaction is best-effort; never affect the primary send
            return {'success': True, 'messageId': msg_id}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8') if e.fp else ''
        # Classified, redacted fields only: Meta's details can echo the request.
        logger.error(json.dumps({'event': 'direct_api_send_failed',
                                 **graph_errors.log_fields(error_body, e.code)}))
        return {'error': True, 'status': e.code, 'detail': error_body}
    except Exception as e:
        # Only the class name: a URLError's text can embed the request URL.
        logger.error(json.dumps({'event': 'direct_api_send_failed', 'error': type(e).__name__}))
        return {'error': True, 'detail': str(e)}


def _send_direct_api_reaction(to_number: str, whatsapp_message_id: str, emoji: str = '\U0001F44D') -> Dict:
    """Send a reaction via Meta Graph API via Direct API."""
    payload = {
        'type': 'reaction',
        'reaction': {
            'message_id': whatsapp_message_id,
            'emoji': emoji
        }
    }
    return _send_direct_api_message(to_number, payload)


def _send_direct_api_read_receipt(whatsapp_message_id: str, meta_phone_id: str = None, show_typing: bool = False) -> Dict:
    """Send a read receipt via Meta Graph API for Direct API phones.
    When show_typing=True, also displays the in-app typing indicator (auto-dismisses
    when you reply or after 25s) — per Meta's typing_indicator API. Only use when a
    reply will follow."""
    token = _load_direct_api_token()
    if not token:
        return {'error': True, 'detail': 'No Direct API token available'}
    payload = {
        'messaging_product': 'whatsapp',
        'status': 'read',
        'message_id': whatsapp_message_id
    }
    if show_typing:
        payload['typing_indicator'] = {'type': 'text'}
    phone_id = meta_phone_id or _current_direct_api_phone or PHONE1_META_ID
    url = f"https://graph.facebook.com/{META_API_VERSION}/{phone_id}/messages"
    app_secret = _direct_api_token_cache.get('app_secret', '')
    if app_secret:
        proof = hmac.new(app_secret.encode(), token.encode(), hashlib.sha256).hexdigest()
        url = f"{url}?appsecret_proof={proof}"
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return {'success': True}
    except urllib.error.HTTPError as e:
        # Meta's own response body, so it carries no credential of ours. `url`,
        # `req` and `headers` must never be logged: the URL carries
        # appsecret_proof and the headers carry the bearer token.
        error_body = e.read().decode('utf-8') if e.fp else ''
        logger.warning(json.dumps({'event': 'direct_api_read_receipt_failed',
                                   **graph_errors.log_fields(error_body, e.code)}))
        return {'error': True, 'status': e.code, 'detail': error_body}
    except Exception as e:
        # Only the class name: a URLError's text embeds the request URL.
        logger.warning(f"Direct API read receipt failed: {type(e).__name__}")
        return {'error': True, 'detail': str(e)}


def _graph_error_code(detail) -> str:
    """Meta's numeric error code from a Graph error body, or '' if unparseable.
    Returns the code only — the body can echo request parameters."""
    try:
        return str((json.loads(detail or '{}').get('error') or {}).get('code') or '')
    except Exception:
        return ''


def _send_direct_api_typing(whatsapp_message_id: str, meta_phone_id: str = None) -> Dict:
    """Show the WhatsApp typing indicator via Meta's real typing_indicator API.
    Marks the message read and displays 'typing…' (auto-dismisses on reply or after 25s).
    Requires the inbound WhatsApp message_id."""
    if not whatsapp_message_id:
        return {'error': True, 'detail': 'whatsapp_message_id required for typing indicator'}
    return _send_direct_api_read_receipt(whatsapp_message_id, meta_phone_id=meta_phone_id, show_typing=True)


# NOTE: a second `_download_media_direct_api` used to be defined here, taking 5
# positional parameters and no `phone_number_id`. It was dead code: Python binds the
# name to whichever definition executes last, so the 6-parameter definition further
# down in this file always won, and the logs prove it (`media_download_direct_api`
# from that one, never `direct_api_media_downloaded` from this one). It was removed
# on 2026-10-06 together with the two call sites that still passed 5 positional
# arguments to the 6-parameter signature, which silently bound `request_id` to
# `phone_number_id` and the mime hint to `request_id`. Harmless in effect - the
# download does not send `phone_number_id` - but it made the request id in those log
# lines wrong, and it would have become a real defect the moment anything started
# reading that parameter. The surviving call sites pass keyword arguments.


# TTL: 30 days in seconds
MESSAGE_TTL_SECONDS = 30 * 24 * 60 * 60

# ── Payment flow messages (hardcoded, LLM-independent, edit here to change) ──
PAY_MSG = {
    'pulling':      '\U0001f440 Pulling your pending invoice...',
    'no_dues':      '\u2705 No pending dues!',
    'paid':         '\u2705 Paid successfully.',
    'pay_failed':   '\u274c Payment failed. Please try again.',
    'all_clear':    '\u2705 No pending dues!',
    'next_due':     '\u26a0\ufe0f You have unpaid invoice of \u20b9{total}.',
    'send_failed':  '\u274c Could not send payment link. Please try again.',
    'error':        '\u26a0\ufe0f Something went wrong. Please try again.',
    'wa_body':      'Your payment is ready \u2014 tap below to complete it \U0001f4b3',
    # `redirect` removed 2026-09-30 with its only caller. It told a customer on WABA2 to go and
    # message +919330994400 instead, because Phone 1 was believed to be the only payment-capable
    # number. Both halves were wrong: every phone handles payments directly, and Phone 1 was
    # never disconnected (measured live, quality GREEN). Sending someone to a different number
    # also abandons the open 24-hour window on the conversation they are already in.
}

# Phone number ID that handles payments (Phone 1: +919330994400 / WECARE.DIGITAL)
PAYMENT_PHONE_NUMBER_ID = 'phone-number-id-waba1-direct-1016149501586345'


# ── Coexistence: the owner running the WhatsApp Business APP on the same number as the
# Cloud API. NOT adopted on this deployment. Both fields are audited and counted and
# nothing else — see the `messaging_handovers` arm in `handler` for the same discipline
# and the same reason: structured parse, NO decision taken from it. `smb_message_echoes`
# carries copies of messages the owner sent from the app, so writing them to the inbox
# would duplicate the owner's own messages into the CRM timeline on a deployment that has
# no coexistence configured. `COEXISTENCE_INGEST_ENABLED` is the seam a future adoption
# would open; it defaults false, and false means audit-only.
#
# This is a MODULE-LEVEL frozenset, deliberately a different convention from the
# `_SYSTEM_EVENT_FIELDS` set beside its membership test. That set looks like a module
# constant but is a set literal rebuilt INSIDE the per-`change` webhook loop in `handler`,
# with its membership test immediately below it. `_process_coexistence_event` is a
# module-level function and needs these names too, so a loop-local set would have to be
# passed in or duplicated. Rebuilding a 10-element set per webhook change is harmless;
# duplicating a field-name list is not. The asymmetry is recorded rather than resolved:
# normalising `_SYSTEM_EVENT_FIELDS` to module scope would touch a loop nine existing
# fields depend on, for no behavioural gain.
_COEXISTENCE_FIELDS = frozenset({'smb_app_state_sync', 'smb_message_echoes'})
# History media enrichment can carry value.messages, just like live inbound
# traffic. Replay must stay audit-only and never run customer automation.
# https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/history/
_AUDIT_ONLY_REPLAY_FIELDS = _COEXISTENCE_FIELDS | {'history'}


def _coexistence_ingest_enabled() -> bool:
    """Whether history/app-echo replay is projected into the canonical Inbox.

    SystemConfig `whatsapp_coexistence_ingest` overrides the environment default so an owner
    can enable/disable ingestion without a deploy. The replay lane never calls live-message
    automation and never advances lastInboundMessageAt.
    """
    default = os.environ.get('COEXISTENCE_INGEST_ENABLED', 'false').strip().lower() \
        in ('1', 'true', 'yes', 'on')
    try:
        item = dynamodb.Table(SYSTEM_CONFIG_TABLE).get_item(
            Key={'id': 'whatsapp_coexistence_ingest'}, ConsistentRead=True).get('Item') or {}
        if 'configValue' in item:
            return str(item.get('configValue') or '').strip().lower() in ('1', 'true', 'yes', 'on')
    except Exception as e:
        logger.warning(json.dumps({
            'event': 'coexistence_ingest_config_read_failed',
            'error': type(e).__name__,
        }))
    return default


def _replay_message_content(message: Dict) -> str:
    """Best-effort Inbox text for a Meta history/echo message, without side effects."""
    try:
        msg_type = str(message.get('type') or 'unknown')
        content = _extract_content_v2(message, msg_type)
        if isinstance(content, str):
            return content
    except Exception:
        pass
    msg_type = str(message.get('type') or 'unknown')
    if msg_type == 'media_placeholder':
        return '[Historical media]'
    return f'[Historical {msg_type} message]'


def _ingest_replay_message(message: Dict, user_phone: str, business_phone: str,
                           phone_number_id: str, request_id: str, source: str,
                           *, phase: Any = None, chunk_order: Any = None) -> bool:
    """Project one history/Business-App echo into MessagesTable only.

    This intentionally does NOT call `_process_message`: no keyword/AI/welcome/payment action,
    no media download, no consent mutation, and no 24-hour service-window timestamp update.
    The Meta wamid is the row id, so webhook replay overwrites the same row instead of duplicating.
    """
    user_digits = contact_store.digits(user_phone)
    if not user_digits or not isinstance(message, dict):
        return False
    wamid = str(message.get('id') or '').strip()
    if not wamid:
        return False

    # A history chunk can include messages already received live before coexistence was
    # enabled. Deduplicate on Meta's global message id before choosing a new row id.
    try:
        existing = dynamodb.Table(UNIFIED_MESSAGES_TABLE).query(
            IndexName='whatsappMessageId-index',
            KeyConditionExpression='whatsappMessageId = :w',
            ExpressionAttributeValues={':w': wamid},
            Limit=1,
        ).get('Items') or []
        if existing:
            logger.info(json.dumps({
                'event': 'coexistence_replay_message_already_present',
                'source': source,
                'requestId': request_id,
            }))
            return True
    except Exception as e:
        # Fail closed on a dedup read failure: importing a duplicate is worse than deferring
        # this historical projection, while the raw webhook remains archived for redrive.
        logger.warning(json.dumps({
            'event': 'coexistence_replay_dedup_failed',
            'source': source,
            'error': type(e).__name__,
            'requestId': request_id,
        }))
        return False

    try:
        contact = _get_or_create_contact(user_digits)
        contact_id = contact_key.resolve(contact)
    except Exception as e:
        logger.warning(json.dumps({
            'event': 'coexistence_replay_contact_failed',
            'source': source,
            'phone': mask_phone(user_phone),
            'error': type(e).__name__,
            'requestId': request_id,
        }))
        return False
    if not contact_id:
        return False

    from_digits = contact_store.digits(message.get('from'))
    business_digits = contact_store.digits(business_phone)
    direction = 'outbound' if from_digits and business_digits and from_digits == business_digits else 'inbound'
    history_context = message.get('history_context') or {}
    raw_status = str(history_context.get('status') or ('sent' if direction == 'outbound' else 'received')).lower()
    status = raw_status if raw_status in ('pending', 'sent', 'delivered', 'read', 'failed', 'received') \
        else ('sent' if direction == 'outbound' else 'received')
    try:
        timestamp = int(message.get('timestamp') or time.time())
    except (TypeError, ValueError):
        timestamp = int(time.time())

    stored = put_message(
        channel='whatsapp',
        direction=direction,
        contact_id=contact_id,
        content=_replay_message_content(message),
        status=status,
        message_id=wamid,
        timestamp=timestamp,
        whatsapp_message_id=wamid,
        message_type=str(message.get('type') or 'unknown'),
        aws_phone_number_id=_get_aws_phone_number_id(
            str(business_phone or ''), str(phone_number_id or ''), [str(phone_number_id or '')]),
        replaySource=source,
        replayOnly=True,
        historyPhase=phase,
        historyChunkOrder=chunk_order,
        raise_on_error=False,
    )
    logger.info(json.dumps({
        'event': 'coexistence_replay_message_ingested' if stored else 'coexistence_replay_message_skipped',
        'source': source,
        'direction': direction,
        'contactId': mask_contact_id(contact_id),
        'wamidPresent': bool(wamid),
        'requestId': request_id,
    }))
    return bool(stored)


def _archive_meta_event(event_type: str, value: Dict, request_id: str,
                        waba_id: str = '', phone_number_id: str = '') -> str:
    """Archive one Meta webhook payload to partitioned JSON in the existing media bucket.

    This is analytics/audit storage only. It never feeds the Inbox, automation, or sends.
    Fail-open so an S3 outage cannot make Meta retry a webhook that was otherwise processed.
    """
    try:
        day = time.strftime('%Y-%m-%d', time.gmtime())
        key = (
            f'secure/d/public/whatsapp/analytics/meta-events/date={day}/event_type={event_type}/'
            f'{int(time.time() * 1000)}-{uuid.uuid4().hex}.json'
        )
        payload = {
            'eventType': event_type,
            'receivedAt': int(time.time()),
            'requestId': request_id,
            'wabaId': waba_id,
            'phoneNumberId': phone_number_id,
            'payload': value,
        }
        s3.put_object(
            Bucket=MEDIA_BUCKET,
            Key=key,
            Body=(json.dumps(payload, default=str, separators=(',', ':')) + '\n').encode('utf-8'),
            ContentType='application/json',
            ServerSideEncryption='AES256',
        )
        return key
    except Exception as e:
        logger.warning(json.dumps({
            'event': 'meta_event_archive_failed',
            'eventType': event_type,
            'error': type(e).__name__,
            'requestId': request_id,
        }))
        return ''


def _record_meta_system_event(event_type: str, value: Dict, request_id: str,
                              waba_id: str = '', phone_number_id: str = '') -> None:
    """Persist a Meta system webhook in both dashboard ring-buffer and durable audit stores."""
    _store_system_event(event_type, value, request_id)
    archive_key = _archive_meta_event(
        event_type, value, request_id, waba_id=waba_id,
        phone_number_id=phone_number_id)
    record_system_event(
        f'whatsapp_{event_type}',
        waba_id=waba_id or None,
        phone_number_id=phone_number_id or None,
        severity='info',
        data={
            'requestId': request_id,
            'archiveKey': archive_key,
            'payload': value,
        },
    )


def _process_history_event(value: Dict, request_id: str, waba_id: str = '') -> None:
    """Persist coexistence history chunks without replaying them as live customer traffic."""
    phone_id = str((value.get('metadata') or {}).get('phone_number_id') or '')
    history = value.get('history') or []
    if not isinstance(history, list):
        history = []
    _record_meta_system_event('history', value, request_id, waba_id, phone_id)
    for chunk in history:
        if not isinstance(chunk, dict):
            continue
        meta = chunk.get('metadata') or {}
        threads = chunk.get('threads') or []
        if not isinstance(threads, list):
            threads = []
        message_count = sum(
            len((thread or {}).get('messages') or [])
            for thread in threads if isinstance(thread, dict)
        )
        record_system_event(
            'whatsapp_history_chunk',
            waba_id=waba_id or None,
            phone_number_id=phone_id or None,
            severity='info',
            data={
                'requestId': request_id,
                'phase': meta.get('phase'),
                'chunkOrder': meta.get('chunk_order'),
                'progress': meta.get('progress'),
                'threadCount': len(threads),
                'messageCount': message_count,
            },
        )
        if _coexistence_ingest_enabled():
            business_phone = str((value.get('metadata') or {}).get('display_phone_number') or '')
            imported = 0
            for thread in threads:
                if not isinstance(thread, dict):
                    continue
                user_phone = str(thread.get('id') or '')
                for message in (thread.get('messages') or []):
                    if _ingest_replay_message(
                            message, user_phone, business_phone, phone_id, request_id, 'history',
                            phase=meta.get('phase'), chunk_order=meta.get('chunk_order')):
                        imported += 1
            record_system_event(
                'whatsapp_history_chunk_ingested',
                waba_id=waba_id or None,
                phone_number_id=phone_id or None,
                severity='info',
                data={
                    'requestId': request_id,
                    'phase': meta.get('phase'),
                    'chunkOrder': meta.get('chunk_order'),
                    'imported': imported,
                },
            )


def _process_partner_solution_event(value: Dict, request_id: str, waba_id: str = '') -> None:
    """Persist Multi-Partner Solution lifecycle changes as structured audit events."""
    phone_id = str((value.get('metadata') or {}).get('phone_number_id') or '')
    _record_meta_system_event('partner_solutions', value, request_id, waba_id, phone_id)
    solution = value.get('partner_solution') or value.get('solution') or value
    if not isinstance(solution, dict):
        solution = {}
    record_system_event(
        'whatsapp_partner_solution_change',
        waba_id=waba_id or None,
        phone_number_id=phone_id or None,
        severity='info',
        data={
            'requestId': request_id,
            'solutionId': solution.get('id') or solution.get('solution_id'),
            'partnerId': solution.get('partner_id') or solution.get('partner_business_id'),
            'status': solution.get('status') or solution.get('event'),
        },
    )


def _process_coexistence_event(field: str, value: Dict, request_id: str) -> None:
    """Audit and count a coexistence webhook. Writes NO message row and sends nothing.

    `_store_system_event` is used exactly as the nine informational fields use it, so the
    raw envelope is inspectable in SystemConfigTable without any inbox change.
    `phone_number_id` is NOT a phone number and is logged in full; recipient phones go
    through `mask_phone`.
    """
    phone_id = str((value.get('metadata') or {}).get('phone_number_id') or '')
    _record_meta_system_event(field, value, request_id, phone_number_id=phone_id)
    if field == 'smb_message_echoes':
        echoes = value.get('message_echoes') or value.get('messages') or []
        if not isinstance(echoes, list):
            echoes = []
        logger.info(json.dumps({
            'event': 'smb_message_echoes_received',
            'echoCount': len(echoes),
            'types': sorted({str((e or {}).get('type', '')) for e in echoes if isinstance(e, dict)}),
            'phoneNumberId': str((value.get('metadata') or {}).get('phone_number_id') or ''),
            'recipients': [mask_phone(str((e or {}).get('to') or '')) for e in echoes
                           if isinstance(e, dict)][:10],
            'ingested': False,
            'requestId': request_id,
        }))
    else:
        state = value.get('state') or value.get(field) or {}
        logger.info(json.dumps({
            'event': 'smb_app_state_sync_received',
            'contactCount': len(state.get('contacts') or []) if isinstance(state, dict) else 0,
            'chatCount': len(state.get('chats') or []) if isinstance(state, dict) else 0,
            'phoneNumberId': str((value.get('metadata') or {}).get('phone_number_id') or ''),
            'ingested': False,
            'requestId': request_id,
        }))
    if _coexistence_ingest_enabled() and field == 'smb_message_echoes':
        business_phone = str((value.get('metadata') or {}).get('display_phone_number') or '')
        phone_id = str((value.get('metadata') or {}).get('phone_number_id') or '')
        echoes = value.get('message_echoes') or value.get('messages') or []
        imported = 0
        for message in echoes if isinstance(echoes, list) else []:
            if not isinstance(message, dict):
                continue
            user_phone = str(message.get('to') or '')
            if _ingest_replay_message(
                    message, user_phone, business_phone, phone_id, request_id, 'smb_message_echoes'):
                imported += 1
        logger.info(json.dumps({
            'event': 'smb_message_echoes_ingested',
            'imported': imported,
            'phoneNumberId': phone_id,
            'requestId': request_id,
        }))


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Process inbound WhatsApp messages from SNS.
    
    Meta Webhook Event Format:
    {
        "context": { "MetaWabaIds": [...], "MetaPhoneNumberIds": [...] },
        "whatsAppWebhookEntry": "{...JSON STRING...}",
        "aws_account_id": "775261844268",
        "message_timestamp": "2026-01-17T12:00:00.000Z",
        "messageId": "uuid"
    }
    """
    request_id = context.aws_request_id if context else 'local'
    origin = extract_origin(event)
    processed_count = 0
    error_count = 0
    
    # Timeout guard: reserve 15s for cleanup/response to avoid Lambda timeout
    _lambda_deadline_ms = (context.get_remaining_time_in_millis() if context else 120000)
    _start_time = time.time()

    # ── Authenticate anything arriving over HTTP, before any side effect ──
    # The production path is an internal `lambda_client.invoke` from
    # wecare-whatsapp-calling, which has already verified Meta's
    # X-Hub-Signature-256 on the canonical /whatsapp ingress. But this function
    # also sits behind a public `POST /whatsapp/inbound` route with
    # AuthorizationType=NONE, and until 2026-09-21 that door required no
    # signature, no token and no Cognito identity - so an anonymous caller could
    # inject forged messages into the inbox and reach create_invoice.
    #
    # An internally invoked event carries no API Gateway envelope, so this guard
    # applies only to the public door and leaves the verified path untouched.
    _via_http = meta_signature.is_http_request(event)
    if _via_http:
        _ok, _reason = meta_signature.verify(event, _meta_app_secrets())
        if not _ok:
            logger.warning(json.dumps({
                'event': 'inbound_http_signature_rejected',
                'reason': _reason,
                'requestId': request_id,
            }))
            return {
                'statusCode': 401,
                'body': json.dumps({'success': False, 'error': 'invalid_signature'}),
            }

    # ── Direct invoke: create_invoice from dashboard ──
    # Internal callers only (core/messages-delete invokes this). A signed Meta
    # webhook never carries `action`, so honouring it over HTTP would only ever
    # serve a forged request.
    if event.get('action') == 'create_invoice':
        if _via_http:
            logger.warning(json.dumps({
                'event': 'inbound_http_action_rejected',
                'action': 'create_invoice',
                'requestId': request_id,
            }))
            return {
                'statusCode': 401,
                'body': json.dumps({'success': False, 'error': 'internal_invocation_only'}),
            }
        # The legacy free-form invoice path (own PNG, float maths, 2% fee, WD-PAY-<hex>) is
        # retired: it rendered outside the GST series. Callers must use the invoice engine's GST
        # series instead; the action is answered with a terminal 410 rather than silently dropped.
        logger.info(json.dumps({
            'event': 'create_invoice_gone',
            'requestId': request_id,
        }))
        return {'statusCode': 410, 'success': False, 'error': 'INVOICE_CREATION_MOVED'}
    
    # Accept the typed contract from the ingress AND the legacy synthetic SNS
    # envelope. Both arms are load-bearing: the ingress and this worker deploy
    # separately and the invoke is asynchronous, so in-flight events can carry the
    # old shape, and dlq-replay may hold stored payloads in it for its retention
    # period. `shape` is logged so the legacy arm's retirement can be measured
    # rather than guessed. See lambda_utils/wa_internal_event.
    _work_items = wa_internal_event.parse(event)

    logger.info(json.dumps({
        'event': 'inbound_processing_start',
        'itemCount': len(_work_items),
        'shapes': sorted({i['shape'] for i in _work_items}),
        'requestId': request_id
    }))

    if not _work_items:
        logger.warning(json.dumps({
            'event': 'inbound_unrecognised_event',
            'topLevelKeys': sorted(k for k in event.keys())[:12],
            'requestId': request_id,
        }))

    for _item in _work_items:
        try:
            meta_waba_ids = _item['waba_ids']
            meta_phone_number_ids = _item['phone_number_ids']
            aws_message_id = _item['message_id'] or str(uuid.uuid4())
            webhook_entry = _item['entry']
            
            # Process each change in the webhook entry
            for change in webhook_entry.get('changes', []):
                value = change.get('value', {})
                metadata = value.get('metadata', {})

                # ── Meta Business Agent handover protocol ──
                # When the Meta AI agent is the primary responder it HOLDS control,
                # and the customer's messages arrive on the `standby` field (copies),
                # while `messaging_handovers` notifies of control changes. We must NOT
                # run our normal responder on standby traffic (that would hijack the
                # AI's thread by implicitly taking control). Capture the payload for
                # audit + to finalise command routing, then skip normal processing.
                _wh_field = change.get('field', '')
                # Per-change, so a standby entry cannot mark a normal `messages` entry
                # later in the same webhook body. Set only by the standby fall-through.
                _standby_sourced = False
                if _wh_field == 'messaging_handovers':
                    # Control-change notification — audit only.
                    try:
                        _store_system_event(_wh_field, value, request_id)
                    except Exception:
                        pass
                    # Structured parse, NO decision taken from it. The ring buffer above
                    # keeps only the last 10 events per type, which is an audit sample
                    # rather than a trail — the ten real handovers from Jul-Aug 2026 are
                    # all that survived of a period when routing was live on both WABAs.
                    # A named log line is queryable and alarmable; a buffer is neither.
                    #
                    # `wa_id` is a phone number, so it is masked. `bsuid` is
                    # business-scoped and is logged in full — that pairing is what makes
                    # a routing event traceable without disclosing a customer's number.
                    try:
                        _ho = thread_ownership.parse_handover(value)
                        logger.info(json.dumps({
                            'event': 'thread_control_changed',
                            'control': _ho['control'],
                            'previousOwnerRole': _ho['previous_owner_role'],
                            'newOwnerRole': _ho['new_owner_role'],
                            'reason': _ho['reason'],
                            'shape': _ho['shape'],
                            'hasConversationContext': _ho['conversation_context'] is not None,
                            'phoneNumberId': _ho['phone_number_id'],
                            'bsuid': _ho['bsuid'],
                            'waId': mask_phone(_ho['wa_id'] or ''),
                            'requestId': request_id,
                        }))
                        # Fold the control change into derived ownership state. WRITE AND
                        # LOG ONLY — nothing in this function gates a send on it. Meta has
                        # no ownership API, so this state is the only possible answer to
                        # "may I send?", and derived state has to be observed to be right
                        # before it is allowed to refuse a customer a reply.
                        _sig = thread_ownership.signal_for_control(_ho)
                        if _sig:
                            _st = thread_ownership.record_signal(
                                _ho['phone_number_id'],
                                bsuid=_ho['bsuid'], wa_id=_ho['wa_id'],
                                signal=_sig,
                                # Persisted only when present. It carries the previous
                                # responder's summary of the conversation and arrives only
                                # on control_passed, and only sometimes; passing None
                                # through would overwrite a stored one with nothing.
                                conversation_context=_ho['conversation_context'],
                                detail=_ho['reason'])
                            logger.info(json.dumps({
                                'event': 'thread_ownership_signal',
                                'signal': _sig,
                                'tracked': _st.get('tracked'),
                                'owned': _st.get('owned'),
                                'idle': _st.get('idle'),
                                'bsuid': _ho['bsuid'],
                                'waId': mask_phone(_ho['wa_id'] or ''),
                                'requestId': request_id,
                            }))
                    except Exception as _hoe:
                        logger.warning(json.dumps({
                            'event': 'thread_control_parse_error',
                            'error': type(_hoe).__name__, 'requestId': request_id}))
                    continue
                if _wh_field == 'standby':
                    # AI holds control. In the handover payload the message + contacts are
                    # nested under value["standby"] (not value["messages"]). Unwrap it, then
                    # take control + run OUR flow ONLY for deterministic triggers
                    # (menu/list/flow/catalog/commands); leave free-form to the AI.
                    try:
                        _sb = value.get('standby')
                        if isinstance(_sb, dict):
                            _msgs = _sb.get('messages', []) or value.get('messages', []) or []
                            _contacts = _sb.get('contacts')
                        elif isinstance(_sb, list):
                            _msgs = _sb; _contacts = None
                        else:
                            _msgs = value.get('messages', []) or []; _contacts = None
                        _det = [m for m in _msgs if _is_deterministic_trigger(m)]
                        # A standby copy means SOMEBODY ELSE owns this thread. Recorded as
                        # an ownership signal; nothing here reads it back, and the arm's
                        # control flow is untouched.
                        _pid, _bsuid, _waid = _thread_identity(
                            value, _msgs[0] if _msgs else None)
                        _sb_state = thread_ownership.record_signal(
                            _pid, bsuid=_bsuid, wa_id=_waid,
                            signal=thread_ownership.SIGNAL_STANDBY_OBSERVED)
                        # Store EVERY standby message as standby-MARKED context, including
                        # the free-form ones the `continue` below discards. Meta's docs
                        # direct you to store incoming standby events locally so you can
                        # retrieve them if you receive control, indexed by BSUID — and the
                        # free-form ones are precisely the conversation the OTHER responder
                        # is handling, which is the context a later handover would need.
                        #
                        # These rows go NOWHERE NEAR MessagesTable or the Unified Inbox.
                        # Marking inbox rows is a separate, deferred change; keeping standby
                        # context in its own table is what keeps that deferrable, because no
                        # UI reads this and no dashboard behaviour changes.
                        _stored = 0
                        for _m in _msgs:
                            try:
                                _c = _extract_content(_m, (_m or {}).get('type', 'text'))
                            except Exception:
                                _c = ''
                            _mp, _mb, _mw = _thread_identity(value, _m)
                            if thread_ownership.store_standby_message(
                                    _mp or _pid, bsuid=_mb or _bsuid, wa_id=_mw or _waid,
                                    message=_m, content=_c):
                                _stored += 1
                        logger.info(json.dumps({'event': 'standby_webhook', 'total': len(_msgs),
                                                'deterministic': len(_det), 'requestId': request_id}))
                        logger.info(json.dumps({
                            'event': 'thread_ownership_signal',
                            'signal': thread_ownership.SIGNAL_STANDBY_OBSERVED,
                            'tracked': _sb_state.get('tracked'),
                            'owned': _sb_state.get('owned'),
                            'stored': _stored,
                            'bsuid': _bsuid,
                            'waId': mask_phone(_waid or ''),
                            'requestId': request_id,
                        }))
                        if not _standby_reply_enabled():
                            # The fix, shipped OFF. Reached only when somebody deliberately
                            # sets STANDBY_REPLY_ENABLED=false, which is the correct state
                            # under an active routing configuration where we are a standby
                            # partner: Meta REJECTS a Service message from a non-owner, so
                            # replying from here produces a silent dead end rather than a
                            # double reply. The messages are stored above either way, so
                            # suppression keeps the context instead of discarding it.
                            logger.info(json.dumps({
                                'event': 'standby_reply_suppressed',
                                'total': len(_msgs), 'deterministic': len(_det),
                                'stored': _stored, 'requestId': request_id}))
                            continue
                        if not _det:
                            continue  # free-form → let the Meta AI agent respond
                        # Unwrap so normal processing (below) handles the deterministic
                        # triggers.
                        #
                        # The comment that used to sit here said "sending a reply takes
                        # thread control from the AI". That was TRUE when this was written
                        # on 2026-07-21 — the Meta Business Agent shared the number and no
                        # routing configuration existed — and it is contradicted by Meta's
                        # current Standby-partners doc: once Conversation Routing is active,
                        # only the designated escalation partner can take a thread that way,
                        # and a Service message from any other standby partner is rejected.
                        # Ownership is claimed by RECEIVING, not by replying. A comment
                        # stating a false protocol rule is how the next reader repeats the
                        # mistake, so it is recorded here rather than deleted.
                        # `STANDBY_REPLY_ENABLED` is the switch between the two worlds.
                        value['messages'] = _det
                        if _contacts is not None:
                            value['contacts'] = _contacts
                        # Mark the rest of this entry as standby-sourced so `_may_send` can
                        # see it. Inert while the flag is true.
                        _standby_sourced = True
                        # fall through to normal message processing
                    except Exception as _he:
                        logger.warning(json.dumps({'event': 'standby_webhook_error',
                                                   'error': str(_he), 'requestId': request_id}))
                        continue

                # Extract receiving phone number info from metadata
                display_phone_number = metadata.get('display_phone_number', '')
                phone_number_id = metadata.get('phone_number_id', '')
                
                # Determine AWS phone number ID for this WABA. Only meaningful when
                # the change carries messages — the _process_message call below is
                # the sole consumer, and _process_status takes no such parameter.
                # WABA-level notifications (`flows` endpoint-availability alerts: 938
                # in 14 days) carry no `metadata`, so resolving here produced ~96
                # WARNING lines a day about a value that was then discarded.
                aws_phone_number_id = (
                    _get_aws_phone_number_id(display_phone_number, phone_number_id,
                                             meta_phone_number_ids)
                    if value.get('messages') and _wh_field not in _AUDIT_ONLY_REPLAY_FIELDS else ''
                )
                
                # Extract contacts info (contains profile names, BSUIDs, usernames)
                # WhatsApp webhook format: contacts array has wa_id, user_id, profile.name, profile.username
                contacts_info = value.get('contacts', [])
                contacts_map = {}
                for contact_info in contacts_info:
                    wa_id = contact_info.get('wa_id', '')
                    user_id = contact_info.get('user_id', '')  # BSUID
                    parent_user_id = contact_info.get('parent_user_id', '')
                    profile = contact_info.get('profile', {})
                    profile_name = profile.get('name', '')
                    username = profile.get('username', '')  # WhatsApp username (e.g. @pablomorales)
                    # Map by wa_id (phone) and user_id (BSUID) for flexible lookup
                    entry = {
                        'name': profile_name,
                        'bsuid': user_id,
                        'parent_bsuid': parent_user_id,
                        'username': username,
                        'contact_book_name': profile.get('contact_book_name', ''),
                        'wa_id': wa_id,
                    }
                    if wa_id:
                        contacts_map[wa_id] = entry
                    if user_id:
                        contacts_map[user_id] = entry
                
                # ── A coexistence change never enters normal message processing ──
                # MEASURED, not hypothetical: `smb_message_echoes` may carry its copies
                # under `messages` (which is why `_process_coexistence_event` reads that
                # key as a fallback), and this loop runs BEFORE the `_COEXISTENCE_FIELDS`
                # arm below. Driven with that payload shape, the handler wrote a row to
                # WhatsAppInboundTable, auto-created a contact, called `put_message` and
                # attempted a welcome send — i.e. it ingested the owner's own outbound
                # copies as inbound CUSTOMER messages and replied to them. Coexistence is
                # not adopted here, so the field is audited and counted and nothing else.
                # Guarding with a computed list rather than a `continue` keeps the audit
                # arm below reachable; the four group arms it sits beside use no
                # `continue` either. Inert for every other field.
                _coexistence_change = _wh_field in _AUDIT_ONLY_REPLAY_FIELDS
                _inbound_messages = [] if _coexistence_change else value.get('messages', [])

                # Process incoming messages
                for _message_index, message in enumerate(_inbound_messages):
                    try:
                        # Timeout guard: skip remaining messages if <15s left
                        if context and context.get_remaining_time_in_millis() < 15000:
                            logger.warning(json.dumps({
                                'event': 'timeout_guard_triggered',
                                'remainingMs': context.get_remaining_time_in_millis(),
                                'processedCount': processed_count,
                                'requestId': request_id
                            }))
                            # Park the unprocessed rest as the typed event dlq-replay hands back
                            # to this worker. The old `{'messages': [...]}` record matched no
                            # shape wa_internal_event.parse accepts, so a replay reproduced
                            # nothing; and slicing by the request-wide processed_count dropped
                            # messages once an earlier change had any. Statuses stay out: this
                            # run still processes them below.
                            _remaining_value = {k: v for k, v in value.items() if k != 'statuses'}
                            _remaining_value['messages'] = _inbound_messages[_message_index:]
                            _send_to_dlq(
                                wa_internal_event.build(
                                    entry={**webhook_entry,
                                           'changes': [{**change, 'value': _remaining_value}]},
                                    waba_id=_item.get('waba_id') or '',
                                    meta_phone_number_ids=meta_phone_number_ids,
                                    request_id=request_id,
                                ),
                                'timeout_guard', request_id)
                            break
                        
                        # Get sender info from contacts array (BSUID-aware)
                        sender_phone = message.get('from', '')
                        sender_bsuid = message.get('from_user_id', '')  # BSUID from message
                        sender_parent_bsuid = message.get('from_parent_user_id', '')  # Parent BSUID from message
                        # Lookup contact info by phone or BSUID
                        contact_entry = contacts_map.get(sender_phone) or contacts_map.get(sender_bsuid) or {}
                        sender_profile_name = contact_entry.get('name', '') if isinstance(contact_entry, dict) else contact_entry
                        sender_username = contact_entry.get('username', '') if isinstance(contact_entry, dict) else ''
                        sender_contact_book_name = contact_entry.get('contact_book_name', '') if isinstance(contact_entry, dict) else ''
                        # Use BSUID from contacts_map if not in message directly
                        if not sender_bsuid and isinstance(contact_entry, dict):
                            sender_bsuid = contact_entry.get('bsuid', '')
                        # Use parent BSUID from contacts_map if not in message directly
                        if not sender_parent_bsuid and isinstance(contact_entry, dict):
                            sender_parent_bsuid = contact_entry.get('parent_bsuid', '')
                        
                        _process_message(
                            message=message,
                            metadata=metadata,
                            request_id=request_id,
                            receiving_phone=display_phone_number,
                            aws_phone_number_id=aws_phone_number_id,
                            meta_waba_ids=meta_waba_ids,
                            sender_profile_name=sender_profile_name,
                            sender_bsuid=sender_bsuid,
                            sender_parent_bsuid=sender_parent_bsuid,
                            sender_username=sender_username,
                            sender_contact_book_name=sender_contact_book_name,
                            standby_sourced=_standby_sourced,
                        )
                        processed_count += 1
                    except Exception as e:
                        logger.error(json.dumps({
                            'event': 'message_processing_error',
                            'messageId': message.get('id'),
                            'error': str(e),
                            'requestId': request_id
                        }))
                        error_count += 1
                        if customer_ideas.idea_payload(message) is not None and not isinstance(e, ValueError):
                            # The record-level recovery path stores normalized work in
                            # the DLQ. Do not acknowledge an idea storage failure alone.
                            raise
                
                # Process status updates
                # Same coexistence guard, same reason: `_process_status` writes to both
                # message tables, and a coexistence envelope must reach neither.
                _status_waba_id = (meta_waba_ids[0] if meta_waba_ids else '')
                for status in ([] if _coexistence_change else value.get('statuses', [])):
                    try:
                        _process_status(status, request_id, contacts_map=contacts_map, waba_id=_status_waba_id)
                    except Exception as e:
                        logger.error(json.dumps({
                            'event': 'status_processing_error',
                            'statusId': status.get('id'),
                            'error': str(e),
                            'requestId': request_id
                        }))
                
                # Process template status updates (APPROVED, REJECTED, PAUSED, etc.)
                field = change.get('field', '')
                if field == 'message_template_status_update':
                    try:
                        _process_template_status(value, request_id)
                    except Exception as e:
                        logger.error(json.dumps({
                            'event': 'template_status_processing_error',
                            'error': str(e),
                            'requestId': request_id
                        }))

                # Flow lifecycle and endpoint-health webhooks. The ingress has always forwarded
                # this field; until 2026-10-25 nothing here read it, so a BLOCKED Flow or a failing
                # endpoint was silent.
                if field == 'flows':
                    try:
                        _process_flow_event(value, request_id)
                    except Exception as e:
                        logger.error(json.dumps({
                            'event': 'flow_event_processing_error',
                            'error': type(e).__name__,
                            'requestId': request_id
                        }))
                
                # Process phone number quality updates
                if field == 'phone_number_quality_update':
                    try:
                        _process_phone_quality_update(value, request_id)
                    except Exception as e:
                        logger.error(json.dumps({
                            'event': 'phone_quality_processing_error',
                            'error': str(e),
                            'requestId': request_id
                        }))
                
                # Process account updates (messaging limits, etc.)
                if field == 'account_update':
                    try:
                        _process_account_update(value, request_id)
                    except Exception as e:
                        logger.error(json.dumps({
                            'event': 'account_update_processing_error',
                            'error': str(e),
                            'requestId': request_id
                        }))
                
                # Process BSUID changes (user_id_update)  -  separate webhook field
                if field == 'user_id_update':
                    _store_system_event('user_id_update', value, request_id)  # audit trail
                    for uid_update in value.get('user_id_update', []):
                        try:
                            _process_user_id_update(uid_update, contacts_map, request_id)
                        except Exception as e:
                            logger.error(json.dumps({
                                'event': 'user_id_update_error',
                                'error': str(e),
                                'requestId': request_id
                            }))
                
                # Process business_username_updates webhook (Meta field is plural;
                # accept singular too for forward/backward compatibility)
                if field in ('business_username_updates', 'business_username_update'):
                    try:
                        _process_business_username_update(value, request_id)
                    except Exception as e:
                        logger.error(json.dumps({
                            'event': 'business_username_updates_error',
                            'error': str(e),
                            'requestId': request_id
                        }))
                
                # Process user_preferences webhook (marketing message opt-in/out with BSUID)
                if field == 'user_preferences':
                    try:
                        _store_system_event('user_preferences', value, request_id)
                        # Also enrich contact BSUID from user_preferences contacts array
                        for pref in value.get('user_preferences', []):
                            pref_bsuid = pref.get('user_id', '')
                            pref_phone = pref.get('wa_id', '')
                            if pref_bsuid and pref_phone:
                                try:
                                    contact = _get_contact_by_phone(pref_phone)
                                    if contact:
                                        ct = dynamodb.Table(CONTACTS_TABLE)
                                        _update_contact_bsuid_fields(ct, contact, '', '', phone=pref_phone, bsuid=pref_bsuid)
                                except Exception as e:
                                    logger.warning(json.dumps({
                                        'event': 'bsuid_enrichment_failed',
                                        'phone': mask_phone(pref_phone),
                                        'error': type(e).__name__}))
                    except Exception as e:
                        logger.error(json.dumps({
                            'event': 'user_preferences_error',
                            'error': str(e),
                            'requestId': request_id
                        }))
                
                # Process group webhook events (group_participant_change, group_membership_approval_request)
                if field == 'group_participant_change':
                    try:
                        _store_system_event('group_participant_change', value, request_id)
                        _process_group_event(value, 'participant_change', request_id)
                    except Exception as e:
                        logger.error(json.dumps({
                            'event': 'group_participant_change_error',
                            'error': str(e),
                            'requestId': request_id
                        }))
                
                if field == 'group_membership_approval_request':
                    try:
                        _store_system_event('group_membership_approval_request', value, request_id)
                        _process_group_event(value, 'membership_approval', request_id)
                    except Exception as e:
                        logger.error(json.dumps({
                            'event': 'group_membership_approval_error',
                            'error': str(e),
                            'requestId': request_id
                        }))
                
                if field == 'group_lifecycle_update':
                    try:
                        _store_system_event('group_lifecycle_update', value, request_id)
                        _process_group_event(value, 'lifecycle', request_id)
                    except Exception as e:
                        logger.error(json.dumps({
                            'event': 'group_lifecycle_update_error',
                            'error': str(e),
                            'requestId': request_id
                        }))
                
                if field == 'group_settings_update':
                    try:
                        _store_system_event('group_settings_update', value, request_id)
                        _process_group_event(value, 'settings_update', request_id)
                    except Exception as e:
                        logger.error(json.dumps({
                            'event': 'group_settings_update_error',
                            'error': str(e),
                            'requestId': request_id
                        }))
                
                # ── Coexistence (WhatsApp Business app on a Cloud API number) ──
                # Audited and counted, never acted on — see `_process_coexistence_event`.
                # NO `continue` here, matching the four group arms above: they are
                # sequential `if field == '...'` blocks that fall through to the
                # `_SYSTEM_EVENT_FIELDS` membership test below. Falling through is safe
                # because neither coexistence field is in that set, so the fall-through
                # reaches no second handler.
                if field in _COEXISTENCE_FIELDS:
                    try:
                        _process_coexistence_event(field, value, request_id)
                    except Exception as e:
                        logger.error(json.dumps({
                            'event': 'coexistence_event_error',
                            'field': field,
                            'error': type(e).__name__,
                            'requestId': request_id
                        }))

                # ── Additional Meta webhook fields (per official docs) ──
                # These are informational/system-level events that we log to SystemEvent
                # for audit trail and operational awareness.
                # Ref: https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks/components
                if field == 'history':
                    try:
                        _process_history_event(
                            value, request_id,
                            meta_waba_ids[0] if meta_waba_ids else '')
                    except Exception as e:
                        logger.error(json.dumps({
                            'event': 'webhook_history_error',
                            'error': type(e).__name__,
                            'requestId': request_id,
                        }))

                if field == 'partner_solutions':
                    try:
                        _process_partner_solution_event(
                            value, request_id,
                            meta_waba_ids[0] if meta_waba_ids else '')
                    except Exception as e:
                        logger.error(json.dumps({
                            'event': 'webhook_partner_solutions_error',
                            'error': type(e).__name__,
                            'requestId': request_id,
                        }))

                _SYSTEM_EVENT_FIELDS = {
                    'account_alerts', 'account_review_update',
                    'automatic_events',
                    'business_capability_update', 'business_status_update',
                    'message_template_components_update',
                    'message_template_quality_update',
                    'payment_configuration_update',
                    'phone_number_name_update', 'security',
                    'template_category_update',
                    'tracking_events',
                }
                if field in _SYSTEM_EVENT_FIELDS:
                    try:
                        phone_id = str((value.get('metadata') or {}).get('phone_number_id') or '')
                        _record_meta_system_event(
                            field, value, request_id,
                            meta_waba_ids[0] if meta_waba_ids else '',
                            phone_id)
                        logger.info(json.dumps({
                            'event': f'webhook_{field}_stored',
                            'field': field,
                            'requestId': request_id,
                        }))
                    except Exception as e:
                        logger.error(json.dumps({
                            'event': f'webhook_{field}_error',
                            'error': type(e).__name__,
                            'requestId': request_id,
                        }))
                        
        except Exception as e:
            logger.error(json.dumps({
                'event': 'record_processing_error',
                'error': str(e),
                'shape': _item.get('shape'),
                'requestId': request_id
            }))
            # DLQ the normalized work item, not the raw envelope. dlq-replay
            # invokes the stored payload directly, and wa_internal_event.parse
            # accepts this shape, so a replay now actually reproduces the work -
            # which it could not do when the stored record was half of an SNS
            # envelope the worker no longer looked at.
            _send_to_dlq(
                wa_internal_event.build(
                    entry=_item.get('entry') or {},
                    waba_id=_item.get('waba_id') or '',
                    meta_phone_number_ids=_item.get('phone_number_ids') or [],
                    request_id=request_id,
                ),
                str(e), request_id,
            )
            error_count += 1
    
    logger.info(json.dumps({
        'event': 'inbound_processing_complete',
        'processedCount': processed_count,
        'errorCount': error_count,
        'requestId': request_id
    }))
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'processed': processed_count,
            'errors': error_count
        })
    }


def _get_aws_phone_number_id(display_phone: str, meta_phone_id: str,
                             entry_phone_ids: Optional[list] = None) -> str:
    """
    Map display phone number or Meta phone ID to phone number ID.
    Returns the appropriate AWS phone number ID for sending reactions.
    For Direct API phones, returns a synthetic ID for tracking purposes.
    `entry_phone_ids` is the webhook entry's own phone-id list, used when
    `value.metadata` is absent.
    """
    # Clean display phone number (remove + and spaces)
    clean_phone = display_phone.replace('+', '').replace(' ', '').replace('-', '')
    
    # Check if we have a mapping for this phone number
    if clean_phone in PHONE_NUMBER_MAP:
        return PHONE_NUMBER_MAP[clean_phone]
    
    # Check Meta phone number ID mapping (for Direct API WABAs)
    if meta_phone_id in META_PHONE_ID_MAP:
        return META_PHONE_ID_MAP[meta_phone_id]

    # The entry names the phone even when `value.metadata` does not. Prefer a real
    # id over a default; only then fall back.
    for pid in (entry_phone_ids or []):
        if pid in META_PHONE_ID_MAP:
            return META_PHONE_ID_MAP[pid]

    # Default to first phone number ID if no mapping found
    logger.warning(json.dumps({
        'event': 'phone_number_mapping_not_found',
        'displayPhone': mask_phone(display_phone),
        'metaPhoneId': meta_phone_id,
        'usingDefault': PHONE_NUMBER_ID_1
    }))
    return PHONE_NUMBER_ID_1


def _epoch_or_zero(value) -> int:
    """Read a stored `timestamp` as epoch seconds, scoring anything unreadable as 0.

    build_message_item in lambda_utils/message_store.py writes Decimal epoch seconds
    (message_store.py:88), but the unified Message model DECLARES `timestamp: a.datetime()`
    (amplify/data/resource.ts:161) — an ISO-8601 string. DynamoDB is schemaless, so both
    shapes can coexist in one table and any producer or backfill honouring the declared
    model type puts a string there. A bare int() on one such row raises ValueError inside
    a list comprehension, which would break _apply_revoke's "never raises" contract and
    surface as `revoke_apply_error` — indistinguishable in the logs from "no candidate".

    Scoring 0 puts the row OUTSIDE the window rather than throwing, so one malformed row
    costs that row and not the whole resolution.
    """
    try:
        return int(Decimal(str(value)))
    except (TypeError, ValueError, ArithmeticError):
        return 0


def _apply_revoke(message: Dict, contact_id: str, revoke_message_id: str,
                  revoke_wamid: str, sender_phone: str, timestamp: int,
                  request_id: str) -> None:
    """Mark the inbound message a revoke deleted. Audit-only on failure; never raises.

    Resolution is two-tier, and BOTH tiers resolve against the unified MessagesTable so
    they can only ever produce the same primary key:
      exact    -- Meta supplied the revoked message's wamid; resolve it through
                  UNIFIED_MESSAGES_TABLE's whatsappMessageId-index, the same lookup
                  shape _process_status uses.
      inferred -- no id available, so take the single most recent inbound WhatsApp
                  message from this contact that is older than the revoke and inside
                  REVOKE_CORRELATION_WINDOW_SECONDS. EXACTLY ONE candidate, or nothing
                  is marked.

    `sender_phone` is used only in the declined-resolution log line, masked, so a
    decline is traceable to a conversation. The inferred tier keys on `contact_id`,
    which is what contactId-index is built on.

    The original content is NOT deleted or redacted — the row is the provenance record
    for a conversation, and `isRevoked` is what the inbox renders. Deleting it would
    destroy an audit trail to satisfy a presentation concern.
    """
    # Step 1 — read whatever id the payload might carry.
    target_wamid = ''
    rv = message.get('revoke')
    for src in (rv if isinstance(rv, dict) else {}, message.get('context') or {}, message):
        for k in _REVOKE_TARGET_ID_KEYS:
            cand = str((src or {}).get(k) or '')
            if cand and cand != revoke_wamid:
                target_wamid = cand
                break
        if target_wamid:
            break

    target_id = ''
    resolution = ''

    if target_wamid:
        # Exact tier. The UNIFIED table, deliberately: the inferred tier reads it and
        # messages-read serves it to the inbox, so both tiers must key on the same
        # store or the same revoke would mark different rows depending on which tier
        # fired. Index: amplify/data/resource.ts:184.
        try:
            resp = dynamodb.Table(UNIFIED_MESSAGES_TABLE).query(
                IndexName='whatsappMessageId-index',
                KeyConditionExpression='whatsappMessageId = :w',
                ExpressionAttributeValues={':w': target_wamid}, Limit=1)
            items = resp.get('Items') or []
        except Exception as e:  # noqa: BLE001 — degrade, never fail the revoke
            # A missing or not-yet-active index degrades to the inferred tier rather
            # than failing the revoke. No scan fallback: _process_status has one for a
            # path that must not lose a delivery receipt, whereas a revoke that cannot
            # be resolved is already a defined outcome here.
            logger.warning(json.dumps({'event': 'revoke_exact_lookup_failed',
                                       'error': type(e).__name__,
                                       'requestId': request_id}))
            items = []
        if items:
            target_id = str(items[0].get('id') or items[0].get('messageId') or '')
            resolution = 'exact'

    if not target_id:
        # Inferred tier. It also runs when an exact id matched nothing, so a supplied
        # id that resolves to no row FALLS THROUGH rather than declining.
        #
        # query_by_contact reads the UNIFIED MessagesTable on its default —
        # message_store's own module-level MESSAGES_TABLE is
        # os.environ['UNIFIED_MESSAGES_TABLE'] (message_store.py:40), which is the
        # OPPOSITE of this handler's MESSAGES_TABLE (the inbound table). No
        # table_name is passed, deliberately: the default is the table both tiers and
        # the inbox agree on, and "clarifying" it later by passing MESSAGES_TABLE
        # through reads like a tightening and is the bug.
        #
        # Then filter in memory: contactId-index returns index order, NOT
        # newest-first, and carries no sort-key condition, so element 0 is not the
        # most recent and the window predicate does the selection.
        candidates = [
            m for m in query_by_contact(contact_id, limit=50)
            if str(m.get('channel', '')) == 'whatsapp'
            and str(m.get('direction', '')) == 'inbound'
            and not m.get('isRevoked')
            and not m.get('paymentReferenceId')      # a payment row is never a revoke target
            and str(m.get('messageType', '')) not in ('revoke', 'edit')
            and str(m.get('whatsappMessageId', '')) != revoke_wamid
            and 0 < (timestamp - _epoch_or_zero(m.get('timestamp')))
                  <= REVOKE_CORRELATION_WINDOW_SECONDS
        ]
        if len(candidates) == 1:
            target_id = str(candidates[0].get('id') or candidates[0].get('messageId') or '')
            resolution = 'inferred'
        if not target_id:
            # Two candidates means we do not know which was deleted, and marking the
            # newer one would be a coin flip presented as an answer. `hadExactId` is
            # what distinguishes "no id" from "id that matched nothing".
            logger.info(json.dumps({
                'event': 'revoke_target_unresolved',
                'candidateCount': len(candidates),
                'reason': 'no_candidate' if not candidates else 'ambiguous',
                'hadExactId': bool(target_wamid),
                # mask_contact_id, not the raw value: a WhatsApp contactId is `wa` plus
                # the customer's E.164 digits (privacy.py), so logging it whole is a
                # disclosure. It passes a uuid-form contactId through untouched, so the
                # correlation key survives where it discloses nothing.
                'contactId': mask_contact_id(contact_id),
                'senderPhone': mask_phone(sender_phone),
                'requestId': request_id}))
            return

    update_expr = ('SET isRevoked = :t, revokedAt = :ts, '
                   'revokedByWhatsappMessageId = :rw, revokeResolution = :res')
    values = {':t': True, ':ts': Decimal(str(timestamp)),
              ':rw': revoke_wamid, ':res': resolution}
    # dict.fromkeys de-duplicates while preserving order: if the two env vars are ever
    # pointed at one table, writing twice would make the second write fail its own
    # attribute_not_exists(isRevoked) condition against the write the loop just made.
    # _process_status:3594 guards the same hazard with an explicit table comparison.
    for table_name in dict.fromkeys((MESSAGES_TABLE, UNIFIED_MESSAGES_TABLE)):
        try:
            dynamodb.Table(table_name).update_item(
                Key={'id': target_id}, UpdateExpression=update_expr,
                ConditionExpression='attribute_exists(id) AND attribute_not_exists(isRevoked)',
                ExpressionAttributeValues=values)
        except ClientError as ce:
            if ce.response.get('Error', {}).get('Code') != 'ConditionalCheckFailedException':
                raise
            # A redelivered revoke, or a row this table does not hold. Not an error:
            # the guard did its job.
            logger.info(json.dumps({'event': 'revoke_already_applied',
                                    'messageId': target_id, 'table': table_name,
                                    'requestId': request_id}))
        except Exception as e:  # noqa: BLE001 — audit-only
            logger.warning(json.dumps({'event': 'revoke_mark_failed',
                                       'table': table_name, 'error': type(e).__name__,
                                       'requestId': request_id}))

    # Back-link the revoke's own row, so the relationship is navigable from either end.
    # BOTH tables, not just MESSAGES_TABLE: the inbox reads the unified MessagesTable and
    # only that (messages-read/handler.py:44-45), so a back-link written only to
    # WhatsAppInboundTable could never reach the frontend and the revoke bubble would
    # never stop rendering — the exact double render this exists to remove.
    #
    # `attribute_exists(id)` ONLY, with no attribute_not_exists: unlike the target mark a
    # back-link is idempotent, so a redelivered revoke rewriting the same two values is
    # harmless and must not log a spurious conditional failure.
    for table_name in dict.fromkeys((MESSAGES_TABLE, UNIFIED_MESSAGES_TABLE)):
        try:
            dynamodb.Table(table_name).update_item(
                Key={'id': revoke_message_id},
                UpdateExpression='SET revokesMessageId = :t, revokeResolution = :res',
                ConditionExpression='attribute_exists(id)',
                ExpressionAttributeValues={':t': target_id, ':res': resolution})
        except ClientError as ce:
            # The revoke row is missing from this table — the mirror must not create
            # one. Same reading as the target write: the condition did its job.
            if ce.response.get('Error', {}).get('Code') != 'ConditionalCheckFailedException':
                raise
        except Exception as e:  # noqa: BLE001 — audit-only
            logger.warning(json.dumps({'event': 'revoke_backlink_failed',
                                       'table': table_name, 'error': type(e).__name__,
                                       'requestId': request_id}))


def _process_message(
    message: Dict,
    metadata: Dict,
    request_id: str,
    receiving_phone: str,
    aws_phone_number_id: str,
    meta_waba_ids: list,
    sender_profile_name: str = '',
    sender_bsuid: str = '',
    sender_parent_bsuid: str = '',
    sender_username: str = '',
    sender_contact_book_name: str = '',
    standby_sourced: bool = False,
) -> None:
    """
    Process a single inbound message.
    Stores which WABA/phone number received the message.
    Supports BSUID (Business-Scoped User ID), parent BSUID, and username from webhook.

    `standby_sourced` marks a message that arrived as a **standby copy** rather than on
    the normal `messages` field, i.e. one another responder owns the thread for. It only
    has an effect when `STANDBY_REPLY_ENABLED` is false; with the shipped `true` default
    `_may_send` short-circuits and every guard below is a no-op.
    """
    whatsapp_message_id = message.get('id')
    sender_phone = message.get('from', '')
    # BSUID: from_user_id in message takes precedence over contacts array
    msg_bsuid = message.get('from_user_id', '') or sender_bsuid
    # Parent BSUID: from_parent_user_id in message takes precedence over contacts array
    msg_parent_bsuid = message.get('from_parent_user_id', '') or sender_parent_bsuid
    msg_type = message.get('type', 'text')
    timestamp = int(message.get('timestamp', time.time()))

    # Reset the send context for THIS message. Unconditional, before anything can send:
    # a `standby` flag leaking from a previous message in the same invocation is the one
    # way `_may_send` can misfire, and the handler processes messages serially.
    global _send_context
    _send_context = {
        'standby': bool(standby_sourced),
        'phone_number_id': str((metadata or {}).get('phone_number_id') or ''),
        'bsuid': msg_bsuid,
        'wa_id': sender_phone,
    }
    
    # ── Detect real content type for "unsupported" messages ──
    # Meta marks many messages as 'unsupported' but they still carry media/text
    # data. Detect the actual type so the inbox can render them properly.
    if msg_type == 'unsupported':
        # Meta names the real type in `unsupported.type` / `unsupported.raw_type`.
        # Reading it is what makes the `revoke` and `edit` extractors reachable at
        # all; before this they were dispatch-table entries nothing could ever hit.
        # Membership is tested against KNOWN_TYPES (the dispatch table itself) rather
        # than a second hand-copied list. `unknown` is not in it, so the measured
        # 125-of-128 case falls through to extract_unsupported_content unchanged.
        # A revoke stores its own row AND marks the message it deleted — see
        # `_apply_revoke`, called from the bottom of this function. The measured payload
        # carries no `context` key, so there is no `context.id` to join on; resolution is
        # therefore two-tier (an exact wamid when Meta ever supplies one, else a
        # single-candidate recency inference inside REVOKE_CORRELATION_WINDOW_SECONDS)
        # and it is allowed to decline. Nothing is deleted or redacted.
        _u = message.get('unsupported')
        if not isinstance(_u, dict):
            _u = {}
        _recovered = _u.get('type') or _u.get('raw_type')
        if _recovered and _recovered != 'unsupported' and _recovered in _KNOWN_TYPES:
            msg_type = _recovered
            logger.info(json.dumps({
                'event': 'unsupported_type_recovered',
                'source': 'unsupported.type',
                'recoveredType': _recovered,
                'whatsappMessageId': whatsapp_message_id,
                'requestId': request_id
            }))
        # The media five are the only types this probe can ever match: the guard
        # below needs a dict carrying an `id`, and `contacts` is a list while
        # `location`/`reaction`/`poll` carry no id. They were listed anyway, which
        # read as coverage that did not exist.
        for probe_type in ('image', 'video', 'audio', 'document', 'sticker'):
            if msg_type != 'unsupported':
                break
            probe_data = message.get(probe_type)
            if isinstance(probe_data, dict) and probe_data.get('id'):
                # Has a media ID  -  this is a real media message wrapped as unsupported
                # (common for view-once, multi-image bundles)
                msg_type = probe_type
                logger.info(json.dumps({
                    'event': 'unsupported_type_recovered',
                    'recoveredType': probe_type,
                    'whatsappMessageId': whatsapp_message_id,
                    'requestId': request_id
                }))
                break
        # Check for text body in unsupported wrapper
        if msg_type == 'unsupported':
            text_data = message.get('text', {})
            if isinstance(text_data, dict) and text_data.get('body'):
                msg_type = 'text'
                logger.info(json.dumps({
                    'event': 'unsupported_type_recovered',
                    'recoveredType': 'text',
                    'whatsappMessageId': whatsapp_message_id,
                    'requestId': request_id
                }))
    
    # Log full message for unsupported or unrecognized types to help debug
    if msg_type in ('unsupported', 'unknown') or msg_type not in (
        'text', 'image', 'video', 'audio', 'document', 'sticker',
        'location', 'contacts', 'reaction', 'interactive', 'button',
        'order', 'system', 'request_welcome', 'ephemeral',
        'referral', 'ad_click', 'product', 'product_inquiry', 'poll',
        'edit', 'revoke',
    ):
        logger.warning(json.dumps({
            'event': 'unsupported_or_new_message_type',
            'senderPhone': mask_phone(sender_phone),
            'whatsappMessageId': whatsapp_message_id,
            'messageType': msg_type,
            'messageKeys': list(message.keys()),
            'fullMessage': message,
            'requestId': request_id
        }))
    
    # Use sender profile name from contacts array (passed in)
    # Fall back to checking message.profile if not provided
    sender_name = sender_profile_name
    if not sender_name and 'profile' in message:
        sender_name = message.get('profile', {}).get('name', '')
    
    # Save endpointless Flow business records before inbox dedup. A retry must repair a
    # failed contact/activity projection even when the transport message already exists.
    _referral_data = referral_response.referral_payload(message)
    _referral_contact = None
    _referral_result = None
    if _referral_data is not None:
        _referral_contact = _get_or_create_contact(
            sender_phone, sender_name, bsuid=msg_bsuid, username=sender_username,
            contact_book_name=sender_contact_book_name, parent_bsuid=msg_parent_bsuid)
        _referral_result = referral_response.save_referral(
            _referral_data,
            contact_id=_referral_contact.get('contactId') or _referral_contact.get('id'),
            phone=sender_phone, sender_name=sender_name,
            message_id=whatsapp_message_id, request_id=request_id,
            customer_uuid_value=str(_referral_contact.get('customerUuid') or ''))

    _idea_data = customer_ideas.idea_payload(message)
    _idea_contact = None
    _idea_result = None
    if _idea_data is not None:
        _idea_contact = _get_or_create_contact(
            sender_phone, sender_name, bsuid=msg_bsuid, username=sender_username,
            contact_book_name=sender_contact_book_name, parent_bsuid=msg_parent_bsuid)
        _idea_result = customer_ideas.save_idea(
            _idea_data, contact_id=_idea_contact.get('contactId') or _idea_contact.get('id'),
            phone=sender_phone, sender_name=sender_name,
            message_id=whatsapp_message_id, dynamodb=dynamodb,
            request_id=request_id,
            customer_uuid_value=str(_idea_contact.get('customerUuid') or ''))

    _track_shipping_data = track_shipping_response.tracking_payload(message)
    _track_shipping_contact = None
    _track_shipping_result = None
    if _track_shipping_data is not None:
        _track_shipping_contact = _get_or_create_contact(
            sender_phone, sender_name, bsuid=msg_bsuid, username=sender_username,
            contact_book_name=sender_contact_book_name, parent_bsuid=msg_parent_bsuid)
        _track_shipping_result = track_shipping_response.save_tracking(
            _track_shipping_data,
            contact_id=_track_shipping_contact.get('contactId')
                or _track_shipping_contact.get('id'),
            phone=sender_phone, sender_name=sender_name,
            message_id=whatsapp_message_id, dynamodb=dynamodb,
            request_id=request_id)

    # Pickup has its own service code and paid-order contract. Parse before the
    # F004 Submit Request fallback so a cloned marker can never be filed as SR.
    _pickup_data = pickup_request_response.pickup_payload(message)
    _pickup_contact = None
    _pickup_result = None
    if _pickup_data is not None:
        _pickup_contact = _get_or_create_contact(
            sender_phone, sender_name, bsuid=msg_bsuid, username=sender_username,
            contact_book_name=sender_contact_book_name, parent_bsuid=msg_parent_bsuid)
        _pickup_result = pickup_request_response.save_pickup(
            _pickup_data,
            contact_id=_pickup_contact.get('contactId') or _pickup_contact.get('id'),
            phone=sender_phone, sender_name=sender_name,
            message_id=whatsapp_message_id, dynamodb=dynamodb,
            request_id=request_id)

    _submit_request_data = submit_request_response.request_payload(message)
    _submit_request_contact = None
    _submit_request_result = None
    if _submit_request_data is not None:
        _submit_request_contact = _get_or_create_contact(
            sender_phone, sender_name, bsuid=msg_bsuid, username=sender_username,
            contact_book_name=sender_contact_book_name, parent_bsuid=msg_parent_bsuid)
        _submit_request_result = submit_request_response.save_request(
            _submit_request_data,
            contact_id=_submit_request_contact.get('contactId') or _submit_request_contact.get('id'),
            phone=sender_phone, sender_name=sender_name,
            message_id=whatsapp_message_id, dynamodb=dynamodb,
            request_id=request_id)

    _request_amendment_data = request_amendment_response.amendment_payload(message)
    _request_amendment_contact = None
    _request_amendment_result = None
    if _request_amendment_data is not None:
        _request_amendment_contact = _get_or_create_contact(
            sender_phone, sender_name, bsuid=msg_bsuid, username=sender_username,
            contact_book_name=sender_contact_book_name, parent_bsuid=msg_parent_bsuid)
        _request_amendment_result = request_amendment_response.save_amendment(
            _request_amendment_data,
            contact_id=_request_amendment_contact.get('contactId')
                or _request_amendment_contact.get('id'),
            phone=sender_phone, sender_name=sender_name,
            message_id=whatsapp_message_id, dynamodb=dynamodb,
            request_id=request_id)

    # Deduplicate using whatsappMessageId.
    # claim_event() is an atomic, strongly-consistent guard that closes the
    # fast-redelivery race window (Meta redelivering within the GSI's eventual-
    # consistency lag). _message_exists() is kept as a fallback so redeliveries
    # older than the dedup table's TTL are still caught. Either signalling a
    # duplicate skips processing.
    _dup = False
    try:
        from lambda_utils.webhook_dedup import claim_event
        if whatsapp_message_id and not claim_event(whatsapp_message_id, source='whatsapp_inbound'):
            _dup = True
    except Exception:  # noqa: BLE001 — dedup must never block a real inbound message
        pass
    if _dup or _message_exists(whatsapp_message_id):
        logger.info(json.dumps({
            'event': 'message_duplicate_skipped',
            'whatsappMessageId': whatsapp_message_id,
            'requestId': request_id
        }))
        return
    
    # Lookup or create contact with sender name, BSUID, parent BSUID, and username
    contact = (_referral_contact or _idea_contact or _track_shipping_contact or _pickup_contact
               or _submit_request_contact or _request_amendment_contact
               or _get_or_create_contact(sender_phone, sender_name, bsuid=msg_bsuid,
                                         username=sender_username,
                                         contact_book_name=sender_contact_book_name,
                                         parent_bsuid=msg_parent_bsuid))
    contact_id = contact.get('contactId') or contact.get('id')
    
    # Extract message content based on type.
    # Leave Review is stored as ONE structured Inbox item, not the old truncated raw
    # `[Flow Response: {...}]` transport preview. The FlowSubmission row remains the
    # durable business record; these fields are the Inbox projection of that same row.
    content = _extract_content(message, msg_type)
    _referral_inbox = None
    if _referral_data is not None and _referral_result is not None:
        _referral_form = referral_response.clean_referral(_referral_data)
        _referral_inbox = {
            'flowId': referral_response.FLOW_ID,
            'flowCode': referral_response.FLOW_CODE,
            'flowType': 'referral',
            'flowScreen': 'CONFIRMATION',
            'flowSubmissionId': _referral_result.submission_id,
            'flowReference': _referral_result.reference,
            'flowAnswers': referral_response.response_answers(_referral_form),
            'flowAttachments': [],
        }
        msg_type = 'flow_response'
        content = 'Flow response — Referral'

    _idea_inbox = None
    if _idea_data is not None and _idea_result is not None:
        _topic = str(_idea_data.get('topic') or 'other')
        _idea_inbox = {
            'flowCode': customer_ideas.FLOW_CODE,
            'flowType': 'customer_idea',
            'flowScreen': 'REVIEW',
            'flowSubmissionId': _idea_result.submission_id,
            'flowReference': _idea_result.reference,
            'flowAnswers': customer_ideas.response_answers(_idea_data),
            'flowAttachments': [],
            'reviewId': _idea_result.submission_id,
            'reviewStatus': 'pending',
            'reviewCategory': _topic,
        }
        msg_type = 'flow_response'
        content = 'Flow response — Customer Idea'

    _track_shipping_inbox = None
    if _track_shipping_data is not None and _track_shipping_result is not None:
        _track_shipping_item = _track_shipping_result.item or {}
        _track_shipping_inbox = {
            'flowCode': track_shipping_response.FLOW_CODE,
            'flowType': 'form_submit',
            'flowScreen': 'CONFIRMATION',
            'flowSubmissionId': _track_shipping_result.submission_id,
            'flowReference': _track_shipping_result.reference,
            'flowAnswers': track_shipping_response.response_answers(
                _track_shipping_data, _track_shipping_result),
            'flowAttachments': [],
            'trackingRequestId': _track_shipping_result.submission_id,
            'trackingRequestStatus': _track_shipping_item.get('status', 'open'),
        }
        msg_type = 'flow_response'
        content = 'Flow response — Track Shipping'

    _pickup_inbox = None
    if _pickup_data is not None and _pickup_result is not None:
        _pickup_item = _pickup_result.item or {}
        _pickup_inbox = {
            'flowCode': pickup_request_response.FLOW_CODE,
            'flowType': 'pickup_request',
            'flowScreen': 'CONFIRMATION',
            'flowSubmissionId': _pickup_result.submission_id,
            'flowReference': _pickup_result.reference,
            'flowAnswers': pickup_request_response.response_answers(
                _pickup_data, _pickup_result),
            'flowAttachments': [],
            'pickupRequestId': _pickup_result.submission_id,
            'pickupRequestStatus': _pickup_item.get('status', 'pending_confirmation'),
        }
        msg_type = 'flow_response'
        content = 'Flow response — Pickup Request'

    _submit_request_inbox = None
    if _submit_request_data is not None and _submit_request_result is not None:
        _submit_request_inbox = {
            'flowCode': submit_request_response.FLOW_CODE,
            'flowType': 'form_submit',
            'flowScreen': 'CONFIRMATION',
            'flowSubmissionId': _submit_request_result.submission_id,
            'flowReference': _submit_request_result.reference,
            'flowAnswers': submit_request_response.response_answers(
                _submit_request_data, _submit_request_result),
            'flowAttachments': [],
            'serviceRequestId': _submit_request_result.submission_id,
            'serviceRequestStatus': _submit_request_result.item.get('status', 'open')
                if _submit_request_result.item else 'open',
        }
        msg_type = 'flow_response'
        content = 'Flow response — Submit Request'

    _request_amendment_inbox = None
    if _request_amendment_data is not None and _request_amendment_result is not None:
        _amendment_item = _request_amendment_result.item or {}
        _request_amendment_inbox = {
            'flowCode': request_amendment_response.FLOW_CODE,
            'flowType': 'amendment',
            'flowScreen': 'CONFIRMATION',
            'flowSubmissionId': _request_amendment_result.submission_id,
            'flowReference': _request_amendment_result.reference,
            'flowAnswers': request_amendment_response.response_answers(
                _request_amendment_data, _request_amendment_result),
            'flowAttachments': [],
            # Keep the service context on the original request when ownership verification
            # succeeded; the amendment itself remains addressable via flowSubmissionId.
            'serviceRequestId': (
                _amendment_item.get('parentSubmissionId')
                or _request_amendment_result.submission_id),
            'serviceRequestStatus': _amendment_item.get(
                'status', 'awaiting_order_verification'),
        }
        msg_type = 'flow_response'
        content = 'Flow response — Request Amendment'

    # A shared contact card carried a name and a number that the old extractor threw
    # away, leaving an agent to ask the customer to retype it. Keep the sanitised
    # payload so the inbox can render a real card. Guarded: a malformed vCard must
    # cost the card, never the message. Never log the payload itself — it holds a
    # third party's phone number.
    _contacts_payload = None
    if msg_type == 'contacts' or message.get('contacts'):
        try:
            _contacts_payload = _extract_contacts_payload(message)
        except Exception as _ce:  # noqa: BLE001
            logger.warning(json.dumps({
                'event': 'contacts_payload_extract_failed',
                'error': type(_ce).__name__,
                'whatsappMessageId': whatsapp_message_id,
                'requestId': request_id
            }))
    
    # Generate message ID and calculate TTL
    message_id = str(uuid.uuid4())
    now = int(time.time())
    expires_at = now + MESSAGE_TTL_SECONDS
    
    # Handle media messages (including stickers)
    # All phones use Direct API
    media_id = None
    s3_key = None
    if msg_type in ['image', 'video', 'audio', 'document', 'sticker']:
        media_data = message.get(msg_type, {})
        whatsapp_media_id = media_data.get('id')
        mime_type_hint = media_data.get('mime_type', '')
        if whatsapp_media_id:
            if _is_direct_api_phone(aws_phone_number_id):
                s3_key = _download_media_direct_api(
                    whatsapp_media_id, message_id, msg_type,
                    phone_number_id=aws_phone_number_id,
                    request_id=request_id,
                    mime_type_hint=mime_type_hint,
                )
            else:
                s3_key = _download_media(whatsapp_media_id, message_id, msg_type, aws_phone_number_id, request_id, mime_type_hint)
            if s3_key:
                media_id = _store_media_record(message_id, s3_key, media_data, whatsapp_media_id)
                # Ordinary Inbox media stays in the conversation. Only an explicit,
                # recent Drop Docs request may bind this media into DocumentTable.
                if msg_type in ('document', 'image'):
                    _attach_whatsapp_document_to_pending_dropdocs(
                        sender_phone, sender_name, contact_id, message_id,
                        whatsapp_media_id, s3_key, msg_type,
                        media_data.get('mime_type', ''),
                        media_data.get('filename', ''),
                        media_data.get('file_size', 0),
                        request_id,
                    )
                # Attach media to the customer's OPEN service request (photos/files
                # sent after the flow are saved under the request's folder + linked).
                try:
                    _link_media_to_service_request(contact_id, s3_key, msg_type,
                                                   media_data.get('filename', ''),
                                                   media_data.get('mime_type', ''), request_id)
                except Exception as _le:
                    logger.warning(json.dumps({'event': 'attach_link_error', 'error': str(_le), 'requestId': request_id}))
    
    # Ephemeral messages may carry media nested inside  -  try to extract
    if msg_type == 'ephemeral' and not s3_key:
        ephemeral_data = message.get('ephemeral', {})
        if isinstance(ephemeral_data, dict):
            for etype in ('image', 'video', 'audio', 'document', 'sticker'):
                edata = ephemeral_data.get(etype, {})
                if isinstance(edata, dict) and edata.get('id'):
                    mime_hint = edata.get('mime_type', '')
                    if _is_direct_api_phone(aws_phone_number_id):
                        s3_key = _download_media_direct_api(
                            edata['id'], message_id, etype,
                            phone_number_id=aws_phone_number_id,
                            request_id=request_id,
                            mime_type_hint=mime_hint,
                        )
                    else:
                        s3_key = _download_media(edata['id'], message_id, etype, aws_phone_number_id, request_id, mime_hint)
                    if s3_key:
                        media_id = _store_media_record(message_id, s3_key, edata, edata['id'])
                    break
    
    # Store message in DynamoDB with WABA info and sender name
    message_record = {
        'id': message_id,
        'messageId': message_id,
        'contactId': contact_id,
        'channel': 'whatsapp',
        'direction': 'inbound',
        'content': content,
        'messageType': msg_type,
        'timestamp': Decimal(str(timestamp)),
        'status': 'received',
        'whatsappMessageId': whatsapp_message_id,
        'mediaId': media_id,
        's3Key': s3_key,
        'senderPhone': sender_phone,
        'senderName': sender_name,  # Sender's WhatsApp profile name
        'senderBsuid': msg_bsuid or None,  # Sender's BSUID (Business-Scoped User ID)
        'senderParentBsuid': msg_parent_bsuid or None,  # Sender's parent BSUID (linked account)
        'senderUsername': sender_username or None,  # Sender's WhatsApp username
        # WABA tracking - which number received this message
        'receivingPhone': receiving_phone,
        'awsPhoneNumberId': aws_phone_number_id,
        'metaWabaIds': meta_waba_ids if meta_waba_ids else None,
        'createdAt': Decimal(str(now)),
        'expiresAt': Decimal(str(expires_at)),
        # None when this is not a contacts message; the put_item below filters
        # None values out, so no attribute is added.
        'contactsPayload': _contacts_payload,
    }
    if _referral_inbox:
        message_record.update(_referral_inbox)
    if _idea_inbox:
        message_record.update(_idea_inbox)
    if _track_shipping_inbox:
        message_record.update(_track_shipping_inbox)
    if _pickup_inbox:
        message_record.update(_pickup_inbox)
    if _submit_request_inbox:
        message_record.update(_submit_request_inbox)
    if _request_amendment_inbox:
        message_record.update(_request_amendment_inbox)
    
    # Keep the complete structured completion; a truncated transport label cannot
    # be reconstructed by the inbox. Both inbox stores must carry the same fields.
    from lambda_utils.flow_inbox import from_message as project_flow_message
    _flow_card = (
        project_flow_message(message)
        if (_referral_data is None and _idea_data is None and _track_shipping_data is None
            and _pickup_data is None and _submit_request_data is None
            and _request_amendment_data is None)
        else {})
    if _flow_card:
        message_record.update(_flow_card)
        content = _flow_card['content']

    # Capture referral context (click-to-WhatsApp ads, product catalogs, social posts)
    # Referral can be attached to ANY message type, not just 'referral' type
    referral = message.get('referral')
    if referral:
        message_record['referralSource'] = referral.get('source_type', '')
        message_record['referralSourceId'] = referral.get('source_id', '')
        message_record['referralSourceUrl'] = referral.get('source_url', '')
        message_record['referralHeadline'] = referral.get('headline', '')
        message_record['referralBody'] = referral.get('body', '')
        # Click-to-WhatsApp Click ID — required by the Conversions API to attribute
        # in-thread conversions (Purchase/Lead) back to the ad. Persist it against the
        # customer's phone so wecare-whatsapp-business-api can log events later.
        ctwa_clid = referral.get('ctwa_clid', '')
        if ctwa_clid:
            message_record['ctwaClid'] = ctwa_clid
            try:
                _digits = ''.join(ch for ch in sender_phone if ch.isdigit())
                _waba = meta_waba_ids[0] if meta_waba_ids else ''
                dynamodb.Table(SYSTEM_CONFIG_TABLE).put_item(Item={
                    'id': 'capi_clid_' + _digits,
                    'configValue': json.dumps({
                        'ctwaClid': ctwa_clid,
                        'phone': _digits,
                        'wabaId': _waba,
                        'sourceType': referral.get('source_type', ''),
                        'sourceId': referral.get('source_id', ''),
                        'headline': referral.get('headline', ''),
                        'ts': int(time.time()),
                    }),
                    'updatedAt': int(time.time()),
                })
            except Exception as _e:
                logger.warning(f'ctwa_clid capture failed (non-blocking): {_e}')
        logger.info(json.dumps({
            'event': 'referral_context',
            'senderPhone': mask_phone(sender_phone),
            'sourceType': referral.get('source_type', ''),
            'sourceUrl': referral.get('source_url', ''),
            'ctwaClid': bool(ctwa_clid),
            'requestId': request_id
        }))
        
        # The referral stays on the message record and the click id in `capi_clid_*` above. The
        # fire-and-forget invoke of `wecare-ad-attribution` that followed went with that function
        # (retired 2026-10-24, 8709d5fdd): every ad click posted the customer's number to a
        # function that no longer existed.
    
    # Capture message context (reply-to, forwarded)
    msg_context = message.get('context')
    if msg_context:
        message_record['replyToMessageId'] = msg_context.get('id', '')
        if msg_context.get('forwarded'):
            message_record['isForwarded'] = True
        if msg_context.get('frequently_forwarded'):
            message_record['isFrequentlyForwarded'] = True
        if msg_context.get('referred_product'):
            message_record['referredProduct'] = msg_context['referred_product']
    
    messages_table = dynamodb.Table(MESSAGES_TABLE)
    messages_table.put_item(Item={k: v for k, v in message_record.items() if v is not None})
    
    # Unified Inbox dual-write — mirror inbound WhatsApp to the canonical MessagesTable
    # (Phase 1). Same messageId as the WhatsApp inbound row, so messages-read dedups by
    # messageId. Guarded inside put_message — can never break inbound processing.
    _partner_waba = next((str(w) for w in (meta_waba_ids or []) if str(w) not in PLATFORM_WABAS), None)
    put_message(
        channel='whatsapp',
        direction='inbound',
        contact_id=contact_id,
        content=content,
        status='received',
        message_id=message_id,
        message_type=_flow_card.get('messageType', msg_type),
        whatsapp_message_id=whatsapp_message_id,
        media_id=media_id,
        s3_key=s3_key,
        sender_phone=sender_phone,
        sender_name=sender_name,
        receiving_phone=receiving_phone,
        aws_phone_number_id=aws_phone_number_id,
        partner_waba_id=_partner_waba,
        contacts_payload=_contacts_payload,
        **{k: v for k, v in _flow_card.items() if k not in ('content', 'messageType')},
        timestamp=timestamp,
        **(_referral_inbox or {}),
        **(_idea_inbox or {}),
        **(_track_shipping_inbox or {}),
        **(_pickup_inbox or {}),
        **(_submit_request_inbox or {}),
        **(_request_amendment_inbox or {}),
    )

    # ── A revoke marks the message it deleted ──
    # Runs AFTER both stores so the revoke's own row exists to be back-linked, and
    # guarded so resolution can never break inbound processing.
    if msg_type == 'revoke':
        try:
            _apply_revoke(message, contact_id, message_id, whatsapp_message_id,
                          sender_phone, timestamp, request_id)
        except Exception as e:
            logger.warning(json.dumps({'event': 'revoke_apply_error',
                                       'error': type(e).__name__, 'requestId': request_id}))

    # ── Thread ownership signal: we received this message ──
    # Meta's docs are explicit that RECEIVING is what claims a thread — "you do not have
    # to reply to claim the thread". So an arrival on the `messages` field (as opposed to
    # `standby`) is the strongest of the four signals.
    #
    # Placed AFTER both stores on purpose: an ownership-write failure must not be able to
    # cost us the message itself. WRITE AND LOG ONLY — nothing gates on this yet.
    try:
        _own_state = thread_ownership.record_signal(
            str((metadata or {}).get('phone_number_id') or ''),
            bsuid=msg_bsuid, wa_id=sender_phone,
            signal=thread_ownership.SIGNAL_MESSAGE_RECEIVED,
            detail=msg_type)
        logger.info(json.dumps({
            'event': 'thread_ownership_signal',
            'signal': thread_ownership.SIGNAL_MESSAGE_RECEIVED,
            'tracked': _own_state.get('tracked'),
            'owned': _own_state.get('owned'),
            'idle': _own_state.get('idle'),
            'bsuid': msg_bsuid,
            'waId': mask_phone(sender_phone or ''),
            'requestId': request_id,
        }))
    except Exception as _oe:
        logger.warning(json.dumps({'event': 'thread_ownership_signal_error',
                                   'error': type(_oe).__name__, 'requestId': request_id}))

    # Automation rules — auto-reply if an enabled rule matches (guarded, fire-and-forget
    # via async outbound invoke so it can never block/break inbound processing).
    try:
        if content and msg_type == 'text':
            _auto = evaluate_rules(content, 'whatsapp')
            # SEND #1. Skipping the block rather than returning, because a `return` here
            # would also skip everything after it and change today's flow.
            if _auto and _may_send('automation_auto_reply'):
                lambda_client.invoke(
                    FunctionName=os.environ.get('OUTBOUND_FUNCTION', OUTBOUND_WHATSAPP_FUNCTION),
                    InvocationType='Event',
                    Payload=json.dumps({
                        'requestContext': {'http': {'method': 'POST', 'path': '/whatsapp/send'}},
                        'body': json.dumps({'contactId': contact_id, 'content': _auto, 'phoneNumberId': aws_phone_number_id}),
                    }),
                )
                logger.info(json.dumps({'event': 'automation_auto_reply', 'contactId': mask_contact_id(contact_id), 'whatsappMessageId': whatsapp_message_id}))
    except Exception as _ae:
        logger.warning(f'automation auto-reply skipped: {_ae}')
    
    # call_permission_reply interactive messages are no longer processed.
    # Permission is auto-granted post-call in the whatsapp-calling handler.
    if msg_type == 'interactive':
        interactive = message.get('interactive', {})
        interactive_type = interactive.get('type', '')
        if interactive_type == 'call_permission_reply':
            logger.info(f"Ignoring call_permission_reply from {mask_phone(sender_phone or '')} — permission auto-granted post-call")
            return  # Discard — no longer forwarded or stored
        # Button reply. The IVR button menu and the follow-up button chooser are both
        # deleted, so there is no button id left to route - a tap on a button still
        # sitting in a customer's history opens the site menu rather than answering
        # with the degraded placeholder.
        elif interactive_type == 'button_reply':
            button_id = interactive.get('button_reply', {}).get('id', '')
            logger.info(json.dumps({
                'event': 'button_reply_received',
                'buttonId': button_id,
                'contactId': mask_contact_id(contact_id),
                'requestId': request_id,
            }))
            # SEND #2. The log above still fires either way, so a suppressed tap is
            # still visible in the record rather than vanishing.
            if _may_send('button_reply_menu'):
                _send_wd_main_menu(contact_id, sender_phone, aws_phone_number_id, request_id)
            return
        # List reply - a tapped row from the site menu, or a stale row from a deleted
        # menu still in chat history. Three ways out and no fourth: open the next
        # list, answer with the site link, or re-open the main menu. Nothing falls
        # through, nothing raises.
        elif interactive_type == 'list_reply':
            list_id = interactive.get('list_reply', {}).get('id', '')
            logger.info(json.dumps({
                'event': 'list_reply_received',
                'listId': list_id,
                'contactId': mask_contact_id(contact_id),
                'requestId': request_id,
            }))
            # SEND #3.
            # A list tap is a fresh signed inbound message. Stamp its WAMID before any
            # commerce action so the identity bridge can independently prove this exact action.
            _update_contact_timestamp(
                contact_id, now, wamid=whatsapp_message_id or '')
            if _may_send('list_reply_route'):
                _route_wd_list_reply(
                    list_id, contact_id, sender_phone, aws_phone_number_id, request_id,
                    source_message_id=whatsapp_message_id or '')
            return
        # Native Flow Message reply — India Address Message submission arrives here
        # as nfm_reply with name='address_message' (also used by flow completions).
        elif interactive_type == 'nfm_reply':
            if _referral_data is not None:
                # F008 was durably saved and projected into both inbox stores.
                # Consent to share a number is NOT consent to contact or market to that person.
                _update_contact_timestamp(contact_id, now, wamid=whatsapp_message_id or '')
                return
            if _idea_data is not None:
                return  # Persisted above; never route a private idea into auto-replies.
            if _track_shipping_data is not None:
                # F006 was persisted above. Keep the customer service window current and
                # stop before the cloned Submit Request/post-payment paths can reinterpret it.
                _update_contact_timestamp(contact_id, now, wamid=whatsapp_message_id or '')
                return
            if _pickup_data is not None:
                # Dedicated paid Pickup completion has been stored before transport dedup.
                _update_contact_timestamp(contact_id, now, wamid=whatsapp_message_id or '')
                return
            if _submit_request_data is not None:
                # The completion is already one FlowSubmission + one Inbox card above.
                # It is a customer message, so keep the 24-hour service window current,
                # then stop before generic/post-payment routing can reinterpret it.
                _update_contact_timestamp(contact_id, now, wamid=whatsapp_message_id or '')
                return
            if _request_amendment_data is not None:
                # Same completion contract as Submit Request: durable business row and
                # structured Inbox card were saved above before transport dedup.
                _update_contact_timestamp(contact_id, now, wamid=whatsapp_message_id or '')
                return
            nfm = interactive.get('nfm_reply', {})
            if nfm.get('name') == 'address_message':
                # Opens the 24-hour window like any customer message (see the `order` branch):
                # the submission can resume a waiting cart, whose replies must not be refused.
                _update_contact_timestamp(contact_id, now, wamid=whatsapp_message_id or '')
                # SEND #4.
                if _may_send('address_submission'):
                    _handle_address_submission(nfm, contact_id, sender_phone, aws_phone_number_id, request_id)
                return  # Stop processing — address submission handled
            # Post-payment (endpointless) flow completion: the DETAILS screen's
            # "complete" action returns a payload with reference_id + order details.
            try:
                _raw = nfm.get('response_json', '{}')
                _rj = json.loads(_raw) if isinstance(_raw, str) else (_raw or {})
                if isinstance(_rj, dict) and (_rj.get('reference_id') or _rj.get('request_id')) and (
                    'delivery_note' in _rj or 'preferred_time' in _rj or 'order_number' in _rj
                    or 'description' in _rj or 'request_id' in _rj):
                    # SEND #5.
                    if _may_send('postpay_submission'):
                        _handle_postpay_submission(_rj, contact_id, sender_phone, aws_phone_number_id, request_id)
                    return  # Stop processing — post-payment submission handled
            except Exception as _pp_err:
                logger.warning(json.dumps({'event': 'postpay_nfm_parse_error', 'error': str(_pp_err), 'requestId': request_id}))

    # ── Cart order (native WhatsApp Catalog checkout) ──
    # Customer sent a cart from the catalog (message.type='order'). `_handle_cart_order` parses
    # product_retailer_id + integer quantity ONLY (Meta's item_price/currency are never read),
    # refuses unsafe senders and foreign/unparseable retailer ids, dedupes the cart, and hands
    # productId/variantId/quantity to wecare-checkout `prepareNativeCart`. Checkout - not this
    # file - prices from ProductsTable, reserves the ONE PaymentAttempt + PAYREF# and sends the
    # approved ORDER_DETAILS template. No amount is computed and no payment message is composed
    # here. Gated by `_catalog_orders_enabled()` (SystemConfig override, else the env flag) and
    # by checkout's own WA_CATALOG_ORDERS_ENABLED.
    if msg_type == 'order':
        # The cart IS a customer message, so it opens the 24-hour window. This branch returns
        # before the general `_update_contact_timestamp` below, which left outbound reading a
        # stale window and refusing every non-template reply to the cart (the address request
        # and the refusal replies) for a customer whose last message was a day old.
        _update_contact_timestamp(contact_id, now, wamid=whatsapp_message_id or '')
        # SEND #6 — the money path. This may-send guard runs before `_handle_cart_order`; the
        # reference mint, pricing and send all live in ecommerce/checkout.
        if _may_send('cart_order'):
            _handle_cart_order(message, contact_id, sender_phone, aws_phone_number_id, request_id)
        return

    # Handle system status messages with user_changed_user_id
    # Per Meta BSUID docs: system messages can have type=user_changed_user_id
    # when a user changes their phone number, triggering a new BSUID
    if msg_type == 'system':
        system_data = message.get('system', {})
        system_type = system_data.get('type', '')
        if system_type == 'user_changed_user_id':
            new_bsuid = system_data.get('user_id', '')
            new_parent_bsuid = system_data.get('parent_user_id', '')
            new_wa_id = system_data.get('wa_id', '')
            logger.info(json.dumps({
                'event': 'system_user_changed_user_id',
                'senderPhone': mask_phone(sender_phone),
                'newBsuid': new_bsuid,
                'newParentBsuid': new_parent_bsuid,
                # The new number masked, and the system text (which quotes both numbers) only
                # by presence. The full values are stored on the system event below.
                'newWaId': mask_phone(new_wa_id),
                'hasSystemBody': bool(system_data.get('body')),
                'requestId': request_id
            }))
            # Update contact with new BSUID and phone if available
            if new_bsuid and contact_id:
                try:
                    ct = dynamodb.Table(CONTACTS_TABLE)
                    update_expr = 'SET bsuid = :b'
                    expr_vals = {':b': new_bsuid}
                    # The canonical `+digits` spelling, the one every other writer stores:
                    # Meta's bare `wa_id` here would make the website checkout's exact-match
                    # phone lookup miss this contact and mint a second row for the person.
                    new_phone = contact_store.canonical_phone(new_wa_id)
                    if new_phone:
                        update_expr += ', phone = :p'
                        expr_vals[':p'] = new_phone
                    ct.update_item(
                        Key={'id': contact_id},
                        UpdateExpression=update_expr,
                        ExpressionAttributeValues=expr_vals
                    )
                except Exception as sys_err:
                    logger.warning(f'System user_changed_user_id update failed: {sys_err}')
            _store_system_event('user_changed_user_id', {
                'senderPhone': sender_phone,
                'contactId': contact_id,
                'newBsuid': new_bsuid,
                'newWaId': new_wa_id,
                'body': system_data.get('body', ''),
            }, request_id)
    
    # Handle REQUEST_CONTACT_INFO button response (contacts message with origin=contact_request)
    # Per Meta BSUID docs (May 2026): when user taps REQUEST_CONTACT_INFO button,
    # a contacts message is sent with origin "contact_request/other" containing vCard + phone
    if msg_type == 'contacts':
        msg_origin = message.get('origin', '')
        if 'contact_request' in msg_origin:
            msg_contacts = message.get('contacts', [])
            for mc in msg_contacts:
                phones = mc.get('phones', [])
                # Canonical `+digits`, not the vCard's display text ("+91 98765 43210"), so
                # every channel's phone lookup resolves this same contact row.
                shared_phone = contact_store.canonical_phone(
                    phones[0].get('phone', '') if phones else '')
                if shared_phone and contact_id:
                    try:
                        ct = dynamodb.Table(CONTACTS_TABLE)
                        ct.update_item(
                            Key={'id': contact_id},
                            UpdateExpression='SET phone = :p',
                            ExpressionAttributeValues={':p': shared_phone}
                        )
                        logger.info(json.dumps({
                            'event': 'contact_request_phone_captured',
                            'contactId': mask_contact_id(contact_id),
                            'sharedPhone': shared_phone,
                            'origin': msg_origin,
                            'requestId': request_id
                        }))
                    except Exception as cr_err:
                        logger.warning(f'Contact request phone update failed: {cr_err}')
    
    # Update Contact.lastInboundMessageAt for 24-hour window (+ WAMID for typing)
    _update_contact_timestamp(contact_id, now, wamid=whatsapp_message_id or '')
    
    logger.info(json.dumps({
        'event': 'message_stored',
        'messageId': message_id,
        'contactId': mask_contact_id(contact_id),
        'senderPhone': mask_phone(sender_phone),
        # A WhatsApp profile name is the customer's own name. contactId already
        # identifies them for correlation, so only its presence is logged.
        'hasSenderName': bool(sender_name),
        'whatsappMessageId': whatsapp_message_id,
        'type': msg_type,
        'hasMedia': bool(media_id),
        'receivingPhone': mask_phone(receiving_phone),
        'awsPhoneNumberId': aws_phone_number_id,
        'requestId': request_id
    }))
    
    # Auto-react with thumbs up (skip reactions to avoid loops)
    # Use the same phone number that received the message
    # Direct API for all phones
    if msg_type != 'reaction':
        # Set the current Direct API phone context for this message
        global _current_direct_api_phone
        _current_direct_api_phone = _get_meta_phone_id_for_direct_api(aws_phone_number_id)
        
        if msg_type == 'unsupported':
            # FIX-3, opened on its recorded gate (>= 48 h of FIX-2, one graphError code for
            # >= 95 % of unsupported receipts). Measured 2026-10-22 06:34Z to 2026-10-25 05:53Z:
            # 22 unsupported messages, 22 read receipts refused with Graph 100, and 22 thumbs-up
            # reactions that Meta accepted synchronously and then failed in the status webhook
            # (Graph 100, "Cannot react to a message ... doesn't correspond to any message").
            # Meta holds no message we can mark read or react to, so neither is attempted.
            logger.info(json.dumps({
                'event': 'unsupported_ack_skipped',
                'whatsappMessageId': whatsapp_message_id,
                'requestId': request_id,
            }))
        elif _is_direct_api_phone(aws_phone_number_id):
            # Send reaction and read receipt via Meta Graph API
            # Both callees return a dict rather than raising, so the `except` blocks
            # below were dead and the success events were emitted unconditionally —
            # 250 `read_receipt_sent_direct_api` against 61 real failures in 14 days.
            # Branch on the returned dict so a refusal is reported as one.
            try:
                # SEND #7. A 👍 reaction IS a Service message, so ownership gates it.
                # Guarded alongside the existing `_auto_thumb_enabled()` rather than
                # replacing it: the two switches answer different questions.
                if _auto_thumb_enabled() and _may_send('auto_reaction'):
                    _rx = _send_direct_api_reaction(sender_phone, whatsapp_message_id, emoji=AUTO_THUMB_EMOJI)
                    if _rx.get('error'):
                        logger.warning(json.dumps({
                            'event': 'auto_reaction_failed',
                            'contactId': mask_contact_id(contact_id),
                            'whatsappMessageId': whatsapp_message_id,
                            'messageType': msg_type,
                            'status': _rx.get('status'),
                            'graphError': _graph_error_code(_rx.get('detail')),
                            'requestId': request_id
                        }))
                    else:
                        logger.info(json.dumps({
                            'event': 'auto_reaction_triggered_direct_api',
                            'contactId': mask_contact_id(contact_id),
                            'whatsappMessageId': whatsapp_message_id,
                            'requestId': request_id
                        }))
                        # The fourth documented signal, and the only place in this handler
                        # that can honestly emit it. A Service message Meta ACCEPTED
                        # proves we owned the thread at that moment — and this is the one
                        # send site with a synchronous answer from Meta to branch on.
                        # Every other send here is a fire-and-forget async invoke, where
                        # "sent" means "handed to a queue", which proves nothing about
                        # ownership. Recording it from those would be inventing evidence.
                        thread_ownership.record_signal(
                            str((metadata or {}).get('phone_number_id') or ''),
                            bsuid=msg_bsuid, wa_id=sender_phone,
                            signal=thread_ownership.SIGNAL_SERVICE_MESSAGE_SENT,
                            detail='auto_reaction')
            except Exception as e:
                logger.warning(f"Direct API auto-reaction failed: {type(e).__name__}")
            try:
                # SEND #8 — DELIBERATELY NOT GATED on ownership. Do not "finish the job"
                # by adding `_may_send` here.
                #
                # TODO(conversation-routing): does a `status: read` / `typing_indicator`
                # count as an ownership-gated Service message? Meta's docs gate "Service
                # messages" and never classify either of these. Both go to the same
                # /{phone_id}/messages endpoint, which argues they do; the typing
                # indicator is user-visible, which argues the same; mark-as-read
                # plausibly does not. It is UNVERIFIED, it is ungated today, and it fires
                # 462 times per 30 days — so guessing either way is worse than leaving one
                # known unknown labelled. The empirical check that would settle it:
                # observe whether Meta rejects a mark-as-read from a non-owner under a
                # live routing configuration. Note the reaction immediately above IS
                # gated: that one is unambiguously a Service message, this one is not.
                _rr = _send_direct_api_read_receipt(whatsapp_message_id, show_typing=True)
                if _rr.get('error'):
                    # `messageType` is what makes the deferred unsupported-skip
                    # (FIX-3) decidable from the log alone.
                    logger.warning(json.dumps({
                        'event': 'read_receipt_failed',
                        'whatsappMessageId': whatsapp_message_id,
                        'messageType': msg_type,
                        'status': _rr.get('status'),
                        'graphError': _graph_error_code(_rr.get('detail')),
                        'requestId': request_id
                    }))
                else:
                    logger.info(json.dumps({
                        'event': 'read_receipt_sent_direct_api',
                        'whatsappMessageId': whatsapp_message_id,
                        'requestId': request_id
                    }))
            except Exception as e:
                logger.warning(f"Direct API read receipt failed: {type(e).__name__}")
        else:
            # SEND #9 — the AWS-path twins of #7 and #8, gated the same way and for the
            # same reasons: the reaction is a Service message, the receipt is the
            # ambiguous one. The asymmetry here is deliberate, not an oversight.
            if _may_send('auto_reaction_aws'):
                _send_auto_reaction(
                    contact_id=contact_id,
                    whatsapp_message_id=whatsapp_message_id,
                    phone_number_id=aws_phone_number_id,
                    request_id=request_id
                )

            # Send read receipt to show message was received.
            # NOT GATED — see the TODO on send #8 above.
            _send_read_receipt(
                whatsapp_message_id=whatsapp_message_id,
                phone_number_id=aws_phone_number_id,
                request_id=request_id
            )

    # ── A message WhatsApp delivered without its content ──
    # Nothing below answers it (keyword routing reads text only), so without this the customer
    # hears nothing, and while the cause lasts (most often disappearing messages on the chat)
    # every message they send arrives the same way.
    if msg_type == 'unsupported' and content in UNREADABLE_MESSAGE_LABELS:
        _send_unreadable_hint(contact_id, aws_phone_number_id, now, request_id)
    
    # ── request_welcome: user tapped "Start"  -  always answer ──
    if msg_type == 'request_welcome':
        logger.info(json.dumps({
            'event': 'request_welcome_triggered',
            'contactId': mask_contact_id(contact_id),
            'senderPhone': mask_phone(sender_phone),
            'requestId': request_id,
        }))
        # SEND #10 — the site menu. Note `request_welcome` is NOT a deterministic
        # trigger, so a standby "Start" tap never reaches here anyway; the guard is for
        # completeness rather than for a path that exists today.
        if _may_send('request_welcome_menu'):
            _send_wd_main_menu(contact_id, sender_phone, aws_phone_number_id, request_id)
        # Mark welcomeSent so brand-new contact path doesn't double-send
        try:
            dynamodb.Table(CONTACTS_TABLE).update_item(
                Key={'id': contact_id},
                UpdateExpression='SET welcomeSent = :t, welcomeSentAt = :ts',
                ExpressionAttributeValues={':t': True, ':ts': Decimal(str(now))}
            )
        except Exception:
            pass
        return  # Skip AI automation  -  welcome flow handled

    # ── Button type: "Get Started" quick reply or other button taps ──
    # WhatsApp "Get Started" ice-breaker sends msg_type='button' with text payload.
    # Treat button text as keyword input so it triggers the interactive menu.
    if msg_type == 'button' and content:
        button_text_lower = content.strip().lower()
        logger.info(json.dumps({
            'event': 'button_message_received',
            'buttonText': button_text_lower,
            'contactId': mask_contact_id(contact_id),
            'senderPhone': mask_phone(sender_phone),
            'requestId': request_id,
        }))
        # "Unlock Vault" on the ₹49 Vault offer (wecare_valut_49). Its payload names the offer,
        # so the tap opens Review and Pay for exactly that document; a tap with no offer payload
        # opens the customer's document list, as the "Vault" keyword does.
        if _route_vault_offer_tap(message, button_text_lower, contact_id, sender_phone,
                                  aws_phone_number_id, whatsapp_message_id, request_id):
            return
        if button_text_lower == 'drop docs' and _route_paid_drop_docs(
                contact_id, sender_phone, aws_phone_number_id, whatsapp_message_id, request_id):
            return
        # Map common button texts to the site menu.
        # `customerservice` is here because the the legacy customer-service label ice breaker is live on
        # both numbers and can arrive as `button` rather than `text`. The text
        # branch below is skipped entirely for a button message, so before this
        # it was a silent tap. THE TRIGGER SET STAYS: you cannot answer a trigger
        # word without a trigger-word set, and every one of these is live on
        # Meta's side as a QR prefill, an ice breaker or a slash command.
        BUTTON_MENU_TRIGGERS = {'get started', 'start', 'menu', 'hi', 'hello', 'hey',
                                'main menu', 'need help!', 'get help',
                                'customerservice', 'customer service', 'customer-service'}
        if (button_text_lower in BUTTON_MENU_TRIGGERS
                or strip_decorative_edges(button_text_lower) in BUTTON_MENU_TRIGGERS
                or button_text_lower.startswith('get started')):
            # SEND #11.
            if _may_send('button_text_menu'):
                _send_wd_main_menu(contact_id, sender_phone, aws_phone_number_id, request_id)
            logger.info(json.dumps({
                'event': 'button_triggered_menu_sent',
                'buttonText': button_text_lower,
                'contactId': mask_contact_id(contact_id),
                'requestId': request_id,
            }))
            return  # Skip AI automation — menu sent via button trigger

    # ── Keyword triggers (before AI automation) ──
    # SEND #12 — one guard covering the WHOLE keyword-routing table below, which is
    # every menu, flow, CTA, payment and link reply a text message can produce. One
    # guard rather than ~20, because the block contains no DynamoDB writes and no state
    # changes: it reads `content_lower` and sends. Skipping it therefore skips only
    # sends, which is exactly the intent. Any future write added inside this block must
    # be hoisted above this guard or it will silently stop happening when the flag is off.
    if msg_type == 'text' and content and _may_send('text_keyword_routing'):
        content_lower = content.strip().lower()

        # ── Slash-command normalization (WhatsApp Conversational Components) ──
        # A configured command can be tapped OR typed with arguments/trailing
        # text, e.g. "[retired public path] 500", "/menu ", "/imagine cars". Meta delivers the
        # FULL body. Collapse a KNOWN "/command [args]" to just the command
        # token so it reliably routes to the same handler as the bare command.
        # Unknown "/foo" is left intact so free-form input still reaches the AI.
        if content_lower.startswith('/'):
            _cmd_token = content_lower.split(None, 1)[0]
            _SLASH_COMMAND_ALIASES = {
                '/menu': '/menu',
                '/orders': 'orders',
                '/submitrequest': 'submit request',
                '/amendment': 'request amendment',
                '/dropdocs': 'drop docs',
                '/vault': 'vault',
                '/shipments': 'shipments',
                '/review': 'leave review',
                '/subscribe': 'subscribe',
                '/pay': '/pay',
                '/bharatstack': '/bharatstack',
                '/self' + 'service': '/self' + 'service',
                '/service': '/service',
                '/help': '/help',
                '/commands': '/commands',
            }
            if _cmd_token in _SLASH_COMMAND_ALIASES:
                logger.info(json.dumps({
                    'event': 'slash_command_normalized',
                    'original': content_lower[:80], 'command': _cmd_token,
                    'contactId': mask_contact_id(contact_id), 'requestId': request_id,
                }))
                content_lower = _SLASH_COMMAND_ALIASES[_cmd_token]

        # Decoration-stripped alias, used as a FALLBACK by the greeting /
        # customer-service / commands checks below so "Hi 👋", "menu 🙏" and "❓ FAQs"
        # route the same as their bare forms. Computed after slash normalisation so
        # '/menu' is already collapsed. See strip_decorative_edges() for why this is
        # deliberately not applied to the pay, flow-trigger or subscriber-id sets.
        _content_plain = strip_decorative_edges(content_lower)

        # Non-form service doors reuse secure website experiences. No second payment path.
        if _content_plain in {'vault', 'my vault', 'request amendment', 'drop docs',
                              'shipments', 'submit request'}:
            if (_content_plain in {'vault', 'my vault'} and whatsapp_message_id
                    and aws_phone_number_id == PHONE_NUMBER_ID_1
                    and os.environ.get('WHATSAPP_CATALOG_SERVICES_ENABLED', 'false').lower() == 'true'):
                # The keyword is a signed inbound message, so it opens the same document list a
                # Vault catalog cart opens (business-api `catalogService.start`): commerce proves
                # the customer from this message id, and each document is offered as Paid (free
                # link), Renew or unpaid (one server-priced Review and Pay). WABA1 only, because
                # only WABA1 may take a payment; anything else keeps the website door below.
                try:
                    from lambda_utils.ecommerce import service_requests as _services
                    _vault_variant = _services.SERVICE_VARIANT_BY_KIND[_services.VAULT]
                    if _may_send('vault_keyword'):
                        lambda_client.invoke(
                            FunctionName='wecare-whatsapp-business-api:live', InvocationType='Event',
                            Payload=json.dumps({
                                'internalAction': 'catalogService', 'action': 'start',
                                'lines': [{'productId': _services.SERVICE_PRODUCT_BY_VARIANT[_vault_variant],
                                           'variantId': _vault_variant, 'quantity': 1}],
                                'sourceMessageId': whatsapp_message_id, 'contactId': contact_id,
                                'senderPhone': sender_phone,
                                'phoneNumberId': aws_phone_number_id}).encode())
                    return
                except Exception as error:  # noqa: BLE001 - fall back to the website door
                    logger.warning(json.dumps({'event': 'vault_keyword_list_unavailable',
                                               'errorType': type(error).__name__,
                                               'requestId': request_id}))
            if (_content_plain == 'drop docs'
                    and _route_paid_drop_docs(contact_id, sender_phone, aws_phone_number_id,
                                              whatsapp_message_id, request_id)):
                return
            service_doors = {
                'vault': ('Vault', '/vault/', 'Access documents linked to your verified account.'),
                'my vault': ('Vault', '/vault/', 'Access documents linked to your verified account.'),
                'request amendment': ('View orders', '/orders/', 'Sign in to select the existing order you want to amend. The WhatsApp amendment checkout is being prepared.'),
                'drop docs': ('View orders', '/orders/', 'Sign in to select your existing order and its request before attaching documents. The WhatsApp document checkout is being prepared.'),
                'shipments': ('Orders', '/orders/', 'View your orders and delivery updates with this verified WhatsApp number.'),
                'submit request': ('View orders', '/orders/', 'Sign in to select your existing order. Your service purchase and the order you need help with remain linked separately. The WhatsApp service checkout is being prepared.'),
            }
            title, path, body = service_doors[_content_plain]
            _send_cta_button(contact_id, aws_phone_number_id, title,
                'https://wecare.digital' + path, request_id,
                body_text=body, footer_text='WECARE.DIGITAL')
            return

        # Orders and public Customer ID share the website's verified customer partition.
        if (_content_plain in {'orders', 'my orders', 'order history', 'all orders',
                               'customer id', 'my customer id', 'customer uuid'}
                or re.fullmatch(r'orders page [1-9][0-9]{0,2}', _content_plain)):
            try:
                result = lambda_client.invoke(
                    FunctionName='wecare-whatsapp-business-api:live',
                    InvocationType='RequestResponse',
                    Payload=json.dumps({'internalAction': 'customerCommand',
                        'text': _content_plain, 'contactId': contact_id,
                        'senderPhone': sender_phone}).encode())
                answer = json.loads(result['Payload'].read())
                if result.get('FunctionError') or not answer.get('reply'):
                    raise RuntimeError('customer command unavailable')
                _send_cta_button(contact_id, aws_phone_number_id, 'View orders',
                    'https://wecare.digital/orders/', request_id,
                    body_text=answer['reply'], footer_text='WECARE.DIGITAL')
            except Exception as error:
                logger.warning(json.dumps({'event': 'customer_command_unavailable',
                                           'errorType': type(error).__name__}))
                _send_cta_button(contact_id, aws_phone_number_id, 'View orders',
                    'https://wecare.digital/orders/', request_id,
                    body_text='Please sign in with this WhatsApp number to securely view your orders and Customer ID.',
                    footer_text='WECARE.DIGITAL')
            return

        # ── "Get my ID" / "my id" / "sub id" — fetch subscriber details ──
        MY_ID_KEYWORDS = {
            'my id', 'my sub id', 'sub id', 'subscriber id', 'my subscriber id',
            'get my id', 'get id', 'what is my id', 'whats my id',
            '/myid', '/id', 'show my id', 'my subscription', 'my subscription id',
            'find id', 'find my id', 'profile id', 'my profile id',
        }
        if content_lower in MY_ID_KEYWORDS:
            # The Customer ID lives on the canonical contact row. FlowSubmission rows are
            # history (and a submission reference is not a Customer ID), so they never answer
            # "who am I". A WhatsApp sender is already proven to hold this number, which is
            # why the public display code - never the internal UUID - is safe to return here.
            try:
                row = contact_store.lookup(dynamodb.Table(CONTACTS_TABLE), sender_phone,
                                           contact_id=contact_id) or {}
            except Exception as e:
                logger.warning(json.dumps({'event': 'my_id_lookup_failed',
                                           'errorType': type(e).__name__,
                                           'requestId': request_id}))
                _send_ai_auto_reply(contact_id, 'We could not look up your WECARE.DIGITAL Customer ID '
                                    'right now. Please try again in a few minutes.',
                                    aws_phone_number_id, request_id)
                return
            display_id = customer_uuid.display_code(row)
            reply = (f'Your WECARE.DIGITAL Customer ID is {display_id}.' if display_id else
                     'This WhatsApp number does not have a WECARE.DIGITAL Customer ID yet. '
                     'Reply here and our team will help.')
            _send_ai_auto_reply(contact_id, reply, aws_phone_number_id, request_id)
            return

        # Load flow triggers from SystemConfigTable (dashboard-configurable). Matching is EXACT:
        # the whole message, trimmed and lowercased, must equal one configured keyword.
        flow_triggers = _get_flow_triggers_config()
        for flow_key, trigger in flow_triggers.items():
            if content_lower not in flow_launch.normalize_keywords(trigger.get('keywords', [])):
                continue
            if flow_key == 'subscribe':
                # F001 owns its whole launch policy; False means "not launched, keep looking".
                if _launch_subscribe_flow(contact_id, aws_phone_number_id, sender_phone,
                                          request_id, trigger):
                    return  # Skip AI automation  -  flow handles the rest
                continue
            if flow_key == 'leave_review':
                # F002 is the second canonical keyword door. Unlike legacy generic flows it
                # defaults OFF and needs canonical + FlowRegistry + Meta + runtime agreement.
                try:
                    registry_row = flow_launch.read_registry_row(
                        dynamodb.Table(flow_launch.registry_table_name()),
                        canonical_flow_id('leave_review'))
                except Exception:  # unreadable registry is a refusal, never a launch
                    continue
                decision = flow_launch.keyword_launch_decision(
                    capability='leave_review', registry_row=registry_row, trigger=trigger)
                if not decision.allowed:
                    logger.info(json.dumps({'event': 'keyword_flow_refused',
                                            'flowKey': flow_key,
                                            'reason': decision.reason,
                                            'requestId': request_id}))
                    continue
            elif not trigger.get('enabled', True):
                continue
            # Paid/post-payment/event-only flows are never allowed to become keyword doors.
            if trigger.get('entryMode', 'keyword_interactive') != 'keyword_interactive':
                continue
            flow_id = trigger.get('flowId', '')
            if not flow_id:
                # No Flow behind this door (track_request today): its website link answers.
                _send_flow_link(contact_id, aws_phone_number_id, flow_key, trigger, request_id,
                                reason='no_flow_id')
                return
            # The trigger is Workspace-editable, so FlowRegistry decides whether this Flow may
            # open from a keyword at all. An unreadable registry refuses rather than guesses.
            try:
                registry_row = flow_launch.read_registry_row(
                    dynamodb.Table(flow_launch.registry_table_name()), flow_id)
                refusal = flow_launch.generic_keyword_refusal(flow_key, flow_id, registry_row)
            except Exception as e:  # noqa: BLE001
                refusal = f'registry_unreadable:{type(e).__name__}'
            if refusal:
                logger.warning(json.dumps({'event': 'keyword_flow_refused', 'flowKey': flow_key,
                                           'reason': refusal, 'requestId': request_id}))
                continue
            # WABA 1 sends the Flow itself, so it must be live on Meta: a missing, draft or
            # deprecated Flow is refused after this Lambda returns and the customer hears
            # nothing. WABA 2 never sends this Flow (`_send_generic_flow` links instead).
            liveness = flow_launch.meta_liveness(registry_row)
            if aws_phone_number_id != PHONE_NUMBER_ID_2 and liveness != 'live':
                _send_flow_link(contact_id, aws_phone_number_id, flow_key, trigger, request_id,
                                reason=liveness)
                return
            # Keyword-native flows use the native WhatsApp Flow interactive sender.
            _send_generic_flow(
                contact_id=contact_id,
                phone_number_id=aws_phone_number_id,
                sender_phone=sender_phone,
                request_id=request_id,
                flow_config=trigger,
                flow_key=flow_key,
            )
            return  # Skip AI automation  -  flow handles the rest

        # ── `review <REF>` — the attributed half of the website review door (Phase R) ──
        #
        # Placed AFTER the exact-match loop so it can never shadow it: `review` on its own
        # is a `leave_review` keyword and still takes the loop above, unattributed. This
        # branch only exists for the extra token the website link adds.
        #
        # It is a second, tightly-bounded branch rather than extra keywords because the
        # loop matches `content_lower in keywords` - an EXACT match - so no keyword list
        # can ever contain a reference. It fires on the literal root `review` only, never
        # on `rate`, `feedback` or `testimonial`: those are the generic keywords
        # `docs/whatsapp-experience-structure.md` already flags as a precedence hazard.
        if _review_attribution_enabled():
            review_reference = _extract_review_reference(content_lower)
            if review_reference:
                review_trigger = (flow_triggers.get('leave_review') or {})
                try:
                    review_registry = flow_launch.read_registry_row(
                        dynamodb.Table(flow_launch.registry_table_name()),
                        canonical_flow_id('leave_review'))
                    review_allowed = flow_launch.keyword_launch_decision(
                        capability='leave_review', registry_row=review_registry,
                        trigger=review_trigger).allowed
                except Exception:
                    review_allowed = False
                if review_allowed and review_trigger.get('flowId') \
                        and _may_send('leave_review_attributed'):
                    # The park result is CARRIED INTO THE LOG, not discarded. A park
                    # failure degrades to an unattributed review, which is the right
                    # trade - the customer still gets the form - but silently, and a
                    # recurring DynamoDB problem would look like customers simply not
                    # using the website door. `attributed` on the one event this branch
                    # emits makes the failure rate answerable from a single metric filter
                    # instead of needing a second log line nobody has a filter for.
                    parked = _park_review_reference(sender_phone, review_reference, request_id)
                    logger.info(json.dumps({
                        'event': 'review_attributed_flow_sent',
                        'reference': review_reference,
                        'attributed': parked,
                        'contactId': mask_contact_id(contact_id),
                        'phone': mask_phone(sender_phone),
                        'requestId': request_id,
                    }))
                    _send_generic_flow(
                        contact_id=contact_id,
                        phone_number_id=aws_phone_number_id,
                        sender_phone=sender_phone,
                        request_id=request_id,
                        flow_config=review_trigger,
                        flow_key='leave_review',
                    )
                    return  # Skip AI automation  -  flow handles the rest

        # ── Direct "Pay" keyword trigger (LLM-independent, hardcoded) ──
        # Exact matches (content_lower must be exactly one of these)
        PAY_KEYWORDS = {
            # English  -  core
            'pay', 'payment', 'pay now', 'pay bill', 'bill pay', '/pay',
            'pay a bill',  # row title in the one menu
            'pay due', 'pay dues', 'pay invoice', 'invoice',
            'pending payment', 'pending due', 'pending dues',
            'send payment', 'make payment', 'make a payment',
            'amount pay', 'pay amount',
            # English  -  conversational
            'i want to pay', 'i want pay', 'want to pay', 'wanna pay',
            'let me pay', 'ready to pay', 'how to pay', 'how do i pay',
            'what is my due', 'what are my dues', 'whats my due',
            'what is due', 'my due', 'my dues', 'my bill', 'my invoice',
            'show my bill', 'show my due', 'show my dues', 'show my invoice',
            'show invoice', 'show bill', 'show due', 'show dues',
            'check due', 'check dues', 'check bill', 'check invoice',
            'any due', 'any dues', 'any pending', 'any bill',
            'pending bill', 'pending bills', 'unpaid', 'unpaid bill',
            'outstanding', 'outstanding due', 'outstanding bill',
            'balance', 'balance due', 'due balance',
            'send bill', 'send invoice', 'resend invoice', 'resend bill',
            # Hindi / Hinglish
            'bhugtan', 'paisa', 'rupees', 'paise', 'kitna dena hai',
            'kitna baaki hai', 'baaki', 'baki', 'baaki hai', 'baki hai',
            'payment karo', 'payment kar do', 'pay karo', 'pay kar do',
            'bill bhejo', 'invoice bhejo', 'paisa dena hai', 'paise dene hai',
            'mera bill', 'mera due', 'mera invoice', 'mera baaki',
            'kितना बाकी है', 'भुगतान', 'बिल', 'पेमेंट',
        }
        # Fuzzy matches (content_lower contains any of these substrings)
        PAY_FUZZY = (
            'want to pay', 'wanna pay', 'make payment', 'pay my', 'pay the', 'pay for',
            'send me bill', 'send me invoice', 'send me due',
            'how much do i owe', 'how much i owe', 'what do i owe',
            'pending amount', 'due amount', 'total due',
            'kitna dena', 'kitna baaki', 'baaki kitna', 'payment bhej',
        )
        if content_lower in PAY_KEYWORDS or any(kw in content_lower for kw in PAY_FUZZY):
            logger.info(json.dumps({
                'event': 'pay_keyword_triggered',
                'matchedKeyword': next((k for k in PAY_KEYWORDS if k == content_lower),
                                      next((k for k in PAY_FUZZY if k in content_lower), '')),
                'contactId': mask_contact_id(contact_id),
                'senderPhone': mask_phone(sender_phone),
                'phoneNumberId': aws_phone_number_id,
                'requestId': request_id,
            }))
            # Phone 2: send CTA link to Phone 1 for payment
            if aws_phone_number_id == PHONE_NUMBER_ID_2:
                _send_cta_button(
                    contact_id=contact_id,
                    phone_number_id=aws_phone_number_id,
                    cta_text='Pay Now',
                    cta_url='https://wecare.digital/r/pay',
                    request_id=request_id,
                    body_text='\U0001f4b3 Make your payment quickly and securely online.',
                    footer_text='WECARE.DIGITAL',
                )
                return
            # Phone 1: Step 1: Send "pulling" message immediately
            _send_ai_auto_reply(contact_id, PAY_MSG['pulling'], aws_phone_number_id, request_id)
            try:
                inv_payload = {
                    'rawPath': '/invoices/send-pending-by-phone',
                    'requestContext': {'http': {'method': 'POST'}},
                    'body': json.dumps({
                        'customerPhone': sender_phone,
                        'phoneNumberId': aws_phone_number_id,
                    }),
                }
                # The checkout function's `live` alias serves /invoices/send-pending-by-phone from
                # the invoice engine it packages (the same code wecare-invoice-engine runs while
                # its API routes move to checkout). Pinning the alias keeps this leg on the
                # published code, as the prepareNativeCart invoke above already does.
                inv_response = lambda_client.invoke(
                    FunctionName=CHECKOUT_FUNCTION,
                    InvocationType='RequestResponse',
                    Payload=json.dumps(inv_payload),
                )
                inv_result = json.loads(inv_response['Payload'].read())
                inv_body = json.loads(inv_result.get('body', '{}'))
                sent_count = inv_body.get('sent', 0)
                total_count = inv_body.get('total', 0)
                send_error = inv_body.get('error', '')

                if total_count == 0:
                    _send_ai_auto_reply(contact_id, PAY_MSG['no_dues'], aws_phone_number_id, request_id)
                elif sent_count == 0:
                    _send_ai_auto_reply(contact_id, PAY_MSG['send_failed'], aws_phone_number_id, request_id)
                    logger.warning(json.dumps({
                        'event': 'pay_keyword_send_failed',
                        'sent': 0, 'total': total_count,
                        'error': send_error, 'phone': mask_phone(sender_phone),
                        'requestId': request_id,
                    }))

                logger.info(json.dumps({
                    'event': 'pay_keyword_complete',
                    'sent': sent_count, 'total': total_count,
                    'phone': mask_phone(sender_phone), 'requestId': request_id,
                }))
            except Exception as pay_err:
                logger.error(json.dumps({
                    'event': 'pay_keyword_error',
                    'error': str(pay_err),
                    'phone': mask_phone(sender_phone),
                    'requestId': request_id,
                }))
                _send_ai_auto_reply(contact_id, PAY_MSG['error'], aws_phone_number_id, request_id)
            return  # Skip AI automation  -  payment flow handled

        # ── Direct "Hi" / greeting keyword trigger (LLM-independent) ──
        # 'get help' and 'hi 👋' are here because they are OUR OWN prefilled QR
        # messages, and neither matched anything until 2026-09-26:
        #
        #   WABA1 QR APDM5HUWH26SG1 -> prefilled "Get Help"
        #   WABA2 QR DPESCFW7U4FXO1 -> prefilled "Hi 👋"
        #
        # Both are what SupportWidget.tsx, wecare-wa-widget.js and every printed
        # QR send as the customer's first message. A brand-new contact still got
        # the menu via the brand-new-contact path further down, which is why this
        # looked like it worked - but a RETURNING visitor tapping the same widget
        # matched no keyword set at all and got silence, because the unmatched-text
        # path deliberately sends nothing.
        #
        # Matched as literal variants rather than by stripping the emoji, which is
        # the existing convention in this file ('📋 submit request', '🚀 customerservice',
        # '❓ faqs'). Fixing the keyword rather than editing the QR is deliberate:
        # the QR codes are already printed and the links are already shared, so the
        # inbound side is the only place a fix reaches messages already in the wild.
        HI_KEYWORDS = {'hi', 'hello', 'hey', 'menu', 'main menu', 'show menu', 'start',
                       'browse menu', '/menu', 'need help!', 'get started',
                       'get help', 'hi 👋'}
        if content_lower in HI_KEYWORDS or _content_plain in HI_KEYWORDS:
            logger.info(json.dumps({
                'event': 'hi_keyword_triggered',
                'content': content_lower,
                'contactId': mask_contact_id(contact_id),
                'senderPhone': mask_phone(sender_phone),
                'requestId': request_id,
            }))
            # Open the site menu so a greeting is answered rather than met with
            # silence. A Graph failure degrades to MENU_PLACEHOLDER_TEXT.
            _send_wd_main_menu(contact_id, sender_phone, aws_phone_number_id, request_id)
            logger.info(json.dumps({
                'event': 'hi_keyword_welcome_sent',
                'contactId': mask_contact_id(contact_id),
                'requestId': request_id,
            }))
            return  # Skip AI automation  -  welcome flow handled

        # ── Ice breaker: "explore WECARE.DIGITAL" ──
        # THE REPLY COPY NO LONGER SAYS "BHARAT STACK". That name is retired - the product
        # is WECARE.DIGITAL everywhere - so the button label and body text now use it.
        # THE TRIGGER KEYWORDS ARE DELIBERATELY UNCHANGED, including 'bharat stack' and
        # '/bharatstack'. They are what people have already been told to send, and some are
        # printed in delivered WhatsApp messages and the ice-breaker config on the Meta side;
        # dropping them would silently stop answering a message a customer was invited to
        # send. They are inbound aliases now, not a brand claim.
        BHARAT_KEYWORDS = {'try bharat stack', 'bharat stack', '/bharatstack', 'bharat', 'aadhaar', 'upi', 'digilocker'}
        if content_lower in BHARAT_KEYWORDS:
            logger.info(json.dumps({
                'event': 'explore_wecare_triggered',
                'content': content_lower,
                'contactId': mask_contact_id(contact_id),
                'requestId': request_id,
            }))
            _send_cta_button(contact_id, aws_phone_number_id, 'Explore WECARE.DIGITAL', 'https://wecare.digital', request_id,
                body_text="Explore WECARE.DIGITAL and discover services designed for everyday Bharat.",
                footer_text='WECARE.DIGITAL')
            return

        # ── Ice breaker: the legacy customer-service label / "[retired public path]" ──
        # THE KEYWORDS STAY. the legacy customer-service label is a live ice breaker and
        # `customerservice` a live slash command on BOTH numbers (read off Meta's
        # conversational_automation on 2026-09-26), so dropping the trigger would
        # stop answering something customers are actively invited to tap. It opens
        # the same site menu as a greeting — the commands reply says so.
        CUSTOMERSERVICE_KEYWORDS = {'self' + '-service', 'self' + 'service', 'self' + ' service', '/self' + 'service', '/service'}
        if content_lower in CUSTOMERSERVICE_KEYWORDS or _content_plain in CUSTOMERSERVICE_KEYWORDS:
            logger.info(json.dumps({
                'event': 'customerservice_triggered',
                'content': content_lower,
                'contactId': mask_contact_id(contact_id),
                'requestId': request_id,
            }))
            _send_wd_main_menu(contact_id, sender_phone, aws_phone_number_id, request_id)
            return

        # ── The one menu's Help row, typed rather than tapped ──
        # Must sit ABOVE COMMANDS_KEYWORDS, which owns bare 'help'. Bare 'help'
        # is deliberately left on the commands list: it is long-established, and
        # the commands reply names itself in its own text. See defect #6 in
        # docs/whatsapp-experience-structure.md — 'help' is contested by three
        # keyword sets and first match wins.
        HELP_ABOUT_KEYWORDS = {'help & about', 'help and about', 'help about',
                               '\u2753 help & about'}
        if content_lower in HELP_ABOUT_KEYWORDS or _content_plain in HELP_ABOUT_KEYWORDS:
            _send_help_about(contact_id, aws_phone_number_id, request_id)
            return

        # ── Ice breaker: "Commands" / "/commands" / "/help" ──
        COMMANDS_KEYWORDS = {'commands', '/commands', '/help', 'help'}
        if content_lower in COMMANDS_KEYWORDS or _content_plain in COMMANDS_KEYWORDS:
            # Only `menu`, `subscribe`, `customerservice` and `pay` are registered as
            # tappable commands on Meta (both numbers, verified 2026-09-26).
            # `/bharatstack` and `/help` work when typed but cannot be tapped,
            # so they are listed last. `[retired public path]` no longer opens a second
            # menu — say so rather than implying there are two.
            commands_text = (
                "*Available Commands*\n\n"
                "/menu - Open the menu\n"
                "/customerservice - Opens the same menu\n"
                "/subscribe - Register for updates and orders\n"
                "/pay - Make a payment or check dues\n"
                "/bharatstack - Explore WECARE.DIGITAL services\n"
                "/help - Show this list"
            )
            _send_ai_auto_reply(contact_id, commands_text, aws_phone_number_id, request_id)
            return

        # ── Keyword: "store" / "shop" / "explore store" ──
        STORE_KEYWORDS = {'store', 'shop', 'explore store', 'brands', 'marketplace', '\U0001f6cd\ufe0f explore store'}
        if content_lower in STORE_KEYWORDS:
            _send_cta_button(contact_id, aws_phone_number_id, 'Explore Store', 'https://wecare.digital', request_id)
            return

        # ── Keyword: "gift card" / "gift" ──
        GIFT_KEYWORDS = {'gift card', 'gift cards', 'gift', 'buy gift card', '\U0001f381 gift cards'}
        if content_lower in GIFT_KEYWORDS:
            _send_cta_button(contact_id, aws_phone_number_id, 'Perks', 'https://wa.me/message/377GALDW4E26F1', request_id)
            return

        # ── Keyword: "faq" / "faqs" / "help" / "questions" ──
        FAQ_KEYWORDS = {'faq', 'faqs', 'help', 'questions', 'common questions', '\u2753 faqs'}
        if content_lower in FAQ_KEYWORDS:
            _send_cta_button(contact_id, aws_phone_number_id, 'FAQs', 'https://wecare.digital/contact/', request_id)
            return

        # ── Keyword: "about" / "about us" / "about wecare" ──
        ABOUT_KEYWORDS = {'about', 'about us', 'about wecare', 'about wecare.digital', '\U0001f49b about wecare.digital'}
        if content_lower in ABOUT_KEYWORDS:
            _send_cta_button(contact_id, aws_phone_number_id, 'About Us', 'https://wecare.digital', request_id)
            return

    # Process AI automation for supported message types
    # Now includes media types (image, audio, video, document) for multimodal AI
    ai_eligible_types = ['text', 'interactive', 'button', 'location', 'image', 'video', 'audio', 'document']

    # Auto-transcribe voice notes (audio messages) for English transcription display
    if msg_type == 'audio' and s3_key:
        _auto_transcribe_voice_note(message_id, s3_key, request_id)

    # ── Welcome message for brand-new contacts (independent of AI pipeline) ──
    # Check if welcome was already sent for this contact
    _welcome_already_sent = contact.get('welcomeSent') or contact.get('welcomeMessageSent')
    _is_brand_new_contact = not _welcome_already_sent
    if _is_brand_new_contact and msg_type in ('text', 'image', 'audio', 'video', 'document', 'request_welcome'):
        try:
            # A brand-new contact gets the site menu. The welcomeSent write below
            # MUST stay, or this re-sends on every message from a new contact.
            #
            # SEND #13 — the SEND is guarded, the write is NOT, and that asymmetry is a
            # deliberate trade with a cost worth naming: when a welcome is suppressed the
            # contact is still marked welcomed, so they never get one later. The
            # alternative — skipping the write too — means retrying the welcome on EVERY
            # subsequent message from that contact, which under an active routing
            # configuration is a rejected Graph send every time, forever. A thread we do
            # not own is being answered by whoever does own it, so the missed welcome is
            # the cheaper of the two failures.
            if _may_send('brand_new_contact_welcome'):
                _send_wd_main_menu(contact_id, sender_phone, aws_phone_number_id, request_id)
            # Mark contact so welcome isn't sent again
            try:
                dynamodb.Table(CONTACTS_TABLE).update_item(
                    Key={'id': contact_id},
                    UpdateExpression='SET welcomeSent = :t, welcomeSentAt = :ts',
                    ExpressionAttributeValues={':t': True, ':ts': Decimal(str(now))}
                )
            except Exception:
                pass
            logger.info(json.dumps({
                'event': 'welcome_message_sent',
                'contactId': mask_contact_id(contact_id),
                'senderPhone': mask_phone(sender_phone),
                'requestId': request_id
            }))
        except Exception as _we:
            logger.warning(f"Welcome message failed (non-blocking): {_we}")

    if msg_type in ai_eligible_types and (content or s3_key) and not _is_brand_new_contact:
        # ── No auto-response for unmatched messages ──
        # Only keyword-triggered flows, welcome messages, and menu responses are sent.
        # Unmatched messages are stored but no reply is sent.
        # The admin can see all messages in the dashboard inbox and reply manually.
        pass


def _route_paid_drop_docs(contact_id: str, sender_phone: str, aws_phone_number_id: str,
                          source_message_id: Optional[str], request_id: str) -> bool:
    """Start the one native ₹199 Drop Docs checkout from a signed inbound interaction."""
    if (not source_message_id or aws_phone_number_id != PHONE_NUMBER_ID_1
            or os.environ.get('WHATSAPP_CATALOG_SERVICES_ENABLED', 'false').lower() != 'true'):
        return False
    from lambda_utils.ecommerce import service_requests as services
    variant = services.SERVICE_VARIANT_BY_KIND[services.DROP_DOCS]
    try:
        lambda_client.invoke(
            FunctionName='wecare-whatsapp-business-api:live',
            InvocationType='Event',
            Payload=json.dumps({
                'internalAction': 'catalogService',
                'action': 'start',
                'lines': [{
                    'productId': services.SERVICE_PRODUCT_BY_VARIANT[variant],
                    'variantId': variant,
                    'quantity': 1,
                }],
                'sourceMessageId': source_message_id,
                'contactId': contact_id,
                'senderPhone': sender_phone,
                'phoneNumberId': aws_phone_number_id,
            }).encode(),
        )
    except Exception as error:  # noqa: BLE001
        logger.warning(json.dumps({
            'event': 'drop_docs_payment_unrouted',
            'errorType': type(error).__name__,
            'requestId': request_id,
        }))
        return False
    logger.info(json.dumps({
        'event': 'drop_docs_payment_routed',
        'contactId': mask_contact_id(contact_id),
        'requestId': request_id,
    }))
    return True


def _route_vault_offer_tap(message: Dict, button_text_lower: str, contact_id: str,
                           sender_phone: str, aws_phone_number_id: str,
                           whatsapp_message_id: Optional[str], request_id: str) -> bool:
    """Hand an "Unlock Vault" tap to business-api `catalogService`. True when handled.

    The tap is a signed inbound message, so its message id is the identity evidence commerce's
    bridge checks, exactly as for a Vault catalog cart. WABA1 only, because only WABA1 may take a
    payment, and only while WHATSAPP_CATALOG_SERVICES_ENABLED is on; otherwise the tap falls
    through to the ordinary button handling. The payload is never trusted for anything but the
    lookup of the offer it names: business-api re-proves the customer and the file.
    """
    from lambda_utils import whatsapp_templates
    payload = str((message.get('button') or {}).get('payload') or '')
    prefix = whatsapp_templates.VAULT_OFFER_PAYLOAD_PREFIX
    if not payload.startswith(prefix) and button_text_lower != 'unlock vault':
        return False
    if (not whatsapp_message_id or aws_phone_number_id != PHONE_NUMBER_ID_1
            or os.environ.get('WHATSAPP_CATALOG_SERVICES_ENABLED', 'false').lower() != 'true'):
        return False
    from lambda_utils.ecommerce import service_requests as services
    variant = services.SERVICE_VARIANT_BY_KIND[services.VAULT]
    token = payload[len(prefix):] if payload.startswith(prefix) else ''
    if _may_send('vault_offer_tap'):
        try:
            lambda_client.invoke(
                FunctionName='wecare-whatsapp-business-api:live', InvocationType='Event',
                Payload=json.dumps({
                    'internalAction': 'catalogService', 'action': 'unlock' if token else 'start',
                    'offerToken': token,
                    'lines': [{'productId': services.SERVICE_PRODUCT_BY_VARIANT[variant],
                               'variantId': variant, 'quantity': 1}],
                    'sourceMessageId': whatsapp_message_id, 'contactId': contact_id,
                    'senderPhone': sender_phone, 'phoneNumberId': aws_phone_number_id}).encode())
        except Exception as error:  # noqa: BLE001 - logged; the tap must not crash the worker
            logger.warning(json.dumps({'event': 'vault_offer_tap_unrouted',
                                       'errorType': type(error).__name__,
                                       'requestId': request_id}))
            return False
    logger.info(json.dumps({'event': 'vault_offer_tap_routed', 'withOffer': bool(token),
                            'contactId': mask_contact_id(contact_id), 'requestId': request_id}))
    return True


def _extract_content(message: Dict, msg_type: str) -> str:
    """Extract message content based on type. Delegates to modules.content."""
    return _extract_content_v2(message, msg_type)


def _extract_unsupported_content(message: Dict) -> str:
    """Extract info from unsupported message types. Delegates to modules.content."""
    return _extract_unsupported_content_v2(message)


def _message_exists(whatsapp_message_id: str) -> bool:
    """Check if message already exists (deduplication) using GSI query."""
    if not whatsapp_message_id:
        return False
    try:
        messages_table = dynamodb.Table(MESSAGES_TABLE)
        response = messages_table.query(
            IndexName='whatsappMessageId-index',
            KeyConditionExpression='whatsappMessageId = :wmid',
            ExpressionAttributeValues={':wmid': whatsapp_message_id},
            Limit=1
        )
        return len(response.get('Items', [])) > 0
    except Exception as e:
        # Fallback to scan if GSI not ready yet
        logger.warning(f"GSI query failed, falling back to scan: {str(e)}")
        try:
            response = messages_table.scan(
                FilterExpression='whatsappMessageId = :wmid',
                ExpressionAttributeValues={':wmid': whatsapp_message_id},
                Limit=1
            )
            return len(response.get('Items', [])) > 0
        except Exception:
            return False


def _deterministic_contact_id(phone: str) -> str:
    """Stable, phone-derived contact id so ONE phone always maps to ONE contact
    (eliminates churn/duplicates from GSI eventual-consistency). Digits only."""
    digits = normalize_phone(phone) if phone else ''
    if not digits:
        digits = ''.join(c for c in (phone or '') if c.isdigit())
    return f'wa{digits}' if digits else ''


def _get_or_create_contact(phone: str, sender_name: str = '', bsuid: str = '', username: str = '', contact_book_name: str = '', parent_bsuid: str = '') -> Dict[str, Any]:
    """Get existing contact or create new one. Supports BSUID and parent BSUID lookup and storage.
    Uses a deterministic phone-derived id + strongly-consistent get_item so repeated
    inbound/outbound events never create duplicate (churned) contacts."""
    contacts_table = dynamodb.Table(CONTACTS_TABLE)

    # 0) Strongly-consistent lookup by deterministic phone id (no GSI lag / no churn)
    det_id = _deterministic_contact_id(phone)
    if det_id:
        try:
            r = contacts_table.get_item(Key={'id': det_id}, ConsistentRead=True)
            existing = r.get('Item')
            if existing and not existing.get('deletedAt'):
                _update_contact_bsuid_fields(contacts_table, existing, sender_name, username, phone, bsuid, contact_book_name, parent_bsuid)
                return existing
        except Exception as e:
            # `det_id` is `wa` + the customer's digits, so it is masked like any contact id.
            logger.warning(f"deterministic contact get failed for {mask_contact_id(det_id)}: "
                           f"{type(e).__name__}")

    # Try BSUID lookup first (most reliable identifier going forward)
    if bsuid:
        try:
            response = contacts_table.query(
                IndexName='bsuid-index',
                KeyConditionExpression='bsuid = :bsuid',
                ExpressionAttributeValues={':bsuid': bsuid},
                Limit=10
            )
            bsuid_items = [i for i in response.get('Items', []) if not i.get('deletedAt')]
            if bsuid_items:
                contact = sorted(bsuid_items, key=lambda x: x.get('createdAt', 0))[0]
                # Update name/username/phone if available and contact doesn't have them
                _update_contact_bsuid_fields(contacts_table, contact, sender_name, username, phone, contact_book_name=contact_book_name, parent_bsuid=parent_bsuid)
                return contact
        except Exception as e:
            logger.warning(f"BSUID index query failed for {bsuid}: {str(e)}")

    # Canonical resolver: follows merge aliases and skips deleted/merged rows, so it is the
    # right answer when a person has more than one historical row. It raises IdentityConflict
    # only when two LIVE rows both claim this phone; that is a data problem, not a reason to drop
    # the inbound message, so we log it (masked) and fall through to the oldest-row choice below.
    try:
        resolved = contact_store.lookup(contacts_table, phone)
    except contact_store.IdentityConflict as conflict:
        logger.warning(json.dumps({
            'event': 'contact_identity_conflict',
            'phone': mask_phone(phone),
            'detail': type(conflict).__name__,
            'bsuid': bsuid,
        }))
        resolved = None
    except Exception as e:
        logger.warning(f"contact_store.lookup failed for {mask_phone(phone)}: {type(e).__name__}")
        resolved = None
    if resolved and not resolved.get('deletedAt'):
        _update_contact_bsuid_fields(contacts_table, resolved, sender_name, username, phone, bsuid, contact_book_name, parent_bsuid)
        return resolved

    # Clean phone for search - normalize to digits-only E.164
    clean_phone = normalize_phone(phone) if phone else ''
    if not clean_phone:
        clean_phone = phone.lstrip('+') if phone else ''
    phone_with_plus = f'+{clean_phone}' if clean_phone else ''
    
    # Use GSI query on phone-index for O(1) lookup (try both formats)
    items = []
    if clean_phone:
        for phone_variant in [phone_with_plus, clean_phone]:
            try:
                response = contacts_table.query(
                    IndexName='phone-index',
                    KeyConditionExpression='phone = :phone',
                    ExpressionAttributeValues={':phone': phone_variant},
                    Limit=10
                )
                variant_items = response.get('Items', [])
                # Filter out deleted contacts
                variant_items = [i for i in variant_items if not i.get('deletedAt')]
                items.extend(variant_items)
            except Exception as e:
                logger.warning(f"GSI phone-index query failed for {mask_phone(phone_variant)}: "
                               f"{type(e).__name__}")
    
    # Fallback to scan if GSI not ready
    if not items and clean_phone:
        try:
            response = contacts_table.scan(
                FilterExpression='(phone = :phone1 OR phone = :phone2) AND (attribute_not_exists(deletedAt) OR deletedAt = :null)',
                ExpressionAttributeValues={
                    ':phone1': clean_phone,
                    ':phone2': phone_with_plus,
                    ':null': None
                },
                Limit=100
            )
            items = response.get('Items', [])
        except Exception:
            items = []
    
    if items:
        # Deduplicate by id in case both phone formats matched the same contact
        seen_ids = set()
        unique_items = []
        for item in items:
            item_id = item.get('id', '')
            if item_id not in seen_ids:
                seen_ids.add(item_id)
                unique_items.append(item)
        items = unique_items
        
        # Return the first (oldest) contact to avoid duplicates
        contact = sorted(items, key=lambda x: x.get('createdAt', 0))[0]
        # Update name/BSUID/username if available
        _update_contact_bsuid_fields(contacts_table, contact, sender_name, username, phone, bsuid, contact_book_name, parent_bsuid)
        return contact
    
    # Create new contact with a DETERMINISTIC phone-derived id (idempotent).
    contact_id = det_id or str(uuid.uuid4())
    now = int(time.time())

    # Ensure phone has + prefix for international format (easier for SMS)
    formatted_phone = ''
    if phone:
        formatted_phone = phone if phone.startswith('+') else f'+{phone}'

    contact = {
        **contact_key.contact_item_keys(contact_id),
        **subscriber_id.new_contact_fields(now=now),
        'name': sender_name or '',
        'phone': formatted_phone or None,
        'email': None,
        'bsuid': bsuid or None,  # Business-Scoped User ID
        'parentBsuid': parent_bsuid or None,  # Parent BSUID (linked account)
        'username': username or None,  # WhatsApp username
        'contactBookName': contact_book_name or None,  # Meta contact book name
        'optInWhatsApp': True,
        'optInSms': True,
        'optInEmail': True,
        'allowlistWhatsApp': True,
        'allowlistSms': True,
        'allowlistEmail': True,
        'lastInboundMessageAt': Decimal(str(now)),
        'createdAt': Decimal(str(now)),
        'updatedAt': Decimal(str(now)),
    }

    claims_table = dynamodb.Table(identity_claims.TABLE_NAME)
    try:
        identity_claims.claim_identities(
            claims_table, contact_id=contact_id, phone=formatted_phone, now=now)
    except identity_claims.IdentityClaimConflict:
        owner_id = identity_claims.owner(claims_table, 'PHONE', formatted_phone)
        if owner_id:
            owner = contacts_table.get_item(
                Key={'id': owner_id}, ConsistentRead=True).get('Item')
            if owner and contact_store.is_live(owner):
                _update_contact_bsuid_fields(
                    contacts_table, owner, sender_name, username, phone, bsuid,
                    contact_book_name, parent_bsuid)
                return owner
        raise

    try:
        contacts_table.put_item(
            Item={k: v for k, v in contact.items() if v is not None},
            ConditionExpression='attribute_not_exists(id)',
        )
        logger.info(json.dumps({
            'event': 'contact_auto_created', 'contactId': mask_contact_id(contact_id),
            'phone': mask_phone(phone), 'hasName': bool(sender_name), 'bsuid': bsuid, 'hasUsername': bool(username),
        }))
        return contact
    except Exception as e:
        # Race: another invocation created it first — fetch and reuse (no duplicate).
        if 'ConditionalCheckFailedException' in str(e):
            try:
                r = contacts_table.get_item(Key={'id': contact_id}, ConsistentRead=True)
                existing = r.get('Item')
                if existing:
                    _update_contact_bsuid_fields(contacts_table, existing, sender_name, username, phone, bsuid, contact_book_name, parent_bsuid)
                    return existing
            except Exception:
                pass
        else:
            logger.warning(json.dumps({'event': 'contact_create_error', 'error': str(e), 'contactId': mask_contact_id(contact_id)}))
        return contact


def _update_contact_bsuid_fields(contacts_table, contact: Dict, sender_name: str, username: str, phone: str = '', bsuid: str = '', contact_book_name: str = '', parent_bsuid: str = '') -> None:
    """Update contact with BSUID, parentBsuid, username, contactBookName, and name if they're new or changed."""
    updates = {}
    names = {}
    values = {}
    idx = 0
    
    current_name = contact.get('name', '')
    if sender_name and (not current_name or current_name in ['', '~', 'Unknown']):
        updates[f'#n{idx}'] = 'name'
        names[f'#n{idx}'] = 'name'
        values[f':v{idx}'] = sender_name
        contact['name'] = sender_name
        idx += 1
    
    if bsuid and not contact.get('bsuid'):
        names[f'#n{idx}'] = 'bsuid'
        values[f':v{idx}'] = bsuid
        contact['bsuid'] = bsuid
        idx += 1
    
    # Store parent BSUID if provided and different from current
    if parent_bsuid and contact.get('parentBsuid') != parent_bsuid:
        names[f'#n{idx}'] = 'parentBsuid'
        values[f':v{idx}'] = parent_bsuid
        contact['parentBsuid'] = parent_bsuid
        idx += 1
    
    if username and contact.get('username') != username:
        names[f'#n{idx}'] = 'username'
        values[f':v{idx}'] = username
        contact['username'] = username
        idx += 1
    
    # If contact has no phone but we have one now (BSUID-first contact getting phone)
    if phone and not contact.get('phone'):
        formatted = phone if phone.startswith('+') else f'+{phone.lstrip("+")}'
        names[f'#n{idx}'] = 'phone'
        values[f':v{idx}'] = formatted
        contact['phone'] = formatted
        idx += 1
    
    # Update contactBookName if provided and different
    if contact_book_name and contact.get('contactBookName') != contact_book_name:
        names[f'#n{idx}'] = 'contactBookName'
        values[f':v{idx}'] = contact_book_name
        contact['contactBookName'] = contact_book_name
        idx += 1
    
    if not names:
        return
    
    values[':now'] = Decimal(str(int(time.time())))
    names['#updatedAt'] = 'updatedAt'
    set_parts = [f'{k} = :v{i}' for i, k in enumerate(names.keys()) if k != '#updatedAt']
    set_parts.append('#updatedAt = :now')
    
    try:
        contacts_table.update_item(
            Key={'id': contact.get('id')},
            UpdateExpression='SET ' + ', '.join(set_parts),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            ConditionExpression='attribute_exists(id)',
        )
    except Exception as e:
        logger.warning(json.dumps({
            'event': 'contact_bsuid_update_failed',
            'contactId': mask_contact_id(contact.get('id', '')),
            'error': str(e),
        }))


def _process_user_id_update(uid_update: Dict, contacts_map: Dict, request_id: str) -> None:
    """
    Handle user_id_update webhook  -  a user's BSUID has changed.
    Per Meta docs (field: user_id_update), the payload contains:
      user_id: { previous: "<OLD_BSUID>", current: "<NEW_BSUID>" }
      parent_user_id: { previous: "<OLD>", current: "<NEW>" }  (optional)
      wa_id: "<PHONE>" (optional)
    Updates the contact's BSUID and parentBsuid in DynamoDB.
    """
    user_id_obj = uid_update.get('user_id', {})
    old_user_id = user_id_obj.get('previous', '')
    new_user_id = user_id_obj.get('current', '')
    parent_id_obj = uid_update.get('parent_user_id', {})
    new_parent_id = parent_id_obj.get('current', '') if isinstance(parent_id_obj, dict) else ''
    wa_id = uid_update.get('wa_id', '')
    
    if not old_user_id or not new_user_id:
        logger.warning(json.dumps({
            'event': 'user_id_update_missing_ids',
            'old_user_id': old_user_id,
            'new_user_id': new_user_id,
            'requestId': request_id,
        }))
        return
    
    logger.info(json.dumps({
        'event': 'user_id_update_processing',
        'old_user_id': old_user_id,
        'new_user_id': new_user_id,
        'new_parent_id': new_parent_id,
        'requestId': request_id,
    }))
    
    contacts_table = dynamodb.Table(CONTACTS_TABLE)
    
    # Find contact by old BSUID
    try:
        response = contacts_table.query(
            IndexName='bsuid-index',
            KeyConditionExpression='bsuid = :bsuid',
            ExpressionAttributeValues={':bsuid': old_user_id},
            Limit=10
        )
        items = [i for i in response.get('Items', []) if not i.get('deletedAt')]
        
        if not items:
            logger.warning(json.dumps({
                'event': 'user_id_update_contact_not_found',
                'old_user_id': old_user_id,
                'requestId': request_id,
            }))
            return
        
        for contact in items:
            update_expr = 'SET bsuid = :new_bsuid, updatedAt = :now'
            expr_vals = {
                ':new_bsuid': new_user_id,
                ':now': Decimal(str(int(time.time()))),
            }
            # Also update parentBsuid if provided
            if new_parent_id:
                update_expr += ', parentBsuid = :new_parent'
                expr_vals[':new_parent'] = new_parent_id
            
            contacts_table.update_item(
                Key={'id': contact['id']},
                UpdateExpression=update_expr,
                ExpressionAttributeValues=expr_vals,
            )
            logger.info(json.dumps({
                'event': 'user_id_updated',
                'contactId': mask_contact_id(contact['id']),
                'old_bsuid': old_user_id,
                'new_bsuid': new_user_id,
                'new_parent_bsuid': new_parent_id,
                'requestId': request_id,
            }))
    except Exception as e:
        logger.error(json.dumps({
            'event': 'user_id_update_failed',
            'old_user_id': old_user_id,
            'new_user_id': new_user_id,
            'error': str(e),
            'requestId': request_id,
        }))


def _process_business_username_update(value: Dict, request_id: str) -> None:
    """Handle business_username_updates webhook — our business username status changed.

    Payload (per Meta BSUID doc): { display_phone_number, username, status }
    status: approved | reserved | deleted. Stores a SystemEvent and logs the
    status so the username claim lifecycle is observable end-to-end.
    """
    display_phone = value.get('display_phone_number', '')
    username = value.get('username', '')
    status = (value.get('status') or '').lower()

    # Audit trail (kept for the dashboard).
    _store_system_event('business_username_updates', value, request_id)

    logger.info(json.dumps({
        'event': 'business_username_update',
        'displayPhoneNumber': display_phone[:6] + '***' if display_phone else '',
        'username': username,
        'status': status,
        'requestId': request_id,
    }))

    # Best-effort: reflect the live username/status onto the FlowRegistry-adjacent
    # phone config if a WhatsAppPhone record exists (non-fatal if table absent).
    try:
        if status in ('approved', 'reserved', 'deleted') and display_phone:
            phones_table = dynamodb.Table(os.environ.get('WHATSAPP_PHONES_TABLE', 'stack-wecare-digital-WhatsAppPhonesTable'))
            phones_table.update_item(
                Key={'displayPhoneNumber': display_phone},
                UpdateExpression='SET businessUsername = :u, businessUsernameStatus = :s, updatedAt = :now',
                ExpressionAttributeValues={
                    ':u': '' if status == 'deleted' else username,
                    ':s': status,
                    ':now': Decimal(str(int(time.time()))),
                },
            )
    except Exception as e:
        # Table/record may not exist — the SystemEvent above is the source of truth.
        logger.info(json.dumps({
            'event': 'business_username_phone_update_skipped',
            'reason': str(e)[:160],
            'requestId': request_id,
        }))


def _update_contact_timestamp(contact_id: str, timestamp: int, wamid: str = '') -> None:
    """Update contact's lastInboundMessageAt for 24-hour window tracking.
    Also stores the latest inbound WAMID so outbound can show a typing indicator
    (Meta's typing_indicator API requires the customer's last received message_id)."""
    try:
        contacts_table = dynamodb.Table(CONTACTS_TABLE)
        # Conditional on the row already existing: an unconditional update_item would UPSERT a
        # stub contact (id + timestamps, no phone/opt-in fields) for any id that no longer exists,
        # e.g. after a merge. A missing row means there is nothing to touch, so we let the
        # condition fail and swallow it rather than minting a ghost.
        if wamid:
            contacts_table.update_item(
                Key={'id': contact_id},
                UpdateExpression='SET lastInboundMessageAt = :ts, updatedAt = :ts, lastInboundWamid = :w',
                ExpressionAttributeValues={':ts': Decimal(str(timestamp)), ':w': wamid},
                ConditionExpression='attribute_exists(id)',
            )
        else:
            contacts_table.update_item(
                Key={'id': contact_id},
                UpdateExpression='SET lastInboundMessageAt = :ts, updatedAt = :ts',
                ExpressionAttributeValues={':ts': Decimal(str(timestamp))},
                ConditionExpression='attribute_exists(id)',
            )
    except ClientError as e:
        if e.response.get('Error', {}).get('Code') == 'ConditionalCheckFailedException':
            # No such contact row (merged/deleted). Nothing to update; not an error.
            return
        logger.error(f"Failed to update contact timestamp: {str(e)}")
    except Exception as e:
        logger.error(f"Failed to update contact timestamp: {str(e)}")


def _download_media_direct_api(whatsapp_media_id: str, message_id: str, media_type: str,
                               phone_number_id: str, request_id: str,
                               mime_type_hint: str = '') -> Optional[str]:
    """Download media via Meta Graph API for Direct API phones."""
    token = _load_direct_api_token()
    if not token:
        logger.error("No Direct API token for media download")
        return None
    app_secret = _direct_api_token_cache.get('app_secret', '')
    
    try:
        # Step 1: Get media URL from Meta
        url = f"https://graph.facebook.com/{META_API_VERSION}/{whatsapp_media_id}"
        if app_secret:
            proof = hmac.new(app_secret.encode(), token.encode(), hashlib.sha256).hexdigest()
            url = f"{url}?appsecret_proof={proof}"
        req = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            media_info = json.loads(resp.read().decode())
        
        media_url = media_info.get('url', '')
        mime_type = media_info.get('mime_type', mime_type_hint)
        if not media_url:
            logger.error(f"No media URL returned for {whatsapp_media_id}")
            return None
        
        # Step 2: Download the actual media file
        req2 = urllib.request.Request(media_url, headers={'Authorization': f'Bearer {token}'})
        with urllib.request.urlopen(req2, timeout=30) as resp2:
            media_bytes = resp2.read()
        
        # Step 3: Upload to S3
        ext = _get_media_extension_from_mime(mime_type)
        s3_key = f"{MEDIA_PREFIX}wecare-digital-{message_id}{ext}"
        s3.put_object(Bucket=MEDIA_BUCKET, Key=s3_key, Body=media_bytes, ContentType=mime_type)
        
        logger.info(json.dumps({
            'event': 'media_download_direct_api',
            'mediaId': whatsapp_media_id,
            's3Key': s3_key,
            'size': len(media_bytes),
            'mimeType': mime_type,
            'requestId': request_id
        }))
        return s3_key
    except Exception as e:
        logger.error(f"Direct API media download failed: {e}")
        return None


def _get_media_extension_from_mime(mime_type: str) -> str:
    """Get file extension from MIME type.

    Delegates to `_get_extension_from_mime` so there is one inbound MIME→ext table
    rather than three that drift. This wrapper previously carried a shorter copy that
    dropped audio/amr, audio/mp4, text/plain, ppt and pptx to '.bin' (a .bin landed a
    wrong display filename and broke the inbox's extension-driven document link).
    """
    return _get_extension_from_mime(mime_type)


def _download_media(whatsapp_media_id: str, message_id: str, media_type: str, 
                    phone_number_id: str, request_id: str,
                    mime_type_hint: str = '') -> Optional[str]:
    """
    Download media file from WhatsApp.
    Routes to Direct API for all phones.
    
    Per AWS docs (S3File.key): The key is a PREFIX  -  AWS appends the WhatsApp
    mediaId to create the final file path. For example:
      key = "audio/"             → final = "audio/{mediaId}.ogg"
    
    Strategy: Use MEDIA_PREFIX directly (ending with "/") so files land flat
    under secure/d/public/whatsapp/incoming/{mediaId}.{ext}, then rename to
    wecare-digital-{uuid}.{ext} format.
    
    Returns the actual S3 key of the downloaded file.
    """
    # Route Direct API phones to Meta Graph API download
    if _is_direct_api_phone(phone_number_id):
        return _download_media_direct_api(
            whatsapp_media_id, message_id, media_type,
            phone_number_id=phone_number_id,
            request_id=request_id,
            mime_type_hint=mime_type_hint,
        )
    
    try:
        # Use MEDIA_PREFIX directly  -  files land flat, no subfolders
        s3_key_prefix = MEDIA_PREFIX  # media_paths.WHATSAPP_INCOMING_PREFIX
        
        logger.info(json.dumps({
            'event': 'media_download_start',
            'mediaId': whatsapp_media_id,
            's3KeyPrefix': s3_key_prefix,
            'mediaType': media_type,
            'mimeTypeHint': mime_type_hint,
            'phoneNumberId': phone_number_id,
            'requestId': request_id
        }))
        
        # Download media via Meta Graph API: GET /{media_id} → get URL → download → upload to S3
        meta_pid = _get_meta_phone_id_for_direct_api(phone_number_id)
        token = _load_direct_api_token()
        app_secret = _direct_api_token_cache.get('app_secret', '')

        # Step 1: Get media URL from Meta
        media_url_endpoint = f"https://graph.facebook.com/{META_API_VERSION}/{whatsapp_media_id}"
        if app_secret:
            proof = hmac.new(app_secret.encode(), token.encode(), hashlib.sha256).hexdigest()
            media_url_endpoint = f"{media_url_endpoint}?appsecret_proof={proof}"
        media_req = urllib.request.Request(media_url_endpoint, headers={
            'Authorization': f'Bearer {token}',
        })
        with urllib.request.urlopen(media_req, timeout=15) as media_resp:
            media_info = json.loads(media_resp.read().decode())
        media_download_url = media_info.get('url', '')
        mime_type = media_info.get('mime_type', mime_type_hint or '')
        file_size = media_info.get('file_size', 0)

        # Step 2: Download the actual media file
        dl_req = urllib.request.Request(media_download_url, headers={
            'Authorization': f'Bearer {token}',
        })
        with urllib.request.urlopen(dl_req, timeout=60) as dl_resp:
            media_bytes = dl_resp.read()

        # Step 3: Determine extension and upload to S3. Use the one shared inbound
        # MIME→ext table (full Meta set) rather than a short inline copy that dropped
        # 3gp/amr/m4a/txt/doc/xls/xlsx/ppt/pptx to no-extension. '' only when the MIME
        # is genuinely unknown; the rename below then re-derives from the type.
        ext = _get_extension_from_mime(mime_type) if mime_type else ''
        actual_s3_key = f"{s3_key_prefix}{whatsapp_media_id}{ext}"
        s3.put_object(
            Bucket=MEDIA_BUCKET,
            Key=actual_s3_key,
            Body=media_bytes,
            ContentType=mime_type or 'application/octet-stream',
        )
        
        # Rename to wecare-digital-{uuid}.{ext} format (flat, no nesting)
        ext = _get_extension_from_mime(mime_type) if mime_type else _get_extension_from_type(media_type)
        short_id = uuid.uuid4().hex[:8]
        renamed_key = f"{MEDIA_PREFIX}wecare-digital-{short_id}{ext}"
        try:
            s3.copy_object(
                Bucket=MEDIA_BUCKET,
                CopySource={'Bucket': MEDIA_BUCKET, 'Key': actual_s3_key},
                Key=renamed_key
            )
            s3.delete_object(Bucket=MEDIA_BUCKET, Key=actual_s3_key)
            logger.info(json.dumps({
                'event': 'media_renamed',
                'originalKey': actual_s3_key,
                'renamedKey': renamed_key,
                'requestId': request_id
            }))
            actual_s3_key = renamed_key
        except Exception as rename_err:
            logger.warning(json.dumps({
                'event': 'media_rename_failed',
                'originalKey': actual_s3_key,
                'targetKey': renamed_key,
                'error': str(rename_err),
                'requestId': request_id
            }))
        
        logger.info(json.dumps({
            'event': 'media_downloaded',
            'mediaId': whatsapp_media_id,
            's3KeyPrefix': s3_key_prefix,
            'actualS3Key': actual_s3_key,
            'mimeType': mime_type,
            'fileSize': file_size,
            'phoneNumberId': phone_number_id,
            'requestId': request_id
        }))
        
        return actual_s3_key
        
    except Exception as e:
        logger.error(json.dumps({
            'event': 'media_download_error',
            'mediaId': whatsapp_media_id,
            'error': str(e),
            'requestId': request_id
        }))
        return None


def _get_extension_from_type(media_type: str) -> str:
    """
    Get file extension based on WhatsApp message type.
    Used as fallback when mime_type is not available.
    
    Supported types per WhatsApp Business Platform Cloud API:
    - image: JPEG (5MB), PNG (5MB)
    - video: MP4 (16MB), 3GPP (16MB)
    - audio: AAC (16MB), AMR (16MB), MP3 (16MB), M4A (16MB), OGG (16MB)
    - document: PDF, TXT, DOC/DOCX, XLS/XLSX, PPT/PPTX (100MB)
    - sticker: WEBP (500KB animated, 100KB static)
    """
    type_extensions = {
        'image': '.jpeg',
        'video': '.mp4',
        'audio': '.ogg',
        'document': '.pdf',
        'sticker': '.webp'
    }
    return type_extensions.get(media_type, '.bin')


def _get_extension_from_mime(mime_type: str) -> str:
    """
    Get file extension based on MIME type.
    Complete mapping per WhatsApp Business Platform supported media types.
    """
    mime_extensions = {
        # Image formats (max 5MB)
        'image/jpeg': '.jpeg',
        'image/png': '.png',
        
        # Sticker formats (max 500KB animated, 100KB static)
        'image/webp': '.webp',
        
        # Video formats (max 16MB)
        'video/mp4': '.mp4',
        'video/3gpp': '.3gp',
        
        # Audio formats (max 16MB)
        'audio/aac': '.aac',
        'audio/amr': '.amr',
        'audio/mpeg': '.mp3',
        'audio/mp4': '.m4a',
        'audio/ogg': '.ogg',
        'audio/opus': '.opus',
        
        # Document formats (max 100MB)
        'application/pdf': '.pdf',
        'text/plain': '.txt',
        'application/msword': '.doc',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
        'application/vnd.ms-excel': '.xls',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
        'application/vnd.ms-powerpoint': '.ppt',
        'application/vnd.openxmlformats-officedocument.presentationml.presentation': '.pptx',
    }
    return mime_extensions.get(mime_type, '.bin')


def _store_media_record(message_id: str, s3_key: str, media_data: Dict, whatsapp_media_id: str) -> Optional[str]:
    """
    Store media file record in MediaFiles table.
    Returns file_id if successful, None if table doesn't exist or write fails.
    This is optional - the s3Key is stored directly in the message record.
    """
    try:
        file_id = str(uuid.uuid4())
        now = int(time.time())
        
        media_record = {
            # MediaFilesTable's hash key is `id`, not `fileId`. Without it every
            # put_item failed with `ValidationException: Missing the key id` - 17 out
            # of 17 writes in the seven days to 2026-10-06 - and the failure was
            # swallowed by the except below as "the table may not exist", so nothing
            # ever surfaced. The visible consequence was downstream: `mediaId` stayed
            # null on the message, and the daily Meta media-DELETE cron
            # (`wecare-media-cleanup`) scanned an empty table and deleted nothing,
            # every day, reporting success. `fileId` is kept alongside for any reader
            # written against the old shape.
            'id': file_id,
            'fileId': file_id,
            'messageId': message_id,
            's3Key': s3_key,
            'contentType': media_data.get('mime_type', ''),
            'size': Decimal(str(media_data.get('file_size', 0))) if media_data.get('file_size') else None,
            'whatsappMediaId': whatsapp_media_id,
            'uploadedAt': Decimal(str(now)),
        }
        
        media_table = dynamodb.Table(MEDIA_FILES_TABLE)
        media_table.put_item(Item={k: v for k, v in media_record.items() if v is not None})
        
        logger.info(json.dumps({
            'event': 'media_record_stored',
            'fileId': file_id,
            'messageId': message_id,
            's3Key': s3_key
        }))
        
        return file_id
    except Exception as e:
        # MediaFile table may not exist - this is OK, s3Key is stored in message record
        logger.warning(json.dumps({
            'event': 'media_record_store_skipped',
            'messageId': message_id,
            's3Key': s3_key,
            'error': str(e),
            'note': 'MediaFile table write failed, but s3Key is stored in message record'
        }))
        return None


def _attach_whatsapp_document_to_pending_dropdocs(
    sender_phone: str, sender_name: str, contact_id: str, message_id: str,
    whatsapp_media_id: str, s3_key: str, msg_type: str,
    mime_type: str, filename: str, file_size: int, request_id: str,
) -> bool:
    """Bind WhatsApp media only to an explicit, recent Drop Docs upload target.

    Ordinary Inbox images/documents remain conversation media. They must not become
    business DocumentTable rows merely because their MIME type looks document-like.
    The Drop Docs flow places a two-hour target on the contact; this consumes it once.
    """
    if not contact_id or not s3_key:
        return False

    now = int(time.time())
    try:
        contact = dynamodb.Table(CONTACTS_TABLE).get_item(
            Key={'id': contact_id}, ConsistentRead=True).get('Item') or {}
        doc_id = str(contact.get('pendingDocumentSubmissionId') or '').strip()
        try:
            opened = int(contact.get('pendingDocumentSubmissionAt') or 0)
        except (TypeError, ValueError):
            opened = 0
        if not doc_id or opened <= 0 or now - opened < 0 or now - opened > 2 * 3600:
            return False

        doc_table = dynamodb.Table(
            os.environ.get('DOCUMENTS_TABLE', 'stack-wecare-digital-DocumentTable'))
        doc = doc_table.get_item(Key={'documentId': doc_id}, ConsistentRead=True).get('Item') or {}
        if not doc:
            return False
        if str(doc.get('contactId') or '') != str(contact_id):
            logger.warning(json.dumps({
                'event': 'dropdocs_media_owner_mismatch',
                'documentId': doc_id, 'requestId': request_id,
            }))
            return False
        if str(doc.get('sourceType') or '') != 'flow':
            return False

        existing_key = str(doc.get('storageKey') or '')
        existing_ref = str(doc.get('sourceReferenceId') or '')
        if existing_key:
            return existing_ref == whatsapp_media_id

        doc_table.update_item(
            Key={'documentId': doc_id},
            UpdateExpression=(
                'SET storageKey=:key, sourceReferenceId=:ref, fileName=:name, '
                'mimeType=:mime, fileSize=:size, verificationStatus=:uploaded, '
                'uploadedAt=:now, updatedAt=:now'
            ),
            ConditionExpression=(
                'contactId=:cid AND sourceType=:flow AND attribute_not_exists(storageKey)'
            ),
            ExpressionAttributeValues={
                ':key': s3_key,
                ':ref': whatsapp_media_id,
                ':name': filename or f'{msg_type}_{message_id[:8]}',
                ':mime': mime_type or '',
                ':size': int(file_size or 0),
                ':uploaded': 'uploaded',
                ':now': now,
                ':cid': contact_id,
                ':flow': 'flow',
            },
        )

        try:
            dynamodb.Table(CONTACTS_TABLE).update_item(
                Key={'id': contact_id},
                UpdateExpression='REMOVE pendingDocumentSubmissionId, pendingDocumentSubmissionAt',
                ConditionExpression='pendingDocumentSubmissionId=:doc',
                ExpressionAttributeValues={':doc': doc_id},
            )
        except Exception:
            pass

        logger.info(json.dumps({
            'event': 'dropdocs_media_attached',
            'documentId': doc_id,
            'messageId': message_id,
            'requestId': request_id,
        }))
        return True
    except ClientError as exc:
        code = str((exc.response.get('Error') or {}).get('Code') or '')
        if code != 'ConditionalCheckFailedException':
            logger.warning(json.dumps({
                'event': 'dropdocs_media_attach_failed',
                'errorType': type(exc).__name__, 'requestId': request_id,
            }))
        return False
    except Exception as exc:
        logger.warning(json.dumps({
            'event': 'dropdocs_media_attach_failed',
            'errorType': type(exc).__name__, 'requestId': request_id,
        }))
        return False

def _meter_partner_usage(status: Dict, waba_id: str, request_id: str) -> None:
    """Charge a partner (Embedded-Signup) tenant's prepaid wallet for a billable
    message. No-op for platform-owned numbers (no wallet). Never raises."""
    if not partner_billing or not waba_id:
        return
    try:
        pricing = status.get('pricing', {}) or {}
        billable = pricing.get('billable', False)
        # Charge once per message on the 'sent' status (which carries pricing).
        if status.get('status') != 'sent' or not billable:
            return
        category = pricing.get('category', '') or ''
        msg_id = status.get('id', '')
        # Idempotency: charge once per message even if the 'sent' webhook is redelivered.
        try:
            from lambda_utils.webhook_dedup import claim_event
            if msg_id and not claim_event(f'meter_{msg_id}', source='partner_meter'):
                return
        except Exception:  # noqa: BLE001 — dedup must never block real metering
            pass
        res = partner_billing.charge(waba_id, category=category, message_id=msg_id,
                                     note='wa message', to_number=status.get('recipient_id', ''))
        if res.get('charged'):
            logger.info(json.dumps({'event': 'partner_usage_charged', 'wabaId': waba_id,
                                    'category': category, 'amount': res.get('amount'),
                                    'balance': res.get('balance'), 'requestId': request_id}))
    except Exception as e:  # noqa: BLE001
        logger.warning(json.dumps({'event': 'partner_metering_error', 'wabaId': waba_id, 'error': str(e)}))


def _process_status(status: Dict, request_id: str, contacts_map: Dict = None, waba_id: str = '') -> None:
    """
    Process message status update (sent|delivered|read|failed|payment).
    Checks BOTH InboundTable and OutboundTable using GSI for O(1) lookup.
    Extracts BSUID (recipient_user_id) and parent_recipient_user_id from status webhooks.
    
    Per Meta BSUID docs (Mar 2026): status webhooks now include a contacts array
    with user_id, username, wa_id, parent_user_id for sent/delivered/read statuses.
    
    Payment status webhooks have type='payment' with payment object containing:
    - reference_id: Order/invoice reference
    - amount: {value, offset}
    - currency: INR
    - status: pending|captured|failed
    """
    whatsapp_message_id = status.get('id')
    status_value = status.get('status')
    status_type = status.get('type', '')  # 'payment' for payment webhooks
    timestamp = int(status.get('timestamp', time.time()))
    recipient_id = status.get('recipient_id', '')
    recipient_user_id = status.get('recipient_user_id', '')  # BSUID
    parent_recipient_user_id = status.get('parent_recipient_user_id', '')  # Parent BSUID
    opaque_message_id = str(status.get('biz_opaque_callback_data') or '').strip()
    if not (opaque_message_id.startswith('wa-idem-') and len(opaque_message_id) <= 96
            and all(32 <= ord(ch) < 127 for ch in opaque_message_id)):
        opaque_message_id = ''
    
    # Log all status updates for debugging. The SHAPE of the status, never its values:
    # `recipient_id` is the customer's phone number, and the full object also carries the BSUID,
    # Meta's error details and the payment object. Error codes are enough to debug a failure.
    logger.info(json.dumps({
        'event': 'status_update_received',
        'statusType': status_type,
        'statusValue': status_value,
        'whatsappMessageId': whatsapp_message_id,
        'recipientId': mask_phone(recipient_id),
        'hasPaymentData': 'payment' in status,
        'hasOpaqueCorrelation': bool(opaque_message_id),
        'statusKeys': sorted(status) if isinstance(status, dict) else [],
        'errorCodes': [e.get('code') for e in (status.get('errors') or [])
                       if isinstance(e, dict)],
        'requestId': request_id
    }))
    
    # Handle payment status webhooks FIRST (before other checks)
    if status_type == 'payment' or 'payment' in status:
        _process_payment_status(status, request_id)
        return
    
    if not whatsapp_message_id or not status_value:
        return

    # Meter partner (Embedded-Signup) tenant usage against their prepaid wallet.
    # No-op for platform-owned numbers. Guarded — never breaks status processing.
    _meter_partner_usage(status, waba_id, request_id)
    
    # Search BOTH tables for the message using GSI
    OUTBOUND_TABLE = os.environ.get('OUTBOUND_TABLE', 'stack-wecare-digital-WhatsAppOutboundTable')
    tables_to_check = [
        ('inbound', MESSAGES_TABLE),
        ('outbound', OUTBOUND_TABLE),
    ]
    
    updated = False
    for direction, table_name in tables_to_check:
        try:
            table = dynamodb.Table(table_name)
            
            # A keyed send may time out after Meta accepts it, so the sender can miss the
            # WAMID. Meta echoes biz_opaque_callback_data on status webhooks; use that stable
            # internal id first, then fall back to the WAMID GSI for all ordinary sends.
            items = []
            if opaque_message_id:
                direct = table.get_item(Key={'id': opaque_message_id}, ConsistentRead=True).get('Item')
                if direct:
                    items = [direct]
            if not items:
                try:
                    response = table.query(
                        IndexName='whatsappMessageId-index',
                        KeyConditionExpression='whatsappMessageId = :wmid',
                        ExpressionAttributeValues={':wmid': whatsapp_message_id},
                        Limit=1
                    )
                except Exception:
                    # Fallback to scan if GSI not ready.
                    response = table.scan(
                        FilterExpression='whatsappMessageId = :wmid',
                        ExpressionAttributeValues={':wmid': whatsapp_message_id},
                        Limit=1
                    )
                items = response.get('Items', [])
            if items:
                message_id = items[0].get('id') or items[0].get('messageId')
                # Build update expression  -  include recipientBsuid and parentRecipientBsuid if available
                #
                # statusRank makes the write MONOTONIC. Meta guarantees neither
                # order nor exactly-once delivery of status webhooks, and this
                # used to be an unconditional SET, so the last webhook to arrive
                # won whatever it said: a late `sent` overwrote `read`, and a
                # re-delivered `failed` overwrote `delivered`. The rank plus the
                # ConditionExpression below refuse any backward transition, which
                # also makes duplicate deliveries harmless. See lambda_utils/wa_status.py
                # for the ranking and why `failed` sits between sent and delivered.
                update_expr = ('SET #status = :status, statusUpdatedAt = :ts, '
                               f'{wa_status.RANK_ATTRIBUTE} = :rank')
                expr_values = {
                    ':status': status_value,
                    ':ts': Decimal(str(timestamp)),
                    ':rank': Decimal(str(wa_status.rank(status_value))),
                }
                if opaque_message_id and whatsapp_message_id:
                    update_expr += ', whatsappMessageId = :wmid'
                    expr_values[':wmid'] = whatsapp_message_id
                if recipient_user_id:
                    update_expr += ', recipientBsuid = :rbsuid'
                    expr_values[':rbsuid'] = recipient_user_id
                if parent_recipient_user_id:
                    update_expr += ', parentRecipientBsuid = :prbsuid'
                    expr_values[':prbsuid'] = parent_recipient_user_id

                # Delivery-time failure: capture Meta error code + reason so the
                # inbox can show a tooltip explaining why the message wasn't
                # delivered (e.g. 131026 undeliverable, 131047 re-engagement).
                if status_value == 'failed':
                    status_errors = status.get('errors', []) or []
                    if status_errors:
                        e0 = status_errors[0]
                        err_code = e0.get('code')
                        err_reason = (e0.get('title') or e0.get('message')
                                      or (e0.get('error_data', {}) or {}).get('details', '') or '')
                        if err_code is not None:
                            update_expr += ', errorCode = :ec'
                            expr_values[':ec'] = int(err_code)
                        if err_reason:
                            update_expr += ', errorDetails = :ed'
                            expr_values[':ed'] = json.dumps({'code': err_code, 'message': err_reason})

                try:
                    table.update_item(
                        Key={'id': message_id},
                        UpdateExpression=update_expr,
                        ConditionExpression=wa_status.condition_expression(),
                        ExpressionAttributeNames={'#status': 'status'},
                        ExpressionAttributeValues=expr_values
                    )
                except ClientError as _ce:
                    if _ce.response.get('Error', {}).get('Code') != 'ConditionalCheckFailedException':
                        raise
                    # A backward or duplicate transition. Not an error: it is the
                    # guard doing its job. Recorded so out-of-order delivery is
                    # observable rather than invisible.
                    logger.info(json.dumps({
                        'event': 'status_out_of_order_skipped',
                        'messageId': message_id,
                        'whatsappMessageId': whatsapp_message_id,
                        'incomingStatus': status_value,
                        'incomingRank': wa_status.rank(status_value),
                        'table': direction,
                        'requestId': request_id,
                    }))
                    updated = True
                    break

                # Mirror the same status onto the canonical MessagesTable (same id,
                # written by the dual-write). Guarded — never breaks status processing.
                # The rank guard is ANDed with the existence check so the mirror
                # cannot regress either.
                if table_name != UNIFIED_MESSAGES_TABLE:
                    try:
                        dynamodb.Table(UNIFIED_MESSAGES_TABLE).update_item(
                            Key={'id': message_id},
                            UpdateExpression=update_expr,
                            ConditionExpression=(
                                'attribute_exists(id) AND ('
                                + wa_status.condition_expression() + ')'
                            ),
                            ExpressionAttributeNames={'#status': 'status'},
                            ExpressionAttributeValues=expr_values
                        )
                    except Exception as _ue:
                        logger.debug(f'canonical status mirror skipped for {message_id}: {_ue}')
                
                logger.info(json.dumps({
                    'event': 'status_updated',
                    'messageId': message_id,
                    'whatsappMessageId': whatsapp_message_id,
                    'status': status_value,
                    'statusRank': wa_status.rank(status_value),
                    'table': direction,
                    'requestId': request_id
                }))
                updated = True
                break  # Found and updated, no need to check other table
                
        except Exception as e:
            logger.error(json.dumps({
                'event': 'status_update_error',
                'whatsappMessageId': whatsapp_message_id,
                'table': direction,
                'error': str(e),
                'requestId': request_id
            }))
    
    if not updated:
        # Downgrade to debug  -  this is normal for auto-reaction/read-receipt messages
        # which are not stored in the outbound table
        logger.debug(json.dumps({
            'event': 'status_update_message_not_found',
            'whatsappMessageId': whatsapp_message_id,
            'status': status_value,
            'requestId': request_id
        }))
    
    # Enrich contact records from status webhook contacts array
    # Per Meta BSUID docs: sent/delivered/read status webhooks include a contacts
    # array with user_id (BSUID), username, wa_id, parent_user_id
    if contacts_map and status_value in ('sent', 'delivered', 'read'):
        for ckey, centry in contacts_map.items():
            if not isinstance(centry, dict):
                continue
            c_bsuid = centry.get('bsuid', '')
            c_username = centry.get('username', '')
            c_phone = centry.get('wa_id', '') if 'wa_id' in centry else ''
            c_parent_bsuid = centry.get('parent_bsuid', '')
            if not c_bsuid:
                continue
            try:
                # Try to find contact by BSUID and update username/phone if new
                contacts_table = dynamodb.Table(CONTACTS_TABLE)
                bsuid_resp = contacts_table.query(
                    IndexName='bsuid-index',
                    KeyConditionExpression='bsuid = :b',
                    ExpressionAttributeValues={':b': c_bsuid},
                    Limit=1
                )
                if bsuid_resp.get('Items'):
                    existing = bsuid_resp['Items'][0]
                    _update_contact_bsuid_fields(
                        contacts_table, existing,
                        sender_name=centry.get('name', ''),
                        username=c_username,
                        phone=c_phone,
                        bsuid=c_bsuid,
                        parent_bsuid=c_parent_bsuid,
                    )
            except Exception as enrich_err:
                logger.debug(f'Status contact enrichment skipped: {enrich_err}')


def _sanitize_reference_id(reference_id: str) -> str:
    """
    Normalise an INBOUND reference_id for lookup and display.

    This is the read side: the value arrives from Meta or Razorpay and is used to resolve a
    payment attempt we created. So the safest possible behaviour is to change it as little as
    possible, and the first branch below now does exactly nothing to a value that is already
    valid.

    That ordering is the fix. Previously every value was upper-cased and stripped of
    non-alphanumerics before the pass-through checks, so a reference containing a dot - which
    Meta explicitly permits - was rewritten into a different string, and the lookup for the
    attempt that owns it then missed. Meta's reference_id is case SENSITIVE, so upper-casing
    is itself a mutation that can break a join.

    Legacy upgrades still run, but only for values that are not already acceptable, which is
    the only situation they were ever meant for.

    Examples:
    - "WD-PAY-ABC12345"    -> "WD-PAY-ABC12345"  (untouched, valid)
    - "WD-PAY-a.b_c"       -> "WD-PAY-a.b_c"     (untouched: dots and case preserved)
    - "WD_41BA3534"        -> "WD-PAY-41BA3534"  (legacy shape upgraded)
    - "WD+41BA3534"        -> "WD-PAY-41BA3534"  (plus is outside Meta's charset)
    """
    import re

    if not reference_id:
        return reference_id

    raw = reference_id.strip()

    # Already something Meta would have accepted, so it is almost certainly the exact value we
    # minted. Return it byte-for-byte: any normalisation here is a chance to break the join.
    if order_keys.is_valid_meta_reference_id(raw) and 'WD-PAY-WD-PAY-' not in raw.upper():
        return raw

    stripped = raw.upper()

    # Remove duplicate WD-PAY- prefixes
    while 'WD-PAY-WD-PAY-' in stripped:
        stripped = stripped.replace('WD-PAY-WD-PAY-', 'WD-PAY-')

    if stripped.startswith('WD-PAY-') or stripped.startswith('WD-ORD-'):
        return stripped

    # Old format: strip non-alnum, remove legacy WD prefix(es), add WD-PAY-
    cleaned = re.sub(r'[^A-Za-z0-9]', '', stripped)
    while cleaned.startswith('WD'):
        cleaned = cleaned[2:]
    if not cleaned:
        return stripped  # Return original if nothing left

    upgraded = f'WD-PAY-{cleaned}'
    if len(upgraded) > order_keys.META_REFERENCE_ID_MAX_LENGTH:
        # Deliberately NOT truncated. Two truncated references are indistinguishable, and this
        # value is about to be used to resolve which order a payment belongs to. Returning it
        # over-length means the lookup misses and the event surfaces for staff, which is the
        # recoverable outcome; truncating means it silently matches the wrong order.
        logger.warning(json.dumps({
            'event': 'inbound_reference_id_over_length',
            'length': len(upgraded),
            'limit': order_keys.META_REFERENCE_ID_MAX_LENGTH,
            'note': 'not truncated; lookup will miss rather than match the wrong order',
        }))
    return upgraded


def _select_payment_transaction(payment_data: Dict) -> Dict:
    """Return the authoritative transaction object from either Meta payment shape.

    Meta has emitted both a legacy singular transaction object and the live
    ORDER_DETAILS transactions[] list. Prefer the plural list when present,
    because it is the shape that carries pg_transaction_id in current native
    payment captures. Among multiple rows, prefer one with a canonical terminal
    state (captured/failed); otherwise preserve Meta order and use the first dict.
    """
    rows = payment_data.get('transactions')
    if isinstance(rows, list):
        candidates = [row for row in rows if isinstance(row, dict)]
        if candidates:
            for row in candidates:
                state = pay_status.canonical(row.get('status', ''))
                if state in (pay_status.CAPTURED, pay_status.FAILED):
                    return row
            return candidates[0]

    legacy = payment_data.get('transaction')
    return legacy if isinstance(legacy, dict) else {}

def _process_payment_status(status: Dict, request_id: str) -> None:
    """
    Process payment status webhook from WhatsApp.
    
    Payment webhook format:
    {
        "id": "wamid.xxx",
        "recipient_id": "919876543210",
        "type": "payment",
        "status": "captured",  // pending, captured, failed
        "payment": {
            "reference_id": "ORDER_12345",
            "amount": {"value": 10000, "offset": 100},
            "currency": "INR",
            "transaction": {
                "id": "txn_xxx",
                "type": "upi",
                "status": "success"
            }
        },
        "timestamp": "1706140800"
    }
    """
    # Keys and masked ids only: the status object carries the payer's recipient_id and the full
    # payment payload (amount, transaction), none of which belong in an advisory log line.
    logger.info(json.dumps({
        'event': 'payment_status_processing',
        'statusKeys': sorted(status) if isinstance(status, dict) else [],
        'statusWord': status.get('status', ''),
        'recipientId': mask_phone(status.get('recipient_id', '')),
        'requestId': request_id
    }))
    
    payment_data = status.get('payment', {})
    raw_reference_id = payment_data.get('reference_id', '')
    # Sanitize reference_id - remove duplicate WD prefix and underscores
    reference_id = _sanitize_reference_id(raw_reference_id)
    payment_status = status.get('status', '')
    # Meta's raw word is kept for storage and logging - we must not lose what the provider
    # actually said - but every DECISION below goes through the canonical form. Meta's own
    # vocabulary is not ours: `payment_status` measured `FlowSubmission.paymentStatus` already
    # holding Meta's raw `paid`, and the branches below used to compare `== 'captured'`. So a
    # capture reported as `paid` took the else branch: no verification, no invoice, and no
    # confirmation to a customer who had paid.
    payment_state = pay_status.canonical(payment_status)
    recipient_id = status.get('recipient_id', '')
    timestamp = int(status.get('timestamp', time.time()))
    
    # Log payment data extraction
    logger.info(json.dumps({
        'event': 'payment_data_extracted',
        # Keys only: the payment object can carry the payer's details.
        'paymentDataKeys': sorted(payment_data) if isinstance(payment_data, dict) else [],
        'referenceId': reference_id,
        'paymentStatus': payment_status,
        'recipientId': mask_phone(recipient_id),
        'requestId': request_id
    }))
    
    amount = payment_data.get('amount', {})
    amount_value = amount.get('value', 0)
    amount_offset = amount.get('offset', 100)
    currency = payment_data.get('currency', 'INR')
    
    # Log amount extraction with full details
    logger.info(json.dumps({
        'event': 'payment_amount_extracted',
        'amountObject': amount,
        'amountValue': amount_value,
        'amountOffset': amount_offset,
        'paymentDataKeys': list(payment_data.keys()) if payment_data else [],
        'requestId': request_id
    }))
    
    # Calculate actual amount (value / offset)
    actual_amount = amount_value / amount_offset if amount_offset else amount_value
    
    # If amount is 0, try to look up from original payment request in DynamoDB
    if actual_amount == 0 and reference_id:
        logger.info(json.dumps({
            'event': 'payment_amount_zero_lookup',
            'referenceId': reference_id,
            'requestId': request_id
        }))
        actual_amount = _lookup_payment_amount(reference_id, request_id)
    
    transaction = _select_payment_transaction(payment_data)
    transaction_id = transaction.get('id', '')
    transaction_type = transaction.get('type', '')
    
    logger.info(json.dumps({
        'event': 'payment_status_received',
        'referenceId': reference_id,
        'paymentStatus': payment_status,
        'recipientId': mask_phone(recipient_id),
        'amount': actual_amount,
        'currency': currency,
        'transactionId': transaction_id,
        'transactionType': transaction_type,
        'requestId': request_id
    }))

    # Meta can redeliver the same payment status. This path is advisory only (the Razorpay
    # webhook is the paid-state authority), but a redelivery still re-stores the record and
    # re-emits the advisory log, so claim once per (reference, status, transaction). claim_event
    # fails open on a missing key or a DynamoDB error, so a real status is never dropped.
    from lambda_utils.webhook_dedup import claim_event
    _dedup_key = f'wa-payment:{reference_id}:{payment_status}:{transaction_id}'
    if not claim_event(_dedup_key, source='whatsapp_payment_status'):
        logger.info(json.dumps({
            'event': 'payment_status_duplicate_skipped',
            'referenceId': reference_id,
            'paymentStatus': payment_status,
            'requestId': request_id,
        }))
        return
    
    # Store payment record in DynamoDB
    _store_payment_record(
        reference_id=reference_id,
        recipient_id=recipient_id,
        payment_status=payment_status,
        amount_value=amount_value,
        amount_offset=amount_offset,
        currency=currency,
        transaction=transaction,
        timestamp=timestamp,
        request_id=request_id,
        full_payment_data=payment_data,
    )
    
    # Look up the phone_number_id from the original outbound payment request
    # so the confirmation goes back from the same business number
    originating_phone_id = None
    if reference_id:
        try:
            OUTBOUND_TABLE = os.environ.get('OUTBOUND_TABLE', 'stack-wecare-digital-WhatsAppOutboundTable')
            outbound_table = dynamodb.Table(OUTBOUND_TABLE)
            # Query GSI paymentReferenceId-index (falls back to scan if GSI missing)
            found = False
            try:
                resp = outbound_table.query(
                    IndexName='paymentReferenceId-index',
                    KeyConditionExpression='paymentReferenceId = :ref',
                    ExpressionAttributeValues={':ref': reference_id},
                    Limit=1,
                )
                items = resp.get('Items', [])
                if items:
                    originating_phone_id = items[0].get('awsPhoneNumberId') or items[0].get('phoneNumberId')
                    found = True
            except Exception:
                # Fallback to paginated scan if GSI not yet active
                scan_kwargs = {
                    'FilterExpression': 'paymentReferenceId = :ref',
                    'ExpressionAttributeValues': {':ref': reference_id},
                    'ProjectionExpression': 'awsPhoneNumberId, phoneNumberId',
                }
                while not found:
                    resp = outbound_table.scan(**scan_kwargs)
                    items = resp.get('Items', [])
                    if items:
                        originating_phone_id = items[0].get('awsPhoneNumberId') or items[0].get('phoneNumberId')
                        found = True
                    elif 'LastEvaluatedKey' in resp:
                        scan_kwargs['ExclusiveStartKey'] = resp['LastEvaluatedKey']
                    else:
                        break
            
            logger.info(json.dumps({
                'event': 'payment_phone_id_resolved',
                'referenceId': reference_id,
                'phoneNumberId': originating_phone_id,
                'found': found,
                'requestId': request_id
            }))
        except Exception as e:
            logger.warning(json.dumps({
                'event': 'payment_phone_id_lookup_failed',
                'referenceId': reference_id,
                'error': str(e),
                'requestId': request_id
            }))

    # Detect effective failure: WhatsApp may send status="pending" but
    # transaction.status="failed" (e.g. insufficient funds / gateway error).
    transaction_status = transaction.get('status', '')
    effective_failed = (
        payment_state == pay_status.FAILED
        or (payment_state == pay_status.PENDING
            and pay_status.canonical(transaction_status) == pay_status.FAILED)
    )

    # Send order_status message based on payment status
    if payment_state == pay_status.CAPTURED:
        # ── Security: Verify payment via Meta Payment Lookup API ──
        # Meta docs: "must not rely solely on the status of the transaction provided in the webhook"
        #
        # There are four possible outcomes here and the code used to record only
        # two. `payment_verified` was a bool initialised True, so a capture that
        # was never checked - because the outbound row had no paymentConfigName, or
        # because the lookup call itself failed - was indistinguishable in the logs
        # and on the invoice from one Meta had confirmed. Asking "which captures did
        # we accept without verifying?" had no answer.
        #
        # ADVISORY ONLY: this lookup no longer gates any financial side effect — the branch
        # below creates NO paid state at all (see the advisory block). In-WhatsApp payments ARE
        # live, but the Razorpay webhook (payments/razorpay-webhook/handler.py, via razorpay_verify)
        # is the single authoritative payment producer: it re-derives the paid state from a provider
        # readback, so this Meta-webhook path must not mint a second, unverified one. The
        # verification is retained ONLY to compute an auditable `verification_outcome` for the
        # advisory log, so the historical fail-open exposure stays visible. PAYMENT_LOOKUP_REQUIRED
        # is intentionally LEFT DEFINED (its env-var contract is preserved) but is now dead on the
        # financial path: regardless of its value, no paid invoice/order/receipt can be created here.
        VERIFIED = 'verified'
        UNVERIFIED_NO_CONFIG = 'unverified_no_payment_config'
        UNVERIFIED_LOOKUP_FAILED = 'unverified_lookup_failed'
        REJECTED_MISMATCH = 'rejected_lookup_mismatch'

        lookup_required = str(
            os.environ.get('PAYMENT_LOOKUP_REQUIRED', '')
        ).strip().lower() in ('1', 'true', 'yes', 'on')

        verification_outcome = UNVERIFIED_NO_CONFIG
        if reference_id and originating_phone_id:
            try:
                # Look up payment config from the original outbound message
                OUTBOUND_TABLE = os.environ.get('OUTBOUND_TABLE', 'stack-wecare-digital-WhatsAppOutboundTable')
                outbound_table = dynamodb.Table(OUTBOUND_TABLE)
                config_name = ''
                try:
                    resp = outbound_table.query(
                        IndexName='paymentReferenceId-index',
                        KeyConditionExpression='paymentReferenceId = :ref',
                        ExpressionAttributeValues={':ref': reference_id},
                        Limit=1,
                    )
                    items = resp.get('Items', [])
                    if items:
                        config_name = items[0].get('paymentConfigName', '')
                except Exception:
                    pass

                if config_name:
                    import urllib.request, urllib.error
                    # Call Meta Payment Lookup API
                    meta_phone_id = originating_phone_id
                    # Extract Meta phone ID if in internal format
                    if '-direct-' in meta_phone_id:
                        meta_phone_id = meta_phone_id.split('-direct-')[-1]

                    token = _load_direct_api_token()
                    lookup_url = f"https://graph.facebook.com/{META_API_VERSION}/{meta_phone_id}/payments/{config_name}/{reference_id}"
                    req = urllib.request.Request(lookup_url, headers={
                        'Authorization': f'Bearer {token}',
                    }, method='GET')
                    try:
                        with urllib.request.urlopen(req, timeout=10) as r:
                            lookup_result = json.loads(r.read().decode())
                        payments = lookup_result.get('payments', [])
                        if payments:
                            lookup_status = payments[0].get('status', '')
                            # Canonical, not raw. This branch decides whether to REJECT a payment
                            # the customer has already made, so a vocabulary mismatch here refuses
                            # real money: Meta answering `paid` against our `captured` would have
                            # been recorded as REJECTED_MISMATCH. An unrecognised word still
                            # rejects - `canonical` returns '' for anything unmappable, which is
                            # the correct direction for a verification step.
                            if pay_status.canonical(lookup_status) != pay_status.CAPTURED:
                                verification_outcome = REJECTED_MISMATCH
                                logger.warning(json.dumps({
                                    'event': 'payment_lookup_mismatch',
                                    'webhookStatus': 'captured',
                                    'lookupStatus': lookup_status,
                                    'lookupStatusCanonical': pay_status.canonical(lookup_status),
                                    'referenceId': reference_id,
                                    'requestId': request_id,
                                }))
                            else:
                                verification_outcome = VERIFIED
                                logger.info(json.dumps({
                                    'event': 'payment_lookup_verified',
                                    'referenceId': reference_id,
                                    'requestId': request_id,
                                }))
                        else:
                            # 200 with an empty payments array. Meta knows the
                            # reference and reports nothing for it, which is not a
                            # confirmation - previously this fell through leaving
                            # payment_verified True.
                            verification_outcome = UNVERIFIED_LOOKUP_FAILED
                            logger.warning(json.dumps({
                                'event': 'payment_lookup_empty',
                                'referenceId': reference_id,
                                'requestId': request_id,
                            }))
                    except Exception as lookup_err:
                        verification_outcome = UNVERIFIED_LOOKUP_FAILED
                        logger.warning(json.dumps({
                            'event': 'payment_lookup_failed',
                            'error': str(lookup_err)[:200],
                            'referenceId': reference_id,
                            'requestId': request_id,
                        }))
                else:
                    verification_outcome = UNVERIFIED_NO_CONFIG
                    logger.warning(json.dumps({
                        'event': 'payment_lookup_skipped_no_config',
                        'reason': ('no paymentConfigName on the outbound row for this '
                                   'referenceId, so the Payment Lookup API cannot be '
                                   'addressed'),
                        'referenceId': reference_id,
                        'requestId': request_id,
                    }))
            except Exception as e:
                verification_outcome = UNVERIFIED_LOOKUP_FAILED
                logger.warning(json.dumps({
                    'event': 'payment_verification_error',
                    'error': str(e)[:200],
                    'requestId': request_id,
                }))

        # ── ADVISORY: this Meta-webhook CAPTURED branch creates NO paid state ──
        # In-WhatsApp payments are live, but the Razorpay webhook is the authoritative payment
        # producer. This Meta payment-webhook path is advisory only, so this CAPTURED branch
        # deliberately creates no paid state — a second producer here, off an unverified webhook
        # body, could mint paid invoices/orders/receipts that disagree with the authority.
        #
        # Previously this path marked the invoice paid, sent a 'completed' order_status,
        # generated a GST invoice, and notified balance-due — all off a capture that was
        # accepted FAIL-OPEN (the Meta Payment Lookup is advisory here and defaults off
        # via PAYMENT_LOOKUP_REQUIRED). An unverified webhook body could therefore mint
        # paid invoices/orders/receipts. That financial fall-through is now retired.
        #
        # The single authoritative payment producer going forward is the Razorpay
        # webhook (amplify/functions/payments/razorpay-webhook/handler.py), which
        # re-derives every financial decision from an authoritative provider readback
        # via lambda_utils/integrations/razorpay_verify (payment_is_captured /
        # verifier_for_event) — never from the event body. No weaker parallel path may
        # create paid state.
        #
        # We still STORE the raw payment record above (non-financial, for audit) and we
        # emit a clearly-labelled, type-only SUPERSEDED audit record here so the event
        # stays visible to whoever reconciles it. We intentionally make NO financial
        # state mutation: no _mark_invoice_paid_by_reference, no _send_order_status
        # 'completed', no _generate_invoice_for_captured_payment, no balance-due notify.
        # `verification_outcome` and `lookup_required` are retained in the log purely for
        # audit; regardless of PAYMENT_LOOKUP_REQUIRED, no paid state can be created here.
        logger.error(json.dumps({
            'event': 'in_whatsapp_payment_capture_superseded',
            'note': ('advisory only; no financial side effects — in-WhatsApp payments '
                     'are live but the Razorpay webhook is the single authoritative '
                     'payment producer'),
            'verificationOutcome': verification_outcome,
            'lookupRequired': lookup_required,
            'referenceId': reference_id,
            'requestId': request_id,
        }))
        # Meta saying "captured" is a reason to LOOK, never evidence. Ask the Razorpay webhook,
        # the one paid-state producer, to settle this reference now from the provider readback,
        # instead of waiting for a late Razorpay delivery or the next 5-minute sweep. Async and
        # best-effort: this path still writes no paid state, and a failure here only means the
        # sweep finds it instead.
        _trigger_capture_reconcile(reference_id, request_id)
    elif effective_failed:
        # Log only. The WhatsApp payment-order lifecycle is pending -> processing -> completed,
        # sent solely by the invoice engine; a failed attempt leaves the order pending so the
        # customer can pay again. The retired kill-switched `canceled` sender lived here.
        logger.info(json.dumps({
            'event': 'payment_effective_failure',
            'paymentStatus': payment_status,
            'transactionStatus': transaction_status,
            'referenceId': reference_id,
            'requestId': request_id,
        }))
    elif payment_state == pay_status.PENDING:
        # Genuine pending (transaction still in progress)  -  log and wait
        logger.info(json.dumps({
            'event': 'payment_pending_waiting',
            'referenceId': reference_id,
            'transactionStatus': transaction_status,
            'requestId': request_id,
        }))


#: The one paid-state producer. Inbound only ever asks it to look (`reconcileReference`).
RAZORPAY_WEBHOOK_FUNCTION = os.environ.get('RAZORPAY_WEBHOOK_FUNCTION',
                                           'wecare-razorpay-webhook:live')


def _trigger_capture_reconcile(reference_id: str, request_id: str) -> None:
    """Fire-and-forget: ask the Razorpay webhook to settle `reference_id` from the provider.

    An `Event` invoke, so the inbound webhook answers Meta immediately. The webhook validates
    the reference shape, resolves the attempt from its own PAYREF# row and settles only on a
    Razorpay readback, so nothing in this request (beyond which reference to look at) is
    trusted. Never raises.
    """
    if not reference_id:
        return
    try:
        lambda_client.invoke(
            FunctionName=RAZORPAY_WEBHOOK_FUNCTION,
            InvocationType='Event',
            Payload=json.dumps({'internalAction': 'reconcileReference',
                                'referenceId': reference_id}),
        )
        logger.info(json.dumps({'event': 'capture_reconcile_requested',
                                'referenceId': reference_id, 'requestId': request_id}))
    except Exception as error:  # noqa: BLE001 - the sweep is the backstop
        logger.warning(json.dumps({'event': 'capture_reconcile_request_failed',
                                   'referenceId': reference_id, 'error': type(error).__name__,
                                   'requestId': request_id}))


def _store_payment_record(reference_id: str, recipient_id: str, payment_status: str,
                          amount_value: int, amount_offset: int, currency: str,
                          transaction: Dict = None, timestamp: int = 0,
                          request_id: str = '', full_payment_data: Dict = None) -> None:
    """Store payment record in Messages table for tracking.
    Stores full transaction object: pg_transaction_id, method.type, error.code/reason.
    Also parses and stores refund data from Meta payment webhooks."""
    if transaction is None:
        transaction = {}
    if full_payment_data is None:
        full_payment_data = {}
    try:
        # Find contact by phone number
        contact = _get_contact_by_phone(recipient_id)
        contact_id = contact.get('id', '') if contact else ''
        
        payment_id = str(uuid.uuid4())
        now = int(time.time())
        expires_at = now + MESSAGE_TTL_SECONDS
        
        # Calculate actual amount
        actual_amount = amount_value / amount_offset if amount_offset else amount_value

        # Extract full transaction fields (Gap 5)
        transaction_id = transaction.get('id', '')
        transaction_type = transaction.get('type', '')
        pg_transaction_id = transaction.get('pg_transaction_id', '')
        transaction_status = transaction.get('status', '')
        txn_method = transaction.get('method', {})
        txn_method_type = txn_method.get('type', '') if isinstance(txn_method, dict) else str(txn_method)
        txn_error = transaction.get('error', {})
        txn_error_code = txn_error.get('code', '') if isinstance(txn_error, dict) else ''
        txn_error_reason = txn_error.get('reason', '') if isinstance(txn_error, dict) else ''
        txn_created = transaction.get('created_timestamp', 0)
        txn_updated = transaction.get('updated_timestamp', 0)

        # Parse refund data from Meta payment webhooks (Gap 6)
        refunds_raw = full_payment_data.get('refunds', [])
        refunds_json = ''
        if refunds_raw:
            refunds_json = json.dumps(refunds_raw, default=str)[:4000]

        # Parse PG-specific UDF/notes echoed back in webhook
        webhook_notes = full_payment_data.get('notes', {})
        webhook_receipt = full_payment_data.get('receipt', '')
        webhook_udf1 = full_payment_data.get('udf1', '')
        webhook_udf2 = full_payment_data.get('udf2', '')
        webhook_udf3 = full_payment_data.get('udf3', '')
        webhook_udf4 = full_payment_data.get('udf4', '')
        
        payment_record = {
            'id': payment_id,
            'messageId': payment_id,
            'contactId': contact_id,
            'channel': 'whatsapp',
            'direction': 'inbound',
            'messageType': 'payment',
            'content': f'Payment {payment_status}: ₹{actual_amount:.2f} ({currency})',
            'status': payment_status,
            'senderPhone': recipient_id,
            # Payment-specific fields
            'paymentReferenceId': reference_id,
            'paymentStatus': payment_status,
            'paymentAmount': Decimal(str(amount_value)),
            'paymentOffset': Decimal(str(amount_offset)),
            'paymentCurrency': currency,
            # Full transaction object (Gap 5)
            'transactionId': transaction_id,
            'transactionType': transaction_type,
            'pgTransactionId': pg_transaction_id,
            'transactionStatus': transaction_status,
            'paymentMethodType': txn_method_type,
            'errorCode': txn_error_code,
            'errorReason': txn_error_reason,
            'txnCreatedAt': Decimal(str(txn_created)) if txn_created else None,
            'txnUpdatedAt': Decimal(str(txn_updated)) if txn_updated else None,
            # Refund data (Gap 6)
            'refundsJson': refunds_json if refunds_json else None,
            # PG-specific fields echoed back
            'webhookNotes': json.dumps(webhook_notes, default=str)[:2000] if webhook_notes else None,
            'webhookReceipt': webhook_receipt if webhook_receipt else None,
            'webhookUdf1': webhook_udf1 if webhook_udf1 else None,
            'webhookUdf2': webhook_udf2 if webhook_udf2 else None,
            'webhookUdf3': webhook_udf3 if webhook_udf3 else None,
            'webhookUdf4': webhook_udf4 if webhook_udf4 else None,
            'timestamp': Decimal(str(timestamp)),
            'createdAt': Decimal(str(now)),
            'expiresAt': Decimal(str(expires_at)),
        }
        
        messages_table = dynamodb.Table(MESSAGES_TABLE)
        messages_table.put_item(Item={k: v for k, v in payment_record.items() if v is not None and v != ''})

        # Unified Inbox dual-write — mirror payment record to canonical MessagesTable so
        # the dashboard (reads canonical) shows payments. Guarded; sparse contactId.
        if MESSAGES_TABLE != UNIFIED_MESSAGES_TABLE:
            try:
                dynamodb.Table(UNIFIED_MESSAGES_TABLE).put_item(
                    Item={k: v for k, v in payment_record.items() if v is not None and v != ''}
                )
            except Exception as _ce:
                logger.warning(f'payment record canonical mirror skipped: {_ce}')
        
        # Link payment to the flow response it pays for (WD-PAY- or legacy SR- references)
        if reference_id and (reference_id.startswith('WD-PAY-') or reference_id.startswith('SR-')):
            _update_flow_submission_payment(reference_id, payment_status, transaction_id, request_id)
        
        logger.info(json.dumps({
            'event': 'payment_record_stored',
            'paymentId': payment_id,
            'referenceId': reference_id,
            'contactId': mask_contact_id(contact_id),
            'paymentStatus': payment_status,
            'amount': actual_amount,
            'pgTransactionId': pg_transaction_id,
            'methodType': txn_method_type,
            'hasRefunds': bool(refunds_raw),
            'requestId': request_id
        }))
        
    except Exception as e:
        logger.error(json.dumps({
            'event': 'payment_record_store_error',
            'referenceId': reference_id,
            'error': str(e),
            'requestId': request_id
        }))


def _update_flow_submission_payment(reference_id: str, payment_status: str,
                                    transaction_id: str, request_id: str) -> None:
    """Record a payment webhook on the flow response it pays for.

    The submission lives in the one flow-response table, keyed for payments by its
    `paymentRefId` GSI. (This used to update SubmitRequestsTable, which no live writer fills,
    so the paid state never reached the submission.)

    Monotonic: the status is written in the shared payment vocabulary and only when it is a
    forward move, so a redelivered `pending` cannot overwrite a `captured`.
    """
    word = pay_status.canonical(payment_status)
    if not word:
        logger.info(json.dumps({
            'event': 'flow_submission_payment_status_unmapped',
            'referenceId': reference_id, 'requestId': request_id,
        }))
        return
    try:
        table = dynamodb.Table(FLOW_SUBMISSIONS_TABLE)
        now = int(time.time())
        resp = table.query(
            IndexName='paymentRefId',
            KeyConditionExpression='paymentRefId = :ref',
            ExpressionAttributeValues={':ref': reference_id},
            Limit=1,
        )
        items = resp.get('Items', [])
        if not items:
            logger.warning(json.dumps({
                'event': 'flow_submission_not_found_for_payment',
                'referenceId': reference_id,
                'requestId': request_id,
            }))
            return
        submission_id = items[0]['submissionId']
        try:
            table.update_item(
                Key={'submissionId': submission_id},
                UpdateExpression=('SET paymentStatus = :s, transactionId = :t, updatedAt = :u, '
                                  + pay_status.RANK_ATTRIBUTE + ' = :rank'),
                ConditionExpression=('attribute_exists(submissionId) AND ('
                                     + pay_status.condition_expression() + ')'),
                ExpressionAttributeValues={
                    ':s': word,
                    ':t': transaction_id,
                    ':u': Decimal(str(now)),
                    ':rank': pay_status.rank(word),
                },
            )
        except Exception as cond:
            if 'ConditionalCheckFailedException' not in str(cond):
                raise
            logger.info(json.dumps({
                'event': 'flow_submission_payment_not_forward',
                'submissionId': submission_id, 'paymentStatus': word,
                'requestId': request_id,
            }))
            return
        logger.info(json.dumps({
            'event': 'flow_submission_payment_linked',
            'submissionId': submission_id,
            'referenceId': reference_id,
            'paymentStatus': word,
            'requestId': request_id,
        }))
    except Exception as e:
        logger.error(json.dumps({
            'event': 'flow_submission_payment_link_error',
            'referenceId': reference_id,
            'errorType': type(e).__name__,
            'requestId': request_id,
        }))


def _get_contact_by_phone(phone: str) -> Optional[Dict]:
    """Get contact by phone number using GSI for O(1) lookup."""
    try:
        contacts_table = dynamodb.Table(CONTACTS_TABLE)
        
        # Clean phone number - handle various formats
        clean_phone = phone.lstrip('+')
        phone_with_plus = f'+{clean_phone}'
        
        logger.info(json.dumps({
            'event': 'contact_lookup_by_phone',
            'cleanPhone': mask_phone(clean_phone),
        }))
        
        # Use GSI query on phone-index for O(1) lookup
        for phone_variant in [phone_with_plus, clean_phone, phone]:
            try:
                response = contacts_table.query(
                    IndexName='phone-index',
                    KeyConditionExpression='phone = :phone',
                    ExpressionAttributeValues={':phone': phone_variant},
                    Limit=5
                )
                items = response.get('Items', [])
                # Filter out deleted contacts
                items = [i for i in items if not i.get('deletedAt')]
                if items:
                    logger.info(json.dumps({
                        'event': 'contact_lookup_result',
                        'phone': mask_phone(phone),
                        'foundCount': len(items),
                        'contactId': mask_contact_id(items[0].get('id', '')),
                        'method': 'gsi'
                    }))
                    return items[0]
            except Exception:
                pass  # GSI not ready, will fallback below
        
        # Fallback to scan if GSI not ready
        response = contacts_table.scan(
            FilterExpression='(phone = :phone1 OR phone = :phone2 OR phone = :phone3) AND (attribute_not_exists(deletedAt) OR deletedAt = :null)',
            ExpressionAttributeValues={
                ':phone1': clean_phone,
                ':phone2': phone_with_plus,
                ':phone3': phone,
                ':null': None
            },
            Limit=10
        )
        
        items = response.get('Items', [])
        
        logger.info(json.dumps({
            'event': 'contact_lookup_result',
            'phone': mask_phone(phone),
            'foundCount': len(items),
            'contactId': mask_contact_id(items[0].get('id', '') if items else None),
            'method': 'scan_fallback'
        }))
        
        return items[0] if items else None
        
    except Exception as e:
        logger.error(json.dumps({
            'event': 'contact_lookup_error',
            'phone': mask_phone(phone),
            'error': str(e)
        }))
        return None


def _lookup_payment_amount(reference_id: str, request_id: str) -> float:
    """
    Look up payment amount from original payment request in Messages table.
    This is a fallback when WhatsApp webhook doesn't include the amount.
    
    The original payment request message stores the amount in the content field
    or in a dedicated paymentAmount field.
    """
    try:
        messages_table = dynamodb.Table(MESSAGES_TABLE)
        
        # Sanitize reference_id for lookup
        sanitized_ref = _sanitize_reference_id(reference_id)
        
        # Extract just the ID part (without WD-PAY- or legacy WD prefix) for broader search
        id_part = sanitized_ref
        for pfx in ('WD-PAY-', 'WD-ORD-', 'WD'):
            if id_part.startswith(pfx):
                id_part = id_part[len(pfx):]
                break
        
        # Look for the original payment request message by reference_id
        # Search with multiple variations to handle format differences
        response = messages_table.scan(
            FilterExpression='paymentReferenceId = :ref1 OR paymentReferenceId = :ref2 OR contains(content, :id_part)',
            ExpressionAttributeValues={
                ':ref1': sanitized_ref,
                ':ref2': reference_id,  # Also try original format
                ':id_part': id_part
            },
            Limit=10
        )
        
        items = response.get('Items', [])
        
        logger.info(json.dumps({
            'event': 'payment_amount_lookup_result',
            'referenceId': reference_id,
            'sanitizedRef': sanitized_ref,
            'idPart': id_part,
            'foundCount': len(items),
            'requestId': request_id
        }))
        
        # Look for amount in the found records
        for item in items:
            # Check for paymentAmount field (stored in paise)
            payment_amount = item.get('paymentAmount')
            if payment_amount:
                offset = item.get('paymentOffset', 100)
                amount = float(payment_amount) / float(offset)
                logger.info(json.dumps({
                    'event': 'payment_amount_found_in_record',
                    'referenceId': reference_id,
                    'amount': amount,
                    'requestId': request_id
                }))
                return amount
            
            # Try to extract from content (e.g., "Payment request: ₹500.00")
            content = item.get('content', '')
            if '₹' in content:
                import re
                match = re.search(r'₹([\d,]+\.?\d*)', content)
                if match:
                    amount_str = match.group(1).replace(',', '')
                    amount = float(amount_str)
                    logger.info(json.dumps({
                        'event': 'payment_amount_extracted_from_content',
                        'referenceId': reference_id,
                        'amount': amount,
                        'content': content[:100],
                        'requestId': request_id
                    }))
                    return amount
        
        logger.warning(json.dumps({
            'event': 'payment_amount_not_found',
            'referenceId': reference_id,
            'requestId': request_id
        }))
        return 0.0
        
    except Exception as e:
        logger.error(json.dumps({
            'event': 'payment_amount_lookup_error',
            'referenceId': reference_id,
            'error': str(e),
            'requestId': request_id
        }))
        return 0.0


def _send_to_dlq(record: Dict, error: str, request_id: str) -> None:
    """Send failed message to inbound-dlq."""
    if not INBOUND_DLQ_URL:
        return
    
    try:
        sqs.send_message(
            QueueUrl=INBOUND_DLQ_URL,
            MessageBody=json.dumps({
                'originalRecord': record,
                'error': error,
                'timestamp': int(time.time()),
                'requestId': request_id
            }, default=str)
        )
    except Exception as e:
        logger.error(json.dumps({
            'event': 'dlq_send_error',
            'error': str(e),
            'requestId': request_id
        }))


CALLING_TABLE = os.environ.get('CALL_LOG_TABLE', 'stack-wecare-digital-WhatsAppCallingTable')


def _forward_call_permission_to_calling_table(sender_phone: str, receiving_phone: str,
                                               aws_phone_number_id: str,
                                               interactive: Dict) -> None:
    """
    DEPRECATED: No longer called. Permission is auto-granted pre/post call.
    Kept for reference only — will be removed in next cleanup.
    """
    pass


def _send_auto_reaction(contact_id: str, whatsapp_message_id: str, 
                        phone_number_id: str, request_id: str) -> None:
    """
    Send automatic thumbs up reaction to inbound message.
    Uses the same phone number that received the message.
    """
    if not whatsapp_message_id:
        return
    
    try:
        reaction_payload = {
            'body': json.dumps({
                'contactId': contact_id,
                'isReaction': True,
                'reactionMessageId': whatsapp_message_id,
                'reactionEmoji': '\U0001F44D',  # Thumbs up
                'phoneNumberId': phone_number_id  # Use same phone that received
            })
        }
        
        response = lambda_client.invoke(
            FunctionName=OUTBOUND_WHATSAPP_FUNCTION,
            InvocationType='Event',
            Payload=json.dumps(reaction_payload)
        )
        
        logger.info(json.dumps({
            'event': 'auto_reaction_triggered',
            'contactId': mask_contact_id(contact_id),
            'whatsappMessageId': whatsapp_message_id,
            'phoneNumberId': phone_number_id,
            'statusCode': response.get('StatusCode'),
            'requestId': request_id
        }))
        
    except Exception as e:
        logger.error(json.dumps({
            'event': 'auto_reaction_error',
            'contactId': mask_contact_id(contact_id),
            'error': str(e),
            'requestId': request_id
        }))


def _send_ai_auto_reply(contact_id: str, content: str, phone_number_id: str, request_id: str) -> None:
    """
    Send AI-generated auto-reply to WhatsApp.
    Uses the same phone number that received the message.
    """
    if not content or not content.strip() or not contact_id:
        return
    
    try:
        reply_payload = {
            'body': json.dumps({
                'contactId': contact_id,
                'content': content,
                'phoneNumberId': phone_number_id
            })
        }
        
        response = lambda_client.invoke(
            FunctionName=OUTBOUND_WHATSAPP_FUNCTION,
            InvocationType='Event',  # Async - don't wait for response
            Payload=json.dumps(reply_payload)
        )
        
        logger.info(json.dumps({
            'event': 'ai_auto_reply_triggered',
            'contactId': mask_contact_id(contact_id),
            'contentLength': len(content),
            'phoneNumberId': phone_number_id,
            'statusCode': response.get('StatusCode'),
            'requestId': request_id
        }))
        
    except Exception as e:
        logger.error(json.dumps({
            'event': 'ai_auto_reply_error',
            'contactId': mask_contact_id(contact_id),
            'error': str(e),
            'requestId': request_id
        }))


#: Only an explicitly disappearing/ephemeral payload gets the disappearing-message hint.
#: Generic 131051/unknown traffic carries no evidence for that diagnosis and may represent an
#: unsupported client type or provider-generated content that WhatsApp does not expose.
UNREADABLE_MESSAGE_LABELS = frozenset({UNSUPPORTED_DISAPPEARING})
UNREADABLE_HINT_TEXT = ("We couldn't read your disappearing message. Please turn disappearing "
                        "messages off in this chat, then send your message again as text.")
#: One hint per contact per day. The cause usually persists for every message that follows.
UNREADABLE_HINT_INTERVAL_SECONDS = 24 * 60 * 60


def _send_unreadable_hint(contact_id: str, phone_number_id: str, now: int,
                          request_id: str) -> bool:
    """Tell the customer we could not read their message, at most once a day. True when sent.

    The once-a-day claim is a conditional write on the contact row, made before the send, so
    concurrent deliveries of the same burst produce one reply. Any failure to claim it sends
    nothing: a missed hint is better than a repeated one.
    """
    if not contact_id or not _may_send('unreadable_message_hint'):
        return False
    try:
        dynamodb.Table(CONTACTS_TABLE).update_item(
            Key={'id': contact_id},
            UpdateExpression='SET unreadableHintAt = :now',
            ConditionExpression=('attribute_exists(id) AND (attribute_not_exists(unreadableHintAt) '
                                 'OR unreadableHintAt < :cutoff)'),
            ExpressionAttributeValues={
                ':now': Decimal(str(int(now))),
                ':cutoff': Decimal(str(int(now) - UNREADABLE_HINT_INTERVAL_SECONDS)),
            },
        )
    except ClientError as e:
        code = e.response.get('Error', {}).get('Code', '')
        logger.info(json.dumps({
            'event': 'unreadable_hint_skipped',
            'reason': 'sent_recently' if code == 'ConditionalCheckFailedException' else f'claim_failed:{code}',
            'contactId': mask_contact_id(contact_id), 'requestId': request_id,
        }))
        return False
    except Exception as e:  # noqa: BLE001 - never let the hint break message processing
        logger.warning(json.dumps({
            'event': 'unreadable_hint_skipped', 'reason': f'claim_failed:{type(e).__name__}',
            'contactId': mask_contact_id(contact_id), 'requestId': request_id,
        }))
        return False
    _send_ai_auto_reply(contact_id, UNREADABLE_HINT_TEXT, phone_number_id, request_id)
    logger.info(json.dumps({'event': 'unreadable_hint_sent',
                            'contactId': mask_contact_id(contact_id), 'requestId': request_id}))
    return True


# `_send_submit_request_flow` was removed on 2026-10-26. It had no caller (the keyword door uses
# `_send_generic_flow`, and Submit Request answers with its website link), and its default Flow
# 1235100738173254 was an unused legacy draft.


F001_CONTRACT = canonical_contract('subscribe')
F001_SESSION_UNAVAILABLE_REPLY = ('We could not open Subscribe right now. Please try again in a '
                                  'few minutes. - WECARE.DIGITAL')


def _launch_subscribe_flow(contact_id: str, phone_number_id: str, sender_phone: str,
                           request_id: str, trigger: Dict) -> bool:
    """F001 Subscribe keyword door. True when the keyword was handled; False to keep looking.

    Order is the policy: every launch control must agree (`flow_launch`), the thread must be
    ours to answer, a server-issued session is recorded BEFORE the Flow message is sent (the
    data-exchange endpoint answers 427 to any token without one), and the opening copy is the
    Workspace-managed New / Returning customer message. A refusal is counted with its reason
    and falls through exactly as a disabled trigger always has.
    """
    flow_code = F001_CONTRACT['flowCode']
    funnel_table = dynamodb.Table(flow_funnel.table_name())

    def count(stage: str, **fields: Any) -> None:
        flow_funnel.record(funnel_table, flow_code, stage, logger=logger, requestId=request_id,
                           launchChannel=flow_sessions.LAUNCH_KEYWORD,
                           contactId=mask_contact_id(contact_id), **fields)

    count('launch_attempted')
    try:
        registry_row = flow_launch.read_registry_row(
            dynamodb.Table(flow_launch.registry_table_name()), canonical_flow_id('subscribe'))
    except Exception:  # noqa: BLE001 - an unreadable registry is a refusal, never a launch
        count('launch_blocked', reason='registry_unreadable')
        return False
    decision = flow_launch.keyword_launch_decision(capability='subscribe',
                                                   registry_row=registry_row, trigger=trigger)
    if not decision.allowed:
        count('launch_blocked', reason=decision.reason)
        return False
    if not _may_send('subscribe_flow'):
        count('launch_blocked', reason='not_thread_owner')
        return True
    try:
        row = contact_store.lookup(dynamodb.Table(CONTACTS_TABLE), sender_phone,
                                   contact_id=contact_id) or {}
    except Exception:  # noqa: BLE001 - only chooses New vs Returning copy; identity is the session
        row = {}
    copy = subscribe_messages.copy_for(subscribe_messages.is_returning(row),
                                       dynamodb.Table(SYSTEM_CONFIG_TABLE))
    flow_config = {**trigger, 'flowId': canonical_flow_id('subscribe'),
                   'message': {'body': copy['body'], 'footer': subscribe_messages.FOOTER,
                               'flowCta': copy['flowCta']}}
    if phone_number_id == PHONE_NUMBER_ID_2:
        # F001 exists on WABA 1 only; a WABA 2 customer receives the website link instead.
        _send_generic_flow(contact_id=contact_id, phone_number_id=phone_number_id,
                           sender_phone=sender_phone, request_id=request_id,
                           flow_config={**flow_config, 'flowId2': ''}, flow_key='subscribe')
        count('launch_redirected')
        return True
    try:
        flow_token = flow_sessions.mint_token(F001_CONTRACT['tokenPrefix'], sender_phone, '1')
        flow_sessions.record_session(
            dynamodb.Table(flow_sessions.table_name()), capability='subscribe',
            token=flow_token, launch_channel=flow_sessions.LAUNCH_KEYWORD,
            initiated_by='customer_keyword')
    except (flow_sessions.FlowSessionUnavailable, ValueError) as e:
        count('launch_failed', reason=f'session_{type(e).__name__}')
        _send_ai_auto_reply(contact_id, F001_SESSION_UNAVAILABLE_REPLY, phone_number_id, request_id)
        return True
    sent = _send_generic_flow(contact_id=contact_id, phone_number_id=phone_number_id,
                              sender_phone=sender_phone, request_id=request_id,
                              flow_config=flow_config, flow_key='subscribe', flow_token=flow_token)
    if sent:
        count('launch_sent')
    else:
        count('launch_failed', reason='outbound_invoke')
    return True


# ── Attributed review door (Phase R) ──
#
# The website's "Leave a review" button opens `wa.me/<WABA1>?text=review <REF>`, so the
# CUSTOMER messages US with the order they want to review. This is the inbound half of
# that door: recognise the reference, park it, and send the review Flow the exact same
# way a bare `review` already does.

#: Anchored and bounded at BOTH ends on purpose. `review` alone keeps taking the existing
#: exact-match path; prose such as `can i leave a review for my order` must NOT match, or
#: a generic sentence starts dispatching a Flow. `src/lib/reviewLink.ts` enforces the
#: identical bound before it will put a reference in the link, so the two ends of this
#: door cannot disagree about what a reference is.
_REVIEW_REF_PATTERN = r'^review\s+([A-Za-z0-9][A-Za-z0-9-]{3,39})$'

#: FlowDraftTable suffix, mirrored by `flows/leave_review.REF_DRAFT_CODE`.
REVIEW_REF_DRAFT_CODE = 'WD_REV_REF'

#: How long a parked review reference stays valid. THIRTY MINUTES, not `save_draft`'s seven
#: days, and the difference is the whole point of having a separate constant.
#:
#: Seven days is right for what `save_draft` holds — a half-finished order form worth
#: resuming tomorrow. This row holds something with a much shorter natural life: the
#: reference is only meaningful between the customer's `review <REF>` message and the
#: submission of the form that message triggered, which is one sitting.
#:
#: The hazard a long TTL creates is ABANDONMENT, not storage. `flows/leave_review.handle_init`
#: reads this row without clearing it, and `handle_review_form` clears it only on a
#: successful submission, so a customer who opens the attributed door for order A and then
#: dismisses the Flow leaves the row behind. With a seven-day life, their next bare `review`
#: — days later, about something else entirely — would be stored against order A, and a
#: staff member reading the moderation queue would see a confident, wrong attribution with
#: nothing to flag it.
#:
#: Thirty minutes is generous for one sitting and short enough that an abandoned door is
#: forgotten rather than remembered wrongly. It is carried BOTH as the DynamoDB `ttl` (which
#: reclaims the row, best-effort and documented to lag up to 48 hours) and as `expiresAt`
#: inside `formData`, which `flows/leave_review._pending_reference` enforces on read. The
#: second is the one that actually bounds attribution; the first only bounds storage.
REVIEW_REF_TTL_SECONDS = 30 * 60


def _review_attribution_enabled() -> bool:
    """Whether `review <REF>` is recognised at all. **Defaults FALSE.**

    OFF is today's exact behaviour: `review WD-ORD-A7K2M9PQ` does not equal any keyword in
    `DEFAULT_FLOW_TRIGGERS['leave_review']`, the match at the keyword loop is `in`, so it
    falls through with no reply. With the flag off this branch returns before matching
    anything and that fall-through is preserved byte for byte.

    It has to default off rather than ship enabled, for the same reason
    `_standby_reply_enabled` has to default to TODAY'S behaviour: the inbound ingress
    invokes `wecare-inbound-whatsapp` UNQUALIFIED, so `$LATEST` is production the instant
    `update-function-code` returns and there is no alias gap in which to verify. The owner
    flips this after publishing the Flow version on Meta.

    Read per call, never cached at module scope - a module-scope read is frozen for the
    life of the execution environment, so flipping it would not take effect until every
    warm sandbox recycled.
    """
    return os.environ.get('REVIEW_ATTRIBUTION_ENABLED', 'false').strip().lower() \
        in ('true', '1', 'yes', 'on')


def _extract_review_reference(content_lower: str) -> str:
    """The order/product reference in a `review <REF>` message, or ''.

    Upper-cased, which is lossless here: the public order-number alphabet
    (`order_keys.PUBLIC_ORDER_NUMBER_ALPHABET`) and the `WD-ORD-`/`WD-PAY-` prefixes are
    already upper-case and digits, so recovering the customer's original string from the
    lowercased `content_lower` needs nothing more than this.
    """
    import re
    match = re.match(_REVIEW_REF_PATTERN, (content_lower or '').strip())
    return match.group(1).upper() if match else ''


def _park_review_reference(sender_phone: str, reference: str, request_id: str) -> bool:
    """Park the reference for the Flow callback to read back. Key `{phone}#WD_REV_REF`.

    Written in the shape `flows/common.restore_draft` expects - `formData` as a JSON
    STRING, not a map - because that helper is the reader and it `json.loads` the field.

    `expiresAt` travels INSIDE `formData` rather than beside it, because `restore_draft`
    returns only `{screen, formData}` and drops every other attribute of the item. The
    DynamoDB `ttl` is set to the same instant, but TTL deletion is best-effort and can lag
    by up to 48 hours, so it reclaims the row while `expiresAt` is what actually bounds the
    attribution. See `REVIEW_REF_TTL_SECONDS` for why that bound is short.

    The reference is logged IN FULL, deliberately. It is neither a secret nor a phone
    number, and it is the one field that makes a review traceable end to end without
    unmasking anything - the same reasoning `reference_id` carries on the payment path.
    """
    try:
        now = int(time.time())
        expires_at = now + REVIEW_REF_TTL_SECONDS
        dynamodb.Table(FLOW_DRAFTS_TABLE).put_item(Item={
            'draftKey': f'{sender_phone}#{REVIEW_REF_DRAFT_CODE}',
            'phone': sender_phone,
            'flowCode': REVIEW_REF_DRAFT_CODE,
            'screen': 'REVIEW_FORM',
            'formData': json.dumps({'reference': reference, 'expiresAt': expires_at}),
            'updatedAt': Decimal(str(now)),
            'ttl': expires_at,
        })
        return True
    except Exception as e:
        logger.warning(json.dumps({
            'event': 'review_reference_park_failed',
            'reference': reference,
            'phone': mask_phone(sender_phone),
            'error': type(e).__name__,
            'requestId': request_id,
        }))
        return False


#: Where a Flow keyword sends the customer when the Flow itself cannot open: on WABA 2 (Flows
#: live on WABA 1 only), when the trigger has no Flow, or when FlowRegistry does not show the
#: Flow live on Meta. Direct destinations, not `/r/` short codes: a code's target lives in
#: ShortLinksTable and can drift (`sr`, `ar`, `rx`, `ea`, `sub` and `lr` were 2026-07 "recovery"
#: rows redirecting to google.com until 2026-10-25). Every target below answered HTTP 200
#: (wa.me: 302 to WhatsApp) on 2026-10-25.
FLOW_LINKS = {
    'submit_request': 'https://wecare.digital/submit-request/',
    'track_request': 'https://wecare.digital/shipments/track/',
    'amend_request': 'https://wecare.digital/request-amendment/',
    'schedule_appointment': 'https://wecare.digital/contact/',
    'rx_slot': 'https://wecare.digital/sehat/',
    'drop_docs': 'https://wecare.digital/drop-docs/',
    'enterprise_assist': 'https://wecare.digital/contact/',
    # Both review doors share one Meta Flow, so they share the owner's verified review link.
    'leave_review': 'https://wa.me/message/ZM74K2H2BIFOA1',
    'customer_idea': 'https://wa.me/message/ZM74K2H2BIFOA1',
    # F001 Subscribe has no web form and exists on WABA 1 only, so a WABA 2 customer continues
    # on WABA 1 with the keyword already typed.
    'subscribe': 'https://wa.me/919330994400?text=subscribe',
    'order_notes': 'https://wecare.digital/orders/',
}
FLOW_LINK_DEFAULT = 'https://wecare.digital/contact/'
FLOW_LINK_BODIES = {
    'submit_request': '\U0001f4cb Start a new support request. Share the details and our team will follow up with you.',
    'track_request': '\U0001f50d Check the status of your request anytime with your reference ID.',
    'amend_request': '\u270f\ufe0f Need to make a change? Edit or correct your submitted request.',
    'schedule_appointment': '\U0001f4c5 Schedule a consultation or service visit at a time that works best for you.',
    'rx_slot': '\U0001fa7a Schedule a medical tourism or prescription-related visit.',
    'drop_docs': '\U0001f4c4 Send supporting documents for your request.',
    'enterprise_assist': '\U0001f3e2 Corporate, B2B, and bulk enquiries. Tell us what you need.',
    'leave_review': '\u2b50 Share your experience with our service.',
    'subscribe': ('Save your details for faster service on WECARE.DIGITAL. Subscribe opens on our '
                  'main WhatsApp number: tap below, then send the message as it is.'),
    'order_notes': '\U0001f4dd Add notes to your order with any special instructions.',
}


def _send_flow_link(contact_id: str, phone_number_id: str, flow_key: str,
                    flow_config: Optional[Dict], request_id: str, *, reason: str) -> bool:
    """Answer a Flow keyword with its website (or WhatsApp) link. Returns True once handed off."""
    msg = (flow_config or {}).get('message') or {}
    link = FLOW_LINKS.get(flow_key, FLOW_LINK_DEFAULT)
    cta_text = msg.get('flowCta') or flow_key.replace('_', ' ').title()
    body_text = FLOW_LINK_BODIES.get(flow_key, msg.get('body') or 'Tap below to continue.')
    _send_cta_button(contact_id, phone_number_id, cta_text, link, request_id,
                     body_text=body_text, footer_text='WECARE.DIGITAL')
    logger.info(json.dumps({
        # The WABA 2 event keeps its established name; the others are keyword fallbacks.
        'event': 'generic_flow_phone2_cta_sent' if reason == 'waba2' else 'keyword_flow_link_fallback',
        'flowKey': flow_key, 'reason': reason, 'contactId': mask_contact_id(contact_id),
        'shortUrl': link, 'phoneNumberId': phone_number_id, 'requestId': request_id,
    }))
    return True


def _send_generic_flow(contact_id: str, phone_number_id: str, sender_phone: str,
                       request_id: str, flow_config: Dict = None, flow_key: str = '',
                       flow_token: str = '') -> bool:
    """
    Generic flow sender  -  works for all flow types.
    
    Phone 1 (WABA 1): Sends WhatsApp Flow interactive message (flows exist on WABA 1).
    Phone 2 (WABA 2): Sends a CTA URL button with the door's `FLOW_LINKS` destination.
    Flows are WABA-specific  -  they only exist on the WABA where they were created.

    `flow_token` is a server-issued session token (F001); without one a token is minted
    here as before. Returns whether the message was handed to the outbound sender.
    """
    try:
        flow_id = (flow_config or {}).get('flowId', '')
        if not flow_id:
            logger.warning(json.dumps({
                'event': 'generic_flow_no_id',
                'flowKey': flow_key,
                'contactId': mask_contact_id(contact_id),
                'requestId': request_id,
            }))
            return False
        msg = (flow_config or {}).get('message', {})

        # ── Phone 2: check if WABA 2 has its own flow, otherwise CTA fallback ──
        if phone_number_id == PHONE_NUMBER_ID_2:
            flow_id_2 = (flow_config or {}).get('flowId2', '')
            if flow_id_2:
                # WABA 2 has its own flow  -  use it instead of WABA 1 flow
                flow_id = flow_id_2
                logger.info(json.dumps({
                    'event': 'generic_flow_using_waba2_flow',
                    'flowKey': flow_key, 'flowId2': flow_id_2, 'requestId': request_id,
                }))
                # Fall through to flow sending logic below
            else:
                # No WABA 2 flow  -  send the website link instead
                return _send_flow_link(contact_id, phone_number_id, flow_key, flow_config,
                                       request_id, reason='waba2')

        # ── Phone 1: send WhatsApp Flow interactive message ──
        _waba_suffix = '1' if phone_number_id == PHONE_NUMBER_ID_1 else '2'
        flow_token = flow_token or f'{flow_key[:10]}-{uuid.uuid4()}-waba-{_waba_suffix}-ph-{sender_phone}'

        # Flows whose FIRST screen is STATIC (needs no endpoint data at open) must
        # open with NAVIGATE, not data_exchange. NAVIGATE renders the first screen
        # client-side and SKIPS the endpoint INIT round-trip — removing the "stuck
        # on loading" latency (per Meta Flows performance guidance). The endpoint is
        # still called later on data_exchange screens (e.g. REVIEW), so no data is
        # lost. Only order-fetching flows (submit_request, etc.) need data_exchange
        # at open to populate their first screen.
        # `leave_review` is the canonical F002 door; the historical `customer_idea` alias points at the same Flow, so it
        # needs the same entry screen: that flow is endpointless and would fail at
        # open under data_exchange.
        STATIC_ENTRY_SCREENS = {'customer_idea': 'FEEDBACK', 'leave_review': 'FEEDBACK'}
        _entry_screen = STATIC_ENTRY_SCREENS.get(flow_key, '')
        flow_action = 'navigate' if _entry_screen else 'data_exchange'

        interactive_data = {
            'body': msg.get('body', 'Please fill in the details below.'),
            'footer': msg.get('footer', 'WECARE.DIGITAL'),
            'flowId': flow_id,
            'flowCta': msg.get('flowCta', flow_key.replace('_', ' ').title()),
            'flowAction': flow_action,
            'flowToken': flow_token,
        }
        if _entry_screen:
            interactive_data['screenId'] = _entry_screen

        header_val = msg.get('header', '')
        if header_val:
            interactive_data['header'] = header_val

        payload = {
            'body': json.dumps({
                'contactId': contact_id,
                'phoneNumberId': phone_number_id,
                'isInteractive': True,
                'interactiveType': 'flow',
                'interactiveData': interactive_data,
            })
        }

        response = lambda_client.invoke(
            FunctionName=OUTBOUND_WHATSAPP_FUNCTION,
            InvocationType='Event',
            Payload=json.dumps(payload)
        )

        logger.info(json.dumps({
            'event': 'generic_flow_sent',
            'flowKey': flow_key,
            'contactId': mask_contact_id(contact_id),
            'senderPhone': mask_phone(sender_phone),
            'flowId': flow_id,
            'flowToken': mask_flow_token(flow_token),
            'statusCode': response.get('StatusCode'),
            'requestId': request_id
        }))
        # An Event invoke answers 202 once the outbound sender has accepted the payload.
        return response.get('StatusCode') in (200, 202)

    except Exception as e:
        logger.error(json.dumps({
            'event': 'generic_flow_error',
            'flowKey': flow_key,
            'contactId': mask_contact_id(contact_id),
            'errorType': type(e).__name__,
            'requestId': request_id
        }))
        return False


def _send_wd_list(list_key: str, contact_id: str, sender_phone: str,
                  aws_phone_number_id: str, request_id: str) -> bool:
    """Send one WD_LISTS interactive list straight to the Meta Graph API.

    SELF-CONTAINED ON PURPOSE, and not a style preference. The generic interactive
    sender in `wecare-outbound-whatsapp` was deleted on 2026-10-02 and now answers
    `interactiveType='list'` with a 400 ("'list' interactive sends were deleted"),
    so delegating there would fail every menu send. This uses the handler's own
    existing Graph path instead: `_load_direct_api_token` reads
    `wecare/meta-system-user-token` lazily, by reference, at request time, and
    `_send_direct_api_message` owns the POST, the bearer header and the
    appsecret_proof. No new secret read, no new HTTP code.

    Returns True when the list was sent (or deliberately suppressed by the
    live-smoke lockdown), False when the caller should fall back. Never raises —
    a menu send must not break `_process_message`.
    """
    try:
        spec = WD_LISTS.get(list_key)
        if not spec:
            logger.warning(json.dumps({
                'event': 'wd_list_unknown_key',
                'listKey': list_key,
                'contactId': mask_contact_id(contact_id),
                'requestId': request_id,
            }))
            return False

        # The direct Graph send bypasses outbound-whatsapp's live_smoke gate, so the
        # lockdown is re-applied here. With WA_LIVE_SMOKE_TEST absent (the state
        # today) check_recipient returns (True, 'not_smoke_mode') and nothing changes.
        allowed, reason = live_smoke.check_recipient(sender_phone)
        if not allowed:
            logger.info(json.dumps({
                'event': 'wd_list_smoke_blocked',
                'listKey': list_key,
                'reason': reason,
                'senderPhone': mask_phone(sender_phone or ''),
                'contactId': mask_contact_id(contact_id),
                'requestId': request_id,
            }))
            return True  # handled, not failed — do not fall back and send anyway

        rows = []
        for row in spec.get('rows', [])[:10]:
            entry = {'id': row['id'], 'title': row['title'][:24]}
            if row.get('description'):
                entry['description'] = row['description'][:72]
            rows.append(entry)

        body_text = spec.get('body', '')[:1024]
        interactive: Dict[str, Any] = {
            'type': 'list',
            'body': {'text': body_text},
            'action': {
                'button': spec.get('button', 'Open Menu')[:20],
                'sections': [{'title': spec.get('section', 'Menu')[:24], 'rows': rows}],
            },
        }
        if spec.get('header'):
            interactive['header'] = {'type': 'text', 'text': spec['header'][:60]}

        result = _send_direct_api_message(
            sender_phone,
            {'type': 'interactive', 'interactive': interactive},
            meta_phone_id=_get_meta_phone_id_for_direct_api(aws_phone_number_id),
        )

        if not result.get('success'):
            # Shape only. Never the token, never the full Graph body.
            logger.error(json.dumps({
                'event': 'wd_list_send_failed',
                'listKey': list_key,
                'status': result.get('status'),
                'contactId': mask_contact_id(contact_id),
                'requestId': request_id,
            }))
            return False

        logger.info(json.dumps({
            'event': 'wd_list_sent',
            'listKey': list_key,
            'rowCount': len(rows),
            'contactId': mask_contact_id(contact_id),
            'requestId': request_id,
        }))
        # A direct Graph send writes no message record, so mirror it into the inbox
        # the way the deleted outbound path did. Non-blocking by construction.
        try:
            put_message(
                channel='whatsapp',
                direction='outbound',
                contact_id=contact_id,
                content=f'[Menu: {list_key}] {body_text}',
                status='sent',
                message_id=result.get('messageId') or None,
                messageType='interactive_list',
                raise_on_error=False,
            )
        except Exception as _me:
            logger.warning(f'wd_list inbox mirror skipped: {type(_me).__name__}')
        return True
    except Exception as e:
        logger.error(json.dumps({
            'event': 'wd_list_error',
            'listKey': list_key,
            'error': type(e).__name__,
            'contactId': mask_contact_id(contact_id),
            'requestId': request_id,
        }))
        return False


def _route_wd_list_reply(list_id: str, contact_id: str, sender_phone: str,
                         aws_phone_number_id: str, request_id: str,
                         source_message_id: str = '') -> str:
    """Route one tapped list row. Three ways out and no fourth.

    Returns a short token naming which way it went ('back', 'list', 'leaf',
    'unknown') so the behaviour is testable without a live send. The caller has
    already logged `list_reply_received` with the raw id.

    Nothing falls through and nothing raises: a stale row from a deleted menu, a
    typo and an empty id all re-open the main menu.
    """
    if str(list_id or '').startswith('vaultpick:') and os.environ.get('WHATSAPP_CATALOG_SERVICES_ENABLED', 'false').lower() == 'true':
        parts = list_id.split(':')
        if len(parts) != 3 or not parts[2].isdigit():
            return 'unknown'
        lambda_client.invoke(FunctionName='wecare-whatsapp-business-api:live', InvocationType='Event',
            Payload=json.dumps({'internalAction': 'catalogService', 'action': 'select',
                'token': parts[1], 'fileIndex': int(parts[2]), 'contactId': contact_id,
                'senderPhone': sender_phone, 'sourceMessageId': source_message_id,
                'phoneNumberId': aws_phone_number_id}).encode())
        return 'vault'
    if list_id == 'wd_drop_docs':
        if _route_paid_drop_docs(contact_id, sender_phone, aws_phone_number_id,
                                 source_message_id, request_id):
            return 'drop_docs'
        _send_wd_leaf_link(list_id, contact_id, aws_phone_number_id, request_id)
        return 'leaf'
    if list_id == 'wd_back':
        # Explicit, so WD_LISTS stays one key per list rather than gaining an alias.
        _send_wd_main_menu(contact_id, sender_phone, aws_phone_number_id, request_id)
        return 'back'
    if list_id in WD_LISTS:
        if not _send_wd_list(list_id, contact_id, sender_phone, aws_phone_number_id, request_id):
            _send_wd_main_menu(contact_id, sender_phone, aws_phone_number_id, request_id)
        return 'list'
    if list_id in WD_LEAF_LINKS:
        _send_wd_leaf_link(list_id, contact_id, aws_phone_number_id, request_id)
        return 'leaf'
    # An old cached `menu_*` id, a typo, an empty id. Never silent.
    logger.info(json.dumps({
        'event': 'wd_list_reply_unknown',
        'listId': list_id,
        'contactId': mask_contact_id(contact_id),
        'requestId': request_id,
    }))
    _send_wd_main_menu(contact_id, sender_phone, aws_phone_number_id, request_id)
    return 'unknown'


def _send_wd_main_menu(contact_id: str, sender_phone: str, aws_phone_number_id: str,
                       request_id: str) -> None:
    """Send the main menu, falling back to the plain-text stand-in if Meta refuses.

    The fallback is what keeps "nothing goes silent" true even with no token or a
    Graph outage.
    """
    if not _send_wd_list('wd_main', contact_id, sender_phone, aws_phone_number_id, request_id):
        _send_menu_placeholder(contact_id, aws_phone_number_id, request_id)


def _send_wd_leaf_link(leaf_id: str, contact_id: str, aws_phone_number_id: str,
                       request_id: str) -> None:
    """Answer a tapped leaf row with the site link as plain text.

    Goes through `_send_ai_auto_reply` rather than the direct Graph path: a text
    send still works downstream, and routing it through `outbound-whatsapp` keeps
    the inbox record and the live-smoke lockdown for free.
    """
    entry = WD_LEAF_LINKS.get(leaf_id)
    if not entry:
        return
    name, path = entry
    url = path if path.startswith('https://') else f'{WD_SITE_BASE}{path}'
    text = WD_LEAF_TEMPLATE.format(name=name, url=url)
    # leafId and path are neither secrets nor phone numbers, so they are logged in
    # full — the same reasoning the payments steering gives for referenceId.
    logger.info(json.dumps({
        'event': 'wd_leaf_link_sent',
        'leafId': leaf_id,
        'path': path,
        'contactId': mask_contact_id(contact_id),
        'requestId': request_id,
    }))
    _send_ai_auto_reply(contact_id, text, aws_phone_number_id, request_id)


def _send_menu_placeholder(contact_id: str, phone_number_id: str, request_id: str) -> None:
    """Send the plain-text stand-in — the DEGRADED FALLBACK, not the menu.

    The real menu is `WD_LISTS` via `_send_wd_list`. This is what a customer gets
    when that Graph send fails (no token, HTTP error), so a greeting is answered
    rather than met with silence.

    The string itself must not drift: `tests/test_calling_menu_template_is_gone.py`
    asserts this Lambda's `MENU_PLACEHOLDER_TEXT` is byte-identical to the
    `whatsapp-calling` Lambda's own copy, because the two share no module and a
    drift would make one WABA answer differently from the other.
    """
    logger.info(json.dumps({
        'event': 'menu_placeholder_sent',
        'contactId': mask_contact_id(contact_id),
        'requestId': request_id,
    }))
    _send_ai_auto_reply(contact_id, MENU_PLACEHOLDER_TEXT, phone_number_id, request_id)


def _send_cta_button(contact_id: str, phone_number_id: str, cta_text: str, cta_url: str, request_id: str,
                     body_text: str = '', header_text: str = '', footer_text: str = '') -> None:
    """Send a WhatsApp CTA URL button message with body text.
    Sends ONE interactive message with body text + CTA button."""
    if not contact_id or not cta_url:
        return

    try:
        interactive_data: Dict[str, Any] = {
            'body': body_text or cta_text,
            'buttonText': cta_text[:20],  # Max 20 chars for CTA display text
            'url': cta_url,
        }
        if header_text:
            interactive_data['header'] = header_text
        if footer_text:
            interactive_data['footer'] = footer_text

        payload = {
            'body': json.dumps({
                'contactId': contact_id,
                'phoneNumberId': phone_number_id,
                'isInteractive': True,
                'interactiveType': 'cta_url',
                'interactiveData': interactive_data,
            })
        }

        response = lambda_client.invoke(
            FunctionName=OUTBOUND_WHATSAPP_FUNCTION,
            InvocationType='Event',
            Payload=json.dumps(payload)
        )

        logger.info(json.dumps({
            'event': 'cta_button_sent',
            'contactId': mask_contact_id(contact_id),
            'ctaText': cta_text,
            'ctaUrl': cta_url,
            'statusCode': response.get('StatusCode'),
            'requestId': request_id
        }))

    except Exception as e:
        logger.error(json.dumps({
            'event': 'cta_button_error',
            'contactId': mask_contact_id(contact_id),
            'error': str(e),
            'requestId': request_id
        }))


def _send_help_about(contact_id: str, phone_number_id: str, request_id: str) -> None:
    """The one menu's single Help row, and the `help & about` keyword.

    This reply carries the weight of the 10-row cap. Meta allows 10 rows in a
    list; the previous main menu plus the customer-service submenu held 18 between
    them. The 8 that did not make the cut were not deleted — they moved to
    keyword access — and this is the only place a customer is told they exist.
    Do not trim the "just type" list without moving those entries onto the menu.
    """
    help_text = (
        "*Help & About*\n\n"
        "WECARE.DIGITAL builds Everyday AI and everyday services for Bharat "
        "\u2014 for people, businesses, climate tech, and emerging technology.\n\n"
        "Type *menu* anytime for everything in one place.\n\n"
        "*Not on the menu? Just type:*\n"
        "\u2022 *my id* \u2014 find your profile or subscription ID\n"
        "\u2022 *store* \u2014 browse services, brands, and offers\n"
        "\u2022 *gift card* \u2014 send a digital gift card\n"
        "\u2022 *order notes* \u2014 add notes to an existing order\n"
        "\u2022 *review* \u2014 share your experience with us\n"
        "\u2022 *bharat stack* \u2014 Aadhaar, UPI, DigiLocker, and more\n\n"
        "We are available 24/7 for online orders and support. "
        "Prefer to talk? Call +91 9330994400 or email one@wecare.digital.\n\n"
        "Tap below for the full FAQ page. \U0001f447"
    )
    _send_cta_button(contact_id, phone_number_id, 'Open FAQs', 'https://wecare.digital/contact/', request_id,
        body_text=help_text,
        footer_text='WECARE.DIGITAL')


def _send_audio_response(contact_id: str, phone_number_id: str, text: str, language: str, request_id: str,
                         sender_phone: str = '', sender_bsuid: str = '') -> None:
    """
    Invoke the whatsapp-voice Lambda to generate TTS audio and send it.
    Called when user has audioEnabled=True.
    """
    if not contact_id or not text or len(text.strip()) < 5:
        return

    # Map language preference to Polly voice/language code
    # Languages with native Polly voices use them; others use best fallback
    LANG_TO_POLLY = {
        # ── Popular (Indian + English) ──
        'english': ('Kajal', 'en-IN'),
        'hindi': ('Kajal', 'hi-IN'),
        'hinglish': ('Kajal', 'hi-IN'),
        'bengali': ('Kajal', 'hi-IN'),       # No native voice → Hindi fallback
        'tamil': ('Kajal', 'en-IN'),         # No native voice → English fallback
        'telugu': ('Kajal', 'en-IN'),        # No native voice
        'gujarati': ('Kajal', 'hi-IN'),      # No native voice → Hindi fallback
        'marathi': ('Kajal', 'hi-IN'),       # No native voice → Hindi fallback
        'kannada': ('Kajal', 'en-IN'),       # No native voice
        'malayalam': ('Kajal', 'en-IN'),     # No native voice
        # ── Asian ──
        'chinese': ('Zhiyu', 'cmn-CN'),
        'japanese': ('Kazuha', 'ja-JP'),
        'korean': ('Seoyeon', 'ko-KR'),
        'thai': ('Kajal', 'en-IN'),          # No native voice
        'vietnamese': ('Kajal', 'en-IN'),    # No native voice
        'indonesian': ('Kajal', 'en-IN'),    # No native voice
        'malay': ('Kajal', 'en-IN'),         # No native voice
        'sinhala': ('Kajal', 'en-IN'),       # No native voice
        # ── Middle East ──
        'arabic': ('Hala', 'arb'),
        'turkish': ('Burcu', 'tr-TR'),
        'russian': ('Tatyana', 'ru-RU'),
        'urdu': ('Kajal', 'hi-IN'),          # No native voice → Hindi fallback
        'punjabi': ('Kajal', 'hi-IN'),       # No native voice → Hindi fallback
        # ── European ──
        'french': ('Lea', 'fr-FR'),
        'spanish': ('Lupe', 'es-US'),
        'portuguese': ('Camila', 'pt-BR'),
        'italian': ('Bianca', 'it-IT'),
        'german': ('Vicki', 'de-DE'),
        'dutch': ('Laura', 'nl-NL'),
        'polish': ('Ola', 'pl-PL'),
        'swedish': ('Elin', 'sv-SE'),
        'danish': ('Sofie', 'da-DK'),
        'norwegian': ('Ida', 'nb-NO'),
        'finnish': ('Suvi', 'fi-FI'),
        'catalan': ('Arlet', 'ca-ES'),
        'romanian': ('Carmen', 'ro-RO'),
        'welsh': ('Gwyneth', 'cy-GB'),
    }
    voice_id, lang_code = LANG_TO_POLLY.get(language.lower(), ('Kajal', 'en-IN'))

    try:
        # The voice Lambda expects an HTTP-style event with POST /whatsapp-voice/tts
        tts_payload = {
            'requestContext': {'http': {'method': 'POST'}},
            'rawPath': '/whatsapp-voice/tts',
            'body': json.dumps({
                'contactId': contact_id,
                'phoneNumber': sender_phone,
                'messageText': text[:500],  # Polly limit
                'voiceId': voice_id,
                'languageCode': lang_code,
                'engine': 'neural',
                'phoneNumberId': phone_number_id,
                'recipientBsuid': sender_bsuid,
            })
        }

        response = lambda_client.invoke(
            FunctionName=WHATSAPP_VOICE_FUNCTION,
            InvocationType='Event',  # Async  -  don't block
            Payload=json.dumps(tts_payload)
        )

        logger.info(json.dumps({
            'event': 'audio_response_triggered',
            'contactId': mask_contact_id(contact_id),
            'voiceId': voice_id,
            'langCode': lang_code,
            'textLength': len(text),
            'statusCode': response.get('StatusCode'),
            'requestId': request_id
        }))

    except Exception as e:
        logger.error(json.dumps({
            'event': 'audio_response_error',
            'contactId': mask_contact_id(contact_id),
            'error': str(e),
            'requestId': request_id
        }))


def _auto_transcribe_voice_note(message_id: str, s3_key: str, request_id: str) -> None:
    """
    Async-invoke the whatsapp-voice Lambda to transcribe a voice note.
    The transcription result is stored back in the message record.
    Non-blocking (InvocationType='Event').
    """
    try:
        # Check if auto-transcribe is enabled in system config
        config_table = dynamodb.Table(
            os.environ.get('SYSTEM_CONFIG_TABLE', 'stack-wecare-digital-SystemConfigTable')
        )
        try:
            cfg_result = config_table.get_item(Key={'id': 'voice_language_config'})
            cfg_value = cfg_result.get('Item', {}).get('configValue', '{}')
            voice_config = json.loads(cfg_value) if isinstance(cfg_value, str) else cfg_value
            if not voice_config.get('autoTranscribe', True):
                return  # Auto-transcribe disabled
        except Exception:
            pass  # Default: auto-transcribe enabled

        transcribe_payload = {
            'requestContext': {'http': {'method': 'POST'}},
            'rawPath': '/whatsapp-voice/transcribe',
            'body': json.dumps({
                'messageId': message_id,
                's3Key': s3_key,
                'direction': 'INBOUND',
            })
        }

        response = lambda_client.invoke(
            FunctionName=WHATSAPP_VOICE_FUNCTION,
            InvocationType='Event',  # Async  -  don't block inbound processing
            Payload=json.dumps(transcribe_payload)
        )

        logger.info(json.dumps({
            'event': 'auto_transcribe_triggered',
            'messageId': message_id,
            's3Key': s3_key,
            'statusCode': response.get('StatusCode'),
            'requestId': request_id,
        }))

    except Exception as e:
        logger.warning(json.dumps({
            'event': 'auto_transcribe_error',
            'messageId': message_id,
            'error': str(e),
            'requestId': request_id,
        }))


def _fetch_catalog_product_names(catalog_id: str, retailer_ids: list) -> dict:
    """Fetch real product display names from a Meta catalog by retailer_id, so the
    order/invoice shows 'WECARE Test Product' instead of a raw SKU like 'htlu35lrs1'.
    Returns {retailer_id: name}; best-effort (empty on failure)."""
    names = {}
    rids = [r for r in {str(x) for x in (retailer_ids or [])} if r]
    if not catalog_id or not rids:
        return names
    try:
        import urllib.parse as _up
        token = _load_direct_api_token()
        app_secret = _direct_api_token_cache.get('app_secret', '')
        flt = json.dumps({'retailer_id': {'is_any': rids}})
        url = (f"https://graph.facebook.com/{META_API_VERSION}/{catalog_id}/products"
               f"?fields=name,retailer_id&limit=100&filter={_up.quote(flt)}&access_token={token}")
        if app_secret:
            url += '&appsecret_proof=' + hmac.new(app_secret.encode(), token.encode(), hashlib.sha256).hexdigest()
        with urllib.request.urlopen(urllib.request.Request(url), timeout=15) as r:
            data = json.loads(r.read().decode())
        for it in data.get('data', []):
            rid = it.get('retailer_id', '')
            if rid:
                names[rid] = it.get('name', rid)
    except Exception as e:
        logger.warning(json.dumps({'event': 'catalog_name_fetch_error', 'error': str(e)}))
    return names


def _phone_suffix(phone: str) -> str:
    """The last four digits, which is the only part of a phone number that may be logged.

    The masked suffix is AMBIGUOUS by design and that is cheaper than the alternative: `...0044`
    could be the owner's QA recipient or the secondary business number. Disambiguate on
    `direction`, `channel` or a delivery id, never by widening this.
    """
    digits = ''.join(character for character in str(phone or '') if character.isdigit())
    return digits[-4:] if len(digits) >= 4 else ''


def _handoff_url(token: str) -> str:
    """The link the customer opens. `/checkout/?basket=<token>` on the public site.

    The token is the only thing in the URL. It names a basket, it is phone-bound on the row, and
    the claim additionally requires a signed-in session whose phone matches - so a leaked link
    cannot be redeemed by whoever holds it.
    """
    return CART_HANDOFF_URL + '?basket=' + urllib.parse.quote(str(token or ''), safe='')


def _catalog_orders_enabled() -> bool:
    """The WhatsApp catalogue-order hand-off gate. DEFAULT OFF.

    Two sources: a SystemConfig row wins and the env var is the default, so an owner can turn
    this on without a deploy and off again in one write.

    OFF MEANS NOTHING HAPPENS AT ALL: no DynamoDB write, no outbound invoke, no reply. Not "reply
    with a shop link instead", because a silent no-op is the only state provably free of
    customer-visible effect, and this is the gate in front of a brand-new commerce path. A config
    READ FAILURE falls through to the env default rather than to True, so an unreachable table is
    never a way to turn the gate on.
    """
    try:
        item = dynamodb.Table(SYSTEM_CONFIG_TABLE).get_item(
            Key={'id': 'whatsapp_catalog_orders'}).get('Item')
        if item and 'configValue' in item:
            return str(item.get('configValue')).lower() in ('true', '1', 'yes', 'on')
    except Exception:
        pass
    return WA_CATALOG_ORDERS_ENABLED


#: The India Address Message's own field names (Meta "Address messages"), which are the only keys
#: a re-asked form may be prefilled with.
_ADDRESS_MESSAGE_FIELDS = ('name', 'phone_number', 'in_pin_code', 'house_number', 'floor_number',
                           'tower_number', 'building_name', 'address', 'landmark_area', 'city',
                           'state')

#: A refused address field -> (the Address Message field to mark, the line WhatsApp shows under
#: it). Meta's documented recovery for an address the business cannot use is to send the form
#: back with the customer's own values and a `validation_errors` entry per bad field, and
#: WhatsApp then holds the form until those fields change. Keyed on the canonical field names
#: `contact_address.UnusableAddress` and `payment_address.UnpayableAddress` report.
_ADDRESS_FIELD_ERRORS = {
    'postalCode': ('in_pin_code', 'Enter the 6-digit PIN code for this address.'),
    'state': ('state', 'Enter the state name in full, for example West Bengal.'),
    'city': ('city', 'Enter the city or town.'),
    'addressLine1': ('address', 'Enter the house number and street.'),
}


def _request_shipping_address(contact_id: str, phone_number_id: str, sender_phone: str,
                              request_id: str, body_text: str = '', *,
                              submitted: Optional[Dict[str, Any]] = None,
                              bad_field: str = '') -> None:
    """Ask for a delivery address with the India Address Message. Never raises.

    Called only AFTER checkout has refused a cart for its address: DELIVERY_DETAILS_REQUIRED
    (checkout's own test, `contact_address.from_contact` on the verified checkout profile then
    `payment_address.assert_payable`, found the address on file missing or unusable for a
    WhatsApp payment) or DELIVERY_CONFIRMATION_REQUIRED (the address is fine but has not been
    confirmed for this order). It used to run before checkout was invoked and skip any contact
    holding a legacy `shippingAddress`, so an unverified customer was asked for an address that
    could never make their cart payable, and a customer whose stored address was unpayable was
    never asked at all. The submission comes back as `nfm_reply`/`address_message`, is stored by
    `_handle_address_submission`, and resumes the waiting cart.

    A FRESH ask (no `submitted`) opens on the address already on file, so a returning customer
    confirms it in one tap instead of typing it again, and the copy says which case it is: confirm
    a payable address, correct an unpayable one (its bad field marked), or share one.

    A RE-ASK after a refused submission passes `submitted` (the customer's own form values) and
    the canonical `bad_field`, so the form comes back filled in with the one field to fix marked,
    instead of an empty form that reads as "we lost your address".
    """
    try:
        contact = {}
        if contact_id:
            contact = dynamodb.Table(CONTACTS_TABLE).get_item(
                Key={'id': contact_id}).get('Item', {}) or {}
        values = {}
        for key, value in (submitted or {}).items():
            if key in _ADDRESS_MESSAGE_FIELDS and isinstance(value, (str, int)) and str(value).strip():
                values[key] = str(value).strip()[:200]
        if submitted is None:
            from lambda_utils.ecommerce import contact_address, payment_address
            stored = contact_address.from_contact(contact)
            prefill = contact_address.to_meta_address_values(stored)
            if prefill:
                values.update(prefill)
                try:
                    payment_address.assert_payable(
                        stored, channel=payment_address.WHATSAPP_ORDER_DETAILS)
                    body_text = body_text or CART_REPLY_ADDRESS_CONFIRM
                except payment_address.UnpayableAddress as unpayable:
                    body_text = body_text or CART_REPLY_ADDRESS_FIX
                    bad_field = bad_field or unpayable.field
        body_text = body_text or CART_REPLY_ADDRESS
        values['phone_number'] = '+' + str(sender_phone or '').lstrip('+')
        name = contact.get('contactBookName', '') or contact.get('name', '') or ''
        if name and not values.get('name'):
            values['name'] = name
        interactive_data = {'body': body_text, 'country': 'IN', 'values': values}
        if bad_field in _ADDRESS_FIELD_ERRORS:
            field, message = _ADDRESS_FIELD_ERRORS[bad_field]
            interactive_data['validationErrors'] = {field: message}
        payload = {'body': json.dumps({
            'contactId': contact_id, 'phoneNumberId': phone_number_id,
            'isInteractive': True, 'interactiveType': 'address_message',
            'interactiveData': interactive_data,
        })}
        lambda_client.invoke(FunctionName=OUTBOUND_WHATSAPP_FUNCTION,
                             InvocationType='Event', Payload=json.dumps(payload))
    except Exception as error:
        logger.warning(json.dumps({'event': 'cart_address_request_error',
                                   'error': type(error).__name__, 'requestId': request_id}))


def _handle_cart_order(message: Dict, contact_id: str, sender_phone: str,
                       phone_number_id: str, request_id: str) -> None:
    """Native catalog checkout: parse the cart, then drive the unified native money leg.

    WHAT THIS DOES
    --------------
    Parses the catalogue `order` message into variants and integer quantities, refuses the three
    things that must never reach a commerce write (one of our own numbers as sender, a sender that
    is not E.164, a basket with no resolvable catalogue line), routes a SERVICE basket to the
    proven catalog-service convergence, and routes a general PRODUCT cart to `_send_payment_request`
    — the rebuilt money sender that drives a priced native ORDER_DETAILS send through the unified
    checkout machinery.

    WHY THERE IS NO PRICE AND NO REFERENCE IN THIS FILE
    ---------------------------------------------------
    The amount a customer pays and the single `PAYREF#` they pay against are BOTH owned by
    `ecommerce/checkout`. This function reads no `item_price`, computes no total, and mints no
    reference: the parse produces variants + quantities only (`whatsapp_basket`), and everything
    priced or reserved happens behind `_send_payment_request`'s one invoke of the checkout
    `prepareNativeCart` action. The defects the old build carried — a client price read as a float,
    18 percent GST re-added, a 2 percent convenience fee, synthetic retailer ids, a self-minted
    browser-style reference reserved nowhere, a free-form interactive-payment envelope — are
    structurally unreachable because none of those computations exist here any more.

    All the parse logic is in `lambda_utils.ecommerce.whatsapp_basket`, which is pure and tested on
    its own. This function is wiring: a gate, three refusals, a service branch and the general-cart
    hand-off to `_send_payment_request`.
    """
    try:
        if (not _catalog_orders_enabled()
                and os.environ.get('WHATSAPP_CATALOG_SERVICES_ENABLED', 'false').lower() != 'true'):
            logger.info(json.dumps({
                'event': 'cart_order_handoff_disabled',
                'phone_suffix': _phone_suffix(sender_phone),
                'requestId': request_id,
            }))
            return

        # BEFORE ANY WRITE AND BEFORE ANY SEND. One of our own numbers can appear as a sender when
        # a business number messages another, and replying to it would be us messaging ourselves on
        # a commerce path. `whatsapp_basket` holds the registry copy; a test pins it against
        # `notifications.events.business_numbers()`.
        if whatsapp_basket.is_business_sender(sender_phone):
            logger.warning(json.dumps({
                'event': 'cart_order_business_sender_refused',
                'phone_suffix': _phone_suffix(sender_phone),
                'requestId': request_id,
            }))
            return

        phone = whatsapp_basket.e164(sender_phone)
        if not phone:
            logger.warning(json.dumps({
                'event': 'cart_order_sender_not_e164',
                'phone_suffix': _phone_suffix(sender_phone),
                'requestId': request_id,
            }))
            return

        # The money path needs the number the cart was SENT TO, proven from the webhook's own
        # metadata - never `_get_aws_phone_number_id`'s WABA1 fallback for an unmapped number,
        # which would let a cart that reached another WABA (an Embedded-Signup tenant) be
        # answered with a WECARE payment request from WABA1.
        receiving_meta_id = str(_send_context.get('phone_number_id') or '')
        if META_PHONE_ID_MAP.get(receiving_meta_id) != phone_number_id:
            logger.warning(json.dumps({
                'event': 'cart_order_receiving_number_unproven',
                'metaPhoneId': receiving_meta_id,
                'requestId': request_id,
            }))
            return

        basket = whatsapp_basket.parse_order_message(message)
        if basket is None:
            # Nothing in the cart resolves to a catalogue variant. No later path answers an
            # `order` message (the dispatcher returns after this handler), so the customer is told
            # rather than left with silence.
            logger.info(json.dumps({
                'event': 'cart_order_no_resolvable_lines',
                'phone_suffix': _phone_suffix(sender_phone),
                'requestId': request_id,
            }))
            if _catalog_orders_enabled():
                _reply_cart_refused('items_unavailable', contact_id, phone_number_id, request_id)
            return

        # Part 1: Meta may display multi-product/multi-quantity catalog carts. Refuse the
        # whole unsupported selection instead of trimming to one item and charging another.
        # This guard is OFF until the owner approves the payment-rail rollout.
        if short_purchase.enabled() and not short_purchase.whatsapp_order_is_one_unit(message, basket):
            logger.info(json.dumps({'event': 'cart_order_short_only_refused',
                                    **basket.log_fields(), 'requestId': request_id}))
            _reply_cart_refused('short_only', contact_id, phone_number_id, request_id)
            return

        if os.environ.get('WHATSAPP_CATALOG_SERVICES_ENABLED', 'false').lower() == 'true':
            from lambda_utils.ecommerce.catalog_service_checkout import (service_from_lines,
                                                                         service_refusal)
            # A refused service cart used to raise out of this handler into the `except` below,
            # so the customer heard nothing. Each refusal now gets the reply that fits it.
            try:
                choice = service_from_lines(basket.lines)
            except ValueError:
                refusal = service_refusal(basket.lines)
                logger.info(json.dumps({'event': 'cart_order_service_refused', 'kind': refusal,
                                        **basket.log_fields(),
                                        'phone_suffix': _phone_suffix(sender_phone),
                                        'requestId': request_id}))
                _reply_cart_refused('service' if refusal == 'unsupported' else 'service_alone',
                                    contact_id, phone_number_id, request_id)
                return
            if choice:
                if basket.dropped or basket.clamped:
                    _reply_cart_refused('partial', contact_id, phone_number_id, request_id)
                    return
                lambda_client.invoke(FunctionName='wecare-whatsapp-business-api:live', InvocationType='Event',
                    Payload=json.dumps({'internalAction': 'catalogService', 'action': 'start',
                        'lines': basket.lines, 'sourceMessageId': basket.message_id,
                        'contactId': contact_id, 'senderPhone': sender_phone,
                        'phoneNumberId': phone_number_id}).encode())
                return

        if not _catalog_orders_enabled():
            return

        if basket.dropped:
            # Part of the cart is not ours (or is past the line ceiling). Charging for the rest
            # would bill an order the customer did not build, so the whole cart is refused and
            # they are told why - the same rule the service leg applies.
            logger.info(json.dumps({'event': 'cart_order_partial_refused', **basket.log_fields(),
                                    'phone_suffix': _phone_suffix(sender_phone),
                                    'requestId': request_id}))
            _reply_cart_refused('partial', contact_id, phone_number_id, request_id)
            return

        # The general PRODUCT cart. Everything priced, reserved and sent is owned by
        # `_send_payment_request` -> `ecommerce/checkout`; this function has already parsed the
        # basket and refused the three unsafe senders.
        _send_payment_request(basket, phone, contact_id, sender_phone, phone_number_id, request_id)
    except Exception as error:
        # `type(error).__name__`, not `str(error)`: an exception message on this path can carry
        # request content, and a phone number is request content.
        logger.error(json.dumps({'event': 'cart_order_error',
                                 'error': type(error).__name__, 'requestId': request_id}))


def _rollback_cart_order_index(keys, order_id: str, token: str, request_id: str) -> None:
    """Delete the resolve-before-generate index row this invocation wrote, so a retry can proceed.

    Called only when the `prepareNativeCart` invoke DEFINITELY did not prepare a payment (the
    Lambda service refused the invoke, or checkout answered anything other than
    `NATIVE_CART_PREPARED`); an ambiguous timeout keeps the index instead. The delete is
    CONDITIONAL on `token = :token`: the row we wrote carries this invocation's unguessable token,
    so if a concurrent winner has already replaced the row with its own the condition fails and we
    leave that live row untouched. That keeps the single-attempt invariant intact (we only ever
    clear an index that no prepared attempt is relying on) while making a transient failure
    recoverable. A missed condition is the expected, benign outcome, not an error.
    """
    try:
        keys.delete_item(Key={'orderId': order_id},
                         ConditionExpression='#t = :token',
                         ExpressionAttributeNames={'#t': 'token'},
                         ExpressionAttributeValues={':token': str(token)})
    except ClientError as error:
        if error.response.get('Error', {}).get('Code') != 'ConditionalCheckFailedException':
            raise
        # A concurrent winner replaced our row; its attempt is the live one. Nothing to roll back.
        logger.info(json.dumps({'event': 'cart_order_payment_index_retained',
                                 'requestId': request_id}))


def _send_payment_request(basket, phone: str, contact_id: str, sender_phone: str,
                          phone_number_id: str, request_id: str, *,
                          delivery_confirmed: bool = False,
                          delivery_recipient: str = '') -> None:
    """Drive the native WhatsApp ORDER_DETAILS money leg for a general PRODUCT cart.

    `delivery_confirmed` is True only when `_resume_pending_cart` re-enters here from the
    customer's Address Message submission for this cart; `delivery_recipient` is the name they
    typed on that form. Checkout asks for that confirmation on every cart it can otherwise pay.

    THE MONEY SENDER, REBUILT ON THE UNIFIED MACHINERY. The owner authorised rebuilding this
    function; it is deliberately NOT the self-contained calculator-and-sender that was deleted.
    It computes NO money and mints NO reference. The amount comes from `_native_quote`
    (ProductsTable, integer paise) and the ONE `PAYREF#` + ONE PaymentAttempt come from the
    checkout reservation — both reached through a single invoke of `wecare-commerce:live`'s
    `prepareNativeCart` internal action, the general-cart twin of the catalog-service convergence.
    The approved Meta template `wecare_whatapp_native_pay_template` is sent by `_send_order_details`
    inside that action, never from here.

    IDEMPOTENCY AGAINST A REDELIVERED WEBHOOK. Meta redelivers an `order` webhook whenever our ack
    is lost. The resolve-before-generate `build_message_index` conditional write is the guard: the
    FIRST delivery to win `attribute_not_exists(orderId)` is the only one that invokes checkout, so
    a redelivery (same wamid, or the no-wamid content key) cannot produce a second attempt or a
    second `order_details` send. The attempt-level send claim in the checkout reservation
    (`wa_payment_request.claim_send` / the `sendStatus` guard on the native service leg) is the
    second line of defence for the catalog-service path; for the general cart the message index is
    the single point a duplicate is collapsed before any attempt is minted.

    NO client price, NO float, NO self-minted browser-style reference, NO 2%/18% constant. All of
    those lived in the deleted sender's own arithmetic; this function performs none.
    """
    # An address submission can resume a cart created before rollout. Refuse old multi-unit
    # pending carts BEFORE allocating any dedupe index, payment reference or attempt.
    if short_purchase.enabled() and not short_purchase.one_unit_lines(basket.lines):
        _reply_cart_refused('short_only', contact_id, phone_number_id, request_id)
        return
    keys = dynamodb.Table(COMMERCE_KEYS_TABLE)
    now = int(time.time())

    # RESOLVE BEFORE GENERATE. A redelivered cart must not mint a second attempt. The index row is
    # written FIRST and conditionally; whichever delivery wins it is the only one that reaches the
    # checkout invoke, and every later delivery reads it back and stops. ALWAYS a row: wamid-keyed
    # when Meta sent an id, else a deterministic content+phone key, so a redelivery WITH OR WITHOUT
    # a wamid loses this write.
    token = whatsapp_basket.new_token()
    index = whatsapp_basket.build_message_index(basket, token, now, phone=phone)
    try:
        keys.put_item(Item=index, ConditionExpression='attribute_not_exists(orderId)')
    except ClientError as error:
        if error.response.get('Error', {}).get('Code') != 'ConditionalCheckFailedException':
            raise
        # A redelivery. The attempt was already prepared and the message already went out on the
        # delivery that won. Re-invoking checkout would risk a second attempt, so we stop here.
        existing = keys.get_item(Key={'orderId': index['orderId']}).get('Item') or {}
        logger.info(json.dumps({
            'event': 'cart_order_payment_replayed',
            'indexType': str(index.get('indexType') or ''),
            'sourceMessageId': basket.message_id,
            'resolvedHandoff': str(existing.get('handoffId') or ''),
            'phone_suffix': _phone_suffix(sender_phone),
            'requestId': request_id,
        }))
        return

    # The delivery address is asked for only AFTER checkout says it is what is missing or not yet
    # confirmed for this order (DELIVERY_DETAILS_REQUIRED / DELIVERY_CONFIRMATION_REQUIRED, below).
    # Asking before the invoke prompted customers whose cart was going to be refused for another
    # reason, and skipped those whose stored address was unpayable.
    prepare = {'internalAction': 'prepareNativeCart', 'lines': basket.lines,
               'sourceMessageId': basket.message_id, 'contactId': contact_id,
               'senderPhone': sender_phone, 'phoneNumberId': phone_number_id}
    if delivery_confirmed:
        prepare['deliveryConfirmed'] = True
        recipient = ' '.join(str(delivery_recipient or '').split())[:120]
        if recipient:
            prepare['deliveryRecipient'] = recipient

    # THE ONE SEAM. `prepareNativeCart` resolves the verified customer from the contact, prices the
    # basket via `_native_quote`, reserves the single attempt + `PAYREF#` carrying contactId +
    # customerUuid, and sends the approved template through `_send_order_details`. We pass variants
    # and integer quantities only; no amount of any kind travels in this payload.
    #
    # ROLLBACK ONLY WHEN NOTHING CAN HAVE BEEN RESERVED. The index row was written BEFORE this
    # invoke so a redelivery cannot race us into a second attempt. Which redeliveries reach this
    # point: the wamid was already claimed permanently in WebhookDedup at the top of
    # `_process_message`, so a Meta redelivery of the SAME wamid stops there, before this
    # function. What the rollback re-opens is the content-keyed (wamid-less) index, and with it
    # the customer's own retry of the same cart. So:
    #   * a definite failure (the Lambda service refused the invoke, or checkout answered anything
    #     other than NATIVE_CART_PREPARED) deletes OUR index row, conditionally on `token`;
    #   * an AMBIGUOUS failure (no answer within the read timeout, the connection dropped after
    #     the request was sent, or checkout itself timed out) KEEPS the index, because checkout
    #     may already have reserved the attempt and sent the template, and re-opening the key
    #     could let a retry create a second payment request for the same cart.
    # The `token = :token` guard means we never clear an index another live prepare relies on.
    # The SUCCESS path never deletes, so a prepared cart collapses every redelivery to one attempt.
    from botocore.exceptions import ConnectionClosedError, ReadTimeoutError
    outcome = ''
    ambiguous = False
    try:
        response = _checkout_invoke_client().invoke(
            FunctionName=CHECKOUT_FUNCTION, InvocationType='RequestResponse',
            Payload=json.dumps(prepare).encode())
        raw = response['Payload'].read()
        result = json.loads(raw.decode('utf-8')) if raw else {}
        outcome = str(result.get('outcome') or '')
        if response.get('FunctionError') and 'timed out' in str(
                result.get('errorMessage') or '').lower():
            ambiguous = True
        # Checkout reserved the attempt but could not confirm the template left: it may be on
        # the customer's phone already, so this is not a definite failure either.
        if result.get('sendUnconfirmed') is True:
            ambiguous = True
    except (ReadTimeoutError, ConnectionClosedError) as error:
        ambiguous = True
        logger.error(json.dumps({'event': 'cart_order_payment_invoke_ambiguous',
                                 'error': type(error).__name__,
                                 'phone_suffix': _phone_suffix(sender_phone),
                                 'requestId': request_id}))
    except Exception as error:  # noqa: BLE001
        logger.error(json.dumps({'event': 'cart_order_payment_invoke_error',
                                 'error': type(error).__name__,
                                 'phone_suffix': _phone_suffix(sender_phone),
                                 'requestId': request_id}))
        _rollback_cart_order_index(keys, index['orderId'], token, request_id)
        # Definite: the Lambda service refused the invoke, so checkout never ran.
        _reply_cart_refused('try_later', contact_id, phone_number_id, request_id)
        return

    if ambiguous:
        # Index retained on purpose; see above. An operator reconciles from the attempt table.
        logger.error(json.dumps({'event': 'cart_order_payment_outcome_unknown',
                                 'alert': 'CART_PAYMENT_PREPARE_AMBIGUOUS',
                                 'sourceMessageId': basket.message_id,
                                 'phone_suffix': _phone_suffix(sender_phone),
                                 'requestId': request_id}))
        return

    if outcome != 'NATIVE_CART_PREPARED':
        # A definite not-prepared answer from checkout (e.g. NATIVE_CART_NOT_PREPARED: no
        # profile/address/verified customer, unpriceable cart, readiness blocked, send refused).
        # Clear the index so the customer's retry of the same cart is not swallowed as a replay.
        logger.warning(json.dumps({'event': 'cart_order_payment_not_prepared',
                                    'outcome': outcome,
                                    # A refusal CODE (e.g. DELIVERY_DETAILS_REQUIRED), never text.
                                    'reason': str(result.get('error') or result.get('status')
                                                  or '')[:64],
                                    'sourceMessageId': basket.message_id,
                                    'phone_suffix': _phone_suffix(sender_phone),
                                    'requestId': request_id}))
        _rollback_cart_order_index(keys, index['orderId'], token, request_id)
        kind = _cart_refusal_kind(outcome, str(result.get('error') or ''))
        if kind == 'address':
            from lambda_utils.ecommerce import contact_address
            if not contact_address.address_message_reaches(phone):
                # Meta sends the India Address Message to +91 numbers only, so asking this number
                # for an address would leave the customer with nothing. Nothing is kept waiting,
                # since no submission can arrive to resume it; the website takes the address and
                # the order instead.
                _reply_cart_refused('address_web', contact_id, phone_number_id, request_id)
                return
            # The one refusal the customer can fix in this chat: keep the cart, ask for the
            # address, and let the submission resume it (`_resume_pending_cart`).
            _remember_pending_cart(keys, basket, phone, contact_id, phone_number_id, now,
                                   request_id)
            _request_shipping_address(contact_id, phone_number_id, sender_phone, request_id)
        elif kind:
            _reply_cart_refused(kind, contact_id, phone_number_id, request_id)
        return

    # A cart that became a payment request supersedes any cart still waiting for an address, so a
    # later address submission can never resume an older basket.
    _forget_pending_cart(keys, contact_id, request_id)
    logger.info(json.dumps({
        'event': 'cart_order_payment_prepared',
        'outcome': outcome,
        'indexType': str(index.get('indexType') or ''),
        # `sourceMessageId` is a wamid: a correlation id, loggable in full. No phone, no price.
        'sourceMessageId': basket.message_id,
        'contactId': mask_contact_id(contact_id),
        'phone_suffix': _phone_suffix(sender_phone),
        'lineCount': len(basket.lines),
        'clampedLines': basket.clamped,
        'requestId': request_id,
    }))


def _cart_refusal_kind(outcome: str, error: str) -> str:
    """Which reply a DEFINITE not-prepared answer gets. '' means the customer is not messaged.

    Only the rollout gate stays silent: OFF means no customer-visible effect at all (see
    `_catalog_orders_enabled`). An ambiguous answer never reaches here - the request may already
    be on the customer's phone, and "we could not prepare it" would then be false.
    """
    if outcome == 'NATIVE_CART_ROLLOUT_DISABLED':
        return ''
    if outcome in ('VERIFIED_CUSTOMER_REQUIRED', 'WHATSAPP_IDENTITY_REQUIRED'):
        # Native WhatsApp payment never redirects to browser sign-in. Identity failures are
        # fail-closed and recoverable by retry/support; website authentication remains on HTTP
        # checkout routes only.
        return 'try_later'
    if error in ('DELIVERY_DETAILS_REQUIRED', 'DELIVERY_CONFIRMATION_REQUIRED'):
        return 'address'
    if outcome == 'NATIVE_CART_ALREADY_REQUESTED':
        return 'already_requested'
    if outcome == 'PAYMENT_SENDER_NOT_PERMITTED':
        return 'not_here'
    if error.startswith('SERVICE_'):
        return 'service'
    if outcome == 'NATIVE_CART_EMPTY' or error == 'AMOUNT_NOT_SETTLED':
        return 'items_unavailable'
    return 'try_later'


def _reply_cart_refused(kind: str, contact_id: str, phone_number_id: str, request_id: str) -> None:
    """Tell the customer why their cart produced no payment request. Never raises.

    Through outbound (`_send_cta_button` / `_send_ai_auto_reply`), so the inbox records the reply
    and the window, live-smoke and consent rules apply exactly as to any other send.
    """
    try:
        if kind == 'sign_in':
            _send_cta_button(contact_id, phone_number_id, 'Sign in', CART_SIGN_IN_URL, request_id,
                             body_text=CART_REPLY_SIGN_IN, footer_text='WECARE.DIGITAL')
        elif kind in ('service', 'service_alone', 'not_here', 'address_web'):
            _send_cta_button(contact_id, phone_number_id, 'Open shop', CART_SHOP_URL, request_id,
                             body_text={'service': CART_REPLY_SERVICE,
                                        'service_alone': CART_REPLY_SERVICE_ALONE,
                                        'address_web': CART_REPLY_ADDRESS_WEB}.get(
                                            kind, CART_REPLY_NOT_HERE),
                             footer_text='WECARE.DIGITAL')
        else:
            text = {'already_requested': CART_REPLY_ALREADY_REQUESTED,
                    'partial': CART_REPLY_PARTIAL,
                    'short_only': CART_REPLY_SHORT_ONLY,
                    'items_unavailable': CART_REPLY_ITEMS_UNAVAILABLE}.get(kind, CART_REPLY_TRY_LATER)
            _send_ai_auto_reply(contact_id, text, phone_number_id, request_id)
        logger.info(json.dumps({'event': 'cart_order_refusal_replied', 'kind': kind,
                                'contactId': mask_contact_id(contact_id),
                                'requestId': request_id}))
    except Exception as error:  # noqa: BLE001
        logger.warning(json.dumps({'event': 'cart_order_refusal_reply_failed', 'kind': kind,
                                   'error': type(error).__name__, 'requestId': request_id}))


def _remember_pending_cart(keys, basket, phone: str, contact_id: str, phone_number_id: str,
                           now: int, request_id: str) -> None:
    """Keep a cart refused only for its delivery address, so the address can resume it.

    No money, no price: the lines and quantities `whatsapp_basket` parsed, the E.164 the cart was
    sent from (the resume must come from the same number) and the receiving number. An
    unconditional put, so the latest such cart from this contact is the one that resumes.
    """
    if not contact_id or not basket.lines:
        return
    try:
        keys.put_item(Item={
            'orderId': CART_PENDING_PREFIX + contact_id,
            'token': whatsapp_basket.new_token(),
            'contactId': contact_id,
            'phone': phone,
            'phoneNumberId': phone_number_id,
            'lines': [dict(line) for line in basket.lines],
            'sourceMessageId': basket.message_id,
            'catalogId': basket.catalog_id,
            'createdAt': int(now),
            'expiresAt': int(now) + CART_PENDING_LIFETIME_SECONDS,
        })
    except Exception as error:  # noqa: BLE001 - the address is still requested without it
        logger.warning(json.dumps({'event': 'cart_pending_store_failed',
                                   'error': type(error).__name__, 'requestId': request_id}))


def _forget_pending_cart(keys, contact_id: str, request_id: str) -> None:
    """Drop this contact's waiting cart, if any. Best-effort."""
    if not contact_id:
        return
    try:
        keys.delete_item(Key={'orderId': CART_PENDING_PREFIX + contact_id})
    except Exception as error:  # noqa: BLE001
        logger.warning(json.dumps({'event': 'cart_pending_clear_failed',
                                   'error': type(error).__name__, 'requestId': request_id}))


def _pending_cart(contact_id: str) -> Dict[str, Any]:
    """This contact's unexpired waiting cart, or {}. Read consistently: it gates a payment."""
    if not contact_id:
        return {}
    row = dynamodb.Table(COMMERCE_KEYS_TABLE).get_item(
        Key={'orderId': CART_PENDING_PREFIX + contact_id}, ConsistentRead=True).get('Item') or {}
    if int(row.get('expiresAt') or 0) <= int(time.time()):
        return {}
    return row


def _resume_pending_cart(contact_id: str, sender_phone: str, phone_number_id: str,
                         request_id: str, *, recipient: str = '') -> bool:
    """Resume the cart that was waiting for this delivery address. True when one was resumed.

    The cart re-enters `_send_payment_request` exactly as the original message did - same lines,
    same wamid, so the same resolve-before-generate index (which that refusal rolled back) - and
    checkout re-checks everything: rollout gate, verified customer, the address just saved, price.
    The pending row is CLAIMED by a token-conditional delete first, so two submissions of the
    address resume one cart, never two.

    Only this path tells checkout the address is confirmed for the order (`delivery_confirmed`),
    because only this path runs on the customer's own submission of it. `recipient` is the name
    they typed on that form.
    """
    try:
        row = _pending_cart(contact_id)
    except Exception as error:  # noqa: BLE001
        logger.warning(json.dumps({'event': 'cart_pending_read_failed',
                                   'error': type(error).__name__, 'requestId': request_id}))
        return False
    if not row or not _catalog_orders_enabled():
        return False
    phone = whatsapp_basket.e164(sender_phone)
    # Same number, same business number, proven from this webhook - the rule `_handle_cart_order`
    # applies to the cart itself.
    receiving_meta_id = str(_send_context.get('phone_number_id') or '')
    if (not phone or row.get('phone') != phone
            or str(row.get('phoneNumberId') or '') != phone_number_id
            or META_PHONE_ID_MAP.get(receiving_meta_id) != phone_number_id):
        logger.warning(json.dumps({'event': 'cart_pending_resume_refused',
                                   'phone_suffix': _phone_suffix(sender_phone),
                                   'requestId': request_id}))
        return False
    keys = dynamodb.Table(COMMERCE_KEYS_TABLE)
    try:
        keys.delete_item(Key={'orderId': CART_PENDING_PREFIX + contact_id},
                         ConditionExpression='#t = :token',
                         ExpressionAttributeNames={'#t': 'token'},
                         ExpressionAttributeValues={':token': str(row.get('token') or '')})
    except ClientError as error:
        if error.response.get('Error', {}).get('Code') != 'ConditionalCheckFailedException':
            raise
        return False  # another submission resumed it first
    # DynamoDB hands numbers back as Decimal; checkout accepts integer quantities only.
    lines = []
    for line in row.get('lines') or []:
        if not isinstance(line, dict):
            continue
        product_id = str(line.get('productId') or '')
        variant_id = str(line.get('variantId') or '')
        quantity = int(line.get('quantity') or 0)
        if product_id and variant_id and quantity > 0:
            lines.append({'productId': product_id, 'variantId': variant_id, 'quantity': quantity})
    if not lines:
        return False
    basket = whatsapp_basket.Basket(lines=lines, catalog_id=str(row.get('catalogId') or ''),
                                    message_id=str(row.get('sourceMessageId') or ''))
    logger.info(json.dumps({'event': 'cart_order_resumed_after_address',
                            'sourceMessageId': basket.message_id, 'lineCount': len(lines),
                            'contactId': mask_contact_id(contact_id), 'requestId': request_id}))
    _send_payment_request(basket, phone, contact_id, sender_phone, phone_number_id, request_id,
                          delivery_confirmed=True, delivery_recipient=recipient)
    return True


# ============================================================================
# BOT FLOW CONFIGS (loaded from SystemConfigTable, dashboard-manageable)
# ============================================================================

# Default flow triggers config  -  keyword-to-flow mapping
# These drive TYPED keywords and are untouched by the menu wipe. Keywords MUST
# include the exact keyword plus natural variations. The former menus' row ids no
# longer dispatch here — a tapped row gets the menu placeholder — so the one-time
# "row title without emoji" entries are kept only because people type them.
DEFAULT_FLOW_TRIGGERS = {
    'customer_idea': {
        'keywords': sorted(CUSTOMER_IDEA_KEYWORDS),
        # Shares the published review flow with 'leave_review' (one Meta room, two doors).
        'flowId': canonical_flow_id('leave_review'),
        'entryMode': 'keyword_interactive',
        'message': {
            'body': '\u2b50 We’d value your feedback!',
            'footer': 'WECARE.DIGITAL',
            'flowCta': 'Leave Review',
        },
        # Historical alias only. The canonical F002 contract belongs to leave_review and
        # flow_launch.generic_keyword_refusal rejects this alias as a second launch door.
        'enabled': False,
    },
    'submit_request': {
        'keywords': [
            'submit request', 'sr', 'raise request', 'submit', 'request',
            'new request', 'start a new support request', 'support request',
            '\U0001f4cb submit request',
            # Row title in the one menu
            '\U0001f4cb new request',
        ],
        # Canonical: WD_Submit_Request_Paid_v1, DEPRECATED on Meta since 2026-10-25. It has no
        # PUBLISHED FlowRegistry row, so `flow_launch.meta_liveness` answers this door with the
        # website link instead of a Flow Meta would refuse. Phone 2 (WABA 2) cannot send WABA 1
        # flows — it uses the same CTA URL fallback.
        'flowId': canonical_flow_id('submit_request'),
        'entryMode': 'keyword_interactive',
        'message': {
            'body': '\U0001f4cb Start a new support request. Share the details and our team will follow up with you.',
            'footer': 'WECARE.DIGITAL',
            'flowCta': 'Submit Request',
        },
        'enabled': True,
    },
    'track_request': {
        'keywords': [
            'track request', 'track', 'status', 'where is my request', 'check status',
            'request status', 'track order', 'check the status',
            '\U0001f50d track request',
            # Row title in the one menu. Every row title must be typeable:
            # the menu invites the phrase, and these sets are exact-match with
            # no decoration stripping (deliberately — see strip_decorative_edges).
            'track a request', '\U0001f50d track a request',
        ],
        # No canonical Track Flow (not in keepIds); the former literal was an unused DRAFT
        # (02.WD_TR). Tracking is served by GET /wa-business/service/track/{orderId} + the
        # /orders/ page; canonical_flow_id('track_request') is None, so the keyword falls through
        # to the website CTA rather than opening a non-existent flow.
        'flowId': canonical_flow_id('track_request'),
        'entryMode': 'keyword_interactive',
        'message': {
            'body': '\U0001f50d Check the status of your request anytime. Enter your reference ID below.',
            'footer': 'WECARE.DIGITAL',
            'flowCta': 'Track Request',
        },
        'enabled': True,
    },
    'amend_request': {
        'keywords': [
            'amend request', 'amend', 'change request', 'modify request',
            'update request', 'edit request', 'correct request',
            'edit or correct', 'existing request',
            '\u270f\ufe0f amend request',
            # Row title in the one menu
            'change a request', '\u270f\ufe0f change a request',
        ],
        # No Flow: the former draft 03.WD_Amend_Request no longer exists on Meta, so
        # canonical_flow_id('amend_request') is None and this door answers with its website link.
        'flowId': canonical_flow_id('amend_request'),
        'entryMode': 'keyword_interactive',
        'message': {
            'body': '\u270f\ufe0f Need to make a change? Edit or correct your submitted request.',
            'footer': 'WECARE.DIGITAL',
            'flowCta': 'Amend Request',
        },
        'enabled': True,
    },
    'schedule_appointment': {
        'keywords': [
            'schedule appointment', 'appointment', 'book appointment', 'schedule',
            'meeting', 'book meeting', 'schedule meeting', 'consultation',
            'schedule a consultation', 'service visit',
            '\U0001f4c5 appointment',
            # "Visit" is the customer-facing word now (the one menu says
            # "Book a Visit"), but every `appointment` keyword above STAYS. They
            # are printed in already-delivered messages and in the Meta-side ice
            # breaker config; dropping one would silently stop answering a
            # message a customer was invited to send.
            'book a visit', 'book visit', 'visit', '\U0001f4c5 book a visit',
        ],
        'flowId': '26575380852083467',
        'entryMode': 'keyword_interactive',
        'message': {
            'body': '\U0001f4c5 Schedule a consultation or service visit at a time that works best for you.',
            'footer': 'WECARE.DIGITAL',
            'flowCta': 'Appointment',
        },
        'enabled': True,
    },
    'rx_slot': {
        'keywords': [
            'rx slot', 'rx', 'prescription', 'book rx', 'medicine', 'pharmacy',
            'chemist', 'book medical visit', 'medical visit', 'medical tourism',
            '\U0001fa7a rx slot',
            # Row title in the one menu
            'book an rx slot', 'book rx slot', '\U0001fa7a book an rx slot',
        ],
        'flowId': '895208030185211',
        'entryMode': 'keyword_interactive',
        'message': {
            'body': '\U0001fa7a Schedule a medical tourism or prescription-related visit.',
            'footer': 'WECARE.DIGITAL',
            'flowCta': 'RX Slot',
        },
        'enabled': True,
    },
    'drop_docs': {
        'keywords': [
            'drop docs', 'drop documents', 'upload docs', 'send docs', 'documents',
            'upload documents', 'share docs', 'supporting documents',
            '\U0001f4c4 drop docs',
            # Row title in the one menu
            'send documents', '\U0001f4c4 send documents',
        ],
        # No Flow: the former draft WD_Drop_Documents no longer exists on Meta, so
        # canonical_flow_id('drop_docs') is None and this door answers with its website link.
        'flowId': canonical_flow_id('drop_docs'),
        'entryMode': 'keyword_interactive',
        'message': {
            'body': '\U0001f4c4 Send supporting documents for your request.',
            'footer': 'WECARE.DIGITAL',
            'flowCta': 'Drop Docs',
        },
        'enabled': True,
    },
    'enterprise_assist': {
        'keywords': [
            'enterprise assist', 'enterprise', 'business assist', 'corporate',
            'b2b', 'enterprise help', 'enterprise support', 'business support',
            'bulk enquiries', 'bulk',
            '\U0001f3e2 enterprise assist',
            # Row title in the one menu
            'business enquiry', 'business enquiries', '\U0001f3e2 business enquiry',
        ],
        'flowId': '1707170524029465',
        'entryMode': 'keyword_interactive',
        'message': {
            'body': '\U0001f3e2 Corporate, B2B, and bulk enquiries. Tell us what you need.',
            'footer': 'WECARE.DIGITAL',
            'flowCta': 'Enterprise Assist',
        },
        'enabled': True,
    },
    'leave_review': {
        # KEYWORDS: this exact ordered list is the single source of truth and is
        # mirrored verbatim in four workspace surfaces (forms/selfservice.tsx,
        # engage/whatsapp/settings.tsx, engage/whatsapp/scripts.tsx and
        # dashboard/system-architecture.tsx) so the workspace SHOWS what the
        # backend answers. tests/test_leave_review_wiring.py asserts all five
        # agree as an ordered list, so a one-sided edit fails the build.
        'keywords': [
            'leave review', 'leave a review', 'review', 'reviews', 'feedback',
            'leave feedback', 'give feedback', 'share feedback', 'rate', 'rate us',
            'rate service', 'rating', 'ratings', 'testimonial', 'write a review',
            'give a review', 'share your experience', 'how was it',
            '\u2b50 leave review',
        ],
        # F002 resolves from canonical_flows to the currently published review Flow on WABA 1.
        # The historical `customer_idea` alias points at the same Meta asset but is not a second
        # launch authority. It is ENDPOINTLESS (no data_api_version, first
        # screen FEEDBACK carries no `data` block), so it MUST open with NAVIGATE —
        # see STATIC_ENTRY_SCREENS in _send_generic_flow. Opening it with
        # data_exchange fails at open. The id this replaced pointed at the
        # never-published WD_Feedback_v1 draft, which is why the keyword did nothing.
        'flowId': canonical_flow_id('leave_review'),
        'entryMode': 'keyword_interactive',
        'message': {
            'body': '\u2b50 Share your experience with our service.',
            'footer': 'WECARE.DIGITAL',
            'flowCta': 'Leave Review',
        },
        # F002 activation is separate from Meta publication. Workspace writes an explicit
        # SystemConfig override only after the canonical registry row is valid and deployed.
        'enabled': False,
    },
    'subscribe': {
        # F001 Subscribe: a customer-initiated native Flow inside the customer-service window.
        # A keyword opens it only when every control in lambda_utils.flow_launch agrees -
        # canonical record, FlowRegistry row, Meta status and this runtime switch - so the
        # switch defaults OFF and Workspace (Auto response -> Subscribe) turns it on. The Flow
        # id always comes from the canonical registry and the opening copy from
        # `subscribe_messages_config`, so no message is configured here.
        'keywords': list(canonical_contract('subscribe')['defaultKeywords']),
        'flowId': canonical_flow_id('subscribe'),
        'entryMode': 'keyword_interactive',
        'enabled': False,
    },
    'order_notes': {
        'keywords': ['order notes', 'order note', 'special instructions', 'delivery notes', 'order instructions'],
        'flowId': '1434731571172691',
        'entryMode': 'keyword_interactive',
        'message': {
            'body': '\U0001f4dd Add notes to your order \u2014 share any special instructions.',
            'footer': 'WECARE.DIGITAL',
            'flowCta': 'Order Notes',
        },
        'enabled': True,
    },
}


def _link_media_to_service_request(contact_id: str, s3_key: str, media_type: str,
                                   filename: str, mime: str, request_id: str) -> None:
    """If the contact has a recent OPEN service request, copy the media into the
    request's private upload folder under the media bucket and append
    it to the request's attachments list so the team can service it from the dashboard."""
    if not contact_id or not s3_key:
        return
    try:
        c = dynamodb.Table(CONTACTS_TABLE).get_item(Key={'id': contact_id}).get('Item') or {}
        from lambda_utils.flow_inbox import active_submission
        req = active_submission(c, int(time.time()))
        if not req:
            return
        base = s3_key.split('/')[-1]
        dest_key = media_paths.SERVICE_REQUEST_UPLOAD_PREFIX + f"{req}/{int(time.time())}-{base}"
        try:
            s3.copy_object(Bucket=MEDIA_BUCKET, CopySource={'Bucket': MEDIA_BUCKET, 'Key': s3_key}, Key=dest_key)
        except Exception:
            dest_key = s3_key  # fall back to the original key if copy fails
        attachment = {
            'key': dest_key,
            'private': True,
            'type': media_type,
            'filename': filename or base,
            'mime': mime or '',
            'ts': int(time.time()),
        }
        try:
            dynamodb.Table(FLOW_SUBMISSIONS_TABLE).update_item(
                Key={'submissionId': req},
                UpdateExpression='SET attachments = list_append(if_not_exists(attachments, :empty), :a), updatedAt = :u',
                ConditionExpression='contactId = :cid',
                ExpressionAttributeValues={':a': [attachment], ':empty': [], ':u': int(time.time()), ':cid': contact_id},
            )
            logger.info(json.dumps({'event': 'service_request_attachment_added', 'submissionId': req,
                                    'key': dest_key, 'requestId': request_id}))
        except Exception as e:
            logger.warning(json.dumps({'event': 'service_request_attachment_error', 'error': str(e),
                                       'requestId': request_id}))
    except Exception as e:
        logger.warning(json.dumps({'event': 'link_media_error', 'error': str(e), 'requestId': request_id}))


def _link_flow_submission_to_order(reference_id: str, submission_id: str,
                                   canonical_address: Optional[Dict], request_id: str) -> None:
    """Write the flow's info back onto the ONE OrderTable row it belongs to.

    THE JOIN, in the only direction that is safe. The flow echoes a `reference_id`
    (`WD-PAY-...`), not the canonical OrderTable `orderId` (`WD-ORD-...`), so this resolves the
    order through the immutable CommerceKeys chain the payment already wrote:
    `PAYREF#<ref>` -> paymentAttemptId -> `PAYMENTATTEMPT#<attempt>` -> orderIdRef. That chain is
    the one `paid_submit_request` and the webhook use, so no new index and no trust in a
    customer-supplied id. When the order does not exist yet (a pending/failed attempt resolves to
    None) this is a no-op, which is the correct answer, not an error.

    What it writes onto the order: the flow `submissionId` (so the Order<->FlowSubmission join
    exists in BOTH directions — the submission already carries the reference), and the delivery
    address the flow collected (the canonical `checkoutDeliveryAddress` Map + the declared
    `shippingAddress` string column the schema already has). It NEVER touches the five money /
    identity keys the finalization conflict guard compares (`customerId`, `paymentAttemptId`,
    `providerPaymentId`, `snapshotHash`, `orderNumber`) — this is attribution and fulfilment data
    added beside the frozen record, conditional on the order existing so a race cannot create one.
    """
    if not reference_id:
        return
    try:
        keys = dynamodb.Table(COMMERCE_KEYS_TABLE)
        payref = order_keys.resolve_payment_reference(keys, reference_id)
        attempt_id = str((payref or {}).get('paymentAttemptId') or '')
        claim = order_keys.resolve_order_for_payment(keys, attempt_id) if attempt_id else None
        order_id = str((claim or {}).get('orderIdRef') or '')
        if not order_id:
            # No order yet (pending/failed/legacy reference). The submission still stands on its
            # own; there is simply nothing to link to.
            return
        now = int(time.time())
        expr_names = {}
        expr_vals = {':sid': submission_id, ':ua': now}
        set_parts = ['flowSubmissionId=:sid', 'updatedAt=:ua']
        if canonical_address is not None:
            from lambda_utils.ecommerce import contact_address
            wf = contact_address.contact_write_fields(canonical_address, now=now)
            # `shippingAddress` is the declared OrderTable column; `checkoutDeliveryAddress` is the
            # same canonical Map the contact carries, so an order and its contact describe one
            # address, not two that can drift.
            expr_names['#cda'] = contact_address.ATTRIBUTE
            set_parts += ['shippingAddress=:sa', '#cda=:cda']
            expr_vals.update({':sa': wf['shippingAddress'],
                              ':cda': wf[contact_address.ATTRIBUTE]})
        kwargs = {
            'Key': {'orderId': order_id},
            'UpdateExpression': 'SET ' + ', '.join(set_parts),
            # Only an existing order is updated — never create one here. Finalization owns order
            # creation; this adds fulfilment data to a row that already committed.
            'ConditionExpression': 'attribute_exists(orderId)',
            'ExpressionAttributeValues': expr_vals,
        }
        if expr_names:
            kwargs['ExpressionAttributeNames'] = expr_names
        dynamodb.Table(shared_tables.orders_table_name()).update_item(**kwargs)
        logger.info(json.dumps({'event': 'flow_submission_linked_to_order', 'orderId': order_id,
                                'submissionId': submission_id, 'requestId': request_id}))
    except Exception as link_error:  # noqa: BLE001
        # The submission and the contact are already saved; failing to decorate the order must not
        # fail the whole post-pay handling or send the customer a second confirmation. Logged for
        # staff, swallowed here — the order record is still authoritative without this label.
        logger.warning(json.dumps({'event': 'flow_order_link_failed', 'referenceId': reference_id,
                                    'error': str(link_error)[:300], 'requestId': request_id}))


def _handle_postpay_submission(data: Dict, contact_id: str, sender_phone: str,
                               phone_number_id: str, request_id: str) -> None:
    """Handle a post-payment (endpointless) flow completion. The flow's 'complete'
    action returns reference_id + order/payment ids + the customer's details.
    Saves ONE submission per payment (idempotent, keyed on reference_id), links that
    submission and its address back onto the matching OrderTable row, and sends a
    confirmation message."""
    try:
        # New multi-screen flow uses request_id + order_number (+ full address/details).
        # Stay backward-compatible with the old payload (reference_id/delivery_note).
        request_sr_id = str(data.get('request_id', '')).strip()
        reference_id = str(data.get('reference_id') or data.get('order_number') or '').strip()
        if not request_sr_id and not reference_id:
            return
        now = int(time.time())
        # Key on the unique Request ID (falls back to reference for old payloads).
        sub_id = request_sr_id or f'postpay-{reference_id}'
        from lambda_utils.ecommerce import contact_address
        # ONE address shape: validate the flow's address fields through `contact_address` so the
        # contact back-write below stores the canonical Map, not a parallel flat row. `canonical`
        # is None when the flow carried no usable address (a service with no delivery) — the
        # submission row is still saved, only the contact address back-write is skipped.
        try:
            canonical = contact_address.normalize_for_storage(
                contact_address.map_meta_address(data))
        except contact_address.UnusableAddress:
            canonical = None
        # The human one-liner for the submission record. From the canonical Map when we have one,
        # else composed from the raw flow fields so an address-less service still reads sensibly.
        if canonical is not None:
            address_str = str(canonical.get('fullAddress') or '')
        else:
            addr_parts = [data.get('address', ''), data.get('landmark', ''), data.get('city', ''),
                          data.get('state', ''), data.get('pin', '')]
            address_str = ', '.join(str(p).strip() for p in addr_parts if str(p).strip())
        form = {k: v for k, v in data.items() if k not in ('flow_token',)}
        # Through the ONE FlowSubmissionTable writer. The explicit id keeps one row per request
        # (or per payment for the old payload), and the id doubles as the persisted token, so no
        # live Flow token is written. `formData` rides in `extra`, serialised as before, rather
        # than as `form_data`, so the promoted orderId stays the referenceId and is never a
        # payload field. Default ttl is the 365 days this row always had.
        from lambda_utils import flow_completion
        result = flow_completion.claim_completion(
            flow_token=sub_id, screen='DETAILS', flow_code='03.WD_POSTPAY_REQUEST',
            flow_type='service_request', phone=sender_phone, contact_id=contact_id or '',
            submission_id=sub_id, status='open', request_id=request_id,
            channel=flow_completion.CHANNEL_WHATSAPP,
            extra={
                'formData': json.dumps(form),
                'requestId': request_sr_id,
                'orderId': reference_id,
                'referenceId': reference_id,
                'orderNumber': str(data.get('order_number', '')),
                'product': str(data.get('product', '')),
                'amount': str(data.get('amount', '')),
                'customerName': str(data.get('name', '')),
                'shippingAddress': address_str,
                'addressLine1': str(data.get('address', '')),
                'city': str(data.get('city', '')),
                'state': str(data.get('state', '')),
                'postalCode': str(data.get('pin', '')),
                'landmark': str(data.get('landmark', '')),
                'description': str(data.get('description', '')),
                'deliveryNote': str(data.get('delivery_note', '')),
                'preferredTime': str(data.get('preferred_time', '')),
                'paymentStatus': 'paid',
            })
        if result.duplicate:
            logger.info(json.dumps({'event': 'postpay_submission_duplicate', 'submissionId': sub_id,
                                    'requestId': request_id}))
            return  # already recorded — do not send a second confirmation
        if not result.created:
            raise RuntimeError('post-payment request could not be saved')
        logger.info(json.dumps({'event': 'postpay_submission_saved', 'submissionId': sub_id,
                                'requestId2': request_sr_id, 'referenceId': reference_id,
                                'requestId': request_id}))
        # Link this submission + its address back onto the ONE OrderTable row (resolved through
        # the immutable PAYREF chain). After the idempotent put above, so a redelivered flow does
        # not re-link; before the contact write so the order and contact get one consistent
        # address in the same handling.
        _link_flow_submission_to_order(reference_id, sub_id, canonical, request_id)
        # Update the customer's saved address from the flow so future orders pre-fill.
        try:
            if contact_id:
                # Tag the contact with the open request so any media they send next
                # gets attached to THIS request. Also save the address for reuse.
                _uexpr = 'SET openServiceRequestId=:rid, openServiceRequestAt=:ua, updatedAt=:ua'
                _names = {}
                _vals = {':rid': sub_id, ':ua': now}
                if canonical is not None:
                    # Canonical Map + flat columns from the SAME normalised address, matching
                    # `_handle_address_submission` so the Address-Message path and the post-pay flow
                    # path leave an identical shape on the contact.
                    wf = contact_address.contact_write_fields(canonical, now=now)
                    _uexpr += (', shippingAddress=:sa, addressLine1=:al, addressLine2=:a2, city=:cy, '
                               '#st=:st, postalCode=:pc, landmark=:lm, #co=:co, #cda=:cda, #cau=:cau')
                    _names.update({'#st': 'state', '#co': 'country',
                                   '#cda': contact_address.ATTRIBUTE,
                                   '#cau': contact_address.UPDATED_ATTRIBUTE})
                    _vals.update({':sa': wf['shippingAddress'], ':al': wf['addressLine1'],
                                  ':a2': wf['addressLine2'], ':cy': wf['city'], ':st': wf['state'],
                                  ':pc': wf['postalCode'], ':lm': wf['landmark'], ':co': wf['country'],
                                  ':cda': wf[contact_address.ATTRIBUTE],
                                  ':cau': wf[contact_address.UPDATED_ATTRIBUTE]})
                _kwargs = {'Key': {'id': contact_id}, 'UpdateExpression': _uexpr,
                           'ExpressionAttributeValues': _vals}
                if _names:
                    _kwargs['ExpressionAttributeNames'] = _names
                dynamodb.Table(CONTACTS_TABLE).update_item(**_kwargs)
        except Exception:
            pass
        # Confirmation message showing the Request ID.
        try:
            rid = request_sr_id or sub_id
            msg = (f'\u2705 *Request confirmed*\n\nRequest ID: *{rid}*\n'
                   'Our team will process it within 24-48 hours. You can send any photos '
                   'or documents here and we\u2019ll attach them to your request.\n\n'
                   '_Thank you for choosing WECARE.DIGITAL_')
            meta_pid = _get_meta_phone_id_for_direct_api(phone_number_id)
            _send_direct_api_message(sender_phone, {'type': 'text', 'text': {'body': msg}}, meta_pid)
        except Exception:
            pass
    except Exception as e:
        logger.error(json.dumps({'event': 'postpay_submission_error', 'error': str(e), 'requestId': request_id}))


def _handle_address_submission(nfm: Dict, contact_id: str, sender_phone: str,
                               phone_number_id: str, request_id: str) -> None:
    """Handle a native India Address Message submission (nfm_reply,
    name='address_message'). Parses response_json and saves the structured
    shipping address to the contact so checkout / order_details can reuse it."""
    try:
        from lambda_utils.ecommerce import contact_address
        raw = nfm.get('response_json', '{}')
        data = json.loads(raw) if isinstance(raw, str) else (raw or {})
        vals = data.get('values', data) or {}
        name = vals.get('name', '')
        # ONE address shape: fold Meta's Address-Message fields into the canonical `_RULES` keys and
        # validate through `contact_address`, exactly as `customer_orders.update_profile` does. A
        # structurally-bad address (missing a required field) is skipped rather than written as a
        # half row — the customer can resubmit, and no divergent flat-only row is left behind.
        try:
            address = contact_address.normalize_for_storage(
                contact_address.map_meta_address(vals))
        except contact_address.UnusableAddress as bad:
            logger.info(json.dumps({
                'event': 'address_submission_unusable', 'code': bad.code, 'field': bad.field,
                'phone_suffix': sender_phone[-4:] if sender_phone else '', 'requestId': request_id}))
            # A cart is waiting on this address: ask again rather than leave the customer with
            # silence. Without a waiting cart nothing depends on it, and nothing is sent.
            try:
                waiting = bool(_pending_cart(contact_id))
            except Exception:  # noqa: BLE001
                waiting = False
            if waiting:
                _request_shipping_address(contact_id, phone_number_id, sender_phone, request_id,
                                          body_text=CART_REPLY_ADDRESS_UNUSABLE,
                                          submitted=vals, bad_field=bad.field)
            return
        # A cart is waiting on this address, so it must be one a WhatsApp payment can SETTLE, not
        # just one storage accepts (India: a six-digit PIN and a state that maps to a GST state).
        # Asked HERE, before it is saved: an unpayable address used to be saved, the resumed cart
        # was refused for it again, and the customer was asked for "your delivery address" a
        # second time with no hint of what was wrong. Without a waiting cart, storage stays
        # international (FEAT-003) and the address is kept as before.
        try:
            waiting = bool(_pending_cart(contact_id))
        except Exception:  # noqa: BLE001 - the resume re-checks everything anyway
            waiting = False
        if waiting:
            from lambda_utils.ecommerce import payment_address
            try:
                payment_address.assert_payable(
                    address, channel=payment_address.WHATSAPP_ORDER_DETAILS)
            except payment_address.UnpayableAddress as unpayable:
                logger.info(json.dumps({
                    'event': 'address_submission_unpayable', 'code': unpayable.code,
                    'field': unpayable.field,
                    'phone_suffix': sender_phone[-4:] if sender_phone else '',
                    'requestId': request_id}))
                _request_shipping_address(contact_id, phone_number_id, sender_phone, request_id,
                                          body_text=CART_REPLY_ADDRESS_UNUSABLE,
                                          submitted=vals, bad_field=unpayable.field)
                return
        logger.info(json.dumps({
            'event': 'address_submission', 'phone_suffix': sender_phone[-4:] if sender_phone else '',
            'savedAddressId': data.get('saved_address_id', ''),
            # The PIN's region digits only; a full PIN plus a city narrows to a street.
            'pinPrefix': str(address.get('postalCode', ''))[:3],
            'requestId': request_id,
        }))
        if not contact_id:
            return
        ct = dynamodb.Table(CONTACTS_TABLE)
        now = int(time.time())
        # The canonical Map + its timestamp + the legacy flat columns, all projected from the ONE
        # normalised address so they cannot drift. `contact_write_fields` owns that projection.
        write_fields = contact_address.contact_write_fields(address, now=now)
        expr_names = {'#st': 'state', '#co': 'country', '#cda': contact_address.ATTRIBUTE,
                      '#cau': contact_address.UPDATED_ATTRIBUTE}
        expr_vals = {
            ':sa': write_fields['shippingAddress'], ':al': write_fields['addressLine1'],
            ':a2': write_fields['addressLine2'], ':lm': write_fields['landmark'],
            ':cy': write_fields['city'], ':st': write_fields['state'],
            ':pc': write_fields['postalCode'], ':co': write_fields['country'],
            ':cda': write_fields[contact_address.ATTRIBUTE],
            ':cau': write_fields[contact_address.UPDATED_ATTRIBUTE], ':ua': now,
        }
        update_expr = ('SET shippingAddress=:sa, addressLine1=:al, addressLine2=:a2, landmark=:lm, '
                       'city=:cy, #st=:st, postalCode=:pc, #co=:co, #cda=:cda, #cau=:cau, '
                       'updatedAt=:ua')
        if name:
            update_expr += ', contactBookName=:nm'
            expr_vals[':nm'] = name
        ct.update_item(Key={'id': contact_id}, UpdateExpression=update_expr,
                       ExpressionAttributeNames=expr_names, ExpressionAttributeValues=expr_vals)
        logger.info(json.dumps({'event': 'address_saved', 'contactId': mask_contact_id(contact_id), 'requestId': request_id}))
        # The cart that was refused for want of this address continues now, so the customer
        # does not have to send it again. The name on the form is who this order ships to.
        _resume_pending_cart(contact_id, sender_phone, phone_number_id, request_id,
                             recipient=name if isinstance(name, str) else '')
    except Exception as e:
        logger.error(json.dumps({'event': 'address_submission_error', 'error': type(e).__name__, 'requestId': request_id}))


def _get_flow_triggers_config() -> Dict:
    """Load flow triggers config from SystemConfigTable (id: 'flow_triggers_config')."""
    try:
        config_table = dynamodb.Table(SYSTEM_CONFIG_TABLE)
        response = config_table.get_item(Key={'id': 'flow_triggers_config'})
        if 'Item' in response:
            config_value = response['Item'].get('configValue', '{}')
            config = json.loads(config_value) if isinstance(config_value, str) else config_value
            # Merge with defaults  -  config overrides per flow key
            merged = {}
            for key, default in DEFAULT_FLOW_TRIGGERS.items():
                if key in config:
                    entry = default.copy()
                    entry.update(config[key])
                    if 'message' in config[key]:
                        entry['message'] = {**default.get('message', {}), **config[key]['message']}
                    merged[key] = entry
                else:
                    merged[key] = default.copy()
            # Also include any new flows defined in config but not in defaults
            for key, val in config.items():
                if key not in merged:
                    merged[key] = val
            return merged
        return {k: v.copy() for k, v in DEFAULT_FLOW_TRIGGERS.items()}
    except Exception:
        return {k: v.copy() for k, v in DEFAULT_FLOW_TRIGGERS.items()}


def _send_read_receipt(whatsapp_message_id: str, phone_number_id: str, request_id: str) -> None:
    """
    Send read receipt to WhatsApp per AWS docs.
    Per AWS: send-whatsapp-message with status='read' shows two blue check marks.
    """
    if not whatsapp_message_id:
        return
    
    try:
        # Build read receipt payload per Meta WhatsApp API
        read_receipt_payload = {
            'messaging_product': 'whatsapp',
            'message_id': whatsapp_message_id,
            'status': 'read'
        }
        
        logger.info(json.dumps({
            'event': 'read_receipt_payload',
            'messageId': whatsapp_message_id,
            'status': 'read',
            'requestId': request_id
        }))
        
        # Send read receipt via Direct API
        if _is_direct_api_phone(phone_number_id):
            meta_pid = _get_meta_phone_id_for_direct_api(phone_number_id)
            _rr = _send_direct_api_read_receipt(whatsapp_message_id, meta_phone_id=meta_pid)
        else:
            # Fallback: try Direct API with default phone
            _rr = _send_direct_api_read_receipt(whatsapp_message_id)

        # The callee returns a dict rather than raising, so `read_receipt_sent` used
        # to be emitted even when Meta refused the receipt.
        if _rr.get('error'):
            logger.warning(json.dumps({
                'event': 'read_receipt_failed',
                'messageId': whatsapp_message_id,
                'phoneNumberId': phone_number_id,
                'status': _rr.get('status'),
                'graphError': _graph_error_code(_rr.get('detail')),
                'requestId': request_id
            }))
        else:
            logger.info(json.dumps({
                'event': 'read_receipt_sent',
                'messageId': whatsapp_message_id,
                'phoneNumberId': phone_number_id,
                'statusCode': 200,
                'requestId': request_id
            }))
        
    except Exception as e:
        logger.warning(json.dumps({
            'event': 'read_receipt_error',
            'messageId': whatsapp_message_id,
            'error': str(e),
            'requestId': request_id
        }))


# ============================================================================
# AI AUTOMATION INTEGRATION
# ============================================================================

# Default AI configuration
DEFAULT_AI_CONFIG = {
    'enabled': False,
    'autoReplyEnabled': False,
    'respondToInteractive': True,
    'respondToText': True,
    'respondToMedia': True,  # Now enabled  -  multimodal AI via Converse API
    'respondToLocation': True,
    'maxResponseLength': 500,
    'responseDelay': 0,
    'supportedLanguages': ['en', 'hi', 'hi-Latn', 'bn', 'ta', 'te', 'gu', 'mr'],
    'defaultLanguage': 'en',
    # No agent, alias or knowledge-base id. Re-measured 2026-09-23: the account's
    # only Bedrock Agent is an empty never-prepared shell (no model, 0-character
    # instruction, null role, 0 action groups) and the account holds 0 knowledge
    # bases. The values previously here - '4UUQYFWX64' / 'TSTALIASID' /
    # 'static-faq' - named nothing, and this config is returned by an API and
    # rendered in the dashboard, so they read as working configuration.
    # Empty means not configured, which is the truth. See plan item 6.4.
    'agentId': '',
    'agentAlias': '',
    'knowledgeBaseId': '',
    'modelId': 'amazon.nova-pro-v1:0',
}


def _get_ai_config() -> Dict[str, Any]:
    """
    Get AI configuration from SystemConfig table.
    Returns default config if not found or on error.
    """
    try:
        config_table = dynamodb.Table(SYSTEM_CONFIG_TABLE)
        # SystemConfigTable PK is 'id', we use id=configKey for compatibility
        response = config_table.get_item(Key={'id': 'ai_config'})
        
        if 'Item' in response:
            config_value = response['Item'].get('configValue', '{}')
            config = json.loads(config_value) if isinstance(config_value, str) else config_value
            # Merge with defaults to ensure all keys exist
            merged = DEFAULT_AI_CONFIG.copy()
            merged.update(config)
            return merged
        
        return DEFAULT_AI_CONFIG.copy()
    except Exception as e:
        logger.warning(f"Failed to get AI config: {str(e)}")
        return DEFAULT_AI_CONFIG.copy()


def _is_ai_enabled() -> bool:
    """
    Check if AI automation is enabled in SystemConfig.
    Returns False — AI auto-reply permanently removed.
    """
    return False


def _process_ai_automation(message_id: str, contact_id: str, content: str, message_type: str, phone_number_id: str, sender_phone: str, s3_key: str, mime_type: str, request_id: str, sender_bsuid: str = '') -> Optional[Dict]:
    """
    WhatsApp AI auto-reply — PERMANENTLY REMOVED.
    This function is kept as a no-op stub so callers don't break.
    """
    return None


def _invoke_ai_query_kb(query: str, message_id: str, request_id: str) -> Optional[Dict]:
    """Invoke ai-query-kb Lambda function."""
    try:
        logger.info(json.dumps({
            'event': 'invoking_ai_query_kb',
            'functionName': AI_QUERY_KB_FUNCTION,
            'messageId': message_id,
            'requestId': request_id
        }))
        response = lambda_client.invoke(
            FunctionName=AI_QUERY_KB_FUNCTION,
            InvocationType='RequestResponse',
            Payload=json.dumps({'query': query, 'messageId': message_id, 'requestId': request_id})
        )
        status_code = response.get('StatusCode')
        logger.info(json.dumps({
            'event': 'ai_query_kb_response',
            'statusCode': status_code,
            'messageId': message_id,
            'requestId': request_id
        }))
        if status_code == 200:
            payload = response['Payload'].read().decode('utf-8')
            return json.loads(json.loads(payload).get('body', '{}'))
        return None
    except Exception as e:
        logger.error(json.dumps({
            'event': 'ai_query_kb_error',
            'error': str(e),
            'messageId': message_id,
            'requestId': request_id
        }))
        return None


def _invoke_ai_generate_response(content: str, kb_context: Optional[Dict], 
                                  message_id: str, contact_id: str, request_id: str) -> Optional[Dict]:
    """Invoke ai-generate-response Lambda function (legacy, used for internal)."""
    try:
        response = lambda_client.invoke(
            FunctionName=AI_GENERATE_RESPONSE_FUNCTION,
            InvocationType='RequestResponse',
            Payload=json.dumps({
                'messageContent': content,
                'kbContext': kb_context,
                'messageId': message_id,
                'contactId': contact_id,
                'requestId': request_id
            })
        )
        if response.get('StatusCode') == 200:
            body = json.loads(json.loads(response['Payload'].read().decode('utf-8')).get('body', '{}'))
            _store_ai_interaction(message_id, content, body.get('suggestion', '') or body.get('suggestedResponse', ''), request_id)
            return body
        return None
    except Exception:
        return None


def _invoke_ai_generate_response_v2(
    content: str, message_id: str, contact_id: str, sender_phone: str,
    message_type: str, s3_key: str, mime_type: str, request_id: str,
    phone_number_id: str = '',
) -> Optional[Dict]:
    """
    Invoke ai-generate-response Lambda with multimodal payload.
    Passes sender phone, message type, S3 key, and mime type for
    the Converse API path to handle images, audio, video, documents.
    Passes phoneNumberId so AI sessions are separated per WABA.
    """
    try:
        payload = {
            'messageContent': content,
            'messageId': message_id,
            'contactId': contact_id,
            'senderPhone': sender_phone,
            'context': 'external',
            'messageType': message_type,
            's3Key': s3_key,
            'mediaType': message_type if message_type in ('image', 'audio', 'video', 'document') else '',
            'mimeType': mime_type,
            'requestId': request_id,
            'phoneNumberId': phone_number_id,
        }

        logger.info(json.dumps({
            'event': 'ai_generate_v2_invoke',
            'messageType': message_type,
            'hasMedia': bool(s3_key),
            'messageId': message_id,
            'requestId': request_id
        }))

        # Use a shorter boto3 read timeout for AI invocation to prevent
        # this Lambda from timing out waiting for the AI Lambda.
        # Default boto3 read_timeout is 60s; we cap at 45s here.
        import botocore.config
        _ai_lambda_config = botocore.config.Config(read_timeout=45, retries={'max_attempts': 0})
        _ai_lambda_client = boto3.client('lambda', region_name=os.environ.get('AWS_REGION', 'us-east-1'), config=_ai_lambda_config)
        
        response = _ai_lambda_client.invoke(
            FunctionName=AI_GENERATE_RESPONSE_FUNCTION,
            InvocationType='RequestResponse',
            Payload=json.dumps(payload)
        )

        if response.get('StatusCode') == 200:
            raw = response['Payload'].read().decode('utf-8')
            parsed = json.loads(raw)
            body = json.loads(parsed.get('body', '{}'))

            # Store AI interaction for audit
            suggestion = body.get('suggestion', '') or body.get('suggestedResponse', '')
            if suggestion and not body.get('locked'):
                _store_ai_interaction(message_id, content or f'[{message_type}]', suggestion, request_id)

            return body
        return None
    except Exception as e:
        logger.error(json.dumps({
            'event': 'ai_generate_v2_error',
            'error': str(e),
            'messageId': message_id,
            'requestId': request_id
        }))
        return None


def _send_typing_indicator(sender_phone: str, phone_number_id: str, request_id: str) -> None:
    """
    Send WhatsApp typing indicator so the customer sees engagement while AI processes.
    
    Meta Graph API does not expose a native typing indicator endpoint.
    We send a read receipt (blue ticks) as the closest proxy  -  this signals
    to the customer that their message was seen and a response is coming.
    """
    if not sender_phone or not phone_number_id:
        return

    # Use Direct API read receipt as typing proxy
    if _is_direct_api_phone(phone_number_id):
        try:
            # For Direct API phones, we already sent read receipt in the auto-reaction block.
            # Send another read receipt as typing proxy if we have a message ID.
            logger.info(json.dumps({
                'event': 'typing_indicator_direct_api',
                'senderPhone': mask_phone(sender_phone),
                'phoneNumberId': phone_number_id,
                'note': 'Using read receipt as typing proxy for Direct API phone',
                'requestId': request_id
            }))
        except Exception as e:
            logger.warning(f"Direct API typing indicator failed: {e}")
        return

    try:
        # Clean phone number  -  ensure + prefix for WhatsApp recipient
        clean_phone = sender_phone.lstrip('+')
        formatted_phone = f'+{clean_phone}'

        # Send read receipt as typing proxy
        read_payload = {
            'messaging_product': 'whatsapp',
            'status': 'read',
            'recipient_type': 'individual',
            'to': formatted_phone,
        }

        if _is_direct_api_phone(phone_number_id):
            meta_pid = _get_meta_phone_id_for_direct_api(phone_number_id)
            _rr = _send_direct_api_read_receipt(whatsapp_message_id if 'whatsapp_message_id' in dir() else '', meta_phone_id=meta_pid)
        else:
            # Fallback: try Direct API with default phone
            _rr = _send_direct_api_read_receipt('', meta_phone_id=_current_direct_api_phone or PHONE1_META_ID)

        # The callee returns a dict rather than raising, so `typing_indicator_sent`
        # used to be emitted even when Meta refused the receipt.
        if _rr.get('error'):
            logger.warning(json.dumps({
                'event': 'typing_indicator_failed',
                'senderPhone': mask_phone(sender_phone),
                'phoneNumberId': phone_number_id,
                'status': _rr.get('status'),
                'graphError': _graph_error_code(_rr.get('detail')),
                'requestId': request_id
            }))
        else:
            logger.info(json.dumps({
                'event': 'typing_indicator_sent',
                'senderPhone': mask_phone(sender_phone),
                'phoneNumberId': phone_number_id,
                'note': 'Sent read receipt as typing proxy',
                'requestId': request_id
            }))

    except Exception as e:
        # Non-critical  -  don't fail the AI flow for typing indicator
        logger.warning(json.dumps({
            'event': 'typing_indicator_error',
            'error': str(e),
            'requestId': request_id
        }))


def _store_ai_interaction(message_id: str, query: str, response: str, request_id: str) -> None:
    """Store AI interaction record."""
    try:
        ai_table = dynamodb.Table(AI_INTERACTIONS_TABLE)
        ai_table.put_item(Item={
            'id': str(uuid.uuid4()),
            'interactionId': str(uuid.uuid4()),
            'messageId': message_id,
            'query': query,
            'response': response,
            'approved': False,
            'timestamp': Decimal(str(int(time.time()))),
        })
    except Exception as e:
        logger.error(f"Failed to store AI interaction: {str(e)}")


# ============================================================================
# WHATSAPP BUSINESS ACCOUNT WEBHOOKS
# Template Status, Phone Quality, Messaging Limits
# ============================================================================

def _process_template_status(value: Dict, request_id: str) -> None:
    """
    Process template status update webhook.
    
    Webhook format:
    {
        "event": "APPROVED" | "REJECTED" | "PENDING" | "PAUSED" | "DISABLED" | "FLAGGED",
        "message_template_id": 123456789,
        "message_template_name": "template_name",
        "message_template_language": "en_US",
        "reason": "NONE" | "ABUSIVE_CONTENT" | "INVALID_FORMAT" | ...
    }
    
    Events:
    - APPROVED: Template approved and ready to use
    - REJECTED: Template rejected (check reason)
    - PENDING: Template submitted for review
    - PAUSED: Template paused due to quality issues
    - DISABLED: Template disabled
    - FLAGGED: Template flagged for review
    """
    event = value.get('event', '')
    template_id = value.get('message_template_id', '')
    template_name = value.get('message_template_name', '')
    template_language = value.get('message_template_language', '')
    reason = value.get('reason', 'NONE')
    
    logger.info(json.dumps({
        'event': 'template_status_update',
        'templateEvent': event,
        'templateId': template_id,
        'templateName': template_name,
        'templateLanguage': template_language,
        'reason': reason,
        'requestId': request_id
    }))
    
    # Store template status in SystemConfig table for dashboard display
    _store_system_event(
        event_type='template_status',
        event_data={
            'event': event,
            'templateId': str(template_id),
            'templateName': template_name,
            'templateLanguage': template_language,
            'reason': reason
        },
        request_id=request_id
    )
    
    # A template that cannot be sent. `template_status_alert` drives the
    # `wecare-whatsapp-template-status-alert` CloudWatch alarm
    # (scripts/provision_template_flow_alarms.py); `registered` says whether automation (payment,
    # invoice, order status, OTP, Vault) sends it, which is what makes a PAUSED one urgent.
    if event in ['REJECTED', 'PAUSED', 'DISABLED', 'FLAGGED']:
        logger.warning(json.dumps({
            'event': 'template_status_alert',
            'templateEvent': event,
            'templateId': str(template_id),
            'templateName': template_name,
            'registered': whatsapp_templates.by_name(template_name) is not None,
            'reason': reason,
            'action': 'Review template in Meta Business Manager',
            'requestId': request_id
        }))


#: Flow states a customer cannot open. BLOCKED/THROTTLED always need a person; DEPRECATED only
#: when the runtime still names the Flow (a planned retirement is not an incident).
_FLOW_ALERT_STATUSES = frozenset({'BLOCKED', 'THROTTLED'})
#: Health events Meta sends with alert_state ACTIVATED on a breach and DEACTIVATED on recovery.
_FLOW_HEALTH_EVENTS = frozenset({'CLIENT_ERROR_RATE', 'ENDPOINT_ERROR_RATE', 'ENDPOINT_LATENCY',
                                 'ENDPOINT_AVAILABILITY'})


def _process_flow_event(value: Dict, request_id: str) -> None:
    """Record one `flows` webhook and raise `flow_status_alert` when it stops customers.

    Meta sends FLOW_STATUS_CHANGE (DRAFT/PUBLISHED/DEPRECATED/BLOCKED/THROTTLED, sometimes with a
    version-freeze `warning`), the four endpoint/client health events and
    FLOW_VERSION_EXPIRY_WARNING. Every one is stored in the `flows` ring buffer the Workspace event
    view reads (waba-management GET /waba/events). The alert drives the
    `wecare-whatsapp-flow-status-alert` alarm. The payload names a Flow and its metrics only;
    nothing in it identifies a customer.
    """
    event = str(value.get('event') or '')
    flow_id = str(value.get('flow_id') or '')
    new_status = str(value.get('new_status') or '')
    alert_state = str(value.get('alert_state') or '')
    data = {key: value.get(key) for key in (
        'event', 'flow_id', 'old_status', 'new_status', 'alert_state', 'threshold', 'error_rate',
        'p50_latency', 'p90_latency', 'availability', 'requests_count')
        if value.get(key) not in (None, '')}
    errors = value.get('errors')
    if isinstance(errors, list):
        data['errors'] = [{k: e.get(k) for k in ('error_type', 'error_rate', 'error_count')}
                          for e in errors[:10] if isinstance(e, dict)]
    if value.get('warning'):
        data['warning'] = str(value.get('warning'))[:300]
    in_use = published_flow_by_id(flow_id) is not None

    logger.info(json.dumps({'event': 'flow_webhook', 'flowEvent': event, 'flowId': flow_id,
                            'newStatus': new_status, 'alertState': alert_state,
                            'inUse': in_use, 'requestId': request_id}))
    _store_system_event(event_type='flows', event_data=data, request_id=request_id)

    alert = ((event == 'FLOW_STATUS_CHANGE'
              and (new_status in _FLOW_ALERT_STATUSES or (new_status == 'DEPRECATED' and in_use)))
             or (event in _FLOW_HEALTH_EVENTS and alert_state == 'ACTIVATED')
             or event == 'FLOW_VERSION_EXPIRY_WARNING' or bool(value.get('warning')))
    if alert:
        logger.warning(json.dumps({
            'event': 'flow_status_alert',
            'flowEvent': event,
            'flowId': flow_id,
            'newStatus': new_status,
            'alertState': alert_state,
            'inUse': in_use,
            'message': str(value.get('message') or '')[:200],
            'action': 'Review the Flow in WhatsApp Manager > Flows',
            'requestId': request_id,
        }))


def _process_phone_quality_update(value: Dict, request_id: str) -> None:
    """
    Process phone number quality update webhook.
    
    Webhook format:
    {
        "display_phone_number": "+1234567890",
        "current_limit": "TIER_1K" | "TIER_10K" | "TIER_100K" | "TIER_UNLIMITED",
        "event": "FLAGGED" | "UNFLAGGED",
        "quality_score": "GREEN" | "YELLOW" | "RED"
    }
    
    Quality scores:
    - GREEN: High quality, no issues
    - YELLOW: Medium quality, some issues
    - RED: Low quality, at risk of being blocked
    
    Events:
    - FLAGGED: Phone number flagged due to quality issues
    - UNFLAGGED: Phone number quality restored
    """
    display_phone = value.get('display_phone_number', '')
    current_limit = value.get('current_limit', '')
    event = value.get('event', '')
    quality_score = value.get('quality_score', '')
    
    logger.info(json.dumps({
        'event': 'phone_quality_update',
        'displayPhone': mask_phone(display_phone),
        'currentLimit': current_limit,
        'qualityEvent': event,
        'qualityScore': quality_score,
        'requestId': request_id
    }))
    
    # Store phone quality in SystemConfig table
    _store_system_event(
        event_type='phone_quality',
        event_data={
            'displayPhone': display_phone,
            'currentLimit': current_limit,
            'event': event,
            'qualityScore': quality_score
        },
        request_id=request_id
    )
    
    # Log warning for quality issues
    if quality_score in ['YELLOW', 'RED'] or event == 'FLAGGED':
        logger.warning(json.dumps({
            'event': 'phone_quality_alert',
            'displayPhone': mask_phone(display_phone),
            'qualityScore': quality_score,
            'qualityEvent': event,
            'action': 'Review message quality and reduce spam complaints',
            'requestId': request_id
        }))


def _process_account_update(value: Dict, request_id: str) -> None:
    """
    Process account update webhook (messaging limits, restrictions, etc.).
    
    Webhook format for messaging limit changes:
    {
        "phone_number": "+1234567890",
        "event": "PHONE_NUMBER_MESSAGING_LIMIT_CHANGED",
        "current_limit": "TIER_1K" | "TIER_10K" | "TIER_100K" | "TIER_UNLIMITED"
    }
    
    Webhook format for account restrictions:
    {
        "event": "ACCOUNT_RESTRICTION",
        "restriction_type": "RESTRICTED_ADD_PHONE_NUMBER_ACTION" | ...
    }
    
    Messaging limit tiers:
    - TIER_1K: 1,000 business-initiated conversations per 24 hours
    - TIER_10K: 10,000 business-initiated conversations per 24 hours
    - TIER_100K: 100,000 business-initiated conversations per 24 hours
    - TIER_UNLIMITED: Unlimited business-initiated conversations
    """
    event = value.get('event', '')
    phone_number = value.get('phone_number', '')
    current_limit = value.get('current_limit', '')
    restriction_type = value.get('restriction_type', '')
    ban_info = value.get('ban_info', {})
    
    logger.info(json.dumps({
        'event': 'account_update',
        'accountEvent': event,
        'phoneNumber': mask_phone(phone_number),
        'currentLimit': current_limit,
        'restrictionType': restriction_type,
        'banInfo': ban_info,
        'requestId': request_id
    }))
    
    # Store account update in SystemConfig table
    _store_system_event(
        event_type='account_update',
        event_data={
            'event': event,
            'phoneNumber': phone_number,
            'currentLimit': current_limit,
            'restrictionType': restriction_type,
            'banInfo': ban_info
        },
        request_id=request_id
    )
    
    # Log messaging limit changes
    if event == 'PHONE_NUMBER_MESSAGING_LIMIT_CHANGED':
        logger.info(json.dumps({
            'event': 'messaging_limit_changed',
            'phoneNumber': mask_phone(phone_number),
            'newLimit': current_limit,
            'requestId': request_id
        }))
    
    # Log warnings for restrictions
    if event == 'ACCOUNT_RESTRICTION' or restriction_type:
        logger.warning(json.dumps({
            'event': 'account_restriction_alert',
            'restrictionType': restriction_type,
            'action': 'Review account in Meta Business Manager',
            'requestId': request_id
        }))
    
    # Log ban info if present
    if ban_info:
        logger.error(json.dumps({
            'event': 'account_ban_alert',
            'banInfo': ban_info,
            'action': 'Contact Meta support immediately',
            'requestId': request_id
        }))


def _store_system_event(event_type: str, event_data: Dict, request_id: str) -> None:
    """
    Store system event in SystemConfig table for dashboard display.
    Uses a composite key: whatsapp_events_{event_type}
    Stores last 10 events of each type.
    
    Note: SystemConfigTable PK is 'id', we use id=configKey for compatibility.
    """
    try:
        config_table = dynamodb.Table(SYSTEM_CONFIG_TABLE)
        config_key = f'whatsapp_events_{event_type}'
        now = int(time.time())
        
        # Get existing events (PK is 'id')
        try:
            response = config_table.get_item(Key={'id': config_key})
            existing = response.get('Item', {})
            events_list = json.loads(existing.get('configValue', '[]'))
        except Exception:
            events_list = []
        
        # Add new event with timestamp
        new_event = {
            'timestamp': now,
            'data': event_data
        }
        events_list.insert(0, new_event)
        
        # Keep only last 10 events
        events_list = events_list[:10]
        
        # Store updated events (PK is 'id')
        config_table.put_item(Item={
            'id': config_key,
            'configKey': config_key,
            'configValue': json.dumps(events_list),
            'updatedAt': Decimal(str(now))
        })
        
        logger.info(json.dumps({
            'event': 'system_event_stored',
            'eventType': event_type,
            'configKey': config_key,
            'eventsCount': len(events_list),
            'requestId': request_id
        }))
        
    except dynamodb.meta.client.exceptions.ResourceNotFoundException:
        # SystemConfig table doesn't exist - skip silently
        logger.warning(json.dumps({
            'event': 'system_event_store_skipped',
            'eventType': event_type,
            'reason': 'SystemConfig table not found',
            'requestId': request_id
        }))
    except Exception as e:
        logger.error(json.dumps({
            'event': 'system_event_store_error',
            'eventType': event_type,
            'error': str(e),
            'requestId': request_id
        }))


def _process_group_event(value: Dict, event_subtype: str, request_id: str) -> None:
    """
    Process group webhook events and update WhatsAppGroup table.
    Handles: group_participant_change, group_membership_approval_request.
    Per Meta Groups API docs.
    """
    try:
        GROUP_TABLE = os.environ.get('GROUP_TABLE', 'stack-wecare-digital-WhatsAppGroupTable')
        group_table = dynamodb.Table(GROUP_TABLE)
        now = int(time.time())

        # Extract group info from webhook value
        groups = value.get('groups', [value]) if isinstance(value.get('groups'), list) else [value]
        for group_data in groups:
            group_id = group_data.get('group_id', group_data.get('id', ''))
            if not group_id:
                continue

            subject = group_data.get('subject', '')
            participants = group_data.get('participants', [])
            action = group_data.get('action', event_subtype)

            # Upsert group record
            update_expr = 'SET updatedAt = :now'
            expr_vals: Dict[str, Any] = {':now': Decimal(str(now))}

            if subject:
                update_expr += ', subject = :subj'
                expr_vals[':subj'] = subject
            if participants:
                update_expr += ', lastParticipantEvent = :pe'
                expr_vals[':pe'] = json.dumps({
                    'action': action,
                    'participants': participants[:20],  # Limit stored participants
                    'timestamp': now,
                })

            try:
                group_table.update_item(
                    Key={'id': group_id},
                    UpdateExpression=update_expr,
                    ExpressionAttributeValues=expr_vals,
                )
            except Exception:
                # Table may not exist yet  -  create item instead
                group_table.put_item(Item={
                    'id': group_id,
                    'groupId': group_id,
                    'subject': subject,
                    'lastParticipantEvent': json.dumps({
                        'action': action,
                        'participants': participants[:20],
                        'timestamp': now,
                    }),
                    'createdAt': Decimal(str(now)),
                    'updatedAt': Decimal(str(now)),
                })

            logger.info(json.dumps({
                'event': 'group_event_processed',
                'groupId': group_id,
                'action': action,
                'participantCount': len(participants),
                'requestId': request_id,
            }))
    except Exception as e:
        logger.error(json.dumps({
            'event': 'group_event_processing_error',
            'error': str(e),
            'requestId': request_id,
        }))
