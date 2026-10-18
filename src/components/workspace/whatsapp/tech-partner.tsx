/**
 * Tech Partner Readiness — [retired public path]/whatsapp/tech-partner
 *
 * Live dashboard for the 4 Meta "Upgrade to Tech Partner" eligibility gates:
 *   1. Tech Provider Get Started (done)
 *   2. Phone quality rating >= GREEN on both WABAs
 *   3. >= 2,500 average daily messages over the last 7 days
 *   4. >= 10 active client businesses
 * Backed by POST /meta-agent  action=tp_eligibility (measures against the live
 * Meta Graph API + PartnerWallet). The upgrade submission itself is a manual
 * Meta process (App Dashboard -> Quickstart -> Become a Partner).
 */
import React, { useState, useEffect, useCallback } from 'react';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import Button from '../../../components/ui/Button';
import { aiAgentApi, type TechPartnerReadiness } from '../../../api/client';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const card: React.CSSProperties = { background: '#fff', border: '1px solid #e5e7eb', borderRadius: 10, padding: 18, marginBottom: 14 };

const Badge = ( { ok }: { ok: boolean } ) => (
    <span style={ {
        fontSize: 12, fontWeight: 700, padding: '3px 10px', borderRadius: 999,
        background: ok ? '#ecfdf5' : '#fef2f2', color: ok ? '#047857' : '#b91c1c',
    } }>{ ok ? 'PASS' : 'NOT MET' }</span>
);

function Bar ( { value, target }: { value: number; target: number } ) {
    const pct = Math.max( 2, Math.min( 100, Math.round( ( value / target ) * 100 ) ) );
    const ok = value >= target;
    return (
        <div style={ { background: '#f3f4f6', borderRadius: 999, height: 10, overflow: 'hidden', margin: '8px 0' } }>
            <div style={ { width: `${pct}%`, height: '100%', background: ok ? '#10b981' : '#f59e0b' } } />
        </div>
    );
}

