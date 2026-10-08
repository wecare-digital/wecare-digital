/**
 * Conversions API for Business Messaging — [retired public path]/whatsapp/conversions-api
 *
 * Console for the Click-to-WhatsApp (CTWA) Conversions API. Uses the
 * whatsapp_business_manage_events permission to log in-thread conversion events
 * (Purchase, LeadSubmitted, ...) to Meta so ad campaigns that click to WhatsApp
 * can optimize and measure. Backed by:
 *   GET  /wa-business/capi              (dataset + captured click ids + event log)
 *   POST /wa-business/capi/dataset      (get/create the dataset for a WABA)
 *   POST /wa-business/capi/event        (log a conversion event)
 *
 * ctwa_clid is captured automatically from the inbound `referral` object when a
 * customer arrives from a Click-to-WhatsApp ad. Purchase events are logged
 * automatically on Razorpay payment success; this page also lets you log events
 * manually for testing/verification in Events Manager.
 */
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import Layout from '../../../../components/Layout';
import SEO from '../../../../components/SEO';
import Button from '../../../../components/ui/Button';
import Select, { type SelectOption } from '../../../../components/ui/Select';
import { useToastContext } from '../../../../contexts/ToastContext';
import {
    getCapiStatus, createCapiDataset, logCapiEvent,
    type CapiStatus,
} from '../../../../api/client';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const WABAS = [
    { label: 'WABA1 · +91 93309 94400', wabaId: '2094615664435155' },
    { label: 'WABA2 · +91 99033 00044', wabaId: '2513394156072604' },
];

const WABA_OPTIONS: SelectOption[] = WABAS.map( w => ( { value: w.wabaId, label: w.label } ) );
/** Layout only. The native control sized to its widest option; the trigger may shrink. */
const WABA_SELECT_STYLE: React.CSSProperties = { flex: '0 1 240px', minWidth: 0 };
/** The marginBottom the shared `input` object carried. */
const EVENT_SELECT_STYLE: React.CSSProperties = { marginBottom: 10 };
const FALLBACK_EVENTS = [ 'Purchase', 'LeadSubmitted', 'AddToCart', 'InitiateCheckout' ];

