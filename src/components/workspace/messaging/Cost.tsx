/**
 * Cost & Usage — estimated per-channel spend from message volume × an editable rate card.
 * Read-only (no backend); rates are adjustable inline for what-if estimates.
 */
import React, { useState, useEffect, useMemo } from 'react';
import Layout from '../../../components/Layout';
import PageHeader from '../../../components/PageHeader';
import SEO from '../../../components/SEO';
import { useToastContext } from '../../../contexts/ToastContext';
import * as api from '../../../api/client';
import { colors } from '../../../lib/design-tokens';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

// Editable default rate card (₹ per message; voice per call). Adjust to your contracts.
const DEFAULT_RATES: Record<string, number> = { whatsapp: 0.7, sms: 0.2, rcs: 0.3, email: 0.01, voice: 1.0 };
const CH_META: Record<string, { label: string; fg: string; bg: string }> = {
    whatsapp: { label: 'WhatsApp', fg: '#15803d', bg: '#f0fdf4' },
    sms: { label: 'SMS', fg: '#1d4ed8', bg: '#eff6ff' },
    rcs: { label: 'RCS', fg: '#0f766e', bg: '#f0fdfa' },
    email: { label: 'Email', fg: '#b45309', bg: '#fffbeb' },
    voice: { label: 'Voice', fg: '#6d28d9', bg: '#f5f3ff' },
};

const CostPage: React.FC<PageProps> = ( { signOut, user, embedded } ) => {
    const toast = useToastContext();
    const [ messages, setMessages ] = useState<api.Message[]>( [] );
    const [ loading, setLoading ] = useState( true );
    const [ rates, setRates ] = useState<Record<string, number>>( DEFAULT_RATES );

    useEffect( () => {
        api.listMessages( undefined, 'ALL', 5000 ).then( setMessages )
            .catch( () => toast.error( 'Failed to load usage' ) ).finally( () => setLoading( false ) );
    }, [ toast ] );

    const counts = useMemo( () => {
        const c: Record<string, number> = { whatsapp: 0, sms: 0, rcs: 0, email: 0, voice: 0 };
        messages.forEach( m => { const ch = ( m.channel || '' ).toLowerCase(); if ( c[ ch ] !== undefined ) c[ ch ]++; } );
        return c;
    }, [ messages ] );

    const totalCost = Object.keys( counts ).reduce( ( sum, ch ) => sum + counts[ ch ] * ( rates[ ch ] || 0 ), 0 );

    const content = (
        <>
            <div className="co-wrap">
                <PageHeader title="Cost & Usage" subtitle="Estimated per-channel spend — adjust rates for what-if" icon="payment" />
                { loading ? <div className="co-empty">Loading…</div> : (
                    <>
                        <div className="co-total">Estimated total: <strong>₹{ totalCost.toFixed( 2 ) }</strong> <span className="co-total-sub">({ messages.length } messages)</span></div>
                        <div className="co-table-wrap">
                            <table className="co-table">
                                <thead><tr><th>Channel</th><th>Volume</th><th>Rate (₹)</th><th>Est. cost (₹)</th></tr></thead>
                                <tbody>
                                    { Object.keys( CH_META ).map( ch => (
                                        <tr key={ ch }>
                                            <td><span className="co-pill" style={ { color: CH_META[ ch ].fg, background: CH_META[ ch ].bg } }>{ CH_META[ ch ].label }</span></td>
                                            <td>{ counts[ ch ] }</td>
                                            <td><input className="co-rate" type="number" step="0.01" min="0" value={ rates[ ch ] } onChange={ e => setRates( r => ( { ...r, [ ch ]: parseFloat( e.target.value ) || 0 } ) ) } /></td>
                                            <td className="co-cost">₹{ ( counts[ ch ] * ( rates[ ch ] || 0 ) ).toFixed( 2 ) }</td>
                                        </tr>
                                    ) ) }
                                </tbody>
                            </table>
                        </div>
                        <p className="co-note">Rates are estimates for planning. WhatsApp/Voice are typically billed per-conversation/per-minute; adjust to your provider contracts (Meta · AWS End User Messaging · Sinch RCS · Amazon SES · Plivo).</p>
                    </>
                ) }
            </div>
            <style jsx>{ `
                .co-wrap { padding: 20px; max-width: 800px; margin: 0 auto; }
                .co-total { font-size: 18px; color: ${colors.text}; margin: 14px 0; }
                .co-total strong { font-size: 24px; color: ${colors.primary}; }
                .co-total-sub { font-size: 13px; color: ${colors.textMuted}; }
                .co-table-wrap { border: 1px solid ${colors.border}; border-radius: 12px; overflow: hidden; background: #fff; }
                .co-table { width: 100%; border-collapse: collapse; }
                .co-table th { background: ${colors.bgSecondary}; padding: 10px 14px; text-align: left; font-size: 11px; font-weight: 700; color: ${colors.textMuted}; text-transform: uppercase; }
                .co-table td { padding: 11px 14px; border-top: 1px solid ${colors.borderLight}; font-size: 14px; color: ${colors.text}; }
                .co-pill { font-size: 11px; font-weight: 700; padding: 3px 9px; border-radius: 9999px; }
                .co-rate { width: 90px; padding: 6px 10px; border: 1px solid ${colors.border}; border-radius: 8px; font-size: 13px; }
                .co-cost { font-weight: 700; }
                .co-note { font-size: 12px; color: ${colors.textMuted}; margin-top: 12px; }
                .co-empty { text-align: center; padding: 40px; color: ${colors.textMuted}; }
            ` }</style>
        </>
    );

    if ( embedded ) return content;
    return (
        <Layout user={ user } onSignOut={ signOut }>
            <SEO title="Cost & Usage | WECARE.DIGITAL" description="Cross-channel cost estimate" noindex={ true } />
            { content }
        </Layout>
    );
};

export default CostPage;
