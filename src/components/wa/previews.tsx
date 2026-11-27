/**
 * Template + WhatsApp chat preview cards (Part 5).
 */
import React, { useState, useEffect } from 'react';

const bubble: React.CSSProperties = {
    background: '#fff', borderRadius: 8, padding: '8px 10px', maxWidth: 320,
    boxShadow: '0 1px 1px rgba(0,0,0,0.12)', fontSize: 14, lineHeight: 1.4, whiteSpace: 'pre-wrap',
};
const chatBg: React.CSSProperties = { background: '#e5ddd5', padding: 16, borderRadius: 10 };

// Renders a sample message inside a WhatsApp-like chat bubble.
export const WhatsAppChatPreview: React.FC<{ header?: React.ReactNode; body?: string; footer?: string; buttons?: string[] }> = (
    { header, body, footer, buttons }
) => (
    <div style={ chatBg }>
        <div style={ bubble }>
            { header && <div style={ { fontWeight: 700, marginBottom: 4 } }>{ header }</div> }
            { body && <div>{ body }</div> }
            { footer && <div style={ { color: '#888', fontSize: 12, marginTop: 4 } }>{ footer }</div> }
            { buttons && buttons.length > 0 && (
                <div style={ { borderTop: '1px solid #eee', marginTop: 8, paddingTop: 6 } }>
                    { buttons.map( ( b, i ) => (
                        <div key={ i } style={ { color: '#1a73e8', textAlign: 'center', padding: '6px 0', fontSize: 14, fontWeight: 600, borderTop: i ? '1px solid #f0f0f0' : 'none' } }>{ b }</div>
                    ) ) }
                </div>
            ) }
        </div>
    </div>
);

interface TemplateComponent { type?: string; format?: string; text?: string; buttons?: { type?: string; text?: string }[]; }

// Parses a Meta template definition into a chat preview.
export const TemplatePreviewCard: React.FC<{ template?: { components?: TemplateComponent[]; name?: string; category?: string } }> = (
    { template }
) => {
    if ( !template?.components ) return <div style={ { color: '#999', fontSize: 13 } }>No template to preview</div>;
    let header: React.ReactNode = null, body = '', footer = '';
    let buttons: string[] = [];
    for ( const c of template.components )
    {
        const t = ( c.type || '' ).toUpperCase();
        if ( t === 'HEADER' ) header = ( c.format || 'TEXT' ) === 'TEXT' ? c.text : `[${c.format} header]`;
        else if ( t === 'BODY' ) body = c.text || '';
        else if ( t === 'FOOTER' ) footer = c.text || '';
        else if ( t === 'BUTTONS' ) buttons = ( c.buttons || [] ).map( b => b.text || b.type || 'Button' );
    }
    return (
        <div>
            <div style={ { fontSize: 12, color: '#888', marginBottom: 6 } }>{ template.name } · { template.category }</div>
            <WhatsAppChatPreview header={ header } body={ body } footer={ footer } buttons={ buttons } />
        </div>
    );
};

// Compact flow summary card.
export const FlowPreviewCard: React.FC<{ flow?: { id?: string; name?: string; status?: string; previewUrl?: string; previewExpiresAt?: number } }> = (
    { flow }
) => {
    // The clock is read in an effect, not during render: this component is prerendered by the
    // static export, so a render-time Date.now() would bake the build timestamp into the HTML and
    // then mismatch on hydration — and a preview that expired after the build would still render
    // as valid. Hooks sit above the `!flow` early return because they cannot be called
    // conditionally. First tick via requestAnimationFrame rather than a direct call, matching
    // ContactLocation.tsx: setNow( ... ) in the effect body is a synchronous setState in an
    // effect, which is its own lint error.
    const [ now, setNow ] = useState( 0 );
    useEffect( () => {
        const raf = requestAnimationFrame( () => setNow( Date.now() ) );
        return () => cancelAnimationFrame( raf );
    }, [] );
    if ( !flow ) return null;
    const expired = flow.previewExpiresAt ? flow.previewExpiresAt * 1000 < now : false;
    return (
        <div style={ { border: '1px solid #e5e5e5', borderRadius: 8, padding: 12 } }>
            <div style={ { fontWeight: 700, fontSize: 14 } }>{ flow.name || flow.id }</div>
            <div style={ { fontSize: 12, color: '#888', marginBottom: 8 } }>{ flow.status }</div>
            { flow.previewUrl ? (
                <div>
                    <a href={ flow.previewUrl } target="_blank" rel="noreferrer" style={ { color: '#1a73e8', fontSize: 13 } }>Open preview ↗</a>
                    <span style={ { fontSize: 12, color: expired ? '#374151' : '#888', marginLeft: 8 } }>{ expired ? 'Preview expired — regenerate' : 'Preview valid' }</span>
                </div>
            ) : <div style={ { fontSize: 12, color: '#999' } }>No preview generated</div> }
        </div>
    );
};
