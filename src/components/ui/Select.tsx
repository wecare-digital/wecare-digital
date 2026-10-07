/**
 * Select - our own select-only combobox, so the OPEN menu is ours too.
 *
 * Layer 1 skinned the closed state of a native `<select>`; the open list stays OS-drawn and
 * cannot be reached from CSS. This is the replacement. It is a trigger plus a portalled
 * listbox, and it keeps the native control's VALUE CONTRACT and KEYBOARD exactly, so muscle
 * memory and every call site's state shape survive.
 *
 * LABELLING IS "AT LEAST ONE OF THREE", AND `label` + `ariaLabel` IS EXPLICITLY LEGAL.
 * A one-of-three discriminated union was specified first and it cannot express a real call
 * site: src/pages/cart.tsx:1720-1727 renders a visible "Choose option" span - the same four
 * words on every cart row - with a PER-ITEM `aria-label` of "Choose option for <name>", and
 * src/test/CartCheckout.test.tsx:506 resolves the control by exactly that per-item name.
 * Forcing that site to drop one of the two would break the test standing in front of a
 * wrong-amount order. So the type is a union of three variants, each REQUIRING one labelling
 * prop, with `ariaLabel` optional in the `label` variant: an unlabelled combobox cannot
 * compile, and a dual-labelled one can.
 *
 * WHEN BOTH ARE PASSED, `aria-label` IS EMITTED AND `aria-labelledby` IS NOT. ARIA name
 * computation puts `aria-labelledby` ABOVE `aria-label`, so emitting both would let the
 * visible span win and the per-item name would be lost - silently, with everything still
 * rendering. The visible span still renders and still opens the menu on click; in that
 * combination it is presentational and carries no id.
 *
 * THE UNSUPPORTED SHAPE, written here because it is the shape all ELEVEN id-carrying selects
 * use today: an external `<label htmlFor={id}>` left in place, `id` passed, and NO labelling
 * prop. Per HTML-AAM a `<button>`'s accessible name comes from its CONTENTS - an external
 * `<label for>` is not a name source for a button the way it is for a `<select>` - so such a
 * site renders a combobox whose only accessible name is its current value: "WhatsApp",
 * "Paid", "Unassigned". It compiles, it renders, it passes every existing test, and it is
 * broken for a screen-reader user. A migrated site must either (a) delete the `<label>` and
 * pass `label="Channel"`, which is preferred, or (b) give the `<label>` an `id`, drop its
 * `htmlFor`, and pass `labelledBy`. The type requirement catches the mechanical rewrite
 * outright; what it CANNOT catch is a site that passes `ariaLabel` and leaves a stale
 * `<label htmlFor>` behind, which is why each migration batch carries a per-file `htmlFor`
 * grep rather than trusting the compiler.
 *
 * `onChange( value )` RATHER THAN `onChange( event )` is a deliberate break from the native
 * signature. Every migrated site changes from `e => set( e.target.value )` to `v => set( v )`,
 * which is mechanical and VISIBLE in the diff. Synthesising a fake event object was rejected:
 * it makes a migrated site look unmigrated, and it lets a real `e.target.name` or
 * `e.preventDefault()` dependency slip through unnoticed.
 */
