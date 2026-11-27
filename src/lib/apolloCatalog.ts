import { getSession, restoreSession } from './customerAuth';
import { AppointmentApiError, appointmentDraftAction, type ApolloCatalogResponse, type ApolloOption } from './arogyaBooking';
import config from '../content/arogyaBookingConfig.json';

export function catalogOptions ( data: ApolloCatalogResponse['data'], key: string ): ApolloOption[] {
  const rows = data?.[key];
  if ( !Array.isArray( rows ) ) throw new Error( 'Appointment choices could not be loaded.' );
  return rows.filter( ( row ): row is ApolloOption => typeof row === 'object' && row !== null && Number.isInteger( row.id ) && typeof row.label === 'string' );
}

export async function readLiveCatalog ( body: Record<string, unknown>, signal: AbortSignal ): Promise<ApolloCatalogResponse> {
  for ( let attempt = 0; attempt < 20; attempt++ ) {
    if ( signal.aborted ) throw new DOMException( 'Cancelled', 'AbortError' );
    const session = getSession() || await restoreSession();
    if ( !session ) throw new AppointmentApiError( 'Sign in to continue.', 401 );
    const result = await appointmentDraftAction( config.endpoint, session.accessToken, { ...body, action: 'catalog' }, signal );
    if ( result.status === 'ready' && result.data ) return result;
    if ( result.status !== 'renewing' ) throw new Error( 'Live appointment choices are unavailable. Please try again.' );
    await new Promise<void>( ( resolve, reject ) => {
      const stop = (): void => { clearTimeout( timer ); reject( new DOMException( 'Cancelled', 'AbortError' ) ); };
      const timer = setTimeout( () => { signal.removeEventListener( 'abort', stop ); resolve(); }, Math.max( 2, Math.min( result.retryAfter || 3, 60 ) ) * 1000 );
      signal.addEventListener( 'abort', stop, { once: true } );
      if ( signal.aborted ) stop();
    } );
  }
  throw new Error( 'Live appointment choices are taking longer than expected. Please try again.' );
}
