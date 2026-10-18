/**
 * Contact 360 — unified activity timeline for one contact.
 *
 * Aggregates everything we know about a contact into one chronological feed:
 * messages (all channels) + calls + payments (from the canonical MessagesTable) +
 * orders (by phone) + invoices (by contactId). Read-only.
 */
import React, { useState, useEffect, useMemo, useCallback } from 'react';
import Link from 'next/link';
import Layout from '../../../components/Layout';
import PageHeader from '../../../components/PageHeader';
import SEO from '../../../components/SEO';
import { useToastContext } from '../../../contexts/ToastContext';
import * as api from '../../../api/client';
import { colors } from '../../../lib/design-tokens';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

type EntryType = 'message' | 'call' | 'payment' | 'order' | 'invoice';
interface Entry { type: EntryType; ts: number; title: string; sub: string; tag: string; tagFg: string; tagBg: string; }

const TYPE_STYLE: Record<EntryType, { fg: string; bg: string }> = {
    message: { fg: '#1d4ed8', bg: '#eff6ff' },
    call: { fg: '#6d28d9', bg: '#f5f3ff' },
    payment: { fg: '#15803d', bg: '#f0fdf4' },
    order: { fg: '#b45309', bg: '#fffbeb' },
    invoice: { fg: '#0f766e', bg: '#f0fdfa' },
};

