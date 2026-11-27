import type { AppointmentPlan } from './appointmentPlan';

export interface SavedAppointmentDraft {
  draftId: string;
  status: 'DRAFT';
  revision: number;
  createdAt: number;
  updatedAt: number;
  expiresAt: number;
  plan?: AppointmentPlan;
}

export class AppointmentApiError extends Error {
  readonly status: number;
  constructor ( message: string, status: number ) { super( message ); this.status = status; }
}

/** Exact deployment URL comes from the public deployment configuration; no patient data goes in a URL. */
export async function appointmentDraftAction (
  endpoint: string, token: string, body: Record<string, unknown>,
): Promise<{ draft?: SavedAppointmentDraft; drafts?: SavedAppointmentDraft[]; deleted?: boolean }> {
  if ( !/^https:\/\/[a-z0-9-]+\.lambda-url\.us-east-1\.on\.aws\/$/.test( endpoint ) ) throw new Error( 'Saved appointments are not available yet.' );
  const response = await fetch( endpoint, {
    method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${ token }` },
    body: JSON.stringify( body ), cache: 'no-store', credentials: 'omit',
    signal: AbortSignal.timeout( 20000 ),
  } );
  let value: { error?: string; draft?: SavedAppointmentDraft; drafts?: SavedAppointmentDraft[]; deleted?: boolean };
  try { value = await response.json(); }
  catch { throw new AppointmentApiError( 'Appointment storage is temporarily unavailable. Check My saved drafts before saving again.', response.status ); }
  if ( !response.ok ) throw new AppointmentApiError( typeof value.error === 'string' ? value.error : 'Appointment storage is temporarily unavailable. Please try again.', response.status );
  return value;
}

export type ApolloCatalogKind = 'hospitals' | 'specialities' | 'doctors' | 'healthChecks' | 'dates';
export interface ApolloCatalogOption { id: string; label: string; city?: string }

/** The authenticated backend is the only source of provider catalogue data. */
export async function appointmentCatalogAction (
  endpoint: string, token: string, kind: ApolloCatalogKind,
  selection: { hospitalId?: string; specialityId?: string; doctorId?: string; healthCheckId?: string },
  signal: AbortSignal,
): Promise<ApolloCatalogOption[]> {
  if ( !/^https:\/\/[a-z0-9-]+\.lambda-url\.us-east-1\.on\.aws\/$/.test( endpoint ) ) throw new Error( 'Live appointment availability is not configured.' );
  const response = await fetch( endpoint, {
    method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${ token }` },
    body: JSON.stringify( { action: 'catalog', kind, ...selection } ), cache: 'no-store', credentials: 'omit',
    signal: AbortSignal.any( [ signal, AbortSignal.timeout( 20000 ) ] ),
  } );
  if ( !response.ok ) throw new AppointmentApiError( 'Live appointment choices are temporarily unavailable.', response.status );
  const data = await response.json() as { options?: unknown };
  if ( !Array.isArray( data.options ) || !data.options.every( ( value: unknown ) => {
    if ( !value || typeof value !== 'object' ) return false;
    const option = value as Partial<ApolloCatalogOption>;
    return typeof option.id === 'string' && ( kind === 'dates' ? /^\d{4}-\d{2}-\d{2}$/.test( option.id ) : /^[1-9]\d{0,9}$/.test( option.id ) ) &&
      typeof option.label === 'string' && !!option.label.trim() && option.label.length <= 120 &&
      ( option.city === undefined || ( typeof option.city === 'string' && option.city.length <= 80 ) );
  } ) ) throw new Error( 'Live appointment choices could not be verified.' );
  const options = data.options as ApolloCatalogOption[];
  if ( new Set( options.map( option => option.id ) ).size !== options.length ) throw new Error( 'Live appointment choices could not be verified.' );
  return options;
}
