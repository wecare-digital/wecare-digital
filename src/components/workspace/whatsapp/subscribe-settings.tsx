/**
 * F001 Subscribe control surface (WD-F001-SUBSCRIBE-PROFILE).
 *
 * One place where staff can see what launches F001, who may launch it, what it reads, writes
 * and protects, what the customer and staff see, its history and its health, and change the
 * parts that are meant to change without a deploy: keywords, the keyword switch, the
 * opening/confirmation copy, the FlowRegistry row and a controlled staff send.
 *
 * Every launch rule is enforced server-side (lambda_utils.flow_launch); this page shows the
 * server's own decision from /wa-business/flow-launch-status rather than recomputing it.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import * as api from '../../../api/client';
import { useToastContext } from '../../../contexts/ToastContext';
import { useConfirm } from '../../../contexts/ConfirmContext';
import ConsentPanel from '../customers/ConsentPanel';
import FlowFunnel from './flow-funnel';
import { CANONICAL_FLOWS, CANONICAL_CONTRACTS } from '../../../lib/canonicalFlows';

const CAPABILITY = 'subscribe';
const CONTRACT = CANONICAL_CONTRACTS[ CAPABILITY ];
const FLOW = CANONICAL_FLOWS[ CAPABILITY ];
const F001_FLOW_ID = FLOW.flowId || '';
const CONFIG_KEY = 'subscribe_messages_config';
const TRIGGER_CONFIG_KEY = 'flow_triggers_config';
const ENDPOINT = 'https://wecare.digital/api/wa-business/flow-data';
const FLOW_HUB_LINK = '/workspace/communications?view=manage&section=flows';
const MAX_KEYWORDS = 20;
const MAX_KEYWORD_CHARS = 60;
/** Commands the inbound dispatcher answers before Flow keywords; a keyword here could never fire. */
const RESERVED_KEYWORDS = [
  'hi', 'hello', 'hey', 'menu', 'main menu', 'start', 'get started', 'help', 'faq', 'pay', '/pay',
  'orders', 'my orders', 'customer id', 'my customer id', 'my id', 'vault', 'review', 'leave review',
  'feedback', 'submit request', 'drop docs', 'shipments', 'request amendment',
];

/**
 * The F001 field contract: Flow field -> backend key -> canonical Contact field, where the
 * prefill comes from, whether the customer may change it, the server-side validation, who
 * owns the value, whether approval is needed and where staff see it.
 */
const FIELD_CONTRACT: readonly ( readonly [ string, string, string, string, string, string, string, string, string ] )[] = [
  [ 'Full name', 'full_name', 'name', 'Contact row', 'Yes', 'Required, max 200, no control characters', 'Customer-declared', 'No', 'Inbox profile, Customers' ],
  [ 'WhatsApp username', 'username', 'profileUsername', 'Contact row', 'Yes', 'Optional, max 50', 'Customer-declared; never the Meta username', 'No', 'Inbox "WECARE.DIGITAL profile name"' ],
  [ 'Organization', 'company_name', 'companyName', 'Contact row', 'Yes', 'Optional, max 200', 'Customer-declared', 'No', 'Inbox profile, Customers' ],
  [ 'Job title', 'designation', 'designation', 'Contact row', 'Yes', 'Optional, max 200', 'Customer-declared', 'No', 'Inbox profile, Customers' ],
  [ 'Street address', 'address_line1', 'checkoutDeliveryAddress.addressLine1', 'Saved address', 'Yes', 'Required, max 200 (website validator)', 'Customer-declared', 'No', 'Inbox address' ],
  [ 'Apartment / suite / unit', 'address_line2', 'checkoutDeliveryAddress.addressLine2', 'Saved address', 'Yes', 'Optional, max 200', 'Customer-declared', 'No', 'Inbox address' ],
  [ 'Landmark / neighborhood', 'locality', 'checkoutDeliveryAddress.locality', 'Saved address', 'Yes', 'Optional, max 100', 'Customer-declared', 'No', 'Inbox address' ],
  [ 'City', 'city', 'checkoutDeliveryAddress.city', 'Saved address', 'Yes', 'Required, max 100', 'Customer-declared', 'No', 'Inbox address' ],
  [ 'State / region', 'state', 'checkoutDeliveryAddress.state', 'Saved address', 'Yes', 'Required, max 100', 'Customer-declared', 'No', 'Inbox address' ],
  [ 'Postal code', 'postal_code', 'checkoutDeliveryAddress.postalCode', 'Saved address', 'Yes', 'Required, max 100, any country', 'Customer-declared', 'No', 'Inbox address' ],
  [ 'Country', 'country', 'checkoutDeliveryAddress.country / countryCode', 'Saved ISO code; India for new', 'Yes', 'One of 195 listed countries; ISO code set by the server', 'Customer-declared', 'No', 'Inbox address' ],
  [ 'Linked WhatsApp number', 'phone_number', 'phone', 'Server-issued session', 'No', 'Display only; never read as identity', 'WhatsApp-verified identity', 'Never written', 'Inbox identity' ],
  [ 'Customer ID', 'customer_id', 'customerUuid (shown as C-…)', 'Contact row', 'No', 'Display only', 'Server-minted once', 'Never written', 'Inbox identity' ],
  [ '(hidden) revision guard', 'profile_revision, updated_at', 'subscribeProfileRevision, updatedAt', 'Contact row', 'No', 'Must match the row at save', 'System', '—', '—' ],
  [ '(not in Flow) Meta username, BSUID', '—', 'username, bsuid, parentBsuid', '—', 'No', '—', 'Meta', 'Never written', 'Inbox identity' ],
  [ '(not in Flow) Retention lock', '—', 'locked, lockedReason', '—', 'No', 'Not an edit freeze: locked and paid customers still save', 'System', 'Never written', 'Customers' ],
  [ '(not in Flow) Consent', '—', 'consentLedger, optIn*, allowlist*', '—', 'No', 'Separate evidence workflow below', 'Evidence ledger', 'Never written', 'Customer consent panel' ],
];

