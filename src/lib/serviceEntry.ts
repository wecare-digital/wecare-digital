/**
 * The ONE front-door gate every service / product / contribute / pay CTA routes through.
 *
 * Owner decision 2026-10-08: one login ("Sign in on WhatsApp") for everything, and one flow:
 *   - signed in  → go straight to the action's form/checkout (no login screen);
 *   - signed out → go to the single `/account/sign-in` (WhatsApp OTP) with a return to the
 *                  SAME destination, then continue there after signing in.
 * There is no second login surface and no standalone OTP step; `/account/sign-in` IS the
 * WhatsApp sign-in.
 *
 * WHY THE DESTINATION IS NORMALLY `/cart/`
 * ----------------------------------------
 * `safeLocalReturnPath` only lets a post-sign-in redirect land on an allowlisted customer path
 * (`/cart/`, `/orders/`, `/blog/`, `/`), and that allowlist is a security control we do NOT
 * loosen. Every paid action in this store is a line on the ONE checkout (`/cart/`) — the four
 * fixed-price services (O-1/O-2), a contribution, and any product — so the gate's destination is
 * `/cart/`, which is already allowlisted and round-trips through sign-in unchanged. The specific
 * action (which service, which product) is carried OUT OF BAND in sessionStorage, the same
 * pattern Phase W used for the WhatsApp basket token, so it survives the sign-in round trip
 * without ever riding the `?return=` query string (which the validator strips).
 */

import type { NextRouter } from 'next/router';

import { getSession, restoreSession } from './customerAuth';

/** The one checkout surface. Allowlisted in safeReturnPath, so it survives the sign-in return. */
export const CHECKOUT_PATH = '/cart/';
/** The one WhatsApp login. */
export const SIGN_IN_PATH = '/account/sign-in/';
/** Out-of-band carrier for the pending action, so it survives the sign-in round trip. */
const PENDING_ACTION_KEY = 'wecare.pendingServiceAction';

/** A service/product/contribute action to resume on the checkout after sign-in. */
export interface PendingServiceAction {
  /** The service/product slug or line the checkout should preselect (e.g. 'submit-request'). */
  readonly kind: string;
  /** Wix product id for the line, when the action maps to a fixed catalogue line. */
  readonly productId?: string;
  /** Wix variant id for the line. */
  readonly variantId?: string;
  /** Optional human label for UI continuity. */
  readonly label?: string;
}

/** Stash the pending action out of band (survives the sign-in redirect; never on the URL). */
export function stashPendingAction ( action: PendingServiceAction ): void {
  if ( typeof window === 'undefined' ) return;
  try {
    window.sessionStorage.setItem( PENDING_ACTION_KEY, JSON.stringify( action ) );
  } catch { /* storage disabled: the checkout still works, it just will not preselect */ }
}

/** Read and CLEAR the pending action (single use), for the checkout to resume after arrival. */
export function takePendingAction (): PendingServiceAction | null {
  if ( typeof window === 'undefined' ) return null;
  try {
    const raw = window.sessionStorage.getItem( PENDING_ACTION_KEY );
    if ( !raw ) return null;
    window.sessionStorage.removeItem( PENDING_ACTION_KEY );
    const parsed = JSON.parse( raw ) as PendingServiceAction;
    return parsed && typeof parsed.kind === 'string' ? parsed : null;
  } catch { return null; }
}

/** True when a customer WhatsApp session is live right now (sync, no network). */
export function isSignedIn (): boolean {
  return getSession() !== null;
}

/**
 * The gate. Resolve the session, then route:
 *   signed in  → push `destination` (default `/cart/`), the real form/checkout → payment;
 *   signed out → push `/account/sign-in/?return=<destination>`, the one WhatsApp login,
 *                which returns to `destination` after sign-in to continue.
 *
 * `action`, when given, is stashed out of band first so the checkout can preselect the service
 * line whether or not a sign-in happened in between.
 *
 * `restoreSession` is tried only when the fast sync `getSession` is empty, because the customer
 * may have a valid server cookie whose short access token has not yet been rehydrated into this
 * tab — exactly the case `/account/sign-in` itself handles on load. A failed restore just means
 * "not signed in", so the customer sees the one login rather than an error.
 */
export async function goToServiceAction (
  router: Pick<NextRouter, 'push'>,
  opts: { destination?: string; action?: PendingServiceAction } = {},
): Promise<void> {
  const destination = opts.destination ?? CHECKOUT_PATH;
  if ( opts.action ) stashPendingAction( opts.action );

  let signedIn = getSession() !== null;
  if ( !signedIn ) {
    try { signedIn = ( await restoreSession() ) !== null; } catch { signedIn = false; }
  }

  if ( signedIn ) {
    await router.push( destination );
    return;
  }
  // The ONE login, returning to the SAME destination. encodeURIComponent so the path is a clean
  // single query value; safeLocalReturnPath re-validates it on arrival and only honours an
  // allowlisted local path, which `/cart/` is.
  await router.push( `${SIGN_IN_PATH}?return=${encodeURIComponent( destination )}` );
}
