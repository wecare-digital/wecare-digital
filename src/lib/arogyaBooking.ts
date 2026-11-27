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
): Promise<{ draft?: SavedAppointmentDraft; drafts?: SavedAppointmentDraft[]; deleted?: boolean; phoneVerified?: boolean }> {
  if ( !/^https:\/\/[a-z0-9-]+\.lambda-url\.us-east-1\.on\.aws\/$/.test( endpoint ) ) throw new Error( 'Saved appointments are not available yet.' );
  const response = await fetch( endpoint, {
    method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${ token }` },
    body: JSON.stringify( body ), cache: 'no-store', credentials: 'omit',
    signal: AbortSignal.timeout( 20000 ),
  } );
  let value: { error?: string; draft?: SavedAppointmentDraft; drafts?: SavedAppointmentDraft[]; deleted?: boolean; phoneVerified?: boolean };
  try { value = await response.json(); }
  catch { throw new AppointmentApiError( 'Appointment storage is temporarily unavailable. Check My saved drafts before saving again.', response.status ); }
  if ( !response.ok ) throw new AppointmentApiError( typeof value.error === 'string' ? value.error : 'Appointment storage is temporarily unavailable. Please try again.', response.status );
  return value;
}

export type ApolloCatalogKind = 'hospitals' | 'specialities' | 'doctors' | 'healthChecks' | 'dates' | 'appointmentTypes' | 'salutations' | 'times';
export interface ApolloCatalogOption { id: string; label: string; city?: string }

type CatalogResponse = { status: 'ready'; options: ApolloCatalogOption[] } | { status: 'renewing'; retryAfter: number };

function waitForProvider ( milliseconds: number, signal: AbortSignal ): Promise<void> {
  return new Promise( ( resolve, reject ) => {
    if ( signal.aborted ) { reject( new Error( 'Cancelled' ) ); return; }
    const abort = () => { clearTimeout( timer ); reject( new Error( 'Cancelled' ) ); };
    const timer = setTimeout( () => { signal.removeEventListener( 'abort', abort ); resolve(); }, milliseconds );
    signal.addEventListener( 'abort', abort, { once: true } );
  } );
}

/** A single request with explicit timeout and parent cancellation, including older mobile browsers. */
export async function requestApolloCatalog (
  endpoint: string, token: string, kind: ApolloCatalogKind,
  selection: { hospitalId?: string; specialityId?: string; doctorId?: string; healthCheckId?: string },
  signal: AbortSignal, timeoutMs = 65000,
): Promise<CatalogResponse> {
  if ( !/^https:\/\/[a-z0-9-]+\.lambda-url\.us-east-1\.on\.aws\/$/.test( endpoint ) ) throw new Error( 'Live appointment availability is not configured.' );
  const controller = new AbortController();
  const cancel = () => controller.abort();
  const timer = setTimeout( cancel, timeoutMs );
  if ( signal.aborted ) cancel();
  signal.addEventListener( 'abort', cancel, { once: true } );
  try {
    const response = await fetch( endpoint, {
      method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${ token }` },
      body: JSON.stringify( { action: 'catalog', kind, ...selection } ), cache: 'no-store', credentials: 'omit',
      signal: controller.signal,
    } );
    if ( !response.ok ) throw new AppointmentApiError( 'Live appointment choices are temporarily unavailable.', response.status );
    const data = await response.json() as { options?: unknown; status?: unknown; retryAfter?: unknown; preferredOnly?: unknown };
    if ( response.status === 202 ) {
      if ( data.status !== 'renewing' || typeof data.retryAfter !== 'number' || !Number.isInteger( data.retryAfter ) ||
        data.retryAfter < 2 || data.retryAfter > 60 ) throw new Error( 'Invalid appointment availability response.' );
      return { status: 'renewing', retryAfter: data.retryAfter };
    }
    if ( kind === 'times' && data.preferredOnly !== true ) throw new Error( 'Appointment time choices could not be verified.' );
    if ( response.status !== 200 || !Array.isArray( data.options ) || !data.options.every( ( value: unknown ) => {
      if ( !value || typeof value !== 'object' ) return false;
      const option = value as Partial<ApolloCatalogOption>;
      const validId = kind === 'dates' ? /^\d{4}-\d{2}-\d{2}$/ : kind === 'times'
        ? /^(?:0[1-9]|1\d|2[0-3]):(?:00|05|10|15|20|25|30|35|40|45|50|55)$/ : /^[1-9]\d{0,9}$/;
      return typeof option.id === 'string' && validId.test( option.id ) &&
        typeof option.label === 'string' && !!option.label.trim() && option.label.length <= 120 &&
        ( kind !== 'times' || option.id === option.label ) &&
        ( option.city === undefined || ( typeof option.city === 'string' && option.city.length <= 80 ) );
    } ) ) throw new Error( 'Live appointment choices could not be verified.' );
    const options = data.options as ApolloCatalogOption[];
    if ( new Set( options.map( option => option.id ) ).size !== options.length ) throw new Error( 'Live appointment choices could not be verified.' );
    return { status: 'ready', options };
  } finally {
    clearTimeout( timer );
    signal.removeEventListener( 'abort', cancel );
  }
}

/** Poll only a server-declared renewal, while the customer is actively requesting choices.
 * No automatic retry of errors, no timers after unmount, and no unbounded background polling.
 */
export async function appointmentCatalogAction (
  endpoint: string, token: string, kind: ApolloCatalogKind,
  selection: { hospitalId?: string; specialityId?: string; doctorId?: string; healthCheckId?: string },
  signal: AbortSignal,
): Promise<ApolloCatalogOption[]> {
  const deadline = Date.now() + 120000;
  for ( let attempt = 0; attempt < 8 && !signal.aborted; attempt += 1 ) {
    const remaining = deadline - Date.now();
    if ( remaining <= 0 ) break;
    const response = await requestApolloCatalog( endpoint, token, kind, selection, signal, Math.min( 65000, remaining ) );
    if ( response.status === 'ready' ) return response.options;
    const delay = response.retryAfter * 1000;
    if ( Date.now() + delay >= deadline ) break;
    await waitForProvider( delay, signal );
  }
  throw new Error( 'Live appointment choices are temporarily unavailable. Try again.' );
}
