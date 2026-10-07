/**
 * Scheduled — unified view of all upcoming scheduled sends (cross-channel via the
 * scheduled-messages Lambda). List, filter by status, and cancel pending sends.
 */
import React, { useState, useEffect, useMemo, useCallback } from 'react';
import Layout from '../../../../components/Layout';
import PageHeader from '../../../../components/PageHeader';
import SEO from '../../../../components/SEO';
import Select, { type SelectOption } from '../../../../components/ui/Select';
import { useToastContext } from '../../../../contexts/ToastContext';
import * as api from '../../../../api/client';
import { colors } from '../../../../lib/design-tokens';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const STATUS_COLOR: Record<string, { fg: string; bg: string }> = {
    pending: { fg: '#b45309', bg: '#fffbeb' },
    sent: { fg: '#1d4ed8', bg: '#eff6ff' },
    failed: { fg: '#b91c1c', bg: '#fef2f2' },
    cancelled: { fg: '#6b7280', bg: '#f9fafb' },
};

const STATUS_FILTER_OPTIONS: SelectOption[] = [
    { value: 'all', label: 'All status' },
    { value: 'pending', label: 'Pending' },
    { value: 'sent', label: 'Sent' },
    { value: 'failed', label: 'Failed' },
    { value: 'cancelled', label: 'Cancelled' },
];

const fmt = ( iso: string ) => { const d = new Date( iso ); return isNaN( d.getTime() ) ? iso : d.toLocaleString( 'en-IN', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' } ); };

const ScheduledPage: React.FC<PageProps> = ( { signOut, user, embedded } ) => {
    const toast = useToastContext();
    const [ items, setItems ] = useState<api.ScheduledMessage[]>( [] );
    const [ loading, setLoading ] = useState( true );
    const [ statusFilter, setStatusFilter ] = useState( 'all' );
    const [ cancelling, setCancelling ] = useState<string | null>( null );

    const load = useCallback( async () => {
        try { setItems( await api.listScheduledMessages() ); }
        catch { toast.error( 'Failed to load scheduled messages' ); }
        finally { setLoading( false ); }
    }, [ toast ] );

    useEffect( () => { load(); }, [ load ] );

    const rows = useMemo( () => {
        const r = statusFilter === 'all' ? items : items.filter( i => ( i.status || '' ).toLowerCase() === statusFilter );
        return [ ...r ].sort( ( a, b ) => new Date( a.scheduledAt ).getTime() - new Date( b.scheduledAt ).getTime() );
    }, [ items, statusFilter ] );

    const cancel = useCallback( async ( id: string ) => {
        if ( cancelling ) return;
        setCancelling( id );
        try
        {
            const ok = await api.cancelScheduledMessage( id );
            if ( ok ) { toast.success( 'Cancelled' ); load(); } else toast.error( 'Cancel failed' );
        } catch { toast.error( 'Cancel failed' ); }
        finally { setCancelling( null ); }
    }, [ cancelling, toast, load ] );

    const content = (
        <>
            <div className="sc-wrap">
                <PageHeader title="Scheduled" subtitle="Upcoming scheduled sends across channels" icon="message" />
                <div className="sc-toolbar">
                    { /* `.sc-filter` is not forwarded: it is a styled-jsx class, and styled-jsx
                         scopes by adding a hash to the elements IN THIS FILE's JSX - markup a
                         child component renders never receives it, so the class would be inert
                         on the wrapper and the box would be drawn twice if it were not. */ }
                    <Select ariaLabel="Status" value={ statusFilter }
                        onChange={ v => setStatusFilter( v ) }
                        options={ STATUS_FILTER_OPTIONS } style={ { width: 180 } } />
                    <button className="sc-refresh" onClick={ load }>Refresh</button>
                </div>
                <div className="sc-table-wrap">
                    <table className="sc-table">
                        <thead><tr><th>Scheduled for</th><th>Template</th><th>Contact</th><th>Status</th><th></th></tr></thead>
                        <tbody>
                            { loading ? <tr><td colSpan={ 5 } className="sc-empty">Loading…</td></tr> :
                                rows.length === 0 ? <tr><td colSpan={ 5 } className="sc-empty">No scheduled messages</td></tr> :
                                    rows.map( s => {
                                        const sc = STATUS_COLOR[ ( s.status || '' ).toLowerCase() ] || { fg: colors.textMuted, bg: colors.bgSecondary };
                                        const pending = ( s.status || '' ).toLowerCase() === 'pending';
                                        return (
                                            <tr key={ s.scheduledId }>
                                                <td className="sc-when">{ fmt( s.scheduledAt ) }</td>
                                                <td className="sc-tpl">{ s.templateName || '—' }</td>
                                                <td className="sc-contact">{ s.contactId || '—' }</td>
                                                <td><span className="sc-status" style={ { color: sc.fg, background: sc.bg } }>{ s.status || '—' }</span></td>
                                                <td>{ pending ? <button className="sc-cancel" disabled={ cancelling === s.scheduledId } onClick={ () => cancel( s.scheduledId ) }>{ cancelling === s.scheduledId ? '…' : 'Cancel' }</button> : '' }</td>
                                            </tr>
                                        );
                                    } ) }
                        </tbody>
                    </table>
                </div>
            </div>

            <style jsx>{ `
                .sc-wrap { padding: 20px; max-width: 1000px; margin: 0 auto; }
                .sc-toolbar { display: flex; gap: 10px; margin: 12px 0; }
                .sc-filter { padding: 9px 12px; border: 1px solid ${colors.border}; border-radius: 10px; font-size: 13px; background: #fff; }
                .sc-refresh { padding: 9px 16px; border: 1px solid ${colors.border}; border-radius: 10px; background: #fff; font-size: 13px; cursor: pointer; }
                .sc-table-wrap { border: 1px solid ${colors.border}; border-radius: 12px; overflow: hidden; background: #fff; }
                .sc-table { width: 100%; border-collapse: collapse; }
                .sc-table th { background: ${colors.bgSecondary}; padding: 10px 14px; text-align: left; font-size: 11px; font-weight: 700; color: ${colors.textMuted}; text-transform: uppercase; }
                .sc-table td { padding: 11px 14px; border-top: 1px solid ${colors.borderLight}; font-size: 13px; color: ${colors.text}; }
                .sc-when { white-space: nowrap; }
                .sc-tpl { font-weight: 600; }
                .sc-contact { font-family: monospace; font-size: 12px; color: ${colors.textSecondary}; }
                .sc-status { font-size: 11px; font-weight: 700; padding: 3px 9px; border-radius: 9999px; text-transform: capitalize; }
                .sc-cancel { padding: 5px 12px; border: 1px solid ${colors.danger}; color: ${colors.danger}; background: #fff; border-radius: 8px; font-size: 12px; cursor: pointer; }
                .sc-cancel:disabled { opacity: 0.5; cursor: not-allowed; }
                .sc-empty { text-align: center; padding: 40px; color: ${colors.textMuted}; }
            ` }</style>
        </>
    );

    if ( embedded ) return content;
    return (
        <Layout user={ user } onSignOut={ signOut }>
            <SEO title="Scheduled | WECARE.DIGITAL" description="Scheduled sends across channels" noindex={ true } />
            { content }
        </Layout>
    );
};

export default ScheduledPage;
