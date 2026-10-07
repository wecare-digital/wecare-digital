/**
 * DateTimeUnixInput + CurlPreview (Part 5).
 */
import React from 'react';
import { CopyToClipboardButton } from './copy';
import DateTimeField from '../ui/DateTimeField';

// Edits a Unix timestamp (seconds) via a datetime-local control; shows the epoch.
export const DateTimeUnixInput: React.FC<{ value?: number; onChange: ( unixSeconds: number ) => void; label?: string }> = (
    { value, onChange, label = 'Date / time' }
) => {
    const toLocal = ( s?: number ) => {
        if ( !s ) return '';
        const d = new Date( s * 1000 );
        const pad = ( n: number ) => String( n ).padStart( 2, '0' );
        return `${d.getFullYear()}-${pad( d.getMonth() + 1 )}-${pad( d.getDate() )}T${pad( d.getHours() )}:${pad( d.getMinutes() )}`;
    };
    return (
        <div>
            { /* DateTimeField emits exactly the string `datetime-local` did - `YYYY-MM-DDTHH:MM`
                 - so `toLocal`'s output goes straight back in and the Date.parse that converts
                 it to epoch seconds is UNCHANGED, including its NaN guard. The one difference
                 is that the component now also emits '' while either half is unset, which
                 Date.parse rejects, so the guard that was already here covers it. The <label>
                 moves into the component rather than sitting beside an unlabelled control. */ }
            <DateTimeField
                label={ label }
                style={ { fontSize: 12, fontWeight: 600, color: '#444' } }
                value={ toLocal( value ) }
                onChange={ v => { const t = Date.parse( v ); if ( !isNaN( t ) ) onChange( Math.floor( t / 1000 ) ); } }
            />
            { value ? <span style={ { marginInlineStart: 8, fontSize: 12, color: '#888' } }>epoch: { value }</span> : null }
        </div>
    );
};

export interface CurlSpec { method?: string; url: string; headers?: Record<string, string>; body?: any; }

// Builds a copyable cURL command. Secrets are shown as placeholders, never real tokens.
export function buildCurl ( spec: CurlSpec ): string {
    const method = ( spec.method || 'GET' ).toUpperCase();
    const parts = [ `curl -X ${method} '${spec.url}'` ];
    const headers = { Authorization: 'Bearer $ACCESS_TOKEN', 'Content-Type': 'application/json', ...( spec.headers || {} ) };
    for ( const [ k, v ] of Object.entries( headers ) ) parts.push( `  -H '${k}: ${v}'` );
    if ( spec.body !== undefined )
    {
        const b = typeof spec.body === 'string' ? spec.body : JSON.stringify( spec.body );
        parts.push( `  -d '${b}'` );
    }
    return parts.join( ' \\\n' );
}

export const CurlPreview: React.FC<{ spec: CurlSpec }> = ( { spec } ) => {
    const cmd = buildCurl( spec );
    return (
        <div style={ { position: 'relative', marginTop: 8 } }>
            <div style={ { position: 'absolute', top: 6, right: 6 } }><CopyToClipboardButton text={ cmd } /></div>
            <pre style={ { background: '#000', color: '#9cdcfe', padding: 12, borderRadius: 8, fontSize: 12, overflow: 'auto', margin: 0 } }>{ cmd }</pre>
        </div>
    );
};
