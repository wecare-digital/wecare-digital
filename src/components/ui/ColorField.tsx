/**
 * ColorField - a palette swatch grid plus a hex field, in a Popover.
 *
 * IT EMITS AND ACCEPTS `#rrggbb` LOWERCASE, identical to a native colour input's `.value`, so
 * AppBuilderTab's `appConfig.primaryColor`, `accentColor` and `splashBg` are unchanged and the
 * text input beside each one keeps round-tripping the same string.
 *
 * ===========================================================================================
 * THIS REDUCES CAPABILITY, IT IS ACCEPTED, AND IT IS WRITTEN HERE SO IT STAYS A DECISION
 * RATHER THAN BECOMING A DISCOVERY. (design.md section 5.5 and open question Q4.)
 *
 * The native control opens the OS colour picker: an HSV area, an eyedropper on most platforms,
 * and recent-colour memory. None of that is reachable from CSS, which is the whole reason
 * Layer 2 exists - and none of it is rebuilt here. What this component offers instead is the
 * design palette already exported as `colors` from src/lib/design-tokens.ts, plus a hex field.
 *
 * So: AN ARBITRARY COLOUR OUTSIDE THE PALETTE IS REACHABLE ONLY BY TYPING ITS HEX. There is no
 * eyedropper and no HSV area. For a BRAND-colour picker that is arguably the correct product
 * decision - the three call sites choose an app's primary, accent and splash colours, and a
 * palette makes the house tokens the obvious answer - but it is a reduction either way, and a
 * full HSV panel is a large build for three call sites.
 * ===========================================================================================
 *
 * COLOUR IS NEVER THE ONLY INDICATOR. The chosen swatch carries a visible check mark as well as
 * a ring, each swatch's accessible name is its TOKEN name rather than its hex, and the trigger
 * shows the hex as text beside the preview. A grid where "which one is picked" is conveyed by a
 * tint alone fails for a low-vision or colour-blind operator - on a control whose entire
 * subject is colour.
 *
 * ARIA: `role="radiogroup"` with `role="radio"` swatches and `aria-checked`, arrow-key
 * navigation and a roving tabindex. A radiogroup rather than a listbox because exactly one
 * value is chosen and the group is two-dimensional.
 */
