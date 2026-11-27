/**
 * Status / quality / health / risk / feature-flag badges (Part 5).
 * Small presentational pills with consistent theming.
 */
import React from 'react';

const base: React.CSSProperties = {
    display: 'inline-flex', alignItems: 'center', gap: 4,
    padding: '2px 8px', borderRadius: 999, fontSize: 11, fontWeight: 700,
    lineHeight: 1.6, whiteSpace: 'nowrap',
};

function pill ( bg: string, fg: string, text: string, title?: string ) {
    return <span style={ { ...base, background: bg, color: fg } } title={ title }>{ text }</span>;
}

// Generic status (template/flow lifecycle)
export const StatusBadge: React.FC<{ status?: string }> = ( { status } ) => {
    const s = ( status || 'UNKNOWN' ).toUpperCase();
    const map: Record<string, [ string, string ]> = {
        APPROVED: [ '#e6f4ea', '#1a7a3a' ], PUBLISHED: [ '#e6f4ea', '#1a7a3a' ], ACTIVE: [ '#e6f4ea', '#1a7a3a' ],
        PENDING: [ '#fff4e0', '#9a6300' ], IN_REVIEW: [ '#fff4e0', '#9a6300' ], DRAFT: [ '#eef0f2', '#555' ],
        REJECTED: [ '#f5f5f5', '#374151' ], DISABLED: [ '#f5f5f5', '#374151' ], BLOCKED: [ '#f5f5f5', '#374151' ],
        DEPRECATED: [ '#f0e6f4', '#6b3a8a' ], PAUSED: [ '#fff4e0', '#9a6300' ],
    };
    const [ bg, fg ] = map[ s ] || [ '#eef0f2', '#555' ];
    return pill( bg, fg, s );
};

// Meta quality rating (GREEN/YELLOW/RED)
export const QualityBadge: React.FC<{ score?: string }> = ( { score } ) => {
    const s = ( score || 'UNKNOWN' ).toUpperCase();
    const map: Record<string, [ string, string ]> = {
        GREEN: [ '#e6f4ea', '#1a7a3a' ], HIGH: [ '#e6f4ea', '#1a7a3a' ],
        YELLOW: [ '#fff4e0', '#9a6300' ], MEDIUM: [ '#fff4e0', '#9a6300' ],
        RED: [ '#f5f5f5', '#374151' ], LOW: [ '#f5f5f5', '#374151' ],
    };
    const [ bg, fg ] = map[ s ] || [ '#eef0f2', '#555' ];
    return pill( bg, fg, `Quality: ${s}` );
};

// Flow health (AVAILABLE / LIMITED / BLOCKED)
export const HealthStatusBadge: React.FC<{ health?: string }> = ( { health } ) => {
    const s = ( health || 'UNKNOWN' ).toUpperCase();
    const map: Record<string, [ string, string ]> = {
        AVAILABLE: [ '#e6f4ea', '#1a7a3a' ], LIMITED: [ '#fff4e0', '#9a6300' ], BLOCKED: [ '#f5f5f5', '#374151' ],
    };
    const [ bg, fg ] = map[ s ] || [ '#eef0f2', '#555' ];
    return pill( bg, fg, `Health: ${s}` );
};

// Generic risk level (low/medium/high/critical)
export const RiskBadge: React.FC<{ level?: string }> = ( { level } ) => {
    const s = ( level || 'low' ).toLowerCase();
    const map: Record<string, [ string, string ]> = {
        low: [ '#e6f4ea', '#1a7a3a' ], medium: [ '#fff4e0', '#9a6300' ],
        high: [ '#f5f5f5', '#374151' ], critical: [ '#374151', '#fff' ],
    };
    const [ bg, fg ] = map[ s ] || [ '#eef0f2', '#555' ];
    return pill( bg, fg, `${s.toUpperCase()} risk` );
};

// Feature-flag on/off badge
export const FeatureFlagBadge: React.FC<{ name: string; enabled: boolean }> = ( { name, enabled } ) => (
    pill( enabled ? '#e6f4ea' : '#eef0f2', enabled ? '#1a7a3a' : '#888', `${name}: ${enabled ? 'ON' : 'OFF'}` )
);