type Scenario = 'newCustomer' | 'returningCustomer';
type Copy = { body: string; flowCta: string; confirmation: string };
type Messages = Record<Scenario, Copy>;
/** Mirrors lambda_utils/subscribe_messages.py DEFAULTS, used when nothing is saved. */
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

const card: React.CSSProperties = { border: '1px solid var(--border)', borderRadius: 12, padding: 16, margin: '12px 0', background: '#fff' };
const button: React.CSSProperties = { minHeight: 40, padding: '8px 14px', border: '1px solid var(--border)', borderRadius: 8, background: '#fff', cursor: 'pointer', fontWeight: 600 };
const input: React.CSSProperties = { display: 'block', width: '100%', padding: 10, border: '1px solid var(--border)', borderRadius: 8, fontSize: 16 };
const cell: React.CSSProperties = { textAlign: 'left', padding: 8, borderBottom: '1px solid var(--border)', verticalAlign: 'top' };

const normalizeKeywords = ( raw: string ): string[] => {
  const out: string[] = [];
  for ( const part of raw.split( ',' ) )
  {
    const keyword = part.split( /\s+/ ).filter( Boolean ).join( ' ' ).toLowerCase();
    if ( keyword && !out.includes( keyword ) ) out.push( keyword );
  }
  return out;
};

const formatEpoch = ( value?: number ) => value ? new Date( value * 1000 ).toLocaleString( 'en-US' ) : '—';

type Check = { label: string; state: string; ok: boolean; requirement: string };
type HistoryRow = { code: string; total: number | null; error: string };

const fetchStatus = () => api.getFlowLaunchStatus( CAPABILITY );

/** Saved copy over DEFAULTS; a failed or malformed read is an error, never silent defaults. */
async function fetchMessages (): Promise<{ messages: Messages | null; error: string }> {
  const result = await api.getSystemConfigResult( CONFIG_KEY );
  if ( !result.ok ) return { messages: null, error: result.failure.message || 'Could not load Subscribe messages.' };
  const stored = result.data.config;
  if ( stored !== null && ( typeof stored !== 'object' || Array.isArray( stored ) ) )
    return { messages: null, error: 'Saved Subscribe messages have an invalid format.' };
  const next: Messages = { newCustomer: { ...DEFAULTS.newCustomer }, returningCustomer: { ...DEFAULTS.returningCustomer } };
  for ( const scenario of SCENARIOS ) for ( const field of FIELDS )
  {
    const value = stored?.[ scenario ]?.[ field ];
    if ( typeof value === 'string' ) next[ scenario ][ field ] = value;
  }
  return { messages: next, error: '' };
}