const TechPartnerPage: React.FC<PageProps> = ( { signOut, user, embedded = false } ) => {
    const [ data, setData ] = useState<TechPartnerReadiness | null>( null );
    const [ loading, setLoading ] = useState( false );

    const load = useCallback( async () => {
        setLoading( true );
        try { setData( await aiAgentApi.techPartnerReadiness() ); }
        finally { setLoading( false ); }
    }, [] );

    useEffect( () => { load(); }, [ load ] );

    const g = data?.gates;

    const body = (
        <div style={ { maxWidth: 900, margin: '0 auto', padding: embedded ? 0 : 20 } }>
            <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10 } }>
                <div>
                    <h1 style={ { fontSize: 22, fontWeight: 800, margin: 0 } }>Tech Partner Readiness</h1>
                    <p style={ { color: '#6b7280', fontSize: 14, margin: '4px 0 0' } }>
                        Live check of the four Meta eligibility gates for upgrading from Tech Provider to Tech Partner.
                    </p>
                </div>
                <Button onClick={ load } disabled={ loading }>{ loading ? 'Checking…' : 'Re-check' }</Button>
            </div>

            {/* Overall */ }
            <div style={ { ...card, marginTop: 14, borderColor: data?.eligible ? '#a7f3d0' : '#fde68a', background: data?.eligible ? '#ecfdf5' : '#fffbeb' } }>
                <div style={ { display: 'flex', alignItems: 'center', gap: 12 } }>
                    <span style={ { fontSize: 28 } }>{ data?.eligible ? '✅' : '⏳' }</span>
                    <div>
                        <b style={ { fontSize: 16 } }>{ data?.eligible ? 'Eligible — you can start the upgrade flow.' : 'Not eligible yet' }</b>
                        <div style={ { fontSize: 13, color: '#6b7280' } }>
                            { data ? `${Object.values( data.gates ).filter( x => x.pass ).length} of 4 gates met` : 'Loading…' }
                            { data?.checkedAt ? ` · checked ${new Date( data.checkedAt * 1000 ).toLocaleString()}` : '' }
                        </div>
                    </div>
                </div>
            </div>

            {/* Gate 1 — provider */ }
            <div style={ card }>
                <div style={ { display: 'flex', justifyContent: 'space-between' } }>
                    <b>1 · { g?.provider.label || 'Tech Provider Get Started' }</b>
                    { g && <Badge ok={ g.provider.pass } /> }
                </div>
                <p style={ { fontSize: 13, color: '#6b7280', margin: '6px 0 0' } }>{ g?.provider.detail }</p>
            </div>

            {/* Gate 2 — quality */ }
            <div style={ card }>
                <div style={ { display: 'flex', justifyContent: 'space-between' } }>
                    <b>2 · { g?.quality.label || 'Phone quality rating' }</b>
                    { g && <Badge ok={ g.quality.pass } /> }
                </div>
                <div style={ { display: 'flex', gap: 20, marginTop: 8, flexWrap: 'wrap' } }>
                    { g && Object.entries( g.quality.byWaba ).map( ( [ name, q ] ) => (
                        <div key={ name } style={ { fontSize: 13 } }>
                            <div style={ { color: '#6b7280' } }>{ name } · { q.phone }</div>
                            <div style={ { fontWeight: 700, color: q.ok ? '#047857' : '#b91c1c' } }>{ q.rating || '—' } <span style={ { fontWeight: 400, color: '#9ca3af' } }>({ q.status })</span></div>
                        </div>
                    ) ) }
                </div>
            </div>

            {/* Gate 3 — volume */ }
            <div style={ card }>
                <div style={ { display: 'flex', justifyContent: 'space-between' } }>
                    <b>3 · { g?.volume.label || 'Message volume' }</b>
                    { g && <Badge ok={ g.volume.pass } /> }
                </div>
                { g && <>
                    <div style={ { fontSize: 13, color: '#374151', marginTop: 6 } }>
                        <b style={ { fontSize: 18 } }>{ g.volume.avgPerDay.toLocaleString() }</b> avg messages/day
                        <span style={ { color: '#9ca3af' } }> / target { g.volume.threshold.toLocaleString() }</span>
                    </div>
                    <Bar value={ g.volume.avgPerDay } target={ g.volume.threshold } />
                    <div style={ { fontSize: 12, color: '#6b7280' } }>
                        7-day total { g.volume.total7d.toLocaleString() } ·
                        { Object.entries( g.volume.byWaba ).map( ( [ n, v ] ) => ` ${n}: ${v.total7d}` ).join( ' ·' ) }
                    </div>
                </> }
            </div>

            {/* Gate 4 — clients */ }
            <div style={ card }>
                <div style={ { display: 'flex', justifyContent: 'space-between' } }>
                    <b>4 · { g?.clients.label || 'Active client businesses' }</b>
                    { g && <Badge ok={ g.clients.pass } /> }
                </div>
                { g && <>
                    <div style={ { fontSize: 13, color: '#374151', marginTop: 6 } }>
                        <b style={ { fontSize: 18 } }>{ g.clients.active }</b> onboarded client{ g.clients.active === 1 ? '' : 's' }
                        <span style={ { color: '#9ca3af' } }> / target { g.clients.threshold }</span>
                    </div>
                    <Bar value={ g.clients.active } target={ g.clients.threshold } />
                    { g.clients.error && <div style={ { fontSize: 12, color: '#b45309' } }>Note: { g.clients.error }</div> }
                    <div style={ { fontSize: 12, color: '#6b7280' } }>
                        Meta counts <b>client</b> WhatsApp Business Accounts shared to your app — not your own owned
                        numbers ({ g.clients.ownedWabas ?? 0 } owned).
                        { ( g.clients.testCount ?? 0 ) > 0 ? ` ${g.clients.testCount} test WABA(s) excluded.` : '' }
                    </div>
                    { ( g.clients.clientList?.length ?? 0 ) > 0 && (
                        <div style={ { marginTop: 6 } }>
                            { g.clients.clientList!.map( c => (
                                <div key={ c.id } style={ { fontSize: 12, color: c.isTest ? '#9ca3af' : '#374151' } }>
                                    • { c.name } <span style={ { color: '#9ca3af' } }>({ c.id }){ c.isTest ? ' — test, not counted' : '' }</span>
                                </div>
                            ) ) }
                        </div>
                    ) }
                    <div style={ { fontSize: 12, color: '#6b7280', marginTop: 6 } }>
                        To grow this, onboard external businesses through Embedded Signup
                        (DM → WhatsApp → Connect WABA). Each becomes a client WABA.
                    </div>
                </> }
            </div>

            <div style={ { fontSize: 12, color: '#9ca3af', marginTop: 4 } }>
                When all four gates are green, start the upgrade in the App Dashboard → WhatsApp → Quickstart →
                “Become a Partner”. The submission and Meta Business Partner review is a manual, multi-week process.
            </div>
        </div>
    );

    if ( embedded ) return body;
    return (
        <Layout onSignOut={ signOut } user={ user }>
            <SEO title="Tech Partner Readiness | WECARE.DIGITAL" description="Live check of Meta Tech Partner upgrade eligibility gates" noindex />
            { body }
        </Layout>
    );
};

export default TechPartnerPage;
