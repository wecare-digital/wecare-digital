/**
 * Connected Accounts — ADMIN partner management (protected, Admin/Operator)
 *
 * Full control over Embedded-Signup onboarded/migrated WhatsApp Business
 * Accounts: onboard a new number, migrate an existing number from another
 * provider, view every connected tenant with live details + provisioning step
 * results, and disconnect a tenant.
 *
 * Customers never see this page — they get the limited [retired public path]/whatsapp/my-account/.
 */
import React, { useCallback, useEffect, useState } from 'react';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import EmbeddedSignupPanel from '../../../components/EmbeddedSignupPanel';
import { useToastContext } from '../../../contexts/ToastContext';
import { useConfirm } from '../../../contexts/ConfirmContext';
import { authFetch } from '../../../api/client';
import { API_BASE } from '../../../config/constants';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

interface Tenant {
    wabaId?: string;
    phoneNumberId?: string;
    businessId?: string;
    mode?: string;
    status?: string;
    connectedAt?: string;
    disconnectedAt?: string;
    steps?: { step: string; ok: boolean | null; detail?: string }[];
    details?: { waba?: any; phone?: any };
}

const card: React.CSSProperties = { background: '#fff', border: '1px solid #e5e5e5', borderRadius: 8, padding: 20, marginBottom: 16 };
const tag = ( c: string ): React.CSSProperties => ( { display: 'inline-block', padding: '2px 8px', borderRadius: 10, fontSize: 'var(--text-xs)', fontWeight: 700, background: c === 'CONNECTED' ? '#e6f6ea' : '#fbeaea', color: c === 'CONNECTED' ? 'var(--accent)' : '#a11' } );
const btnDanger: React.CSSProperties = { padding: '6px 12px', background: '#7a1a1a', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 'var(--text-sm)' };

