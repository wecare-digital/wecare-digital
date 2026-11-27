/**
 * Cost warning banner + last-sync indicator + feature-flag aware helpers (Part 5/6).
 */
import React from 'react';

// Shown before enabling a paid AWS resource.
export const CostWarningBanner: React.FC<{ resource: string; risk?: 'low' | 'medium' | 'high'; children?: React.ReactNode }> = (
    { resource, risk = 'medium', children }
) => {
    const colors = {
        low: { bg: '#f0f7ff', border: '#cfe2ff', fg: '#1a4a7a' },
        medium: { bg: '#fff9ec', border: '#f0dca0', fg: '#9a6300' },
        high: { bg: '#f5f5f5', border: '#d1d5db', fg: '#374151' },
    }[ risk ];
    return (
        <div style={ { background: colors.bg, border: `1px solid ${colors.border}`, borderRadius: 8, padding: 12, marginBottom: 12 } }>
            <div style={ { fontWeight: 700, color: colors.fg, fontSize: 13 } }>
                💰 Paid resource: { resource } — { risk.toUpperCase() } cost risk
            </div>
            { children && <div style={ { fontSize: 13, color: colors.fg, marginTop: 4 } }>{ children }</div> }
        </div>
    );
};

function timeAgo ( ts?: number | string ): string {
    if ( !ts ) return 'never';
    const t = typeof ts === 'string' ? Date.parse( ts ) : ts * ( ts < 1e12 ? 1000 : 1 );
    if ( isNaN( t ) ) return String( ts );
    const diff = Math.max( 0, Date.now() - t );
    const m = Math.floor( diff / 60000 );
    if ( m < 1 ) return 'just now';
    if ( m < 60 ) return `${m}m ago`;
    const h = Math.floor( m / 60 );
    if ( h < 24 ) return `${h}h ago`;
    return `${Math.floor( h / 24 )}d ago`;
};

export const LastSyncIndicator: React.FC<{ at?: number | string; onSync?: () => void; syncing?: boolean }> = (
    { at, onSync, syncing }
) => (
    <div style={ { display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: '#777' } }>
        <span>Last sync: { timeAgo( at ) }</span>
        { onSync && (
            <button onClick={ onSync } disabled={ syncing } style={ {
                border: '1px solid #d0d0d0', background: '#fff', borderRadius: 6, cursor: 'pointer',
                fontSize: 12, padding: '3px 10px', fontWeight: 600,
            } }>{ syncing ? 'Syncing…' : '↻ Sync' }</button>
        ) }
    </div>
);
