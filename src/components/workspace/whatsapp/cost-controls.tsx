/**
 * Cost Controls (Part 5/6) — shows cost-control feature flags and their effective
 * state, with cost-risk guidance. Read-only view of /wa-business/cost-flags.
 */
import React, { useState, useEffect, useCallback } from 'react';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import { useToastContext } from '../../../contexts/ToastContext';
import * as api from '../../../api/client';
import { FeatureFlagBadge, RiskBadge, CostWarningBanner, LastSyncIndicator, RawJsonDrawer } from '../../../components/wa';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const REQUIRED_SERVICES = [
    'Lambda (Python)', 'DynamoDB (PAY_PER_REQUEST)', 'Cognito', 'S3 (wecare-digital-get)',
    'SQS / DLQ', 'CloudWatch Logs (3-month retention)', 'Critical CloudWatch alarms',
];

const CostControls: React.FC<PageProps> = ( { signOut, user, embedded = false } ) => {
    const toast = useToastContext();
    const [ data, setData ] = useState<api.CostFlagsResponse | null>( null );
    const [ loading, setLoading ] = useState( true );
    const [ syncedAt, setSyncedAt ] = useState<number>( 0 );

    const load = useCallback( async () => {
        setLoading( true );
        try
        {
            const res = await api.getCostFlags();
            setData( res );
            setSyncedAt( Math.floor( Date.now() / 1000 ) );
        } catch ( e: any )
        {
            toast.error( e?.message || 'Failed to load cost flags' );
        } finally { setLoading( false ); }
    }, [ toast ] );

    useEffect( () => { load(); }, [ load ] );

    const flags = data?.flags || {};
    const meta = data?.meta || {};
    const enabledCount = Object.values( flags ).filter( Boolean ).length;

    const content = (
        <div style={ { maxWidth: 860, margin: '0 auto', padding: 16 } }>
            <SEO title="Cost Controls" description="WhatsApp platform AWS cost controls and feature flags." noindex />
            <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 } }>
                <h1 style={ { fontSize: 22, fontWeight: 700 } }>Cost Controls</h1>
                <LastSyncIndicator at={ syncedAt } onSync={ load } syncing={ loading } />
            </div>
            <p style={ { color: '#777', fontSize: 'var(--text-sm)', marginBottom: 16 } }>
                Optional paid AWS services are <strong>off by default</strong> and gated behind feature flags.
                Enable a flag only for a defined need; disable after. See docs/AWS_COST_CONTROL.md.
            </p>

            <CostWarningBanner resource="Optional AWS services" risk="medium">
                { enabledCount === 0
                    ? 'All optional paid services are OFF — lowest cost posture. Nothing extra needs enabling for current features.'
                    : `${enabledCount} optional paid service(s) currently ENABLED — verify they are still needed.` }
            </CostWarningBanner>

            <div style={ { background: '#fff', border: '1px solid #e5e5e5', borderRadius: 8, padding: 16, marginBottom: 16 } }>
                <h3 style={ { marginTop: 0, fontSize: 'var(--text-md)' } }>Always-on (required) services</h3>
                <div style={ { display: 'flex', flexWrap: 'wrap', gap: 8 } }>
                    { REQUIRED_SERVICES.map( s => (
                        <span key={ s } style={ { fontSize: 'var(--text-xs)', background: '#e6f4ea', color: '#1a7a3a', padding: '3px 10px', borderRadius: 999, fontWeight: 600 } }>✓ { s }</span>
                    ) ) }
                </div>
            </div>

            <div style={ { background: '#fff', border: '1px solid #e5e5e5', borderRadius: 8, padding: 16 } }>
                <h3 style={ { marginTop: 0, fontSize: 'var(--text-md)' } }>Optional paid services (feature-flagged)</h3>
                { loading && !data ? <div style={ { color: '#888' } }>Loading…</div> : (
                    <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: 'var(--text-sm)' } }>
                        <thead>
                            <tr style={ { textAlign: 'left', color: '#888', fontSize: 'var(--text-xs)' } }>
                                <th style={ { padding: '6px 4px' } }>Flag</th>
                                <th style={ { padding: '6px 4px' } }>Service</th>
                                <th style={ { padding: '6px 4px' } }>Cost risk</th>
                                <th style={ { padding: '6px 4px' } }>State</th>
                            </tr>
                        </thead>
                        <tbody>
                            { Object.keys( flags ).map( name => (
                                <tr key={ name } style={ { borderTop: '1px solid #f0f0f0' } }>
                                    <td style={ { padding: '8px 4px', fontFamily: 'monospace', fontSize: 'var(--text-xs)' } }>{ name }</td>
                                    <td style={ { padding: '8px 4px' } }>{ meta[ name ]?.service || '—' }</td>
                                    <td style={ { padding: '8px 4px' } }><RiskBadge level={ meta[ name ]?.risk || 'medium' } /></td>
                                    <td style={ { padding: '8px 4px' } }><FeatureFlagBadge name={ name.replace( 'ENABLE_', '' ) } enabled={ !!flags[ name ] } /></td>
                                </tr>
                            ) ) }
                        </tbody>
                    </table>
                ) }
                <p style={ { fontSize: 'var(--text-xs)', color: '#888', marginTop: 12 } }>
                    To enable a flag: set its env var (e.g. <code>ENABLE_CLOUDFRONT=true</code>) in the Amplify backend, or the
                    <code> cost_flags</code> SystemConfig record, then redeploy. There is no WAF flag: AWS WAF was removed from
                    this account on 2026-09-28 as a cost decision, so endpoints are protected by HMAC signature verification
                    and Lambda-side rate limiting only.
                </p>
                <RawJsonDrawer data={ data } label="Raw flags response" />
            </div>
        </div>
    );

    if ( embedded ) return content;
    return <Layout user={ user } onSignOut={ signOut }>{ content }</Layout>;
};

export default CostControls;
