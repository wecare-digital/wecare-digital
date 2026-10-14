/**
 * Cross-channel Analytics — volume, direction split, delivery rate per channel,
 * computed from the canonical MessagesTable (one read, all channels).
 */
import React, { useState, useEffect, useMemo } from 'react';
import Layout from '../../../../components/Layout';
import PageHeader from '../../../../components/PageHeader';
import SEO from '../../../../components/SEO';
import { useToastContext } from '../../../../contexts/ToastContext';
import * as api from '../../../../api/client';
import { colors } from '../../../../lib/design-tokens';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const CH = [ 'whatsapp', 'sms', 'rcs', 'email', 'voice' ];
const CH_META: Record<string, { label: string; fg: string; bg: string }> = {
    whatsapp: { label: 'WhatsApp', fg: '#15803d', bg: '#f0fdf4' },
    sms: { label: 'SMS', fg: '#1d4ed8', bg: '#eff6ff' },
    rcs: { label: 'RCS', fg: '#0f766e', bg: '#f0fdfa' },
    email: { label: 'Email', fg: '#b45309', bg: '#fffbeb' },
    voice: { label: 'Voice', fg: '#6d28d9', bg: '#f5f3ff' },
};
const DELIVERED = new Set( [ 'delivered', 'read', 'sent' ] );

