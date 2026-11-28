import React, { useEffect, useRef, useState } from 'react';
import { indiaDate } from '../../lib/appointmentPlan';
import { clearSession, getSession, restoreSession } from '../../lib/customerAuth';
import { appointmentDraftAction, AppointmentApiError } from '../../lib/arogyaBooking';
import { HOSPITAL_CHOICES, REQUEST_TYPES, TIME_WINDOWS, isAssistanceReceipt,
  type HospitalAssistanceRequest, type AssistanceReceipt } from '../../lib/hospitalAssistance';
import bookingConfig from '../../content/arogyaBookingConfig.json';
import PublicNotice from './PublicNotice';
import styles from './AppointmentPlanner.module.css';

const EMPTY: HospitalAssistanceRequest = {
  hospitalChoice: 'Help me choose', hospitalName: '', city: '', appointmentType: 'Consultation',
  speciality: '', doctor: '', preferredDate: '', preferredTime: 'Flexible',
  patientName: '', mobile: '', email: '', notes: '', consent: false,
};

const AUTH_URL = '/auth?return=%2Felsewhere%2Farogya-yatra%2F';

/** Public form. Verify the customer only when they submit or request history. */
export default function AppointmentPlanner (): React.ReactElement {
  const [ form, setForm ] = useState<HospitalAssistanceRequest>( EMPTY );
  const [ today, setToday ] = useState( '' );
  const [ busy, setBusy ] = useState( false );
  const [ error, setError ] = useState( '' );
  const [ receipt, setReceipt ] = useState<AssistanceReceipt | null>( null );
  const [ history, setHistory ] = useState<AssistanceReceipt[]>( [] );
  const [ historyError, setHistoryError ] = useState( '' );
  const [ historyLoaded, setHistoryLoaded ] = useState( false );
  const [ nextAfter, setNextAfter ] = useState<string | null>( null );
  const [ uncertain, setUncertain ] = useState( false );
  const [ needsSignIn, setNeedsSignIn ] = useState( false );
  const pending = useRef<{ accountKey: string; requestId: string; request: HospitalAssistanceRequest } | null>( null );
  const verifiedOwner = useRef( '' );
  const submitting = useRef( false );
  const receiptHeading = useRef<HTMLHeadingElement>( null );
  const signInHeading = useRef<HTMLHeadingElement>( null );

  useEffect( () => { setToday( indiaDate() ); }, [] );
  useEffect( () => { if ( receipt ) receiptHeading.current?.focus(); }, [ receipt ] );
  useEffect( () => { if ( needsSignIn ) signInHeading.current?.focus(); }, [ needsSignIn ] );
  useEffect( () => {
    const changed = ( event: StorageEvent ) => {
      if ( event.key === 'wecare.customer.sessionHint' || event.key === null ) {
        setHistory( [] ); setHistoryLoaded( false ); setNextAfter( null ); setReceipt( null );
      }
    };
    window.addEventListener( 'storage', changed );
    return () => window.removeEventListener( 'storage', changed );
  }, [] );

  function accountChanged (): void {
    pending.current = null; verifiedOwner.current = ''; setForm( EMPTY ); setReceipt( null );
    setHistory( [] ); setHistoryLoaded( false ); setNextAfter( null ); setUncertain( false );
    setError( 'Your signed-in account changed. Enter the request details again before submitting.' );
  }

  async function verifyAtAction () {
    const session = getSession() || await restoreSession();
    if ( !session ) { setNeedsSignIn( true ); return null; }
    const access = await appointmentDraftAction( bookingConfig.endpoint, session.accessToken, { action: 'access' } );
    if ( access.phoneVerified !== true || typeof access.accountKey !== 'string' || !/^[a-f0-9]{64}$/.test( access.accountKey ) ) throw new Error( 'Account verification is temporarily unavailable.' );
    if ( getSession()?.accessToken !== session.accessToken ) { setNeedsSignIn( true ); return null; }
    if ( verifiedOwner.current && verifiedOwner.current !== access.accountKey ) { accountChanged(); return null; }
    verifiedOwner.current = access.accountKey;
    setNeedsSignIn( false );
    return { accessToken: session.accessToken, accountKey: access.accountKey };
  }

  function authenticationFailure ( failure: unknown ): boolean {
    if ( failure instanceof AppointmentApiError && failure.code === 'ACCOUNT_CHANGED' ) { accountChanged(); return true; }
    if ( failure instanceof AppointmentApiError && [ 401, 403 ].includes( failure.status ) ) {
      clearSession(); setNeedsSignIn( true ); return true;
    }
    return false;
  }

  function update ( key: keyof HospitalAssistanceRequest, value: string | boolean ): void {
    setForm( current => ( { ...current, [key]: value, ...( key === 'hospitalChoice' ? { hospitalName: '' } : {} ) } ) ); setError( '' );
  }

  async function submit ( event?: React.FormEvent<HTMLFormElement> ): Promise<void> {
    event?.preventDefault();
    if ( submitting.current || receipt ) return;
    if ( !pending.current && form.preferredDate < indiaDate() ) { setError( 'Choose today or a future date in India Standard Time.' ); return; }
    submitting.current = true; setBusy( true ); setError( '' );
    try {
      const access = await verifyAtAction();
      if ( !access ) return;
      if ( !pending.current ) pending.current = { accountKey: access.accountKey, requestId: crypto.randomUUID(), request: { ...form } };
      if ( pending.current.accountKey !== access.accountKey ) { accountChanged(); return; }
      const value = await appointmentDraftAction( bookingConfig.endpoint, access.accessToken,
        { action: 'submitRequest', ...pending.current } );
      if ( getSession()?.accessToken !== access.accessToken ) {
        setUncertain( true ); setError( 'Your session changed while sending. Retry the same request to check its receipt.' ); return;
      }
      if ( !isAssistanceReceipt( value.request ) || value.request.requestId !== pending.current.requestId ) throw new Error( 'Receipt could not be verified.' );
      const saved = value.request;
      setReceipt( saved ); setUncertain( false );
      setHistory( rows => [ saved, ...rows.filter( row => row.requestId !== saved.requestId ) ] );
    } catch ( failure ) {
      if ( authenticationFailure( failure ) ) { if ( pending.current ) setUncertain( true ); return; }
      const rejected = failure instanceof AppointmentApiError && [ 400, 409 ].includes( failure.status );
      if ( rejected ) pending.current = null;
      setUncertain( !rejected && !!pending.current );
      setError( rejected && failure instanceof Error ? failure.message : pending.current
        ? 'We could not verify receipt of your request. Retry the same request below; the reference prevents a duplicate.'
        : 'We could not check sign-in. Your form is still here. Please try Submit request again.' );
    } finally { submitting.current = false; setBusy( false ); }
  }

  async function loadHistory ( more = false ): Promise<void> {
    if ( busy ) return;
    setBusy( true );
    try {
      const access = await verifyAtAction();
      if ( !access ) return;
      const value = await appointmentDraftAction( bookingConfig.endpoint, access.accessToken,
        { action: 'myRequests', accountKey: access.accountKey, ...( more && nextAfter ? { after: nextAfter } : {} ) } );
      if ( getSession()?.accessToken !== access.accessToken ) { setHistory( [] ); setHistoryLoaded( false ); return; }
      if ( !Array.isArray( value.requests ) || !value.requests.every( isAssistanceReceipt ) ) throw new Error( 'Invalid history.' );
      const rows = value.requests;
      setHistory( current => more ? [ ...current, ...rows.filter( row => !current.some( existing => existing.requestId === row.requestId ) ) ] : rows );
      setHistoryLoaded( true ); setNextAfter( value.nextAfter || null ); setHistoryError( '' );
    } catch ( failure ) {
      if ( !authenticationFailure( failure ) ) setHistoryError( 'Your request history could not be loaded. Retry below.' );
    } finally { setBusy( false ); }
  }

  const input = ( key: Exclude<keyof HospitalAssistanceRequest, 'consent'>, label: string, required = false, type = 'text', placeholder?: string ) => (
    <label htmlFor={ `ay-${key}` }>{ label }{ required ? ' *' : ' (optional)' }
      <input id={ `ay-${key}` } name={ key } type={ type } value={ form[key] } required={ required } maxLength={ key === 'city' ? 80 : 120 }
        min={ type === 'date' ? today || undefined : undefined } placeholder={ placeholder }
        autoComplete={ key === 'patientName' ? 'name' : key === 'mobile' ? 'tel' : key === 'email' ? 'email' : 'off' }
        pattern={ key === 'mobile' ? '\\+?[1-9][0-9]{9,14}' : undefined }
        onChange={ event => update( key, event.target.value ) } />
    </label>
  );
  const select = ( key: 'hospitalChoice' | 'appointmentType' | 'preferredTime', label: string, choices: readonly string[] ) => (
    <label htmlFor={ `ay-${key}` }>{ label } *<select id={ `ay-${key}` } name={ key } value={ form[key] } required onChange={ event => update( key, event.target.value ) }>
      { choices.map( choice => <option key={ choice }>{ choice }</option> ) }
    </select></label>
  );

  return <section className={ styles.planner } aria-labelledby="ay-title">
    <p className={ styles.eyebrow }>Arogya Yatra · hospital assistance</p>
    <h2 id="ay-title">Submit an appointment request</h2>
    <p>Tell us the hospital and care you are looking for. Choose Apollo, name another hospital, or ask WECARE to help you choose.</p>
    { receipt ? <div className={ styles.panel } role="status">
      <h3 ref={ receiptHeading } tabIndex={ -1 }>Request received</h3>
      <p><strong>Reference:</strong> <span className={ styles.reference }>{ receipt.requestId }</span></p>
      <p><strong>Status:</strong> Awaiting review</p>
      <p>WECARE will review your preferences and contact you about the next steps. Your appointment is confirmed only when the hospital accepts it and the details are shared with you.</p>
      <p>No payment was collected for this submission.</p>
      <div className={ styles.actions }><button type="button" onClick={ () => { pending.current = null; setReceipt( null ); setForm( EMPTY ); setError( '' ); } }>Start another request</button></div>
    </div> : <form onSubmit={ event => { void submit( event ); } }>
      <fieldset className={ styles.requestFields } disabled={ busy || uncertain }>
        <legend>Hospital and appointment preferences</legend>
        <p className={ styles.help }>* Indicates mandatory fields. Dates and times are preferences to be checked with the hospital.</p>
        <div className={ styles.fields } data-public-field-group="appointment">
          { select( 'hospitalChoice', 'Hospital preference', HOSPITAL_CHOICES ) }
          { form.hospitalChoice !== 'Help me choose' && input( 'hospitalName', form.hospitalChoice === 'Apollo Hospitals' ? 'Preferred Apollo branch' : 'Hospital name', form.hospitalChoice === 'Another hospital' ) }
          { input( 'city', 'Preferred city', true ) }
          { select( 'appointmentType', 'Request type', REQUEST_TYPES ) }
          { input( 'speciality', 'Speciality or health check needed' ) }
          { input( 'doctor', 'Preferred doctor' ) }
          { input( 'preferredDate', 'Preferred date', true, 'date' ) }
          { select( 'preferredTime', 'Preferred time window (India Standard Time)', TIME_WINDOWS ) }
        </div>
        <h3>Patient and contact details</h3>
        <div className={ styles.fields }>
          { input( 'patientName', 'Patient name', true ) }
          { input( 'mobile', 'Patient contact number with country code', true, 'tel', 'For example, 919999999999' ) }
          { input( 'email', 'Email', false, 'email' ) }
          <label htmlFor="ay-notes">Anything else we should know? (optional)
            <textarea id="ay-notes" value={ form.notes } maxLength={ 500 } onChange={ event => update( 'notes', event.target.value ) } />
          </label>
          <label className={ styles.consent } htmlFor="ay-consent"><input id="ay-consent" type="checkbox" required checked={ form.consent } onChange={ event => update( 'consent', event.target.checked ) } />
            I am the patient or have their permission to share these details with WECARE for hospital appointment coordination.
          </label>
        </div>
      </fieldset>
      { error && <PublicNotice mode="inline" tone="error" message={ error } /> }
      { uncertain ? <div className={ styles.actions }><button type="button" disabled={ busy } onClick={ () => { void submit(); } }>{ busy ? 'Checking request…' : 'Retry the same request' }</button></div>
        : <div className={ styles.actions }><button type="submit" disabled={ busy }>{ busy ? 'Submitting…' : 'Submit request' }</button></div> }
      <p className={ styles.help }>Submission is free. We explain any service charges before you agree to paid assistance. Hospital acceptance is required for an appointment.</p>
    </form> }
    { needsSignIn && <section className={ styles.panel } aria-labelledby="ay-signin-title">
      <h3 id="ay-signin-title" ref={ signInHeading } tabIndex={ -1 }>Sign in to submit your request</h3>
      <p>Your form stays open here. Complete WhatsApp sign-in in a new tab, return to this tab, then press Submit request again.</p>
      <div className={ styles.actions }><a className={ styles.signInLink } href={ AUTH_URL } target="_blank" rel="noopener noreferrer">Sign in with WhatsApp (new tab)</a></div>
    </section> }
    <section className={ styles.panel } aria-labelledby="ay-history">
      <h3 id="ay-history">Your submitted requests</h3>
      { historyError && <PublicNotice mode="inline" tone="error" message={ historyError } /> }
      { historyLoaded && !history.length && !historyError && <p className={ styles.help }>Your submitted requests will appear here for 30 days.</p> }
      <ul className={ styles.requestList }>{ history.map( item => <li key={ item.requestId }><span className={ styles.reference }>{ item.requestId }</span><br />Awaiting review · { new Date( item.createdAt * 1000 ).toLocaleDateString( 'en-IN', { timeZone: 'Asia/Kolkata' } ) }</li> ) }</ul>
      <div className={ styles.actions }>
        { nextAfter && <button type="button" disabled={ busy } onClick={ () => { void loadHistory( true ); } }>Show more requests</button> }
        <button type="button" disabled={ busy } onClick={ () => { void loadHistory(); } }>{ historyLoaded ? 'Refresh request history' : 'View my submitted requests' }</button>
      </div>
    </section>
  </section>;
}
