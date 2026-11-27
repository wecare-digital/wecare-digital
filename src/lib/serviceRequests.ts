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
import { publicActionText } from './publicActionNotices';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api';
const REQUEST_INTENT_URL = `${ API_BASE }/services/request-intent`;

/**
 * Public service-refusal codes stay stable, while customer-facing feedback
 * always uses the same six approved action notices. Backend codes remain
 * authoritative for pricing, eligibility and pre-payment refusal decisions.
 * Never render raw provider/server error messages to customers.
 */
export const SERVICE_REFUSAL_MESSAGES: Readonly<Record<string, string>> = {
  SERVICE_NOT_OFFERED: publicActionText( 'blocked' ),
  SERVICE_UNKNOWN_CHOICE: publicActionText( 'failure' ),
  SERVICE_INVALID_QUANTITY: publicActionText( 'failure' ),
  SERVICE_ONE_PER_ORDER: publicActionText( 'blocked' ),
  SERVICE_SEPARATE_CHECKOUT: publicActionText( 'blocked' ),
  SERVICE_INTENT_REQUIRED: publicActionText( 'blocked' ),
  SERVICE_ORIGINAL_ORDER_REQUIRED: publicActionText( 'failure' ),
  SERVICE_UNAVAILABLE: publicActionText( 'blocked' ),
  SERVICE_WEBSITE_ONLY: publicActionText( 'blocked' ),
  SERVICE_PRICE_CHANGED: publicActionText( 'blocked' ),
  SERVICE_NOT_PAYABLE: publicActionText( 'blocked' ),
};

/** Is this prepare status one of the service refusals? */
export const isServiceRefusal = ( code: string ): boolean =>
  Object.prototype.hasOwnProperty.call( SERVICE_REFUSAL_MESSAGES, code );

interface ServiceIntent {
  intentId: string;
  kind: ServiceKind;
  variantId: string;
  /**
   * ALWAYS `null` since 2026-10-08: PRICED AT CHECKOUT, from ProductsTable. An intent is pre-payment, and
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


type IntentOutcome =
  | { kind: 'ok'; intent: ServiceIntent }
  | { kind: 'notFound' }
  | { kind: 'refused'; message: string }
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

