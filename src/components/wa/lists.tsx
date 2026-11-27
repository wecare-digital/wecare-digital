/**
 * Validation error + warning lists (Part 5).
 * Accepts plain strings or Meta-style validation_error objects.
 */
import React from 'react';

type ValErr = string | { message?: string; error_type?: string; line_start?: number; pointers?: any[] };

function fmt ( e: ValErr ): string {
    if ( typeof e === 'string' ) return e;
    const where = e.line_start ? ` (line ${e.line_start})` : '';
    return `${e.error_type ? `[${e.error_type}] ` : ''}${e.message || 'Validation error'}${where}`;
}

export const ValidationErrorList: React.FC<{ errors?: ValErr[]; title?: string }> = ( { errors, title = 'Validation errors' } ) => {
    if ( !errors || errors.length === 0 ) return null;
    return (
        <div style={ { border: '1px solid #d1d5db', background: '#f5f5f5', borderRadius: 8, padding: 12, marginTop: 10 } }>
            <div style={ { fontWeight: 700, color: '#374151', fontSize: 13, marginBottom: 6 } }>⚠ { title } ({ errors.length })</div>
            <ul style={ { margin: 0, paddingLeft: 18 } }>
                { errors.map( ( e, i ) => <li key={ i } style={ { fontSize: 13, color: '#374151', marginBottom: 2 } }>{ fmt( e ) }</li> ) }
            </ul>
        </div>
    );
};

export const WarningList: React.FC<{ warnings?: string[]; title?: string }> = ( { warnings, title = 'Warnings' } ) => {
    if ( !warnings || warnings.length === 0 ) return null;
    return (
        <div style={ { border: '1px solid #f0dca0', background: '#fff9ec', borderRadius: 8, padding: 12, marginTop: 10 } }>
            <div style={ { fontWeight: 700, color: '#9a6300', fontSize: 13, marginBottom: 6 } }>⚠ { title } ({ warnings.length })</div>
            <ul style={ { margin: 0, paddingLeft: 18 } }>
                { warnings.map( ( w, i ) => <li key={ i } style={ { fontSize: 13, color: '#7a5a10', marginBottom: 2 } }>{ w }</li> ) }
            </ul>
        </div>
    );
};
