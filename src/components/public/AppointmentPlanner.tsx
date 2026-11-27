import React, { useEffect, useRef, useState } from 'react';
import { appointmentPlanError, appointmentPlanSummary, indiaDate, type AppointmentPlan } from '../../lib/appointmentPlan';
import { useApolloCatalog } from '../../hooks/useApolloCatalog';
import type { ApolloOption } from '../../lib/arogyaBooking';
import PublicNotice from './PublicNotice';
import SavedAppointmentDrafts from './SavedAppointmentDrafts';
import styles from './AppointmentPlanner.module.css';

const EMPTY_PLAN: AppointmentPlan = {
  city: '', hospital: '', professional: '', date: '', hospitalId: '', specialityId: '', doctorId: '', healthCheckId: '',
  patientMode: 'Telephone', appointmentType: 'Consultation', speciality: '', healthCheck: '', time: '',
  userType: '', salutation: '', patientName: '', age: '', gender: '', area: '', email: '', mobile: '', uhid: '', pickup: '', remarks: '',
  pickupFrom: '', vehicleNo: '', arrivalDate: '', arrivalTime: '', attendants: '', journeyRemarks: '',
  shiftingFrom: '', shiftingDate: '', shiftingTime: '', healthDescription: '', ambulancePickup: '', ambulanceFrom: '', ambulanceArea: '', ambulanceDate: '', ambulanceTime: '',
};
const STEPS = [ 'Appointment', 'Date & time', 'Patient', 'Review' ];

