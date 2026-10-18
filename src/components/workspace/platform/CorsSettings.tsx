/**
 * CORS Manager (admin)
 * View and control the allowed origins (CORS) on the HTTP APIs without code changes.
 * Backed by waba-management (?action=cors-status / action=cors-apply).
 */
import React, { useState, useEffect, useCallback } from 'react';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import Button from '../../../components/ui/Button';
import { useToastContext } from '../../../contexts/ToastContext';
import * as api from '../../../api/client';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const CorsSettingsPage: React.FC<PageProps> = ( { signOut, user, embedded } ) => {
    const toast = useToastContext();
    const [ loading, setLoading ] = useState( true );
    const [ saving, setSaving ] = useState( false );
    const [ status, setStatus ] = useState<api.CorsStatus | null>( null );
    const [ allowAll, setAllowAll ] = useState( false );
    const [ selected, setSelected ] = useState<string[]>( [] );
    const [ customInput, setCustomInput ] = useState( '' );

    const load = useCallback( async () => {
        setLoading( true );
        try
        {
            const s = await api.getCorsStatus();
            if ( s )
            {
                setStatus( s );
                const first = s.apis?.[ 0 ];
                const isAll = !!first?.allowAll;
                setAllowAll( isAll );
                // Seed selection from the current allowlist (minus '*'), unioned with recommended.
                const current = ( first?.allowOrigins || [] ).filter( o => o !== '*' );
                const seed = Array.from( new Set( [ ...s.coreOrigins, ...current, ...( isAll ? s.recommendedOrigins : [] ) ] ) );
                setSelected( seed );
            }
        } catch ( err: any )
        {
            toast.error( err?.message || 'Failed to load CORS status' );
        } finally
        {
            setLoading( false );
        }
    }, [ toast ] );

    useEffect( () => { load(); }, [ load ] );

    const toggleOrigin = ( o: string ) => {
        if ( status?.coreOrigins.includes( o ) ) return; // core is locked-in
        setSelected( prev => prev.includes( o ) ? prev.filter( x => x !== o ) : [ ...prev, o ] );
    };

    const addCustom = () => {
        const v = customInput.trim();
        if ( !v ) return;
        if ( !/^([a-z]+:\/\/|https?:\/\/)/i.test( v ) ) { toast.error( 'Origin must start with a scheme, e.g. https:// or capacitor://' ); return; }
        if ( !selected.includes( v ) ) setSelected( prev => [ ...prev, v ] );
        setCustomInput( '' );
    };

    const apply = async () => {
        setSaving( true );
        try
        {
            const res = await api.applyCors( allowAll ? { allowAll: true } : { origins: selected } );
            if ( res?.success )
            {
                toast.success( allowAll ? 'CORS set to allow all origins (*)' : `Applied ${res.allowOrigins.length} allowed origins` );
                await load();
            } else
            {
                toast.error( 'Failed to apply CORS (partial or error) — check status below' );
                await load();
            }
        } catch ( err: any )
        {
            toast.error( err?.message || 'Apply failed' );
        } finally
        {
            setSaving( false );
        }
    };

    // Union of recommended + any custom/current already selected, for the checklist.
    const allOrigins = Array.from( new Set( [ ...( status?.recommendedOrigins || [] ), ...selected ] ) );

    const body = (
        <div style={ { padding: 24, maxWidth: 860 } }>
                <h2 style={ { margin: '0 0 6px', color: 'var(--accent)' } }>CORS Manager</h2>
                <p style={ { color: 'var(--text-muted)', fontSize: 14, marginTop: 0 } }>
                    Control which website/app origins may call the APIs. Core origins (dashboard + native app) are always
                    kept so you can never lock yourself out. Use <strong>Allow all</strong> only as a temporary escape hatch.
                </p>

                { loading ? (
                    <div style={ { padding: 40, textAlign: 'center', color: 'var(--text-muted)' } }>Loading…</div>
                ) : (
                    <>
                        {/* Current live status */ }
                        <div style={ { background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, marginBottom: 18 } }>
                            <div style={ { fontWeight: 600, fontSize: 13, marginBottom: 8, color: 'var(--accent)' } }>Live API status</div>
                            { status?.apis?.map( a => (
                                <div key={ a.apiId } style={ { fontSize: 12, color: '#374151', marginBottom: 4 } }>
                                    <strong>{ a.name || a.apiId }</strong>{ ' ' }
                                    { a.error ? <span style={ { color: '#b91c1c' } }>error: { a.error }</span>
                                        : a.allowAll ? <span style={ { color: '#b45309' } }>● allows ALL origins (*)</span>
                                            : <span style={ { color: '#166534' } }>● { ( a.allowOrigins || [] ).length } origins allowed</span> }
                                </div>
                            ) ) }
                        </div>

                        {/* Allow-all toggle */ }
                        <label style={ { display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16, cursor: 'pointer' } }>
                            <input type="checkbox" checked={ allowAll } onChange={ e => setAllowAll( e.target.checked ) } style={ { width: 18, height: 18 } } />
                            <span style={ { fontSize: 14, fontWeight: 600, color: allowAll ? '#b45309' : 'var(--accent)' } }>
                                Allow all origins (*) — permissive, not recommended for production
                            </span>
                        </label>

                        {/* Origin checklist */ }
                        <div style={ { opacity: allowAll ? 0.45 : 1, pointerEvents: allowAll ? 'none' : 'auto' } }>
                            <div style={ { fontWeight: 600, fontSize: 13, marginBottom: 8, color: 'var(--accent)' } }>Allowed origins</div>
                            { allOrigins.map( o => {
                                const core = status?.coreOrigins.includes( o );
                                const on = selected.includes( o );
                                return (
                                    <label key={ o } style={ { display: 'flex', alignItems: 'center', gap: 10, padding: '6px 0', cursor: core ? 'default' : 'pointer' } }>
                                        <input type="checkbox" checked={ on } disabled={ core } onChange={ () => toggleOrigin( o ) } style={ { width: 16, height: 16 } } />
                                        <span style={ { fontSize: 13, fontFamily: 'monospace', color: '#374151' } }>{ o }</span>
                                        { core && <span style={ { fontSize: 10, background: 'var(--accent)', color: '#fff', padding: '1px 6px', borderRadius: 8 } }>core</span> }
                                    </label>
                                );
                            } ) }

                            <div style={ { display: 'flex', gap: 8, marginTop: 12 } }>
                                <input
                                    type="text"
                                    value={ customInput }
                                    onChange={ e => setCustomInput( e.target.value ) }
                                    placeholder="Add custom origin e.g. https://partner.example.com"
                                    style={ { flex: 1, padding: '8px 10px', border: '1px solid #d1d5db', borderRadius: 8, fontSize: 13 } }
                                    onKeyDown={ e => { if ( e.key === 'Enter' ) addCustom(); } }
                                />
                                <Button variant="secondary" size="sm" onClick={ addCustom }>Add</Button>
                            </div>
                        </div>

                        <div style={ { marginTop: 20, display: 'flex', gap: 10, alignItems: 'center' } }>
                            <Button variant="primary" size="md" onClick={ apply } loading={ saving }>Apply to APIs</Button>
                            <Button variant="ghost" size="md" onClick={ load } disabled={ saving }>Reload</Button>
                        </div>
                    </>
                ) }
            </div>
    );

    if ( embedded ) return body;
    return (
        <Layout user={ user } onSignOut={ signOut }>
            <SEO title="CORS Manager" description="Manage allowed origins for the WECARE.DIGITAL APIs" />
            { body }
        </Layout>
    );
};

export default CorsSettingsPage;
