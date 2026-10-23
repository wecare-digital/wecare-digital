import React, { useEffect, useState } from 'react';
import * as api from '../../../api/client';
import { useToastContext } from '../../../contexts/ToastContext';
import ConsentPanel from '../customers/ConsentPanel';

const CONFIG_KEY = 'subscribe_messages_config';
const TRIGGER_CONFIG_KEY = 'flow_triggers_config';
const F001_FLOW_ID = '2413873616105042';
const F001_FLOW_CODE = 'WD-F001-SUBSCRIBE-PROFILE';
type TriggerConfig = {
  enabled: boolean;
  keywords: string[];
  flowId: string;
  entryMode: 'keyword_interactive';
  message: { body: string; footer: string; flowCta: string };
};
const DEFAULT_TRIGGER: TriggerConfig = {
  enabled: false,
  keywords: [ 'subscribe', 'signup', 'sign up', 'register', 'join', '/subscribe' ],
  flowId: F001_FLOW_ID,
  entryMode: 'keyword_interactive',
  message: { body: 'Save your details for faster service on WECARE.DIGITAL.', footer: 'WECARE.DIGITAL', flowCta: 'Subscribe' },
};
const FIELD_POLICY = [
  [ 'Full name', 'name', 'Yes', 'Customer editable', '200' ],
  [ 'WhatsApp username', 'profileUsername', 'Yes', 'Customer editable; never Meta username', '50' ],
  [ 'Organization', 'companyName', 'Yes', 'Customer editable', '200' ],
  [ 'Job title', 'designation', 'Yes', 'Customer editable', '200' ],
  [ 'Address', 'checkoutDeliveryAddress', 'Yes', 'Customer editable; shared validator', 'Field limits' ],
  [ 'Phone', 'phone', 'Yes', 'Read-only / provider identity', '—' ],
  [ 'Meta username', 'username', 'Yes', 'Read-only / provider identity', '—' ],
  [ 'BSUID', 'bsuid', 'Yes', 'Read-only / provider identity', '—' ],
  [ 'Customer ID', 'customerUuid', 'Yes', 'Read-only / server identity', '—' ],
  [ 'Consent', 'consent ledger', 'No', 'Separate evidence workflow', '—' ],
] as const;
type Scenario = 'newCustomer' | 'returningCustomer';
type Copy = { body: string; flowCta: string; confirmation: string };
type Messages = Record<Scenario, Copy>;
const DEFAULTS: Messages = {
  newCustomer: {
    body: 'Welcome to WECARE.DIGITAL. Add your name, WhatsApp username, and address to complete your customer profile.',
    flowCta: 'Subscribe', confirmation: 'Your details have been saved.',
  },
  returningCustomer: {
    body: 'Welcome back to WECARE.DIGITAL. Review your saved details and update your WhatsApp username or address whenever needed.',
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
  const [ trigger, setTrigger ] = useState<TriggerConfig>( DEFAULT_TRIGGER );
  const [ triggerSaving, setTriggerSaving ] = useState( false );
  const [ registryFlow, setRegistryFlow ] = useState<api.FlowRegistryItem | null>( null );

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
  const loadRouting = async () => {
    try {
      const [ triggerResult, flows ] = await Promise.all( [
        api.getSystemConfigResult( TRIGGER_CONFIG_KEY ),
        api.listFlowRegistry(),
      ] );
      const current = triggerResult.ok && triggerResult.data.config && typeof triggerResult.data.config === 'object'
        ? triggerResult.data.config.subscribe : null;
      setTrigger( {
        ...DEFAULT_TRIGGER,
        ...( current || {} ),
        flowId: F001_FLOW_ID,
        entryMode: 'keyword_interactive',
        message: { ...DEFAULT_TRIGGER.message, ...( current?.message || {} ) },
      } );
      setRegistryFlow( flows.find( row => row.flowId === F001_FLOW_ID || row.flowCode === F001_FLOW_CODE ) || null );
    } catch {
      setTrigger( DEFAULT_TRIGGER );
    }
  };
  useEffect( () => { void load(); void loadRouting(); }, [] );

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

  const saveRouting = async ( event: React.FormEvent ) => {
    event.preventDefault();
    const published = registryFlow?.status === 'PUBLISHED';
    const normalized: TriggerConfig = {
      ...trigger,
      enabled: published ? trigger.enabled : false,
      flowId: F001_FLOW_ID,
      entryMode: 'keyword_interactive',
      keywords: trigger.keywords.map( keyword => keyword.trim().toLowerCase() ).filter( Boolean ),
      message: {
        body: trigger.message.body.trim(),
        footer: 'WECARE.DIGITAL',
        flowCta: trigger.message.flowCta.trim(),
      },
    };
    if ( !normalized.keywords.length || !normalized.message.body || !normalized.message.flowCta ) {
      toast.error( 'Keywords, opening message, and button text are required.' ); return;
    }
    if ( normalized.message.flowCta.length > 20 ) { toast.error( 'Button text must be 20 characters or fewer.' ); return; }
    setTriggerSaving( true );
    try {
      const result = await api.getSystemConfigResult( TRIGGER_CONFIG_KEY );
      const all = result.ok && result.data.config && typeof result.data.config === 'object' ? { ...result.data.config } : {};
      all.subscribe = normalized;
      if ( !await api.updateSystemConfig( TRIGGER_CONFIG_KEY, all ) ) throw new Error( 'Routing save could not be confirmed.' );
      setTrigger( normalized );
      toast.success( published ? 'F001 routing saved.' : 'F001 routing saved disabled while the Flow is DRAFT.' );
    } catch ( err ) {
      toast.error( err instanceof Error ? err.message : 'Could not save F001 routing.' );
    } finally { setTriggerSaving( false ); }
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

  const published = registryFlow?.status === 'PUBLISHED';
  return <section aria-label="Subscribe settings">
    <h3>F001 · Subscribe</h3>
    <p>One control surface for the native Subscribe Flow, its keyword entry message, prefill/write policy, and customer-facing confirmation. F001 does not use a marketing template.</p>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(180px,1fr))', gap: 10, margin: '12px 0 20px' }}>
      <div><strong>Meta Flow</strong><br />{ F001_FLOW_ID }</div>
      <div><strong>Name</strong><br />{ F001_FLOW_CODE }</div>
      <div><strong>Status</strong><br />{ registryFlow?.status || 'DRAFT' }</div>
      <div><strong>Entry</strong><br />Keyword → native Flow</div>
      <div><strong>Endpoint</strong><br />/api/wa-business/flow-data</div>
    </div>
    { !published && <p role="status"><strong>Customer launch is OFF.</strong> F001 remains DRAFT. Saving routing cannot enable customer sends until the registry reports PUBLISHED.</p> }

    <h3>Keyword entry</h3>
    <p>Used only inside the WhatsApp customer-service window. Paid/post-payment Flows use their own template/event entry mode and cannot be opened by this keyword dispatcher.</p>
    <form onSubmit={ saveRouting }>
      <fieldset disabled={ triggerSaving } style={{ border: '1px solid var(--border)', borderRadius: 12, padding: 16 }}>
        <label style={{ display: 'block', marginBottom: 12 }}>
          Keywords
          <input value={ trigger.keywords.join( ', ' ) }
            onChange={ event => setTrigger( previous => ({ ...previous, keywords: event.target.value.split( ',' ) }) ) }
            style={{ display: 'block', width: '100%', padding: 10, border: '1px solid var(--border)', borderRadius: 8 }} />
        </label>
        <label style={{ display: 'block', marginBottom: 12 }}>
          Opening message
          <textarea rows={ 3 } maxLength={ 1024 } value={ trigger.message.body }
            onChange={ event => setTrigger( previous => ({ ...previous, message: { ...previous.message, body: event.target.value } }) ) }
            style={{ display: 'block', width: '100%', padding: 10, border: '1px solid var(--border)', borderRadius: 8 }} />
        </label>
        <label style={{ display: 'block', marginBottom: 12 }}>
          Button text
          <input maxLength={ 20 } value={ trigger.message.flowCta }
            onChange={ event => setTrigger( previous => ({ ...previous, message: { ...previous.message, flowCta: event.target.value } }) ) }
            style={{ display: 'block', width: '100%', padding: 10, border: '1px solid var(--border)', borderRadius: 8 }} />
        </label>
        <label style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 12 }}>
          <input type="checkbox" checked={ published && trigger.enabled } disabled={ !published }
            onChange={ event => setTrigger( previous => ({ ...previous, enabled: event.target.checked } ) ) } />
          Enable typed-keyword launch
        </label>
        <button type="submit" disabled={ triggerSaving }>{ triggerSaving ? 'Saving…' : 'Save F001 routing' }</button>
      </fieldset>
    </form>

    <hr style={{ margin: '24px 0', border: 0, borderTop: '1px solid var(--border)' }} />
    <h3>Subscribe messages</h3>
    <p>Edit new/returning customer copy and the confirmation returned by the data-exchange backend. Customer ID is displayed separately.</p>
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
    <h3>Prefill and write policy</h3>
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead><tr>
          { [ 'Flow field', 'Contact field', 'Prefill', 'Update policy', 'Limit' ].map( heading => <th key={ heading } style={{ textAlign: 'left', padding: 8, borderBottom: '1px solid var(--border)' }}>{ heading }</th> ) }
        </tr></thead>
        <tbody>
          { FIELD_POLICY.map( row => <tr key={ row[ 0 ] }>
            { row.map( ( cell, index ) => <td key={ index } style={{ padding: 8, borderBottom: '1px solid var(--border)' }}>{ cell }</td> ) }
          </tr> ) }
        </tbody>
      </table>
    </div>

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
