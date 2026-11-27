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

/** Exact deployment URL comes from the public deployment configuration; no patient data goes in a URL. */
export async function appointmentDraftAction (
  endpoint: string, token: string, body: Record<string, unknown>,
): Promise<{ draft?: SavedAppointmentDraft; drafts?: SavedAppointmentDraft[]; deleted?: boolean }> {
  if ( !/^https:\/\/[a-z0-9]+\.lambda-url\.us-east-1\.on\.aws\/$/.test( endpoint ) ) throw new Error( 'Saved appointments are not available yet.' );
  const response = await fetch( endpoint, {
    method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${ token }` },
    body: JSON.stringify( body ), cache: 'no-store', credentials: 'omit',
    signal: AbortSignal.timeout( 20000 ),
  } );
  const value = await response.json() as { error?: string; draft?: SavedAppointmentDraft; drafts?: SavedAppointmentDraft[]; deleted?: boolean };
  if ( !response.ok ) throw new Error( value.error || 'Could not save your appointment. Please try again.' );
  return value;
}