import React, { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';

import Popover, { type PopoverDismissReason, type PopoverLayer } from './Popover';
import { useSyncedDraft } from './useSyncedDraft';
import { colors } from '../../lib/design-tokens';

type ColorFieldBaseProps = {
    /** `#rrggbb`. Controlled. */
    value: string;
    /** The bare lowercase `#rrggbb`, never an event. */
    onChange: ( hex: string ) => void;
    id?: string;
    name?: string;
    disabled?: boolean;
    required?: boolean;
    invalid?: boolean;
    describedBy?: string;
    className?: string;
    /** Layout only. */
    style?: React.CSSProperties;
    layer?: PopoverLayer;
};

type ColorFieldLabelling =
    | { label: string; ariaLabel?: string; labelledBy?: undefined }
    | { label?: undefined; ariaLabel: string; labelledBy?: undefined }
    | { label?: undefined; ariaLabel?: undefined; labelledBy: string };

export type ColorFieldProps = ColorFieldBaseProps & ColorFieldLabelling;

/** Six hex digits, with or without the hash. Validated on blur and on Enter, never per key. */
const HEX_RE = /^#?[0-9a-f]{6}$/i;

/** How many swatches a row holds. ArrowDown/ArrowUp move by this, which is why it is named. */
const COLUMNS = 5;

export type ColorSwatch = { token: string; hex: string };

/**
 * The palette, derived from `colors` rather than retyped: a second list would drift from the
 * tokens the rest of the app draws with, and no new hex may be introduced here
 * (grahak-os-design.md). The `rgba()` entries are skipped because a colour input cannot carry
 * alpha, and duplicate hexes are collapsed to their first token so two radios cannot report
 * `aria-checked` for one value.
 */
export const PALETTE: ColorSwatch[] = ( () => {
    const seen = new Set<string>();
    const out: ColorSwatch[] = [];
    for ( const [ token, raw ] of Object.entries( colors ) ) {
        if ( !/^#[0-9a-f]{6}$/i.test( raw ) ) continue;
        const hex = raw.toLowerCase();
        if ( seen.has( hex ) ) continue;
        seen.add( hex );
        out.push( { token, hex } );
    }
    return out;
} )();

/** `primaryHover` -> `primary hover`, so the accessible name reads as words. */
function humanise ( token: string ): string {
    return token.replace( /([a-z])([A-Z0-9])/g, '$1 $2' ).toLowerCase();
}

export function normaliseHex ( text: string ): string | null {
    const trimmed = text.trim();
    if ( !HEX_RE.test( trimmed ) ) return null;
    return `#${ trimmed.replace( /^#/, '' ).toLowerCase() }`;
}

const ColorField: React.FC<ColorFieldProps> = ( {
    value,
    onChange,
    id,
    name,
    label,
    ariaLabel,
    labelledBy,
    disabled = false,
    required = false,
    invalid = false,
    describedBy,
    className,
    style,
    layer = 'default',
} ) => {
    const uid = useId().replace( /[^A-Za-z0-9_-]/g, '' );
    const labelId = `ui-color-${ uid }-label`;
    const hexId = `ui-color-${ uid }-hex`;

    const [ open, setOpen ] = useState( false );
    /** See useSyncedDraft: `#d1f4` on the way to `#d1f470` is a draft, not a value. */
    const [ hexText, setHexText ] = useSyncedDraft( value, v => v );
    const [ activeIndex, setActiveIndex ] = useState( 0 );

    const triggerRef = useRef<HTMLButtonElement>( null );
    const gridRef = useRef<HTMLDivElement>( null );

    const normalised = useMemo( () => normaliseHex( value ) ?? '', [ value ] );
    const selectedIndex = useMemo(
        () => PALETTE.findIndex( swatch => swatch.hex === normalised ),
        [ normalised ]
    );

    const ariaLabelledBy = ariaLabel
        ? undefined
        : ( labelledBy ?? ( label ? labelId : undefined ) );

    const commit = useCallback( ( hex: string ) => {
        if ( hex !== value ) onChange( hex );
    }, [ onChange, value ] );

    /** Valid and normalised -> emit. Anything else -> revert to the last valid value. */
    const commitHexText = useCallback( () => {
        const hex = normaliseHex( hexText );
        if ( hex ) { commit( hex ); setHexText( hex ); return; }
        setHexText( value );
        // `setHexText` is a stable useState setter, but it arrives through a tuple from
        // useSyncedDraft, so the lint cannot prove that. Listed rather than suppressed.
    }, [ hexText, value, commit, setHexText ] );

    const openPanel = useCallback( () => {
        if ( disabled ) return;
        setActiveIndex( selectedIndex >= 0 ? selectedIndex : 0 );
        setOpen( true );
    }, [ disabled, selectedIndex ] );

    const onDismiss = useCallback( ( _reason: PopoverDismissReason ) => { setOpen( false ); }, [] );

    /** Roving focus, so the arrow keys land somewhere visible the moment the grid opens. */
    useEffect( () => {
        if ( !open ) return;
        const swatch = gridRef.current?.querySelector<HTMLButtonElement>( '.ui-color-swatch[tabindex="0"]' );
        swatch?.focus();
    }, [ open, activeIndex ] );

    /**
     * Arrow keys MOVE AND CHECK, which is the radiogroup convention and gives a live preview
     * while the panel is open. Enter / Space closes; a click both checks and closes.
     */
    const onGridKeyDown = useCallback( ( e: React.KeyboardEvent<HTMLDivElement> ) => {
        const last = PALETTE.length - 1;
        let next = activeIndex;
        switch ( e.key ) {
            case 'ArrowRight': next = Math.min( last, activeIndex + 1 ); break;
            case 'ArrowLeft': next = Math.max( 0, activeIndex - 1 ); break;
            case 'ArrowDown': next = Math.min( last, activeIndex + COLUMNS ); break;
            case 'ArrowUp': next = Math.max( 0, activeIndex - COLUMNS ); break;
            case 'Home': next = 0; break;
            case 'End': next = last; break;
            case 'Enter':
            case ' ':
            case 'Spacebar':
                e.preventDefault();
                commit( PALETTE[ activeIndex ].hex );
                setOpen( false );
                triggerRef.current?.focus();
                return;
            default: return;
        }
        e.preventDefault();
        setActiveIndex( next );
        commit( PALETTE[ next ].hex );
    }, [ activeIndex, commit ] );

    return (
        <div className={ [ 'ui-field', className ].filter( Boolean ).join( ' ' ) } style={ style }>
            { label !== undefined && (
                <span
                    className="ui-field-label"
                    id={ ariaLabel ? undefined : labelId }
                    onClick={ () => ( open ? setOpen( false ) : openPanel() ) }
                >
                    { label }
                </span>
            ) }

            <button
                ref={ triggerRef }
                type="button"
                id={ id }
                className="ui-color-trigger"
                aria-haspopup="dialog"
                aria-expanded={ open }
                aria-label={ ariaLabel }
                aria-labelledby={ ariaLabelledBy }
                aria-describedby={ describedBy }
                /*
                 * NO aria-invalid AND NO aria-required: this trigger is a plain button that
                 * opens a dialog, and role="button" supports neither. Select's trigger can
                 * carry them because it is a role="combobox", which does. `invalid` is
                 * therefore surfaced VISUALLY through data-invalid, which form-controls.css
                 * turns into the same --danger border every other control uses. No call site
                 * sets either prop today.
                 */
                data-invalid={ invalid || undefined }
                data-required={ required || undefined }
                disabled={ disabled }
                onClick={ () => ( open ? setOpen( false ) : openPanel() ) }
            >
                { /* The preview is the ONE place a raw colour is written from TSX, and it has to
                     be: the value is runtime data, not a token. */ }
                <span className="ui-color-preview" aria-hidden="true" style={ { backgroundColor: normalised || 'transparent' } } />
                <span className="ui-color-value">{ normalised || value }</span>
            </button>

            { name !== undefined && <input type="hidden" name={ name } value={ value } /> }

            <Popover
                open={ open }
                anchorRef={ triggerRef }
                onDismiss={ onDismiss }
                matchAnchorWidth={ false }
                maxHeight={ 360 }
                layer={ layer }
                className="ui-color-popover"
            >
                <div role="dialog" aria-label="Choose colour" className="ui-color-panel">
                    <div
                        ref={ gridRef }
                        role="radiogroup"
                        aria-label="Palette"
                        className="ui-color-grid"
                        onKeyDown={ onGridKeyDown }
                    >
                        { PALETTE.map( ( swatch, index ) => (
                            <button
                                key={ swatch.hex }
                                type="button"
                                role="radio"
                                className="ui-color-swatch"
                                aria-label={ humanise( swatch.token ) }
                                aria-checked={ swatch.hex === normalised }
                                tabIndex={ index === activeIndex ? 0 : -1 }
                                data-checked={ swatch.hex === normalised ? 'true' : undefined }
                                style={ { backgroundColor: swatch.hex } }
                                onClick={ () => {
                                    setActiveIndex( index );
                                    commit( swatch.hex );
                                    setOpen( false );
                                    triggerRef.current?.focus();
                                } }
                            >
                                { /* The second indicator. A check mark, not a tint. */ }
                                <span className="ui-color-check" aria-hidden="true" />
                            </button>
                        ) ) }
                    </div>

                    <div className="ui-color-hex">
                        <label className="ui-color-hex-label" htmlFor={ hexId }>Hex</label>
                        <input
                            type="text"
                            id={ hexId }
                            className="ui-color-hex-input"
                            value={ hexText }
                            spellCheck={ false }
                            autoComplete="off"
                            inputMode="text"
                            placeholder="#rrggbb"
                            onChange={ e => setHexText( e.target.value ) }
                            onBlur={ commitHexText }
                            onKeyDown={ e => {
                                if ( e.key === 'Enter' ) { e.preventDefault(); commitHexText(); }
                            } }
                        />
                    </div>
                </div>
            </Popover>
        </div>
    );
};

export default ColorField;
