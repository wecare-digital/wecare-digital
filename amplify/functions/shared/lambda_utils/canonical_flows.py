"""The canonical WABA 1 Flow map — the ONE Python source of truth for which Meta Flow id
backs each customer-service capability. Python twin of src/lib/canonicalFlows.ts.

WHY THIS MODULE EXISTS. Flow ids used to be hand-copied as literals across the inbound
handler's DEFAULT_FLOW_TRIGGERS and four workspace tables, and they drifted — the same
capability named different ids, several of them unused DRAFT design-duplicates or DEPRECATED
flows, while the real retained flow sat elsewhere. Centralising the ids here (and in the TS
twin) makes a one-sided edit a test failure rather than a silent production mismatch.

SOURCE OF TRUTH. outputs/flow-retirement-2026-10-09.json is a full paginated live-Meta
readback taken after the 9-Oct deprecation run; its keepIds list is the retained plan. Every
id below is one of those keepIds, or None where the capability has no Flow.
tests/test_canonical_flow_ids.py asserts this module against that readback and against the TS
twin, and forbids flow-id literals outside the canonical modules.

WABA 1 only (2094615664435155). WABA 2 has no retained customer-service Flow set and is not
routed from here.
"""

# capability -> (flow_id or None, status, meta_name or None)
CANONICAL_FLOWS = {
    'orders':         (None, 'NONE', None),  # No Orders Flow; website and invoices own this journey.
    # DEPRECATED on Meta (live read 2026-10-25): it cannot be sent, so `published_flow` no longer
    # offers it. The id stays as the identity of past paid submissions; paid requests start on
    # the website (lambda_utils/ecommerce/catalog_service_checkout.ALLOWED).
    # F004 Submit Request replacement, published on Meta 2026-10-29. The Flow is
    # endpointless-style at completion; inbound nfm_reply persistence owns the business row.
    'submit_request': ('993516553092471', 'PUBLISHED', 'WD-F004-Submit-Request'),
    # F005 Request Amendment replacement, published on Meta 2026-10-29. Like F004 Submit
    # Request, completion is persisted from inbound nfm_reply rather than data_exchange.
    'amend_request':  ('2408621596338289', 'PUBLISHED', 'WD-F004-Request-Amendment'),
    # Request Pickup published on Meta 2026-10-29. Completion payload is still guarded
    # separately because the published asset retained the cloned Submit Request marker.
    'request_pickup': ('2988393421499259', 'PUBLISHED', 'WD-F005-Pick-Up-Request'),
    # F003 Drop Docs replacement, published on Meta 2026-10-28.
    'drop_docs':      ('39581903361452878', 'PUBLISHED', 'WD-F003-DROP-DOCS'),
    'shipments':      ('1804165164183485', 'PUBLISHED', 'WD-F006-Track-Shipping'),
    # F008 published in Meta on 2026-11-01; response-only for now, no automatic launch.
    'referral':       ('1933489271340286', 'PUBLISHED', 'WD-F008- Referal'),
    'leave_review':   ('993862443003108',  'PUBLISHED', 'WD-F002-LEAVE-REVIEW'),
    # Vault: website CTA + ₹49 catalog delivery, no Flow.
    'vault':          (None, 'NONE', None),
    # F001 replacement. Published in Meta; runtime activation remains controlled from
    # FlowRegistry/SystemConfig so publication does not by itself enable customer sends.
    'subscribe':      ('2413873616105042', 'PUBLISHED', 'WD-F001-SUBSCRIBE-PROFILE'),
    # Track Request: not in keepIds. Former ids 1486454129852338 (DRAFT) / 973888792200167
    # (DEPRECATED) are not canonical. Tracking is served by
    # GET /wa-business/service/track/{orderId} + the /orders/ page, not a Flow.
    'track_request':  (None, 'NONE', None),
}


def canonical_flow_id(capability: str):
    """The retained flow id for a capability, or None when it has no Flow."""
    row = CANONICAL_FLOWS.get(capability)
    return row[0] if row else None


def canonical_flow_status(capability: str) -> str:
    """The Meta lifecycle status for a capability's canonical flow."""
    row = CANONICAL_FLOWS.get(capability)
    return row[1] if row else 'NONE'


def published_flow(capability: str):
    """Published canonical Flow metadata, or None when the capability is not live.

    DRAFT/NONE entries remain in the canonical registry for staff/reconciliation, but
    customer-facing callers can use this helper without accidentally sending a draft Flow.
    """
    row = CANONICAL_FLOWS.get(capability)
    if not row or not row[0] or row[1] != 'PUBLISHED':
        return None
    return {
        'capability': capability,
        'flowId': row[0],
        'status': row[1],
        'metaName': row[2],
    }


