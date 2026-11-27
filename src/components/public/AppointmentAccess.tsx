import React, { useCallback, useEffect, useState } from 'react';
import { clearSession, getSession, restoreSession } from '../../lib/customerAuth';
import { appointmentDraftAction, AppointmentApiError } from '../../lib/arogyaBooking';
import bookingConfig from '../../content/arogyaBookingConfig.json';
import AppointmentPlanner from './AppointmentPlanner';
import PublicNotice from './PublicNotice';
import styles from './AppointmentPlanner.module.css';

export const APPOINTMENT_AUTH_URL = '/auth?return=%2Felsewhere%2Farogya-yatra%2F';

/** Never mount patient fields until the owning API confirms a verified customer. */
export default function AppointmentAccess (): React.ReactElement {
  const [ ready, setReady ] = useState( false );
  const [ accountKey, setAccountKey ] = useState( '' );
  const [ error, setError ] = useState( '' );
  const [ attempt, setAttempt ] = useState( 0 );
  const signIn = useCallback( () => {
    setReady( false );
    window.location.replace( APPOINTMENT_AUTH_URL );
  }, [] );
  const accountChanged = useCallback( () => {
    setReady( false ); setAccountKey( '' ); setAttempt( value => value + 1 );
  }, [] );
  const sessionExpired = useCallback( () => {
    clearSession();
    signIn();
  }, [ signIn ] );

  useEffect( () => {
    let active = true;
    let inFlight = false;
    let expiry: ReturnType<typeof setTimeout> | undefined;
    const check = async () => {
      if ( !active || inFlight ) return;
      inFlight = true;
      if ( expiry ) clearTimeout( expiry );
      try {
        const session = getSession() || await restoreSession();
        if ( !active ) return;
        if ( !session ) { signIn(); return; }
        // Access is independent of price or provider availability.
        const access = await appointmentDraftAction( bookingConfig.endpoint, session.accessToken, { action: 'access' } );
        if ( access.phoneVerified !== true || typeof access.accountKey !== 'string' || !/^[a-f0-9]{64}$/.test( access.accountKey ) ) throw new Error( 'Customer verification unavailable.' );
        if ( !active ) return;
        setAccountKey( access.accountKey ); setError( '' ); setReady( true );
        // Refresh the shared session instead of revoking it at an access-token deadline.
        expiry = setTimeout( () => { void check(); }, Math.max( 1000, session.expiresAt - Date.now() - 25000 ) );
      } catch ( failure ) {
        if ( !active ) return;
        setReady( false );
        if ( failure instanceof AppointmentApiError && [ 401, 403 ].includes( failure.status ) ) {
          sessionExpired(); return;
        }
        setError( 'Appointment access is temporarily unavailable. Please try again.' );
      } finally {
        inFlight = false;
      }
    };
    const verifyOnReturn = () => {
      if ( document.visibilityState === 'visible' ) void check();
    };
    void check();
    window.addEventListener( 'focus', verifyOnReturn );
    const storageChanged = ( event: StorageEvent ) => {
      if ( event.key === 'wecare.customer.sessionHint' || event.key === null ) accountChanged();
    };
    window.addEventListener( 'storage', storageChanged );
    document.addEventListener( 'visibilitychange', verifyOnReturn );
    return () => {
      active = false; if ( expiry ) clearTimeout( expiry );
      window.removeEventListener( 'focus', verifyOnReturn );
      window.removeEventListener( 'storage', storageChanged );
      document.removeEventListener( 'visibilitychange', verifyOnReturn );
    };
  }, [ attempt, signIn, sessionExpired, accountChanged ] );

  if ( ready ) return <AppointmentPlanner key={ accountKey } accountKey={ accountKey } onAccountChanged={ accountChanged } onSessionExpired={ sessionExpired } />;
  return <section className={ styles.planner } aria-label="Appointment access">
    <h2>Request an appointment</h2>
    { error ? <>
      <PublicNotice mode="inline" tone="error" message={ error } />
      <div className={ styles.actions }><button type="button" onClick={ () => { setError( '' ); setAttempt( value => value + 1 ); } }>Try again</button></div>
    </> : <p role="status">Checking your WhatsApp-verified account…</p> }
    <div className={ styles.actions }><button type="button" className={ styles.primary } onClick={ signIn }>Sign in with WhatsApp</button></div>
  </section>;
}
