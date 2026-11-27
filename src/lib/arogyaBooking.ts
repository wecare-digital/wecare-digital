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