const ConnectedAccountsPage: React.FC<PageProps> = ( { signOut, user, embedded = false } ) => {
    const toast = useToastContext();
    const confirm = useConfirm();
    const [ tenants, setTenants ] = useState<Tenant[]>( [] );
    const [ loading, setLoading ] = useState( true );
    const [ mode, setMode ] = useState<'onboard' | 'migrate'>( 'onboard' );
    const [ customerEmail, setCustomerEmail ] = useState( '' );
    const [ wallets, setWallets ] = useState<Record<string, any>>( {} );
    const [ topupAmt, setTopupAmt ] = useState<Record<string, string>>( {} );
    const [ markup, setMarkup ] = useState<Record<string, string>>( {} );

    const saveSettings = async ( wabaId?: string ) => {
        if ( !wabaId ) return;
        const m = parseFloat( markup[ wabaId ] || '' );
        if ( isNaN( m ) ) { toast.error( 'Enter a markup %' ); return; }
        try
        {
            const res = await authFetch( `${API_BASE}/partners/billing/settings`, {
                method: 'POST', body: JSON.stringify( { wabaId, markupPct: m } ),
            } );
            const data = await res.json();
            if ( !res.ok ) throw new Error( data?.error || 'Save failed' );
            toast.success( `Markup set to ${m}%` );
            load();
        } catch ( e: any ) { toast.error( e?.message || 'Save failed' ); }
    };

    const load = useCallback( async () => {
        setLoading( true );
        try
        {
            const [ tRes, bRes ] = await Promise.all( [
                authFetch( `${API_BASE}/partners/tenants` ),
                authFetch( `${API_BASE}/partners/billing` ),
            ] );
            const data = await tRes.json();
            if ( !tRes.ok ) throw new Error( data?.error || 'Failed to load' );
            setTenants( Array.isArray( data.tenants ) ? data.tenants : [] );
            if ( bRes.ok )
            {
                const bd = await bRes.json();
                const map: Record<string, any> = {};
                ( bd.wallets || [] ).forEach( ( w: any ) => { map[ w.wabaId ] = w; } );
                setWallets( map );
            }
        } catch ( e: any )
        {
            toast.error( e?.message || 'Failed to load connected accounts' );
        } finally
        {
            setLoading( false );
        }
    }, [ toast ] );

    const topup = async ( wabaId?: string ) => {
        if ( !wabaId ) return;
        const amount = parseFloat( topupAmt[ wabaId ] || '' );
        if ( !amount || amount <= 0 ) { toast.error( 'Enter a valid amount' ); return; }
        try
        {
            const res = await authFetch( `${API_BASE}/partners/billing/topup`, {
                method: 'POST', body: JSON.stringify( { wabaId, amount } ),
            } );
            const data = await res.json();
            if ( !res.ok ) throw new Error( data?.error || 'Top-up failed' );
            toast.success( `Balance: ${data.balance}` );
            setTopupAmt( ( m ) => ( { ...m, [ wabaId ]: '' } ) );
            load();
        } catch ( e: any ) { toast.error( e?.message || 'Top-up failed' ); }
    };

    useEffect( () => { load(); }, [ load ] );

    const disconnect = async ( wabaId?: string ) => {
        if ( !wabaId ) return;
        const ok = await confirm( { title: 'Disconnect account?', message: `This marks WABA ${wabaId} as disconnected.`, confirmText: 'Disconnect' } );
        if ( !ok ) return;
        try
        {
            const res = await authFetch( `${API_BASE}/partners/tenants?wabaId=${encodeURIComponent( wabaId )}`, { method: 'DELETE' } );
            const data = await res.json();
            if ( !res.ok ) throw new Error( data?.error || 'Disconnect failed' );
            toast.success( 'Disconnected' );
            load();
        } catch ( e: any )
        {
            toast.error( e?.message || 'Disconnect failed' );
        }
    };

    const active = tenants.filter( t => t.status === 'CONNECTED' );

    const content = (
        <div style={ { maxWidth: 960, margin: '0 auto', padding: 16 } }>
            <SEO title="Connected Accounts" description="Manage onboarded WhatsApp Business Accounts." noindex />
            <h1 style={ { fontSize: 22, fontWeight: 700, marginBottom: 4 } }>Connected Accounts</h1>
            <p style={ { color: '#777', fontSize: 'var(--text-sm)', marginBottom: 16 } }>
                Onboard or migrate WhatsApp Business Accounts and manage every connected tenant. Admin only.
            </p>

            <div style={ card }>
                <div style={ { display: 'flex', gap: 8, marginBottom: 14 } }>
                    <button onClick={ () => setMode( 'onboard' ) } style={ { padding: '8px 14px', borderRadius: 8, border: '1px solid #d0d0d0', background: mode === 'onboard' ? 'var(--accent)' : '#fff', color: mode === 'onboard' ? '#fff' : '#333', cursor: 'pointer', fontWeight: 600 } }>Onboard new / existing</button>
                    <button onClick={ () => setMode( 'migrate' ) } style={ { padding: '8px 14px', borderRadius: 8, border: '1px solid #d0d0d0', background: mode === 'migrate' ? 'var(--accent)' : '#fff', color: mode === 'migrate' ? '#fff' : '#333', cursor: 'pointer', fontWeight: 600 } }>Migrate from another provider</button>
                </div>
                <div style={ { marginBottom: 12 } }>
                    <div style={ { fontSize: 'var(--text-xs)', fontWeight: 600, color: '#444', marginBottom: 4 } }>Customer email (optional — auto-creates their limited login)</div>
                    <input value={ customerEmail } onChange={ e => setCustomerEmail( e.target.value ) } placeholder="customer@business.com" type="email"
                        style={ { width: '100%', maxWidth: 360, padding: '8px 10px', border: '1px solid #d0d0d0', borderRadius: 6, fontSize: 'var(--text-md)' } } />
                </div>
                <EmbeddedSignupPanel admin mode={ mode } customerEmail={ customerEmail } onConnected={ () => { toast.success( 'Account connected' ); setCustomerEmail( '' ); load(); } } />
            </div>

            <div style={ card }>
                <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 } }>
                    <h3 style={ { margin: 0, fontSize: 'var(--text-base)' } }>Tenants ({ active.length })</h3>
                    <button onClick={ load } style={ { padding: '6px 12px', border: '1px solid #d0d0d0', borderRadius: 6, background: '#fff', cursor: 'pointer', fontSize: 'var(--text-sm)' } }>Refresh</button>
                </div>
                { loading ? <div style={ { color: '#777', fontSize: 'var(--text-md)' } }>Loading…</div>
                    : tenants.length === 0 ? <div style={ { color: '#777', fontSize: 'var(--text-md)' } }>No accounts connected yet. Use the panel above to onboard the first one.</div>
                        : (
                            <div style={ { display: 'grid', gap: 12 } }>
                                { tenants.map( ( t ) => (
                                    <div key={ t.wabaId } style={ { border: '1px solid #eee', borderRadius: 8, padding: 14 } }>
                                        <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' } }>
                                            <div>
                                                <div style={ { fontWeight: 700 } }>
                                                    { t.details?.phone?.name || t.details?.waba?.name || t.wabaId }
                                                    <span style={ { ...tag( t.status || '' ), marginLeft: 8 } }>{ t.status }</span>
                                                    { t.mode === 'migrate' && <span style={ { ...tag( 'CONNECTED' ), marginLeft: 6, background: '#eef', color: '#334' } }>migrated</span> }
                                                </div>
                                                <div style={ { fontSize: 'var(--text-xs)', color: '#666', marginTop: 4 } }>
                                                    WABA { t.wabaId } · Phone { t.phoneNumberId || '—' }
                                                    { t.details?.phone?.display ? ` · ${t.details.phone.display}` : '' }
                                                    { t.details?.phone?.quality ? ` · quality ${t.details.phone.quality}` : '' }
                                                </div>
                                                <div style={ { fontSize: 'var(--text-xs)', color: '#999', marginTop: 2 } }>Connected { t.connectedAt ? new Date( t.connectedAt ).toLocaleString() : '—' }</div>
                                                { t.steps && t.steps.length > 0 && (
                                                    <div style={ { fontSize: 'var(--text-xs)', marginTop: 6 } }>
                                                        { t.steps.map( ( s, i ) => (
                                                            <span key={ i } style={ { marginRight: 10, color: s.ok === true ? 'var(--accent)' : s.ok === false ? '#a11' : '#a60' } }>
                                                                { s.ok === true ? '✓' : s.ok === false ? '✕' : '•' } { s.step }
                                                            </span>
                                                        ) ) }
                                                    </div>
                                                ) }
                                            </div>
                                            { t.status === 'CONNECTED' && (
                                                <button style={ btnDanger } onClick={ () => disconnect( t.wabaId ) }>Disconnect</button>
                                            ) }
                                        </div>
                                        <div style={ { marginTop: 10, paddingTop: 10, borderTop: '1px solid #f0f0f0', display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' } }>
                                            <span style={ { fontSize: 'var(--text-sm)', fontWeight: 600 } }>
                                                Wallet: { wallets[ t.wabaId || '' ] ? `${wallets[ t.wabaId! ].balance} ${wallets[ t.wabaId! ].currency}` : '—' }
                                            </span>
                                            { wallets[ t.wabaId || '' ]?.status === 'SUSPENDED' && (
                                                <span style={ { ...tag( '' ), background: '#fbeaea', color: '#a11' } }>SUSPENDED (low balance)</span>
                                            ) }
                                            <input value={ topupAmt[ t.wabaId || '' ] || '' } onChange={ e => setTopupAmt( m => ( { ...m, [ t.wabaId || '' ]: e.target.value } ) ) }
                                                placeholder="amount" type="number"
                                                style={ { width: 100, padding: '5px 8px', border: '1px solid #d0d0d0', borderRadius: 6, fontSize: 'var(--text-sm)' } } />
                                            <button onClick={ () => topup( t.wabaId ) }
                                                style={ { padding: '5px 12px', background: 'var(--accent)', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 'var(--text-sm)' } }>Top up</button>
                                            <span style={ { fontSize: 'var(--text-xs)', color: '#777', marginLeft: 8 } }>Markup { wallets[ t.wabaId || '' ]?.markupPct ?? 0 }%</span>
                                            <input value={ markup[ t.wabaId || '' ] || '' } onChange={ e => setMarkup( m => ( { ...m, [ t.wabaId || '' ]: e.target.value } ) ) }
                                                placeholder="markup %" type="number"
                                                style={ { width: 90, padding: '5px 8px', border: '1px solid #d0d0d0', borderRadius: 6, fontSize: 'var(--text-sm)' } } />
                                            <button onClick={ () => saveSettings( t.wabaId ) }
                                                style={ { padding: '5px 12px', background: '#fff', color: 'var(--accent)', border: '1px solid var(--accent)', borderRadius: 6, cursor: 'pointer', fontSize: 'var(--text-sm)' } }>Save</button>
                                        </div>
                                    </div>
                                ) ) }
                            </div>
                        ) }
            </div>
        </div>
    );

    if ( embedded ) return content;
    return <Layout user={ user } onSignOut={ signOut }>{ content }</Layout>;
};

export default ConnectedAccountsPage;
