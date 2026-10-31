/**
 * Authenticated home/Orders menu doors for the two customer-initiated WhatsApp templates.
 *
 * The URL carries ONLY an allowlisted action, never a mobile number or bearer token.
 * /orders/ consumes the intent after Cognito sign-in and sends it to the customer-profile
 * API; that API takes the verified number exclusively from the authenticated session.
 *
 * A short-lived sessionStorage handoff survives the /auth/ redirect in the same tab,
 * and is consumed BEFORE an API send so reloads cannot silently send again.
 */
export type CustomerMenuAction = 'subscribe' | 'leave-review';

export const CUSTOMER_MENU_HREFS: Readonly<Record<CustomerMenuAction, string>> = {
  subscribe: '/orders/?service=subscribe',
  'leave-review': '/orders/?service=leave-review',
};

const PENDING_KEY = 'wecare.customer.pendingServiceAction';
const MAX_PENDING_AGE_MS = 10 * 60 * 1000;
const PROFILE_URL = `${process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api'}/customer/profile`;

export function actionFromSearch ( search: string ): CustomerMenuAction | null {
  const value = new URLSearchParams( search ).get( 'service' );
  return value === 'subscribe' || value === 'leave-review' ? value : null;
}

export function stashCustomerMenuAction ( action: CustomerMenuAction ): void {
  if ( typeof window === 'undefined' ) return;
  try {
    window.sessionStorage.setItem( PENDING_KEY, JSON.stringify( { action, at: Date.now() } ) );
  } catch {
    // Storage can be unavailable in privacy modes. The URL remains intact until sign-in.
  }
}

export function takeCustomerMenuAction (): CustomerMenuAction | null {
  if ( typeof window === 'undefined' ) return null;
  try {
    const raw = window.sessionStorage.getItem( PENDING_KEY );
    window.sessionStorage.removeItem( PENDING_KEY );
    if ( !raw ) return null;
    const parsed = JSON.parse( raw ) as { action?: string; at?: number };
    if ( !Number.isFinite( parsed.at ) || !parsed.at
      || Date.now() < parsed.at || Date.now() - parsed.at > MAX_PENDING_AGE_MS ) return null;
    return parsed.action === 'subscribe' || parsed.action === 'leave-review'
      ? parsed.action : null;
  } catch {
    return null;
  }
}

type SendResult = { kind: 'accepted'; messageId: string } | { kind: 'expired' } | { kind: 'failed' };

/** Never includes a recipient field. Only the server's authenticated session may choose it. */
export async function sendCustomerMenuAction ( action: CustomerMenuAction, accessToken: string ): Promise<SendResult> {
  const backendAction = action === 'subscribe' ? 'sendProfileUpdate' : 'sendLeaveReview';
  try {
    const response = await fetch( PROFILE_URL, {
      method: 'POST',
      cache: 'no-store',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
        Authorization: `Bearer ${ accessToken }`,
      },
      body: JSON.stringify( { action: backendAction } ),
    } );
    if ( response.status === 401 ) return { kind: 'expired' };
    const data = await response.json().catch( () => ( {} ) ) as { status?: string; messageId?: string };
    const expected = action === 'subscribe' ? 'PROFILE_UPDATE_SENT' : 'REVIEW_REQUEST_SENT';
    if ( response.ok && data.status === expected ) {
      return { kind: 'accepted', messageId: String( data.messageId || '' ) };
    }
    return { kind: 'failed' };
  } catch {
    return { kind: 'failed' };
  }
}
