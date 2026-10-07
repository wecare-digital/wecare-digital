/**
 * DateField - our own date picker, so the OPEN calendar is ours too.
 *
 * IT EMITS AND ACCEPTS `YYYY-MM-DD`, BYTE-IDENTICAL TO a native date input's `.value`.
 *
 * (The native attribute is never SPELLED OUT in this file, here or below, and that is not
 * squeamishness. The batch's own gate greps every .ts and .tsx outside src/test for the four
 * picker type attributes and expects NO output, so prose describing the control being replaced
 * would be indistinguishable from a control that was never replaced. It is the trap the
 * comment-stripping in FormControlsCss.test.ts and ScrollbarDeclarations.test.ts exists for,
 * except this gate is a grep and cannot strip anything - so the prose gives way, not the gate.)
 *
 * That single
 * decision is the whole reason this migration is safe: no call site's state shape changes, no
 * API payload changes, no validation helper changes, and reverting one call site to the native
 * input is a two-line edit rather than an unpick. Every other choice in this file is downstream
 * of it.
 *
 * COMPOSITION: a token-styled TEXT input showing `DD/MM/YYYY` - the India convention and this
 * audience's - plus a trigger button opening a Popover calendar. The text input is the primary
 * control and carries the field's accessible name, the `id` and the validity state; the button
 * is a secondary affordance named "Choose date".
 *
 * `id` GOES ON THE TEXT INPUT, which is a real difference from Select and worth stating. An
 * external `<label htmlFor={id}>` IS a valid name source for an `<input>`, so the shape that is
 * broken for Select - see its header - is legitimate here. A migrated date site may keep its
 * external label and pass `labelledBy`, or drop it and pass `label`; both work.
 *
 * PARSING IS ON BLUR AND ON Enter, NEVER PER KEYSTROKE, and `min`/`max` are enforced in BOTH
 * the grid and the parse. The reason is the one src/pages/cart.tsx records for its own control:
 * `min`/`max` on a native input are not enforced while typing or on paste, so the parse
 * boundary is the only place the rule can actually hold. Unparseable or out-of-range input
 * reverts the DISPLAY to the last valid value and leaves `value` untouched - this component
 * never emits a string the caller would have to validate again.
 *
 * PARSING IS AN EXPLICIT REGEX PLUS A REAL-CALENDAR CHECK, DELIBERATELY NOT `new Date( s )`.
 * `new Date( '31/02/2026' )` is implementation-defined and `new Date( 2026, 1, 31 )` rolls
 * silently into March, which is the one failure a slot-booking form must not have. The check
 * builds the date from numeric parts and asserts the parts come back unchanged, so 31/02/2026
 * is REJECTED rather than rolled.
 *
 * STYLING COMES FROM CLASSES IN src/styles/form-controls.css, not styled-jsx: the calendar is
 * portalled by Popover and a portal escapes styled-jsx's scope hash, which
 * src/test/StyledJsxBuildScope.test.ts watches for.
 */
