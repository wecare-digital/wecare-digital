/**
 * WhatsApp Webhooks Management
 * View and manage webhook subscriptions per WABA
 * Ref: https://developers.facebook.com/docs/whatsapp/webhooks/overview
 */
import React, { useState, useEffect } from 'react';
import Layout from '../../../../components/Layout';
import SEO from '../../../../components/SEO';
import { useToastContext } from '../../../../contexts/ToastContext';
import * as api from '../../../../api/client';
import { WHATSAPP_PHONES } from '../../../../config/constants';
import { RawJsonDrawer, LastSyncIndicator, StatusBadge, useConfirmDanger } from '../../../../components/wa';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const WABAS = [
  { id: WHATSAPP_PHONES.primary.wabaId, name: WHATSAPP_PHONES.primary.name, display: WHATSAPP_PHONES.primary.display },
  { id: WHATSAPP_PHONES.secondary.wabaId, name: WHATSAPP_PHONES.secondary.name, display: WHATSAPP_PHONES.secondary.display },
];

const WEBHOOK_FIELDS = [
  { field: 'messages', desc: 'Incoming messages, message status updates, message errors' },
  { field: 'account_update', desc: 'Phone number name, quality rating, messaging limit changes' },
  { field: 'account_review_update', desc: 'Business verification status changes' },
  { field: 'business_capability_update', desc: 'Changes to business capabilities' },
  { field: 'message_template_status_update', desc: 'Template approval/rejection notifications' },
  { field: 'phone_number_name_update', desc: 'Display name change status' },
  { field: 'phone_number_quality_update', desc: 'Phone number quality rating changes' },
  { field: 'security', desc: 'Security-related events (two-step verification)' },
  { field: 'template_category_update', desc: 'Template category change notifications' },
  { field: 'flows', desc: 'Flow status changes and data exchange events' },
  { field: 'calls', desc: 'WhatsApp Business Calling events (connect, terminate, permission)' },
  { field: 'business_username_updates', desc: 'Business username status changes (reserved → approved/deleted) — 2026 usernames rollout' },
  { field: 'user_id_update', desc: 'Business-scoped User ID (BSUID) changes for a user — subscribe to track identity continuity' },
  { field: 'message_echoes', desc: 'Echoes of messages sent by the business (required for Meta Business Agent)' },
  { field: 'messaging_handovers', desc: 'Conversation handoff between Meta Business Agent and human agents (required for MBA)' },
  // Coexistence and Multi-Partner Solutions. Listed so an operator CAN subscribe —
  // nothing in code, in a script or as a side effect subscribes for them. This
  // deployment is not a coexistence deployment and not a multi-partner solution, so if
  // subscribed these three are audited and counted only; no inbox row, no send.
  { field: 'smb_app_state_sync', desc: 'Coexistence: contact/chat state sync from the WhatsApp Business app — audited only, not ingested' },
  { field: 'smb_message_echoes', desc: 'Coexistence: echoes of messages the owner sent from the WhatsApp Business app — audited only, never written to the inbox' },
  { field: 'partner_solutions', desc: 'Multi-Partner Solutions: solution/partner association changes — audit only' },
];

const EXISTING_WEBHOOKS = [
  { name: 'Inbound Messages', url: 'https://wecare.digital/api/whatsapp-inbound', fields: [ 'messages' ], lambda: 'wecare-inbound-whatsapp-handler', status: 'active', verification: 'Server-side' },
  { name: 'WhatsApp Unified (Calls + Messages)', url: 'https://wecare.digital/api/whatsapp', fields: [ 'messages', 'calls' ], lambda: 'wecare-whatsapp-calling', status: 'active', verification: 'Server-side' },
  { name: 'Voice CDR Webhook', url: 'https://wecare.digital/api/voice-cdr-webhook', fields: [ 'CDR', 'ALL' ], lambda: 'wecare-voice-cdr-webhook', status: 'active', verification: 'Server-side' },
  { name: 'Voice C2C', url: 'https://wecare.digital/api/voice-in/c2c', fields: [ 'CDR' ], lambda: 'wecare-voice-in-c2c', status: 'active', verification: 'Server-side' },
  { name: 'Voice OBD', url: 'https://wecare.digital/api/voice-in/obd', fields: [ 'CDR' ], lambda: 'wecare-voice-in-obd', status: 'active', verification: 'Server-side' },
  // The "SMS Airtel" row was removed on 2026-09-23. It listed
  // lambda 'wecare-sms-in-airtel' with status 'active', and neither the function nor
  // the route /sms-in/airtel exists: measured against the account, there are zero
  // retired-provider functions and zero retired-provider routes. Airtel is prohibited
  // outright. A webhook inventory that reports a deleted endpoint as active is worse
  // than an incomplete one, because someone will go looking for why it stopped
  // delivering.
  { name: 'Wix Store', url: 'https://wecare.digital/api/wix-store/*', fields: [ 'orders', 'products', 'inventory', 'collections' ], lambda: 'wecare-wix-store', status: 'active', verification: 'Server-side' },
];