import React, { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';

import Popover, { type PopoverDismissReason, type PopoverLayer } from './Popover';

export type SelectOption = { value: string; label: string; disabled?: boolean };
export type SelectGroup = { label: string; options: SelectOption[] };

type SelectBaseProps = {
    /** Controlled, and ALWAYS a string. */
    value: string;
    /** The bare value, never an event. */
    onChange: ( value: string ) => void;
    options: SelectOption[] | SelectGroup[];
    id?: string;
    /** Emits a hidden input, so a native form submission and new FormData( form ) still see it. */
    name?: string;
    /** Shown when the value matches no option. */
    placeholder?: string;
    disabled?: boolean;
    required?: boolean;
    invalid?: boolean;
    describedBy?: string;
    className?: string;
    /** Layout only: width / flex / margin. Appearance belongs to form-controls.css. */
    style?: React.CSSProperties;
    maxMenuHeight?: number;
    layer?: PopoverLayer;
};

/**
 * The three variants. Each requires one labelling prop; `ariaLabel` is additionally allowed
 * alongside `label`. Omitting all three fails to compile, which is the whole point.
 */
type SelectLabelling =
    | { label: string; ariaLabel?: string; labelledBy?: undefined }
    | { label?: undefined; ariaLabel: string; labelledBy?: undefined }
    | { label?: undefined; ariaLabel?: undefined; labelledBy: string };

export type SelectProps = SelectBaseProps & SelectLabelling;

/** 600ms, matching the native type-ahead window. */
const TYPE_AHEAD_RESET_MS = 600;
/** PageUp / PageDown step, as the native control moves. */
const PAGE_STEP = 10;

function isGrouped ( options: SelectOption[] | SelectGroup[] ): options is SelectGroup[] {
    return options.length > 0 && Object.prototype.hasOwnProperty.call( options[ 0 ], 'options' );
}

const Select: React.FC<SelectProps> = ( {
    value,
    onChange,
    options,
    id,
    name,
    label,
    ariaLabel,
    labelledBy,
    placeholder = '',
    disabled = false,
    required = false,
    invalid = false,
    describedBy,
    className,
    style,
    maxMenuHeight = 320,
    layer = 'default',
} ) => {
    // useId's own output is not guaranteed to be selector-safe, and these ids are written into
    // aria-activedescendant and aria-labelledby. Reduced to word characters so nothing
    // downstream has to escape them.
    const uid = useId().replace( /[^A-Za-z0-9_-]/g, '' );
    const labelId = `ui-sel-${ uid }-label`;
    const listId = `ui-sel-${ uid }-list`;
    const optionId = useCallback( ( index: number ) => `ui-sel-${ uid }-opt-${ index }`, [ uid ] );

    const [ open, setOpen ] = useState( false );
    const [ activeIndex, setActiveIndex ] = useState( -1 );
    const triggerRef = useRef<HTMLButtonElement>( null );
    const optionRefs = useRef<Array<HTMLLIElement | null>>( [] );
    const typeBuffer = useRef( '' );
    const typeTimer = useRef<ReturnType<typeof setTimeout> | null>( null );

    const groups: SelectGroup[] = useMemo(
        () => ( isGrouped( options ) ? options : [ { label: '', options: options as SelectOption[] } ] ),
        [ options ]
    );
    /** Every option in render order. Navigation and type-ahead run over this, groups and all. */
    const flat: SelectOption[] = useMemo(
        () => groups.flatMap( group => group.options ),
        [ groups ]
    );
    /**
     * Where each group starts in `flat`, so a rendered option can name its own flat index
     * without a counter mutated during render. A `let` incremented inside the JSX .map reads
     * more directly and is rejected by react-hooks/immutability - correctly, since the lint
     * cannot prove the callback runs during render, and a counter that ran twice would give
     * two options the same id and silently break aria-activedescendant.
     */
    const groupOffsets: number[] = useMemo( () => {
        const offsets: number[] = [];
        let total = 0;
        for ( const group of groups ) { offsets.push( total ); total += group.options.length; }
        return offsets;
    }, [ groups ] );

    /**
     * CLAUSE 4 - duplicate values: the first wins for display, with a development-only warning
     * carrying a COUNT and NO option text. The count is what makes it actionable; the text is
     * withheld because an option label can carry a customer name.
     */
    useEffect( () => {
        if ( process.env.NODE_ENV === 'production' ) return;
        const seen = new Set<string>();
        let duplicates = 0;
        for ( const option of flat ) {
            if ( seen.has( option.value ) ) duplicates += 1;
            else seen.add( option.value );
        }
        if ( duplicates > 0 ) {
            console.warn(
                `Select: ${ duplicates } duplicate option value(s); the first of each wins for display.`
            );
        }
    }, [ flat ] );

    useEffect( () => () => { if ( typeTimer.current ) clearTimeout( typeTimer.current ); }, [] );

    /**
     * CLAUSE 1 - an option whose value is '' is the placeholder ROW and is selectable when it
     * appears in options. CLAUSE 3 - a value matching no option shows the placeholder, and the
     * hidden input below still carries the unmatched value: this component never silently
     * rewrites state it was given.
     */
    const selectedIndex = useMemo( () => flat.findIndex( option => option.value === value ), [ flat, value ] );
    const selected = selectedIndex >= 0 ? flat[ selectedIndex ] : null;

    /** CLAUSE 5 - no options at all: the trigger is disabled and the menu never opens. */
    const noOptions = flat.length === 0;
    const isDisabled = disabled || noOptions;

    const firstEnabled = useCallback( () => flat.findIndex( option => !option.disabled ), [ flat ] );
    const lastEnabled = useCallback( () => {
        for ( let i = flat.length - 1; i >= 0; i -= 1 ) if ( !flat[ i ].disabled ) return i;
        return -1;
    }, [ flat ] );

    /** Step from `from` in `direction`, skipping disabled options, stopping at the ends. */
    const step = useCallback( ( from: number, direction: 1 | -1 ): number => {
        let i = from + direction;
        while ( i >= 0 && i < flat.length && flat[ i ].disabled ) i += direction;
        if ( i < 0 || i >= flat.length ) return from;
        return i;
    }, [ flat ] );

    const openMenu = useCallback( ( active: number ) => {
        if ( isDisabled ) return;
        setActiveIndex( active >= 0 && !flat[ active ]?.disabled ? active : firstEnabled() );
        setOpen( true );
    }, [ isDisabled, flat, firstEnabled ] );

    /**
     * CLAUSE 2 - onChange fires ONLY on a committed change, and NOT when the committed value
     * equals the current one. A native `change` event does not fire on a no-op either, and a
     * call site that re-saves on every selection would otherwise write on a re-pick.
     */
    const commit = useCallback( ( next: string ) => {
        setOpen( false );
        if ( next !== value ) onChange( next );
        triggerRef.current?.focus();
    }, [ onChange, value ] );

    const onDismiss = useCallback( ( _reason: PopoverDismissReason ) => {
        // Every dismissal route keeps the current value; Popover restores focus on Escape.
        setOpen( false );
    }, [] );

    /** Keep the active option in view. jsdom implements no scrollIntoView, hence the guard. */
    useEffect( () => {
        if ( !open || activeIndex < 0 ) return;
        optionRefs.current[ activeIndex ]?.scrollIntoView?.( { block: 'nearest' } );
    }, [ open, activeIndex ] );

    const pushTypeAhead = useCallback( ( char: string ): string => {
        typeBuffer.current += char;
        if ( typeTimer.current ) clearTimeout( typeTimer.current );
        typeTimer.current = setTimeout( () => { typeBuffer.current = ''; }, TYPE_AHEAD_RESET_MS );
        return typeBuffer.current;
    }, [] );

    const matchIndex = useCallback( ( query: string ): number => flat.findIndex(
        option => !option.disabled && option.label.toLowerCase().startsWith( query.toLowerCase() )
    ), [ flat ] );

    const onKeyDown = useCallback( ( e: React.KeyboardEvent<HTMLButtonElement> ) => {
        if ( isDisabled ) return;
        const { key, altKey, ctrlKey, metaKey } = e;

        if ( !open ) {
            if ( key === 'Enter' || key === ' ' || key === 'Spacebar'
                || key === 'ArrowDown' || key === 'ArrowUp' ) {
                e.preventDefault();
                openMenu( selectedIndex );
                return;
            }
            if ( key === 'Home' ) { e.preventDefault(); openMenu( firstEnabled() ); return; }
            if ( key === 'End' ) { e.preventDefault(); openMenu( lastEnabled() ); return; }
            // A printable character selects the first match WITHOUT opening, as the native
            // control does. One character, not the buffer: the buffer is an open-menu affair.
            if ( key.length === 1 && !ctrlKey && !metaKey && !altKey ) {
                const index = matchIndex( key );
                if ( index >= 0 ) { e.preventDefault(); commit( flat[ index ].value ); }
            }
            return;
        }

        switch ( key ) {
            case 'Enter':
            case ' ':
            case 'Spacebar':
                e.preventDefault();
                if ( activeIndex >= 0 && !flat[ activeIndex ].disabled ) commit( flat[ activeIndex ].value );
                else { setOpen( false ); triggerRef.current?.focus(); }
                return;
            case 'ArrowDown':
                e.preventDefault();
                setActiveIndex( current => ( current < 0 ? firstEnabled() : step( current, 1 ) ) );
                return;
            case 'ArrowUp':
                e.preventDefault();
                setActiveIndex( current => ( current < 0 ? lastEnabled() : step( current, -1 ) ) );
                return;
            case 'Home':
                e.preventDefault();
                setActiveIndex( firstEnabled() );
                return;
            case 'End':
                e.preventDefault();
                setActiveIndex( lastEnabled() );
                return;
            case 'PageDown':
            case 'PageUp': {
                e.preventDefault();
                const direction: 1 | -1 = key === 'PageDown' ? 1 : -1;
                setActiveIndex( current => {
                    const from = current < 0 ? ( direction === 1 ? firstEnabled() : lastEnabled() ) : current;
                    const target = Math.min( Math.max( 0, from + direction * PAGE_STEP ), flat.length - 1 );
                    // Land on an ENABLED option: walk on in the same direction, then back the
                    // other way if the end of the list is disabled.
                    if ( !flat[ target ]?.disabled ) return target;
                    const forward = step( target, direction );
                    return flat[ forward ]?.disabled ? step( target, direction === 1 ? -1 : 1 ) : forward;
                } );
                return;
            }
            case 'Escape':
                e.preventDefault();
                setOpen( false );
                triggerRef.current?.focus();
                return;
            case 'Tab':
                // Closes, keeps the current value, and does NOT preventDefault: focus moves on.
                setOpen( false );
                return;
            default:
                if ( key.length === 1 && !ctrlKey && !metaKey && !altKey ) {
                    e.preventDefault();
                    const index = matchIndex( pushTypeAhead( key ) );
                    if ( index >= 0 ) setActiveIndex( index );
                }
        }
    }, [
        isDisabled, open, activeIndex, selectedIndex, flat, openMenu, commit, step,
        firstEnabled, lastEnabled, matchIndex, pushTypeAhead,
    ] );

    // Alt+ArrowDown opens. Handled with the plain ArrowDown arm above, which fires whether or
    // not Alt is held - so the one combination the table singles out needs no second branch.

    const triggerText = selected ? selected.label : placeholder;

    /**
     * THE NAME WIRING, in one expression so the precedence is readable. `aria-label` wins when
     * both are passed, and `aria-labelledby` is then NOT emitted - see the note at the top.
     */
    const ariaLabelledBy = ariaLabel
        ? undefined
        : ( labelledBy ?? ( label ? labelId : undefined ) );

    return (
        <div className={ [ 'ui-field', className ].filter( Boolean ).join( ' ' ) } style={ style }>
            { label !== undefined && (
                /*
                 * The visible label the component OWNS. 18 selects in 13 files sit inside a
                 * wrapping <label> today, and leaving that wrapper around a
                 * <button role="combobox"> has two defects: a <button> is a labelable element,
                 * so the name is computed by walking the label's subtree - which now contains
                 * the trigger's own text, producing "Fit and size Choose your fit and size" -
                 * and a label forwards clicks to its control, which can double-activate a
                 * button. A <span> plus aria-labelledby has neither problem, and the onClick
                 * keeps the "click the words to open it" affordance a <label> gave for free.
                 */
                <span
                    className="ui-field-label"
                    id={ ariaLabel ? undefined : labelId }
                    onClick={ () => ( open ? setOpen( false ) : openMenu( selectedIndex ) ) }
                >
                    { label }
                </span>
            ) }

            <button
                ref={ triggerRef }
                type="button"
                id={ id }
                role="combobox"
                className="ui-select-trigger"
                aria-expanded={ open }
                aria-controls={ listId }
                aria-haspopup="listbox"
                aria-activedescendant={ open && activeIndex >= 0 ? optionId( activeIndex ) : undefined }
                aria-label={ ariaLabel }
                aria-labelledby={ ariaLabelledBy }
                aria-invalid={ invalid || undefined }
                aria-required={ required || undefined }
                aria-describedby={ describedBy }
                aria-disabled={ isDisabled || undefined }
                disabled={ isDisabled }
                onClick={ () => ( open ? setOpen( false ) : openMenu( selectedIndex ) ) }
                onKeyDown={ onKeyDown }
            >
                <span className={ selected ? 'ui-select-value' : 'ui-select-placeholder' }>
                    { triggerText }
                </span>
            </button>

            { /* So a native <form> submission and new FormData( form ) still see the field.
                 HONEST JUSTIFICATION: measured across all 162 select elements, ZERO set name,
                 form, required, onBlur or ref - there is no current instance of the failure
                 this prevents. It is defensive design for the next form, and it carries the
                 value the component was GIVEN, matched or not. */ }
            { name !== undefined && <input type="hidden" name={ name } value={ value } /> }

            <Popover
                open={ open }
                anchorRef={ triggerRef }
                onDismiss={ onDismiss }
                maxHeight={ maxMenuHeight }
                layer={ layer }
            >
                { /* The listbox takes the SAME resolved wiring as the trigger rather than
                     always pointing at labelId, which is what design 5.2's line literally
                     says. The difference matters in the ariaLabel-only case: labelId names no
                     rendered element there, so an aria-labelledby pointing at it would be a
                     DANGLING reference - and a dangling reference computes to no name at all,
                     which UiSelect.test.tsx's last case demonstrates. */ }
                <ul
                    className="ui-select-menu"
                    id={ listId }
                    role="listbox"
                    aria-label={ ariaLabel }
                    aria-labelledby={ ariaLabelledBy }
                >
                    { groups.map( ( group, groupIndex ) => {
                        const groupLabelId = `ui-sel-${ uid }-grp-${ groupIndex }`;
                        const items = group.options.map( ( option, withinGroup ) => {
                            const index = groupOffsets[ groupIndex ] + withinGroup;
                            return (
                                <li
                                    key={ `${ option.value }-${ index }` }
                                    id={ optionId( index ) }
                                    role="option"
                                    className="ui-select-option"
                                    aria-selected={ index === selectedIndex }
                                    aria-disabled={ option.disabled || undefined }
                                    data-active={ index === activeIndex ? 'true' : undefined }
                                    ref={ element => { optionRefs.current[ index ] = element; } }
                                    onClick={ () => { if ( !option.disabled ) commit( option.value ); } }
                                >
                                    { option.label }
                                </li>
                            );
                        } );

                        if ( !group.label ) return items;
                        return (
                            <li role="presentation" key={ `grp-${ groupIndex }` }>
                                <span className="ui-select-group-label" id={ groupLabelId }>{ group.label }</span>
                                <ul role="group" aria-labelledby={ groupLabelId } className="ui-select-group">
                                    { items }
                                </ul>
                            </li>
                        );
                    } ) }
                </ul>
            </Popover>
        </div>
    );
};

export default Select;
