import React, { useState } from 'react';
import { getSession, restoreSession } from '../../lib/customerAuth';
import { AppointmentApiError, appointmentDraftAction, type SavedAppointmentDraft } from '../../lib/arogyaBooking';
import type { AppointmentPlan } from '../../lib/appointmentPlan';
import PublicNotice from './PublicNotice';
import bookingConfig from '../../content/arogyaBookingConfig.json';
import styles from './AppointmentPlanner.module.css';

interface Props {
  plan: AppointmentPlan;
  canSave: boolean;
  onLoad: ( plan: AppointmentPlan ) => void;
  onSessionExpired: () => void;
}

const ENDPOINT = bookingConfig.endpoint;
type Intent = { action: 'save' | 'list' } | { action: 'get' | 'delete'; draftId: string };

/** Patient details stay in memory until the customer explicitly chooses Save. */
export default function SavedAppointmentDrafts ( { plan, canSave, onLoad, onSessionExpired }: Props ): React.ReactElement | null {
  const [ busy, setBusy ] = useState( false );
  const [ error, setError ] = useState( '' );
  const [ notice, setNotice ] = useState( '' );
  const [ references, setReferences ] = useState<SavedAppointmentDraft[] | null>( null );
  const [ current, setCurrent ] = useState<SavedAppointmentDraft | null>( null );
  if ( !ENDPOINT ) return null;

  async function perform ( intent: Intent ): Promise<void> {
    setBusy( true ); setError( '' ); setNotice( '' );
    try {
      const session = getSession() || await restoreSession();
      if ( !session ) { onSessionExpired(); return; }
      if ( intent.action === 'save' ) {
        const reference = current?.draftId || crypto.randomUUID();
        const result = await appointmentDraftAction( ENDPOINT, session.accessToken, {
          action: 'save', draftId: reference, revision: current?.revision || 0, plan,
        } );
        if ( !result.draft ) throw new Error( 'The server did not return a saved draft.' );
        setCurrent( result.draft );
        setNotice( 'Draft saved to your account for 30 days. No Apollo appointment has been booked and no payment has been taken.' );
      } else if ( intent.action === 'list' ) {
        const result = await appointmentDraftAction( ENDPOINT, session.accessToken, { action: 'list' } );
        setReferences( result.drafts || [] );
      } else if ( 'draftId' in intent ) {
        const result = await appointmentDraftAction( ENDPOINT, session.accessToken, intent );
        if ( intent.action === 'get' ) {
          if ( !result.draft?.plan ) throw new Error( 'This draft is no longer available.' );
          setCurrent( result.draft ); onLoad( result.draft.plan ); setReferences( null );
          setNotice( 'Saved draft opened. Provider availability still needs confirmation.' );
        } else {
          setReferences( items => items?.filter( item => item.draftId !== intent.draftId ) || [] );
          if ( current?.draftId === intent.draftId ) setCurrent( null );
          setNotice( 'Saved draft deleted from your account. Any details open in this form remain until you clear it.' );
        }
      }
    } catch ( failure ) {
      if ( failure instanceof AppointmentApiError && [ 401, 403 ].includes( failure.status ) ) { onSessionExpired(); return; }
      setError( failure instanceof Error ? failure.message : 'Please try again.' );
    }
    finally { setBusy( false ); }
  }

  return <div className={ styles.panel } aria-label="Saved appointment drafts">
    <div className={ styles.actions }>
      { canSave && <button type="button" disabled={ busy } onClick={ () => { void perform( { action: 'save' } ); } }>{ busy ? 'Please wait…' : 'Save draft to my account' }</button> }
      <button type="button" disabled={ busy } onClick={ () => { void perform( { action: 'list' } ); } }>My saved drafts</button>
    </div>
    { references && <div><p>{ references.length ? 'Choose a saved draft. Drafts expire 30 days after the last save.' : 'You have no saved drafts.' }</p>
      { references.map( item => <div key={ item.draftId } className={ styles.actions }>
        <button disabled={ busy } type="button" onClick={ () => { void perform( { action: 'get', draftId: item.draftId } ); } }>Open draft saved { new Date( item.updatedAt * 1000 ).toLocaleString( 'en-IN', { timeZone: 'Asia/Kolkata' } ) } IST</button>
        <button disabled={ busy } type="button" onClick={ () => { void perform( { action: 'delete', draftId: item.draftId } ); } }>Delete saved draft</button>
      </div> ) }
    </div> }
    { notice && <PublicNotice mode="inline" tone="success" message={ notice } /> }
    { error && <PublicNotice mode="inline" tone="error" message={ error } /> }
  </div>;
}
