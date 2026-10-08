/**
 * TimeField - two of our own Selects, so the OPEN list is ours too.
 *
 * IT EMITS AND ACCEPTS `HH:MM`, 24-hour, byte-identical to a native time input's `.value`, for the
 * same reason DateField emits ISO: no call site's state shape, payload or validation changes,
 * and reverting one site to the native input is a two-line edit.
 *
 * IT IS NOT A FREE-TEXT FIELD, AND THE TRADEOFF IS REAL. All three live native time inputs
 * are SLOT times - engage/appointments, engage/rx-slots and TemplateSender - where a bounded
 * list reads better than arbitrary minutes. A 5-minute `step` cannot EXPRESS 09:07, so any
 * future site needing arbitrary minutes simply is not migrated and keeps the Layer-1-skinned
 * native input.
 *
 * WHAT THAT TRADEOFF MUST NOT DO IS LOSE AN EXISTING VALUE, which is a separate hazard and is
 * handled rather than accepted: if the incoming `value` carries a minute the step does not
 * generate - a row saved before this component existed, or by an API - that minute is INJECTED
 * into the options in sorted position. Without it the trigger would fall back to its
 * placeholder and the operator would see an empty field over a stored 09:07.
 *
 * INCOMPLETE MEANS EMPTY, as the native control behaves: until both parts are chosen the
 * emitted value is '', so a half-filled field cannot be mistaken for midnight. The two parts
 * are held in local state so picking the hour first does not throw the choice away.
 *
 * IT IS A role="group", NOT a labelled single control. Two comboboxes cannot share one
 * accessible name without one of them being unnamed, so the group carries the field's name and
 * each Select carries "Hours" or "Minutes".
 */
import React, { useCallback, useId, useMemo } from 'react';

import Select, { type SelectOption } from './Select';
import { type PopoverLayer } from './Popover';
import { useSyncedDraft } from './useSyncedDraft';

type TimeFieldBaseProps = {
    /** `HH:MM` or ''. Controlled. */
    value: string;
    /** The bare `HH:MM`, never an event. '' while either part is unset. */
    onChange: ( time: string ) => void;
    /** Minutes granularity. 5 by default; 1 gives every minute. */
    step?: number;
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

type TimeFieldLabelling =
    | { label: string; ariaLabel?: string; labelledBy?: undefined }
    | { label?: undefined; ariaLabel: string; labelledBy?: undefined }
    | { label?: undefined; ariaLabel?: undefined; labelledBy: string };

export type TimeFieldProps = TimeFieldBaseProps & TimeFieldLabelling;

const TIME_RE = /^(\d{2}):(\d{2})$/;

const pad = ( n: number ) => String( n ).padStart( 2, '0' );

const HOUR_OPTIONS: SelectOption[] = Array.from( { length: 24 }, ( _unused, h ) => ( {
    value: pad( h ),
    label: pad( h ),
} ) );

type TimeParts = { hour: string; minute: string };

export function splitTime ( value: string ): TimeParts {
    const m = TIME_RE.exec( value );
    if ( !m ) return { hour: '', minute: '' };
    const hour = Number( m[ 1 ] );
    const minute = Number( m[ 2 ] );
    if ( hour > 23 || minute > 59 ) return { hour: '', minute: '' };
    return { hour: m[ 1 ], minute: m[ 2 ] };
}

const TimeField: React.FC<TimeFieldProps> = ( {
    value,
    onChange,
    step = 5,
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
    const labelId = `ui-time-${ uid }-label`;

    /** See useSyncedDraft: the two halves are a draft until both are set, re-derived only when
     *  the caller's value moves. */
    const [ parts, setParts ] = useSyncedDraft( value, splitTime );

    const minuteOptions = useMemo( () => {
        const safeStep = Math.min( Math.max( Math.round( step ), 1 ), 60 );
        const minutes: number[] = [];
        for ( let m = 0; m < 60; m += safeStep ) minutes.push( m );
        // The injection described in the header: a stored minute the step cannot generate.
        const current = parts.minute === '' ? null : Number( parts.minute );
        if ( current !== null && !minutes.includes( current ) ) {
            minutes.push( current );
            minutes.sort( ( a, b ) => a - b );
        }
        return minutes.map( m => ( { value: pad( m ), label: pad( m ) } ) );
    }, [ step, parts.minute ] );

    const emit = useCallback( ( next: TimeParts ) => {
        setParts( next );
        const out = next.hour && next.minute ? `${ next.hour }:${ next.minute }` : '';
        if ( out !== value ) onChange( out );
        // `setParts` is a useState setter and is stable, but it arrives through a tuple from
        // useSyncedDraft, so the lint cannot prove that. Listed rather than suppressed.
    }, [ onChange, value, setParts ] );

    const ariaLabelledBy = ariaLabel
        ? undefined
        : ( labelledBy ?? ( label ? labelId : undefined ) );

    return (
        <div
            className={ [ 'ui-field', className ].filter( Boolean ).join( ' ' ) }
            style={ style }
            role="group"
            id={ id }
            aria-label={ ariaLabel }
            aria-labelledby={ ariaLabelledBy }
            aria-describedby={ describedBy }
        >
            { /* NO aria-invalid AND NO aria-required ON THE GROUP: `role="group"` supports
                 neither, so a screen reader may drop them and jsx-a11y flags them. Both props
                 are still honoured - they go to the two Selects below, which are comboboxes and
                 do support them, and that is also where the operator sees the invalid border. */ }
            { label !== undefined && (
                <span className="ui-field-label" id={ ariaLabel ? undefined : labelId }>{ label }</span>
            ) }

            <div className="ui-time-parts">
                <Select
                    ariaLabel="Hours"
                    value={ parts.hour }
                    onChange={ hour => emit( { hour, minute: parts.minute } ) }
                    options={ HOUR_OPTIONS }
                    placeholder="HH"
                    disabled={ disabled }
                    invalid={ invalid }
                    layer={ layer }
                />
                <span className="ui-time-sep" aria-hidden="true">:</span>
                <Select
                    ariaLabel="Minutes"
                    value={ parts.minute }
                    onChange={ minute => emit( { hour: parts.hour, minute } ) }
                    options={ minuteOptions }
                    placeholder="MM"
                    disabled={ disabled }
                    invalid={ invalid }
                    layer={ layer }
                />
            </div>

            { name !== undefined && <input type="hidden" name={ name } value={ value } /> }
        </div>
    );
};

export default TimeField;
