/**
 * SMS - AWS End User Messaging, campaigns, the TRAI DLT registry and read-only
 * history from retired providers.
 *
 * AWS End User Messaging is the only SMS provider. The Airtel, Sinch and classic
 * Pinpoint-template tabs were removed on 2026-09-19: the first two offered
 * sending through prohibited providers, and the third managed AWS templates that
 * cannot satisfy TRAI DLT. Their records remain reachable, read-only, under
 * "Legacy history".
 */
import React, { useState, useEffect, useCallback } from 'react';
import Layout from '../../../../components/Layout';
import SEO from '../../../../components/SEO';
import PageShell, { ShellTab } from '../../../../components/PageShell';
import Button from '../../../../components/ui/Button';
import Pagination from '../../../../components/ui/Pagination';
import Select, { type SelectOption } from '../../../../components/ui/Select';
import { useToastContext } from '../../../../contexts/ToastContext';
import { useConfirm } from '../../../../contexts/ConfirmContext';
import * as api from '../../../../api/client';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }
interface Contact { contactId: string; name: string; phone: string; }
interface SmsMessage {
  messageId: string; contactId: string; contactName?: string; phone: string;
  content: string; status: string; direction: string; messageType?: string;
  campaignId?: string; campaignName?: string; timestamp: string;
}
interface Campaign { id: string; name: string; recipients: number; sent: number; delivered: number; failed: number; createdAt: string; }
/** A retained record from a retired provider. Read-only; `provider` is as stored. */
interface LegacySmsMessage {
  messageId: string; phoneNumber: string; content: string; status: string;
  direction: string; dltTemplateId?: string; messageType?: string;
  provider: string; providerLabel: string; isHistorical: boolean;
  createdAt: number;
}
interface DLTTemplate { templateId: string; name: string; content: string; messageType: string; senderId: string; entityId: string; variables: string[]; status: string; createdAt: number; }

/**
 * Approved TRAI DLT template keys, for the send form's dropdown.
 *
 * The authoritative mapping is lambda_utils/comms/dlt.py on the server; the send
 * request carries only the KEY, and the server resolves the template id, entity
 * and sender. The ids below are shown to the operator for confirmation, never
 * sent. The registry at /sms-aws/dlt-templates reports builtinKeys so this list
 * can be checked against the server.
 */
const DLT_TEMPLATE_OPTIONS: { key: string; id: string; label: string }[] = [
  { key: 'ivr-default', id: '1007277993798259629', label: 'ivr-default — IVR / voice notifications' },
  { key: 'wa-alert', id: '1007284579074821763', label: 'wa-alert — WhatsApp alerts' },
  { key: 'wd_order', id: '1007723091207562020', label: 'wd_order — order notifications' },
];

/*
 * The option lists, hoisted. Each holds exactly the <option> rows it replaced, in the same
 * order, with the same values and the same visible text. The DLT list is derived from
 * DLT_TEMPLATE_OPTIONS above so the two can never drift: the send request carries only the
 * KEY and the server resolves the template id, entity and sender.
 */
const LEGACY_PROVIDER_OPTIONS: SelectOption[] = [
  { value: '', label: 'All retired providers' },
  { value: 'airtel', label: 'Airtel IQ (retired)' },
  { value: 'sinch', label: 'Sinch SMS (retired)' },
];
const SEND_TYPE_OPTIONS: SelectOption[] = [
  { value: 'PROMOTIONAL', label: 'Promotional' },
  { value: 'TRANSACTIONAL', label: 'Transactional' },
];
const DLT_KEY_OPTIONS: SelectOption[] = DLT_TEMPLATE_OPTIONS.map(
  t => ( { value: t.key, label: t.label } )
);
const TPL_MESSAGE_TYPE_OPTIONS: SelectOption[] =
  [ 'SERVICE_EXPLICIT', 'SERVICE_IMPLICIT', 'TRANSACTIONAL', 'PROMOTIONAL' ]
    .map( t => ( { value: t, label: t } ) );

/** LAYOUT ONLY - what `.sms-search`'s 200px/220px cap carried; the box is the trigger's. */
const LEGACY_PROVIDER_STYLE: React.CSSProperties = { width: 200, maxWidth: '100%' };

/** +91XXXXXXXXXX (12 digits incl. country code) routes via ap-south-1 + DLT. */
const isIndianDestination = ( phone: string ): boolean => {
  const digits = ( phone || '' ).replace( /\D/g, '' );
  return digits.startsWith( '91' ) && digits.length === 12;
};

const ITEMS_PER_PAGE = 25;
const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api';

const TABS: ShellTab[] = [
  { id: 'aws', label: 'AWS SMS' },
  { id: 'campaign', label: 'Campaign' },
  { id: 'templates', label: 'DLT Templates' },
  { id: 'legacy', label: 'Legacy history' },
];

