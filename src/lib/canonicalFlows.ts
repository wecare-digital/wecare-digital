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
import { REVIEW_ENTRY_KEYWORDS, REVIEW_FLOW_ID } from './reviewEntry';

export type FlowStatus = 'PUBLISHED' | 'DRAFT' | 'DEPRECATED' | 'NONE';

export interface CanonicalFlow {
  /** Capability key, matching DEFAULT_FLOW_TRIGGERS keys in the inbound handler. */
  readonly capability: string;
  /** Human label as shown to staff. */
  readonly label: string;
  /** The retained Meta Flow id on WABA 1, or null when the capability has no Flow. */
  readonly flowId: string | null;
  /** Meta lifecycle state per the 2026-10-09 readback, corrected by the 2026-10-25 live read. */
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
    flowId: null, status: 'NONE', metaName: null,
  },
  // DEPRECATED on Meta (live read 2026-10-25): it cannot be sent. The id stays as the identity
  // of past paid submissions; paid requests start on the website.
  submit_request: {
    capability: 'submit_request', label: 'Submit Request',
    flowId: '993516553092471', status: 'PUBLISHED', metaName: 'WD-F004-Submit-Request',
  },
  // F005 Request Amendment replacement, published on Meta 2026-10-29.
  amend_request: {
    capability: 'amend_request', label: 'Request Amendment',
    flowId: '2408621596338289', status: 'PUBLISHED', metaName: 'WD-F004-Request-Amendment',
  },
  // Request Pickup published on Meta 2026-10-29. Runtime completion handling stays guarded
  // until the published completion payload carries the pickup-specific fields.
  request_pickup: {
    capability: 'request_pickup', label: 'Request Pickup',
    flowId: '2988393421499259', status: 'PUBLISHED', metaName: 'WD-F005-Pick-Up-Request',
  },
  // F003 Drop Docs replacement, published on Meta 2026-10-28.
  drop_docs: {
    capability: 'drop_docs', label: 'Drop Docs',
    flowId: '39581903361452878', status: 'PUBLISHED', metaName: 'WD-F003-DROP-DOCS',
  },
  shipments: {
    capability: 'shipments', label: 'Shipments',
    flowId: '1804165164183485', status: 'PUBLISHED', metaName: 'WD-F006-Track-Shipping',
  },
  // F008 published in Meta on 2026-11-01. Authenticated customer-initiated send only;
  // no keyword, post-payment or automatic referred-person outreach.
  referral: {
    capability: 'referral', label: 'Refer Someone',
    flowId: '1933489271340286', status: 'PUBLISHED', metaName: 'WD-F008- Referal',
  },
  leave_review: {
    capability: 'leave_review', label: 'Leave Review',
    flowId: REVIEW_FLOW_ID, status: 'PUBLISHED', metaName: 'WD-F002-LEAVE-REVIEW',
  },
  // Vault has no separate Flow: it is a website CTA + ₹49 catalog delivery.
  vault: {
    capability: 'vault', label: 'Vault',
    flowId: null, status: 'NONE', metaName: null,
  },
  // F001 replacement. Published in Meta; runtime activation remains controlled from
  // FlowRegistry/SystemConfig so publication does not by itself enable customer sends.
  subscribe: {
    capability: 'subscribe', label: 'Subscribe',
    flowId: '2413873616105042', status: 'PUBLISHED', metaName: 'WD-F001-SUBSCRIBE-PROFILE',
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

/** Published metadata for a customer-facing Flow. Draft/NONE entries deliberately return null. */
export const publishedFlow = ( capability: string ): CanonicalFlow | null => {
  const flow = CANONICAL_FLOWS[capability];
  return flow?.flowId && flow.status === 'PUBLISHED' ? flow : null;
};

/** Resolve a published Meta Flow id back to the canonical capability record. */
export const publishedFlowById = ( flowId: string ): CanonicalFlow | null => {
  const target = String( flowId || '' ).trim();
  if ( !target ) return null;
  return Object.values( CANONICAL_FLOWS )
    .find( flow => flow.flowId === target && flow.status === 'PUBLISHED' ) ?? null;
};

export type EntryMode = 'keyword_interactive' | 'payment_template' | 'internal_event' | 'manual' | 'none';

/** The fixed launch contract of a canonical Flow capability. */
export interface CanonicalContract {
  readonly flowNumber: string;
  readonly flowCode: string;
  readonly label: string;
  readonly flowType: string;
  readonly entryMode: EntryMode;
  readonly entryTemplateName: string;
  readonly requiresPayment: boolean;
  readonly submissionPrefix: string;
  readonly wabaId: string;
  readonly tokenPrefix: string;
  readonly defaultKeywords: readonly string[];
  readonly legacyFlowCodes: readonly string[];
}

/**
 * Twin of CANONICAL_CONTRACTS in amplify/functions/shared/lambda_utils/canonical_flows.py.
 * The server enforces the contract on every FlowRegistry write and every launch; Workspace
 * uses this copy to explain it. scripts/check_f001_subscribe.py asserts the twins agree.
 */
export const CANONICAL_CONTRACTS: Record<string, CanonicalContract> = {
  subscribe: {
    flowNumber: 'F001',
    flowCode: 'WD-F001-SUBSCRIBE-PROFILE',
    label: 'Subscribe',
    flowType: 'data_collection',
    entryMode: 'keyword_interactive',
    entryTemplateName: '',
    requiresPayment: false,
    submissionPrefix: 'WD-SUB',
    wabaId: '2094615664435155',
    tokenPrefix: 'subscribe',
    defaultKeywords: [ 'subscribe', 'signup', 'sign up', 'register', 'join', '/subscribe' ],
    legacyFlowCodes: [ 'WD_SUBSCRIBE' ],
  },
  drop_docs: {
    flowNumber: 'F003',
    flowCode: 'WD_F003_DROP_DOCS',
    label: 'Drop Docs',
    flowType: 'drop_docs',
    entryMode: 'payment_template',
    entryTemplateName: '_dropdoc_flow',
    requiresPayment: true,
    submissionPrefix: 'WD-DOC',
    wabaId: '2094615664435155',
    tokenPrefix: 'drop_docs',
    defaultKeywords: [ 'drop docs', 'upload documents', 'upload docs', 'send documents', 'send docs', 'documents' ],
    legacyFlowCodes: [],
  },
  referral: {
    flowNumber: 'F008',
    flowCode: 'WD-F008-REFERRAL',
    label: 'Referral',
    flowType: 'referral',
    entryMode: 'none',
    entryTemplateName: '',
    requiresPayment: false,
    submissionPrefix: 'WD-REF',
    wabaId: '2094615664435155',
    tokenPrefix: 'referral',
    defaultKeywords: [],
    legacyFlowCodes: [],
  },
  leave_review: {
    flowNumber: 'F002',
    flowCode: 'WD-F002-LEAVE-REVIEW',
    label: 'Leave Review',
    flowType: 'customer_idea',
    entryMode: 'keyword_interactive',
    entryTemplateName: '',
    requiresPayment: false,
    submissionPrefix: 'WD-IDEA',
    wabaId: '2094615664435155',
    tokenPrefix: 'leave_review',
    defaultKeywords: REVIEW_ENTRY_KEYWORDS,
    legacyFlowCodes: [ 'WD_IDEA', 'WD_REV' ],
  },
};

/** The launch contract for a capability, or null when it has none. */
export const canonicalContract = ( capability: string ): CanonicalContract | null =>
  CANONICAL_CONTRACTS[capability] ?? null;

/** [capability, contract] for a canonical Flow id that carries a contract, or null. */
export const contractForFlowId = ( flowId: string ): [ string, CanonicalContract ] | null => {
  const target = String( flowId || '' ).trim();
  if ( !target ) return null;
  const match = Object.entries( CANONICAL_CONTRACTS )
    .find( ( [ capability ] ) => CANONICAL_FLOWS[capability]?.flowId === target );
  return match ?? null;
};
