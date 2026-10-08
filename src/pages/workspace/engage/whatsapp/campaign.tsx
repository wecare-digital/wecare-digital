/**
 * WhatsApp Campaign Page
 */
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import Layout from '../../../../components/Layout';
import SEO from '../../../../components/SEO';
import { SkeletonTable } from '../../../../components/Skeleton';
import { useToastContext } from '../../../../contexts/ToastContext';
import * as api from '../../../../api/client';
import { WHATSAPP_PHONES, API_BASE } from '../../../../config/constants';
import Button from '../../../../components/ui/Button';
import Select, { type SelectOption } from '../../../../components/ui/Select';
import Tabs, { TabItem } from '../../../../components/ui/Tabs';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }
type TabType = 'create' | 'logs';
interface Template { name: string; language: string; status: string; category: string; }
interface CampaignLog { id: string; name: string; template: string; recipients: number; sent: number; delivered: number; read: number; failed: number; status: string; createdAt: string; }

const tabItems: TabItem[] = [
  { id: 'create', label: 'Create Campaign' },
  { id: 'logs', label: 'Campaign Logs' },
];

/** One account today, exactly as the single `<option>` it replaces. */
const WABA_OPTIONS: SelectOption[] = [
  { value: WHATSAPP_PHONES.primary.id, label: WHATSAPP_PHONES.primary.name },
];

