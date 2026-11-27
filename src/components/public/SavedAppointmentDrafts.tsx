import React, { useEffect, useRef, useState } from 'react';
import { getSession, restoreSession } from '../../lib/customerAuth';
import { AppointmentApiError, appointmentDraftAction, type SavedAppointmentDraft } from '../../lib/arogyaBooking';
import type { AppointmentPlan } from '../../lib/appointmentPlan';
import PublicNotice from './PublicNotice';
import bookingConfig from '../../content/arogyaBookingConfig.json';
import styles from './AppointmentPlanner.module.css';

interface Props {
  accountKey: string;
  onAccountChanged: () => void;
  plan: AppointmentPlan;
  canSave: boolean;
  onLoad: ( plan: AppointmentPlan ) => void;
  onSessionExpired: () => void;
}

const ENDPOINT = bookingConfig.endpoint;
type Intent = { action: 'save' } | { action: 'list'; after?: string } | { action: 'get' | 'delete'; draftId: string };

/** Patient details stay in memory until the customer explicitly chooses Save. */
export default function SavedAppointmentDrafts ( { accountKey, onAccountChanged, plan, canSave, onLoad, onSessionExpired }: Props ): React.ReactElement | null {
  const [ busy, setBusy ] = useState( false );
  const [ error, setError ] = useState( '' );
  const [ notice, setNotice ] = useState( '' );
  const [ references, setReferences ] = useState<SavedAppointmentDraft[] | null>( null );
  const [ current, setCurrent ] = useState<SavedAppointmentDraft | null>( null );
  const [ nextAfter, setNextAfter ] = useState<string | null>( null );
  const pendingSave = useRef<{ draftId: string; revision: number; plan: AppointmentPlan } | null>( null );
  const busyRef = useRef( false );
  const active = useRef( false );
  useEffect( () => { active.current = true; return () => { active.current = false; }; }, [] );
  if ( !ENDPOINT ) return null;

  async function perform ( intent: Intent ): Promise<void> {
    if ( busyRef.current || !active.current ) return;
    busyRef.current = true;
    setBusy( true ); setError( '' ); setNotice( '' );
    let requestToken = '';
    try {
      const session = getSession() || await restoreSession();
      if ( !active.current ) return;
      if ( !session ) { onSessionExpired(); return; }
      requestToken = session.accessToken;
      if ( intent.action === 'save' ) {
        // A network timeout is not proof that a write failed. Preserve the
        // same reference, revision and exact payload until the result is known.
        if ( pendingSave.current && JSON.stringify( pendingSave.current.plan ) !== JSON.stringify( plan ) ) {
          throw new Error( 'The previous save has not been verified. Open My saved drafts before saving edited details.' );
        }
        const request = pendingSave.current || {
          draftId: current?.draftId || crypto.randomUUID(), revision: current?.revision || 0,
          plan: { ...plan },
        };
        pendingSave.current = request;
        const result = await appointmentDraftAction( ENDPOINT, requestToken, { action: 'save', accountKey, ...request } );
        if ( !active.current ) return;
        if ( !result.draft || result.draft.draftId !== request.draftId ||
          result.draft.revision !== request.revision + 1 ) throw new Error( 'The server did not return the expected saved draft.' );
        const { plan: _storedPlan, ...metadata } = result.draft;
        pendingSave.current = null;
        setCurrent( metadata );
        setNotice( 'Draft saved to your account for 30 days. No Apollo appointment has been booked and no payment has been taken.' );
      } else if ( intent.action === 'list' ) {
        const result = await appointmentDraftAction( ENDPOINT, requestToken, {
          action: 'list', accountKey, ...( intent.after ? { after: intent.after } : {} ),
        } );
        if ( !active.current ) return;
        setReferences( previous => intent.after
          ? [ ...( previous || [] ), ...( result.drafts || [] ).filter( item => !previous?.some( prior => prior.draftId === item.draftId ) ) ]
          : ( result.drafts || [] ) );
        setNextAfter( result.nextAfter || null );
      } else {
        const result = await appointmentDraftAction( ENDPOINT, requestToken, { ...intent, accountKey } );
        if ( !active.current ) return;
        if ( intent.action === 'get' ) {
          if ( !result.draft?.plan ) throw new Error( 'This draft is no longer available.' );
          const { plan: saved, ...metadata } = result.draft;
          pendingSave.current = null;
          setCurrent( metadata ); onLoad( saved ); setReferences( null ); setNextAfter( null );
          setNotice( 'Saved draft opened. Provider availability still needs confirmation.' );
        } else {
          if ( result.deleted !== true ) throw new Error( 'Draft deletion could not be verified.' );
          setReferences( items => items?.filter( item => item.draftId !== intent.draftId ) || [] );
          if ( current?.draftId === intent.draftId ) setCurrent( null );
          if ( pendingSave.current?.draftId === intent.draftId ) pendingSave.current = null;
          setNotice( 'Saved draft deleted from your account. Any details open in this form remain until you clear it.' );
        }
      }
    } catch ( failure ) {
      if ( !active.current ) return;
      if ( failure instanceof AppointmentApiError ) {
        if ( failure.code === 'ACCOUNT_CHANGED' ) { onAccountChanged(); return; }
        if ( [ 401, 403 ].includes( failure.status ) ) {
          // A response for an older token must not log out a newer login.
          if ( requestToken && getSession()?.accessToken !== requestToken ) onAccountChanged();
          else onSessionExpired();
          return;
        }
        if ( intent.action === 'save' && failure.status === 400 ) pendingSave.current = null;
      }
      setError( failure instanceof Error ? failure.message : 'Please try again.' );
    }
    finally {
      busyRef.current = false;
      if ( active.current ) setBusy( false );
    }
  }

  return <div className={ styles.panel } aria-label="Saved appointment drafts">
    <div className={ styles.actions }>
      { canSave && <button type="button" disabled={ busy } onClick={ () => { void perform( { action: 'save' } ); } }>{ busy ? 'Please wait…' : 'Save draft to my account' }</button> }
      <button type="button" disabled={ busy } onClick={ () => { void perform( { action: 'list' } ); } }>My saved drafts</button>
    </div>
    { references && <div><p>{ references.length ? 'Choose a saved draft. Drafts expire 30 days after the last save.' : nextAfter ? 'No current drafts on this page. More drafts may be available.' : 'You have no saved drafts.' }</p>
      { references.map( item => <div key={ item.draftId } className={ styles.actions }>
        <button disabled={ busy } type="button" onClick={ () => { void perform( { action: 'get', draftId: item.draftId } ); } }>Open draft saved { new Date( item.updatedAt * 1000 ).toLocaleString( 'en-IN', { timeZone: 'Asia/Kolkata' } ) } IST</button>
        <button disabled={ busy } type="button" onClick={ () => { void perform( { action: 'delete', draftId: item.draftId } ); } }>Delete saved draft</button>
      </div> ) }
      { nextAfter && <button type="button" disabled={ busy } onClick={ () => { void perform( { action: 'list', after: nextAfter } ); } }>Load more drafts</button> }
    </div> }
    { notice && <PublicNotice mode="inline" tone="success" message={ notice } /> }
    { error && <PublicNotice mode="inline" tone="error" message={ error } /> }
  </div>;
}
