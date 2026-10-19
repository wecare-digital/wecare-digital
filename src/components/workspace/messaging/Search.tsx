/**
 * Search — cross-channel search over messages + contacts (canonical MessagesTable).
 * Type a query to find matching messages (any channel) and contacts.
 */
import React, { useState, useEffect, useMemo } from 'react';
import Link from 'next/link';
import Layout from '../../../components/Layout';
import PageHeader from '../../../components/PageHeader';
import SEO from '../../../components/SEO';
import { useToastContext } from '../../../contexts/ToastContext';
import * as api from '../../../api/client';
import { colors } from '../../../lib/design-tokens';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const CH: Record<string, { fg: string; bg: string }> = {
    whatsapp: { fg: '#15803d', bg: '#f0fdf4' }, sms: { fg: '#1d4ed8', bg: '#eff6ff' },
    email: { fg: '#b45309', bg: '#fffbeb' }, rcs: { fg: '#0f766e', bg: '#f0fdfa' }, voice: { fg: '#6d28d9', bg: '#f5f3ff' },
};

const SearchPage: React.FC<PageProps> = ( { signOut, user, embedded } ) => {
    const toast = useToastContext();
    const [ messages, setMessages ] = useState<api.Message[]>( [] );
    const [ contacts, setContacts ] = useState<api.Contact[]>( [] );
    const [ q, setQ ] = useState( '' );
    const [ loading, setLoading ] = useState( true );

    useEffect( () => {
        Promise.all( [ api.listMessages( undefined, 'ALL', 2000 ), api.listContacts() ] )
            .then( ( [ m, c ] ) => { setMessages( m ); setContacts( c ); } )
            .catch( () => toast.error( 'Failed to load search index' ) )
            .finally( () => setLoading( false ) );
    }, [ toast ] );

    const query = q.trim().toLowerCase();
    const msgHits = useMemo( () => !query ? [] : messages.filter( m => ( m.content || '' ).toLowerCase().includes( query ) ).slice( 0, 50 ), [ messages, query ] );
    const contactHits = useMemo( () => !query ? [] : contacts.filter( c => ( c.name || '' ).toLowerCase().includes( query ) || ( c.phone || '' ).includes( query ) || ( c.email || '' ).toLowerCase().includes( query ) ).slice( 0, 30 ), [ contacts, query ] );

    const content = (
        <>
            <div className="se-wrap">
                <PageHeader title="Search" subtitle="Find messages & contacts across every channel" icon="message" />
                <input className="se-input" autoFocus placeholder="Search messages and contacts…" value={ q } onChange={ e => setQ( e.target.value ) } />
                { loading && <div className="se-empty">Building index…</div> }
                { !loading && query && (
                    <>
                        <div className="se-section">Contacts ({ contactHits.length })</div>
                        { contactHits.map( c => (
                            <Link key={ c.contactId } href={ `/workspace/customers?contact=${encodeURIComponent( c.contactId )}` } className="se-row">
                                <span className="se-row-title">{ c.name || c.phone }</span>
                                <span className="se-row-sub">{ c.phone || c.email }</span>
                            </Link>
                        ) ) }
                        <div className="se-section">Messages ({ msgHits.length })</div>
                        { msgHits.map( m => {
                            const ch = ( m.channel || 'whatsapp' ).toLowerCase();
                            const cm = CH[ ch ] || { fg: colors.textMuted, bg: colors.bgSecondary };
                            return (
                                <Link key={ m.messageId } href="/workspace/engage/inbox" className="se-row">
                                    <span className="se-badge" style={ { color: cm.fg, background: cm.bg } }>{ ch }</span>
                                    <span className="se-row-title">{ ( m.content || '' ).slice( 0, 100 ) }</span>
                                    <span className="se-row-sub">{ ( m.direction || '' ).toLowerCase() }</span>
                                </Link>
                            );
                        } ) }
                        { contactHits.length === 0 && msgHits.length === 0 && <div className="se-empty">No matches</div> }
                    </>
                ) }
            </div>
            <style jsx>{ `
                .se-wrap { padding: 20px; max-width: 800px; margin: 0 auto; }
                .se-input { width: 100%; padding: 12px 16px; border: 1px solid ${colors.border}; border-radius: 12px; font-size: var(--text-base); margin: 12px 0; }
                .se-input:focus { outline: none; border-color: ${colors.primary}; }
                .se-section { font-size: var(--text-xs); font-weight: 700; text-transform: uppercase; color: ${colors.textMuted}; margin: 18px 0 6px; }
                .se-row { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border: 1px solid ${colors.borderLight}; border-radius: 10px; margin-bottom: 6px; text-decoration: none; }
                .se-row:hover { background: ${colors.bgHover}; }
                .se-badge { font-size: var(--text-xs); font-weight: 700; padding: 2px 8px; border-radius: 9999px; text-transform: capitalize; }
                .se-row-title { font-size: var(--text-md); color: ${colors.text}; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
                .se-row-sub { font-size: var(--text-xs); color: ${colors.textMuted}; text-transform: capitalize; }
                .se-empty { text-align: center; padding: 30px; color: ${colors.textMuted}; }
            ` }</style>
        </>
    );

    if ( embedded ) return content;
    return (
        <Layout user={ user } onSignOut={ signOut }>
            <SEO title="Search | WECARE.DIGITAL" description="Cross-channel search" noindex={ true } />
            { content }
        </Layout>
    );
};

export default SearchPage;
