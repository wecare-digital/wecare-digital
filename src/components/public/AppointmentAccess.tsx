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
  const [ error, setError ] = useState( '' );
  const [ attempt, setAttempt ] = useState( 0 );
  const signIn = useCallback( () => {
    setReady( false );
    window.location.replace( APPOINTMENT_AUTH_URL );
  }, [] );
  const sessionExpired = useCallback( () => {
    clearSession();
    signIn();
  }, [ signIn ] );

  useEffect( () => {
    let active = true;
    let expiry: ReturnType<typeof setTimeout> | undefined;
    const check = async () => {
      try {
        const session = getSession() || await restoreSession();
        if ( !active ) return;
        if ( !session ) { signIn(); return; }
        // The existing quote action verifies Cognito identity and phone_verified
        // without reading or writing a patient record, charging or booking.
        await appointmentDraftAction( bookingConfig.endpoint, session.accessToken, { action: 'quote' } );
        if ( !active ) return;
        setError( '' ); setReady( true );
        expiry = setTimeout( sessionExpired, Math.max( 0, session.expiresAt - Date.now() - 30000 ) );
      } catch ( failure ) {
        if ( !active ) return;
        if ( failure instanceof AppointmentApiError && [ 401, 403 ].includes( failure.status ) ) {
          sessionExpired(); return;
        }
        setError( 'Appointment access is temporarily unavailable. Please try again.' );
      }
    };
    void check();
    return () => { active = false; if ( expiry ) clearTimeout( expiry ); };
  }, [ attempt, signIn, sessionExpired ] );

  if ( ready ) return <AppointmentPlanner onSessionExpired={ sessionExpired } />;
  return <section className={ styles.planner } aria-label="Appointment access">
    <h2>Request an appointment</h2>
    { error ? <>
      <PublicNotice mode="inline" tone="error" message={ error } />
      <div className={ styles.actions }><button type="button" onClick={ () => { setError( '' ); setAttempt( value => value + 1 ); } }>Try again</button></div>
    </> : <p role="status">Checking your WhatsApp-verified account…</p> }
    <div className={ styles.actions }><button type="button" className={ styles.primary } onClick={ signIn }>Sign in with WhatsApp</button></div>
  </section>;
}
