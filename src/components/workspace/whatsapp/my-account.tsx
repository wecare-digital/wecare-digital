/**
 * My WhatsApp Account — CUSTOMER limited view (protected)
 *
 * Read-only self-view for an onboarded business customer. Shows ONLY their own
 * linked WhatsApp Business Account (scoped server-side by the caller's
 * custom:partner_waba_id Cognito attribute via GET /partners/me).
 *
 * Customers get no admin controls — no tenant list, no onboarding of others,
 * no disconnect. Those live on the admin-only [retired public path]/whatsapp/connected-accounts/.
 */
import React, { useEffect, useState } from 'react';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import { useToastContext } from '../../../contexts/ToastContext';
import { authFetch } from '../../../api/client';
import { API_BASE } from '../../../config/constants';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const card: React.CSSProperties = { background: '#fff', border: '1px solid #e5e5e5', borderRadius: 8, padding: 20, marginBottom: 16 };
const row: React.CSSProperties = { display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid #f0f0f0', fontSize: 14 };
const key: React.CSSProperties = { color: '#777' };

const MyAccountPage: React.FC<PageProps> = ( { signOut, user, embedded = false } ) => {
    const toast = useToastContext();
    const [ tenant, setTenant ] = useState<any>( null );
    const [ isAdmin, setIsAdmin ] = useState( false );
    const [ linked, setLinked ] = useState<boolean | null>( null );
    const [ wallet, setWallet ] = useState<any>( null );
    const [ ledger, setLedger ] = useState<any[]>( [] );
    const [ loading, setLoading ] = useState( true );
    const [ sendTo, setSendTo ] = useState( '' );
    const [ sendText, setSendText ] = useState( '' );
    const [ sending, setSending ] = useState( false );
    const [ addAmt, setAddAmt ] = useState( '' );
    const [ adding, setAdding ] = useState( false );
    const [ messages, setMessages ] = useState<any[]>( [] );
    const [ analytics, setAnalytics ] = useState<any>( null );

    const loadMessages = async () => {
        try
        {
            const res = await authFetch( `${API_BASE}/partners/messages` );
            if ( res.ok )
            {
                const d = await res.json();
                setMessages( Array.isArray( d.messages ) ? d.messages : [] );
            }
        } catch { /* ignore */ }
    };

    const addFunds = async () => {
        const amount = parseFloat( addAmt );
        if ( !amount || amount <= 0 ) { toast.error( 'Enter a valid amount' ); return; }
        setAdding( true );
        try
        {
            const res = await authFetch( `${API_BASE}/partners/billing/topup-order`, {
                method: 'POST', body: JSON.stringify( { amount } ),
            } );
            const data = await res.json();
            if ( !res.ok || data?.success === false ) throw new Error( data?.error || 'Could not create payment link' );
            if ( data.shortUrl ) { window.open( data.shortUrl, '_blank' ); setAddAmt( '' ); }
            else throw new Error( 'No payment link returned' );
        } catch ( e: any ) { toast.error( e?.message || 'Top-up failed' ); }
        finally { setAdding( false ); }
    };

    const sendMessage = async () => {
        if ( !sendTo.trim() || !sendText.trim() ) { toast.error( 'Enter recipient and message' ); return; }
        setSending( true );
        try
        {
            const res = await authFetch( `${API_BASE}/partners/send`, {
                method: 'POST', body: JSON.stringify( { to: sendTo.trim(), type: 'text', text: sendText.trim() } ),
            } );
            const data = await res.json();
            if ( !res.ok || data?.success === false ) throw new Error( data?.error || 'Send failed' );
            toast.success( `Sent — ${data.messageId || ''}` );
            setSendText( '' );
            setTimeout( loadMessages, 1500 );
        } catch ( e: any ) { toast.error( e?.message || 'Send failed' ); }
        finally { setSending( false ); }
    };

    useEffect( () => {
        ( async () => {
            try
            {
                const [ meRes, billRes ] = await Promise.all( [
                    authFetch( `${API_BASE}/partners/me` ),
                    authFetch( `${API_BASE}/partners/billing` ),
                ] );
                const data = await meRes.json();
                if ( !meRes.ok ) throw new Error( data?.error || 'Failed to load' );
                setTenant( data.tenant || null );
                setIsAdmin( !!data.isAdmin );
                setLinked( data.linked ?? !!data.tenant );
                if ( billRes.ok )
                {
                    const bd = await billRes.json();
                    setWallet( bd.wallet || null );
                    setLedger( Array.isArray( bd.ledger ) ? bd.ledger : [] );
                }
                if ( !data.isAdmin && ( data.linked ?? !!data.tenant ) )
                {
                    loadMessages();
                    try
                    {
                        const aRes = await authFetch( `${API_BASE}/partners/billing/analytics?days=30` );
                        if ( aRes.ok ) setAnalytics( ( await aRes.json() ).analytics || null );
                    } catch { /* ignore */ }
                }
            } catch ( e: any )
            {
                toast.error( e?.message || 'Failed to load your account' );
            } finally
            {
                setLoading( false );
            }
        } )();
    }, [ toast ] );

    const p = tenant?.details?.phone || {};
    const w = tenant?.details?.waba || {};

    const content = (
        <div style={ { maxWidth: 720, margin: '0 auto', padding: 16 } }>
            <SEO title="My WhatsApp Account" description="Your linked WhatsApp Business Account." noindex />
            <h1 style={ { fontSize: 22, fontWeight: 700, marginBottom: 4 } }>My WhatsApp Account</h1>
            <p style={ { color: '#777', fontSize: 13, marginBottom: 16 } }>Your linked WhatsApp Business Account and its status.</p>

            { loading ? <div style={ { color: '#777' } }>Loading…</div>
                : isAdmin ? (
                    <div style={ card }>
                        <p style={ { fontSize: 14, margin: 0 } }>You’re signed in as an admin. Manage all connected accounts on the <strong>Connected Accounts</strong> page.</p>
                    </div>
                ) : !linked ? (
                    <div style={ card }>
                        <p style={ { fontSize: 14, margin: 0 } }>No WhatsApp Business Account is linked to your login yet. Please contact WECARE.DIGITAL to complete onboarding.</p>
                    </div>
                ) : (
                    <div style={ card }>
                        <div style={ row }><span style={ key }>Business name</span><span>{ p.name || w.name || '—' }</span></div>
                        <div style={ row }><span style={ key }>Phone number</span><span>{ p.display || '—' }</span></div>
                        <div style={ row }><span style={ key }>Quality rating</span><span>{ p.quality || '—' }</span></div>
                        <div style={ row }><span style={ key }>WABA review status</span><span>{ w.reviewStatus || '—' }</span></div>
                        <div style={ row }><span style={ key }>Status</span><span>{ tenant?.status || '—' }</span></div>
                        <div style={ { ...row, borderBottom: 'none' } }><span style={ key }>Connected on</span><span>{ tenant?.connectedAt ? new Date( tenant.connectedAt ).toLocaleString() : '—' }</span></div>
                    </div>
                ) }

            { !loading && !isAdmin && linked && (
                <div style={ card }>
                    <h3 style={ { marginTop: 0, fontSize: 16 } }>Wallet & Usage</h3>
                    <div style={ row }>
                        <span style={ key }>Prepaid balance</span>
                        <span style={ { fontWeight: 700 } }>{ wallet ? `${wallet.balance} ${wallet.currency}` : '—' }
                            { wallet?.status === 'SUSPENDED' && <span style={ { color: '#a11', marginLeft: 8, fontSize: 12 } }>SUSPENDED — top up to resume</span> }
                        </span>
                    </div>
                    <div style={ { marginTop: 10, fontSize: 13, color: '#555' } }>Recent activity</div>
                    { ledger.length === 0 ? <div style={ { fontSize: 13, color: '#999', marginTop: 4 } }>No usage yet.</div>
                        : (
                            <div style={ { marginTop: 6 } }>
                                { ledger.slice( 0, 10 ).map( ( l, i ) => (
                                    <div key={ i } style={ { display: 'flex', justifyContent: 'space-between', fontSize: 12, padding: '4px 0', borderBottom: '1px solid #f5f5f5' } }>
                                        <span style={ { color: '#666' } }>{ l.ts ? new Date( l.ts ).toLocaleString() : '' } · { l.type }{ l.category ? ` (${l.category})` : '' }</span>
                                        <span style={ { color: l.type === 'topup' ? 'var(--accent)' : '#a11' } }>{ l.type === 'topup' ? '+' : '−' }{ l.amount } · bal { l.balanceAfter }</span>
                                    </div>
                                ) ) }
                            </div>
                        ) }
                    <div style={ { marginTop: 12, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' } }>
                        <input value={ addAmt } onChange={ e => setAddAmt( e.target.value ) } type="number" placeholder="amount (INR)"
                            style={ { width: 140, padding: '7px 10px', border: '1px solid #d0d0d0', borderRadius: 6, fontSize: 14 } } />
                        <button onClick={ addFunds } disabled={ adding }
                            style={ { padding: '8px 16px', background: adding ? '#ccc' : 'var(--lime)', color: 'var(--accent)', border: 'none', borderRadius: 6, cursor: adding ? 'not-allowed' : 'pointer', fontSize: 14, fontWeight: 700 } }>
                            { adding ? 'Creating link…' : 'Add funds' }
                        </button>
                    </div>
                    <p style={ { fontSize: 12, color: '#999', marginTop: 8 } }>Secure payment via Razorpay. Your balance updates automatically after payment.</p>
                    { analytics && (
                        <div style={ { marginTop: 14, paddingTop: 12, borderTop: '1px solid #f0f0f0' } }>
                            <div style={ { fontSize: 13, fontWeight: 600, marginBottom: 6 } }>Usage (last 30 days)</div>
                            <div style={ { fontSize: 13, color: '#444' } }>
                                { analytics.messageCount || 0 } messages · spent { analytics.totalSpend || 0 } { analytics.currency } · topped up { analytics.totalTopup || 0 } { analytics.currency }
                            </div>
                            { analytics.spendByCategory && Object.keys( analytics.spendByCategory ).length > 0 && (
                                <div style={ { fontSize: 12, color: '#666', marginTop: 4 } }>
                                    { Object.entries( analytics.spendByCategory ).map( ( [ c, v ]: any ) => `${c}: ${v}` ).join( ' · ' ) }
                                </div>
                            ) }
                        </div>
                    ) }
                </div>
            ) }

            { !loading && !isAdmin && linked && (
                <div style={ card }>
                    <h3 style={ { marginTop: 0, fontSize: 16 } }>Send a message</h3>
                    <p style={ { fontSize: 12, color: '#777', marginTop: 0 } }>Sends from your WhatsApp number. Charged to your prepaid wallet.</p>
                    <input value={ sendTo } onChange={ e => setSendTo( e.target.value ) } placeholder="Recipient (E.164, e.g. 919900000000)"
                        style={ { width: '100%', padding: '8px 10px', border: '1px solid #d0d0d0', borderRadius: 6, fontSize: 14, marginBottom: 8 } } />
                    <textarea value={ sendText } onChange={ e => setSendText( e.target.value ) } placeholder="Message text"
                        style={ { width: '100%', minHeight: 80, padding: '8px 10px', border: '1px solid #d0d0d0', borderRadius: 6, fontSize: 14, marginBottom: 8 } } />
                    <button onClick={ sendMessage } disabled={ sending }
                        style={ { padding: '9px 16px', background: sending ? '#ccc' : 'var(--accent)', color: '#fff', border: 'none', borderRadius: 6, cursor: sending ? 'not-allowed' : 'pointer', fontSize: 14, fontWeight: 600 } }>
                        { sending ? 'Sending…' : 'Send message' }
                    </button>
                </div>
            ) }

            { !loading && !isAdmin && linked && (
                <div style={ card }>
                    <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center' } }>
                        <h3 style={ { margin: 0, fontSize: 16 } }>Recent messages</h3>
                        <button onClick={ loadMessages } style={ { padding: '5px 10px', border: '1px solid #d0d0d0', borderRadius: 6, background: '#fff', cursor: 'pointer', fontSize: 12 } }>Refresh</button>
                    </div>
                    { messages.length === 0 ? <div style={ { fontSize: 13, color: '#999', marginTop: 8 } }>No messages yet.</div>
                        : (
                            <div style={ { marginTop: 8 } }>
                                { messages.map( ( m, i ) => (
                                    <div key={ m.id || i } style={ { padding: '8px 0', borderBottom: '1px solid #f5f5f5', fontSize: 13 } }>
                                        <div style={ { display: 'flex', justifyContent: 'space-between', color: '#666', fontSize: 11 } }>
                                            <span>{ m.direction === 'inbound' ? '⬇ received' : '⬆ sent' }{ m.senderPhone ? ` · ${m.senderPhone}` : '' }</span>
                                            <span>{ m.timestamp ? new Date( m.timestamp * 1000 ).toLocaleString() : '' } · { m.status }</span>
                                        </div>
                                        <div style={ { marginTop: 2, color: '#222' } }>{ ( m.content || m.messageType || '' ).slice( 0, 200 ) }</div>
                                    </div>
                                ) ) }
                            </div>
                        ) }
                </div>
            ) }
        </div>
    );

    if ( embedded ) return content;
    return <Layout user={ user } onSignOut={ signOut }>{ content }</Layout>;
};

export default MyAccountPage;
