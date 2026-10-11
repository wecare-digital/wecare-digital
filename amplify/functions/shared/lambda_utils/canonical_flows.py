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
    'orders':         ('2167802357142172', 'DRAFT',     'WD_Orders_Design_v1'),
    'submit_request': ('1107164111921876', 'PUBLISHED', 'WD_Submit_Request_Paid_v1'),
    'amend_request':  ('3678132465672138', 'DRAFT',     '03.WD_Amend_Request'),
    'drop_docs':      ('1211063631104445', 'DRAFT',     'WD_Drop_Documents'),
    'shipments':      ('849713848195607',  'DRAFT',     'WD_Shipments_Design_v1'),
    'leave_review':   ('1578178897413815', 'PUBLISHED', 'WD_Leave_Review_v2'),
    # Vault: website CTA + ₹49 catalog delivery, no Flow.
    'vault':          (None, 'NONE', None),
    # Subscribe: NO production Flow. The 02.WD_Profile ids 1262971692700761 / 951987930811295
    # are DEPRECATED and must not be resurrected; profile screens belong in the Orders draft.
    'subscribe':      (None, 'NONE', None),
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