const SmsPage: React.FC<PageProps> = ( { signOut, user, embedded } ) => {
  // AWS End User Messaging state
  const [ messages, setMessages ] = useState<SmsMessage[]>( [] );
  const [ campaigns, setCampaigns ] = useState<Campaign[]>( [] );
  const [ loading, setLoading ] = useState( true );
  const [ loadError, setLoadError ] = useState( false );
  const [ page, setPage ] = useState( 1 );
  const [ searchQuery, setSearchQuery ] = useState( '' );
  const [ directionFilter, setDirectionFilter ] = useState<'all' | 'inbound' | 'outbound'>( 'all' );
  const [ showSendModal, setShowSendModal ] = useState( false );
  const [ sendPhone, setSendPhone ] = useState( '' );
  const [ sendContent, setSendContent ] = useState( '' );
  const [ sendMessageType, setSendMessageType ] = useState( 'PROMOTIONAL' );
  const [ sendDltTemplateKey, setSendDltTemplateKey ] = useState( 'ivr-default' );
  const [ sending, setSending ] = useState( false );
  const [ showCampaignModal, setShowCampaignModal ] = useState( false );
  const [ campaignName, setCampaignName ] = useState( '' );
  const [ campaignContent, setCampaignContent ] = useState( '' );
  const [ selectedContacts, setSelectedContacts ] = useState<string[]>( [] );
  const [ campaignSending, setCampaignSending ] = useState( false );
  const [ contacts, setContacts ] = useState<Contact[]>( [] );
  const [ showContactPicker, setShowContactPicker ] = useState<'single' | 'campaign' | null>( null );
  const [ contactSearch, setContactSearch ] = useState( '' );
  const [ loadingContacts, setLoadingContacts ] = useState( false );
  const [ clearing, setClearing ] = useState( false );

  // DLT Templates state
  const [ dltTemplates, setDltTemplates ] = useState<DLTTemplate[]>( [] );
  const [ templatesLoading, setTemplatesLoading ] = useState( false );
  const [ showTemplateModal, setShowTemplateModal ] = useState( false );
  const [ tplId, setTplId ] = useState( '' );
  const [ tplName, setTplName ] = useState( '' );
  const [ tplContent, setTplContent ] = useState( '' );
  const [ tplMessageType, setTplMessageType ] = useState( 'SERVICE_EXPLICIT' );
  const [ tplSaving, setTplSaving ] = useState( false );
  // Edit template state
  const [ editingTemplate, setEditingTemplate ] = useState<DLTTemplate | null>( null );
  const [ showEditTemplateModal, setShowEditTemplateModal ] = useState( false );
  const [ editTplName, setEditTplName ] = useState( '' );
  const [ editTplContent, setEditTplContent ] = useState( '' );
  const [ editTplMessageType, setEditTplMessageType ] = useState( 'SERVICE_IMPLICIT' );
  const [ editTplSaving, setEditTplSaving ] = useState( false );
  const [ seeding, setSeeding ] = useState( false );

  // Legacy history state (read-only view over retired-provider records)
  const [ legacyMessages, setLegacyMessages ] = useState<LegacySmsMessage[]>( [] );
  const [ legacyLoading, setLegacyLoading ] = useState( false );
  const [ legacyError, setLegacyError ] = useState( '' );
  const [ legacyProvider, setLegacyProvider ] = useState( '' );
  const [ legacyNextToken, setLegacyNextToken ] = useState( '' );

  const toast = useToastContext();
  const confirm = useConfirm();

  const loadContacts = useCallback( async () => {
    setLoadingContacts( true );
    try
    {
      const data = await api.listContacts();
      setContacts( data.filter( c => c.phone ).map( c => ( { contactId: c.contactId, name: c.name || c.phone || 'Unknown', phone: c.phone || '' } ) ) );
    } catch ( err ) { console.error( 'Load contacts error:', err ); } finally { setLoadingContacts( false ); }
  }, [] );

  const loadAwsData = useCallback( async () => {
    setLoading( true );
    setLoadError( false );
    try
    {
      const [ smsData, contactsData ] = await Promise.all( [ api.listSmsAwsMessages(), api.listContacts() ] );
      const contactMap = new Map<string, api.Contact>();
      contactsData.forEach( c => contactMap.set( c.contactId, c ) );
      let formatted: SmsMessage[];
      if ( smsData.length > 0 )
      {
        formatted = smsData.map( m => ( {
          messageId: m.messageId, contactId: m.contactId, contactName: contactMap.get( m.contactId )?.name,
          phone: m.phoneNumber || contactMap.get( m.contactId )?.phone || '', content: m.content || '', status: m.status || 'unknown',
          direction: m.direction || 'OUTBOUND', messageType: m.messageType, campaignId: ( m as any ).campaignId,
          campaignName: ( m as any ).campaignName, timestamp: m.createdAt ? new Date( m.createdAt * 1000 ).toISOString() : new Date().toISOString()
        } ) );
      } else
      {
        const messagesData = await api.listMessages( undefined, 'SMS' );
        formatted = messagesData.map( m => ( {
          messageId: m.messageId, contactId: m.contactId, contactName: contactMap.get( m.contactId )?.name,
          phone: ( m as any ).phoneNumber || m.senderPhone || m.receivingPhone || contactMap.get( m.contactId )?.phone || '',
          content: m.content || '', status: m.status || 'unknown', direction: m.direction,
          messageType: ( m as any ).messageType, campaignId: ( m as any ).campaignId,
          campaignName: ( m as any ).campaignName, timestamp: m.timestamp
        } ) );
      }
      formatted.sort( ( a, b ) => new Date( b.timestamp ).getTime() - new Date( a.timestamp ).getTime() );
      setMessages( formatted );
      const campaignMap = new Map<string, Campaign>();
      formatted.filter( m => m.campaignId ).forEach( m => {
        const cid = m.campaignId!;
        if ( !campaignMap.has( cid ) ) campaignMap.set( cid, { id: cid, name: m.campaignName || cid, recipients: 0, sent: 0, delivered: 0, failed: 0, createdAt: m.timestamp } );
        const c = campaignMap.get( cid )!; c.recipients++;
        if ( m.status === 'sent' || m.status === 'delivered' ) c.sent++;
        if ( m.status === 'delivered' ) c.delivered++;
        if ( m.status === 'failed' ) c.failed++;
      } );
      setCampaigns( Array.from( campaignMap.values() ).sort( ( a, b ) => new Date( b.createdAt ).getTime() - new Date( a.createdAt ).getTime() ) );
    } catch ( err ) { console.error( 'Load error:', err ); setLoadError( true ); toast.error( 'Failed to load data' ); } finally { setLoading( false ); }
  }, [ toast ] );

  useEffect( () => { setPage( 1 ); }, [ searchQuery, directionFilter ] );
  useEffect( () => { if ( showContactPicker ) loadContacts(); }, [ showContactPicker, loadContacts ] );

  const filteredContacts = contacts.filter( c => c.name.toLowerCase().includes( contactSearch.toLowerCase() ) || c.phone.includes( contactSearch ) );
  const selectContact = ( contact: Contact ) => {
    if ( showContactPicker === 'single' ) { setSendPhone( contact.phone ); setShowContactPicker( null ); }
    else if ( showContactPicker === 'campaign' && !selectedContacts.includes( contact.contactId ) ) setSelectedContacts( prev => [ ...prev, contact.contactId ] );
    setContactSearch( '' );
  };

  const handleSendSms = async () => {
    if ( !sendPhone || !sendContent ) { toast.error( 'Phone and message required' ); return; }
    setSending( true );
    try
    {
      // Indian destinations route via ap-south-1 with TRAI DLT parameters and
      // require an approved template id. The backend rejects an Indian send
      // with an unmapped template key (422 MISSING_DLT_TEMPLATE) rather than
      // sending unregistered content, so pass the key through explicitly.
      const payload: Parameters<typeof api.sendSmsAws>[ 0 ] & { dltTemplateKey?: string } = {
        phoneNumber: sendPhone,
        content: sendContent,
        messageType: sendMessageType as 'TRANSACTIONAL' | 'PROMOTIONAL',
      };
      if ( isIndianDestination( sendPhone ) ) payload.dltTemplateKey = sendDltTemplateKey;

      const result = await api.sendSmsAws( payload );
      if ( result && ( result.messageId || result.status === 'sent' ) ) { toast.success( 'SMS sent!' ); setShowSendModal( false ); setSendPhone( '' ); setSendContent( '' ); await loadAwsData(); }
      else if ( ( result as any )?.error === 'MISSING_DLT_TEMPLATE' ) toast.error( 'No approved DLT template for this message type' );
      else toast.error( 'Failed to send SMS' );
    } catch ( err ) { toast.error( 'Failed to send SMS' ); } finally { setSending( false ); }
  };

  const handleSendCampaign = async () => {
    if ( !campaignName.trim() || !campaignContent.trim() || selectedContacts.length === 0 ) { toast.error( 'Campaign name, message, and contacts required' ); return; }
    setCampaignSending( true );
    try
    {
      let sent = 0, failed = 0;
      for ( const contactId of selectedContacts )
      {
        const contact = contacts.find( c => c.contactId === contactId );
        if ( !contact?.phone ) { failed++; continue; }
        try { const result = await api.sendSmsAws( { contactId, phoneNumber: contact.phone, content: campaignContent, messageType: 'PROMOTIONAL' } ); if ( result && result.messageId ) sent++; else failed++; } catch { failed++; }
        if ( sent % 10 === 0 ) await new Promise( r => setTimeout( r, 200 ) );
      }
      toast.success( `Campaign sent: ${sent} success, ${failed} failed` );
      setShowCampaignModal( false ); setCampaignName( '' ); setCampaignContent( '' ); setSelectedContacts( [] ); await loadAwsData();
    } catch ( err ) { toast.error( 'Campaign failed' ); } finally { setCampaignSending( false ); }
  };

  // Clears the AWS SMS log only. Legacy history is deliberately NOT clearable
  // from here: it is audit and DLT evidence, and its purge requires a typed
  // table-name confirmation server-side.
  const handleClearLogs = async () => {
    if ( !( await confirm( 'Clear all AWS SMS logs?' ) ) ) return;
    setClearing( true );
    try
    {
      const res = await api.authFetch( `${API_BASE}/sms-aws/clear-logs`, { method: 'DELETE', headers: { 'Content-Type': 'application/json' } } );
      const result = await res.json();
      if ( result.success ) { toast.success( 'Cleared logs' ); await loadAwsData(); }
      else toast.error( result.error || 'Failed' );
    } catch ( err ) { toast.error( 'Failed to clear logs' ); } finally { setClearing( false ); }
  };

  // DLT Template functions
  const loadTemplates = useCallback( async () => {
    setTemplatesLoading( true );
    try
    {
      const res = await api.authFetch( `${API_BASE}/sms-aws/dlt-templates` );
      const data = await res.json();
      setDltTemplates( data.templates || [] );
    } catch ( err ) { console.error( 'Load templates error:', err ); } finally { setTemplatesLoading( false ); }
  }, [] );

  useEffect( () => { loadTemplates(); }, [ loadTemplates ] );


  const handleCreateTemplate = async () => {
    if ( !tplId || !tplContent ) { toast.error( 'Template ID and content are required' ); return; }
    setTplSaving( true );
    try
    {
      const res = await api.authFetch( `${API_BASE}/sms-aws/dlt-templates`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify( { templateId: tplId, name: tplName, content: tplContent, messageType: tplMessageType } )
      } );
      const data = await res.json();
      if ( data.success ) { toast.success( 'Template saved' ); setShowTemplateModal( false ); setTplId( '' ); setTplName( '' ); setTplContent( '' ); await loadTemplates(); }
      else toast.error( data.error || 'Failed' );
    } catch ( err ) { toast.error( 'Failed to save template' ); } finally { setTplSaving( false ); }
  };

  const handleDeleteTemplate = async ( templateId: string ) => {
    if ( !( await confirm( `Delete template ${templateId}?` ) ) ) return;
    try
    {
      const res = await api.authFetch( `${API_BASE}/sms-aws/dlt-templates?templateId=${templateId}`, { method: 'DELETE' } );
      const data = await res.json();
      if ( data.success ) { toast.success( 'Template deleted' ); await loadTemplates(); }
      else toast.error( data.error || 'Failed' );
    } catch ( err ) { toast.error( 'Failed to delete template' ); }
  };

  const handleEditTemplate = ( tpl: DLTTemplate ) => {
    setEditingTemplate( tpl );
    setEditTplName( tpl.name );
    setEditTplContent( tpl.content );
    setEditTplMessageType( tpl.messageType );
    setShowEditTemplateModal( true );
  };

  const handleUpdateTemplate = async () => {
    if ( !editingTemplate ) return;
    setEditTplSaving( true );
    try
    {
      const res = await api.authFetch( `${API_BASE}/sms-aws/dlt-templates`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify( { templateId: editingTemplate.templateId, name: editTplName, content: editTplContent, messageType: editTplMessageType } )
      } );
      const data = await res.json();
      if ( data.success ) { toast.success( 'Template updated' ); setShowEditTemplateModal( false ); setEditingTemplate( null ); await loadTemplates(); }
      else toast.error( data.error || 'Failed' );
    } catch ( err ) { toast.error( 'Failed to update template' ); } finally { setEditTplSaving( false ); }
  };

  const handleSeedTemplates = async () => {
    setSeeding( true );
    try
    {
      const res = await api.authFetch( `${API_BASE}/sms-aws/dlt-templates?action=seed` );
      const data = await res.json();
      if ( data.success ) { toast.success( data.message || 'Templates seeded' ); await loadTemplates(); }
      else toast.error( data.error || 'Failed' );
    } catch ( err ) { toast.error( 'Failed to seed templates' ); } finally { setSeeding( false ); }
  };

  // Legacy history (read-only) — retired-provider records.
  const loadLegacyHistory = useCallback( async () => {
    setLegacyLoading( true );
    setLegacyError( '' );
    try
    {
      const qs = legacyProvider ? `?provider=${encodeURIComponent( legacyProvider )}` : '';
      const res = await api.authFetch( `${API_BASE}/sms-aws/legacy-history${qs}` );
      if ( !res.ok ) throw new Error( `HTTP ${res.status}` );
      const data = await res.json();
      setLegacyMessages( data.messages || [] );
      setLegacyNextToken( data.nextToken || '' );
    } catch ( err: any )
    {
      console.error( 'Legacy history load error:', err );
      setLegacyMessages( [] );
      setLegacyError( err?.message || 'Request failed' );
    } finally { setLegacyLoading( false ); }
  }, [ legacyProvider ] );

  // Load on mount and whenever the provider filter changes. The tab id lives
  // inside PageShell's render prop, so there is no outer activeTab to key on;
  // one small scan on mount is cheaper than threading tab state out.
  useEffect( () => { loadLegacyHistory(); }, [ loadLegacyHistory ] );

  // AWS filtered
  const filteredMessages = messages.filter( msg => {
    if ( directionFilter === 'inbound' && msg.direction !== 'INBOUND' ) return false;
    if ( directionFilter === 'outbound' && msg.direction !== 'OUTBOUND' ) return false;
    if ( searchQuery ) { const q = searchQuery.toLowerCase(); return msg.contactName?.toLowerCase().includes( q ) || msg.phone?.includes( q ) || msg.content?.toLowerCase().includes( q ); }
    return true;
  } );
  const totalPages = Math.ceil( filteredMessages.length / ITEMS_PER_PAGE );
  const paginatedMessages = filteredMessages.slice( ( page - 1 ) * ITEMS_PER_PAGE, page * ITEMS_PER_PAGE );
  const inboundCount = messages.filter( m => m.direction === 'INBOUND' ).length;
  const outboundCount = messages.filter( m => m.direction === 'OUTBOUND' ).length;

  const shellContent = (
    <>
      <PageShell title="SMS" subtitle="AWS End User Messaging \u00b7 send, campaigns, DLT registry" tabs={ TABS } defaultTab="aws">
        { ( activeTab ) => (
          <>
            {/* ===== AWS PINPOINT TAB ===== */ }
            { activeTab === 'aws' && (
              <div className="sms-tab-content">
                <div className="tab-header">
                  <div className="tab-header-left"><span className="provider-badge">AWS End User Messaging</span><span className="region-badge">us-east-1 \u00b7 ap-south-1</span></div>
                  <div className="tab-header-actions">
                    <Button variant="primary" onClick={ () => setShowSendModal( true ) }>Send SMS</Button>
                    <Button variant="secondary" onClick={ () => handleClearLogs() } disabled={ clearing } loading={ clearing }>Clear</Button>
                    <Button variant="secondary" icon="refresh" onClick={ loadAwsData } disabled={ loading } loading={ loading }>Refresh</Button>
                  </div>
                </div>
                <div className="controls-row">
                  <div className="filter-tabs">
                    <button className={ directionFilter === 'all' ? 'active' : '' } onClick={ () => setDirectionFilter( 'all' ) }>All ({ messages.length })</button>
                    <button className={ directionFilter === 'inbound' ? 'active' : '' } onClick={ () => setDirectionFilter( 'inbound' ) }>? In ({ inboundCount })</button>
                    <button className={ directionFilter === 'outbound' ? 'active' : '' } onClick={ () => setDirectionFilter( 'outbound' ) }>? Out ({ outboundCount })</button>
                  </div>
                  <input type="text" placeholder="Search..." value={ searchQuery } onChange={ e => setSearchQuery( e.target.value ) } className="sms-search" />
                  <Pagination currentPage={ page } totalPages={ totalPages } onPageChange={ setPage } />
                </div>
                <div className="table-area">{ loading ? <div className="loading-state">Loading...</div> : loadError ? <div style={ { padding: 32, textAlign: 'center' } }><p style={ { color: '#991b1b', fontSize: 13, marginBottom: 8 } }>Failed to load SMS data</p><button onClick={ () => loadAwsData() } style={ { padding: '6px 14px', background: '#d1f470', color: '#1a3a2a', border: 'none', borderRadius: 13, fontSize: 12, fontWeight: 600, cursor: 'pointer' } }>Retry</button></div> : (
                  <table><thead><tr><th>Time</th><th>Dir</th><th>Contact</th><th className="hide-mobile">Phone</th><th>Message</th><th>Status</th></tr></thead><tbody>
                    { paginatedMessages.map( msg => ( <tr key={ msg.messageId }><td className="time-cell">{ new Date( msg.timestamp ).toLocaleString() }</td><td><span className={ msg.direction === 'INBOUND' ? 'dir-in' : 'dir-out' }>{ msg.direction === 'INBOUND' ? '?' : '?' }</span></td><td>{ msg.contactName || '-' }</td><td className="phone-cell hide-mobile">{ msg.phone }</td><td className="content-cell" title={ msg.content }>{ msg.content?.substring( 0, 40 ) }{ msg.content?.length > 40 ? '...' : '' }</td><td><span className={ `st-badge ${msg.status?.toLowerCase()}` }>{ msg.status }</span></td></tr> ) ) }
                    { paginatedMessages.length === 0 && <tr><td colSpan={ 6 } className="empty-row">No messages</td></tr> }
                  </tbody></table>
                ) }</div>
              </div>
            ) }

            {/* ===== AIRTEL IN TAB ===== */ }
            {/* ===== CAMPAIGN TAB ===== */ }
            { activeTab === 'campaign' && (
              <div className="sms-tab-content">
                <div className="tab-header">
                  <div className="tab-header-left"><span className="provider-badge">SMS Campaigns</span></div>
                  <div className="tab-header-actions">
                    <Button variant="primary" onClick={ () => { setShowCampaignModal( true ); loadContacts(); } }>New Campaign</Button>
                  </div>
                </div>
                <div className="table-area">
                  <table><thead><tr><th>Campaign</th><th>Recipients</th><th>Sent</th><th>Delivered</th><th>Failed</th><th>Date</th></tr></thead><tbody>
                    { campaigns.map( c => ( <tr key={ c.id }><td className="name-cell">{ c.name }</td><td>{ c.recipients }</td><td className="success-cell">{ c.sent }</td><td>{ c.delivered }</td><td className="failed-cell">{ c.failed }</td><td className="time-cell">{ new Date( c.createdAt ).toLocaleDateString() }</td></tr> ) ) }
                    { campaigns.length === 0 && <tr><td colSpan={ 6 } className="empty-row">No campaigns yet</td></tr> }
                  </tbody></table>
                </div>
              </div>
            ) }

            {/* ===== DLT TEMPLATES TAB ===== */ }
            { activeTab === 'templates' && (
              <div className="sms-tab-content">
                <div className="tab-header">
                  <div className="tab-header-left"><span className="provider-badge">DLT Templates</span><span className="region-badge">TRAI \u00b7 India</span></div>
                  <div className="tab-header-actions">
                    <Button variant="primary" onClick={ () => setShowTemplateModal( true ) }>Add Template</Button>
                    <Button variant="secondary" onClick={ handleSeedTemplates } disabled={ seeding } loading={ seeding }>Seed Defaults</Button>
                    <Button variant="secondary" icon="refresh" onClick={ loadTemplates } disabled={ templatesLoading } loading={ templatesLoading }>Refresh</Button>
                  </div>
                </div>
                <div className="table-area">{ templatesLoading ? <div className="loading-state">Loading...</div> : (
                  <table><thead><tr><th>Template ID</th><th>Name</th><th>Content</th><th>Type</th><th>Sender</th><th>Actions</th></tr></thead><tbody>
                    { dltTemplates.map( tpl => ( <tr key={ tpl.templateId }><td className="phone-cell">{ tpl.templateId }</td><td className="name-cell">{ tpl.name }</td><td className="content-cell" title={ tpl.content }>{ tpl.content?.substring( 0, 60 ) }{ tpl.content?.length > 60 ? '...' : '' }</td><td><span className="st-badge">{ tpl.messageType }</span></td><td>{ tpl.senderId }</td><td><button className="pick-btn" onClick={ () => handleEditTemplate( tpl ) }>Edit</button> <button className="pick-btn" onClick={ () => handleDeleteTemplate( tpl.templateId ) }>Delete</button></td></tr> ) ) }
                    { dltTemplates.length === 0 && <tr><td colSpan={ 6 } className="empty-row">No DLT templates. Click &quot;Add Template&quot; to register one, or &quot;Seed Defaults&quot; to add WA-Alert + ivr-default.</td></tr> }
                  </tbody></table>
                ) }</div>
                <div style={ { padding: '12px', background: '#f9fafb', borderTop: '1px solid #f3f4f6', fontSize: '12px', color: '#6b7280' } }>
                  { dltTemplates.length } template(s) registered · PE ID: <code>1201161991108627443</code> · Sender: <code>WDBEEP</code> · Templates are managed in the DLT Templates tab
                </div>
              </div>
            ) }

            {/* ===== PINPOINT TEMPLATES TAB (ap-south-1) ===== */ }
            {/* ===== LEGACY HISTORY (read-only) ===== */ }
            { activeTab === 'legacy' && (
              <div className="sms-tab-content">
                <div className="tab-header">
                  <div className="tab-header-left">
                    <span className="provider-badge">Legacy history</span>
                    <span className="region-badge">read-only</span>
                  </div>
                  <div className="tab-header-actions">
                    { /* `.sms-search` is dropped rather than forwarded: it SKINNED the native
                         control, and className on a Select lands on the wrapper, so it would
                         paint a box around the whole field. Its width survives as layout. */ }
                    <Select ariaLabel="Retired provider" value={ legacyProvider }
                      onChange={ v => { setLegacyProvider( v ); } }
                      options={ LEGACY_PROVIDER_OPTIONS } style={ LEGACY_PROVIDER_STYLE } />
                    <Button variant="secondary" icon="refresh" onClick={ loadLegacyHistory } disabled={ legacyLoading } loading={ legacyLoading }>Refresh</Button>
                  </div>
                </div>
                <div style={ { padding: '12px', background: '#fffbeb', border: '1px solid #fde68a', borderRadius: '8px', margin: '8px 0', fontSize: '13px', color: '#78350f' } }>
                  <strong>Historical records from retired SMS providers.</strong> Retained as
                  audit and TRAI DLT evidence. Each row keeps the provider that actually
                  delivered it and is never relabelled. Sending is not possible from this
                  view — all new SMS goes through AWS End User Messaging.
                </div>
                { legacyError ? (
                  <div className="empty-row" style={ { padding: '24px', textAlign: 'center', color: '#b91c1c' } }>
                    Could not load legacy history. { legacyError }
                  </div>
                ) : (
                  <div className="table-area">{ legacyLoading ? <div className="loading-state">Loading...</div> : (
                    <table><thead><tr><th>Time</th><th>Dir</th><th>Phone</th><th>Message</th><th className="hide-mobile">Provider</th><th className="hide-mobile">DLT template</th><th>Status</th></tr></thead><tbody>
                      { legacyMessages.map( msg => (
                        <tr key={ msg.messageId }>
                          <td className="time-cell">{ msg.createdAt ? new Date( msg.createdAt * 1000 ).toLocaleString() : '-' }</td>
                          <td><span className={ msg.direction === 'INBOUND' ? 'dir-in' : 'dir-out' }>{ msg.direction === 'INBOUND' ? '\u2193' : '\u2191' }</span></td>
                          <td className="phone-cell">{ msg.phoneNumber || '-' }</td>
                          <td className="content-cell" title={ msg.content }>{ msg.content?.substring( 0, 50 ) }{ msg.content && msg.content.length > 50 ? '...' : '' }</td>
                          <td className="hide-mobile"><span className="st-badge" title={ msg.providerLabel }>{ msg.provider }</span></td>
                          <td className="hide-mobile">{ msg.dltTemplateId || '-' }</td>
                          <td><span className={ `st-badge ${msg.status?.toLowerCase()}` }>{ msg.status || '-' }</span></td>
                        </tr>
                      ) ) }
                      { legacyMessages.length === 0 && <tr><td colSpan={ 7 } className="empty-row">No historical messages{ legacyProvider ? ` for ${legacyProvider}` : '' }.</td></tr> }
                    </tbody></table>
                  ) }</div>
                ) }
                <div style={ { padding: '12px', background: '#f9fafb', borderTop: '1px solid #f3f4f6', fontSize: '12px', color: '#6b7280' } }>
                  { legacyMessages.length } record(s) shown{ legacyNextToken ? ' \u00b7 more available' : '' } \u00b7 ordering is within this page only
                </div>
              </div>
            ) }

            {/* ===== MODALS ===== */ }
            { showSendModal && ( <div className="modal-overlay" onClick={ () => setShowSendModal( false ) }><div className="modal-content" onClick={ e => e.stopPropagation() }>
              <h3>Send SMS (AWS)</h3>
              <div className="form-group"><label>Phone *</label><div className="input-row"><input type="tel" value={ sendPhone } onChange={ e => setSendPhone( e.target.value ) } placeholder="+1234567890" /><button type="button" className="pick-btn" onClick={ () => setShowContactPicker( 'single' ) }>Contacts</button></div></div>
              <div className="form-group"><label>Message *</label><textarea value={ sendContent } onChange={ e => setSendContent( e.target.value ) } placeholder="Enter message..." rows={ 3 } /></div>
              { /* The `.form-group` caption is an UNASSOCIATED <label> - no `for`, no wrapped
                   control - so it was never a name source and the native control had no
                   accessible name at all. It stays where it is, keeping `.form-group label`'s
                   own type and spacing, and the control takes `ariaLabel`. */ }
              <div className="form-group"><label>Type</label><Select ariaLabel="Message type" value={ sendMessageType } onChange={ v => setSendMessageType( v ) } options={ SEND_TYPE_OPTIONS } /></div>
              { isIndianDestination( sendPhone ) ? (
                <div className="form-group">
                  <label>DLT Template * <span style={ { fontSize: '11px', color: '#9ca3af' } }>required for +91 · TRAI DLT</span></label>
                  <Select ariaLabel="DLT template" value={ sendDltTemplateKey }
                    onChange={ v => setSendDltTemplateKey( v ) } options={ DLT_KEY_OPTIONS } />
                  <div style={ { marginTop: '6px', fontSize: '11px', color: '#6b7280' } }>
                    Routes via <code>ap-south-1</code> · Sender <code>WDBEEP</code> · Entity <code>1201161991108627443</code> · Template <code>{ DLT_TEMPLATE_OPTIONS.find( t => t.key === sendDltTemplateKey )?.id }</code>
                    <br />Message body must match the approved DLT template content exactly.
                  </div>
                </div>
              ) : sendPhone ? (
                <div style={ { marginBottom: '12px', fontSize: '11px', color: '#6b7280' } }>
                  Non-India destination · routes via <code>us-east-1</code> · no DLT fields applied
                </div>
              ) : null }
              <div className="modal-actions"><Button variant="secondary" onClick={ () => setShowSendModal( false ) }>Cancel</Button><Button variant="primary" onClick={ handleSendSms } loading={ sending } disabled={ !sendPhone || !sendContent }>Send</Button></div>
            </div></div> ) }

            { showCampaignModal && ( <div className="modal-overlay" onClick={ () => setShowCampaignModal( false ) }><div className="modal-content campaign-modal" onClick={ e => e.stopPropagation() }>
              <h3>Create SMS Campaign</h3>
              <div className="form-group"><label>Name *</label><input type="text" value={ campaignName } onChange={ e => setCampaignName( e.target.value ) } placeholder="My Campaign" /></div>
              <div className="form-group"><label>Message *</label><textarea value={ campaignContent } onChange={ e => setCampaignContent( e.target.value ) } placeholder="Enter message..." rows={ 3 } /></div>
              <div className="form-group"><label>Recipients ({ selectedContacts.length })</label><button type="button" className="pick-btn full-w" onClick={ () => setShowContactPicker( 'campaign' ) }>Select Contacts</button>
                { selectedContacts.length > 0 && ( <div className="tags">{ selectedContacts.map( id => { const c = contacts.find( x => x.contactId === id ); return c ? <span key={ id } className="tag">{ c.name } <button onClick={ () => setSelectedContacts( prev => prev.filter( x => x !== id ) ) }>�</button></span> : null; } ) }</div> ) }
              </div>
              <div className="modal-actions"><Button variant="secondary" onClick={ () => setShowCampaignModal( false ) }>Cancel</Button><Button variant="primary" onClick={ handleSendCampaign } loading={ campaignSending } disabled={ !campaignName || !campaignContent || selectedContacts.length === 0 }>Send to { selectedContacts.length }</Button></div>
            </div></div> ) }

            { showTemplateModal && ( <div className="modal-overlay" onClick={ () => setShowTemplateModal( false ) }><div className="modal-content" onClick={ e => e.stopPropagation() }>
              <h3>Add DLT Template</h3>
              <div className="form-group"><label>Template ID (DLT) *</label><input type="text" value={ tplId } onChange={ e => setTplId( e.target.value ) } placeholder="DLT Template ID from portal" /></div>
              <div className="form-group"><label>Name</label><input type="text" value={ tplName } onChange={ e => setTplName( e.target.value ) } placeholder="e.g. Customer-Service IVR" /></div>
              <div className="form-group"><label>Content *</label><textarea value={ tplContent } onChange={ e => setTplContent( e.target.value ) } placeholder="Template text with {#var#} placeholders" rows={ 4 } /></div>
              <div className="form-group"><label>Message Type</label><Select ariaLabel="DLT message type" value={ tplMessageType } onChange={ v => setTplMessageType( v ) } options={ TPL_MESSAGE_TYPE_OPTIONS } /></div>
              <div className="modal-actions"><Button variant="secondary" onClick={ () => setShowTemplateModal( false ) }>Cancel</Button><Button variant="primary" onClick={ handleCreateTemplate } loading={ tplSaving } disabled={ !tplId || !tplContent }>Save</Button></div>
            </div></div> ) }

            {/* Edit DLT Template Modal */ }
            { showEditTemplateModal && editingTemplate && ( <div className="modal-overlay" onClick={ () => setShowEditTemplateModal( false ) }><div className="modal-content" onClick={ e => e.stopPropagation() }>
              <h3>Edit DLT Template</h3>
              <div className="form-group"><label>Template ID</label><input type="text" value={ editingTemplate.templateId } disabled style={ { background: '#f3f4f6' } } /></div>
              <div className="form-group"><label>Name</label><input type="text" value={ editTplName } onChange={ e => setEditTplName( e.target.value ) } /></div>
              <div className="form-group"><label>Content *</label><textarea value={ editTplContent } onChange={ e => setEditTplContent( e.target.value ) } rows={ 4 } /></div>
              <div className="form-group"><label>Message Type</label><Select ariaLabel="DLT message type" value={ editTplMessageType } onChange={ v => setEditTplMessageType( v ) } options={ TPL_MESSAGE_TYPE_OPTIONS } /></div>
              <div className="modal-actions"><Button variant="secondary" onClick={ () => setShowEditTemplateModal( false ) }>Cancel</Button><Button variant="primary" onClick={ handleUpdateTemplate } loading={ editTplSaving } disabled={ !editTplContent }>Update</Button></div>
            </div></div> ) }

            { showContactPicker && ( <div className="modal-overlay" onClick={ () => setShowContactPicker( null ) }><div className="modal-content contact-picker" onClick={ e => e.stopPropagation() }>
              <h3>Select Contact{ showContactPicker === 'campaign' ? 's' : '' }</h3>
              <input type="text" placeholder="Search..." value={ contactSearch } onChange={ e => setContactSearch( e.target.value ) } className="contact-search" />
              <div className="contact-list">{ loadingContacts ? <div className="loading-state">Loading...</div> : filteredContacts.length === 0 ? <div className="loading-state">No contacts</div> : (
                filteredContacts.slice( 0, 50 ).map( contact => ( <div key={ contact.contactId } className={ `contact-row ${selectedContacts.includes( contact.contactId ) ? 'selected' : ''}` } onClick={ () => selectContact( contact ) }><div className="contact-avatar">{ contact.name.charAt( 0 ).toUpperCase() }</div><div className="contact-details"><div className="c-name">{ contact.name }</div><div className="c-phone">{ contact.phone }</div></div>{ showContactPicker === 'campaign' && selectedContacts.includes( contact.contactId ) && <span className="check">?</span> }</div> ) )
              ) }</div>
              <div className="modal-actions"><Button variant="secondary" onClick={ () => setShowContactPicker( null ) }>{ showContactPicker === 'campaign' ? 'Done' : 'Cancel' }</Button></div>
            </div></div> ) }
          </>
        ) }
      </PageShell>

      <style jsx>{ `
        .sms-tab-content { padding: 0; }
        .tab-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 10px; }
        .tab-header-left { display: flex; align-items: center; gap: 8px; }
        .tab-header-actions { display: flex; gap: 6px; flex-wrap: wrap; }
        .provider-badge { background: #1a3a2a; color: #fff; padding: 3px 10px; border-radius: 6px; font-size: 11px; font-weight: 600; }
        .provider-badge.legacy { background: #78350f; }
        .region-badge { background: #f3f4f6; color: #6b7280; padding: 3px 8px; border-radius: 4px; font-size: 10px; }
        .controls-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; gap: 10px; flex-wrap: wrap; }
        .filter-tabs { display: flex; gap: 4px; }
        .filter-tabs button { padding: 6px 12px; border: 1px solid #e5e7eb; background: #fff; border-radius: 6px; cursor: pointer; font-size: 12px; min-height: 44px; }
        .filter-tabs button.active { background: #d1f470; color: #1a3a2a; border-color: #1a3a2a; }
        .sms-search { padding: 8px 12px; border: 1px solid #d1d5db; border-radius: 8px; width: 200px; max-width: 100%; font-size: 16px; min-height: 44px; box-sizing: border-box; }
        .sms-search:focus { outline: none; border-color: #1a3a2a; box-shadow: 0 0 0 3px rgba(209,244,112,0.3); }
        .table-area { background: #fff; border-radius: 12px; border: 1px solid #e5e7eb; overflow: auto; }
        .loading-state { padding: 40px; text-align: center; color: #6b7280; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 10px 12px; text-align: left; border-bottom: 1px solid #f3f4f6; font-size: 12px; white-space: nowrap; }
        th { background: #f9fafb; font-weight: 600; color: #374151; position: sticky; top: 0; z-index: 1; }
        tr:hover { background: #f9fafb; }
        .time-cell { font-size: 11px; color: #6b7280; }
        .phone-cell { font-family: monospace; color: #1a3a2a; font-size: 11px; }
        .content-cell { max-width: 200px; overflow: hidden; text-overflow: ellipsis; }
        .name-cell { font-weight: 500; color: #1a1a1a; }
        .success-cell { color: #1a3a2a; font-weight: 500; }
        .failed-cell { color: #1a3a2a; font-weight: 500; }
        .dir-in { background: #1a3a2a; color: #fff; padding: 2px 6px; border-radius: 4px; font-size: 10px; }
        .dir-out { background: #6b7280; color: #fff; padding: 2px 6px; border-radius: 4px; font-size: 10px; }
        .st-badge { padding: 2px 6px; border-radius: 4px; font-size: 10px; background: #f1f5f9; color: #6b7280; }
        .st-badge.sent, .st-badge.delivered { background: #f9fafb; color: #1a3a2a; }
        .st-badge.failed { background: #f9fafb; color: #1a3a2a; }
        .empty-row { text-align: center; color: #6b7280; padding: 30px !important; }
        .modal-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 1000; padding: 16px; }
        .modal-content { background: #fff; border-radius: 12px; padding: 20px; width: 100%; max-width: 420px; max-height: 90vh; overflow-y: auto; }
        .modal-content.campaign-modal { max-width: 480px; }
        .modal-content h3 { margin: 0 0 16px 0; color: #1a1a1a; }
        .form-group { margin-bottom: 14px; }
        .form-group label { display: block; font-size: 12px; font-weight: 500; margin-bottom: 5px; color: #374151; }
        .form-group input, .form-group textarea, .form-group select { width: 100%; padding: 8px 10px; border: 1px solid #d1d5db; border-radius: 8px; font-size: 13px; font-family: inherit; box-sizing: border-box; }
        .form-group input:focus, .form-group textarea:focus, .form-group select:focus { outline: none; border-color: #1a3a2a; }
        .input-row { display: flex; gap: 6px; }
        .input-row input { flex: 1; }
        .form-row { display: flex; gap: 10px; }
        .form-group.half { flex: 1; }
        .checkbox-label { display: flex !important; align-items: center; gap: 6px; cursor: pointer; }
        .checkbox-label input[type="checkbox"] { width: auto; margin: 0; }
        .pick-btn { padding: 8px 12px; background: #f9fafb; border: 1px solid #1a3a2a; border-radius: 8px; color: #0f2a1d; font-size: 12px; cursor: pointer; }
        .pick-btn:hover { background: #f9fafb; }
        .pick-btn.full-w { width: 100%; }
        .modal-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 16px; }
        .tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
        .tag { display: inline-flex; align-items: center; gap: 4px; padding: 4px 8px; background: #f3f4f6; border-radius: 4px; font-size: 11px; }
        .tag button { background: none; border: none; cursor: pointer; font-size: 14px; padding: 0; }
        .contact-picker { max-width: 360px; }
        .contact-search { width: 100%; padding: 8px 10px; border: 1px solid #d1d5db; border-radius: 8px; font-size: 13px; margin-bottom: 10px; box-sizing: border-box; }
        .contact-list { max-height: 280px; overflow-y: auto; border: 1px solid #e5e7eb; border-radius: 8px; }
        .contact-row { display: flex; align-items: center; gap: 10px; padding: 10px 12px; cursor: pointer; border-bottom: 1px solid #f3f4f6; min-height: 44px; }
        .contact-row:hover { background: #f9fafb; }
        .contact-row.selected { background: #f9fafb; }
        .contact-avatar { width: 36px; height: 36px; background: #1a3a2a; color: #fff; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: 500; font-size: 13px; flex-shrink: 0; }
        .contact-details { flex: 1; }
        .c-name { font-size: 13px; font-weight: 500; color: #1a1a1a; }
        .c-phone { font-size: 11px; color: #6b7280; font-family: monospace; }
        .check { color: #1a3a2a; font-weight: bold; }
        @media (max-width: 768px) {
          .tab-header { flex-direction: column; align-items: flex-start; }
          .controls-row { flex-direction: column; align-items: stretch; }
          .sms-search { width: 100%; }
          .filter-tabs { flex-wrap: wrap; }
          .modal-overlay { align-items: flex-end; padding: 0; }
          .modal-content { max-width: 100%; border-radius: 16px 16px 0 0; max-height: 85vh; }
          .modal-content.campaign-modal { max-width: 100%; }
          .contact-picker { max-width: 100%; }
          .modal-actions { flex-direction: column; }
          .modal-actions button { width: 100%; }
          .hide-mobile { display: none; }
          th, td { padding: 8px 10px; font-size: 11px; }
        }
        @media (max-width: 480px) {
          .tab-header-actions { width: 100%; }
          .tab-header-actions button { flex: 1; }
          .filter-tabs { width: 100%; overflow-x: auto; -webkit-overflow-scrolling: touch; flex-wrap: nowrap; }
          .filter-tabs button { flex-shrink: 0; }
        }
      `}</style>
    </>
  );

  if ( embedded ) return shellContent;

  return (
    <Layout user={ user } onSignOut={ signOut }>
      <SEO title="SMS" description="SMS via AWS End User Messaging" />
      { shellContent }
    </Layout>
  );
};

export default SmsPage;
