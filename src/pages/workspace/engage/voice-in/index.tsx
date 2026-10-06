/**
 * Voice-IN Page - voice call records, text-to-speech and audio library.
 * Outbound dialling here is retired; PSTN voice is the Plivo softphone.
 * Tabs: Click-to-Call (C2C), OBD Campaigns, Call Detail Records (CDR)
 */
import React, { useState, useEffect, useCallback } from 'react';
import Layout from '../../../../components/Layout';
import SEO from '../../../../components/SEO';
import Button from '../../../../components/ui/Button';
import Pagination from '../../../../components/ui/Pagination';
import Tabs, { TabItem } from '../../../../components/ui/Tabs';
import { useToastContext } from '../../../../contexts/ToastContext';
import { useConfirm } from '../../../../contexts/ConfirmContext';
import * as api from '../../../../api/client';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }
interface Contact { contactId: string; name: string; phone: string; }
interface C2CCall { callId: string; fromNumber: string; toNumber: string; callerId: string; status: string; duration: number; recordingUrl?: string; correlationId?: string; createdAt: number; }
interface OBDCampaign { id: string; airtelCampaignId: string; campaignName: string; status: string; audioUrl: string; contactCount?: number; createdAt: number; }
interface CDRRecord {
  id: string; vmSessionId: string; clientCorrelationId: string;
  // The original 16-column CDR layout. Retained because historical rows still
  // populate these fields; Plivo rows are normalised into the same shape.
  date: string; time: string; callId: string; callerId: string;
  callerNumber: string; destinationCli: string; destinationNumber: string;
  callerWaitingTime: string; conversationDuration: string;
  overallCallStatus: string; hangupCause: string;
  callerStatus: string; destinationStatus: string;
  callerCircleName: string; pulseCount: number; recording: string;
  // Extended fields
  callType: string; direction: string; derivedOverallStatus: string;
  calledNumber: string; displayCliDestination: string;
  callerName: string; destinationName: string; customerId: string;
  // Timestamps
  startTime: number; endTime: number; callAnswerTime: number;
  // Durations (seconds)
  durationSec: number; conversationDurationSec: number;
  billableDurationSec: number; fromWaitingTimeSec: number; callerDurationSec: number;
  // Duration display (mm:ss)
  billableDurationDisplay: string; callerDurationDisplay: string; durationDisplay: string;
  // Status details
  callerNumberStatusDetails: string; destinationNumberStatusDetails: string;
  hangupStatus: string; hangupCauseDetail: string;
  // Circle & operator
  circleNameCaller: string; circleNameDestination: string;
  operatorNameCaller: string; operatorNameDestination: string;
  // Retry
  retryCountCaller: number; retryCountDestination: number;
  // Recording
  recordingURL: string; s3RecordingUrl: string;
  callerAudioUrl: string; destinationAudioUrl: string;
  // Per-participant timing
  callerStartTime: number; callerEndTime: number; callerAnswerTime: number;
  destStartTime: number; destEndTime: number; destAnswerTime: number;
  // OBD Campaign
  campaignId: string; campaignName: string; dtmfCapture: string;
  // Setup & metadata
  callSetupTimeCaller: number; source: string; participantsCount: number;
  timestamp: string; createdAt: number;
  // IST timestamp
  istTimestamp: string;
  // WhatsApp message trigger
  whatsappMessageTriggered: boolean; whatsappMessageId: string;
  whatsappMessageContent: string; whatsappMessageTimestamp: string;
  smsTriggered: boolean; smsMessageId: string; smsDltTemplateId: string;
  smsContent: string; smsTimestamp: string;
  // RCS message trigger
  rcsMessageTriggered: boolean; rcsMessageId: string;
  rcsMessageContent: string; rcsMessageTimestamp: string;
}

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api';
const RETIRED_ACTION_REASON =
  'Outbound calling here has been retired. This page dialled a retired India voice '
  + 'provider; PSTN voice is now Plivo, and outbound calling arrives with the Plivo '
  + 'browser softphone. Historical records, call detail records, text-to-speech and '
  + 'the audio library on this page are unaffected.';

const ITEMS_PER_PAGE = 100;

