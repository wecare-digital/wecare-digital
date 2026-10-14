/**
 * Voice workspace - current supported voice capabilities
 * Uses PageShell for section header + scrollable tab bar
 */
import React, { useState, useEffect, useCallback } from 'react';
import Layout from '../../../../components/Layout';
import SEO from '../../../../components/SEO';
import PageShell, { ShellTab } from '../../../../components/PageShell';
import Button from '../../../../components/ui/Button';
import Pagination from '../../../../components/ui/Pagination';
import { useToastContext } from '../../../../contexts/ToastContext';
import { useConfirm } from '../../../../contexts/ConfirmContext';
import * as api from '../../../../api/client';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }
interface Contact { contactId: string; name: string; phone: string; }
interface VoiceCall {
  callId: string; contactId: string; contactName?: string; phoneNumber: string;
  direction: string; status: string; duration: number; callType: string;
  message?: string; campaignId?: string; campaignName?: string; createdAt: string;
}
interface Campaign { id: string; name: string; recipients: number; connected: number; completed: number; failed: number; createdAt: string; }

const ITEMS_PER_PAGE = 25;
const TABS: ShellTab[] = [
  { id: 'aws', label: 'AWS' },
  { id: 'campaign', label: 'Campaign' },
];

const VoicePage: React.FC<PageProps> = ( { signOut, user, embedded } ) => {
  const [ calls, setCalls ] = useState<VoiceCall[]>( [] );
  const [ campaigns, setCampaigns ] = useState<Campaign[]>( [] );
  const [ loading, setLoading ] = useState( true );
  const [ loadError, setLoadError ] = useState( false );
  const [ page, setPage ] = useState( 1 );
  const [ searchQuery, setSearchQuery ] = useState( '' );
  const [ directionFilter, setDirectionFilter ] = useState<'all' | 'inbound' | 'outbound'>( 'all' );
  const [ showCallModal, setShowCallModal ] = useState( false );
  const [ callPhone, setCallPhone ] = useState( '' );
  const [ callMessage, setCallMessage ] = useState( '' );
  const [ calling, setCalling ] = useState( false );
  const [ showCampaignModal, setShowCampaignModal ] = useState( false );
  const [ campaignName, setCampaignName ] = useState( '' );
  const [ campaignMessage, setCampaignMessage ] = useState( '' );
  const [ selectedContacts, setSelectedContacts ] = useState<string[]>( [] );
  const [ campaignSending, setCampaignSending ] = useState( false );
  const [ contacts, setContacts ] = useState<Contact[]>( [] );
  const [ showContactPicker, setShowContactPicker ] = useState<'single' | 'campaign' | null>( null );
  const [ contactSearch, setContactSearch ] = useState( '' );
  const [ loadingContacts, setLoadingContacts ] = useState( false );
  const [ clearing, setClearing ] = useState( false );
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

  const loadData = useCallback( async () => {
    setLoading( true );
    setLoadError( false );
    try
    {
      const [ callsData, contactsData ] = await Promise.all( [ api.listVoiceAwsCalls(), api.listContacts() ] );
      const contactMap = new Map<string, api.Contact>();
      contactsData.forEach( c => contactMap.set( c.contactId, c ) );
      let formattedCalls: VoiceCall[];
      if ( callsData.length > 0 )
      {
        formattedCalls = callsData.map( c => ( {
          callId: c.callId, contactId: c.contactId, contactName: contactMap.get( c.contactId )?.name,
          phoneNumber: c.phoneNumber || contactMap.get( c.contactId )?.phone || '', direction: c.direction || 'OUTBOUND',
          status: c.status || 'unknown', duration: c.duration || 0, callType: c.callType || 'tts',
          message: ( c as any ).messageText, campaignId: ( c as any ).campaignId, campaignName: ( c as any ).campaignName,
          createdAt: c.createdAt ? new Date( c.createdAt * 1000 ).toISOString() : new Date().toISOString()
        } ) );
      } else
      {
        const sharedCalls = await api.listVoiceCalls( undefined, 'aws' );
        formattedCalls = sharedCalls.map( c => ( {
          callId: c.callId, contactId: c.contactId, contactName: contactMap.get( c.contactId )?.name,
          phoneNumber: c.phoneNumber || contactMap.get( c.contactId )?.phone || '', direction: c.direction || 'OUTBOUND',
          status: c.status || 'unknown', duration: c.duration || 0, callType: c.callType || 'tts',
          message: '', campaignId: undefined, campaignName: undefined, createdAt: c.createdAt
        } ) );
      }
      formattedCalls.sort( ( a, b ) => new Date( b.createdAt ).getTime() - new Date( a.createdAt ).getTime() );
      setCalls( formattedCalls );
      const campaignMap = new Map<string, Campaign>();
      formattedCalls.filter( c => c.campaignId ).forEach( c => {
        const cid = c.campaignId!;
        if ( !campaignMap.has( cid ) ) campaignMap.set( cid, { id: cid, name: c.campaignName || cid, recipients: 0, connected: 0, completed: 0, failed: 0, createdAt: c.createdAt } );
        const camp = campaignMap.get( cid )!; camp.recipients++;
        if ( c.status === 'connected' || c.status === 'completed' ) camp.connected++;
        if ( c.status === 'completed' ) camp.completed++;
        if ( c.status === 'failed' ) camp.failed++;
      } );
      setCampaigns( Array.from( campaignMap.values() ).sort( ( a, b ) => new Date( b.createdAt ).getTime() - new Date( a.createdAt ).getTime() ) );
    } catch ( err ) { console.error( 'Load error:', err ); setLoadError( true ); toast.error( 'Failed to load data' ); } finally { setLoading( false ); }
  }, [ toast ] );

  useEffect( () => { loadData(); }, [ loadData ] );
  useEffect( () => { setPage( 1 ); }, [ searchQuery, directionFilter ] );
  useEffect( () => { if ( showContactPicker ) loadContacts(); }, [ showContactPicker, loadContacts ] );

  const filteredContacts = contacts.filter( c => c.name.toLowerCase().includes( contactSearch.toLowerCase() ) || c.phone.includes( contactSearch ) );
  const selectContact = ( contact: Contact ) => {
    if ( showContactPicker === 'single' ) { setCallPhone( contact.phone ); setShowContactPicker( null ); }
    else if ( showContactPicker === 'campaign' && !selectedContacts.includes( contact.contactId ) ) setSelectedContacts( prev => [ ...prev, contact.contactId ] );
    setContactSearch( '' );
  };
  const formatDuration = ( seconds: number ) => { if ( !seconds ) return '0:00'; const mins = Math.floor( seconds / 60 ); const secs = Math.round( seconds % 60 ); return `${mins}:${secs.toString().padStart( 2, '0' )}`; };

  const handleMakeCall = async () => {
    if ( !callPhone ) { toast.error( 'Phone number required' ); return; }
    setCalling( true );
    try
    {
      const result = await api.makeVoiceAwsCall( { phoneNumber: callPhone, messageText: callMessage || 'Hello, this is a call from WECARE Digital.', callType: 'tts' } );
      if ( result && ( result.callId || result.status ) ) { toast.success( 'Call initiated!' ); setShowCallModal( false ); setCallPhone( '' ); setCallMessage( '' ); await loadData(); }
      else toast.error( 'Failed to initiate call' );
    } catch ( err ) { toast.error( 'Failed to make call' ); } finally { setCalling( false ); }
  };

  const handleSendCampaign = async () => {
    if ( !campaignName.trim() || !campaignMessage.trim() || selectedContacts.length === 0 ) { toast.error( 'Campaign name, message, and contacts required' ); return; }
    setCampaignSending( true );
    try
    {
      let sent = 0, failed = 0;
      for ( const contactId of selectedContacts )
      {
        const contact = contacts.find( c => c.contactId === contactId );
        if ( !contact?.phone ) { failed++; continue; }
        try { const result = await api.makeVoiceAwsCall( { contactId, phoneNumber: contact.phone, messageText: campaignMessage, callType: 'tts' } ); if ( result && result.callId ) sent++; else failed++; } catch { failed++; }
        if ( sent % 5 === 0 ) await new Promise( r => setTimeout( r, 500 ) );
      }
      toast.success( `Campaign initiated: ${sent} calls, ${failed} failed` );
      setShowCampaignModal( false ); setCampaignName( '' ); setCampaignMessage( '' ); setSelectedContacts( [] ); await loadData();
    } catch ( err ) { toast.error( 'Campaign failed' ); } finally { setCampaignSending( false ); }
  };

  const handleClearLogs = async () => {
    if ( !( await confirm( 'Clear all voice logs?' ) ) ) return;
    setClearing( true );
    try
    {
      const response = await api.authFetch( `${process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api'}/voice-aws/clear-logs`, { method: 'DELETE' } );
      const result = await response.json();
      if ( result.success ) { toast.success( `Cleared logs` ); await loadData(); }
      else toast.error( result.error || 'Failed' );
    } catch ( err ) { toast.error( 'Failed to clear logs' ); } finally { setClearing( false ); }
  };

  const filteredCalls = calls.filter( call => {
    if ( directionFilter === 'inbound' && call.direction !== 'INBOUND' ) return false;
    if ( directionFilter === 'outbound' && call.direction !== 'OUTBOUND' ) return false;
    if ( searchQuery ) { const q = searchQuery.toLowerCase(); return call.contactName?.toLowerCase().includes( q ) || call.phoneNumber?.includes( q ) || call.status?.toLowerCase().includes( q ); }
    return true;
  } );
  const totalPages = Math.ceil( filteredCalls.length / ITEMS_PER_PAGE );
  const paginatedCalls = filteredCalls.slice( ( page - 1 ) * ITEMS_PER_PAGE, page * ITEMS_PER_PAGE );
  const inboundCount = calls.filter( c => c.direction === 'INBOUND' ).length;
  const outboundCount = calls.filter( c => c.direction === 'OUTBOUND' ).length;

  const shellContent = (
    <>
      <PageShell title="Voice" subtitle="Business Calling — calls, campaigns and call records" tabs={ TABS } defaultTab="aws">
        { ( activeTab ) => (
          <>
            {/* ===== AWS PINPOINT TAB ===== */ }
            { activeTab === 'aws' && (
              <div className="voice-tab-content">
                <div className="tab-header">
                  <div className="tab-header-left"><span className="provider-badge">AWS</span><span className="region-badge">us-east-1</span></div>
                  <div className="tab-header-actions">
                    <Button variant="primary" onClick={ () => setShowCallModal( true ) }>Make Call</Button>
                    <Button variant="secondary" onClick={ handleClearLogs } disabled={ clearing } loading={ clearing }>Clear</Button>
                    <Button variant="secondary" icon="refresh" onClick={ loadData } disabled={ loading } loading={ loading }>Refresh</Button>
                  </div>
                </div>
                <div className="controls-row">
                  <div className="filter-tabs">
                    <button className={ directionFilter === 'all' ? 'active' : '' } onClick={ () => setDirectionFilter( 'all' ) }>All ({ calls.length })</button>
                    <button className={ directionFilter === 'inbound' ? 'active' : '' } onClick={ () => setDirectionFilter( 'inbound' ) }>In ({ inboundCount })</button>
                    <button className={ directionFilter === 'outbound' ? 'active' : '' } onClick={ () => setDirectionFilter( 'outbound' ) }>Out ({ outboundCount })</button>
                  </div>
                  <input type="text" placeholder="Search..." value={ searchQuery } onChange={ e => setSearchQuery( e.target.value ) } className="v-search" />
                  <Pagination currentPage={ page } totalPages={ totalPages } onPageChange={ setPage } />
                </div>
                <div className="table-area">{ loading ? <div className="loading-state">Loading...</div> : (
                  <table><thead><tr><th>Time</th><th>Dir</th><th>Contact</th><th className="hide-mobile">Phone</th><th>Duration</th><th>Type</th><th>Status</th></tr></thead><tbody>
                    { paginatedCalls.map( call => ( <tr key={ call.callId }><td className="time-cell">{ new Date( call.createdAt ).toLocaleString() }</td><td><span className={ call.direction === 'INBOUND' ? 'dir-in' : 'dir-out' }>{ call.direction === 'INBOUND' ? '?' : '?' }</span></td><td>{ call.contactName || '-' }</td><td className="phone-cell hide-mobile">{ call.phoneNumber }</td><td>{ formatDuration( call.duration ) }</td><td><span className="type-badge">{ call.callType }</span></td><td><span className={ `st-badge ${call.status?.toLowerCase()}` }>{ call.status }</span></td></tr> ) ) }
                    { paginatedCalls.length === 0 && <tr><td colSpan={ 7 } className="empty-row">No calls</td></tr> }
                  </tbody></table>
                ) }</div>
              </div>
            ) }

            {/* ===== CAMPAIGN TAB ===== */ }
            { activeTab === 'campaign' && (
              <div className="voice-tab-content">
                <div className="tab-header">
                  <div className="tab-header-left"><span className="provider-badge">Voice Campaigns</span></div>
                  <div className="tab-header-actions">
                    <Button variant="primary" onClick={ () => { setShowCampaignModal( true ); loadContacts(); } }>New Campaign</Button>
                  </div>
                </div>
                <div className="table-area">
                  <table><thead><tr><th>Campaign</th><th>Recipients</th><th>Connected</th><th>Completed</th><th>Failed</th><th>Date</th></tr></thead><tbody>
                    { campaigns.map( c => ( <tr key={ c.id }><td className="name-cell">{ c.name }</td><td>{ c.recipients }</td><td className="success-cell">{ c.connected }</td><td>{ c.completed }</td><td className="failed-cell">{ c.failed }</td><td className="time-cell">{ new Date( c.createdAt ).toLocaleDateString() }</td></tr> ) ) }
                    { campaigns.length === 0 && <tr><td colSpan={ 6 } className="empty-row">No campaigns yet</td></tr> }
                  </tbody></table>
                </div>
              </div>
            ) }

            {/* ===== MODALS ===== */ }
            { showCallModal && ( <div className="modal-overlay" onClick={ () => setShowCallModal( false ) }><div className="modal-content" onClick={ e => e.stopPropagation() }>
              <h3>Make Voice Call (AWS)</h3>
              <div className="form-group"><label>Phone *</label><div className="input-row"><input type="tel" value={ callPhone } onChange={ e => setCallPhone( e.target.value ) } placeholder="+1234567890" /><button type="button" className="pick-btn" onClick={ () => setShowContactPicker( 'single' ) }>Contacts</button></div></div>
              <div className="form-group"><label>Message (TTS)</label><textarea value={ callMessage } onChange={ e => setCallMessage( e.target.value ) } placeholder="Message to be spoken..." rows={ 3 } /></div>
              <div className="modal-actions"><Button variant="secondary" onClick={ () => setShowCallModal( false ) }>Cancel</Button><Button variant="primary" onClick={ handleMakeCall } loading={ calling } disabled={ !callPhone }>Call</Button></div>
            </div></div> ) }

            { showCampaignModal && ( <div className="modal-overlay" onClick={ () => setShowCampaignModal( false ) }><div className="modal-content campaign-modal" onClick={ e => e.stopPropagation() }>
              <h3>Create Voice Campaign</h3>
              <div className="form-group"><label>Name *</label><input type="text" value={ campaignName } onChange={ e => setCampaignName( e.target.value ) } placeholder="My Campaign" /></div>
              <div className="form-group"><label>Voice Message (TTS) *</label><textarea value={ campaignMessage } onChange={ e => setCampaignMessage( e.target.value ) } placeholder="Message to be spoken..." rows={ 3 } /></div>
              <div className="form-group"><label>Recipients ({ selectedContacts.length })</label><button type="button" className="pick-btn full-w" onClick={ () => setShowContactPicker( 'campaign' ) }>Select Contacts</button>
                { selectedContacts.length > 0 && ( <div className="tags">{ selectedContacts.map( id => { const c = contacts.find( x => x.contactId === id ); return c ? <span key={ id } className="tag">{ c.name } <button onClick={ () => setSelectedContacts( prev => prev.filter( x => x !== id ) ) }>�</button></span> : null; } ) }</div> ) }
              </div>
              <div className="modal-actions"><Button variant="secondary" onClick={ () => setShowCampaignModal( false ) }>Cancel</Button><Button variant="primary" onClick={ handleSendCampaign } loading={ campaignSending } disabled={ !campaignName || !campaignMessage || selectedContacts.length === 0 }>Call { selectedContacts.length }</Button></div>
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
        .voice-tab-content { padding: 0; }
        .tab-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 10px; }
        .tab-header-left { display: flex; align-items: center; gap: 8px; }
        .tab-header-actions { display: flex; gap: 6px; flex-wrap: wrap; }
        .provider-badge { background: #1a3a2a; color: #fff; padding: 3px 10px; border-radius: 6px; font-size: 11px; font-weight: 600; }
        .region-badge { background: #f3f4f6; color: #6b7280; padding: 3px 8px; border-radius: 4px; font-size: 10px; }
        .controls-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; gap: 10px; flex-wrap: wrap; }
        .filter-tabs { display: flex; gap: 4px; }
        .filter-tabs button { padding: 6px 12px; border: 1px solid #e5e7eb; background: #fff; border-radius: 6px; cursor: pointer; font-size: 12px; min-height: 44px; }
        .filter-tabs button.active { background: #d1f470; color: #1a3a2a; border-color: #1a3a2a; }
        .v-search { padding: 8px 12px; border: 1px solid #d1d5db; border-radius: 8px; width: 200px; max-width: 100%; font-size: 16px; min-height: 44px; box-sizing: border-box; }
        .v-search:focus { outline: none; border-color: #1a3a2a; box-shadow: 0 0 0 3px rgba(209,244,112,0.3); }
        .table-area { background: #fff; border-radius: 12px; border: 1px solid #e5e7eb; overflow: auto; }
        .loading-state { padding: 40px; text-align: center; color: #6b7280; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 10px 12px; text-align: left; border-bottom: 1px solid #f3f4f6; font-size: 12px; white-space: nowrap; }
        th { background: #f9fafb; font-weight: 600; color: #374151; position: sticky; top: 0; z-index: 1; }
        tr:hover { background: #f9fafb; }
        .time-cell { font-size: 11px; color: #6b7280; }
        .phone-cell { font-family: monospace; color: #1a3a2a; font-size: 11px; }
        .name-cell { font-weight: 500; color: #1a1a1a; }
        .success-cell { color: #1a3a2a; font-weight: 500; }
        .failed-cell { color: #1a3a2a; font-weight: 500; }
        .dir-in { background: #1a3a2a; color: #fff; padding: 2px 6px; border-radius: 4px; font-size: 10px; }
        .dir-out { background: #6b7280; color: #fff; padding: 2px 6px; border-radius: 4px; font-size: 10px; }
        .type-badge { padding: 2px 6px; border-radius: 4px; font-size: 10px; background: #f3f4f6; color: #374151; }
        .st-badge { padding: 2px 6px; border-radius: 4px; font-size: 10px; background: #f1f5f9; color: #6b7280; }
        .st-badge.connected, .st-badge.completed { background: #f9fafb; color: #1a3a2a; }
        .st-badge.initiated, .st-badge.sent { background: #eff6ff; color: #1d4ed8; }
        .st-badge.failed { background: #f9fafb; color: #1a3a2a; }
        .empty-row { text-align: center; color: #6b7280; padding: 30px !important; }
        .modal-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 1000; padding: 16px; }
        .modal-content { background: #fff; border-radius: 12px; padding: 20px; width: 100%; max-width: 420px; max-height: 90vh; overflow-y: auto; }
        .modal-content.campaign-modal { max-width: 480px; }
        .modal-content h3 { margin: 0 0 16px 0; color: #1a1a1a; }
        .form-group { margin-bottom: 14px; }
        .form-group label { display: block; font-size: 12px; font-weight: 500; margin-bottom: 5px; color: #374151; }
        .form-group input, .form-group textarea { width: 100%; padding: 8px 10px; border: 1px solid #d1d5db; border-radius: 8px; font-size: 13px; font-family: inherit; box-sizing: border-box; }
        .form-group input:focus, .form-group textarea:focus { outline: none; border-color: #1a3a2a; }
        .input-row { display: flex; gap: 6px; }
        .input-row input { flex: 1; }
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
          .v-search { width: 100%; }
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
      <SEO title="Voice" description="Business Calling — calls, campaigns and call records" />
      { shellContent }
    </Layout>
  );
};

export default VoicePage;