/** Apollo-shaped local request draft. Provider submission remains disabled until server integration is verified. */
export default function AppointmentPlanner ( { onSessionExpired }: { onSessionExpired: () => void } ): React.ReactElement {
  const [ plan, setPlan ] = useState<AppointmentPlan>( EMPTY_PLAN );
  const [ step, setStep ] = useState( 1 );
  const [ error, setError ] = useState( '' );
  const [ copied, setCopied ] = useState( false );
  const [ today, setToday ] = useState( '' );
  const [ draftVersion, setDraftVersion ] = useState( 0 );
  const heading = useRef<HTMLHeadingElement>( null );
  const previousStep = useRef( step );
  const catalog = useApolloCatalog( plan, onSessionExpired );

  useEffect( () => { setToday( indiaDate() ); }, [] );
  useEffect( () => {
    if ( previousStep.current !== step ) heading.current?.focus();
    previousStep.current = step;
  }, [ step ] );

  function update<K extends keyof AppointmentPlan> ( field: K, value: AppointmentPlan[K] ): void {
    setPlan( current => {
      const next = { ...current, [field]: value };
      if ( field === 'hospital' || field === 'appointmentType' ) {
        next.speciality = ''; next.professional = ''; next.healthCheck = ''; next.specialityId = ''; next.doctorId = ''; next.healthCheckId = ''; next.date = ''; next.time = '';
        for ( const key of [ 'shiftingFrom', 'shiftingDate', 'shiftingTime', 'healthDescription', 'ambulancePickup', 'ambulanceFrom', 'ambulanceArea', 'ambulanceDate', 'ambulanceTime' ] as const ) next[key] = '';
      }
      if ( field === 'speciality' ) { next.professional = ''; next.doctorId = ''; next.date = ''; next.time = ''; }
      if ( field === 'professional' || field === 'healthCheck' ) { next.date = ''; next.time = ''; }
      if ( field === 'date' ) next.time = '';
      if ( field === 'pickup' || field === 'pickupFrom' ) {
        next.vehicleNo = ''; next.arrivalDate = ''; next.arrivalTime = ''; next.attendants = ''; next.journeyRemarks = '';
        if ( field === 'pickup' ) next.pickupFrom = '';
      }
      if ( field === 'ambulancePickup' ) { next.ambulanceFrom = ''; next.ambulanceArea = ''; next.ambulanceDate = ''; next.ambulanceTime = ''; }
      if ( field === 'userType' ) {
        for ( const key of [ 'salutation', 'patientName', 'age', 'gender', 'area', 'email', 'mobile', 'uhid', 'pickup', 'remarks', 'pickupFrom', 'vehicleNo', 'arrivalDate', 'arrivalTime', 'attendants', 'journeyRemarks', 'shiftingFrom', 'shiftingDate', 'shiftingTime', 'healthDescription', 'ambulancePickup', 'ambulanceFrom', 'ambulanceArea', 'ambulanceDate', 'ambulanceTime' ] as const ) next[key] = '';
      }
      return next;
    } );
    setError( '' ); setCopied( false );
  }

  function advance ( event: React.FormEvent<HTMLFormElement> ): void {
    event.preventDefault();
    if ( step === 1 && ( !plan.hospitalId || ( plan.appointmentType === 'Health Checks' ? !catalog.healthChecks.some( item => String( item.id ) === plan.healthCheckId ) : !catalog.specialities.some( item => String( item.id ) === plan.specialityId ) || !catalog.doctors.some( item => String( item.id ) === plan.doctorId ) ) ) ) { setError( 'Choose from the current hospital, speciality and appointment options.' ); return; }
    if ( step === 2 && plan.appointmentType !== 'Admission' && !catalog.dates.includes( plan.date ) ) { setError( 'Choose a currently available date.' ); return; }
    if ( step === 2 && plan.date < indiaDate() ) { setError( 'Choose today or a future date, using India Standard Time.' ); return; }
    if ( step === 3 ) {
      const message = appointmentPlanError( plan );
      if ( message ) { setError( message ); return; }
    }
    setError( '' ); setStep( value => value + 1 );
  }

  const input = ( key: keyof AppointmentPlan, label: string, options: { required?: boolean; type?: string; placeholder?: string; maxLength?: number } = {} ) => (
    <label htmlFor={ `ay-${key}` }>{ label }{ options.required ? ' *' : ' (optional)' }
      <input id={ `ay-${key}` } name={ key } value={ plan[key] } type={ options.type || 'text' } required={ options.required } maxLength={ options.maxLength || 120 } placeholder={ options.placeholder } autoComplete="off" onChange={ event => update( key, event.target.value ) } />
    </label>
  );
  const select = ( key: keyof AppointmentPlan, label: string, options: readonly string[] ) => (
    <label htmlFor={ `ay-${key}` }>{ label } *
      <select id={ `ay-${key}` } name={ key } value={ plan[key] } required onChange={ event => update( key, event.target.value ) }>
        <option value="">Select</option>{ options.map( value => <option key={ value }>{ value }</option> ) }
      </select>
    </label>
  );

  const liveSelect = ( field: 'hospital' | 'speciality' | 'professional' | 'healthCheck', idField: 'hospitalId' | 'specialityId' | 'doctorId' | 'healthCheckId', label: string, options: ApolloOption[], busy = false ) => (
    <label htmlFor={ `ay-${field}` }>{ label } *
      <select id={ `ay-${field}` } required value={ plan[idField] || '' } disabled={ busy || !options.length } onChange={ event => {
        const option = options.find( item => String( item.id ) === event.target.value );
        update( field, option?.label || '' );
        setPlan( current => ( { ...current, [idField]: option ? String( option.id ) : '', ...( field === 'hospital' ? { city: option?.city || '' } : {} ) } ) );
      } }>
        <option value="">{ busy ? 'Loading…' : options.length ? 'Select' : 'No options available' }</option>
        { options.map( option => <option key={ option.id } value={ option.id }>{ option.label }</option> ) }
      </select>
    </label>
  );

  async function copySummary (): Promise<void> {
    try {
      // Deliberately exclude patient identifiers and contact details from the clipboard.
      await navigator.clipboard.writeText( appointmentPlanSummary( plan ) );
      setCopied( true ); setError( '' );
    } catch { setError( 'Copy is unavailable. Select and copy the appointment summary below.' ); }
  }

  const bootstrap = catalog.bootstrap;
  if ( !bootstrap ) return <section className={ styles.planner } aria-label="Appointment availability"><h2>Request an appointment</h2>
    { catalog.errors.bootstrap ? <><PublicNotice mode="inline" tone="error" message={ catalog.errors.bootstrap } /><div className={ styles.actions }><button type="button" onClick={ catalog.retry }>Try again</button></div></> : <p role="status">Loading live appointment choices…</p> }
  </section>;

  return (
    <section className={ styles.planner } aria-labelledby="ay-title">
      <p className={ styles.eyebrow }>Your next appointment</p>
      <h2 id="ay-title">Request an appointment</h2>
      <p>Choose your hospital, appointment and patient details. Review everything before continuing.</p>
      <p className={ styles.help }>Choose from the current Apollo hospital and appointment options. * Indicates mandatory fields.</p>
      <ol className={ styles.progress } aria-label="Appointment request progress">
        { STEPS.map( ( label, index ) => <li key={ label } aria-current={ step === index + 1 ? 'step' : undefined }><span aria-hidden="true">{ index + 1 }</span>{ label }</li> ) }
      </ol>
      <SavedAppointmentDrafts key={ draftVersion } plan={ plan } canSave={ step === 4 } onSessionExpired={ onSessionExpired } onLoad={ saved => { setPlan( saved ); setStep( 1 ); setError( '' ); } } />
      <div className={ styles.panel }>
        <h3 ref={ heading } tabIndex={ -1 }>{ STEPS[step - 1] }</h3>
        { step < 4 ? (
          <form onSubmit={ advance }>
            <div className={ styles.fields }>
              { step === 1 && <>
                { liveSelect( 'hospital', 'hospitalId', 'Hospital', bootstrap.hospitals ) }
                { plan.hospitalId && !bootstrap.hospitals.find( item => String( item.id ) === plan.hospitalId )?.city && input( 'city', 'City', { required: true } ) }
                { select( 'patientMode', 'Patient mode', [ 'Telephone', 'Camp' ] ) }
                { select( 'appointmentType', 'Appointment type', bootstrap.appointmentTypes.map( item => item.label ) ) }
                { plan.appointmentType === 'Health Checks' ? liveSelect( 'healthCheck', 'healthCheckId', 'Health check', catalog.healthChecks, catalog.busy.hospital ) : <>
                  { liveSelect( 'speciality', 'specialityId', 'Speciality', catalog.specialities, catalog.busy.hospital ) }
                  { liveSelect( 'professional', 'doctorId', 'Doctor', catalog.doctors, catalog.busy.doctors ) }
                </> }
                { ( catalog.errors.hospital || catalog.errors.doctors ) && <PublicNotice mode="inline" tone="error" message={ catalog.errors.hospital || catalog.errors.doctors } /> }
                <p className={ styles.help }>Doctor and hospital choices are fetched from Apollo. Your appointment still requires provider confirmation.</p>
              </> }
              { step === 2 && <>
                { plan.appointmentType === 'Admission' ? <label htmlFor="ay-date">Preferred admission date *<input id="ay-date" type="date" required min={ today || undefined } value={ plan.date } onChange={ event => update( 'date', event.target.value ) } /></label> : <label htmlFor="ay-date">Appointment date *
                  <select id="ay-date" required disabled={ catalog.busy.dates || !catalog.dates.length } value={ plan.date } onChange={ event => update( 'date', event.target.value ) }>
                    <option value="">{ catalog.busy.dates ? 'Loading available dates…' : catalog.dates.length ? 'Select date' : 'No dates available' }</option>
                    { catalog.dates.map( date => <option key={ date } value={ date }>{ new Date( `${ date }T00:00:00Z` ).toLocaleDateString( 'en-IN', { timeZone: 'UTC', day: '2-digit', month: 'long', year: 'numeric' } ) }</option> ) }
                  </select>
                </label> }
                { catalog.errors.dates && <PublicNotice mode="inline" tone="error" message={ catalog.errors.dates } /> }
                { catalog.observedAt > 0 && <p className={ styles.help }>Availability checked { new Date( catalog.observedAt * 1000 ).toLocaleString( 'en-IN', { timeZone: 'Asia/Kolkata' } ) } IST.</p> }
                <fieldset><legend>{ plan.appointmentType === 'Admission' ? 'Admission time' : 'Slot time' } *</legend>
                  <div className={ styles.time }>
                    <label htmlFor="ay-hour">Hour<select id="ay-hour" required value={ plan.time.split( ':' )[0] || '' } onChange={ event => update( 'time', `${event.target.value}:${plan.time.split( ':' )[1] || ''}` ) }>
                      <option value="">HH</option>{ bootstrap.hours.filter( item => item.id > 0 ).map( item => <option key={ item.id } value={ String( item.id ).padStart( 2, '0' ) }>{ item.label }</option> ) }
                    </select></label>
                    <label htmlFor="ay-minute">Minute<select id="ay-minute" required value={ plan.time.split( ':' )[1] || '' } onChange={ event => update( 'time', `${plan.time.split( ':' )[0] || ''}:${event.target.value}` ) }>
                      <option value="">MM</option>{ bootstrap.minutes.map( item => <option key={ item.id } value={ String( item.id ).padStart( 2, '0' ) }>{ item.label }</option> ) }
                    </select></label>
                  </div>
                </fieldset>
                <p className={ styles.help }>24-hour time, in India Standard Time. This is your requested time; the provider must confirm availability.</p>
              </> }
              { step === 3 && <>
                <fieldset><legend>User type *</legend><div className={ styles.radios }>
                  { [ 'Registered User', 'New User' ].map( value => <label key={ value }><input type="radio" name="userType" value={ value } checked={ plan.userType === value } required onChange={ () => update( 'userType', value as AppointmentPlan['userType'] ) } />{ value }</label> ) }
                </div></fieldset>
                { plan.userType === 'Registered User' && <>
                  <p className={ styles.help }>Use your registered 10-digit mobile number or UHID. Patient lookup will require provider verification; this draft does not verify a patient record.</p>
                  { input( 'mobile', 'Registered mobile number', { type: 'tel', maxLength: 10, placeholder: '10-digit mobile number' } ) }
                  { input( 'uhid', 'UHID', { placeholder: 'APX1.0000000000', maxLength: 40 } ) }
                </> }
                { plan.userType === 'New User' && <>
                  <p className={ styles.help }>Use the patient name as it appears on their identity document. The hospital may charge a separate registration fee.</p>
                  { select( 'salutation', 'Salutation', bootstrap.salutations.map( item => item.label ) ) }
                  { input( 'patientName', 'Patient name', { required: true } ) }
                  { input( 'age', 'Age', { required: true, type: 'number', maxLength: 3 } ) }
                  { select( 'gender', 'Gender', [ 'Male', 'Female' ] ) }
                  { input( 'area', 'Patient area / location', { required: true, maxLength: 240 } ) }
                  { input( 'email', 'Email', { type: 'email' } ) }
                  { input( 'mobile', 'Mobile number', { required: true, type: 'tel', maxLength: 16, placeholder: '919999999999' } ) }
                  { select( 'pickup', 'Request vehicle pickup', [ 'Yes', 'No' ] ) }
                  { plan.pickup === 'Yes' && <>
                    { select( 'pickupFrom', 'Pickup from', [ 'Railway Station', 'Airport' ] ) }
                    { plan.pickupFrom && <>
                      { input( 'vehicleNo', plan.pickupFrom === 'Airport' ? 'Flight number' : 'Train number', { required: true } ) }
                      { input( 'arrivalDate', 'Arrival date', { required: true, type: 'date' } ) }
                      { input( 'arrivalTime', 'Arrival time (India Standard Time)', { required: true, type: 'time' } ) }
                      { select( 'attendants', 'Number of attendants', [ '1', '2', '3', '4', '5' ] ) }
                      { input( 'journeyRemarks', 'Journey remarks', { required: true, maxLength: 500 } ) }
                    </> }
                  </> }
                  <p className={ styles.help }>Pickup availability and any applicable conditions must be confirmed by the hospital.</p>
                  { plan.appointmentType === 'Admission' && <>
                    <h4>Admission transfer</h4>
                    { select( 'shiftingFrom', 'Patient shifting from', [ 'Home', 'Other Hospital', 'RTA', 'Workplace' ] ) }
                    { input( 'shiftingDate', 'Patient shifting date', { required: true, type: 'date' } ) }
                    { input( 'shiftingTime', 'Patient shifting time (IST)', { required: true, type: 'time' } ) }
                    { input( 'healthDescription', 'Patient health description', { required: true, maxLength: 1000 } ) }
                    { select( 'ambulancePickup', 'Request ambulance pickup', [ 'Yes', 'No' ] ) }
                    { plan.ambulancePickup === 'Yes' && <>
                      { select( 'ambulanceFrom', 'Ambulance provider', [ 'Apollo', 'Others' ] ) }
                      { select( 'ambulanceArea', 'Ambulance pickup area', [ 'Airport', 'Home', 'Railway Station', 'Other Hospital' ] ) }
                      { input( 'ambulanceDate', 'Ambulance pickup date', { required: true, type: 'date' } ) }
                      { input( 'ambulanceTime', 'Ambulance pickup time (IST)', { required: true, type: 'time' } ) }
                    </> }
                  </> }
                </> }
                { plan.userType && <label htmlFor="ay-remarks">IC remarks (optional)<textarea id="ay-remarks" value={ plan.remarks } maxLength={ 1000 } onChange={ event => update( 'remarks', event.target.value ) } /></label> }
                <p className={ styles.help }>Details stay in this tab and are cleared when it closes or reloads. Do not enter Aadhaar numbers, medical records or passwords.</p>
              </> }
            </div>
            { error && <PublicNotice mode="inline" tone="error" message={ error } /> }
            <div className={ styles.actions }>
              { step > 1 && <button type="button" onClick={ () => { setError( '' ); setStep( value => value - 1 ); } }>Back</button> }
              <button className={ styles.primary } type="submit">{ step === 3 ? 'Review request' : 'Continue' } →</button>
            </div>
          </form>
        ) : <>
          <p className={ styles.summary }>{ appointmentPlanSummary( plan ) }</p>
          { plan.userType === 'New User' && <dl className={ styles.patientReview }>
            <dt>Patient</dt><dd>{ plan.salutation } { plan.patientName }</dd><dt>Age / gender</dt><dd>{ plan.age } / { plan.gender }</dd>
            <dt>Area</dt><dd>{ plan.area }</dd><dt>Mobile</dt><dd>{ plan.mobile }</dd><dt>Email</dt><dd>{ plan.email || 'Not provided' }</dd><dt>Pickup requested</dt><dd>{ plan.pickup }</dd>
            { plan.pickup === 'Yes' && <><dt>Pickup journey</dt><dd>{ plan.pickupFrom }, { plan.vehicleNo }, { plan.arrivalDate } at { plan.arrivalTime } IST; { plan.attendants } attendants</dd><dt>Journey remarks</dt><dd>{ plan.journeyRemarks || 'None' }</dd></> }
            { plan.appointmentType === 'Admission' && <><dt>Admission transfer</dt><dd>From { plan.shiftingFrom }, { plan.shiftingDate } at { plan.shiftingTime } IST</dd><dt>Health description</dt><dd>{ plan.healthDescription }</dd><dt>Ambulance requested</dt><dd>{ plan.ambulancePickup }</dd>{ plan.ambulancePickup === 'Yes' && <><dt>Ambulance pickup</dt><dd>{ plan.ambulanceFrom }, { plan.ambulanceArea }, { plan.ambulanceDate } at { plan.ambulanceTime } IST</dd></> }</> }
          </dl> }
          { plan.userType === 'Registered User' && <p className={ styles.help }>Patient lookup pending: { plan.uhid || plan.mobile }</p> }
          { plan.remarks && <p className={ styles.help }>Remarks: { plan.remarks }</p> }
          <PublicNotice mode="inline" message="Draft only. No request has been sent to Apollo, no payment taken and no appointment booked. Provider submission will be enabled after the connection is verified." />
          <div className={ styles.actions }>
            <button type="button" onClick={ () => { setError( '' ); setCopied( false ); setStep( 1 ); } }>Edit request</button>
            <button className={ styles.primary } type="button" onClick={ () => { void copySummary(); } }>Copy appointment summary</button>
            <button type="button" onClick={ () => { setPlan( EMPTY_PLAN ); setDraftVersion( value => value + 1 ); setError( '' ); setCopied( false ); setStep( 1 ); } }>Clear this form</button>
          </div>
          { copied && <PublicNotice mode="inline" tone="success" message="Appointment summary copied. Patient identifiers and contact details were excluded." /> }
          { error && <PublicNotice mode="inline" tone="error" message={ error } /> }
        </> }
      </div>
    </section>
  );
}