const AnalyticsPage: React.FC<PageProps> = ( { signOut, user, embedded } ) => {
    const toast = useToastContext();
    const [ messages, setMessages ] = useState<api.Message[]>( [] );
    const [ loading, setLoading ] = useState( true );
    // The clock is read in an effect rather than during render: this page is prerendered by the
    // static export, so a render-time Date.now() bakes the build timestamp into the HTML and then
    // mismatches on hydration. The 0 default is not a bug and is not user-visible — `messages`
    // starts as [] and is only populated by the effect below, so every stat is zero on the first
    // render regardless of what the time value is. First tick via requestAnimationFrame rather
    // than a direct call, matching ContactLocation.tsx: setNow( ... ) in the effect body is a
    // synchronous setState in an effect, which is its own lint error.
    const [ now, setNow ] = useState( 0 );

    useEffect( () => {
        const raf = requestAnimationFrame( () => setNow( Date.now() ) );
        return () => cancelAnimationFrame( raf );
    }, [] );

    useEffect( () => {
        api.listMessages( undefined, 'ALL', 5000 ).then( setMessages )
            .catch( () => toast.error( 'Failed to load analytics' ) ).finally( () => setLoading( false ) );
    }, [ toast ] );

    const stats = useMemo( () => {
        const wk = now - 7 * 86400000;
        const per: Record<string, { total: number; inbound: number; outbound: number; delivered: number; failed: number; week: number }> = {};
        CH.forEach( c => per[ c ] = { total: 0, inbound: 0, outbound: 0, delivered: 0, failed: 0, week: 0 } );
        let total = 0;
        for ( const m of messages )
        {
            const ch = ( m.channel || 'whatsapp' ).toLowerCase();
            if ( !per[ ch ] ) continue;
            const s = per[ ch ];
            s.total++; total++;
            const out = ( m.direction || '' ).toUpperCase() === 'OUTBOUND';
            out ? s.outbound++ : s.inbound++;
            const st = ( m.status || '' ).toLowerCase();
            if ( st === 'failed' ) s.failed++;
            else if ( out && DELIVERED.has( st ) ) s.delivered++;
            if ( ( new Date( m.timestamp ).getTime() || 0 ) >= wk ) s.week++;
        }
        return { per, total };
    }, [ messages, now ] );

    // ── Call analytics — computed from channel=voice breadcrumbs ──
    const callStats = useMemo( () => {
        const wk = now - 7 * 86400000;
        const calls = messages.filter( m => ( m.channel || '' ).toLowerCase() === 'voice' );
        const isAnswered = ( m: api.Message ) => {
            const st = ( m.status || '' ).toLowerCase();
            return ( m.duration || 0 ) > 0 || st === 'completed' || st === 'answered' || st === 'connected';
        };
        const byProv: Record<string, { total: number; answered: number; durSum: number }> = {};
        let total = 0, inbound = 0, outbound = 0, answered = 0, durSum = 0, week = 0;
        for ( const m of calls )
        {
            total++;
            ( ( m.direction || '' ).toUpperCase() === 'OUTBOUND' ) ? outbound++ : inbound++;
            const ans = isAnswered( m );
            if ( ans ) { answered++; durSum += ( m.duration || 0 ); }
            if ( ( new Date( m.timestamp ).getTime() || 0 ) >= wk ) week++;
            const rawType = ( m.callType || 'other' ).toLowerCase();
            const prov = rawType === 'aws' || rawType === 'whatsapp' ? rawType : 'legacy';
            if ( !byProv[ prov ] ) byProv[ prov ] = { total: 0, answered: 0, durSum: 0 };
            byProv[ prov ].total++;
            if ( ans ) { byProv[ prov ].answered++; byProv[ prov ].durSum += ( m.duration || 0 ); }
        }
        return {
            total, inbound, outbound, answered, week,
            pickupRate: total > 0 ? Math.round( ( answered / total ) * 100 ) : 0,
            avgDuration: answered > 0 ? Math.round( durSum / answered ) : 0,
            byProv,
        };
    }, [ messages, now ] );

    const fmtDur = ( s: number ) => {
        if ( !s ) return '0:00';
        const m = Math.floor( s / 60 ), sec = s % 60;
        return `${m}:${String( sec ).padStart( 2, '0' )}`;
    };
    const PROV_META: Record<string, { label: string; fg: string }> = {
        aws: { label: 'AWS', fg: '#1d4ed8' },
        legacy: { label: 'Legacy calls', fg: '#6b7280' },
        whatsapp: { label: 'WhatsApp', fg: '#15803d' },
    };

    const maxTotal = Math.max( 1, ...CH.map( c => stats.per[ c ]?.total || 0 ) );

    const content = (
        <>
            <div className="an-wrap">
                <PageHeader title="Analytics" subtitle="Cross-channel volume, mix & delivery — from the unified table" icon="message" />
                { loading ? <div className="an-empty">Loading…</div> : (
                    <>
                        <div className="an-cards">
                            <div className="an-card"><div className="an-num">{ stats.total }</div><div className="an-lbl">Total messages</div></div>
                            { CH.map( c => {
                                const s = stats.per[ c ];
                                const rate = s.outbound > 0 ? Math.round( ( s.delivered / s.outbound ) * 100 ) : 100;
                                return (
                                    <div key={ c } className="an-card">
                                        <span className="an-pill" style={ { color: CH_META[ c ].fg, background: CH_META[ c ].bg } }>{ CH_META[ c ].label }</span>
                                        <div className="an-num">{ s.total }</div>
                                        <div className="an-lbl">{ s.week } this week</div>
                                        { c !== 'voice' && <div className="an-rate">{ rate }% delivered</div> }
                                    </div>
                                );
                            } ) }
                        </div>

                        <div className="an-section">Volume by channel</div>
                        <div className="an-bars">
                            { CH.map( c => {
                                const s = stats.per[ c ];
                                return (
                                    <div key={ c } className="an-bar-row">
                                        <span className="an-bar-label">{ CH_META[ c ].label }</span>
                                        <div className="an-bar-track"><div className="an-bar-fill" style={ { width: `${( s.total / maxTotal ) * 100}%`, background: CH_META[ c ].fg } } /></div>
                                        <span className="an-bar-val">{ s.total } <span className="an-bar-sub">({ s.inbound }↓ / { s.outbound }↑)</span></span>
                                    </div>
                                );
                            } ) }
                        </div>

                        <div className="an-section">Call analytics</div>
                        <div className="an-cards">
                            <div className="an-card"><div className="an-num">{ callStats.total }</div><div className="an-lbl">Total calls</div><div className="an-rate">{ callStats.week } this week</div></div>
                            <div className="an-card"><div className="an-num">{ callStats.pickupRate }%</div><div className="an-lbl">Pickup rate</div><div className="an-rate">{ callStats.answered } / { callStats.total } answered</div></div>
                            <div className="an-card"><div className="an-num">{ fmtDur( callStats.avgDuration ) }</div><div className="an-lbl">Avg duration</div><div className="an-rate">answered calls</div></div>
                            <div className="an-card"><div className="an-num">{ callStats.inbound }↓ / { callStats.outbound }↑</div><div className="an-lbl">In / Out</div></div>
                        </div>
                        { callStats.total > 0 && (
                            <div className="an-bars" style={ { marginTop: '6px' } }>
                                { Object.keys( callStats.byProv ).sort( ( a, b ) => callStats.byProv[ b ].total - callStats.byProv[ a ].total ).map( prov => {
                                    const p = callStats.byProv[ prov ];
                                    const meta = PROV_META[ prov ] || { label: prov.charAt( 0 ).toUpperCase() + prov.slice( 1 ), fg: colors.textMuted };
                                    const pick = p.total > 0 ? Math.round( ( p.answered / p.total ) * 100 ) : 0;
                                    const avg = p.answered > 0 ? Math.round( p.durSum / p.answered ) : 0;
                                    return (
                                        <div key={ prov } className="an-bar-row">
                                            <span className="an-bar-label" style={ { color: meta.fg, fontWeight: 600 } }>{ meta.label }</span>
                                            <div className="an-bar-track"><div className="an-bar-fill" style={ { width: `${( p.total / callStats.total ) * 100}%`, background: meta.fg } } /></div>
                                            <span className="an-bar-val">{ p.total } <span className="an-bar-sub">({ pick }% pickup · { fmtDur( avg ) } avg)</span></span>
                                        </div>
                                    );
                                } ) }
                            </div>
                        ) }
                    </>
                ) }
            </div>
            <style jsx>{ `
                .an-wrap { padding: 20px; max-width: 1000px; margin: 0 auto; }
                .an-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 12px; margin: 14px 0; }
                .an-card { border: 1px solid ${colors.border}; border-radius: 12px; padding: 14px; background: #fff; }
                .an-pill { font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 9999px; }
                .an-num { font-size: 26px; font-weight: 700; color: ${colors.text}; margin-top: 6px; }
                .an-lbl { font-size: 12px; color: ${colors.textMuted}; }
                .an-rate { font-size: 11px; color: ${colors.textSecondary}; margin-top: 4px; }
                .an-section { font-size: 12px; font-weight: 700; text-transform: uppercase; color: ${colors.textMuted}; margin: 22px 0 10px; }
                .an-bars { display: flex; flex-direction: column; gap: 10px; }
                .an-bar-row { display: flex; align-items: center; gap: 12px; }
                .an-bar-label { width: 90px; font-size: 13px; color: ${colors.text}; }
                .an-bar-track { flex: 1; height: 16px; background: ${colors.bgSecondary}; border-radius: 9999px; overflow: hidden; }
                .an-bar-fill { height: 100%; border-radius: 9999px; min-width: 2px; }
                .an-bar-val { font-size: 12px; color: ${colors.text}; white-space: nowrap; }
                .an-bar-sub { color: ${colors.textMuted}; }
                .an-empty { text-align: center; padding: 40px; color: ${colors.textMuted}; }
            ` }</style>
        </>
    );

    if ( embedded ) return content;
    return (
        <Layout user={ user } onSignOut={ signOut }>
            <SEO title="Analytics | WECARE.DIGITAL" description="Cross-channel analytics" noindex={ true } />
            { content }
        </Layout>
    );
};

export default AnalyticsPage;
