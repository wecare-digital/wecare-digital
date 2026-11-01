/**
 * One-time authenticated Orders actions for customer-initiated WhatsApp templates.
 *
 * An explicit first-party menu click is required to create a one-time send intent.
 * Plain navigation to /orders/ (including a copied URL with ?service=...) must NEVER
 * generate a WhatsApp send. A sessionStorage handoff survives the /auth/ redirect
 * in the same tab, then is consumed BEFORE an API call so refresh/back never resends.
 * The server chooses the verified phone from the authenticated session, never the URL.
 */
import { CONTRIBUTION_PRODUCT_ID, CONTRIBUTION_CHOICES } from '../config/contribution';

export type CustomerMenuAction = 'subscribe' | 'leave-review' | 'referral' | 'contribute';

export const CUSTOMER_MENU_HREFS: Readonly<Record<CustomerMenuAction, string>> = {
  subscribe: '/orders/',
  'leave-review': '/orders/',
  referral: '/orders/',
  contribute: '/orders/',
};

const PENDING_KEY = 'wecare.customer.pendingServiceAction';
const MAX_PENDING_AGE_MS = 10 * 60 * 1000;
const PROFILE_URL = `${process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api'}/customer/profile`;

/** Only explicit menu labels create send intents, never arbitrary URLs. */
export function menuActionForLabel ( label: string ): CustomerMenuAction | null {
  if ( label === 'Subscribe' ) return 'subscribe';
  if ( label === 'Leave Review' ) return 'leave-review';
  if ( label === 'Referral' ) return 'referral';
  return null;
}

/** Modified/new-tab opens navigate only: never queue a send in the original tab. */
export function isPrimaryMenuActivation ( event: {
  button: number; metaKey: boolean; ctrlKey: boolean; shiftKey: boolean; altKey: boolean;
} ): boolean {
  return event.button === 0 && !event.metaKey && !event.ctrlKey
    && !event.shiftKey && !event.altKey;
}

export function stashCustomerMenuAction ( action: CustomerMenuAction ): void {
  if ( typeof window === 'undefined' ) return;
  try {
    window.sessionStorage.setItem( PENDING_KEY, JSON.stringify( { action, at: Date.now() } ) );
  } catch {
    // Privacy-mode storage denial fails CLOSED: navigation occurs, but nothing is sent.
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
      || parsed.action === 'referral' || parsed.action === 'contribute'
      ? parsed.action : null;
  } catch {
    return null;
  }
}

type SendResult = { kind: 'accepted'; messageId: string } | { kind: 'expired' }
  | { kind: 'awaiting-template' } | { kind: 'failed' };

/** Never includes a recipient field. Only the server's authenticated session may choose it. */
export async function sendCustomerMenuAction ( action: CustomerMenuAction, accessToken: string ): Promise<SendResult> {
  const backendAction = action === 'subscribe' ? 'sendProfileUpdate'
    : action === 'referral' ? 'sendReferral' : 'sendLeaveReview';
  try {
    // The original one-use menu intent has already been consumed by OrdersPage.
    // Contribute is a PAYMENT, not a free-form invitation: send the exact catalog
    // SKU through the existing authenticated Commerce/ORDER_DETAILS rail.
    if ( action === 'contribute' ) {
      const choice = CONTRIBUTION_CHOICES[0];
      if ( !choice || choice.paise !== 30000 || typeof window === 'undefined'
        || typeof window.crypto?.randomUUID !== 'function' ) return { kind: 'failed' };
      const response = await fetch(
        `${ process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api' }/ecommerce/checkout`, {
          method: 'POST',
          cache: 'no-store',
          headers: {
            'Content-Type': 'application/json',
            Accept: 'application/json',
            Authorization: `Bearer ${ accessToken }`,
          },
          body: JSON.stringify( {
            action: 'create',
            requestKey: window.crypto.randomUUID(),
            lineItems: [ {
              catalogReference: {
                catalogItemId: CONTRIBUTION_PRODUCT_ID,
                options: { variantId: choice.variantId },
              },
              quantity: 1,
            } ],
          } ),
        },
      );
      if ( response.status === 401 ) return { kind: 'expired' };
      const data = await response.json().catch( () => ( {} ) ) as {
        status?: string; amountPaise?: number; currency?: string; paymentAttemptId?: string;
        error?: string;
      };
      if ( response.ok && data.status === 'PAYMENT_REQUEST_SENT'
        && data.amountPaise === 30000 && data.currency === 'INR'
        && typeof data.paymentAttemptId === 'string' && data.paymentAttemptId )
        return { kind: 'accepted', messageId: '' };
      // A 409 / release refusal creates no payable request. Never fall back to
      // a generic template or trigger a second attempt after a timeout.
      if ( response.status === 409 && (
        data.error === 'AMOUNT_NOT_SETTLED'
        || data.error === 'CONTRIBUTION_TAXABLE_NOT_RELEASED'
      ) ) return { kind: 'awaiting-template' };
      return { kind: 'failed' };
    }
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
    const expected = action === 'subscribe' ? 'PROFILE_UPDATE_SENT'
      : action === 'referral' ? 'REFERRAL_REQUEST_SENT' : 'REVIEW_REQUEST_SENT';
    if ( response.ok && data.status === expected ) {
      return { kind: 'accepted', messageId: String( data.messageId || '' ) };
    }
    return { kind: 'failed' };
  } catch {
    // Provider acceptance may already have happened. Never retry automatically.
    return { kind: 'failed' };
  }
}