/** Submission counts under the canonical code and the code earlier F001 rows used. */
async function fetchHistory (): Promise<HistoryRow[]> {
  const codes = [ CONTRACT.flowCode, ...CONTRACT.legacyFlowCodes ];
  return Promise.all( codes.map( async code => {
    const result = await api.getFlowSubmissionStatsResult( code );
    return result.ok
      ? { code, total: result.data.total, error: '' }
      : { code, total: null, error: result.failure.kind === 'forbidden' ? 'Operator role required' : result.failure.message };
  } ) );
}

export default function SubscribeSettings () {
  const toast = useToastContext();
  const confirm = useConfirm();
  const [ status, setStatus ] = useState<api.FlowLaunchStatus | null>( null );
  const [ statusError, setStatusError ] = useState( '' );
  const [ statusLoading, setStatusLoading ] = useState( true );
  const [ registrySaving, setRegistrySaving ] = useState( false );
  const [ keywordText, setKeywordText ] = useState( CONTRACT.defaultKeywords.join( ', ' ) );
  const [ keywordEnabled, setKeywordEnabled ] = useState( false );
  const [ routingSaving, setRoutingSaving ] = useState( false );
  const [ messages, setMessages ] = useState<Messages>( DEFAULTS );
  const [ messagesReady, setMessagesReady ] = useState( false );
  const [ messagesError, setMessagesError ] = useState( '' );
  const [ messagesSaving, setMessagesSaving ] = useState( false );
  const [ history, setHistory ] = useState<HistoryRow[]>( [] );
  const [ customerQuery, setCustomerQuery ] = useState( '' );
  const [ customerMatches, setCustomerMatches ] = useState<api.Contact[]>( [] );
  const [ customerSearchMessage, setCustomerSearchMessage ] = useState( '' );
  const [ searchingCustomers, setSearchingCustomers ] = useState( false );
  const [ selectedContact, setSelectedContact ] = useState<api.Contact | null>( null );
  const [ sending, setSending ] = useState( false );
  const [ lastSend, setLastSend ] = useState<api.CanonicalFlowSendResult | null>( null );

  const applyStatus = useCallback( ( result: Awaited<ReturnType<typeof fetchStatus>> ) => {
    if ( result.ok )
    {
      setStatus( result.data );
      setStatusError( '' );
      setKeywordText( result.data.runtime.keywords.join( ', ' ) );
      setKeywordEnabled( result.data.runtime.enabled );
    } else
    {
      setStatus( null );
      setStatusError( result.failure.message || 'Launch status could not be read.' );
    }
    setStatusLoading( false );
  }, [] );

  const applyMessages = useCallback( ( loaded: Awaited<ReturnType<typeof fetchMessages>> ) => {
    setMessagesError( loaded.error );
    setMessagesReady( !loaded.error );
    if ( loaded.messages ) setMessages( loaded.messages );
  }, [] );

  // State is applied only after the requests resolve, and dropped after unmount.
  useEffect( () => {
    let cancelled = false;
    ( async () => {
      const [ loadedStatus, loadedMessages, loadedHistory ] = await Promise.all( [ fetchStatus(), fetchMessages(), fetchHistory() ] );
      if ( cancelled ) return;
      applyStatus( loadedStatus );
      applyMessages( loadedMessages );
      setHistory( loadedHistory );
    } )();
    return () => { cancelled = true; };
  }, [ applyStatus, applyMessages ] );

  const refreshStatus = async () => {
    setStatusLoading( true );
    applyStatus( await fetchStatus() );
  };

  const retryMessages = async () => {
    setMessagesError( '' );
    applyMessages( await fetchMessages() );
  };

  const registry = status?.registry || null;
  const registryPublished = registry?.status === 'PUBLISHED';
  const canonicalPublished = status?.canonical.status === 'PUBLISHED';

  const checks: Check[] = useMemo( () => {
    if ( !status ) return [];
    const meta = registry?.metaStatus || '';
    return [
      { label: 'Canonical Flow record (code)', state: status.canonical.status, ok: canonicalPublished, requirement: 'PUBLISHED' },
      { label: 'FlowRegistry row', state: status.registryError ? `Unreadable (${status.registryError})` : registry ? registry.status : 'Missing', ok: registryPublished, requirement: 'PUBLISHED' },
      { label: 'Meta status (last sync)', state: meta ? `${meta} · ${formatEpoch( registry?.lastSyncedAt )}` : 'Not synced yet', ok: !meta || meta === 'PUBLISHED' || meta === 'THROTTLED', requirement: 'PUBLISHED when synced' },
      { label: 'Registry matches the F001 contract', state: status.registryProblems.length ? status.registryProblems.join( ' · ' ) : registry ? 'Consistent' : '—', ok: !!registry && status.registryProblems.length === 0, requirement: 'No contradictions' },
      { label: 'Keyword switch (Workspace)', state: status.runtime.readError ? `Unreadable (${status.runtime.readError})` : status.runtime.enabled ? 'ON' : 'OFF', ok: status.runtime.enabled, requirement: 'ON for keyword launch only' },
    ];
  }, [ status, registry, registryPublished, canonicalPublished ] );

  const saveRegistry = async ( patch: Partial<api.FlowRegistryItem>, success: string ) => {
    setRegistrySaving( true );
    const result = await api.upsertFlowRegistry( { flowId: F001_FLOW_ID, ...patch } );
    setRegistrySaving( false );
    if ( result.ok )
    {
      toast.success( success );
      void refreshStatus();
    } else toast.error( result.failure.kind === 'forbidden' ? 'Changing FlowRegistry requires the Admin role.' : result.failure.message );
  };

  const registerF001 = () => saveRegistry( {
    flowCode: CONTRACT.flowCode, flowName: CONTRACT.label, flowType: CONTRACT.flowType,
    wabaId: CONTRACT.wabaId, status: 'DRAFT', entryMode: CONTRACT.entryMode, entryTemplateName: '',
    requiresPayment: false, paymentAmount: 0, submissionPrefix: CONTRACT.submissionPrefix,
    endpointUri: ENDPOINT, flowVersion: '7.3', dataApiVersion: '3.0',
  }, 'F001 registered in FlowRegistry as DRAFT.' );

  const setRegistryStatus = async ( next: 'DRAFT' | 'PUBLISHED' ) => {
    const ok = await confirm( {
      title: next === 'PUBLISHED' ? 'Publish F001 in FlowRegistry?' : 'Return F001 to DRAFT?',
      message: next === 'PUBLISHED'
        ? 'Staff sends become possible. Customer keyword launch still needs the keyword switch to be ON.'
        : 'Customer keyword launch and staff sends stop immediately. Saved profiles and history are not changed.',
      confirmText: next === 'PUBLISHED' ? 'Mark PUBLISHED' : 'Return to DRAFT',
      danger: next === 'DRAFT',
    } );
    if ( ok ) await saveRegistry( { status: next }, next === 'PUBLISHED' ? 'FlowRegistry status is PUBLISHED.' : 'FlowRegistry status is DRAFT.' );
  };

  const saveRouting = async ( event: React.FormEvent ) => {
    event.preventDefault();
    const keywords = normalizeKeywords( keywordText );
    if ( !keywords.length ) { toast.error( 'Add at least one keyword.' ); return; }
    if ( keywords.length > MAX_KEYWORDS ) { toast.error( `Use ${MAX_KEYWORDS} keywords or fewer.` ); return; }
    const tooLong = keywords.find( keyword => keyword.length > MAX_KEYWORD_CHARS );
    if ( tooLong ) { toast.error( `Keywords allow ${MAX_KEYWORD_CHARS} characters: "${tooLong.slice( 0, 20 )}…"` ); return; }
    const reserved = keywords.filter( keyword => RESERVED_KEYWORDS.includes( keyword ) );
    if ( reserved.length ) { toast.error( `These are already WhatsApp commands: ${reserved.join( ', ' )}` ); return; }
    const enable = keywordEnabled && registryPublished && canonicalPublished;
    setRoutingSaving( true );
    try
    {
      // Read-modify-write of the whole trigger map. A failed read saves nothing, so other
      // Flows' triggers can never be replaced by a partial copy.
      const current = await api.getSystemConfigResult( TRIGGER_CONFIG_KEY );
      if ( !current.ok ) throw new Error( `Keyword settings could not be read, so nothing was saved: ${current.failure.message}` );
      const stored = current.data.config;
      const all: Record<string, unknown> = stored && typeof stored === 'object' && !Array.isArray( stored ) ? { ...stored } : {};
      for ( const [ key, value ] of Object.entries( all ) )
      {
        if ( key === CAPABILITY || !value || typeof value !== 'object' ) continue;
        const theirs = Array.isArray( ( value as { keywords?: unknown } ).keywords ) ? ( value as { keywords: unknown[] } ).keywords : [];
        const clash = keywords.filter( keyword => theirs.some( other => typeof other === 'string' && other.trim().toLowerCase() === keyword ) );
        if ( clash.length ) throw new Error( `Already used by the "${key}" trigger: ${clash.join( ', ' )}` );
      }
      all[ CAPABILITY ] = { enabled: enable, keywords, flowId: F001_FLOW_ID, entryMode: CONTRACT.entryMode };
      if ( !await api.updateSystemConfig( TRIGGER_CONFIG_KEY, all ) ) throw new Error( 'Keyword save could not be confirmed. Your edits are still here.' );
      toast.success( enable ? 'Keywords saved. Keyword launch is ON.' : 'Keywords saved. Keyword launch is OFF.' );
      void refreshStatus();
    } catch ( err )
    {
      toast.error( err instanceof Error ? err.message : 'Could not save F001 keywords.' );
    } finally { setRoutingSaving( false ); }
  };

  const saveMessages = async ( event: React.FormEvent ) => {
    event.preventDefault();
    if ( !messagesReady ) return;
    const next: Messages = { newCustomer: { ...messages.newCustomer }, returningCustomer: { ...messages.returningCustomer } };
    for ( const scenario of SCENARIOS ) for ( const field of FIELDS )
    {
      next[ scenario ][ field ] = next[ scenario ][ field ].trim();
      const limit = field === 'flowCta' ? 20 : 1024;
      if ( !next[ scenario ][ field ] || next[ scenario ][ field ].length > limit )
      {
        toast.error( 'Each message is required. Button labels allow 20 characters; messages allow 1024.' ); return;
      }
    }
    setMessagesSaving( true );
    try
    {
      if ( !await api.updateSystemConfig( CONFIG_KEY, next ) ) throw new Error( 'Save could not be confirmed. Your edits are still here.' );
      setMessages( next );
      toast.success( 'Subscribe messages saved.' );
    } catch ( err ) { toast.error( err instanceof Error ? err.message : 'Could not save Subscribe messages.' ); }
    finally { setMessagesSaving( false ); }
  };

  const searchCustomers = async ( event: React.FormEvent ) => {
    event.preventDefault();
    const query = customerQuery.trim();
    setSelectedContact( null );
    setCustomerMatches( [] );
    setCustomerSearchMessage( '' );
    if ( !query ) return;
    setSearchingCustomers( true );
    try
    {
      const result = await api.searchContactsResult( query );
      if ( !result.ok ) { setCustomerSearchMessage( result.failure.message || 'Customer search unavailable.' ); return; }
      setCustomerMatches( result.data );
      if ( result.data.length === 0 ) setCustomerSearchMessage( 'No matching customers found.' );
    } finally { setSearchingCustomers( false ); }
  };

  const sendToCustomer = async () => {
    if ( !selectedContact?.phone ) return;
    const ok = await confirm( {
      title: 'Send F001 Subscribe?',
      message: `${selectedContact.name || 'This customer'} receives the Subscribe Flow on WhatsApp now. The send is recorded under your name. WhatsApp only delivers it inside the customer-service window.`,
      confirmText: 'Send Subscribe',
    } );
    if ( !ok ) return;
    setSending( true );
    setLastSend( null );
    const result = await api.sendCanonicalFlow( CAPABILITY, selectedContact.phone );
    setSending( false );
    if ( result.ok )
    {
      setLastSend( result.data );
      toast.success( 'Subscribe Flow sent.' );
    } else toast.error( result.failure.kind === 'forbidden' ? 'Sending F001 requires the Operator or Admin role.' : result.failure.message );
  };

  return <section aria-label="F001 Subscribe control surface">
    <h3 style={ { marginBottom: 4 } }>{ CONTRACT.flowNumber } · { CONTRACT.label }</h3>
    <p style={ { marginTop: 0 } }>
      Saves a customer&apos;s WECARE.DIGITAL profile (name, profile name, organization, job title and one address) on their
      contact record, and records each save in Flow history. It is not a marketing subscription: it never grants consent.
    </p>

    <div style={ card } aria-label="Launch status">
      <div style={ { display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap', alignItems: 'center' } }>
        <strong>Launch status</strong>
        <button type="button" style={ button } onClick={ () => void refreshStatus() } disabled={ statusLoading }>{ statusLoading ? 'Checking…' : 'Refresh status' }</button>
      </div>
      { statusError && <p role="alert">Launch status unavailable: { statusError }</p> }
      { status && <>
        <p role="status" style={ { fontSize: 15 } }>
          <strong>Customer keyword launch: { status.keywordLaunch.allowed ? 'ON' : 'OFF' }.</strong> { status.keywordLaunch.allowed ? 'Customers who type a keyword below receive the Flow.' : status.keywordLaunch.explanation }
          <br />
          <strong>Staff send (your role): { status.manualLaunch.allowed ? 'available' : 'unavailable' }.</strong> { status.manualLaunch.allowed ? 'Use “Send to a customer” below.' : status.manualLaunch.explanation }
        </p>
        <div style={ { overflowX: 'auto' } }>
          <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: 13 } }>
            <thead><tr>{ [ 'Control', 'Current state', 'Needed', '' ].map( heading => <th key={ heading } scope="col" style={ cell }>{ heading }</th> ) }</tr></thead>
            <tbody>{ checks.map( check => <tr key={ check.label }>
              <th scope="row" style={ { ...cell, fontWeight: 500 } }>{ check.label }</th>
              <td style={ cell }>{ check.state }</td>
              <td style={ cell }>{ check.requirement }</td>
              <td style={ cell } aria-label={ check.ok ? 'Satisfied' : 'Not satisfied' }>{ check.ok ? '✓' : '✗' }</td>
            </tr> ) }</tbody>
          </table>
        </div>
        <div style={ { display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 12 } }>
          { !registry && !status.registryError && <button type="button" style={ button } disabled={ registrySaving } onClick={ () => void registerF001() }>Register F001 in FlowRegistry (DRAFT)</button> }
          { registry && !registryPublished && canonicalPublished && <button type="button" style={ button } disabled={ registrySaving } onClick={ () => void setRegistryStatus( 'PUBLISHED' ) }>Mark registry PUBLISHED</button> }
          { registry && registryPublished && <button type="button" style={ button } disabled={ registrySaving } onClick={ () => void setRegistryStatus( 'DRAFT' ) }>Return registry to DRAFT</button> }
        </div>
        <p style={ { fontSize: 12, color: 'var(--text-muted)' } }>Registry changes need the Admin role. Meta status comes from “Sync from Meta” and never changes the registry status by itself.</p>
      </> }
    </div>

    <div style={ card } aria-label="Flow identity">
      <strong>Flow identity</strong>
      <div style={ { display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(200px,1fr))', gap: 10, marginTop: 10, fontSize: 13 } }>
        { [
          [ 'Flow code', CONTRACT.flowCode ],
          [ 'Meta Flow ID', F001_FLOW_ID ],
          [ 'Meta name', FLOW.metaName || '—' ],
          [ 'WABA', `WABA 1 · ${CONTRACT.wabaId}` ],
          [ 'Entry model', 'Keyword → native Flow (keyword_interactive)' ],
          [ 'Approved template', 'None. Keyword Flows never use a template' ],
          [ 'Payment', 'Not required (contract)' ],
          [ 'Internal events', 'None' ],
          [ 'Endpoint', status?.endpoint || ENDPOINT ],
          [ 'Submission prefix', CONTRACT.submissionPrefix ],
          [ 'History flow code', CONTRACT.flowCode ],
          [ 'Flow link lifetime', status ? `${Math.round( status.session.ttlSeconds / 3600 )} hours, one save` : '—' ],
          [ 'Meta JSON version', registry?.jsonVersion || '—' ],
          [ 'Registry last changed', registry ? `${formatEpoch( registry.updatedAt )}${registry.updatedBy ? ` by ${registry.updatedBy}` : ''}` : '—' ],
        ].map( ( [ label, value ] ) => <div key={ label }><strong>{ label }</strong><br /><span style={ { wordBreak: 'break-word' } }>{ value }</span></div> ) }
      </div>
    </div>

    <div style={ card } aria-label="Who can launch F001">
      <strong>Who can launch it</strong>
      <ul style={ { margin: '8px 0 0', paddingLeft: 20, fontSize: 14 } }>
        <li>Customers, by typing one exact keyword in the open WhatsApp customer-service window, only while customer keyword launch is ON.</li>
        <li>Operators and Admins, with “Send to a customer” below. Each send is recorded with the sender&apos;s identity. It works before keyword launch is ON, so the Flow can be tested first.</li>
        <li>Never through payment, an approved template or an internal event. The F001 contract rejects those settings.</li>
        <li>Each Flow message carries a one-time link valid for 24 hours. An unknown, expired or already-used link is refused and its button is disabled.</li>
      </ul>
    </div>

    <form onSubmit={ saveRouting } style={ card } aria-label="Keyword entry">
      <strong>Keyword entry</strong>
      <p style={ { fontSize: 13 } }>Matching is exact: the whole message, ignoring capital letters and surrounding spaces. The opening message is the New / Returning customer copy below.</p>
      <fieldset disabled={ routingSaving } style={ { border: 0, padding: 0, margin: 0 } }>
        <label style={ { display: 'block', marginBottom: 12 } }>
          Keywords (comma-separated)
          <input value={ keywordText } onChange={ event => setKeywordText( event.target.value ) } style={ input } />
        </label>
        <label style={ { display: 'flex', gap: 8, alignItems: 'center', marginBottom: 12 } }>
          <input type="checkbox" checked={ keywordEnabled && registryPublished && canonicalPublished } disabled={ !registryPublished || !canonicalPublished }
            onChange={ event => setKeywordEnabled( event.target.checked ) } />
          Customer keyword launch ON
        </label>
        { ( !registryPublished || !canonicalPublished ) && <p role="status" style={ { fontSize: 13 } }>The switch unlocks when the canonical record and the FlowRegistry row are both PUBLISHED.</p> }
        <button type="submit" style={ button }>{ routingSaving ? 'Saving…' : 'Save keywords' }</button>
      </fieldset>
    </form>

    <form onSubmit={ saveMessages } style={ card } aria-label="Subscribe messages">
      <strong>What the customer sees</strong>
      <p style={ { fontSize: 13 } }>
        Opening message and button (the customer is “Returning” when a saved address exists), then the screens Subscribe → Address → Review → Subscribed.
        Correction messages name the screen to fix. The confirmation below appears on the final screen with the Customer ID.
      </p>
      { messagesError && <p role="alert">{ messagesError } <button type="button" style={ button } onClick={ () => void retryMessages() }>Retry loading messages</button></p> }
      { !messagesReady && !messagesError && <p>Loading Subscribe messages…</p> }
      <fieldset disabled={ !messagesReady || messagesSaving } style={ { border: 0, padding: 0, margin: 0 } }>
        { SCENARIOS.map( scenario => <fieldset key={ scenario } style={ { margin: '12px 0', padding: 12, border: '1px solid var(--border)', borderRadius: 12 } }>
          <legend>{ scenario === 'newCustomer' ? 'New customer' : 'Returning customer' }</legend>
          { FIELDS.map( field => <label key={ field } style={ { display: 'block', marginBottom: 12 } }>
            { field === 'body' ? 'Opening message' : field === 'flowCta' ? 'Button text' : 'Confirmation inside Flow' }
            <textarea aria-label={ `${scenario} ${field}` } required maxLength={ field === 'flowCta' ? 20 : 1024 }
              rows={ field === 'flowCta' ? 1 : 3 } value={ messages[ scenario ][ field ] }
              onChange={ event => setMessages( previous => ( { ...previous, [ scenario ]: { ...previous[ scenario ], [ field ]: event.target.value } } ) ) }
              style={ input } />
          </label> ) }
        </fieldset> ) }
        <button type="submit" style={ button }>{ messagesSaving ? 'Saving…' : 'Save Subscribe messages' }</button>
      </fieldset>
    </form>

    <div style={ card } aria-label="Send to a customer">
      <strong>Send to a customer</strong>
      <p style={ { fontSize: 13 } }>Controlled QA and support. Operator or Admin only.</p>
      <form onSubmit={ searchCustomers }>
        <label style={ { display: 'block', marginBottom: 8 } }>
          Find customer
          <input aria-label="Find customer" value={ customerQuery } style={ input }
            onChange={ event => { setCustomerQuery( event.target.value ); setSelectedContact( null ); setCustomerMatches( [] ); setCustomerSearchMessage( '' ); } } />
        </label>
        <button type="submit" style={ button } disabled={ searchingCustomers || !customerQuery.trim() }>{ searchingCustomers ? 'Searching…' : 'Search customers' }</button>
      </form>
      { customerSearchMessage && <p role="status">{ customerSearchMessage }</p> }
      { customerMatches.length > 0 && <div aria-label="Customer search results" style={ { display: 'grid', gap: 8, marginTop: 12 } }>
        { customerMatches.map( contact => <button key={ contact.contactId } type="button" style={ { ...button, textAlign: 'left', borderColor: selectedContact?.contactId === contact.contactId ? 'var(--accent)' : 'var(--border)' } }
          aria-pressed={ selectedContact?.contactId === contact.contactId } onClick={ () => setSelectedContact( contact ) }>
          { contact.name || 'Unnamed customer' } · { contact.customerDisplayId || contact.customerUuid || 'No Customer ID yet' }
        </button> ) }
      </div> }
      { selectedContact && <div style={ { marginTop: 12 } }>
        { selectedContact.phone
          ? <button type="button" style={ button } disabled={ sending || !status?.manualLaunch.allowed } onClick={ () => void sendToCustomer() }>{ sending ? 'Sending…' : 'Send Subscribe Flow' }</button>
          : <p role="status">This customer has no WhatsApp number on their profile.</p> }
        { status && !status.manualLaunch.allowed && <p role="status" style={ { fontSize: 13 } }>{ status.manualLaunch.explanation }</p> }
      </div> }
      { lastSend && <p role="status" style={ { fontSize: 13 } }>Sent (message { lastSend.messageId || 'accepted' }). The link expires { formatEpoch( lastSend.sessionExpiresAt ) }.</p> }
    </div>

    <div style={ card } aria-label="Health and history">
      <strong>Health and history</strong>
      <div style={ { margin: '8px 0 12px', fontSize: 13 } }>
        { history.map( row => <div key={ row.code }>
          Submissions filed as <code>{ row.code }</code>{ row.code !== CONTRACT.flowCode ? ' (before the canonical code)' : '' }: { row.total ?? `unavailable (${row.error})` }
        </div> ) }
        <a href={ FLOW_HUB_LINK }>Open Flow Hub for submissions, journeys and logs</a>
      </div>
      <FlowFunnel flowCode={ CONTRACT.flowCode } days={ 7 } />
    </div>

    <div style={ card } aria-label="Field contract">
      <strong>What F001 reads, writes and protects</strong>
      <p style={ { fontSize: 13 } }>
        The contact record is the current profile; Flow history is a record of each save and is never used to prefill. Prefill and save use the customer the
        server-issued Flow link belongs to, never a phone number or Customer ID sent in the form. A save is refused when the profile changed since the Flow opened.
      </p>
      <div style={ { overflowX: 'auto' } }>
        <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: 12 } }>
          <thead><tr>{ [ 'Flow field', 'Backend key', 'Contact field', 'Prefill from', 'Customer edits', 'Validation', 'Owner / trust', 'Approval', 'Staff see it in' ].map( heading => <th key={ heading } scope="col" style={ cell }>{ heading }</th> ) }</tr></thead>
          <tbody>{ FIELD_CONTRACT.map( row => <tr key={ row[ 0 ] }>{ row.map( ( value, index ) => index === 0
            ? <th key={ index } scope="row" style={ { ...cell, fontWeight: 500 } }>{ value }</th>
            : <td key={ index } style={ cell }>{ value }</td> ) }</tr> ) }</tbody>
        </table>
      </div>
    </div>

    <div style={ card } aria-label="Customer consent">
      <strong>Customer consent</strong>
      <p style={ { fontSize: 13 } }>Saving profile details never changes consent. Review or record consent evidence for the customer selected above.</p>
      { selectedContact ? <ConsentPanel contactId={ selectedContact.contactId } /> : <p style={ { fontSize: 13, color: 'var(--text-muted)' } }>Search for a customer above to open their consent ledger.</p> }
    </div>
  </section>;
}