const ConversionsApiPage: React.FC<PageProps> = ( { signOut, user, embedded = false } ) => {
    const toast = useToastContext();
    const [ wabaId, setWabaId ] = useState( WABAS[ 0 ].wabaId );
    const [ status, setStatus ] = useState<CapiStatus | null>( null );
    const [ busy, setBusy ] = useState( '' );

    // manual event form
    const [ evName, setEvName ] = useState( 'Purchase' );
    const [ evPhone, setEvPhone ] = useState( '' );
    const [ evClid, setEvClid ] = useState( '' );
    const [ evValue, setEvValue ] = useState( '' );
    const [ evCurrency, setEvCurrency ] = useState( 'INR' );
    const [ evOrder, setEvOrder ] = useState( '' );

    /* Derived from the FETCHED status, so memoised rather than rebuilt inline. */
    const eventOptions: SelectOption[] = useMemo(
        () => ( status?.supportedEvents || FALLBACK_EVENTS ).map( ev => ( { value: ev, label: ev } ) ),
        [ status ]
    );

    const load = useCallback( async () => {
        setBusy( 'load' );
        try
        {
            const s = await getCapiStatus( wabaId );
            setStatus( s );
        } finally { setBusy( '' ); }
    }, [ wabaId ] );

    useEffect( () => { load(); }, [ load ] );

    const doCreateDataset = async () => {
        setBusy( 'dataset' );
        try
        {
            const r = await createCapiDataset( wabaId );
            if ( r?.success && r.datasetId ) toast.success( `Dataset ready: ${r.datasetId}` );
            else toast.error( r?.error?.message || 'Could not create/link dataset' );
            await load();
        } finally { setBusy( '' ); }
    };

    const doLogEvent = async () => {
        if ( !evClid && !evPhone ) { toast.error( 'Enter a customer phone or a ctwa_clid' ); return; }
        setBusy( 'event' );
        try
        {
            const r = await logCapiEvent( {
                wabaId, eventName: evName,
                phone: evPhone.replace( /\D/g, '' ) || undefined,
                ctwaClid: evClid || undefined,
                value: evValue ? Number( evValue ) : undefined,
                currency: evCurrency || 'INR',
                orderId: evOrder || undefined,
            } );
            if ( r?.success ) toast.success( `${evName} logged → dataset ${r.datasetId}` );
            else toast.error( r?.error?.message || r?.error || 'Event failed (no ctwa_clid for this contact?)' );
            await load();
        } finally { setBusy( '' ); }
    };

    const dsId = status?.dataset?.datasetId;
    const dsErr = status?.dataset?.error;
    const card: React.CSSProperties = { background: '#fff', border: '1px solid #e5e7eb', borderRadius: 10, padding: 18, marginBottom: 18 };
    const label: React.CSSProperties = { display: 'block', fontSize: 13, color: '#374151', marginBottom: 4, fontWeight: 600 };
    const input: React.CSSProperties = { width: '100%', padding: '8px 10px', border: '1px solid #d1d5db', borderRadius: 6, marginBottom: 10 };

    const body = (
        <div style={ { maxWidth: 980, margin: '0 auto', padding: embedded ? 0 : 20 } }>
            <h1 style={ { fontSize: 22, fontWeight: 800, marginBottom: 4 } }>Conversions API — Click to WhatsApp</h1>
            <p style={ { color: '#6b7280', fontSize: 14, marginBottom: 18 } }>
                Log in-thread conversion events (Purchase, Lead, …) back to Meta so Click-to-WhatsApp ad
                campaigns can optimize and measure. Uses the <code>whatsapp_business_manage_events</code> permission.
            </p>

            <div style={ { display: 'flex', gap: 10, alignItems: 'center', marginBottom: 16 } }>
                <Select ariaLabel="WhatsApp Business Account" value={ wabaId }
                    onChange={ v => setWabaId( v ) } options={ WABA_OPTIONS } style={ WABA_SELECT_STYLE } />
                <Button onClick={ load } disabled={ busy !== '' }>{ busy === 'load' ? 'Loading…' : 'Refresh' }</Button>
            </div>

            {/* Dataset */ }
            <div style={ card }>
                <h2 style={ { fontSize: 16, fontWeight: 700, marginBottom: 8 } }>1 · Dataset</h2>
                <p style={ { fontSize: 13, color: '#6b7280', marginBottom: 10 } }>
                    Meta needs a dataset (created from the WhatsApp Business Account ID) as the destination for events.
                    One dataset links per WABA; the business owns it and can see events in Events Manager.
                </p>
                { dsId
                    ? <div style={ { fontSize: 14 } }>Dataset ID: <code style={ { background: '#ecfdf5', padding: '2px 6px', borderRadius: 4, color: '#065f46' } }>{ dsId }</code></div>
                    : <div style={ { fontSize: 14, color: '#b45309' } }>{ dsErr ? `Error: ${dsErr?.message || JSON.stringify( dsErr )}` : 'No dataset linked yet.' }</div> }
                <div style={ { marginTop: 10 } }>
                    <Button onClick={ doCreateDataset } disabled={ busy !== '' }>{ busy === 'dataset' ? 'Working…' : ( dsId ? 'Re-check / link dataset' : 'Create / link dataset' ) }</Button>
                </div>
            </div>

            {/* Captured clicks */ }
            <div style={ card }>
                <h2 style={ { fontSize: 16, fontWeight: 700, marginBottom: 8 } }>2 · Captured ad clicks (ctwa_clid)</h2>
                <p style={ { fontSize: 13, color: '#6b7280', marginBottom: 10 } }>
                    When a customer messages you after tapping a Click-to-WhatsApp ad, the inbound webhook
                    carries a <code>ctwa_clid</code>. We store it against their number so conversions can be attributed.
                </p>
                { ( status?.capturedClicks?.length ?? 0 ) === 0
                    ? <div style={ { fontSize: 13, color: '#9ca3af' } }>No ad clicks captured yet.</div>
                    : (
                        <table style={ { width: '100%', fontSize: 13, borderCollapse: 'collapse' } }>
                            <thead><tr style={ { textAlign: 'left', color: '#6b7280' } }>
                                <th style={ { padding: 6 } }>Phone</th><th>Source</th><th>Headline</th><th>Click ID</th><th>When</th>
                            </tr></thead>
                            <tbody>
                                { status!.capturedClicks.map( ( c, i ) => (
                                    <tr key={ i } style={ { borderTop: '1px solid #f0f0f0' } }>
                                        <td style={ { padding: 6 } }>{ c.phone }</td>
                                        <td>{ c.sourceType }</td>
                                        <td>{ c.headline }</td>
                                        <td><code>{ ( c.ctwaClid || '' ).slice( 0, 14 ) }…</code></td>
                                        <td>{ c.ts ? new Date( c.ts * 1000 ).toLocaleString() : '' }</td>
                                    </tr>
                                ) ) }
                            </tbody>
                        </table>
                    ) }
            </div>

            {/* Log event */ }
            <div style={ card }>
                <h2 style={ { fontSize: 16, fontWeight: 700, marginBottom: 8 } }>3 · Log a conversion event</h2>
                <p style={ { fontSize: 13, color: '#6b7280', marginBottom: 10 } }>
                    Purchase events fire automatically on Razorpay payment success. You can also log one manually to
                    verify it appears in Events Manager. Enter a customer phone (we look up their stored click id) or paste a ctwa_clid.
                </p>
                <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 } }>
                    <div>
                        <label style={ label }>Event</label>
                        <Select ariaLabel="Event" value={ evName } onChange={ v => setEvName( v ) }
                            options={ eventOptions } style={ EVENT_SELECT_STYLE } />
                    </div>
                    <div>
                        <label style={ label }>Customer phone</label>
                        <input style={ input } value={ evPhone } onChange={ e => setEvPhone( e.target.value ) } placeholder="9198XXXXXXXX" />
                    </div>
                    <div style={ { gridColumn: '1 / span 2' } }>
                        <label style={ label }>…or ctwa_clid (optional)</label>
                        <input style={ input } value={ evClid } onChange={ e => setEvClid( e.target.value ) } placeholder="ARAkLkA8rmlF…" />
                    </div>
                    <div>
                        <label style={ label }>Value</label>
                        <input style={ input } value={ evValue } onChange={ e => setEvValue( e.target.value ) } placeholder="4599" />
                    </div>
                    <div>
                        <label style={ label }>Currency</label>
                        <input style={ input } value={ evCurrency } onChange={ e => setEvCurrency( e.target.value ) } />
                    </div>
                    <div style={ { gridColumn: '1 / span 2' } }>
                        <label style={ label }>Order ID (optional)</label>
                        <input style={ input } value={ evOrder } onChange={ e => setEvOrder( e.target.value ) } placeholder="WD-ORDER-123" />
                    </div>
                </div>
                <Button onClick={ doLogEvent } disabled={ busy !== '' }>{ busy === 'event' ? 'Logging…' : 'Log event to Meta' }</Button>
            </div>

            {/* Recent events */ }
            <div style={ card }>
                <h2 style={ { fontSize: 16, fontWeight: 700, marginBottom: 8 } }>4 · Recent logged events</h2>
                { ( status?.recentEvents?.length ?? 0 ) === 0
                    ? <div style={ { fontSize: 13, color: '#9ca3af' } }>No events logged yet.</div>
                    : (
                        <table style={ { width: '100%', fontSize: 13, borderCollapse: 'collapse' } }>
                            <thead><tr style={ { textAlign: 'left', color: '#6b7280' } }>
                                <th style={ { padding: 6 } }>When</th><th>Event</th><th>Value</th><th>Phone</th><th>Status</th>
                            </tr></thead>
                            <tbody>
                                { status!.recentEvents.map( ( e, i ) => (
                                    <tr key={ i } style={ { borderTop: '1px solid #f0f0f0' } }>
                                        <td style={ { padding: 6 } }>{ e.ts ? new Date( e.ts * 1000 ).toLocaleString() : '' }</td>
                                        <td>{ e.event }</td>
                                        <td>{ e.value != null ? `${e.currency || ''} ${e.value}` : '—' }</td>
                                        <td>{ e.phone || '—' }</td>
                                        <td style={ { color: e.ok ? '#065f46' : '#b91c1c', fontWeight: 600 } }>{ e.ok ? 'OK' : 'FAILED' }</td>
                                    </tr>
                                ) ) }
                            </tbody>
                        </table>
                    ) }
            </div>
        </div>
    );

    if ( embedded ) return body;
    return (
        <Layout onSignOut={ signOut } user={ user }>
            <SEO title="Conversions API | WECARE.DIGITAL" description="Click-to-WhatsApp Conversions API console" noindex />
            { body }
        </Layout>
    );
};

export default ConversionsApiPage;