const WhatsAppCampaignPage: React.FC<PageProps> = ( { signOut, user, embedded = false } ) => {
  const [ activeTab, setActiveTab ] = useState<TabType>( 'create' );
  const [ loading, setLoading ] = useState( false );
  const [ sending, setSending ] = useState( false );
  const [ contacts, setContacts ] = useState<api.Contact[]>( [] );
  const [ templates, setTemplates ] = useState<Template[]>( [] );
  const [ campaigns, setCampaigns ] = useState<CampaignLog[]>( [] );
  const toast = useToastContext();
  const [ campaignName, setCampaignName ] = useState( '' );
  const [ selectedTemplate, setSelectedTemplate ] = useState( '' );
  const [ selectedWaba, setSelectedWaba ] = useState( WHATSAPP_PHONES.primary.id );
  const [ selectedContacts, setSelectedContacts ] = useState<string[]>( [] );
  const [ selectAll, setSelectAll ] = useState( false );
  const [ searchQuery, setSearchQuery ] = useState( '' );
  const [ message, setMessage ] = useState<{ type: string; text: string } | null>( null );

  /* Fetched, so memoised on `templates`; the leading '' row is the placeholder. */
  const templateOptions: SelectOption[] = useMemo( () => [
    { value: '', label: 'Select a template...' },
    ...templates.map( t => ( { value: t.name, label: `${ t.name } (${ t.language })` } ) ),
  ], [ templates ] );

  const loadData = useCallback( async () => {
    setLoading( true );
    try
    {
      const contactsData = await api.listContacts();
      setContacts( contactsData.filter( c => c.phone || c.bsuid ) );
      const tpls = await api.listTemplates( selectedWaba );
      setTemplates( ( tpls as any[] ).filter( ( t ) => t.status === 'APPROVED' ) as any );
      const messages = await api.listMessages( undefined, 'WHATSAPP' );
      const campaignMsgs = messages.filter( m => ( m as any ).campaignId );
      const campaignMap = new Map<string, CampaignLog>();
      campaignMsgs.forEach( m => {
        const cid = ( m as any ).campaignId;
        if ( !campaignMap.has( cid ) )
        {
          campaignMap.set( cid, { id: cid, name: ( m as any ).campaignName || cid, template: ( m as any ).templateName || '-', recipients: 0, sent: 0, delivered: 0, read: 0, failed: 0, status: 'completed', createdAt: m.timestamp } );
        }
        const c = campaignMap.get( cid )!;
        c.recipients++;
        if ( m.status === 'sent' || m.status === 'delivered' || m.status === 'read' ) c.sent++;
        if ( m.status === 'delivered' || m.status === 'read' ) c.delivered++;
        if ( m.status === 'read' ) c.read++;
        if ( m.status === 'failed' ) c.failed++;
      } );
      setCampaigns( Array.from( campaignMap.values() ).sort( ( a, b ) => new Date( b.createdAt ).getTime() - new Date( a.createdAt ).getTime() ) );
    } catch ( err )
    {
      console.error( 'Load error:', err );
      toast.error( 'Failed to load campaign data' );
    } finally
    {
      setLoading( false );
    }
  }, [ selectedWaba, toast ] );

  useEffect( () => { loadData(); }, [ loadData ] );

  const filteredContacts = contacts.filter( c => c.name?.toLowerCase().includes( searchQuery.toLowerCase() ) || c.phone?.includes( searchQuery ) || c.bsuid?.includes( searchQuery ) || c.username?.toLowerCase().includes( searchQuery.toLowerCase() ) );

  const handleSelectAll = () => {
    if ( selectAll ) { setSelectedContacts( [] ); }
    else { setSelectedContacts( filteredContacts.map( c => c.contactId ) ); }
    setSelectAll( !selectAll );
  };

  const toggleContact = ( id: string ) => {
    setSelectedContacts( prev => prev.includes( id ) ? prev.filter( c => c !== id ) : [ ...prev, id ] );
  };

  const handleSendCampaign = async () => {
    if ( !campaignName.trim() ) { setMessage( { type: 'error', text: 'Campaign name required' } ); return; }
    if ( !selectedTemplate ) { setMessage( { type: 'error', text: 'Select a template' } ); return; }
    if ( selectedContacts.length === 0 ) { setMessage( { type: 'error', text: 'Select at least one contact' } ); return; }
    setSending( true );
    setMessage( null );
    try
    {
      const campaignId = 'WC' + Date.now();
      const template = templates.find( t => t.name === selectedTemplate );
      let sent = 0, failed = 0;
      for ( const contactId of selectedContacts )
      {
        const contact = contacts.find( c => c.contactId === contactId );
        if ( !contact?.phone && !contact?.bsuid ) { failed++; continue; }
        try
        {
          const result = await api.sendWhatsAppTemplateMessage( {
            contactId,
            templateName: selectedTemplate,
            language: template?.language || 'en',
            phoneNumberId: selectedWaba,
            recipientBsuid: contact.bsuid || undefined,
            campaignId,
            campaignName,
          } );
          if ( result ) sent++; else failed++;
        } catch ( e ) { failed++; }
        if ( sent % 10 === 0 ) await new Promise( r => setTimeout( r, 200 ) );
      }
      setMessage( { type: sent > 0 ? 'success' : 'error', text: 'Campaign sent: ' + sent + ' success, ' + failed + ' failed' } );
      setCampaignName( '' );
      setSelectedTemplate( '' );
      setSelectedContacts( [] );
      setSelectAll( false );
      loadData();
    } catch ( err: any ) { setMessage( { type: 'error', text: err.message || 'Campaign failed' } ); }
    finally { setSending( false ); }
  };

  const content = (
    <div className="inner-page campaign-page">
      <div className="page-header">
        <h2>WhatsApp Campaign</h2>
        <Button variant="secondary" icon="refresh" onClick={ loadData } disabled={ loading } loading={ loading }>Refresh</Button>
      </div>

      <Tabs
        items={ tabItems.map( t => ( { ...t, count: t.id === 'logs' ? campaigns.length : undefined } ) ) }
        activeTab={ activeTab }
        onChange={ ( id ) => setActiveTab( id as TabType ) }
        variant="sub"
      />

      { message && (
        <div className={ 'alert alert-' + message.type }>
          { message.text }
          <button onClick={ () => setMessage( null ) }>x</button>
        </div>
      ) }

      { activeTab === 'create' && (
        <div className="form-section">
          <div className="form-row">
            <div className="form-group">
              <label>Campaign Name *</label>
              <input type="text" value={ campaignName } onChange={ e => setCampaignName( e.target.value ) } placeholder="My WhatsApp Campaign" />
            </div>
            <div className="form-group">
              <label>WABA Account</label>
              <Select ariaLabel="WABA Account" value={ selectedWaba }
                onChange={ v => setSelectedWaba( v ) } options={ WABA_OPTIONS } />
            </div>
          </div>

          <div className="form-group">
            <label>Template * ({ templates.length } approved)</label>
            <Select ariaLabel="Template" value={ selectedTemplate }
              onChange={ v => setSelectedTemplate( v ) } options={ templateOptions } />
          </div>

          <div className="contacts-section">
            <div className="contacts-header">
              <h3>Select Recipients ({ selectedContacts.length } / { filteredContacts.length })</h3>
              <div className="contacts-actions">
                <input type="text" placeholder="Search..." value={ searchQuery } onChange={ e => setSearchQuery( e.target.value ) } />
                <button onClick={ handleSelectAll }>{ selectAll ? 'Deselect All' : 'Select All' }</button>
              </div>
            </div>
            <div className="contacts-grid">
              { filteredContacts.slice( 0, 100 ).map( c => (
                <label key={ c.contactId } className={ 'contact-item' + ( selectedContacts.includes( c.contactId ) ? ' selected' : '' ) }>
                  <input type="checkbox" checked={ selectedContacts.includes( c.contactId ) } onChange={ () => toggleContact( c.contactId ) } />
                  <span className="contact-name">{ c.name || c.phone || c.username || c.bsuid }</span>
                  <span className="contact-phone">{ c.phone || ( c.bsuid ? '🆔 ' + c.bsuid.slice( 0, 16 ) + '...' : '-' ) }</span>
                  { c.username && <span className="contact-username" style={ { fontSize: '0.75rem', color: '#888' } }>@{ c.username }</span> }
                </label>
              ) ) }
              { filteredContacts.length === 0 && <div className="empty-state">No contacts found</div> }
            </div>
          </div>

          <Button variant="primary" className="btn-block" onClick={ handleSendCampaign } disabled={ sending || selectedContacts.length === 0 || !selectedTemplate } loading={ sending }>
            { sending ? 'Sending...' : 'Send Campaign to ' + selectedContacts.length + ' Contacts' }
          </Button>
        </div>
      ) }

      { activeTab === 'logs' && (
        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th>Campaign</th>
                <th>Template</th>
                <th>Recipients</th>
                <th>Sent</th>
                <th>Delivered</th>
                <th>Read</th>
                <th>Failed</th>
                <th>Date</th>
              </tr>
            </thead>
            <tbody>
              { campaigns.map( c => (
                <tr key={ c.id }>
                  <td><strong>{ c.name }</strong></td>
                  <td>{ c.template }</td>
                  <td>{ c.recipients }</td>
                  <td className="text-success">{ c.sent }</td>
                  <td>{ c.delivered }</td>
                  <td>{ c.read }</td>
                  <td className="text-error">{ c.failed }</td>
                  <td>{ new Date( c.createdAt ).toLocaleDateString() }</td>
                </tr>
              ) ) }
              { campaigns.length === 0 && (
                <tr><td colSpan={ 8 } className="empty-state">No campaigns yet</td></tr>
              ) }
            </tbody>
          </table>
        </div>
      ) }
    </div>
  );

  if ( embedded ) return content;

  return (
    <Layout user={ user } onSignOut={ signOut }>
      <SEO title="WhatsApp Campaign" description="Send bulk WhatsApp campaigns" />
      { content }
    </Layout>
  );
};

export default WhatsAppCampaignPage;