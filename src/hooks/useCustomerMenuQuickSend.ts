/**
 * Fast explicit-click path for the non-payment customer WhatsApp menu actions.
 *
 * If a customer already has a live access token, do not navigate to /orders/
 * just to send the invitation. On a missing/expired token, preserve the
 * existing one-use Orders -> /auth handoff. This path never retries or sends
 * from a URL, page view, prefetch or background effect.
 */
import { useCallback, useEffect, useRef, useState } from 'react';

import { useOptionalPublicToast } from '../components/public/PublicToastProvider';
import { useOptionalToastContext } from '../contexts/ToastContext';
import { customerMenuNotice } from '../lib/customerMenuNotices';
import { sendCustomerMenuAction, stashCustomerMenuAction, takeCustomerMenuAction } from '../lib/customerMenuActions';
import type { CustomerMenuAction } from '../lib/customerMenuActions';

// Header and Stay connected can coexist in one tree. A second tap anywhere
// on that tree must not send a second Meta invitation while one is in flight.
let quickSendInFlight = false;

export function useCustomerMenuQuickSend () {
  const publicToast = useOptionalPublicToast();
  const workspaceToast = useOptionalToastContext();
  const [ error, setError ] = useState( '' );
  const [ busy, setBusy ] = useState( false );
  const mounted = useRef( false );

  useEffect( () => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, [] );

  const dismissError = useCallback( () => setError( '' ), [] );

  const start = useCallback( ( action: CustomerMenuAction ): boolean => {
    // Contribute initiates payment and must remain on the exact Orders/Commerce
    // route with its existing amount, consent and reconciliation rules.
    if ( action === 'contribute' || typeof window === 'undefined' ) return false;
    if ( quickSendInFlight ) return true;
    quickSendInFlight = true;
    setBusy( true );
    setError( '' );
    const pendingToast = publicToast?.showToast( 'processing', { durationMs: 0 } ) || 0;
    if ( !publicToast ) workspaceToast?.info( customerMenuNotice( 'pending' ).message );

    void ( async () => {
      try {
        // Dynamic import keeps customer Cognito/auth code out of every public
        // page's initial JS. Only this real click can load the helper.
        const { getSession, clearSession } = await import( '../lib/customerAuth' );
        const session = getSession();
        if ( !session ) {
          // No API request has happened: the original one-use handoff is safe.
          publicToast?.hideToast( pendingToast );
          stashCustomerMenuAction( action );
          window.location.assign( '/orders/' );
          return;
        }
        // A newer direct click supersedes any previously queued but unsent
        // one-use menu intent from an interrupted navigation in this tab.
        // Otherwise opening Orders later could unexpectedly send the old one.
        void takeCustomerMenuAction();
        const outcome = await sendCustomerMenuAction( action, session.accessToken );
        if ( !mounted.current ) return;
        if ( outcome.kind === 'expired' ) {
          // A 401 is a definitive *authorization refusal*, not Meta acceptance.
          // Clear the unusable token BEFORE the auth handoff: going to Orders
          // with the same token would immediately replay this one-use action.
          // No send occurs again until the customer completes fresh sign-in.
          publicToast?.hideToast( pendingToast );
          clearSession();
          stashCustomerMenuAction( action );
          window.location.assign( '/auth?return=/orders/' );
          return;
        }
        if ( outcome.kind === 'accepted' ) {
          // Accepted by Meta is not delivered, read, or Flow completed.
          if ( publicToast ) publicToast.showToast( 'whatsappAccepted', { ownerId: pendingToast } );
          else workspaceToast?.success( customerMenuNotice( 'accepted' ).message );
          return;
        }
        // Ambiguous and blocked results remain visible until dismissal;
        // WhatsApp failures are never self-clearing success-style toasts.
        publicToast?.hideToast( pendingToast );
        setError( customerMenuNotice( outcome.kind ).message );
      } catch {
        if ( mounted.current ) {
          publicToast?.hideToast( pendingToast );
          setError( customerMenuNotice( 'failed' ).message );
        }
      } finally {
        quickSendInFlight = false;
        if ( mounted.current ) setBusy( false );
      }
    } )();
    return true;
  }, [ publicToast, workspaceToast ] );

  return { start, error, busy, dismissError };
}
