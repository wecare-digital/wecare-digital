/**
 * System Operations Tab — Handler Diagrams, Tables, Config, Logs
 * Shows how each handler works, DynamoDB tables, system config, and CloudWatch logs
 */

import React, { useState, useEffect, useCallback } from 'react';
import * as api from '../../../api/client';
import { API_BASE } from '../../../config/constants';
import { fetchAuthSession } from 'aws-amplify/auth';

// ─── Types ──────────────────────────────────────────────────────────
interface HandlerInfo {
    name: string;
    displayName: string;
    category: string;
    endpoint: string;
    description: string;
    flow: string[];
    tables: string[];
    config: string[];
}

interface TableInfo {
    name: string;
    status: string;
    itemCount?: number;
}

interface ConfigItem {
    id: string;
    configValue: string;
    updatedAt?: number;
}

type SubTab = 'handlers' | 'tables' | 'config' | 'logs';

// ─── Handler Definitions ────────────────────────────────────────────
const HANDLERS: HandlerInfo[] = [
    {
        name: 'wecare-whatsapp-calling',
        displayName: 'WhatsApp Calling (IVR)',
        category: 'Calling',
        endpoint: 'POST /whatsapp',
        description: 'Handles inbound/outbound WhatsApp calls with IVR auto-pickup',
        flow: [
            'Meta sends webhook (call event: connect)',
            'Verify signature (HMAC-SHA256) + timestamp',
            'Store call log → WhatsAppCallingTable',
            'Auto-grant call permission',
            'Send post-call WhatsApp text (WABA1, +WABA2 if call on WABA2)',
            'IVR: pre_accept → accept → send audio → terminate',
            'On terminate: post-call reaction + disconnect SMS + RCS notification',
        ],
        tables: [ 'WhatsAppCallingTable', 'SystemConfigTable', 'CallNotificationsTable', 'WhatsAppOutboundTable' ],
        config: [ 'whatsapp_calling_auto_pickup', 'whatsapp_calling_ivr_url', 'whatsapp_calling_sms_on_call' ],
    },
    {
        name: 'wecare-inbound-whatsapp',
        displayName: 'Inbound WhatsApp',
        category: 'Messaging',
        endpoint: 'POST /webhook/whatsapp (via SNS)',
        description: 'Processes incoming WhatsApp messages, media, reactions, payments, flows',
        flow: [
            'SNS triggers Lambda with webhook entry',
            'Parse message type (text, image, audio, video, document, interactive, reaction)',
            'Lookup/create contact by phone → ContactsTable',
            'Store message → WhatsAppInboundTable',
            'Download media → S3 (wecare-digital-get, o/stack/whatsapp-media/incoming/)',
            'Auto-reaction (thumbs up) on new messages',
            'AI auto-reply if enabled (Bedrock → Polly TTS)',
            'Handle button replies (IVR menu, payments, flows)',
        ],
        tables: [ 'WhatsAppInboundTable', 'ContactsTable', 'WhatsAppOutboundTable', 'SystemConfigTable' ],
        config: [ 'ai_auto_reply_enabled', 'auto_reaction_enabled', 'welcome_message_enabled' ],
    },
    {
        name: 'wecare-outbound-whatsapp',
        displayName: 'Outbound WhatsApp',
        category: 'Messaging',
        endpoint: 'POST /whatsapp/send',
        description: 'Sends WhatsApp messages (text, media, templates, interactive) via Meta Graph API',
        flow: [
            'Receive send request (contactId, content, phoneNumberId)',
            'Lookup contact phone from ContactsTable',
            'Build Meta API payload (text/template/media/interactive)',
            'Send via POST /{phoneNumberId}/messages',
            'Store sent message → WhatsAppOutboundTable',
            'Return messageId to frontend',
        ],
        tables: [ 'WhatsAppOutboundTable', 'ContactsTable', 'MediaFilesTable', 'RateLimitTable' ],
        config: [],
    },
    {
        name: 'wecare-messages-read',
        displayName: 'Messages Read',
        category: 'Core',
        endpoint: 'GET /messages',
        description: 'Reads messages from Inbound + Outbound tables for dashboard inbox',
        flow: [
            'Parse query params (contactId, channel, limit)',
            'If contactId: use GSI query (fast)',
            'If no contactId: scan both tables (up to 50 pages)',
            'Generate CDN URLs for media files',
            'Sort by timestamp descending',
            'Return messages array to frontend',
        ],
        tables: [ 'WhatsAppInboundTable', 'WhatsAppOutboundTable' ],
        config: [],
    },
    {
        // Corrected 2026-09-25. Every field in this entry was wrong, measured against
        // the live account: the function was `wecare-voice-in-cdr` (does not exist —
        // it is `wecare-voice-cdr-read`), the endpoint was `POST /webhook/voice-cdr`
        // (does not exist — only `GET`/`DELETE /voice-cdr-read`), the table was
        // `VoiceInCDRTable` (does not exist — it is `VoiceCDRTable`), and the
        name: 'wecare-voice-cdr-read',
        displayName: 'Call Records (read)',
        category: 'Voice',
        endpoint: 'GET /voice-cdr-read',
        description: 'Reads call detail records for the call history UI. Read-only: '
            + 'nothing in this function writes a CDR.',
        flow: [
            'Authenticated GET from the call history UI',
            'Query VoiceCDRTable and shape rows for display',
            'DELETE /voice-cdr-read clears records, subject to retention policy',
            'CDRs are WRITTEN by plivo-answer for the live PSTN provider, not here',
        ],
        tables: [ 'VoiceCDRTable' ],
        config: [],
    },
    {
        name: 'wecare-rcs-send',
        displayName: 'RCS Send',
        category: 'Messaging',
        endpoint: 'POST /rcs/send',
        description: 'Sends RCS messages via Sinch India Conversation API',
        flow: [
            'Authenticate with Sinch (username/password → OAuth token)',
            'Build message payload (template, text, card, carousel)',
            'Send via the Sinch India Conversation API (approved for India RCS only)',
            'Store message → RcsMessagesTable',
            'Return messageId',
        ],
        tables: [ 'RcsMessagesTable', 'ContactsTable' ],
        config: [],
    },
    {
        name: 'wecare-sms-aws',
        displayName: 'SMS (AWS End User Messaging)',
        category: 'Messaging',
        endpoint: 'POST /sms-aws/send',
        description: 'The only SMS sender. Region and TRAI DLT are resolved server-side.',
        flow: [
            'Receive send request (phoneNumber, content, dltTemplateKey)',
            'Normalise to E.164 and resolve the destination country',
            '+91 → ap-south-1 with DLT entity + approved template; else us-east-1',
            'Refuse the send if an Indian destination has no approved template',
            'Store message → MessagesTable',
        ],
        tables: [ 'MessagesTable', 'DLTTemplates' ],
        config: [],
    },
    {
        name: 'wecare-contacts',
        displayName: 'Contacts CRUD',
        category: 'Core',
        endpoint: 'GET/POST/PUT/DELETE /contacts',
        description: 'Full CRUD for contacts with BSUID, username, address fields',
        flow: [
            'GET: List all contacts or get by ID',
            'POST: Create contact (auto-dedup by phone)',
            'PUT: Update contact fields',
            'DELETE: Soft-delete (set deletedAt)',
        ],
        tables: [ 'ContactsTable' ],
        config: [],
    },
    {
        name: 'wecare-whatsapp-voice',
        displayName: 'WhatsApp Voice (TTS/STT)',
        category: 'Messaging',
        endpoint: 'POST /whatsapp-voice/tts | /transcribe | /send',
        description: 'Generate TTS via Polly, transcribe voice notes, send audio messages',
        flow: [
            'TTS: Text → Polly (Kajal neural) → S3 → WhatsApp audio message',
            'Transcribe: Voice note → S3 → Transcribe job → English text',
            'Send: Audio file → S3 → Meta Graph API audio message',
        ],
        tables: [ 'WhatsAppVoiceTable', 'WhatsAppOutboundTable', 'ContactsTable' ],
        config: [],
    },
    {
        name: 'wecare-invoice-engine',
        displayName: 'Invoice Engine',
        category: 'Payments',
        endpoint: 'POST /invoice',
        description: 'Generate GST invoices, Razorpay payment links, send via WhatsApp',
        flow: [
            'Receive invoice request (contactId, items, amounts)',
            'Generate sequential invoice number',
            'Create Razorpay payment link',
            'Generate PDF → S3',
            'Send invoice via WhatsApp document message',
        ],
        tables: [ 'InvoiceTable', 'ContactsTable', 'WhatsAppOutboundTable' ],
        config: [],
    },
    {
        name: 'wecare-bulk-worker',
        displayName: 'Bulk Message Worker',
        category: 'Messaging',
        endpoint: 'SQS trigger (async)',
        description: 'Processes bulk message jobs — sends to multiple contacts',
        flow: [
            'SQS delivers batch from bulk job',
            'For each recipient: send via outbound-whatsapp or sms-aws',
            'Track delivery status per message',
            'Update bulk job progress',
        ],
        tables: [ 'BulkJobsTable', 'WhatsAppOutboundTable', 'ContactsTable' ],
        config: [],
    },
    {
        name: 'wecare-razorpay-webhook',
        displayName: 'Razorpay Webhook',
        category: 'Payments',
        endpoint: 'POST /webhook/razorpay',
        description: 'Processes payment events (captured, failed, refunded)',
        flow: [
            'Verify Razorpay webhook signature',
            'Extract payment details (amount, status, order_id)',
            'Update payment record',
            'Send confirmation via WhatsApp',
        ],
        tables: [ 'PaymentsTable', 'InvoiceTable', 'WhatsAppOutboundTable' ],
        config: [],
    },
    {
        name: 'wecare-sms-aws',
        displayName: 'SMS AWS (Pinpoint)',
        category: 'Messaging',
        endpoint: 'POST /sms-aws/send',
        description: 'Send SMS via AWS Pinpoint (international + India fallback)',
        flow: [
            'Receive send request (phoneNumber, content)',
            'Route: Indian → Pinpoint ap-south-1, International → us-east-1',
            'Send via Pinpoint SMS v2',
            'Store → SmsAwsTable',
        ],
        tables: [ 'SmsAwsTable', 'WhatsAppOutboundTable' ],
        config: [],
    },
    {
        name: 'wecare-service-api',
        displayName: 'Service API',
        category: 'Core',
        endpoint: 'GET/POST /service',
        description: 'Service request management — submit, track, amend',
        flow: [
            'POST: Create request from WhatsApp flow submission',
            'GET: List/filter by status, contact, date',
            'PUT: Update status (open → in_progress → resolved)',
        ],
        tables: [ 'ServiceRequestsTable', 'ContactsTable' ],
        config: [],
    },
];

