/**
 * The canonical WABA 1 Flow map — the ONE TypeScript source of truth for which Meta Flow
 * id backs each customer-service capability.
 *
 * WHY THIS MODULE EXISTS. Six surfaces used to restate flow ids as literals — the website
 * entry config, the inbound handler's DEFAULT_FLOW_TRIGGERS, and four workspace tables
 * (forms/selfservice, engage/whatsapp/settings, engage/whatsapp/scripts,
 * dashboard/system-architecture). They drifted: the same capability named three or four
 * DIFFERENT ids, several of them unused DRAFT design-duplicates or DEPRECATED flows, while
 * the real published/retained flow sat elsewhere. The workspace confidently advertised doors
 * that pointed at the wrong flow. One module makes a one-sided edit impossible rather than
 * merely discouraged — the same move `reviewEntry.ts` already made for the review door.
 *
 * SOURCE OF TRUTH FOR THE IDS. `outputs/flow-retirement-2026-10-09.json` is a full paginated
 * live-Meta readback of both WABAs taken AFTER the 9-Oct deprecation run. Its `keepIds` list
 * is the retained plan. Every id below is one of those keepIds (or `null` where the capability
 * has no Flow). `tests/test_canonical_flow_ids.py` asserts this file against that readback and
 * against the inbound handler, and forbids any flow-id literal outside the canonical modules.
 *
 * Review stays in `reviewEntry.ts` (its keyword list is load-bearing elsewhere); this module
 * re-exports REVIEW_FLOW_ID so a reader has one complete table.
 */
import { REVIEW_FLOW_ID } from './reviewEntry';

export type FlowStatus = 'PUBLISHED' | 'DRAFT' | 'NONE';

export interface CanonicalFlow {
  /** Capability key, matching DEFAULT_FLOW_TRIGGERS keys in the inbound handler. */
  readonly capability: string;
  /** Human label as shown to staff. */
  readonly label: string;
  /** The retained Meta Flow id on WABA 1, or null when the capability has no Flow. */
  readonly flowId: string | null;
  /** Meta lifecycle state per the 2026-10-09 readback. */
  readonly status: FlowStatus;
  /** The Meta Flow name per the readback, for staff display and reconciliation. */
  readonly metaName: string | null;
}

/**
 * WABA 1 only (2094615664435155). WABA 2 is deliberately absent — it has no retained
 * customer-service Flow set and must not be routed from here.
 */
export const CANONICAL_FLOWS: Record<string, CanonicalFlow> = {
  orders: {
    capability: 'orders', label: 'Orders',
    flowId: '2167802357142172', status: 'DRAFT', metaName: 'WD_Orders_Design_v1',
  },
  submit_request: {
    capability: 'submit_request', label: 'Submit Request',
    flowId: '1107164111921876', status: 'PUBLISHED', metaName: 'WD_Submit_Request_Paid_v1',
  },
  amend_request: {
    capability: 'amend_request', label: 'Request Amendment',
    flowId: '3678132465672138', status: 'DRAFT', metaName: '03.WD_Amend_Request',
  },
  drop_docs: {
    capability: 'drop_docs', label: 'Drop Docs',
    flowId: '1211063631104445', status: 'DRAFT', metaName: 'WD_Drop_Documents',
  },
  shipments: {
    capability: 'shipments', label: 'Shipments',
    flowId: '849713848195607', status: 'DRAFT', metaName: 'WD_Shipments_Design_v1',
  },
  leave_review: {
    capability: 'leave_review', label: 'Leave Review',
    flowId: REVIEW_FLOW_ID, status: 'PUBLISHED', metaName: 'WD_Leave_Review_v2',
  },
  // Vault has no separate Flow: it is a website CTA + ₹49 catalog delivery.
  vault: {
    capability: 'vault', label: 'Vault',
    flowId: null, status: 'NONE', metaName: null,
  },
  // Subscribe has NO production Flow. The historical 02.WD_Profile ids (1262971692700761 /
  // 951987930811295) are DEPRECATED and must not be resurrected — profile/account screens
  // belong in the retained Orders draft. Entry stays a /subscribe/ CTA until a verified
  // profile backend exists.
  subscribe: {
    capability: 'subscribe', label: 'Subscribe',
    flowId: null, status: 'NONE', metaName: null,
  },
  // Track Request has no retained canonical Flow (not in keepIds). The former ids
  // 1486454129852338 (DRAFT) and 973888792200167 (DEPRECATED) are not canonical. Tracking is
  // served by GET /wa-business/service/track/{orderId} + the /orders/ page, not a Flow.
  track_request: {
    capability: 'track_request', label: 'Track Request',
    flowId: null, status: 'NONE', metaName: null,
  },
};

/** The retained flow id for a capability, or null when it has no Flow. */
export const canonicalFlowId = ( capability: string ): string | null =>
  CANONICAL_FLOWS[capability]?.flowId ?? null;

/** The Meta lifecycle status for a capability's canonical flow. */
export const canonicalFlowStatus = ( capability: string ): FlowStatus =>
  CANONICAL_FLOWS[capability]?.status ?? 'NONE';