const META_WEBHOOK_CONFIG = {
  callbackUrl: 'https://wecare.digital/api/whatsapp',
  waba1: { appId: '2238810740192680', appName: 'WECARE.DIGITAL', business: 'Wecare.Digital' },
  waba2: { appId: '1224334845952721', appName: 'Manish Agarwal', business: 'Manish Agarwal' },
  tokenType: 'System User Token',
};

const WebhooksPage: React.FC<PageProps> = ( { signOut, user, embedded = false } ) => {
  const toast = useToastContext();
  const confirmDanger = useConfirmDanger();
  const [ selectedWaba, setSelectedWaba ] = useState( WABAS[ 0 ] );
  const [ subscriptions, setSubscriptions ] = useState<any[]>( [] );
  const [ loading, setLoading ] = useState( false );
  const [ subscribing, setSubscribing ] = useState( false );
  const [ lastSync, setLastSync ] = useState<number | undefined>( undefined );

  const loadSubs = async ( waba: typeof WABAS[ 0 ] ) => {
    setLoading( true );
    try
    {
      const data = await api.getWebhookSubscriptions( waba.id );
      setSubscriptions( data );
      setLastSync( Math.floor( Date.now() / 1000 ) );
    } catch ( e ) { toast.error( 'Failed to load subscriptions' ); }
    setLoading( false );
  };

  useEffect( () => { loadSubs( selectedWaba ); }, [ selectedWaba ] );

  const handleSubscribe = async () => {
    setSubscribing( true );
    const ok = await api.subscribeWebhook( selectedWaba.id );
    if ( ok ) { toast.success( 'Subscribed' ); loadSubs( selectedWaba ); }
    else toast.error( 'Subscribe failed' );
    setSubscribing( false );
  };

  const handleUnsubscribe = async () => {
    if ( !( await confirmDanger( 'unsubscribe', `Unsubscribe this app from webhooks for WABA ${selectedWaba.id}? Inbound events stop until you re-subscribe.` ) ) ) return;
    setSubscribing( true );
    const ok = await api.unsubscribeWebhook( selectedWaba.id );
    if ( ok ) { toast.success( 'Unsubscribed' ); loadSubs( selectedWaba ); }
    else toast.error( 'Unsubscribe failed' );
    setSubscribing( false );
  };

  const content = (
    <>
      <SEO title="Webhooks" description="WhatsApp Webhook Management" noindex />
      <div className="inner-page-container" style={ { background: '#fff' } }>
        <h2 style={ { margin: '0 0 16px', fontSize: 20 } }>WhatsApp Webhooks</h2>

        <div style={ { display: 'flex', gap: 8, marginBottom: 20 } }>
          { WABAS.map( w => (
            <button key={ w.id } onClick={ () => setSelectedWaba( w ) }
              style={ { padding: '8px 16px', borderRadius: 6, border: selectedWaba.id === w.id ? '2px solid #1a3a2a' : '1px solid #ddd', background: selectedWaba.id === w.id ? '#f9fafb' : '#fff', cursor: 'pointer', fontSize: 13 } }>
              { w.name } ({ w.display })
            </button>
          ) ) }
        </div>

        {/* Meta Webhook Configuration */ }
        <div style={ { marginBottom: 24, background: '#f0f9ff', border: '1px solid #bae6fd', borderRadius: 8, padding: 16 } }>
          <h3 style={ { fontSize: 16, marginBottom: 12, color: '#0369a1' } }>Meta App Webhook Configuration</h3>
          <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, fontSize: 13 } }>
            <div><span style={ { color: '#666', fontWeight: 500 } }>Callback URL:</span><br /><code style={ { fontSize: 12, background: '#e0f2fe', padding: '2px 6px', borderRadius: 4 } }>{ META_WEBHOOK_CONFIG.callbackUrl }</code></div>
            <div><span style={ { color: '#666', fontWeight: 500 } }>Verify Token:</span><br /><span>Configured server-side</span></div>
            <div><span style={ { color: '#666', fontWeight: 500 } }>WABA1 App:</span> { META_WEBHOOK_CONFIG.waba1.appId } ({ META_WEBHOOK_CONFIG.waba1.appName })</div>
            <div><span style={ { color: '#666', fontWeight: 500 } }>WABA2 App:</span> { META_WEBHOOK_CONFIG.waba2.appId } ({ META_WEBHOOK_CONFIG.waba2.appName })</div>
          </div>
          <p style={ { fontSize: 12, color: '#666', marginTop: 8, marginBottom: 0 } }>
            Configure in Meta App Dashboard → WhatsApp → Configuration → Callback URL
          </p>
        </div>

        {/* Active Webhook Endpoints */ }
        <div style={ { marginBottom: 24 } }>
          <h3 style={ { fontSize: 16, marginBottom: 12 } }>Active Webhook Endpoints</h3>
          <div style={ { display: 'grid', gap: 10 } }>
            { EXISTING_WEBHOOKS.map( wh => (
              <div key={ wh.name } style={ { background: '#f9fafb', border: '1px solid #e5e7eb', borderRadius: 8, padding: 14 } }>
                <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center' } }>
                  <span style={ { fontWeight: 600, fontSize: 14 } }>{ wh.name }</span>
                  <span style={ { padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 600, color: '#fff', background: '#1a3a2a' } }>{ wh.status }</span>
                </div>
                <div style={ { fontSize: 12, color: '#666', marginTop: 4 } }>URL: { wh.url }</div>
                <div style={ { fontSize: 12, color: '#666' } }>Lambda: { wh.lambda } | Verification: { wh.verification }</div>
                <div style={ { fontSize: 12, color: '#666' } }>Fields: { wh.fields.join( ', ' ) }</div>
              </div>
            ) ) }
          </div>
        </div>

        {/* App Subscriptions */ }
        <div style={ { marginBottom: 24 } }>
          <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 } }>
            <h3 style={ { fontSize: 16, margin: 0 } }>App Subscriptions (WABA: { selectedWaba.id })</h3>
            <div style={ { display: 'flex', gap: 8, alignItems: 'center' } }>
              <LastSyncIndicator at={ lastSync } onSync={ () => loadSubs( selectedWaba ) } syncing={ loading } />
              <button onClick={ handleSubscribe } disabled={ subscribing } style={ { padding: '6px 14px', background: '#d1f470', color: '#1a3a2a', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 12 } }>
                { subscribing ? '...' : 'Subscribe App' }
              </button>
              <button onClick={ handleUnsubscribe } disabled={ subscribing } style={ { padding: '6px 14px', background: '#fff', color: '#1a3a2a', border: '1px solid #1a3a2a', borderRadius: 6, cursor: 'pointer', fontSize: 12 } }>
                Unsubscribe
              </button>
            </div>
          </div>
          { loading ? <p>Loading...</p> : subscriptions.length === 0 ? (
            <p style={ { color: '#666', fontSize: 13 } }>No subscriptions found. Click &quot;Subscribe App&quot; to subscribe.</p>
          ) : (
            <div style={ { display: 'grid', gap: 8 } }>
              { subscriptions.map( ( sub: any, i: number ) => (
                <div key={ i } style={ { background: '#fff', border: '1px solid #e5e7eb', borderRadius: 6, padding: 12, fontSize: 13 } }>
                  <div style={ { display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' } }>
                    <strong>{ sub.name || sub.whatsapp_business_api_data?.name || `App ${i + 1}` }</strong>
                    <StatusBadge status="ACTIVE" />
                  </div>
                  <RawJsonDrawer data={ sub } label="Subscription JSON" />
                </div>
              ) ) }
            </div>
          ) }
        </div>

        {/* Available Webhook Fields Reference */ }
        <div>
          <h3 style={ { fontSize: 16, marginBottom: 12 } }>Available Webhook Fields</h3>
          <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: 13 } }>
            <thead>
              <tr style={ { background: '#f9fafb' } }>
                <th style={ { padding: '8px 12px', textAlign: 'left', borderBottom: '1px solid #e5e7eb' } }>Field</th>
                <th style={ { padding: '8px 12px', textAlign: 'left', borderBottom: '1px solid #e5e7eb' } }>Description</th>
              </tr>
            </thead>
            <tbody>
              { WEBHOOK_FIELDS.map( f => (
                <tr key={ f.field }>
                  <td style={ { padding: '8px 12px', borderBottom: '1px solid #f3f4f6', fontFamily: 'monospace', fontWeight: 500 } }>{ f.field }</td>
                  <td style={ { padding: '8px 12px', borderBottom: '1px solid #f3f4f6', color: '#666' } }>{ f.desc }</td>
                </tr>
              ) ) }
            </tbody>
          </table>
        </div>
      </div>
    </>
  );

  if ( embedded ) return content;

  return (
    <Layout user={ user } onSignOut={ signOut }>
      { content }
    </Layout>
  );
};

export default WebhooksPage;
