import React, { useCallback, useEffect, useState } from 'react';
import { clearSession, getSession, restoreSession } from '../../lib/customerAuth';
import { AppointmentApiError, appointmentDraftAction } from '../../lib/arogyaBooking';
import config from '../../content/arogyaBookingConfig.json';
import AppointmentPlanner from './AppointmentPlanner';
import PublicNotice from './PublicNotice';

export const APPOINTMENT_AUTH_URL = '/auth?return=%2Felsewhere%2Farogya-yatra%2F';

/** Never mount the patient form before the server has verified the customer session. */
export default function AppointmentAccess (): React.ReactElement {
  const [ verified, setVerified ] = useState( false );
  const [ error, setError ] = useState( '' );
  const [ attempt, setAttempt ] = useState( 0 );
  const signIn = useCallback( (): void => { clearSession(); setVerified( false ); window.location.replace( APPOINTMENT_AUTH_URL ); }, [] );

  useEffect( () => {
    let active = true;
    void ( async () => {
      try {
        const session = getSession() || await restoreSession();
        if ( !active ) return;
        if ( !session ) { window.location.replace( APPOINTMENT_AUTH_URL ); return; }
        await appointmentDraftAction( config.endpoint, session.accessToken, { action: 'quote' } );
        if ( active ) setVerified( true );
      } catch ( failure ) {
        if ( !active ) return;
        if ( failure instanceof AppointmentApiError && [ 401, 403 ].includes( failure.status ) ) {
          clearSession(); window.location.replace( APPOINTMENT_AUTH_URL );
        } else setError( 'We could not verify your account. Please try again.' );
      }
    } )();
    return () => { active = false; };
  }, [ attempt ] );

  if ( verified ) return <AppointmentPlanner onSessionExpired={ signIn } />;
  return <section aria-label="Appointment access" aria-busy={ !error }>
    { error ? <><PublicNotice mode="inline" tone="error" message={ error } /><button type="button" onClick={ () => { setError( '' ); setAttempt( value => value + 1 ); } }>Try again</button></> : <p role="status">Checking your account…</p> }
    <a href={ APPOINTMENT_AUTH_URL }>Sign in on WhatsApp</a>
  </section>;
}
