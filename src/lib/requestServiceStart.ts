import type { RequestServiceCode } from '../config/requestServiceContracts';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api';

const headers = ( token: string ) => ( {
  'Content-Type': 'application/json',
  Accept: 'application/json',
  Authorization: `Bearer ${ token }`,
} );

export interface CustomerOrderChoice {
  orderNumber: string;
  createdAt: number | string | null;
  status: string;
}

export type CustomerOrdersOutcome =
  | { kind: 'ok'; orders: CustomerOrderChoice[]; cursor: string }
  | { kind: 'expired' }
  | { kind: 'rate' }
  | { kind: 'failed' };

export type RequestServiceStartOutcome =
  | { kind: 'sent'; paymentAttemptId: string; amountPaise: number; currency: 'INR' }
  | { kind: 'expired' }
  | { kind: 'notAvailable' }
  | { kind: 'rate' }
  | { kind: 'refused'; code: string }
  | { kind: 'failed' };

/** Caller-owned orders only. Identity is taken from the Cognito session, never from this request. */
export async function fetchCustomerOrders (
  token: string, cursor?: string,
): Promise<CustomerOrdersOutcome> {
  try {
    const response = await fetch( `${ API_BASE }/ecommerce/my-orders`, {
      method: 'POST',
      headers: headers( token ),
      body: JSON.stringify( { limit: 50, ...( cursor ? { cursor } : {} ) } ),
    } );
    if ( response.status === 401 ) return { kind: 'expired' };
    if ( response.status === 429 ) return { kind: 'rate' };
    if ( !response.ok ) return { kind: 'failed' };
    const data = await response.json() as { orders?: any[]; cursor?: string };
    const orders = ( Array.isArray( data.orders ) ? data.orders : [] )
      .map( row => ( {
        orderNumber: String( row?.orderNumber || '' ),
        createdAt: row?.createdAt ?? null,
        status: String( row?.status || row?.paymentStatus || '' ),
      } ) )
      .filter( row => row.orderNumber.startsWith( 'WD-ORD-' ) );
    return { kind: 'ok', orders, cursor: String( data.cursor || '' ) };
  } catch {
    return { kind: 'failed' };
  }
}

/**
 * Start exactly one WhatsApp-native service payment against exactly one existing Order Number.
 * No amount, SKU, customer id, internal order id or request id is accepted from the browser.
 */
export async function startRequestService (
  token: string,
  serviceCode: RequestServiceCode,
  selectedOrderNumber: string,
): Promise<RequestServiceStartOutcome> {
  try {
    const response = await fetch( `${ API_BASE }/ecommerce/request-service-start`, {
      method: 'POST',
      headers: headers( token ),
      body: JSON.stringify( { serviceCode, selectedOrderNumber } ),
    } );
    if ( response.status === 401 ) return { kind: 'expired' };
    if ( response.status === 404 ) return { kind: 'notAvailable' };
    if ( response.status === 429 ) return { kind: 'rate' };
    const data = await response.json().catch( () => ( {} ) ) as any;
    if ( !response.ok ) {
      return { kind: 'refused', code: String( data?.error || 'REQUEST_REFUSED' ) };
    }
    if ( data?.status !== 'PAYMENT_REQUEST_SENT' || !data?.paymentAttemptId ) {
      return { kind: 'failed' };
    }
    return {
      kind: 'sent',
      paymentAttemptId: String( data.paymentAttemptId ),
      amountPaise: Number( data.amountPaise || 0 ),
      currency: 'INR',
    };
  } catch {
    return { kind: 'failed' };
  }
}
