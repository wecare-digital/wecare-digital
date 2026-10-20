import React, { useEffect, useRef, useState } from 'react';
import * as api from '../../../api/client';
import ConsentPanel from '../customers/ConsentPanel';
import { useToastContext } from '../../../contexts/ToastContext';

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
  const [ query, setQuery ] = useState( '' );
  const [ results, setResults ] = useState<api.Contact[]>( [] );
  const [ selected, setSelected ] = useState<api.Contact | null>( null );
  const [ searching, setSearching ] = useState( false );
  const [ searchMessage, setSearchMessage ] = useState( '' );
  const searchRevision = useRef( 0 );

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

  const search = async ( event: React.FormEvent ) => {
    event.preventDefault();
    const revision = ++searchRevision.current;
    setSelected( null ); setResults( [] ); setSearchMessage( '' ); setSearching( true );
    try {
      const result = await api.searchContactsResult( query.trim(), 20 );
      if ( revision !== searchRevision.current ) return;
      if ( !result.ok ) {
        setSearchMessage( result.failure.message || 'Customer search failed. Please try again.' );
        return;
      }
      setResults( result.data );
      if ( !result.data.length ) setSearchMessage( 'No matching customers found.' );
    } catch { if ( revision === searchRevision.current ) setSearchMessage( 'Customer search failed. Please try again.' ); }
    finally { if ( revision === searchRevision.current ) setSearching( false ); }
  };

  return <section aria-label="Subscribe settings">
    <h3>Subscribe messages</h3>
    <p>Edit the message before the form opens and the confirmation shown inside the form. Customer ID is displayed separately.</p>
    <p>Flow 1386523953464380 stays in Draft. Saving wording does not publish the Flow or enable automatic sending. One-off send text can override the opening message.</p>
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
    <h3>Customer subscription consent</h3>
    <p>Find a customer to review or record opt-in and opt-out evidence. Saving profile details does not change consent. Message approval and identity verification are separate.</p>
    <form onSubmit={ search } style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
      <label>Find customer<input aria-label="Find customer" value={ query } onChange={ event => {
        ++searchRevision.current; setQuery( event.target.value ); setSelected( null ); setResults( [] ); setSearchMessage( '' ); setSearching( false );
      }} placeholder="Name or WhatsApp number" /></label>
      <button type="submit" disabled={ searching || !query.trim() }>{ searching ? 'Searching…' : 'Search customers' }</button>
    </form>
    { searchMessage && <p role="status">{ searchMessage }</p> }
    <ul>{ results.map( customer => <li key={ customer.contactId }>
      <button type="button" onClick={ () => setSelected( customer ) }>{ customer.name || customer.phone } · { customer.customerDisplayId || customer.phone }</button>
    </li> ) }</ul>
    { selected && <div><h4>{ selected.name || selected.phone } · { selected.customerDisplayId }</h4>
      <ConsentPanel key={ selected.contactId } contactId={ selected.contactId } />
    </div> }
  </section>;
}