def published_flow_by_id(flow_id: str):
    """Resolve a published Meta Flow id back to its canonical capability."""
    target = str(flow_id or '').strip()
    if not target:
        return None
    for capability, row in CANONICAL_FLOWS.items():
        if row[0] == target and row[1] == 'PUBLISHED':
            return published_flow(capability)
    return None


_TOKEN_PREFIX_OVERRIDES = {
    'submit_request': 'sr',
}


def published_flow_by_name(meta_name: str):
    """Resolve a published Meta Flow name back to canonical metadata."""
    target = str(meta_name or '').strip().casefold()
    if not target:
        return None
    for capability, row in CANONICAL_FLOWS.items():
        if row[1] == 'PUBLISHED' and str(row[2] or '').strip().casefold() == target:
            return published_flow(capability)
    return None


def published_flow_token_prefix(capability: str) -> str:
    """Routing prefix for phone-backed Flow tokens."""
    return _TOKEN_PREFIX_OVERRIDES.get(capability, capability)


# Launch contract for canonical Flows that are production capabilities with a fixed entry
# model. A FlowRegistry row for one of these Flow ids must agree with its contract
# (lambda_utils.flow_launch enforces this on every registry write and every launch), so a
# Workspace edit cannot turn the profile Flow into a payment door or a template journey.
# Twin of CANONICAL_CONTRACTS in src/lib/canonicalFlows.ts; scripts/check_f001_subscribe.py
# asserts the two agree field for field.
CANONICAL_CONTRACTS = {
    'subscribe': {
        'flowNumber': 'F001',
        'flowCode': 'WD-F001-SUBSCRIBE-PROFILE',
        'label': 'Subscribe',
        'flowType': 'data_collection',
        'entryMode': 'keyword_interactive',
        'entryTemplateName': '',
        'requiresPayment': False,
        'submissionPrefix': 'WD-SUB',
        'wabaId': '2094615664435155',
        'tokenPrefix': 'subscribe',
        # Exact-match keywords used until Workspace saves its own list. '/subscribe' reaches
        # the same door through the inbound slash-command aliases.
        'defaultKeywords': ('subscribe', 'signup', 'sign up', 'register', 'join', '/subscribe'),
        # FlowSubmission flowCode used by F001 rows written before the canonical code.
        'legacyFlowCodes': ('WD_SUBSCRIBE',),
    },
    'drop_docs': {
        'flowNumber': 'F003',
        'flowCode': 'WD_F003_DROP_DOCS',
        'label': 'Drop Docs',
        'flowType': 'drop_docs',
        'entryMode': 'payment_template',
        'entryTemplateName': '_dropdoc_flow',
        'requiresPayment': True,
        'submissionPrefix': 'WD-DOC',
        'wabaId': '2094615664435155',
        'tokenPrefix': 'drop_docs',
        'defaultKeywords': (
            'drop docs', 'upload documents', 'upload docs',
            'send documents', 'send docs', 'documents',
        ),
        'legacyFlowCodes': (),
    },
    'leave_review': {
        'flowNumber': 'F002',
        'flowCode': 'WD-F002-LEAVE-REVIEW',
        'label': 'Leave Review',
        'flowType': 'customer_idea',
        'entryMode': 'keyword_interactive',
        'entryTemplateName': '',
        'requiresPayment': False,
        'submissionPrefix': 'WD-IDEA',
        'wabaId': '2094615664435155',
        'tokenPrefix': 'leave_review',
        'defaultKeywords': (
            'leave review', 'leave a review', 'review', 'reviews', 'feedback',
            'leave feedback', 'give feedback', 'share feedback', 'rate', 'rate us',
            'rate service', 'rating', 'ratings', 'testimonial', 'write a review',
            'give a review', 'share your experience', 'how was it', '⭐ leave review',
        ),
        'legacyFlowCodes': ('WD_IDEA', 'WD_REV'),
    },
}


def canonical_contract(capability: str):
    """The launch contract for a canonical capability, or None when it has none."""
    contract = CANONICAL_CONTRACTS.get(capability)
    return {**contract, 'capability': capability} if contract else None


def contract_for_flow_id(flow_id: str):
    """(capability, contract) for a canonical Flow id that carries a contract, else None."""
    target = str(flow_id or '').strip()
    if not target:
        return None
    for capability in CANONICAL_CONTRACTS:
        if canonical_flow_id(capability) == target:
            return capability, canonical_contract(capability)
    return None
