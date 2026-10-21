import React, { useEffect, useState } from 'react';
import * as api from '../../../api/client';
import { useToastContext } from '../../../contexts/ToastContext';
import ConsentPanel from '../customers/ConsentPanel';

const CONFIG_KEY = 'subscribe_messages_config';
type Scenario = 'newCustomer' | 'returningCustomer';
type Copy = { body: string; flowCta: string; confirmation: string };
type Messages = Record<Scenario, Copy>;
const DEFAULTS: Messages = {
  newCustomer: {
    body: 'Welcome to WECARE.DIGITAL. Add your name, username and address to complete your customer profile.',
    flowCta: 'Subscribe', confirmation: 'Your details have been saved.',
  },
  returningCustomer: {
    body: 'Welcome back to WECARE.DIGITAL. Review your saved details and update your username or address whenever needed.',
    flowCta: 'Update details', confirmation: 'Your details have been updated.',
  },
};
const SCENARIOS: Scenario[] = [ 'newCustomer', 'returningCustomer' ];
const FIELDS = [ 'body', 'flowCta', 'confirmation' ] as const;

export default function SubscribeSettings () {
  const toast = useToastContext();
  const [ messages, setMessages ] = useState<Messages>( DEFAULTS );
  const [ ready, setReady ] = useState( false );
  const [ error, setError ] = useState( '' );
  const [ saving, setSaving ] = useState( false );
  const [ customerQuery, setCustomerQuery ] = useState( '' );
  const [ customerMatches, setCustomerMatches ] = useState<api.Contact[]>( [] );
  const [ customerSearchMessage, setCustomerSearchMessage ] = useState( '' );
  const [ searchingCustomers, setSearchingCustomers ] = useState( false );
  const [ selectedContactId, setSelectedContactId ] = useState( '' );

  const load = async () => {
    setReady( false ); setError( '' );
    try {
      const result = await api.getSystemConfigResult( CONFIG_KEY );
      if ( !result.ok ) throw new Error( result.failure.message || 'Could not load Subscribe messages.' );
      const stored = result.data.config;
      if ( stored !== null && ( typeof stored !== 'object' || Array.isArray( stored ) ) )
        throw new Error( 'Saved Subscribe messages have an invalid format.' );
      const next = { newCustomer: { ...DEFAULTS.newCustomer }, returningCustomer: { ...DEFAULTS.returningCustomer } };
      for ( const scenario of SCENARIOS ) for ( const field of FIELDS ) {
        const value = stored?.[ scenario ]?.[ field ];
        if ( typeof value === 'string' ) next[ scenario ][ field ] = value;
      }
      setMessages( next ); setReady( true );
    } catch ( err ) { setError( err instanceof Error ? err.message : 'Could not load Subscribe messages.' ); }
  };
  useEffect( () => { void load(); }, [] );

  const save = async ( event: React.FormEvent ) => {
    event.preventDefault();
    if ( !ready ) return;
    const next = { newCustomer: { ...messages.newCustomer }, returningCustomer: { ...messages.returningCustomer } };
    for ( const scenario of SCENARIOS ) for ( const field of FIELDS ) {
      next[ scenario ][ field ] = next[ scenario ][ field ].trim();
      const limit = field === 'flowCta' ? 20 : 1024;
      if ( !next[ scenario ][ field ] || next[ scenario ][ field ].length > limit ) {
        toast.error( `Each message is required. Button labels allow 20 characters; messages allow 1024.` ); return;
      }
    }
    setSaving( true );
    try {
      if ( !await api.updateSystemConfig( CONFIG_KEY, next ) ) throw new Error( 'Save could not be confirmed. Your edits are still here.' );
      setMessages( next ); toast.success( 'Subscribe messages saved.' );
    } catch ( err ) { toast.error( err instanceof Error ? err.message : 'Could not save Subscribe messages.' ); }
    finally { setSaving( false ); }
  };

  const searchCustomers = async ( event: React.FormEvent ) => {
    event.preventDefault();
    const query = customerQuery.trim();
    setSelectedContactId( '' );
    setCustomerMatches( [] );
    setCustomerSearchMessage( '' );
    if ( !query ) return;
    setSearchingCustomers( true );
    try {
      const result = await api.searchContactsResult( query );
      if ( !result.ok ) {
        setCustomerSearchMessage( result.failure.message || 'Customer search unavailable.' );
        return;
      }
      setCustomerMatches( result.data );
      if ( result.data.length === 0 ) setCustomerSearchMessage( 'No matching customers found.' );
    } catch {
      setCustomerSearchMessage( 'Customer search unavailable.' );
    } finally {
      setSearchingCustomers( false );
    }
  };

  return <section aria-label="Subscribe settings">
    <h3>Subscribe messages</h3>
    <p>Edit the message before the form opens and the confirmation shown inside the form. Customer ID is displayed separately.</p>
    <p>Flow 1386523953464380 is Published. Saving wording changes message copy only; it does not modify or republish the Flow. One-off send text can override the opening message.</p>
    { error && <p role="alert">{ error } <button type="button" onClick={ load }>Retry loading messages</button></p> }
    { !ready && !error && <p>Loading Subscribe messages…</p> }
    <form onSubmit={ save }>
      <fieldset disabled={ !ready || saving } style={{ border: 0, padding: 0 }}>
        { SCENARIOS.map( scenario => <fieldset key={ scenario } style={{ margin: '16px 0', padding: 16, border: '1px solid var(--border)', borderRadius: 12 }}>
          <legend>{ scenario === 'newCustomer' ? 'New customer' : 'Returning customer' }</legend>
          { FIELDS.map( field => <label key={ field } style={{ display: 'block', marginBottom: 12 }}>
            { field === 'body' ? 'Opening message' : field === 'flowCta' ? 'Button text' : 'Confirmation inside Flow' }
            <textarea aria-label={`${scenario} ${field}`} required maxLength={ field === 'flowCta' ? 20 : 1024 }
              rows={ field === 'flowCta' ? 1 : 3 } value={ messages[ scenario ][ field ] }
              onChange={ event => setMessages( previous => ({ ...previous, [scenario]: { ...previous[scenario], [field]: event.target.value } }) ) }
              style={{ display: 'block', width: '100%', padding: 10, border: '1px solid var(--border)', borderRadius: 8 }} />
          </label> ) }
        </fieldset> ) }
        <button type="submit">{ saving ? 'Saving…' : 'Save Subscribe messages' }</button>
      </fieldset>
    </form>

    <hr style={{ margin: '24px 0', border: 0, borderTop: '1px solid var(--border)' }} />
    <h3>Customer consent</h3>
    <p>Saving profile details does not change consent. Select a customer to review or record consent evidence separately.</p>
    <form onSubmit={ searchCustomers }>
      <label style={{ display: 'block', marginBottom: 12 }}>
        Find customer
        <input
          aria-label="Find customer"
          value={ customerQuery }
          onChange={ event => {
            setCustomerQuery( event.target.value );
            setSelectedContactId( '' );
            setCustomerMatches( [] );
            setCustomerSearchMessage( '' );
          } }
          style={{ display: 'block', width: '100%', padding: 10, border: '1px solid var(--border)', borderRadius: 8 }}
        />
      </label>
      <button type="submit" disabled={ searchingCustomers || !customerQuery.trim() }>
        { searchingCustomers ? 'Searching…' : 'Search customers' }
      </button>
    </form>
    { customerSearchMessage && <p role="status">{ customerSearchMessage }</p> }
    { customerMatches.length > 0 && (
      <div aria-label="Customer search results" style={{ display: 'grid', gap: 8, marginTop: 12 }}>
        { customerMatches.map( contact => {
          const label = contact.name || contact.phone || contact.contactId;
          const publicId = contact.customerDisplayId || contact.customerUuid || contact.contactId;
          return <button key={ contact.contactId } type="button"
            onClick={ () => setSelectedContactId( contact.contactId ) }>
            { label } · { publicId }
          </button>;
        } ) }
      </div>
    ) }
    { selectedContactId && <ConsentPanel contactId={ selectedContactId } /> }
  </section>;
}