const VoiceInPage: React.FC<PageProps> = ( { signOut, user, embedded = false } ) => {
  const [ activeTab, setActiveTab ] = useState<'c2c' | 'obd' | 'cdr'>( 'c2c' );
  const [ c2cCalls, setC2cCalls ] = useState<C2CCall[]>( [] );
  const [ obdCampaigns, setObdCampaigns ] = useState<OBDCampaign[]>( [] );
  const [ cdrs, setCdrs ] = useState<CDRRecord[]>( [] );
  const [ loading, setLoading ] = useState( true );
  const [ page, setPage ] = useState( 1 );
  const [ searchQuery, setSearchQuery ] = useState( '' );

  const [ showC2CModal, setShowC2CModal ] = useState( false );
  const [ c2cFromNumber, setC2cFromNumber ] = useState( '' );
  const [ c2cToNumber, setC2cToNumber ] = useState( '' );
  const [ c2cRecording, setC2cRecording ] = useState( true );
  const [ c2cCalling, setC2cCalling ] = useState( false );

  const [ showOBDModal, setShowOBDModal ] = useState( false );
  const [ obdNumbers, setObdNumbers ] = useState( '' );
  const [ obdCampaignName, setObdCampaignName ] = useState( '' );
  const [ obdCreating, setObdCreating ] = useState( false );
  const [ obdVariables, setObdVariables ] = useState<{ [ phone: string ]: { [ key: string ]: string } }>( {} );
  const [ obdVarNames, setObdVarNames ] = useState<string[]>( [] );
  const [ obdAudioSource, setObdAudioSource ] = useState<'default' | 'upload' | 'tts' | 'library'>( 'default' );
  const [ obdTtsText, setObdTtsText ] = useState( '' );
  const [ obdTtsVoice, setObdTtsVoice ] = useState( 'Kajal' );
  const [ obdTtsLang, setObdTtsLang ] = useState( 'en-IN' );
  const [ obdSelectedLibraryFile, setObdSelectedLibraryFile ] = useState<{ key: string; name: string; publicUrl: string } | null>( null );
  const [ obdAudioFile, setObdAudioFile ] = useState<File | null>( null );
  const [ obdTtsGenerating, setObdTtsGenerating ] = useState( false );
  const [ audioLibrary, setAudioLibrary ] = useState<{ key: string; name: string; size: number; lastModified: string; publicUrl: string; downloadUrl?: string; sampleRate?: number; channels?: number; bitsPerSample?: number; airtelCompliant?: boolean; formatLabel?: string }[]>( [] );
  const [ loadingAudioLibrary, setLoadingAudioLibrary ] = useState( false );
  const [ uploadingToLibrary, setUploadingToLibrary ] = useState( false );

  const [ contacts, setContacts ] = useState<Contact[]>( [] );
  const [ showContactPicker, setShowContactPicker ] = useState<'c2c-from' | 'c2c-to' | 'obd' | null>( null );
  const [ contactSearch, setContactSearch ] = useState( '' );
  const [ loadingContacts, setLoadingContacts ] = useState( false );
  const [ clearing, setClearing ] = useState( false );
  const [ cdrDirectionFilter, setCdrDirectionFilter ] = useState<'all' | 'INBOUND' | 'OUTBOUND'>( 'all' );
  const [ expandedCdr, setExpandedCdr ] = useState<string | null>( null );
  const [ cdrStartDate, setCdrStartDate ] = useState( '' );
  const [ cdrEndDate, setCdrEndDate ] = useState( '' );
  const [ showVarInput, setShowVarInput ] = useState( false );
  const [ varInputValue, setVarInputValue ] = useState( '' );
  const [ cdrError, setCdrError ] = useState( '' );

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

  const loadAudioLibrary = useCallback( async () => {
    setLoadingAudioLibrary( true );
    try
    {
      const resp = await fetch( `${API_BASE}/voice-in/obd/audio-library` );
      const data = await resp.json();
      setAudioLibrary( data.files || [] );
    } catch ( err ) { console.error( 'Load audio library error:', err ); } finally { setLoadingAudioLibrary( false ); }
  }, [] );

  const handleUploadToLibrary = async ( file: File ) => {
    setUploadingToLibrary( true );
    try
    {
      const reader = new FileReader();
      const audioData = await new Promise<string>( ( resolve ) => {
        reader.onload = () => resolve( ( reader.result as string ).split( ',' )[ 1 ] );
        reader.readAsDataURL( file );
      } );
      const resp = await fetch( `${API_BASE}/voice-in/obd/audio-library`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        // `uploadToAirtel: true` was sent here until 2026-09-25. Airtel is retired
        // and no handler code ever read the field - it survived only in a docstring -
        // so every audio upload carried a flag asking a dead provider to receive it.
        body: JSON.stringify( { audioData, fileName: file.name } )
      } );
      const result = await resp.json();
      if ( result.success )
      {
        const convMsg = result.converted ? ` (converted: ${result.conversionReport})` : '';
        // The message used to append ' + prompt upload' when `result.airtelAudioUrl`
        // was set. The handler stopped returning that field when the audio URL moved
        // to storage we control, so the branch could never fire and the suffix never
        // appeared. Removed rather than left as a condition that is always false.
        toast.success( `Audio "${file.name}" saved to library${convMsg}` );
        await loadAudioLibrary();
      } else
      {
        toast.error( result.error || 'Upload failed' );
        if ( result.report ) toast.error( result.report );
      }
    } catch ( err ) { toast.error( 'Failed to upload audio' ); } finally { setUploadingToLibrary( false ); }
  };

  const handleDeleteLibraryFile = async ( s3Key: string, name: string ) => {
    if ( !( await confirm( `Delete "${name}" from audio library?` ) ) ) return;
    try
    {
      await fetch( `${API_BASE}/voice-in/obd/audio-library`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify( { s3Key } )
      } );
      toast.success( `Deleted "${name}"` );
      setAudioLibrary( prev => prev.filter( f => f.key !== s3Key ) );
      if ( obdSelectedLibraryFile?.key === s3Key ) setObdSelectedLibraryFile( null );
    } catch ( err ) { toast.error( 'Failed to delete' ); }
  };

  const loadData = useCallback( async () => {
    setLoading( true );
    try
    {
      const cdrParams = new URLSearchParams();
      cdrParams.set( 'limit', '500' );
      if ( cdrStartDate ) cdrParams.set( 'startDate', String( Math.floor( new Date( cdrStartDate ).getTime() / 1000 ) ) );
      if ( cdrEndDate ) cdrParams.set( 'endDate', String( Math.floor( new Date( cdrEndDate + 'T23:59:59' ).getTime() / 1000 ) ) );
      const cdrQs = `?${cdrParams.toString()}`;

      const [ c2cResponse, obdResponse, cdrResponse ] = await Promise.all( [
        fetch( `${API_BASE}/voice-in/c2c` ).then( r => r.json() ).catch( e => { console.error( 'C2C fetch error:', e ); return { calls: [] }; } ),
        fetch( `${API_BASE}/voice-in/obd` ).then( r => r.json() ).catch( e => { console.error( 'OBD fetch error:', e ); return { campaigns: [] }; } ),
        api.authFetch( `${API_BASE}/voice-cdr-read${cdrQs}` ).then( r => { if ( !r.ok ) { console.error( 'CDR API error:', r.status, r.statusText ); } return r.json(); } ).catch( e => { console.error( 'CDR fetch error:', e ); return { records: [], error: String( e ) }; } )
      ] );
      setC2cCalls( c2cResponse.calls || [] );
      setObdCampaigns( obdResponse.campaigns || [] );
      setCdrs( cdrResponse.records || [] );
      if ( cdrResponse.error ) { console.error( 'CDR API returned error:', cdrResponse.error ); setCdrError( cdrResponse.error ); } else { setCdrError( '' ); }
    } catch ( err ) { console.error( 'Load error:', err ); toast.error( 'Failed to load data' ); } finally { setLoading( false ); }
  }, [ toast, cdrStartDate, cdrEndDate ] );

  useEffect( () => { loadData(); const interval = setInterval( loadData, 60000 ); return () => clearInterval( interval ); }, [ loadData ] );
  useEffect( () => { setPage( 1 ); }, [ activeTab, searchQuery ] );
  useEffect( () => { if ( showContactPicker ) loadContacts(); }, [ showContactPicker, loadContacts ] );
  useEffect( () => { if ( showOBDModal && audioLibrary.length === 0 ) loadAudioLibrary(); }, [ showOBDModal, audioLibrary.length, loadAudioLibrary ] );

  const filteredContacts = contacts.filter( c =>
    c.name.toLowerCase().includes( contactSearch.toLowerCase() ) ||
    c.phone.includes( contactSearch )
  );

  const selectContact = ( contact: Contact ) => {
    if ( showContactPicker === 'c2c-from' ) setC2cFromNumber( contact.phone );
    else if ( showContactPicker === 'c2c-to' ) setC2cToNumber( contact.phone );
    else if ( showContactPicker === 'obd' )
    {
      const current = obdNumbers.trim();
      setObdNumbers( current ? `${current}\n${contact.phone}` : contact.phone );
    }
    setShowContactPicker( null );
    setContactSearch( '' );
  };

  const formatDuration = ( seconds: number ) => {
    if ( !seconds ) return '0:00';
    const mins = Math.floor( seconds / 60 );
    const secs = Math.round( seconds % 60 );
    return `${mins}:${secs.toString().padStart( 2, '0' )}`;
  };

  // Click-to-call initiation dialled a retired India voice provider and now
  // answers 410 server-side.
  const handleC2CCall = async () => {
    toast.error( RETIRED_ACTION_REASON );
    setShowC2CModal( false );
  };

  const handleOBDCreate = async () => {
    toast.error( RETIRED_ACTION_REASON );
    setShowOBDModal( false );
  };

  // Prompt-variable helpers. These belong to the OBD audio/TTS flow, which is
  // retained - only campaign DIALLING was retired.
  const addOBDVariable = () => {
    setShowVarInput( true );
    setVarInputValue( '' );
  };

  const confirmAddVariable = () => {
    const varName = varInputValue.trim();
    if ( varName && /^\w+$/.test( varName ) && !obdVarNames.includes( varName ) )
    {
      setObdVarNames( prev => [ ...prev, varName ] );
    }
    setShowVarInput( false );
    setVarInputValue( '' );
  };

  const handleClearLogs = async ( type: 'c2c' | 'obd' | 'cdr' ) => {
    if ( !( await confirm( `Clear all ${type.toUpperCase()} logs? This cannot be undone.` ) ) ) return;
    setClearing( true );
    try
    {
      // CDR clear now goes to the AUTHENTICATED read API, not the webhook.
      // DELETE /voice-cdr-webhook/clear-logs was AuthorizationType=NONE with no
      // require_auth in its handler, i.e. anyone on the internet could wipe every
      // call detail record. That route is deleted; voice-cdr-read owns clearing
      // and calls require_auth, so this must use authFetch.
      const response = type === 'cdr'
        ? await api.authFetch( `${API_BASE}/voice-cdr-read`, {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify( { clearAll: true, hardDelete: true } )
        } )
        : await fetch( `${API_BASE}/voice-in/${type}/clear-logs`, {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify( { clearAll: true, hardDelete: true } )
        } );
      const result = await response.json();
      if ( result.success )
      {
        setTimeout( () => toast.success( `Cleared ${result.deletedCount || 0} ${type.toUpperCase()} logs` ), 100 );
        await loadData();
      } else
      {
        setTimeout( () => toast.error( result.error || 'Failed to clear logs' ), 100 );
      }
    } catch ( err )
    {
      console.error( 'Clear logs error:', err );
      setTimeout( () => toast.error( 'Failed to clear logs' ), 100 );
    } finally { setClearing( false ); }
  };

  const filterBySearch = ( items: any[], fields: string[] ) => {
    if ( !searchQuery ) return items;
    const q = searchQuery.toLowerCase();
    return items.filter( item => fields.some( f => item[ f ]?.toString().toLowerCase().includes( q ) ) );
  };

  const filteredC2C = filterBySearch( c2cCalls, [ 'fromNumber', 'toNumber', 'status', 'correlationId' ] );
  const filteredOBD = filterBySearch( obdCampaigns, [ 'campaignName', 'status', 'airtelCampaignId' ] );
  const filteredCDR = filterBySearch( cdrs, [ 'callerNumber', 'destinationNumber', 'destinationCli', 'callType', 'overallCallStatus', 'callerStatus', 'destinationStatus', 'callerId', 'campaignName', 'vmSessionId' ] )
    .filter( cdr => cdrDirectionFilter === 'all' || cdr.callType === cdrDirectionFilter );

  const getCurrentData = () => {
    switch ( activeTab )
    {
      case 'c2c': return filteredC2C;
      case 'obd': return filteredOBD;
      case 'cdr': return filteredCDR;
      default: return [];
    }
  };

  const currentData = getCurrentData();
  const totalPages = Math.ceil( currentData.length / ITEMS_PER_PAGE );
  const paginatedData = currentData.slice( ( page - 1 ) * ITEMS_PER_PAGE, page * ITEMS_PER_PAGE );

  const tabItems: TabItem[] = [
    { id: 'c2c', label: `C2C (${c2cCalls.length})` },
    { id: 'obd', label: `OBD (${obdCampaigns.length})` },
    { id: 'cdr', label: `CDR (${cdrs.length})` }
  ];

  const pageContent = (
    <>
      <div className="voice-page">
        <div className="page-header">
          <div className="header-title">
            <PhoneIcon />
            <h2>Voice IN</h2>
            <span className="badge">C2C + OBD + CDR</span>
          </div>
          <div className="header-actions">
            {/* C2C and OBD initiation are retired. The buttons stay visible but
                disabled, with the reason in the title, because silently removing
                them would leave an operator wondering where the feature went. */}
            <Button variant="secondary" disabled
              title={ RETIRED_ACTION_REASON }>C2C (retired)</Button>
            <Button variant="secondary" disabled
              title={ RETIRED_ACTION_REASON }>OBD (retired)</Button>
            <Button variant="secondary" onClick={ () => handleClearLogs( activeTab ) } disabled={ clearing } loading={ clearing }>Clear</Button>
            <Button variant="secondary" icon="refresh" onClick={ loadData } disabled={ loading } loading={ loading }>Refresh</Button>
          </div>
        </div>

        <div className="tabs-row">
          <Tabs items={ tabItems } activeTab={ activeTab } onChange={ ( id ) => setActiveTab( id as 'c2c' | 'obd' | 'cdr' ) } />
        </div>

        <div className="controls-row">
          <input type="text" placeholder="Search..." value={ searchQuery } onChange={ e => setSearchQuery( e.target.value ) } className="search-input" />
          <Pagination currentPage={ page } totalPages={ totalPages } onPageChange={ setPage } />
        </div>

        <div className="content-area">
          { loading ? (
            <div className="loading-state">Loading...</div>
          ) : (
            <>
              { activeTab === 'c2c' && (
                <div className="table-container">
                  <table>
                    <thead>
                      <tr>
                        <th>Time</th>
                        <th>From</th>
                        <th>To</th>
                        <th>Duration</th>
                        <th>Status</th>
                        <th className="hide-mobile">Correlation ID</th>
                        <th>Recording</th>
                      </tr>
                    </thead>
                    <tbody>
                      { ( paginatedData as C2CCall[] ).map( call => (
                        <tr key={ call.callId }>
                          <td className="time-cell">{ new Date( call.createdAt * 1000 ).toLocaleString() }</td>
                          <td className="phone-cell">{ call.fromNumber }</td>
                          <td className="phone-cell">{ call.toNumber }</td>
                          <td>{ formatDuration( call.duration ) }</td>
                          <td><span className={ `status-badge ${call.status?.toLowerCase()}` }>{ call.status }</span></td>
                          <td className="id-cell hide-mobile">{ call.correlationId?.slice( 0, 12 ) }...</td>
                          <td>{ call.recordingUrl ? <a href={ call.recordingUrl } target="_blank" rel="noopener noreferrer" className="recording-link">Rec</a> : '-' }</td>
                        </tr>
                      ) ) }
                      { paginatedData.length === 0 && <tr><td colSpan={ 7 } className="empty-state">No C2C calls yet</td></tr> }
                    </tbody>
                  </table>
                </div>
              ) }

              { activeTab === 'obd' && (
                <div className="table-container">
                  <table>
                    <thead>
                      <tr>
                        <th>Created</th>
                        <th>Campaign</th>
                        <th>Session ID</th>
                        <th>Contacts</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      { ( paginatedData as OBDCampaign[] ).map( campaign => (
                        <tr key={ campaign.id }>
                          <td className="time-cell">{ new Date( campaign.createdAt * 1000 ).toLocaleString() }</td>
                          <td className="name-cell">{ campaign.campaignName }</td>
                          <td className="id-cell">{ campaign.airtelCampaignId?.slice( 0, 12 ) }...</td>
                          <td>{ campaign.contactCount || '-' }</td>
                          <td><span className={ `status-badge ${campaign.status?.toLowerCase()}` }>{ campaign.status }</span></td>
                        </tr>
                      ) ) }
                      { paginatedData.length === 0 && <tr><td colSpan={ 5 } className="empty-state">No OBD campaigns yet</td></tr> }
                    </tbody>
                  </table>
                </div>
              ) }

              { activeTab === 'cdr' && (
                <div className="table-container">
                  <div style={ { padding: '8px 12px', background: '#f9fafb', borderBottom: '1px solid #f3f4f6', display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' } }>
                    <span style={ { fontSize: '12px', color: '#0f2a1d', fontWeight: 500 } }>Direction:</span>
                    { ( [ 'all', 'INBOUND', 'OUTBOUND' ] as const ).map( dir => (
                      <button key={ dir } onClick={ () => setCdrDirectionFilter( dir ) } style={ { padding: '3px 10px', borderRadius: '4px', border: '1px solid', borderColor: cdrDirectionFilter === dir ? '#1a3a2a' : '#f3f4f6', background: cdrDirectionFilter === dir ? '#f3f4f6' : '#fff', color: '#0f2a1d', fontSize: '11px', cursor: 'pointer', fontWeight: cdrDirectionFilter === dir ? 600 : 400 } }>
                        { dir === 'all' ? 'All' : dir }
                      </button>
                    ) ) }
                    <span style={ { marginLeft: '12px', fontSize: '12px', color: '#0f2a1d', fontWeight: 500 } }>Date:</span>
                    <input type="date" value={ cdrStartDate } onChange={ e => setCdrStartDate( e.target.value ) } className="cdr-date-input" />
                    <span style={ { fontSize: '11px', color: '#6b7280' } }>to</span>
                    <input type="date" value={ cdrEndDate } onChange={ e => setCdrEndDate( e.target.value ) } className="cdr-date-input" />
                    { ( cdrStartDate || cdrEndDate ) && (
                      <button onClick={ () => { setCdrStartDate( '' ); setCdrEndDate( '' ); } } className="cdr-date-clear">Clear</button>
                    ) }
                  </div>
                  <table>
                    <thead>
                      <tr>
                        <th></th>
                        <th>Date</th>
                        <th>Time</th>
                        <th>Type</th>
                        <th>Caller</th>
                        <th>Destination</th>
                        <th>Wait</th>
                        <th>Talk</th>
                        <th>Billable</th>
                        <th>Status</th>
                        <th className="hide-mobile">Hangup</th>
                        <th className="hide-mobile">Caller St.</th>
                        <th className="hide-mobile">Dest St.</th>
                        <th>Rec</th>
                      </tr>
                    </thead>
                    <tbody>
                      { ( paginatedData as CDRRecord[] ).map( cdr => (
                        <React.Fragment key={ cdr.id }>
                          <tr onClick={ () => setExpandedCdr( expandedCdr === cdr.id ? null : cdr.id ) } style={ { cursor: 'pointer' } }>
                            <td style={ { width: '20px', textAlign: 'center', fontSize: '10px' } }>{ expandedCdr === cdr.id ? '▼' : '▶' }</td>
                            <td className="time-cell">{ cdr.date || new Date( cdr.createdAt * 1000 ).toLocaleDateString( 'en-IN' ) }</td>
                            <td className="time-cell">{ cdr.time || new Date( cdr.createdAt * 1000 ).toLocaleTimeString( 'en-IN' ) }</td>
                            <td><span className="type-badge">{ cdr.callType }</span></td>
                            <td className="phone-cell">{ cdr.callerNumber }</td>
                            <td className="phone-cell">{ cdr.destinationCli || cdr.destinationNumber }</td>
                            <td>{ cdr.callerWaitingTime || '0:00' }</td>
                            <td>{ cdr.conversationDuration || '0:00' }</td>
                            <td>{ cdr.billableDurationDisplay || '0:00' }</td>
                            <td><span className={ `status-badge ${( cdr.overallCallStatus || '' ).toLowerCase()}` }>{ cdr.overallCallStatus }</span></td>
                            <td className="hide-mobile">{ cdr.hangupCause || cdr.hangupStatus || '-' }</td>
                            <td className="hide-mobile"><span className={ `status-badge ${( cdr.callerStatus || '' ).toLowerCase()}` }>{ cdr.callerStatus || '-' }</span></td>
                            <td className="hide-mobile"><span className={ `status-badge ${( cdr.destinationStatus || '' ).toLowerCase()}` }>{ cdr.destinationStatus || '-' }</span></td>
                            <td>{ ( cdr.recording || cdr.recordingURL || cdr.s3RecordingUrl ) ? <a href={ cdr.recording || cdr.recordingURL || cdr.s3RecordingUrl } target="_blank" rel="noopener noreferrer" className="recording-link">Rec</a> : '-' }</td>
                          </tr>
                          { expandedCdr === cdr.id && (
                            <tr className="cdr-detail-row">
                              <td colSpan={ 14 } style={ { padding: '12px 16px', background: '#f9fafb', fontSize: '11px' } }>
                                <div style={ { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: '8px 16px' } }>
                                  <div><span className="detail-label">Session ID:</span> { cdr.vmSessionId }</div>
                                  <div><span className="detail-label">Call ID:</span> { cdr.callId || cdr.clientCorrelationId }</div>
                                  <div><span className="detail-label">Caller ID (CLI):</span> { cdr.callerId || '-' }</div>
                                  <div><span className="detail-label">Called Number:</span> { cdr.calledNumber || '-' }</div>
                                  <div><span className="detail-label">Dest CLI:</span> { cdr.displayCliDestination || '-' }</div>
                                  <div><span className="detail-label">Caller Name:</span> { cdr.callerName || '-' }</div>
                                  <div><span className="detail-label">Dest Name:</span> { cdr.destinationName || '-' }</div>
                                  <div><span className="detail-label">Derived Status:</span> { cdr.derivedOverallStatus || '-' }</div>
                                  <div><span className="detail-label">Duration:</span> { cdr.durationDisplay || formatDuration( cdr.durationSec ) }</div>
                                  <div><span className="detail-label">Caller Duration:</span> { cdr.callerDurationDisplay || '-' }</div>
                                  <div><span className="detail-label">Hangup Detail:</span> { cdr.hangupCauseDetail || '-' }</div>
                                  <div><span className="detail-label">Caller Status Detail:</span> { cdr.callerNumberStatusDetails || '-' }</div>
                                  <div><span className="detail-label">Dest Status Detail:</span> { cdr.destinationNumberStatusDetails || '-' }</div>
                                  <div><span className="detail-label">Setup Time:</span> { cdr.callSetupTimeCaller ? `${cdr.callSetupTimeCaller}ms` : '-' }</div>
                                  <div><span className="detail-label">Participants:</span> { cdr.participantsCount || '-' }</div>
                                  { cdr.campaignId && <div><span className="detail-label">Campaign:</span> { cdr.campaignName || cdr.campaignId }</div> }
                                  { cdr.dtmfCapture && <div><span className="detail-label">DTMF:</span> { cdr.dtmfCapture }</div> }
                                  { cdr.callerAudioUrl && <div><span className="detail-label">Caller Audio:</span> <a href={ cdr.callerAudioUrl } target="_blank" rel="noopener noreferrer">Play</a></div> }
                                  { cdr.destinationAudioUrl && <div><span className="detail-label">Dest Audio:</span> <a href={ cdr.destinationAudioUrl } target="_blank" rel="noopener noreferrer">Play</a></div> }
                                  <div><span className="detail-label">Source:</span> { cdr.source }</div>
                                  <div><span className="detail-label">Timestamp:</span> { cdr.istTimestamp || cdr.timestamp }</div>
                                </div>
                                {/* WhatsApp / SMS Message Trigger Section */ }
                                { ( cdr.whatsappMessageTriggered || cdr.smsTriggered || cdr.whatsappMessageId || cdr.smsMessageId ) && (
                                  <div style={ { marginTop: '10px', padding: '8px 10px', background: '#f0fdf4', borderRadius: '6px', border: '1px solid #bbf7d0' } }>
                                    <div style={ { fontWeight: 600, fontSize: '11px', color: '#166534', marginBottom: '6px' } }>📱 WhatsApp / SMS Trigger</div>
                                    <div style={ { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: '4px 16px' } }>
                                      { cdr.whatsappMessageId && <div><span className="detail-label">WA Message ID:</span> <code style={ { fontSize: '10px', background: '#fff', padding: '1px 4px', borderRadius: '3px' } }>{ cdr.whatsappMessageId }</code></div> }
                                      { cdr.whatsappMessageContent && <div><span className="detail-label">WA Content:</span> { cdr.whatsappMessageContent.substring( 0, 80 ) }{ cdr.whatsappMessageContent.length > 80 ? '...' : '' }</div> }
                                      { cdr.whatsappMessageTimestamp && <div><span className="detail-label">WA Sent At:</span> { cdr.whatsappMessageTimestamp }</div> }
                                      { cdr.smsMessageId && <div><span className="detail-label">SMS Message ID:</span> <code style={ { fontSize: '10px', background: '#fff', padding: '1px 4px', borderRadius: '3px' } }>{ cdr.smsMessageId }</code></div> }
                                      { cdr.smsDltTemplateId && <div><span className="detail-label">DLT Template:</span> { cdr.smsDltTemplateId }</div> }
                                      { cdr.smsContent && <div><span className="detail-label">SMS Content:</span> { cdr.smsContent.substring( 0, 80 ) }{ cdr.smsContent.length > 80 ? '...' : '' }</div> }
                                      { cdr.smsTimestamp && <div><span className="detail-label">SMS Sent At:</span> { cdr.smsTimestamp }</div> }
                                    </div>
                                  </div>
                                ) }
                                {/* RCS Message Trigger Section */ }
                                { ( cdr.rcsMessageTriggered || cdr.rcsMessageId ) && (
                                  <div style={ { marginTop: '8px', padding: '8px 10px', background: '#eff6ff', borderRadius: '6px', border: '1px solid #bfdbfe' } }>
                                    <div style={ { fontWeight: 600, fontSize: '11px', color: '#1e40af', marginBottom: '6px' } }>💬 RCS Message Trigger</div>
                                    <div style={ { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: '4px 16px' } }>
                                      { cdr.rcsMessageId && <div><span className="detail-label">RCS Message ID:</span> <code style={ { fontSize: '10px', background: '#fff', padding: '1px 4px', borderRadius: '3px' } }>{ cdr.rcsMessageId }</code></div> }
                                      { cdr.rcsMessageContent && <div><span className="detail-label">RCS Content:</span> { cdr.rcsMessageContent.substring( 0, 80 ) }{ cdr.rcsMessageContent.length > 80 ? '...' : '' }</div> }
                                      { cdr.rcsMessageTimestamp && <div><span className="detail-label">RCS Sent At:</span> { cdr.rcsMessageTimestamp }</div> }
                                    </div>
                                  </div>
                                ) }
                              </td>
                            </tr>
                          ) }
                        </React.Fragment>
                      ) ) }
                      { paginatedData.length === 0 && <tr><td colSpan={ 14 } className="empty-state">{ cdrError ? `CDR Error: ${cdrError}` : 'No CDR records yet' }</td></tr> }
                    </tbody>
                  </table>
                  <div className="webhook-info">
                    <strong>CDR Webhook (provider &rarr; us):</strong>
                    <code>{ API_BASE }/voice-cdr-webhook</code>
                    <div style={ { marginTop: '4px', fontSize: '11px', color: '#6b7280' } }>Receives call detail records for all call types. Live PSTN records arrive from the voice network; C2C and OBD rows are historical.</div>
                    <strong style={ { marginTop: '8px', display: 'block' } }>CDR Read API (Dashboard):</strong>
                    <code>{ API_BASE }/voice-cdr-read</code>
                    <div style={ { marginTop: '4px', fontSize: '11px', color: '#6b7280' } }>Read CDRs with filters, stats, and dashboard aggregations (?dashboard=true)</div>
                  </div>
                </div>
              ) }
            </>
          ) }
        </div>

        { totalPages > 1 && (
          <div className="controls-row" style={ { marginTop: '8px', flexShrink: 0 } }>
            <div style={ { fontSize: '12px', color: '#6b7280' } }>
              Showing { ( ( page - 1 ) * ITEMS_PER_PAGE ) + 1 }–{ Math.min( page * ITEMS_PER_PAGE, currentData.length ) } of { currentData.length }
            </div>
            <Pagination currentPage={ page } totalPages={ totalPages } onPageChange={ setPage } />
          </div>
        ) }
      </div>

      { showC2CModal && (
        <div className="modal-overlay" onClick={ () => setShowC2CModal( false ) }>
          <div className="modal-content" onClick={ e => e.stopPropagation() }>
            <h3>Click-to-Call (C2C)</h3>
            <p className="modal-desc">Connect two parties on a call.</p>
            <div className="form-group">
              <label>From Number * <span style={ { fontSize: 10, color: '#6b7280', fontWeight: 400 } }>(10 digits, no country code)</span></label>
              <div className="input-with-btn">
                <input type="tel" value={ c2cFromNumber } onChange={ e => setC2cFromNumber( e.target.value ) } placeholder="9903300044" />
                <button type="button" className="fetch-btn" onClick={ () => setShowContactPicker( 'c2c-from' ) }>Contacts</button>
              </div>
            </div>
            <div className="form-group">
              <label>To Number * <span style={ { fontSize: 10, color: '#6b7280', fontWeight: 400 } }>(10 digits, no country code)</span></label>
              <div className="input-with-btn">
                <input type="tel" value={ c2cToNumber } onChange={ e => setC2cToNumber( e.target.value ) } placeholder="9903300044" />
                <button type="button" className="fetch-btn" onClick={ () => setShowContactPicker( 'c2c-to' ) }>Contacts</button>
              </div>
            </div>
            <div className="form-group checkbox-group"><label><input type="checkbox" checked={ c2cRecording } onChange={ e => setC2cRecording( e.target.checked ) } />Enable Recording</label></div>
            <div className="info-box"><strong>Config:</strong> Caller ID: 8047311032 (Fixed Line · Karnataka) | App: WECAREDIG_fD4BKqUbC8k90jNrPR0n</div>
            <div className="modal-actions"><Button variant="secondary" onClick={ () => setShowC2CModal( false ) }>Cancel</Button><Button variant="primary" onClick={ handleC2CCall } loading={ c2cCalling } disabled={ !c2cFromNumber || !c2cToNumber }>Call</Button></div>
          </div>
        </div>
      ) }

      { showOBDModal && (
        <div className="modal-overlay" onClick={ () => setShowOBDModal( false ) }>
          <div className="modal-content obd-modal" onClick={ e => e.stopPropagation() }>
            <h3>Create OBD Campaign</h3>
            <p className="modal-desc">Outbound Dialer campaign with audio options.</p>
            <div className="form-group">
              <label>Campaign Name *</label>
              <input type="text" value={ obdCampaignName } onChange={ e => setObdCampaignName( e.target.value ) } placeholder="e.g. Promo Feb 2026" />
            </div>
            <div className="form-group">
              <label>Audio Source</label>
              {/* data-ui-raw ON ALL FOUR RADIOS. `.audio-option input[type="radio"]` hides them
                  with display: none at :823 and the visible control is the .audio-option label
                  itself - its 2px border and its lime .selected state. form-controls.css would
                  otherwise draw an 18px bordered box with a white dot on each one, a second
                  control on top of the first. They are inert today only because this file never
                  declares `display`, which is an accident rather than a contract. */}
              <div className="audio-options">
                <label className={ `audio-option ${obdAudioSource === 'default' ? 'selected' : ''}` }>
                  <input type="radio" data-ui-raw name="audioSource" checked={ obdAudioSource === 'default' } onChange={ () => setObdAudioSource( 'default' ) } />
                  🔔 Default Jingle
                </label>
                <label className={ `audio-option ${obdAudioSource === 'library' ? 'selected' : ''}` }>
                  <input type="radio" data-ui-raw name="audioSource" checked={ obdAudioSource === 'library' } onChange={ () => { setObdAudioSource( 'library' ); loadAudioLibrary(); } } />
                  📚 Audio Library
                </label>
                <label className={ `audio-option ${obdAudioSource === 'tts' ? 'selected' : ''}` }>
                  <input type="radio" data-ui-raw name="audioSource" checked={ obdAudioSource === 'tts' } onChange={ () => setObdAudioSource( 'tts' ) } />
                  🗣️ Text to Speech
                </label>
                <label className={ `audio-option ${obdAudioSource === 'upload' ? 'selected' : ''}` }>
                  <input type="radio" data-ui-raw name="audioSource" checked={ obdAudioSource === 'upload' } onChange={ () => setObdAudioSource( 'upload' ) } />
                  📁 Upload WAV
                </label>
              </div>
            </div>
            { obdAudioSource === 'library' && (
              <div className="form-group">
                <label>Select from Audio Library</label>
                { loadingAudioLibrary ? <div style={ { padding: '12px', fontSize: '12px', color: '#6b7280' } }>Loading audio files...</div> : audioLibrary.length === 0 ? (
                  <div style={ { padding: '12px', fontSize: '12px', color: '#6b7280' } }>No audio files yet. Upload one below.</div>
                ) : (
                  <div className="audio-library-list">
                    { audioLibrary.map( file => (
                      <div key={ file.key } className={ `audio-library-item ${obdSelectedLibraryFile?.key === file.key ? 'selected' : ''}` } onClick={ () => setObdSelectedLibraryFile( file ) }>
                        <div className="audio-lib-info">
                          <span className="audio-lib-name">{ file.name }</span>
                          <span className="audio-lib-meta">
                            { ( file.size / 1024 ).toFixed( 1 ) } KB
                            { file.formatLabel && <> · { file.formatLabel }</> }
                            { file.airtelCompliant !== undefined && (
                              <span className={ `audio-compliance ${file.airtelCompliant ? 'ok' : 'warn'}` }>
                                { file.airtelCompliant ? ' ✓ Telephony-ready' : ' ⚠ Non-compliant' }
                              </span>
                            ) }
                          </span>
                        </div>
                        <div className="audio-lib-actions">
                          <audio src={ file.publicUrl } controls preload="none" style={ { height: '28px', maxWidth: '140px' } } />
                          <a href={ file.downloadUrl || file.publicUrl } download={ file.name } className="audio-lib-dl" title="Download" onClick={ e => e.stopPropagation() }>⬇</a>
                          <button type="button" className="audio-lib-del" onClick={ ( e ) => { e.stopPropagation(); handleDeleteLibraryFile( file.key, file.name ); } } title="Delete">×</button>
                        </div>
                      </div>
                    ) ) }
                  </div>
                ) }
                <div style={ { marginTop: '8px' } }>
                  <label className="fetch-btn" style={ { display: 'inline-block', cursor: 'pointer' } }>
                    { uploadingToLibrary ? 'Uploading...' : '+ Upload to Library' }
                    <input type="file" accept=".wav,audio/wav" style={ { display: 'none' } } disabled={ uploadingToLibrary } onChange={ e => { const f = e.target.files?.[ 0 ]; if ( f ) handleUploadToLibrary( f ); e.target.value = ''; } } />
                  </label>
                  <button type="button" className="fetch-btn" style={ { marginLeft: '6px' } } onClick={ loadAudioLibrary } disabled={ loadingAudioLibrary }>↻ Refresh</button>
                </div>
              </div>
            ) }
            { obdAudioSource === 'tts' && (
              <div className="form-group">
                <label>Text to Speak *</label>
                <textarea value={ obdTtsText } onChange={ e => setObdTtsText( e.target.value ) } placeholder="Type your message here... (max 3000 chars)" rows={ 3 } maxLength={ 3000 } />
                <small>{ obdTtsText.length }/3000 chars</small>
                <div style={ { display: 'flex', gap: '8px', marginTop: '6px' } }>
                  <select value={ obdTtsVoice } onChange={ e => { setObdTtsVoice( e.target.value ); setObdTtsLang( e.target.value === 'Aditi' ? 'hi-IN' : 'en-IN' ); } } style={ { flex: 1, padding: '6px 10px', border: '1px solid #d1d5db', borderRadius: '6px', fontSize: '12px' } }>
                    <option value="Kajal">Kajal (English-IN, Neural)</option>
                    <option value="Aditi">Aditi (Hindi, Standard)</option>
                  </select>
                </div>
              </div>
            ) }
            { obdAudioSource === 'upload' && (
              <div className="form-group">
                <label>WAV File (16bit 8kHz Mono) *</label>
                <input type="file" accept=".wav,audio/wav" className="file-input" onChange={ e => setObdAudioFile( e.target.files?.[ 0 ] || null ) } />
                { obdAudioFile && <small>{ obdAudioFile.name } ({ ( obdAudioFile.size / 1024 ).toFixed( 1 ) } KB)</small> }
                <div style={ { marginTop: '6px' } }>
                  <label style={ { fontSize: '11px', color: '#6b7280', display: 'flex', alignItems: 'center', gap: '4px' } }>
                    <input type="checkbox" id="saveToLib" defaultChecked style={ { width: '14px', height: '14px', accentColor: '#1a3a2a' } } />
                    Also save to Audio Library for reuse
                  </label>
                </div>
              </div>
            ) }
            <div className="form-group">
              <label>Phone Numbers * <span style={ { fontSize: 10, color: '#6b7280', fontWeight: 400 } }>(10 digits, no country code)</span></label>
              <div className="textarea-with-btn">
                <textarea value={ obdNumbers } onChange={ e => setObdNumbers( e.target.value ) } placeholder="9903300044&#10;8130078559&#10;(one per line or comma-separated)" rows={ 3 } />
                <button type="button" className="fetch-btn" onClick={ () => setShowContactPicker( 'obd' ) }>Contacts</button>
              </div>
              <small>{ obdNumbers.split( /[\n,]/ ).filter( n => n.trim().length >= 10 ).length } valid</small>
            </div>
            { obdVarNames.length > 0 && (
              <div className="form-group">
                <label>Variables</label>
                <div className="var-list">
                  { obdVarNames.map( v => (
                    <span key={ v } className="var-tag">{ v } <button onClick={ () => setObdVarNames( prev => prev.filter( x => x !== v ) ) }>×</button></span>
                  ) ) }
                </div>
                <small>Variables will be mapped from CSV columns</small>
              </div>
            ) }
            <div className="form-group">
              <button type="button" className="fetch-btn var-btn" onClick={ addOBDVariable }>+ Variable</button>
              { showVarInput && (
                <div style={ { display: 'flex', gap: '6px', marginTop: '6px' } }>
                  <input type="text" value={ varInputValue } onChange={ e => setVarInputValue( e.target.value ) } placeholder="e.g. name, amount" style={ { flex: 1, padding: '6px 10px', border: '1px solid #d1d5db', borderRadius: '6px', fontSize: '12px' } } onKeyDown={ e => { if ( e.key === 'Enter' ) confirmAddVariable(); if ( e.key === 'Escape' ) setShowVarInput( false ); } } autoFocus />
                  <button type="button" className="fetch-btn" onClick={ confirmAddVariable }>Add</button>
                  <button type="button" className="fetch-btn" onClick={ () => setShowVarInput( false ) }>×</button>
                </div>
              ) }
            </div>
            <div className="info-box">
              <strong>Outbound campaigns (historical):</strong> Info-Only call flow | Audio: 16bit 8kHz Mono WAV (auto-converted) | TRANSACTIONAL<br />
              <strong>Config:</strong> Caller ID: 8040761117 | App: IRONMAN | Flow: dfbeda76<br />
              <strong>Flow:</strong> Upload CSV → Upload Audio (if TTS/custom) → Create Campaign<br />
              <strong>Audio:</strong> Any WAV/PCM uploaded is auto-validated and converted to 16bit 8kHz mono telephony spec. Download link available.
              { obdAudioSource === 'tts' && <><br /><strong>TTS:</strong> Text-to-speech → WAV → prompt upload (auto)</> }
            </div>
            <div className="modal-actions"><Button variant="secondary" onClick={ () => setShowOBDModal( false ) }>Cancel</Button><Button variant="primary" onClick={ handleOBDCreate } loading={ obdCreating || obdTtsGenerating } disabled={ !obdNumbers || !obdCampaignName || ( obdAudioSource === 'tts' && !obdTtsText.trim() ) || ( obdAudioSource === 'upload' && !obdAudioFile ) || ( obdAudioSource === 'library' && !obdSelectedLibraryFile ) }>{ obdTtsGenerating ? 'Generating...' : 'Create' }</Button></div>
          </div>
        </div>
      ) }

      { showContactPicker && (
        <div className="modal-overlay" onClick={ () => setShowContactPicker( null ) }>
          <div className="modal-content contact-picker" onClick={ e => e.stopPropagation() }>
            <h3>Select Contact</h3>
            <input type="text" placeholder="Search..." value={ contactSearch } onChange={ e => setContactSearch( e.target.value ) } className="contact-search" />
            <div className="contact-list">
              { loadingContacts ? <div className="loading-contacts">Loading...</div> : filteredContacts.length === 0 ? <div className="no-contacts">No contacts</div> : (
                filteredContacts.slice( 0, 50 ).map( contact => (
                  <div key={ contact.contactId } className="contact-row" onClick={ () => selectContact( contact ) }>
                    <div className="contact-avatar">{ contact.name.charAt( 0 ).toUpperCase() }</div>
                    <div className="contact-details"><div className="contact-name">{ contact.name }</div><div className="contact-phone">{ contact.phone }</div></div>
                  </div>
                ) )
              ) }
            </div>
            <div className="modal-actions"><Button variant="secondary" onClick={ () => setShowContactPicker( null ) }>Cancel</Button></div>
          </div>
        </div>
      ) }

      <style jsx>{ `
        .voice-page { height: calc(100vh - 165px); display: flex; flex-direction: column; background: #f9fafb; padding: 16px; box-sizing: border-box; overflow: hidden; }
        .page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 8px; flex-shrink: 0; }
        .header-title { display: flex; align-items: center; gap: 10px; color: #0f2a1d; flex-wrap: wrap; }
        .header-title h2 { margin: 0; font-size: 1.1rem; }
        .badge { background: #1a3a2a; color: #fff; padding: 3px 8px; border-radius: 4px; font-size: 10px; font-weight: 500; }
        .header-actions { display: flex; gap: 6px; flex-wrap: wrap; }
        .tabs-row { background: #fff; border-radius: 8px; padding: 0 12px; margin-bottom: 8px; border: 1px solid #f3f4f6; flex-shrink: 0; overflow-x: auto; }
        .controls-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; gap: 12px; flex-wrap: wrap; flex-shrink: 0; }
        .search-input { padding: 8px 12px; border: 1px solid #e5e7eb; border-radius: 8px; width: 100%; max-width: 280px; font-size: 14px; }
        .search-input:focus { outline: none; border-color: #1a3a2a; }
        .content-area { flex: 1; background: #fff; border-radius: 12px; border: 1px solid #f3f4f6; overflow: auto; min-height: 0; }
        .loading-state { padding: 40px; text-align: center; color: #0f2a1d; }
        .table-container { min-width: 100%; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 10px 12px; text-align: left; border-bottom: 1px solid #f9fafb; font-size: 12px; white-space: nowrap; }
        th { background: #f9fafb; font-weight: 600; color: #0f2a1d; position: sticky; top: 0; z-index: 1; }
        tr:hover { background: #f9fafb; }
        .time-cell { font-size: 11px; }
        .phone-cell { font-family: monospace; color: #0f2a1d; font-size: 11px; }
        .id-cell { font-family: monospace; font-size: 10px; color: #6b7280; }
        .name-cell { font-weight: 500; color: #0f2a1d; max-width: 150px; overflow: hidden; text-overflow: ellipsis; }
        .success-cell { color: #1a3a2a; font-weight: 500; }
        .failed-cell { color: #1a3a2a; font-weight: 500; }
        .status-badge { padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: 500; background: #f5f5f5; color: #6b7280; }
        .status-badge.initiated, .status-badge.completed, .status-badge.success, .status-badge.active { background: #f3f4f6; color: #1a3a2a; }
        .status-badge.failed, .status-badge.error { background: #f9fafb; color: #1a3a2a; }
        .status-badge.pending, .status-badge.in_progress { background: #f9fafb; color: #1a3a2a; }
        .type-badge { padding: 2px 6px; border-radius: 4px; font-size: 10px; background: #f9fafb; color: #1a3a2a; }
        .recording-link { color: #1a3a2a; text-decoration: none; }
        .empty-state { text-align: center; color: #0f2a1d; padding: 30px !important; }
        .webhook-info { padding: 12px; background: #f9fafb; border-top: 1px solid #f3f4f6; font-size: 12px; }
        .webhook-info strong { color: #0f2a1d; }
        .webhook-info code { display: block; background: #fff; padding: 8px; border-radius: 6px; font-size: 11px; color: #0f2a1d; border: 1px solid #f3f4f6; margin-top: 6px; word-break: break-all; white-space: normal; }
        .cdr-detail-row td { border-bottom: 2px solid #e5e7eb; }
        .detail-label { font-weight: 600; color: #374151; margin-right: 4px; }
        .cdr-date-input { padding: 5px 10px; border-radius: 8px; border: 1.5px solid #d1f470; font-size: 12px; color: #1a3a2a; background: #fff; outline: none; font-family: inherit; cursor: pointer; }
        .cdr-date-input:focus { border-color: #1a3a2a; box-shadow: 0 0 0 3px rgba(209,244,112,0.35); }
        .cdr-date-input::-webkit-calendar-picker-indicator { filter: invert(0.2) sepia(1) saturate(3) hue-rotate(100deg); cursor: pointer; }
        .cdr-date-clear { padding: 5px 12px; border-radius: 8px; border: 1.5px solid #d1f470; background: #d1f470; font-size: 11px; cursor: pointer; color: #1a3a2a; font-weight: 500; }
        .cdr-date-clear:hover { background: #c4e85e; }

        .modal-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 1000; padding: 16px; }
        .modal-content { background: #fff; border-radius: 12px; padding: 20px; width: 100%; max-width: 440px; max-height: 90vh; overflow-y: auto; }
        .modal-content.obd-modal { max-width: 480px; }
        .modal-content h3 { margin: 0 0 6px 0; color: #0f2a1d; font-size: 1rem; }
        .modal-desc { margin: 0 0 16px 0; color: #0f2a1d; font-size: 13px; }
        .form-group { margin-bottom: 14px; }
        .form-group label { display: block; font-size: 12px; font-weight: 500; margin-bottom: 5px; color: #374151; }
        .form-group input, .form-group textarea { width: 100%; padding: 8px 10px; border: 1px solid #d1d5db; border-radius: 8px; font-size: 13px; font-family: inherit; box-sizing: border-box; }
        .form-group input:focus, .form-group textarea:focus { outline: none; border-color: #1a3a2a; }
        .form-group small { display: block; margin-top: 3px; font-size: 11px; color: #9ca3af; }
        .file-input { padding: 8px 12px; background: #f9fafb; border: 1.5px dashed #d1f470; border-radius: 8px; font-size: 12px; color: #1a3a2a; cursor: pointer; width: 100%; box-sizing: border-box; }
        .file-input:hover { background: #f0fdf4; border-color: #1a3a2a; }
        .file-input::file-selector-button { background: #1a3a2a; color: #d1f470; border: none; padding: 6px 14px; border-radius: 6px; font-size: 12px; font-weight: 500; cursor: pointer; margin-right: 10px; }
        .file-input::file-selector-button:hover { background: #0f2a1d; }
        .audio-options { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }
        .audio-option { display: flex; align-items: center; gap: 8px; padding: 10px; border: 2px solid #e5e7eb; border-radius: 8px; cursor: pointer; font-size: 12px; }
        .audio-option:hover { border-color: #e5e7eb; background: #f9fafb; }
        .audio-option.selected { border-color: #1a3a2a; background: #f9fafb; }
        .audio-option input[type="radio"] { display: none; }
        .checkbox-group label { display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 13px; }
        .checkbox-group input[type="checkbox"] { width: 16px; height: 16px; accent-color: #1a3a2a; }
        .info-box { background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 10px; margin-bottom: 14px; font-size: 12px; color: #0f2a1d; }
        .info-box strong { color: #0f2a1d; }
        .info-box.warning { background: #f9fafb; border-color: #e5e7eb; color: #0f2a1d; }
        .info-box.warning strong { color: #1a3a2a; }
        .modal-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 16px; }
        .input-with-btn { display: flex; gap: 6px; }
        .input-with-btn input { flex: 1; }
        .textarea-with-btn { display: flex; flex-direction: column; gap: 6px; }
        .fetch-btn { padding: 8px 10px; background: #f9fafb; border: 1px solid #1a3a2a; border-radius: 8px; color: #0f2a1d; font-size: 12px; cursor: pointer; white-space: nowrap; }
        .fetch-btn:hover { background: #f3f4f6; }
        .var-btn { background: #f9fafb; border-color: #1a3a2a; color: #1a3a2a; }
        .var-btn:hover { background: #f3f4f6; }
        .var-list { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 6px; }
        .var-tag { display: inline-flex; align-items: center; gap: 4px; padding: 4px 8px; background: #f9fafb; border-radius: 4px; font-size: 11px; color: #1a3a2a; }
        .var-tag button { background: none; border: none; color: #1a3a2a; cursor: pointer; font-size: 14px; padding: 0; line-height: 1; }
        .audio-library-list { max-height: 180px; overflow-y: auto; border: 1px solid #e5e7eb; border-radius: 8px; }
        .audio-library-item { display: flex; justify-content: space-between; align-items: center; padding: 8px 10px; border-bottom: 1px solid #f3f4f6; cursor: pointer; gap: 8px; }
        .audio-library-item:last-child { border-bottom: none; }
        .audio-library-item:hover { background: #f9fafb; }
        .audio-library-item.selected { background: #f0fdf4; border-left: 3px solid #1a3a2a; }
        .audio-lib-info { display: flex; flex-direction: column; min-width: 0; flex: 1; }
        .audio-lib-name { font-size: 12px; font-weight: 500; color: #0f2a1d; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .audio-lib-meta { font-size: 10px; color: #9ca3af; }
        .audio-lib-actions { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }
        .audio-lib-del { background: none; border: none; color: #ef4444; cursor: pointer; font-size: 16px; padding: 2px 4px; line-height: 1; border-radius: 4px; }
        .audio-lib-del:hover { background: #fef2f2; }
        .audio-lib-dl { text-decoration: none; font-size: 14px; padding: 2px 4px; color: #1a3a2a; border-radius: 4px; }
        .audio-lib-dl:hover { background: #f0fdf4; }
        .audio-compliance { font-weight: 500; margin-left: 4px; }
        .audio-compliance.ok { color: #16a34a; }
        .audio-compliance.warn { color: #d97706; }
        .contact-picker { max-width: 360px; }
        .contact-search { width: 100%; padding: 8px 10px; border: 1px solid #d1d5db; border-radius: 8px; font-size: 13px; margin-bottom: 10px; box-sizing: border-box; }
        .contact-list { max-height: 250px; overflow-y: auto; border: 1px solid #e5e7eb; border-radius: 8px; }
        .contact-row { display: flex; align-items: center; gap: 10px; padding: 8px 10px; cursor: pointer; border-bottom: 1px solid #f3f4f6; }
        .contact-row:hover { background: #f9fafb; }
        .contact-row:last-child { border-bottom: none; }
        .contact-avatar { width: 32px; height: 32px; background: #1a3a2a; color: #fff; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: 500; font-size: 13px; flex-shrink: 0; }
        .contact-details { flex: 1; min-width: 0; }
        .contact-name { font-size: 13px; font-weight: 500; color: #0f2a1d; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .contact-phone { font-size: 11px; color: #6b7280; font-family: monospace; }
        .loading-contacts, .no-contacts { padding: 24px; text-align: center; color: #6b7280; font-size: 13px; }
        
        @media (max-width: 768px) {
          .voice-page { padding: 12px; height: calc(100vh - 96px); }
          .page-header { flex-direction: column; align-items: flex-start; }
          .header-actions { width: 100%; justify-content: flex-start; }
          .controls-row { flex-direction: column; align-items: stretch; }
          .search-input { max-width: 100%; }
          .hide-mobile { display: none; }
          th, td { padding: 8px 6px; font-size: 11px; }
          .phone-cell { font-size: 10px; }
          .modal-content { padding: 16px; max-height: 85vh; }
          .audio-options { grid-template-columns: 1fr 1fr; }
        }
        
        @media (max-width: 480px) {
          .voice-page { padding: 8px; height: calc(100vh - 96px); }
          .header-title h2 { font-size: 1rem; }
          .badge { font-size: 9px; padding: 2px 6px; }
          th, td { padding: 6px 4px; font-size: 10px; }
          .time-cell { max-width: 80px; overflow: hidden; text-overflow: ellipsis; }
          .modal-content { padding: 14px; }
          .audio-options { grid-template-columns: 1fr; }
        }
      `}</style>
    </>
  );

  if ( embedded ) return pageContent;

  return (
    <Layout user={ user } onSignOut={ signOut }>
      <SEO title="Voice-IN | Call Records" description="Call detail records, text-to-speech and audio library" />
      { pageContent }
    </Layout>
  );
};

const PhoneIcon = () => (
  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07 19.5 19.5 0 01-6-6 19.79 19.79 0 01-3.07-8.67A2 2 0 014.11 2h3a2 2 0 012 1.72 12.84 12.84 0 00.7 2.81 2 2 0 01-.45 2.11L8.09 9.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45 12.84 12.84 0 002.81.7A2 2 0 0122 16.92z" />
  </svg>
);

export default VoiceInPage;