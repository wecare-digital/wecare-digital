import React, { useState } from 'react';
import { clearSession, getSession, restoreSession, requestOtp, submitOtp, nextSessionFrom, type CustomerSession } from '../../lib/customerAuth';
import { AppointmentApiError, appointmentDraftAction, type SavedAppointmentDraft } from '../../lib/arogyaBooking';
import type { AppointmentPlan } from '../../lib/appointmentPlan';
import PublicNotice from './PublicNotice';
import bookingConfig from '../../content/arogyaBookingConfig.json';
import styles from './AppointmentPlanner.module.css';

interface Props {
  plan: AppointmentPlan;
  canSave: boolean;
  onLoad: ( plan: AppointmentPlan ) => void;
}

const ENDPOINT = bookingConfig.endpoint;
type Intent = { action: 'save' | 'list' } | { action: 'get' | 'delete'; draftId: string };

/** Patient details stay in memory until the customer explicitly chooses Save. */
export default function SavedAppointmentDrafts ( { plan, canSave, onLoad }: Props ): React.ReactElement | null {
  const [ busy, setBusy ] = useState( false );
  const [ error, setError ] = useState( '' );
  const [ notice, setNotice ] = useState( '' );
  const [ references, setReferences ] = useState<SavedAppointmentDraft[] | null>( null );
  const [ current, setCurrent ] = useState<SavedAppointmentDraft | null>( null );
  const [ pending, setPending ] = useState<Intent | null>( null );
  const [ mobile, setMobile ] = useState( '' );
  const [ code, setCode ] = useState( '' );
  const [ challenge, setChallenge ] = useState( '' );
  const [ destination, setDestination ] = useState( '' );

  if ( !ENDPOINT ) return null;

  async function perform ( intent: Intent, signedIn?: CustomerSession ): Promise<void> {
    setBusy( true ); setError( '' ); setNotice( '' );
    try {
      const session = signedIn || getSession() || await restoreSession();
      if ( !session ) { setPending( intent ); return; }
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
      setPending( null );
    } catch ( failure ) {
      if ( failure instanceof AppointmentApiError && failure.status === 401 ) { clearSession(); setPending( intent ); }
      setError( failure instanceof Error ? failure.message : 'Please try again.' );
    }
    finally { setBusy( false ); }
  }

  async function authenticate ( event: React.FormEvent ): Promise<void> {
    event.preventDefault(); setBusy( true ); setError( '' );
    try {
      if ( !challenge ) {
        const result = await requestOtp( mobile );
        if ( !result.registered ) throw new Error( 'This number is not registered. Use the existing customer sign-up on the Sign in page, then return here.' );
        if ( !result.session ) throw new Error( 'Could not start WhatsApp verification. Please try again.' );
        setChallenge( result.session ); setDestination( result.destination );
      } else {
        const result = await submitOtp( mobile, code, challenge, false );
        if ( !result ) throw new Error( 'Check the code and try again.' );
        setChallenge( '' ); setCode( '' );
        await perform( pending || { action: 'list' }, result );
      }
    } catch ( failure ) {
      const next = nextSessionFrom( failure );
      if ( next ) setChallenge( next );
      setError( failure instanceof Error ? failure.message : 'Verification could not complete.' );
    } finally { setBusy( false ); }
  }

  return <div className={ styles.panel } aria-label="Saved appointment drafts">
    <div className={ styles.actions }>
      { canSave && <button type="button" disabled={ busy } onClick={ () => { void perform( { action: 'save' } ); } }>{ busy ? 'Please wait…' : 'Save draft to my account' }</button> }
      <button type="button" disabled={ busy } onClick={ () => { void perform( { action: 'list' } ); } }>My saved drafts</button>
    </div>
    { pending && <form onSubmit={ event => { void authenticate( event ); } }>
      <p>Verify your customer account using the existing WhatsApp sign-in. Your patient details stay on this page during verification.</p>
      <div className={ styles.fields }><label htmlFor="ay-signin-mobile">Your WhatsApp number
        <input id="ay-signin-mobile" type="tel" autoComplete="tel" required maxLength={ 16 } value={ mobile } disabled={ !!challenge || busy } onChange={ event => setMobile( event.target.value ) } />
      </label>
      { challenge && <label htmlFor="ay-signin-code">WhatsApp code { destination ? `for ${ destination }` : '' }
        <input id="ay-signin-code" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" required maxLength={ 6 } value={ code } onChange={ event => setCode( event.target.value ) } />
      </label> }</div>
      <div className={ styles.actions }><button disabled={ busy } type="submit">{ challenge ? 'Verify and continue' : 'Send WhatsApp code' }</button>
        <button disabled={ busy } type="button" onClick={ () => { setChallenge( '' ); setCode( '' ); setPending( null ); } }>Cancel</button></div>
    </form> }
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
