/**
 * Flow-specific components (Part 5): health panel, JSON editor with local
 * validation, screen tree, submission timeline, audit trail drawer.
 */
import React, { useMemo, useState } from 'react';
import { HealthStatusBadge } from './badges';
import { JsonViewer } from './json';
import { MaskedPhone } from './masked';

export const FlowHealthPanel: React.FC<{ health?: any; canSend?: boolean }> = ( { health, canSend } ) => {
    const entities = health?.entities || [];
    return (
        <div style={ { border: '1px solid #e5e5e5', borderRadius: 8, padding: 12 } }>
            <div style={ { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 } }>
                <strong style={ { fontSize: 13 } }>Flow health</strong>
                <HealthStatusBadge health={ canSend === false ? 'BLOCKED' : ( health?.can_send_message || 'AVAILABLE' ) } />
            </div>
            { entities.length > 0 ? (
                <ul style={ { margin: 0, paddingLeft: 18 } }>
                    { entities.map( ( e: any, i: number ) => (
                        <li key={ i } style={ { fontSize: 12, color: '#666' } }>{ e.entity_type }: { e.can_send_message }</li>
                    ) ) }
                </ul>
            ) : <div style={ { fontSize: 12, color: '#999' } }>No health detail</div> }
        </div>
    );
};

// JSON editor with client-side parse validation; calls back on valid change.
export const FlowJsonEditor: React.FC<{ value: string; onChange: ( v: string ) => void; onValid?: ( parsed: any ) => void }> = (
    { value, onChange, onValid }
) => {
    const [ error, setError ] = useState<string | null>( null );
    const handle = ( v: string ) => {
        onChange( v );
        try { const p = JSON.parse( v ); setError( null ); onValid?.( p ); }
        catch ( e: any ) { setError( e.message ); }
    };
    return (
        <div>
            <textarea
                value={ value }
                onChange={ e => handle( e.target.value ) }
                spellCheck={ false }
                style={ { width: '100%', minHeight: 240, fontFamily: 'monospace', fontSize: 12, padding: 10, borderRadius: 8, border: '1px solid ' + ( error ? '#d1d5db' : '#d0d0d0' ) } }
                placeholder='{"version":"7.0","screens":[...]}'
            />
            <div style={ { fontSize: 12, color: error ? '#374151' : '#1a7a3a', marginTop: 4 } }>
                { error ? `Invalid JSON: ${error}` : '✓ Valid JSON' }
            </div>
        </div>
    );
};

// Renders the screen list + routing model from a parsed flow JSON.
export const FlowScreenTree: React.FC<{ flowJson?: any }> = ( { flowJson } ) => {
    const screens = useMemo( () => {
        try { const p = typeof flowJson === 'string' ? JSON.parse( flowJson ) : flowJson; return p?.screens || []; }
        catch { return []; }
    }, [ flowJson ] );
    if ( !screens.length ) return <div style={ { fontSize: 12, color: '#999' } }>No screens</div>;
    return (
        <ul style={ { margin: 0, paddingLeft: 16, fontSize: 13 } }>
            { screens.map( ( s: any, i: number ) => (
                <li key={ i } style={ { marginBottom: 4 } }>
                    <strong>{ s.id }</strong>{ s.terminal ? ' (terminal)' : '' }
                    { s.title ? <span style={ { color: '#888' } }> — { s.title }</span> : null }
                </li>
            ) ) }
        </ul>
    );
};

interface FlowLogEntry { action?: string; screen?: string; isError?: boolean; createdAt?: number; phone?: string; }
export const FlowSubmissionTimeline: React.FC<{ logs?: FlowLogEntry[] }> = ( { logs } ) => {
    if ( !logs || !logs.length ) return <div style={ { fontSize: 12, color: '#999' } }>No interactions logged</div>;
    return (
        <div style={ { borderLeft: '2px solid #e5e5e5', paddingLeft: 12 } }>
            { logs.map( ( l, i ) => (
                <div key={ i } style={ { marginBottom: 10, position: 'relative' } }>
                    <div style={ { position: 'absolute', left: -17, top: 4, width: 8, height: 8, borderRadius: 4, background: l.isError ? '#374151' : '#1a7a3a' } } />
                    <div style={ { fontSize: 13, fontWeight: 600 } }>{ l.action }{ l.screen ? ` · ${l.screen}` : '' }</div>
                    <div style={ { fontSize: 11, color: '#888' } }>
                        { l.createdAt ? new Date( l.createdAt * 1000 ).toLocaleString() : '' } { l.phone ? <>· <MaskedPhone value={ l.phone } /></> : null }
                    </div>
                </div>
            ) ) }
        </div>
    );
};

interface AuditEntry { action?: string; actorId?: string; actorType?: string; createdAt?: number; beforeData?: any; afterData?: any; }
export const AuditTrailDrawer: React.FC<{ entries?: AuditEntry[]; defaultOpen?: boolean }> = ( { entries, defaultOpen } ) => {
    const [ open, setOpen ] = useState( !!defaultOpen );
    if ( !entries || !entries.length ) return null;
    return (
        <div style={ { marginTop: 10, border: '1px solid #e5e5e5', borderRadius: 8 } }>
            <button onClick={ () => setOpen( o => !o ) } style={ { width: '100%', textAlign: 'left', padding: '8px 12px', background: '#fafafa', border: 'none', borderRadius: 8, cursor: 'pointer', fontSize: 13, fontWeight: 600, color: '#444' } }>
                { open ? '▾' : '▸' } Audit trail ({ entries.length })
            </button>
            { open && (
                <div style={ { padding: 10 } }>
                    { entries.map( ( e, i ) => (
                        <div key={ i } style={ { marginBottom: 10, borderBottom: '1px solid #f0f0f0', paddingBottom: 8 } }>
                            <div style={ { fontSize: 13, fontWeight: 600 } }>{ e.action } <span style={ { color: '#888', fontWeight: 400 } }>by { e.actorType || 'user' }:{ e.actorId || '—' }</span></div>
                            <div style={ { fontSize: 11, color: '#888' } }>{ e.createdAt ? new Date( e.createdAt * 1000 ).toLocaleString() : '' }</div>
                            { ( e.beforeData || e.afterData ) && <JsonViewer data={ { before: e.beforeData, after: e.afterData } } maxHeight={ 160 } /> }
                        </div>
                    ) ) }
                </div>
            ) }
        </div>
    );
};
