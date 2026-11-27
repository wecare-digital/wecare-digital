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

export interface ApolloOption { id: number; label: string; city?: string; }
export interface ApolloCatalogResponse {
  status?: 'ready' | 'renewing';
  retryAfter?: number;
  observedAt?: number;
  data?: Record<string, ApolloOption[] | string[]>;
}

export class AppointmentApiError extends Error {
  readonly status: number;
  constructor ( message: string, status: number ) { super( message ); this.status = status; }
}

/** Exact deployment URL comes from the public deployment configuration; no patient data goes in a URL. */
export async function appointmentDraftAction (
  endpoint: string, token: string, body: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<{ draft?: SavedAppointmentDraft; drafts?: SavedAppointmentDraft[]; deleted?: boolean } & ApolloCatalogResponse> {
  if ( !/^https:\/\/[a-z0-9-]+\.lambda-url\.us-east-1\.on\.aws\/$/.test( endpoint ) ) throw new Error( 'Saved appointments are not available yet.' );
  const controller = new AbortController();
  const cancel = (): void => controller.abort();
  signal?.addEventListener( 'abort', cancel, { once: true } );
  if ( signal?.aborted ) controller.abort();
  const timeout = setTimeout( cancel, body.action === 'catalog' ? 55000 : 20000 );
  try {
  const response = await fetch( endpoint, {
    method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${ token }` },
    body: JSON.stringify( body ), cache: 'no-store', credentials: 'omit',
    signal: controller.signal,
  } );
  let value: { error?: string; draft?: SavedAppointmentDraft; drafts?: SavedAppointmentDraft[]; deleted?: boolean } & ApolloCatalogResponse;
  try { value = await response.json(); }
  catch { throw new AppointmentApiError( 'Appointment storage is temporarily unavailable. Check My saved drafts before saving again.', response.status ); }
  if ( !value || typeof value !== 'object' ) throw new AppointmentApiError( 'Appointment choices could not be loaded. Please try again.', response.status );
  if ( !response.ok ) throw new AppointmentApiError( typeof value.error === 'string' ? value.error : 'Appointment storage is temporarily unavailable. Please try again.', response.status );
  return value;
  } finally { clearTimeout( timeout ); signal?.removeEventListener( 'abort', cancel ); }
}