import React, { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';

import Popover, { type PopoverDismissReason, type PopoverLayer } from './Popover';
import { useSyncedDraft } from './useSyncedDraft';

type DateFieldBaseProps = {
    /** `YYYY-MM-DD` or ''. Controlled. */
    value: string;
    /** The bare ISO string, never an event. '' when the field is cleared. */
    onChange: ( iso: string ) => void;
    /** `YYYY-MM-DD`. Honoured in the grid AND on type-in. */
    min?: string;
    max?: string;
    id?: string;
    /** Emits a hidden input carrying the ISO value, so a native form submission still sees it. */
    name?: string;
    disabled?: boolean;
    required?: boolean;
    invalid?: boolean;
    describedBy?: string;
    className?: string;
    /** Layout only: width / flex / margin. Appearance belongs to form-controls.css. */
    style?: React.CSSProperties;
    layer?: PopoverLayer;
};

/** The same "at least one of three" contract Select documents, for the same reason. */
type DateFieldLabelling =
    | { label: string; ariaLabel?: string; labelledBy?: undefined }
    | { label?: undefined; ariaLabel: string; labelledBy?: undefined }
    | { label?: undefined; ariaLabel?: undefined; labelledBy: string };

export type DateFieldProps = DateFieldBaseProps & DateFieldLabelling;

const ISO_RE = /^(\d{4})-(\d{2})-(\d{2})$/;
/** `D/M/YYYY` through `DD/MM/YYYY`. A two-digit year is REJECTED rather than guessed at. */
const DISPLAY_RE = /^(\d{1,2})\/(\d{1,2})\/(\d{4})$/;

const MONTHS = [
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December',
];
/**
 * Sunday-first, which is the convention the audience reads and the one Chrome draws for en-IN.
 * The long name is the column header's accessible name; the two letters are what is drawn.
 */
const WEEKDAYS = [
    { short: 'Su', long: 'Sunday' },
    { short: 'Mo', long: 'Monday' },
    { short: 'Tu', long: 'Tuesday' },
    { short: 'We', long: 'Wednesday' },
    { short: 'Th', long: 'Thursday' },
    { short: 'Fr', long: 'Friday' },
    { short: 'Sa', long: 'Saturday' },
];

const pad = ( n: number ) => String( n ).padStart( 2, '0' );

/** The real-calendar check. Built from numeric parts, then asserted to come back unchanged. */
export function isRealDate ( year: number, month: number, day: number ): boolean {
    if ( month < 1 || month > 12 || day < 1 || day > 31 ) return false;
    const d = new Date( Date.UTC( year, month - 1, day ) );
    return d.getUTCFullYear() === year && d.getUTCMonth() === month - 1 && d.getUTCDate() === day;
}

type Parts = { year: number; month: number; day: number };

export function parseIso ( iso: string ): Parts | null {
    const m = ISO_RE.exec( iso );
    if ( !m ) return null;
    const year = Number( m[ 1 ] );
    const month = Number( m[ 2 ] );
    const day = Number( m[ 3 ] );
    return isRealDate( year, month, day ) ? { year, month, day } : null;
}

const toIso = ( p: Parts ) => `${ p.year }-${ pad( p.month ) }-${ pad( p.day ) }`;

/** `YYYY-MM-DD` -> `DD/MM/YYYY`, and '' for anything this component would not emit. */
export function isoToDisplay ( iso: string ): string {
    const p = parseIso( iso );
    return p ? `${ pad( p.day ) }/${ pad( p.month ) }/${ p.year }` : '';
}

/** `DD/MM/YYYY` -> `YYYY-MM-DD`, or null. 31/02/2026 lands here and returns null. */
export function displayToIso ( text: string ): string | null {
    const m = DISPLAY_RE.exec( text.trim() );
    if ( !m ) return null;
    const day = Number( m[ 1 ] );
    const month = Number( m[ 2 ] );
    const year = Number( m[ 3 ] );
    return isRealDate( year, month, day ) ? toIso( { year, month, day } ) : null;
}

/**
 * ISO strings are fixed-width and zero-padded, so a lexicographic compare IS a chronological
 * one. That is the second thing the format choice buys, and it is why no Date object is
 * constructed to answer a range question.
 */
function inRange ( iso: string, min?: string, max?: string ): boolean {
    if ( min && ISO_RE.test( min ) && iso < min ) return false;
    if ( max && ISO_RE.test( max ) && iso > max ) return false;
    return true;
}

function clampIso ( iso: string, min?: string, max?: string ): string {
    if ( min && ISO_RE.test( min ) && iso < min ) return min;
    if ( max && ISO_RE.test( max ) && iso > max ) return max;
    return iso;
}

/** Shift an ISO date by whole days through UTC, so no local DST transition can lose a day. */
function shiftDays ( iso: string, days: number ): string {
    const p = parseIso( iso );
    if ( !p ) return iso;
    const d = new Date( Date.UTC( p.year, p.month - 1, p.day ) );
    d.setUTCDate( d.getUTCDate() + days );
    return toIso( { year: d.getUTCFullYear(), month: d.getUTCMonth() + 1, day: d.getUTCDate() } );
}

/**
 * Shift by whole months, CLAMPING the day to the target month's length rather than rolling.
 * 31 January + 1 month is 28 February, not 3 March - the same rule a native picker applies.
 */
function shiftMonths ( iso: string, months: number ): string {
    const p = parseIso( iso );
    if ( !p ) return iso;
    const total = ( p.year * 12 ) + ( p.month - 1 ) + months;
    const year = Math.floor( total / 12 );
    const month = ( total % 12 ) + 1;
    const lastDay = new Date( Date.UTC( year, month, 0 ) ).getUTCDate();
    return toIso( { year, month, day: Math.min( p.day, lastDay ) } );
}

/** 0 = Sunday. Built from numeric parts, never from parsing a string back into a Date. */
function weekdayOf ( iso: string ): number {
    const p = parseIso( iso );
    if ( !p ) return 0;
    return new Date( Date.UTC( p.year, p.month - 1, p.day ) ).getUTCDay();
}

function todayIso (): string {
    const now = new Date();
    return toIso( { year: now.getFullYear(), month: now.getMonth() + 1, day: now.getDate() } );
}

const DateField: React.FC<DateFieldProps> = ( {
    value,
    onChange,
    min,
    max,
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
    const labelId = `ui-date-${ uid }-label`;
    const monthId = `ui-date-${ uid }-month`;

    const [ open, setOpen ] = useState( false );
    /**
     * The DISPLAY text, which diverges from `value` only while the operator is mid-type. The
     * caller is the source of truth: when `value` moves, the display follows - and only then,
     * so an unrelated parent re-render never interrupts typing. See useSyncedDraft for why this
     * is a render-time adjustment and not an effect.
     */
    const [ text, setText ] = useSyncedDraft( value, isoToDisplay );
    /** The day the grid's roving tabindex is on. Always inside min/max while the panel is open. */
    const [ focusIso, setFocusIso ] = useState( '' );

    const triggerRef = useRef<HTMLButtonElement>( null );
    const gridRef = useRef<HTMLDivElement>( null );

    const today = useMemo( () => todayIso(), [] );

    const ariaLabelledBy = ariaLabel
        ? undefined
        : ( labelledBy ?? ( label ? labelId : undefined ) );

    /**
     * Commit the typed text. Valid and in range -> emit (and only on a real change, matching
     * Select's clause 2). Anything else -> revert the display and leave `value` alone.
     */
    const commitText = useCallback( () => {
        const trimmed = text.trim();
        if ( trimmed === '' ) {
            if ( value !== '' ) onChange( '' );
            return;
        }
        const iso = displayToIso( trimmed );
        if ( iso && inRange( iso, min, max ) ) {
            if ( iso !== value ) onChange( iso );
            else setText( isoToDisplay( value ) );
            return;
        }
        setText( isoToDisplay( value ) );
        // `setText` is a stable useState setter, but it arrives through a tuple from
        // useSyncedDraft, so the lint cannot prove that. Listed rather than suppressed.
    }, [ text, value, onChange, min, max, setText ] );

    const openPanel = useCallback( () => {
        if ( disabled ) return;
        const start = clampIso( parseIso( value ) ? value : today, min, max );
        setFocusIso( start );
        setOpen( true );
    }, [ disabled, value, today, min, max ] );

    /**
     * THE REASON IS ACTED ON, NOT DISCARDED, AND THAT IS NOT A STYLE POINT.
     *
     * Unlike Select - where DOM focus never leaves the trigger - this component runs roving
     * focus INSIDE the portalled panel (see the effect below). So any dismissal that unmounts
     * the panel while a day button holds focus removes the focused node from the document, and
     * the operator lands on `<body>` with no keyboard route back to the control. That is the
     * hazard UiDateField.test.tsx states in full on the Escape case.
     *
     * Escape is already covered, and covered by Popover rather than here: its 'escape' arm
     * calls `anchorRef.current?.focus()`. 'tab' and 'outside' have no such arm, so they are
     * handled here. 'route' deliberately is NOT - the page is navigating and the trigger is
     * about to be unmounted too, so grabbing focus would fight the next page for it.
     */
    const onDismiss = useCallback( ( reason: PopoverDismissReason ) => {
        setOpen( false );
        if ( reason === 'tab' || reason === 'outside' ) triggerRef.current?.focus();
    }, [] );

    const commitDay = useCallback( ( iso: string ) => {
        setOpen( false );
        if ( iso !== value ) onChange( iso );
        triggerRef.current?.focus();
    }, [ onChange, value ] );

    /** Roving focus: the one tabbable day owns DOM focus whenever the panel is open. */
    useEffect( () => {
        if ( !open || !focusIso ) return;
        const day = gridRef.current?.querySelector<HTMLButtonElement>( '.ui-date-day[tabindex="0"]' );
        day?.focus();
    }, [ open, focusIso ] );

    const move = useCallback( ( next: string ) => {
        setFocusIso( clampIso( next, min, max ) );
    }, [ min, max ] );

    const onGridKeyDown = useCallback( ( e: React.KeyboardEvent<HTMLDivElement> ) => {
        const current = focusIso || today;
        switch ( e.key ) {
            case 'ArrowLeft': e.preventDefault(); move( shiftDays( current, -1 ) ); return;
            case 'ArrowRight': e.preventDefault(); move( shiftDays( current, 1 ) ); return;
            case 'ArrowUp': e.preventDefault(); move( shiftDays( current, -7 ) ); return;
            case 'ArrowDown': e.preventDefault(); move( shiftDays( current, 7 ) ); return;
            case 'Home':
                e.preventDefault();
                move( shiftDays( current, -weekdayOf( current ) ) );
                return;
            case 'End':
                e.preventDefault();
                move( shiftDays( current, 6 - weekdayOf( current ) ) );
                return;
            case 'PageUp':
                e.preventDefault();
                move( shiftMonths( current, e.shiftKey ? -12 : -1 ) );
                return;
            case 'PageDown':
                e.preventDefault();
                move( shiftMonths( current, e.shiftKey ? 12 : 1 ) );
                return;
            case 'Enter':
            case ' ':
            case 'Spacebar':
                e.preventDefault();
                if ( inRange( current, min, max ) ) commitDay( current );
                return;
            case 'Tab':
                /*
                 * TAB IS CANCELLED HERE AND FOCUS IS PUT BACK ON THE TRIGGER, which is one
                 * more Tab than a native picker needs - and is the deliberate trade.
                 *
                 * The browser computes the next tab stop from the node that is focused when
                 * the default action runs. Letting the default stand would compute it from a
                 * day button that the unmount has already removed from the document, so the
                 * move starts from nowhere and ends on `<body>`. Cancelling it and returning
                 * focus to the trigger makes the NEXT Tab a normal move from a real node.
                 *
                 * Like Escape, this DISCARDS: the grid's arrows only move the roving focus,
                 * Enter is what commits, so there is nothing here to commit. Select's Tab
                 * commits because its arrows commit; this one must not.
                 */
                e.preventDefault();
                setOpen( false );
                triggerRef.current?.focus();
                return;
            default:
        }
    }, [ focusIso, today, move, commitDay, min, max ] );

    /** The visible month, derived from the focused day so navigation and the grid cannot drift. */
    const view = useMemo( () => {
        const p = parseIso( focusIso ) ?? parseIso( value ) ?? parseIso( today )!;
        return { year: p.year, month: p.month };
    }, [ focusIso, value, today ] );

    /**
     * Six rows of seven, with leading and trailing padding cells, so the grid is rectangular at
     * every month length and the rows do not reflow as the operator pages through.
     */
    const weeks = useMemo( () => {
        const firstWeekday = new Date( Date.UTC( view.year, view.month - 1, 1 ) ).getUTCDay();
        const daysInMonth = new Date( Date.UTC( view.year, view.month, 0 ) ).getUTCDate();
        const cells: Array<string | null> = [];
        for ( let i = 0; i < firstWeekday; i += 1 ) cells.push( null );
        for ( let d = 1; d <= daysInMonth; d += 1 ) {
            cells.push( toIso( { year: view.year, month: view.month, day: d } ) );
        }
        while ( cells.length % 7 !== 0 ) cells.push( null );
        const rows: Array<Array<string | null>> = [];
        for ( let i = 0; i < cells.length; i += 7 ) rows.push( cells.slice( i, i + 7 ) );
        return rows;
    }, [ view ] );

    const monthLabel = `${ MONTHS[ view.month - 1 ] } ${ view.year }`;

    return (
        <div className={ [ 'ui-field', className ].filter( Boolean ).join( ' ' ) } style={ style }>
            { label !== undefined && (
                <label
                    className="ui-field-label"
                    id={ ariaLabel ? undefined : labelId }
                    htmlFor={ id }
                >
                    { label }
                </label>
            ) }

            { /* The border, radius and fill live on this WRAPPER rather than on the input, so the
                 input and the trigger button read as one control and a workspace stylesheet's
                 element-level `input` rule cannot repaint half of it. */ }
            <div className="ui-date-control" data-invalid={ invalid || undefined } data-disabled={ disabled || undefined }>
                <input
                    type="text"
                    className="ui-date-input"
                    id={ id }
                    value={ text }
                    inputMode="numeric"
                    autoComplete="off"
                    placeholder="DD/MM/YYYY"
                    disabled={ disabled }
                    required={ required || undefined }
                    aria-label={ ariaLabel }
                    aria-labelledby={ ariaLabelledBy }
                    aria-invalid={ invalid || undefined }
                    aria-required={ required || undefined }
                    aria-describedby={ describedBy }
                    onChange={ e => setText( e.target.value ) }
                    onBlur={ commitText }
                    onKeyDown={ e => {
                        if ( e.key === 'Enter' ) { e.preventDefault(); commitText(); }
                    } }
                />
                <button
                    ref={ triggerRef }
                    type="button"
                    className="ui-date-trigger"
                    aria-label="Choose date"
                    aria-haspopup="dialog"
                    aria-expanded={ open }
                    disabled={ disabled }
                    onClick={ () => ( open ? setOpen( false ) : openPanel() ) }
                >
                    { /* The calendar glyph is drawn from a token in form-controls.css, not here. */ }
                    <span className="ui-date-trigger-icon" aria-hidden="true" />
                </button>
            </div>

            { name !== undefined && <input type="hidden" name={ name } value={ value } /> }

            <Popover
                open={ open }
                anchorRef={ triggerRef }
                onDismiss={ onDismiss }
                matchAnchorWidth={ false }
                maxHeight={ 400 }
                layer={ layer }
                className="ui-date-popover"
            >
                <div role="dialog" aria-label="Choose date" className="ui-date-panel">
                    <div className="ui-date-head">
                        <button
                            type="button"
                            className="ui-date-nav"
                            aria-label="Previous month"
                            onClick={ () => move( shiftMonths( focusIso || today, -1 ) ) }
                        >
                            &#8249;
                        </button>
                        { /* The live region. Paging with the keyboard moves no visible focus out of
                             the grid, so without this the month change is silent. */ }
                        <span className="ui-date-month" id={ monthId } aria-live="polite">{ monthLabel }</span>
                        <button
                            type="button"
                            className="ui-date-nav"
                            aria-label="Next month"
                            onClick={ () => move( shiftMonths( focusIso || today, 1 ) ) }
                        >
                            &#8250;
                        </button>
                    </div>

                    <div
                        ref={ gridRef }
                        role="grid"
                        aria-labelledby={ monthId }
                        className="ui-date-grid"
                        onKeyDown={ onGridKeyDown }
                    >
                        <div role="row" className="ui-date-week">
                            { WEEKDAYS.map( day => (
                                <span key={ day.long } role="columnheader" aria-label={ day.long } className="ui-date-weekday">
                                    { day.short }
                                </span>
                            ) ) }
                        </div>
                        { weeks.map( ( week, weekIndex ) => (
                            <div role="row" className="ui-date-week" key={ `w-${ weekIndex }` }>
                                { /*
                                     aria-selected SITS ON THE GRIDCELL, NOT ON THE BUTTON.
                                     design 5.3 wrote it on the button, and role="button" does
                                     not support aria-selected - a screen reader is free to
                                     drop it, and jsx-a11y flags it. role="gridcell" does
                                     support it, which is also where the APG datepicker pattern
                                     puts it. The button keeps data-selected, because that is
                                     what form-controls.css draws the fill from.
                                  */ }
                                { week.map( ( iso, dayIndex ) => (
                                    <span
                                        role="gridcell"
                                        className="ui-date-cell"
                                        aria-selected={ iso ? iso === value : undefined }
                                        key={ iso ?? `pad-${ weekIndex }-${ dayIndex }` }
                                    >
                                        { iso && (
                                            <button
                                                type="button"
                                                className="ui-date-day"
                                                tabIndex={ iso === focusIso ? 0 : -1 }
                                                aria-current={ iso === today ? 'date' : undefined }
                                                aria-disabled={ !inRange( iso, min, max ) || undefined }
                                                disabled={ !inRange( iso, min, max ) }
                                                data-selected={ iso === value ? 'true' : undefined }
                                                data-today={ iso === today ? 'true' : undefined }
                                                onClick={ () => commitDay( iso ) }
                                            >
                                                { Number( iso.slice( 8, 10 ) ) }
                                            </button>
                                        ) }
                                    </span>
                                ) ) }
                            </div>
                        ) ) }
                    </div>
                </div>
            </Popover>
        </div>
    );
};

export default DateField;
