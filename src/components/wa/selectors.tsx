/**
 * WABA / phone / graph-version / field selectors (Part 5).
 */
import React from 'react';
import { WHATSAPP_PHONES } from '../../config/constants';
import Select, { type SelectOption } from '../ui/Select';

/* `sel` is gone with the native controls - it only ever skinned those three. */
const lbl: React.CSSProperties = { fontSize: 12, fontWeight: 600, color: '#444', marginBottom: 4, display: 'block' };

export interface WabaOption { wabaId: string; name: string; display?: string; metaPhoneId?: string; }

export const WABA_OPTIONS: WabaOption[] = [
    { wabaId: WHATSAPP_PHONES.primary.wabaId, name: WHATSAPP_PHONES.primary.name, display: WHATSAPP_PHONES.primary.display, metaPhoneId: WHATSAPP_PHONES.primary.metaPhoneId },
    { wabaId: WHATSAPP_PHONES.secondary.wabaId, name: WHATSAPP_PHONES.secondary.name, display: WHATSAPP_PHONES.secondary.display, metaPhoneId: WHATSAPP_PHONES.secondary.metaPhoneId },
];

/*
 * The three option lists, derived from the sources above so nothing can drift.
 *
 * All three keep their `lbl` caption and take `ariaLabel` rather than Select's own `label`
 * prop, and the reason is in this file rather than in the batch note: FieldSelector below
 * renders the SAME caption and is not a select, so it cannot move. Converting the other
 * three to `.ui-field-label`'s type would leave four captions in one form at two different
 * sizes and weights. The caption was never an accessible name - it has no `for` and wraps
 * nothing - so passing the prop's text as `ariaLabel` adds a name where there was none and
 * changes nothing on screen.
 */
const WABA_SELECT_OPTIONS: SelectOption[] = WABA_OPTIONS.map(
    o => ( { value: o.wabaId, label: o.name } )
);
const PHONE_SELECT_OPTIONS: SelectOption[] = WABA_OPTIONS.map(
    o => ( { value: o.metaPhoneId ?? '', label: `${ o.name } — ${ o.display }` } )
);

export const WabaSelector: React.FC<{ value: string; onChange: ( wabaId: string ) => void; label?: string }> = (
    { value, onChange, label = 'WABA' }
) => (
    <div>
        <label style={ lbl }>{ label }</label>
        <Select ariaLabel={ label } value={ value } onChange={ v => onChange( v ) }
            options={ WABA_SELECT_OPTIONS } />
    </div>
);

export const PhoneNumberSelector: React.FC<{ value: string; onChange: ( metaPhoneId: string ) => void; label?: string }> = (
    { value, onChange, label = 'Phone number' }
) => (
    <div>
        <label style={ lbl }>{ label }</label>
        <Select ariaLabel={ label } value={ value } onChange={ v => onChange( v ) }
            options={ PHONE_SELECT_OPTIONS } />
    </div>
);

const GRAPH_VERSIONS = [ 'v25.0', 'v24.0', 'v23.0', 'v22.0', 'v21.0', 'v20.0' ];
const GRAPH_VERSION_OPTIONS: SelectOption[] = GRAPH_VERSIONS.map( v => ( { value: v, label: v } ) );
export const GraphVersionSelector: React.FC<{ value: string; onChange: ( v: string ) => void; label?: string }> = (
    { value, onChange, label = 'Graph API version' }
) => (
    <div>
        <label style={ lbl }>{ label }</label>
        <Select ariaLabel={ label } value={ value } onChange={ v => onChange( v ) }
            options={ GRAPH_VERSION_OPTIONS } />
    </div>
);

// Multi-select field picker (e.g. Graph API ?fields=).
export const FieldSelector: React.FC<{ options: string[]; selected: string[]; onChange: ( fields: string[] ) => void; label?: string }> = (
    { options, selected, onChange, label = 'Fields' }
) => {
    const toggle = ( f: string ) => onChange( selected.includes( f ) ? selected.filter( x => x !== f ) : [ ...selected, f ] );
    return (
        <div>
            <label style={ lbl }>{ label }</label>
            <div style={ { display: 'flex', flexWrap: 'wrap', gap: 6 } }>
                { options.map( f => (
                    <button key={ f } onClick={ () => toggle( f ) } style={ {
                        padding: '3px 10px', borderRadius: 999, fontSize: 12, cursor: 'pointer', fontWeight: 600,
                        border: '1px solid ' + ( selected.includes( f ) ? '#1a3a2a' : '#d0d0d0' ),
                        background: selected.includes( f ) ? '#1a3a2a' : '#fff',
                        color: selected.includes( f ) ? '#d1f470' : '#555',
                    } }>{ f }</button>
                ) ) }
            </div>
        </div>
    );
};
