/**
 * WhatsApp Campaign Page
 */
import React, { useState, useEffect, useCallback } from 'react';
import Layout from '../../../../components/Layout';
import SEO from '../../../../components/SEO';
import { SkeletonTable } from '../../../../components/Skeleton';
import { useToastContext } from '../../../../contexts/ToastContext';
import * as api from '../../../../api/client';
import { WHATSAPP_PHONES, API_BASE } from '../../../../config/constants';
import Button from '../../../../components/ui/Button';
import Tabs, { TabItem } from '../../../../components/ui/Tabs';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }
type TabType = 'create' | 'logs';
interface Template { name: string; language: string; status: string; category: string; }
interface CampaignLog { id: string; name: string; template: string; recipients: number; sent: number; delivered: number; read: number; failed: number; status: string; createdAt: string; }

const tabItems: TabItem[] = [
  { id: 'create', label: 'Create Campaign' },
  { id: 'logs', label: 'Campaign Logs' },
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
  // MM API conversion metrics. `null` means the read did not land at all (the route is
  // deploy-time work); `available: false` means Meta would not serve the edge, in which
  // case the cached reading with its timestamp is more useful than an empty box.
  const [ mmMetrics, setMmMetrics ] = useState<api.MmConversionMetrics | null>( null );

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

  useEffect( () => {
    let live = true;
    api.getMmConversionMetrics( selectedWaba )
      .then( m => { if ( live ) setMmMetrics( m ); } )
      .catch( () => { if ( live ) setMmMetrics( null ); } );
    return () => { live = false; };
  }, [ selectedWaba ] );

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
              <select value={ selectedWaba } onChange={ e => setSelectedWaba( e.target.value ) }>
                <option value={ WHATSAPP_PHONES.primary.id }>{ WHATSAPP_PHONES.primary.name }</option>
              </select>
            </div>
          </div>

          <div className="info-card" style={ { marginBottom: 16 } }>
            <strong style={ { fontSize: 14 } }>MM API conversion metrics</strong>
            { !mmMetrics && (
              <div style={ { fontSize: 13, color: '#666', marginTop: 6 } }>unavailable</div>
            ) }
            { mmMetrics?.available && (
              <div style={ { fontSize: 13, marginTop: 6 } }>
                { ( mmMetrics.metrics?.length || 0 ) } row{ ( mmMetrics.metrics?.length || 0 ) === 1 ? '' : 's' } via <code>{ mmMetrics.edge }</code>
                { mmMetrics.readAt ? ' · read ' + new Date( mmMetrics.readAt * 1000 ).toLocaleString() : '' }
              </div>
            ) }
            { mmMetrics && !mmMetrics.available && (
              <div style={ { fontSize: 13, marginTop: 6, color: '#666' } }>
                { mmMetrics.cached?.metrics?.length
                  ? <>Last reading: { mmMetrics.cached.metrics.length } row{ mmMetrics.cached.metrics.length === 1 ? '' : 's' }{ mmMetrics.cached.readAt ? ' · ' + new Date( mmMetrics.cached.readAt * 1000 ).toLocaleString() : '' }</>
                  : <>{ mmMetrics.note }</> }
                <div style={ { marginTop: 4, color: '#92400e' } }>
                  Not available for this WABA via <code>{ mmMetrics.edge }</code>{ mmMetrics.reason ? ' — ' + mmMetrics.reason : '' }
                </div>
              </div>
            ) }
          </div>

          <div className="form-group">
            <label>Template * ({ templates.length } approved)</label>
            <select value={ selectedTemplate } onChange={ e => setSelectedTemplate( e.target.value ) }>
              <option value="">Select a template...</option>
              { templates.map( t => (
                <option key={ t.name } value={ t.name }>{ t.name } ({ t.language })</option>
              ) ) }
            </select>
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