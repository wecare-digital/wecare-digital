"""Shared WhatsApp/Meta template constants and enums.

No Graph host or API version lives here. Two constants naming the Graph host and the default
API version were declared in this file as independent literals with zero importers, which read
as configuration while deciding nothing -- the 2026-10-01 version audit counted them as two of
six sources of truth for a value that must have exactly one. `lambda_utils.meta_version` is the
sole authority; take the version, the base URL and the URL builder from there.

Deliberately not re-exported. A re-export would add `whatsapp_types -> meta_version` to the
Lambda packaging closure that `tests/test_provision_checkout_contract.py` pins, so every
function importing a template constant would start shipping the version module too.
"""

TEMPLATE_CATEGORIES = ('MARKETING', 'UTILITY', 'AUTHENTICATION')

HEADER_FORMATS = ('TEXT', 'IMAGE', 'VIDEO', 'GIF', 'DOCUMENT', 'LOCATION')

BUTTON_TYPES = (
    'QUICK_REPLY', 'URL', 'PHONE_NUMBER', 'COPY_CODE', 'VOICE_CALL',
    'OTP', 'MPM', 'SPM', 'CATALOG', 'FLOW', 'REQUEST_CONTACT_INFO',
)

# message_send_ttl_seconds bounds per category (None = use -1 30d sentinel allowed)
TTL_BOUNDS = {
    'AUTHENTICATION': (30, 900),
    'UTILITY': (30, 43200),
    'MARKETING': (43200, 2592000),
}
TTL_NEG1_ALLOWED = {'AUTHENTICATION', 'UTILITY'}

PERMISSION_TASKS = (
    'MANAGE', 'DEVELOP', 'MANAGE_TEMPLATES', 'MANAGE_PHONE', 'VIEW_COST',
    'MANAGE_EXTENSIONS', 'VIEW_PHONE_ASSETS', 'MANAGE_PHONE_ASSETS', 'VIEW_TEMPLATES', 'MESSAGING',
)

ASSIGNED_USER_TYPES = ('BUSINESS_USER', 'SYSTEM_USER', 'PERSONAL_USER')

SCHEDULE_STATUSES = ('COMPLETED', 'FAILED', 'SCHEDULED', 'SENDING')

JOIN_APPROVAL_MODES = ('approval_required', 'auto_approve')

# Pricing categories (analytics + webhooks)
PRICING_CATEGORY_AI_ANALYTICS = 'AI_BOT'
PRICING_CATEGORY_AI_WEBHOOK = 'general_purpose_ai'

# Group limits
GROUP_SUBJECT_MAX = 128
GROUP_DESCRIPTION_MAX = 2048

# Component text limits
HEADER_TEXT_MAX = 60
BODY_TEXT_MAX = 1024
FOOTER_TEXT_MAX = 60
BUTTON_TEXT_MAX = 25
COPY_CODE_EXAMPLE_MAX = 20
PHONE_NUMBER_MAX = 20
URL_MAX = 2000
FLOW_NAME_MAX = 200

# Limited-time-offer templates. LTO_TEXT_MAX is Meta's believed cap on the offer
# label and is NOT confirmable from anything in this repo -- it lives here alone so a
# correction is one line, and template_validation reads it rather than inlining 16.
LTO_COMPONENT_TYPE = 'LIMITED_TIME_OFFER'
LTO_TEXT_MAX = 16
LTO_ALLOWED_CATEGORIES = ('MARKETING',)
LTO_HEADER_FORMATS = ('IMAGE', 'VIDEO')
LTO_REQUIRED_BUTTON_TYPES = ('COPY_CODE', 'URL')

# Authentication-template OTP buttons. SIGNATURE_HASH_LEN is Meta's documented length
# for an Android app signature hash. NOTHING in this account can produce one, because
# there is no signed Android app -- native packaging is POST-PROJECT -- so the length
# is enforced as a WARNING rather than an error: a hard check would be a rule written
# against a value nobody here has ever held. No package name and no signature hash is
# declared anywhere in this file, deliberately.
OTP_TYPES = ('COPY_CODE', 'ONE_TAP', 'ZERO_TAP')
OTP_AUTOFILL_TYPES = ('ONE_TAP', 'ZERO_TAP')
OTP_AUTOFILL_TEXT_MAX = 25
SIGNATURE_HASH_LEN = 11
