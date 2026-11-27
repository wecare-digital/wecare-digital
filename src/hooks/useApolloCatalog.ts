import { useCallback, useEffect, useState } from 'react';
import type { AppointmentPlan } from '../lib/appointmentPlan';
import { AppointmentApiError, type ApolloOption } from '../lib/arogyaBooking';
import { catalogOptions, readLiveCatalog } from '../lib/apolloCatalog';

interface Bootstrap { hospitals: ApolloOption[]; appointmentTypes: ApolloOption[]; salutations: ApolloOption[]; hours: ApolloOption[]; minutes: ApolloOption[]; }

/** Every dependent list comes from the server; an error never selects a snapshot. */
export function useApolloCatalog ( plan: AppointmentPlan, onSessionExpired: () => void ) {
  const [ bootstrap, setBootstrap ] = useState<Bootstrap | null>( null );
  const [ specialities, setSpecialities ] = useState<ApolloOption[]>( [] );
  const [ doctors, setDoctors ] = useState<ApolloOption[]>( [] );
  const [ healthChecks, setHealthChecks ] = useState<ApolloOption[]>( [] );
  const [ dates, setDates ] = useState<string[]>( [] );
  const [ busy, setBusy ] = useState<Record<string, boolean>>( {} );
  const [ errors, setErrors ] = useState<Record<string, string>>( {} );
  const [ generation, setGeneration ] = useState( 0 );
  const [ observedAt, setObservedAt ] = useState( 0 );
  const fail = useCallback( ( key: string, failure: unknown, signal: AbortSignal ): void => {
    if ( signal.aborted ) return;
    if ( failure instanceof AppointmentApiError && [ 401, 403 ].includes( failure.status ) ) { onSessionExpired(); return; }
    setErrors( old => ( { ...old, [key]: 'Live appointment choices are unavailable. Please try again.' } ) );
  }, [ onSessionExpired ] );

  useEffect( () => {
    const controller = new AbortController();
    setBootstrap( null ); setErrors( {} ); setBusy( old => ( { ...old, bootstrap: true } ) );
    void readLiveCatalog( { kind: 'bootstrap' }, controller.signal ).then( value => {
      if ( controller.signal.aborted ) return;
      const data = Object.fromEntries( [ 'hospitals', 'appointmentTypes', 'salutations', 'hours', 'minutes' ].map( key => [ key, catalogOptions( value.data, key ) ] ) ) as unknown as Bootstrap;
      if ( !data.hospitals.length ) throw new Error( 'No hospitals available.' );
      setBootstrap( data );
    } ).catch( error => fail( 'bootstrap', error, controller.signal ) ).finally( () => { if ( !controller.signal.aborted ) setBusy( old => ( { ...old, bootstrap: false } ) ); } );
    return () => controller.abort();
  }, [ generation, fail ] );

  useEffect( () => {
    const controller = new AbortController();
    setSpecialities( [] ); setHealthChecks( [] ); setBusy( old => ( { ...old, hospital: false } ) );
    setErrors( old => ( { ...old, hospital: '' } ) );
    if ( !plan.hospitalId ) return () => controller.abort();
    const health = plan.appointmentType === 'Health Checks';
    setBusy( old => ( { ...old, hospital: true } ) );
    void readLiveCatalog( { kind: health ? 'healthChecks' : 'specialities', hospitalId: Number( plan.hospitalId ) }, controller.signal ).then( value => {
      if ( controller.signal.aborted ) return;
      const options = catalogOptions( value.data, 'options' );
      if ( health ) setHealthChecks( options ); else setSpecialities( options );
    } ).catch( error => fail( 'hospital', error, controller.signal ) ).finally( () => { if ( !controller.signal.aborted ) setBusy( old => ( { ...old, hospital: false } ) ); } );
    return () => controller.abort();
  }, [ plan.hospitalId, plan.appointmentType, generation, fail ] );

  useEffect( () => {
    const controller = new AbortController();
    setDoctors( [] ); setBusy( old => ( { ...old, doctors: false } ) ); setErrors( old => ( { ...old, doctors: '' } ) );
    if ( !plan.hospitalId || !plan.specialityId || plan.appointmentType === 'Health Checks' ) return () => controller.abort();
    setBusy( old => ( { ...old, doctors: true } ) );
    void readLiveCatalog( { kind: 'doctors', hospitalId: Number( plan.hospitalId ), specialityId: Number( plan.specialityId ) }, controller.signal ).then( value => {
      if ( !controller.signal.aborted ) setDoctors( catalogOptions( value.data, 'options' ) );
    } ).catch( error => fail( 'doctors', error, controller.signal ) ).finally( () => { if ( !controller.signal.aborted ) setBusy( old => ( { ...old, doctors: false } ) ); } );
    return () => controller.abort();
  }, [ plan.hospitalId, plan.specialityId, plan.appointmentType, generation, fail ] );

  useEffect( () => {
    const controller = new AbortController();
    setDates( [] ); setObservedAt( 0 ); setBusy( old => ( { ...old, dates: false } ) ); setErrors( old => ( { ...old, dates: '' } ) );
    const itemId = plan.appointmentType === 'Health Checks' ? plan.healthCheckId : plan.doctorId;
    if ( !plan.hospitalId || !itemId || plan.appointmentType === 'Admission' ) return () => controller.abort();
    setBusy( old => ( { ...old, dates: true } ) );
    void readLiveCatalog( { kind: 'dates', hospitalId: Number( plan.hospitalId ), itemId: Number( itemId ), appointmentKind: plan.appointmentType === 'Health Checks' ? 'healthCheck' : 'consultation' }, controller.signal ).then( value => {
      if ( controller.signal.aborted ) return;
      const values = value.data?.dates;
      if ( !Array.isArray( values ) || values.some( item => typeof item !== 'string' ) ) throw new Error( 'Invalid schedule.' );
      setDates( values as string[] ); setObservedAt( value.observedAt || 0 );
    } ).catch( error => fail( 'dates', error, controller.signal ) ).finally( () => { if ( !controller.signal.aborted ) setBusy( old => ( { ...old, dates: false } ) ); } );
    return () => controller.abort();
  }, [ plan.hospitalId, plan.doctorId, plan.healthCheckId, plan.appointmentType, generation, fail ] );

  return { bootstrap, specialities, doctors, healthChecks, dates, busy, errors, observedAt, retry: () => setGeneration( value => value + 1 ) };
}