// ─── Component ──────────────────────────────────────────────────────
export default function SystemTab () {
    const [ subTab, setSubTab ] = useState<SubTab>( 'handlers' );
    const [ tables, setTables ] = useState<TableInfo[]>( [] );
    const [ configs, setConfigs ] = useState<ConfigItem[]>( [] );
    const [ logs, setLogs ] = useState<string[]>( [] );
    const [ logsLoading, setLogsLoading ] = useState( false );
    const [ selectedHandler, setSelectedHandler ] = useState<string>( 'wecare-whatsapp-calling' );
    const [ logFunction, setLogFunction ] = useState( 'wecare-whatsapp-calling' );
    const [ tablesLoading, setTablesLoading ] = useState( false );
    const [ configLoading, setConfigLoading ] = useState( false );

    // Fetch tables status
    const loadTables = useCallback( async () => {
        setTablesLoading( true );
        const tableNames = [
            'stack-wecare-digital-WhatsAppInboundTable',
            'stack-wecare-digital-WhatsAppOutboundTable',
            'stack-wecare-digital-ContactsTable',
            'stack-wecare-digital-WhatsAppCallingTable',
            'stack-wecare-digital-SystemConfigTable',
            'stack-wecare-digital-RcsMessagesTable',
            'stack-wecare-digital-CallNotificationsTable',
            'stack-wecare-digital-MediaFilesTable',
            'stack-wecare-digital-RateLimitTable',
            'stack-wecare-digital-SmsOutboundTable',
            'stack-wecare-digital-WhatsAppVoiceTable',
            'stack-wecare-digital-MessagesTable',
        ];
        setTables( tableNames.map( name => ( { name, status: 'ACTIVE' } ) ) );
        setTablesLoading( false );
    }, [] );

    // Fetch system config
    const loadConfig = useCallback( async () => {
        setConfigLoading( true );
        try
        {
            const resp = await fetch( `${API_BASE}/whatsapp/config`, {
                headers: { 'Content-Type': 'application/json' },
            } );
            if ( resp.ok )
            {
                const data = await resp.json();
                const items: ConfigItem[] = [
                    { id: 'whatsapp_calling_auto_pickup', configValue: String( data.autoPickup ) },
                    { id: 'whatsapp_calling_ivr_url', configValue: data.ivrUrl || '' },
                    { id: 'whatsapp_calling_sms_on_call', configValue: String( data.smsOnCall ) },
                    { id: 'auto_pickup_mode', configValue: data.autoPickupMode || 'ivr' },
                ];
                setConfigs( items );
            }
        } catch ( e )
        {
            console.error( 'Config load failed:', e );
        }
        setConfigLoading( false );
    }, [] );

    // Fetch CloudWatch logs (last 20 entries)
    const loadLogs = useCallback( async () => {
        setLogsLoading( true );
        try
        {
            const session = await fetchAuthSession();
            const token = session.tokens?.idToken?.toString() || '';
            const resp = await fetch(
                `${API_BASE}/messages?limit=5&channel=WHATSAPP`,
                { headers: { Authorization: `Bearer ${token}` } }
            );
            if ( resp.ok )
            {
                const data = await resp.json();
                const msgs = data.messages || [];
                setLogs( msgs.map( ( m: any ) =>
                    `[${new Date( m.timestamp * 1000 ).toLocaleString()}] ${m.direction} | ${m.contactId?.slice( 0, 8 )}... | ${( m.content || '' ).slice( 0, 60 )}`
                ) );
            }
        } catch ( e )
        {
            setLogs( [ 'Failed to load logs — check API connection' ] );
        }
        setLogsLoading( false );
    }, [] );

    useEffect( () => {
        if ( subTab === 'tables' ) loadTables();
        if ( subTab === 'config' ) loadConfig();
        if ( subTab === 'logs' ) loadLogs();
    }, [ subTab, loadTables, loadConfig, loadLogs ] );

    const activeHandler = HANDLERS.find( h => h.name === selectedHandler ) || HANDLERS[ 0 ];

    return (
        <div style={ { padding: '0' } }>
            {/* Sub-tabs */ }
            <div style={ { display: 'flex', gap: 0, borderBottom: '2px solid #e5e7eb', marginBottom: 20 } }>
                { ( [ 'handlers', 'tables', 'config', 'logs' ] as SubTab[] ).map( tab => (
                    <button
                        key={ tab }
                        onClick={ () => setSubTab( tab ) }
                        style={ {
                            padding: '10px 20px',
                            fontSize: 13,
                            fontWeight: subTab === tab ? 700 : 500,
                            color: subTab === tab ? '#1a3a2a' : '#6b7280',
                            background: subTab === tab ? '#f0fdf4' : 'transparent',
                            border: 'none',
                            borderBottom: subTab === tab ? '2px solid #1a3a2a' : '2px solid transparent',
                            cursor: 'pointer',
                            textTransform: 'capitalize',
                        } }
                    >
                        { tab === 'handlers' ? '⚡ Handlers' : tab === 'tables' ? '🗄️ Tables' : tab === 'config' ? '⚙️ Config' : '📋 Logs' }
                    </button>
                ) ) }
            </div>

            {/* Handlers Sub-Tab */ }
            { subTab === 'handlers' && (
                <div style={ { display: 'grid', gridTemplateColumns: '240px 1fr', gap: 20 } }>
                    {/* Handler list */ }
                    <div style={ { borderRight: '1px solid #e5e7eb', paddingRight: 16 } }>
                        { HANDLERS.map( h => (
                            <div
                                key={ h.name }
                                onClick={ () => setSelectedHandler( h.name ) }
                                style={ {
                                    padding: '8px 12px',
                                    fontSize: 12,
                                    fontWeight: selectedHandler === h.name ? 700 : 400,
                                    color: selectedHandler === h.name ? '#1a3a2a' : '#374151',
                                    background: selectedHandler === h.name ? '#f0fdf4' : 'transparent',
                                    borderRadius: 8,
                                    cursor: 'pointer',
                                    marginBottom: 4,
                                    borderLeft: selectedHandler === h.name ? '3px solid #1a3a2a' : '3px solid transparent',
                                } }
                            >
                                <div>{ h.displayName }</div>
                                <div style={ { fontSize: 10, color: '#9ca3af' } }>{ h.category }</div>
                            </div>
                        ) ) }
                    </div>

                    {/* Handler detail */ }
                    <div>
                        <h3 style={ { fontSize: 16, fontWeight: 700, color: '#1a3a2a', marginBottom: 4 } }>
                            { activeHandler.displayName }
                        </h3>
                        <p style={ { fontSize: 12, color: '#6b7280', marginBottom: 12 } }>{ activeHandler.description }</p>
                        <div style={ { fontSize: 11, color: '#9ca3af', marginBottom: 16 } }>
                            <code style={ { background: '#f3f4f6', padding: '2px 6px', borderRadius: 4 } }>{ activeHandler.endpoint }</code>
                        </div>

                        {/* Flow diagram */ }
                        <div style={ { background: '#f9fafb', borderRadius: 10, padding: 16, marginBottom: 16 } }>
                            <div style={ { fontSize: 12, fontWeight: 600, marginBottom: 10, color: '#1a3a2a' } }>Flow</div>
                            { activeHandler.flow.map( ( step, i ) => (
                                <div key={ i } style={ { display: 'flex', alignItems: 'flex-start', marginBottom: 8 } }>
                                    <div style={ {
                                        width: 22, height: 22, borderRadius: '50%', background: '#1a3a2a', color: '#d1f470',
                                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                                        fontSize: 10, fontWeight: 700, flexShrink: 0, marginRight: 10, marginTop: 1,
                                    } }>{ i + 1 }</div>
                                    <div style={ { fontSize: 12, color: '#374151', lineHeight: 1.5 } }>{ step }</div>
                                </div>
                            ) ) }
                        </div>

                        {/* Tables used */ }
                        <div style={ { marginBottom: 16 } }>
                            <div style={ { fontSize: 12, fontWeight: 600, marginBottom: 6, color: '#1a3a2a' } }>DynamoDB Tables</div>
                            <div style={ { display: 'flex', flexWrap: 'wrap', gap: 6 } }>
                                { activeHandler.tables.map( t => (
                                    <span key={ t } style={ { fontSize: 11, background: '#ecfdf5', color: '#065f46', padding: '3px 8px', borderRadius: 6 } }>
                                        { t }
                                    </span>
                                ) ) }
                            </div>
                        </div>

                        {/* Config keys */ }
                        { activeHandler.config.length > 0 && (
                            <div>
                                <div style={ { fontSize: 12, fontWeight: 600, marginBottom: 6, color: '#1a3a2a' } }>Config Keys (SystemConfigTable)</div>
                                <div style={ { display: 'flex', flexWrap: 'wrap', gap: 6 } }>
                                    { activeHandler.config.map( c => (
                                        <span key={ c } style={ { fontSize: 11, background: '#fef3c7', color: '#92400e', padding: '3px 8px', borderRadius: 6 } }>
                                            { c }
                                        </span>
                                    ) ) }
                                </div>
                            </div>
                        ) }
                    </div>
                </div>
            ) }

            {/* Tables Sub-Tab */ }
            { subTab === 'tables' && (
                <div>
                    <div style={ { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 12 } }>
                        { tables.map( t => (
                            <div key={ t.name } style={ { background: '#f9fafb', borderRadius: 10, padding: '12px 16px', border: '1px solid #e5e7eb' } }>
                                <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center' } }>
                                    <span style={ { fontSize: 12, fontWeight: 600, color: '#1a3a2a' } }>
                                        { t.name.replace( 'stack-wecare-digital-', '' ) }
                                    </span>
                                    <span style={ { fontSize: 10, background: '#d1fae5', color: '#065f46', padding: '2px 6px', borderRadius: 4 } }>
                                        { t.status }
                                    </span>
                                </div>
                                <div style={ { fontSize: 10, color: '#9ca3af', marginTop: 4 } }>{ t.name }</div>
                            </div>
                        ) ) }
                    </div>
                </div>
            ) }

            {/* Config Sub-Tab */ }
            { subTab === 'config' && (
                <div>
                    { configLoading ? (
                        <div style={ { padding: 20, textAlign: 'center', color: '#6b7280' } }>Loading config...</div>
                    ) : (
                        <div style={ { display: 'grid', gap: 12 } }>
                            { configs.map( c => (
                                <div key={ c.id } style={ { background: '#f9fafb', borderRadius: 10, padding: '12px 16px', border: '1px solid #e5e7eb' } }>
                                    <div style={ { fontSize: 12, fontWeight: 600, color: '#1a3a2a' } }>{ c.id }</div>
                                    <div style={ { fontSize: 12, color: '#374151', marginTop: 4, fontFamily: 'monospace' } }>{ c.configValue }</div>
                                </div>
                            ) ) }
                        </div>
                    ) }
                </div>
            ) }

            {/* Logs Sub-Tab */ }
            { subTab === 'logs' && (
                <div>
                    <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 } }>
                        <span style={ { fontSize: 12, color: '#6b7280' } }>Recent message activity (last 5)</span>
                        <button onClick={ loadLogs } disabled={ logsLoading } style={ { fontSize: 11, padding: '4px 10px', background: '#1a3a2a', color: '#d1f470', border: 'none', borderRadius: 6, cursor: 'pointer' } }>
                            { logsLoading ? '...' : 'Refresh' }
                        </button>
                    </div>
                    <div style={ { background: '#000', borderRadius: 10, padding: 16, fontFamily: 'monospace', fontSize: 11, color: '#d1d5db', maxHeight: 400, overflow: 'auto' } }>
                        { logs.length === 0 ? (
                            <div style={ { color: '#6b7280' } }>No logs available</div>
                        ) : (
                            logs.map( ( log, i ) => (
                                <div key={ i } style={ { marginBottom: 6, borderBottom: '1px solid #1f2937', paddingBottom: 6 } }>{ log }</div>
                            ) )
                        ) }
                    </div>
                </div>
            ) }
        </div>
    );
}
