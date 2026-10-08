/**
 * The browser client for the Phase O-1 service-request routes, and the refusal sentences.
 *
 *   POST /services/request-intent   { kind, targetRequestId? } -> a PRE-PAYMENT intent
 *   POST /services/my-requests      { referenceIds?, cursor? }  -> the caller's own requests
 *
 * An intent is NOT a request. It carries no public id, never appears on /orders and grants
 * nothing; the copyable `WD-REQ-…` id exists only once the order it pays for exists. The intent
 * id travels to checkout as `serviceIntentId` (see src/lib/cart.ts `serviceIntentFor`), so the
 * server can join the paid order back to what the customer chose - including, for an amendment,
 * which of THEIR requests it amends, which is checked here BEFORE any money moves.
 *
 * No amount, price or currency is ever sent from here.
 */

import type { ServiceKind } from '../config/services';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api';
export const REQUEST_INTENT_URL = `${ API_BASE }/services/request-intent`;
export const MY_REQUESTS_URL = `${ API_BASE }/services/my-requests`;

/**
 * One sentence per server refusal code, word for word the server's own
 * (service_requests.py SERVICE_MESSAGES). tests/test_service_requests.py holds the two equal.
 * Every one ends "Nothing has been charged." because every one is raised before a gateway order
 * can exist.
 */
export const SERVICE_REFUSAL_MESSAGES: Readonly<Record<string, string>> = {
  SERVICE_NOT_OFFERED: 'This service is not offered yet. Nothing has been charged.',
  SERVICE_UNKNOWN_CHOICE: 'Choose a WECARE.DIGITAL service. Nothing has been charged.',
  SERVICE_INVALID_QUANTITY: 'A service is bought one at a time. Set its quantity to 1. Nothing has been charged.',
  SERVICE_ONE_PER_ORDER: 'Only one service can be paid for in an order. Remove the extra one. Nothing has been charged.',
  SERVICE_INTENT_REQUIRED: 'Start this service from its own page, then check out. Nothing has been charged.',
  SERVICE_UNAVAILABLE: 'Services cannot be paid for right now. Nothing has been charged.',
  SERVICE_WEBSITE_ONLY: 'Services can only be paid for on the website. Nothing has been charged.',
  SERVICE_PRICE_CHANGED: 'The price of this service has changed. Nothing has been charged.',
  SERVICE_NOT_PAYABLE: 'This service cannot be paid for right now. Nothing has been charged.',
};

/** Is this prepare status one of the service refusals? */
export const isServiceRefusal = ( code: string ): boolean =>
  Object.prototype.hasOwnProperty.call( SERVICE_REFUSAL_MESSAGES, code );

export interface ServiceIntent {
  intentId: string;
  kind: ServiceKind;
  variantId: string;
  /**
   * ALWAYS `null` since 2026-10-08: PRICED AT CHECKOUT, by Wix. An intent is pre-payment, and
   * the server stores no amount on it (service_request_store `_new_intent`), because a stored
   * figure would be a guess — and a guess on a money row is what later gets compared against
   * reality and refuses an honest payment. The key is kept on the wire so the payload stays a
   * superset of what this module reads, and `null` says "not priced yet" where a `0` would have
   * claimed the service is free. Read the live price from `src/lib/servicePricing.ts` instead.
   */
  amountPaise: number | null;
  currency: string;
  targetRequestId: string | null;
}

export interface ServiceRequestRow {
  /** The public, copyable id, e.g. WD-REQ-7K2M9QXA. */
  requestId: string;
  kind: ServiceKind | string;
  status: string;
  fileId?: string | null;
  fileName?: string | null;
  deliveryStatus?: string | null;
  /** INT epoch seconds, UTC. */
  createdAt: number | null;
  orderNumber: string;
  /** For an amendment: the public id of the request it amends. */
  targetRequestId: string | null;
}

export type IntentOutcome =
  | { kind: 'ok'; intent: ServiceIntent }
  | { kind: 'notFound' }
  | { kind: 'refused'; message: string }
  | { kind: 'expired' }
  | { kind: 'rate' }
  | { kind: 'failed' };

export type RequestsOutcome =
  | { kind: 'ok'; requests: ServiceRequestRow[]; cursor: string }
  | { kind: 'expired' }
  | { kind: 'rate' }
  | { kind: 'failed' };

const headers = ( token: string ) => ( {
  'Content-Type': 'application/json',
  Accept: 'application/json',
  Authorization: `Bearer ${ token }`,
} );

/** Ask the server for (or resume) the caller's open intent for one service. */
export async function postRequestIntent (
  token: string, kind: ServiceKind, targetRequestId?: string, fileId?: string,
): Promise<IntentOutcome> {
  try
  {
    const response = await fetch( REQUEST_INTENT_URL, {
      method: 'POST',
      headers: headers( token ),
      body: JSON.stringify( fileId ? { kind, fileId } : targetRequestId ? { kind, targetRequestId } : { kind } ),
    } );
    if ( response.status === 401 ) return { kind: 'expired' };
    if ( response.status === 429 ) return { kind: 'rate' };
    if ( response.status === 404 ) return { kind: 'notFound' };
    const data = ( await response.json().catch( () => ( {} ) ) ) as Partial<ServiceIntent> & {
      error?: string;
    };
    if ( !response.ok )
    {
      const code = String( data.error || '' );
      return isServiceRefusal( code )
        ? { kind: 'refused', message: SERVICE_REFUSAL_MESSAGES[ code ] }
        : { kind: 'failed' };
    }
    if ( !data.intentId || !data.kind || !data.variantId ) return { kind: 'failed' };
    return { kind: 'ok', intent: data as ServiceIntent };
  }
  catch
  {
    return { kind: 'failed' };
  }
}

/**
 * The caller's own requests. `referenceIds` are the caller's PAID orders' references: the server
 * activates any that are services orders before listing, so a request whose webhook hint was
 * missed still appears (the self-heal). At most 20 travel.
 */
export async function fetchMyRequests (
  token: string, referenceIds: readonly string[], cursor?: string,
): Promise<RequestsOutcome> {
  try
  {
    const ids = Array.from( new Set( referenceIds.filter( Boolean ) ) ).slice( 0, 20 );
    const response = await fetch( MY_REQUESTS_URL, {
      method: 'POST',
      headers: headers( token ),
      body: JSON.stringify( {
        ...( ids.length ? { referenceIds: ids } : {} ),
        ...( cursor ? { cursor } : {} ),
      } ),
    } );
    if ( response.status === 401 ) return { kind: 'expired' };
    if ( response.status === 429 ) return { kind: 'rate' };
    if ( !response.ok ) return { kind: 'failed' };
    const data = ( await response.json() ) as { requests?: ServiceRequestRow[]; cursor?: string };
    return {
      kind: 'ok',
      requests: Array.isArray( data.requests ) ? data.requests : [],
      cursor: String( data.cursor || '' ),
    };
  }
  catch
  {
    return { kind: 'failed' };
  }
}
