/**
 * Content Library — unified view of templates/content across channels.
 *
 * Aggregates WhatsApp message templates + RCS templates (and links to the reusable media
 * library) into one searchable, channel-filterable list. Create/edit deep-links to each
 * channel's own template tool. Read-only aggregation — low risk.
 */
import React, { useState, useEffect, useMemo } from 'react';
import Link from 'next/link';
import Layout from '../../../../components/Layout';
import PageHeader from '../../../../components/PageHeader';
import SEO from '../../../../components/SEO';
import Select, { type SelectOption } from '../../../../components/ui/Select';
import { useToastContext } from '../../../../contexts/ToastContext';
import * as api from '../../../../api/client';
import { colors } from '../../../../lib/design-tokens';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

interface Item {
    channel: 'whatsapp' | 'rcs';
    name: string;
    status: string;
    category: string;
    language: string;
    preview: string;
}

const CH: Record<string, { label: string; fg: string; bg: string; create: string }> = {
    whatsapp: { label: 'WhatsApp', fg: '#15803d', bg: '#f0fdf4', create: '/workspace/engage/whatsapp/settings' },
    rcs: { label: 'RCS', fg: '#0f766e', bg: '#f0fdfa', create: '/workspace/engage/rcs' },
};
const STATUS_COLOR: Record<string, { fg: string; bg: string }> = {
    approved: { fg: '#15803d', bg: '#f0fdf4' },
    pending: { fg: '#b45309', bg: '#fffbeb' },
    rejected: { fg: '#b91c1c', bg: '#fef2f2' },
};
const CHANNEL_FILTER_OPTIONS: SelectOption[] = [
    { value: 'all', label: 'All channels' },
    { value: 'whatsapp', label: 'WhatsApp' },
    { value: 'rcs', label: 'RCS' },
];

const bodyOf = ( t: api.WhatsAppTemplate ): string => {
    const b = ( t.components || [] ).find( c => c.type === 'BODY' );
    return b?.text || '';
};

const ContentLibrary: React.FC<PageProps> = ( { signOut, user, embedded } ) => {
    const toast = useToastContext();
    const [ items, setItems ] = useState<Item[]>( [] );
    const [ loading, setLoading ] = useState( true );
    const [ channelFilter, setChannelFilter ] = useState( 'all' );
    const [ search, setSearch ] = useState( '' );

    useEffect( () => {
        ( async () => {
            const out: Item[] = [];
            try
            {
                const wa = await api.listTemplates();
                ( wa || [] ).forEach( t => out.push( {
                    channel: 'whatsapp', name: t.name, status: ( t.status || '' ).toLowerCase(),
                    category: t.category || '', language: t.language || '', preview: bodyOf( t ),
                } ) );
            } catch { /* non-fatal */ }
            try
            {
                const rcs = await api.listRcsTemplates();
                ( rcs || [] ).forEach( ( t: any ) => out.push( {
                    channel: 'rcs', name: t.name || t.templateName || t.id || 'template',
                    status: ( t.status || 'approved' ).toLowerCase(), category: t.type || 'rich', language: t.language || '',
                    preview: t.text || t.description || '',
                } ) );
            } catch { /* non-fatal */ }
            setItems( out );
            setLoading( false );
        } )().catch( () => { setLoading( false ); toast.error( 'Failed to load content' ); } );
    }, [ toast ] );

    const filtered = useMemo( () => {
        const q = search.trim().toLowerCase();
        return items
            .filter( i => channelFilter === 'all' || i.channel === channelFilter )
            .filter( i => !q || i.name.toLowerCase().includes( q ) || i.preview.toLowerCase().includes( q ) );
    }, [ items, channelFilter, search ] );

    const content = (
        <>
            <div className="cl-wrap">
                <PageHeader title="Content Library" subtitle="Templates & reusable content across all channels" icon="message" />

                <div className="cl-toolbar">
                    <input className="cl-search" placeholder="Search templates…" value={ search } onChange={ e => setSearch( e.target.value ) } />
                    { /* `.cl-filter` is dropped for the styled-jsx scoping reason: the class the
                         stylesheet expects is hashed onto this file's own JSX, never onto markup
                         a child component renders. Width is layout and stays. */ }
                    <Select ariaLabel="Channel" value={ channelFilter }
                        onChange={ v => setChannelFilter( v ) }
                        options={ CHANNEL_FILTER_OPTIONS } style={ { width: 170 } } />
                    <Link href="/workspace/engage/whatsapp/settings" className="cl-new">+ WhatsApp template</Link>
                    <Link href="/workspace/engage/rcs" className="cl-new">+ RCS template</Link>
                </div>

                <div className="cl-grid">
                    { loading ? <div className="cl-empty">Loading…</div> :
                        filtered.length === 0 ? <div className="cl-empty">No templates</div> :
                            filtered.map( ( i, idx ) => {
                                const cm = CH[ i.channel ];
                                const sc = STATUS_COLOR[ i.status ] || { fg: colors.textMuted, bg: colors.bgSecondary };
                                return (
                                    <div key={ i.channel + i.name + idx } className="cl-card">
                                        <div className="cl-card-head">
                                            <span className="cl-pill" style={ { color: cm.fg, background: cm.bg } }>{ cm.label }</span>
                                            <span className="cl-pill" style={ { color: sc.fg, background: sc.bg } }>{ i.status || '—' }</span>
                                        </div>
                                        <div className="cl-name">{ i.name }</div>
                                        { i.preview && <p className="cl-preview">{ i.preview.slice( 0, 120 ) }</p> }
                                        <div className="cl-meta">{ [ i.category, i.language ].filter( Boolean ).join( ' · ' ) }</div>
                                    </div>
                                );
                            } ) }
                </div>
            </div>

            <style jsx>{ `
                .cl-wrap { padding: 20px; max-width: 1100px; margin: 0 auto; }
                .cl-toolbar { display: flex; gap: 10px; margin: 12px 0; flex-wrap: wrap; align-items: center; }
                .cl-search { flex: 1; min-width: 200px; padding: 9px 14px; border: 1px solid ${colors.border}; border-radius: 10px; font-size: 14px; }
                .cl-filter { padding: 9px 12px; border: 1px solid ${colors.border}; border-radius: 10px; font-size: 13px; background: #fff; }
                .cl-new { padding: 9px 14px; border: 1px solid ${colors.border}; border-radius: 10px; font-size: 13px; color: ${colors.primary}; text-decoration: none; font-weight: 600; }
                .cl-new:hover { background: ${colors.bgHover}; }
                .cl-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 14px; }
                .cl-card { border: 1px solid ${colors.border}; border-radius: 12px; padding: 14px; background: #fff; }
                .cl-card-head { display: flex; gap: 6px; margin-bottom: 8px; }
                .cl-pill { font-size: 10px; font-weight: 700; padding: 3px 9px; border-radius: 9999px; text-transform: capitalize; }
                .cl-name { font-size: 14px; font-weight: 700; color: ${colors.text}; word-break: break-word; }
                .cl-preview { font-size: 12px; color: ${colors.textSecondary}; margin: 6px 0 0; }
                .cl-meta { font-size: 11px; color: ${colors.textMuted}; margin-top: 8px; text-transform: capitalize; }
                .cl-empty { grid-column: 1/-1; padding: 40px; text-align: center; color: ${colors.textMuted}; }
            ` }</style>
        </>
    );

    if ( embedded ) return content;
    return (
        <Layout user={ user } onSignOut={ signOut }>
            <SEO title="Content Library | WECARE.DIGITAL" description="Unified templates across channels" noindex={ true } />
            { content }
        </Layout>
    );
};

export default ContentLibrary;