const ms = ( v: any ) => { const n = new Date( v ).getTime(); return isNaN( n ) ? ( typeof v === 'number' ? v * ( v < 1e12 ? 1000 : 1 ) : 0 ) : n; };
const fmt = ( ts: number ) => { const d = new Date( ts ); return isNaN( d.getTime() ) ? '' : d.toLocaleString( 'en-IN', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' } ); };

const Contact360: React.FC<PageProps> = ( { signOut, user, embedded } ) => {
    const toast = useToastContext();
    const [ contacts, setContacts ] = useState<api.Contact[]>( [] );
    const [ selected, setSelected ] = useState<string>( '' );
    const [ search, setSearch ] = useState( '' );
    const [ entries, setEntries ] = useState<Entry[]>( [] );
    const [ loading, setLoading ] = useState( false );

    useEffect( () => { api.listContacts().then( setContacts ).catch( () => { } ); }, [] );

    const contact = contacts.find( c => c.contactId === selected );

    const loadTimeline = useCallback( async ( c: api.Contact ) => {
        setLoading( true );
        const out: Entry[] = [];
        try
        {
            const msgs = await api.listMessages( c.contactId, 'ALL', 1000 );
            msgs.forEach( m => {
                const ch = ( m.channel || '' ).toLowerCase();
                const isCall = ( m.messageType || '' ) === 'call' || ch === 'voice';
                const isPay = ( m.messageType || '' ).includes( 'payment' );
                const type: EntryType = isCall ? 'call' : isPay ? 'payment' : 'message';
                out.push( {
                    type, ts: ms( m.timestamp ),
                    title: m.content || `[${m.messageType || ch}]`,
                    sub: `${( m.direction || '' ).toLowerCase()} · ${( m.status || '' ).toLowerCase()}`,
                    tag: isCall ? 'Call' : isPay ? 'Payment' : ( CHLABEL[ ch ] || 'Message' ),
                    tagFg: TYPE_STYLE[ type ].fg, tagBg: TYPE_STYLE[ type ].bg,
                } );
            } );
        } catch { /* non-fatal */ }
        try
        {
            const inv = await api.listInvoicesEngine( { contactId: c.contactId, limit: 100 } );
            ( inv.invoices || [] ).forEach( ( i: any ) => out.push( {
                type: 'invoice', ts: ms( i.createdAt || i.issuedAt || i.timestamp ),
                title: `Invoice ${i.invoiceNumber || i.invoiceId || ''} — ₹${( i.totalAmount || i.amount || 0 )}`,
                sub: ( i.status || '' ).toLowerCase(), tag: 'Invoice', tagFg: TYPE_STYLE.invoice.fg, tagBg: TYPE_STYLE.invoice.bg,
            } ) );
        } catch { /* non-fatal */ }
        try
        {
            if ( c.phone )
            {
                const ord = await api.listOrders( { phone: c.phone, limit: 100 } );
                ( ord.orders || [] ).forEach( ( o: any ) => out.push( {
                    type: 'order', ts: ms( o.createdAt || o.timestamp ),
                    title: `Order ${o.orderId || o.orderNumber || ''}`,
                    sub: ( o.status || '' ).toLowerCase(), tag: 'Order', tagFg: TYPE_STYLE.order.fg, tagBg: TYPE_STYLE.order.bg,
                } ) );
            }
        } catch { /* non-fatal */ }
        out.sort( ( a, b ) => b.ts - a.ts );
        setEntries( out );
        setLoading( false );
    }, [] );

    useEffect( () => { if ( contact ) loadTimeline( contact ); else setEntries( [] ); }, [ contact, loadTimeline ] );

    const filteredContacts = useMemo( () => {
        const q = search.trim().toLowerCase();
        return contacts.filter( c => !q || ( c.name || '' ).toLowerCase().includes( q ) || ( c.phone || '' ).includes( q ) || ( c.email || '' ).toLowerCase().includes( q ) ).slice( 0, 100 );
    }, [ contacts, search ] );

    const counts = useMemo( () => {
        const c: Record<string, number> = {};
        entries.forEach( e => { c[ e.type ] = ( c[ e.type ] || 0 ) + 1; } );
        return c;
    }, [ entries ] );

    const content = (
        <>
            <div className="c3-wrap">
                <PageHeader title="Contact 360" subtitle="Everything about a contact — messages, calls, payments, orders & invoices" icon="contacts" />
                <div className="c3-panes">
                    <div className="c3-list">
                        <input className="c3-search" placeholder="Search contacts…" value={ search } onChange={ e => setSearch( e.target.value ) } />
                        <div className="c3-contacts">
                            { filteredContacts.map( c => (
                                <button key={ c.contactId } className={ `c3-contact ${selected === c.contactId ? 'active' : ''}` } onClick={ () => setSelected( c.contactId ) }>
                                    <span className="c3-c-name">{ c.name || c.phone || c.email }</span>
                                    <span className="c3-c-sub">{ c.phone || c.email }</span>
                                </button>
                            ) ) }
                        </div>
                    </div>
                    <div className="c3-timeline">
                        { !contact ? <div className="c3-empty">Select a contact</div> : (
                            <>
                                <div className="c3-head">
                                    <div>
                                        <div className="c3-name">{ contact.name || contact.phone }</div>
                                        <div className="c3-meta">{ contact.phone }{ contact.email ? ` · ${contact.email}` : '' }</div>
                                    </div>
                                    <div className="c3-counts">
                                        { ( [ 'message', 'call', 'payment', 'order', 'invoice' ] as EntryType[] ).map( t => (
                                            <span key={ t } className="c3-count" style={ { color: TYPE_STYLE[ t ].fg, background: TYPE_STYLE[ t ].bg } }>{ counts[ t ] || 0 } { t }</span>
                                        ) ) }
                                    </div>
                                    <Link href="/workspace/engage/inbox" className="c3-open">Open inbox →</Link>
                                </div>
                                <div className="c3-feed">
                                    { loading ? <div className="c3-empty">Loading…</div> :
                                        entries.length === 0 ? <div className="c3-empty">No activity</div> :
                                            entries.map( ( e, i ) => (
                                                <div key={ i } className="c3-entry">
                                                    <span className="c3-tag" style={ { color: e.tagFg, background: e.tagBg } }>{ e.tag }</span>
                                                    <div className="c3-entry-body">
                                                        <div className="c3-entry-title">{ e.title.slice( 0, 140 ) }</div>
                                                        <div className="c3-entry-sub">{ e.sub } · { fmt( e.ts ) }</div>
                                                    </div>
                                                </div>
                                            ) ) }
                                </div>
                            </>
                        ) }
                    </div>
                </div>
            </div>

            <style jsx>{ `
                .c3-wrap { padding: 20px; max-width: 1200px; margin: 0 auto; }
                .c3-panes { display: grid; grid-template-columns: 300px 1fr; gap: 16px; height: 72vh; }
                .c3-list { display: flex; flex-direction: column; border: 1px solid ${colors.border}; border-radius: 12px; background: #fff; overflow: hidden; }
                .c3-search { margin: 10px; padding: 8px 12px; border: 1px solid ${colors.border}; border-radius: 9px; font-size: var(--text-sm); }
                .c3-contacts { flex: 1; overflow-y: auto; }
                .c3-contact { display: flex; flex-direction: column; gap: 2px; width: 100%; text-align: left; padding: 10px 14px; border: none; border-top: 1px solid ${colors.borderLight}; background: #fff; cursor: pointer; }
                .c3-contact:hover { background: ${colors.bgHover}; }
                .c3-contact.active { background: ${colors.bgActive}; }
                .c3-c-name { font-size: var(--text-sm); font-weight: 600; color: ${colors.text}; }
                .c3-c-sub { font-size: var(--text-xs); color: ${colors.textMuted}; }
                .c3-timeline { border: 1px solid ${colors.border}; border-radius: 12px; background: #fff; display: flex; flex-direction: column; overflow: hidden; }
                .c3-head { padding: 14px 18px; border-bottom: 1px solid ${colors.border}; display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
                .c3-name { font-size: var(--text-base); font-weight: 700; color: ${colors.text}; }
                .c3-meta { font-size: var(--text-xs); color: ${colors.textMuted}; }
                .c3-counts { display: flex; gap: 6px; flex-wrap: wrap; margin-left: auto; }
                .c3-count { font-size: var(--text-xs); font-weight: 600; padding: 3px 9px; border-radius: 9999px; text-transform: capitalize; }
                .c3-open { font-size: var(--text-sm); color: ${colors.primary}; text-decoration: none; font-weight: 600; }
                .c3-feed { flex: 1; overflow-y: auto; padding: 14px 18px; }
                .c3-entry { display: flex; gap: 12px; padding: 10px 0; border-bottom: 1px solid ${colors.borderLight}; }
                .c3-tag { font-size: var(--text-xs); font-weight: 700; padding: 3px 9px; border-radius: 9999px; height: fit-content; white-space: nowrap; }
                .c3-entry-title { font-size: var(--text-sm); color: ${colors.text}; }
                .c3-entry-sub { font-size: var(--text-xs); color: ${colors.textMuted}; margin-top: 2px; text-transform: capitalize; }
                .c3-empty { display: flex; align-items: center; justify-content: center; height: 100%; color: ${colors.textMuted}; }
                @media (max-width: 800px) { .c3-panes { grid-template-columns: 1fr; height: auto; } }
            ` }</style>
        </>
    );

    if ( embedded ) return content;
    return (
        <Layout user={ user } onSignOut={ signOut }>
            <SEO title="Contact 360 | WECARE.DIGITAL" description="Unified contact activity timeline" noindex={ true } />
            { content }
        </Layout>
    );
};

const CHLABEL: Record<string, string> = { whatsapp: 'WhatsApp', sms: 'SMS', email: 'Email', rcs: 'RCS' };

export default Contact360;
