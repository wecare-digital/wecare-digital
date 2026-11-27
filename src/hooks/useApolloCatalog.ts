import { useEffect, useState } from 'react';
import { appointmentCatalogAction, AppointmentApiError, type ApolloCatalogKind, type ApolloCatalogOption } from '../lib/arogyaBooking';
import { getSession, restoreSession } from '../lib/customerAuth';
import bookingConfig from '../content/arogyaBookingConfig.json';

type Selection = { hospitalId?: string; specialityId?: string; doctorId?: string; healthCheckId?: string };
interface Result { key: string; options: ApolloCatalogOption[]; error: string }
const EMPTY: ApolloCatalogOption[] = [];

/** Keep an old response invisible when any parent selection changes. */
export function useApolloChoices (
  kind: ApolloCatalogKind, selection: Selection, enabled: boolean, retry: number,
  onSessionExpired: () => void,
): { options: ApolloCatalogOption[]; loading: boolean; error: string } {
  const { hospitalId = '', specialityId = '', doctorId = '', healthCheckId = '' } = selection;
  const key = enabled ? JSON.stringify( [ kind, hospitalId, specialityId, doctorId, healthCheckId, retry ] ) : '';
  const [ result, setResult ] = useState<Result | null>( null );

  useEffect( () => {
    if ( !key ) return;
    const controller = new AbortController();
    const run = async () => {
      try {
        const session = getSession() || await restoreSession();
        if ( controller.signal.aborted ) return;
        if ( !session ) { onSessionExpired(); return; }
        const options = await appointmentCatalogAction( bookingConfig.endpoint, session.accessToken, kind,
          { ...( hospitalId ? { hospitalId } : {} ), ...( specialityId ? { specialityId } : {} ),
            ...( doctorId ? { doctorId } : {} ), ...( healthCheckId ? { healthCheckId } : {} ) }, controller.signal );
        if ( !controller.signal.aborted ) setResult( { key, options, error: '' } );
      } catch ( failure ) {
        if ( controller.signal.aborted ) return;
        if ( failure instanceof AppointmentApiError && [ 401, 403 ].includes( failure.status ) ) {
          onSessionExpired(); return;
        }
        setResult( { key, options: [], error: 'Live Apollo choices are temporarily unavailable. Try again.' } );
      }
    };
    void run();
    return () => controller.abort();
  }, [ key, kind, hospitalId, specialityId, doctorId, healthCheckId, onSessionExpired ] );

  return { options: key && result?.key === key ? result.options : EMPTY,
    loading: !!key && result?.key !== key, error: key && result?.key === key ? result.error : '' };
}
