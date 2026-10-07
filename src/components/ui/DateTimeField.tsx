/**
 * DateTimeField - DateField and TimeField side by side.
 *
 * IT EMITS AND ACCEPTS `YYYY-MM-DDTHH:MM`, matching a native datetime-local input's `.value`,
 * which
 * is the same reversibility decision the other two pickers make. The two live call sites both
 * round-trip that exact string: dashboard/wa-graph-tools posts it as `delivery_time`, and
 * components/wa/inputs.tsx converts it to and from a Unix timestamp.
 *
 * INCOMPLETE MEANS EMPTY, as the native control behaves and for the reason TimeField records:
 * until BOTH halves are chosen the emitted value is '', so a date with no time cannot be
 * mistaken for midnight on a scheduled send. The halves are held locally so choosing the date
 * first does not throw it away.
 *
 * NO SECONDS. `datetime-local` renders seconds only when `step` asks for them, neither live
 * call site does, and both read the value back at minute precision.
 */
import React, { useCallback, useId } from 'react';

import DateField from './DateField';
import TimeField from './TimeField';
import { type PopoverLayer } from './Popover';
import { useSyncedDraft } from './useSyncedDraft';

type DateTimeFieldBaseProps = {
    /** `YYYY-MM-DDTHH:MM` or ''. Controlled. */
    value: string;
    /** The bare `YYYY-MM-DDTHH:MM`, never an event. '' while either half is unset. */
    onChange: ( local: string ) => void;
    /** `YYYY-MM-DD`, passed through to the date half. */
    min?: string;
    max?: string;
    /** Minutes granularity for the time half. */
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

type DateTimeFieldLabelling =
    | { label: string; ariaLabel?: string; labelledBy?: undefined }
    | { label?: undefined; ariaLabel: string; labelledBy?: undefined }
    | { label?: undefined; ariaLabel?: undefined; labelledBy: string };

export type DateTimeFieldProps = DateTimeFieldBaseProps & DateTimeFieldLabelling;

const LOCAL_RE = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/;

type LocalParts = { date: string; time: string };

export function splitLocal ( value: string ): LocalParts {
    const m = LOCAL_RE.exec( value );
    return m ? { date: m[ 1 ], time: m[ 2 ] } : { date: '', time: '' };
}

const DateTimeField: React.FC<DateTimeFieldProps> = ( {
    value,
    onChange,
    min,
    max,
    step,
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
    const labelId = `ui-dt-${ uid }-label`;

    /** See useSyncedDraft: a date with no time yet is a draft, not a value. */
    const [ parts, setParts ] = useSyncedDraft( value, splitLocal );

    const emit = useCallback( ( next: LocalParts ) => {
        setParts( next );
        const out = next.date && next.time ? `${ next.date }T${ next.time }` : '';
        if ( out !== value ) onChange( out );
        // `setParts` is a stable useState setter, but it arrives through a tuple from
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
            { /* NO aria-invalid AND NO aria-required ON THE GROUP - `role="group"` supports
                 neither. Both props are passed to the two halves, which do. */ }
            { label !== undefined && (
                <span className="ui-field-label" id={ ariaLabel ? undefined : labelId }>{ label }</span>
            ) }

            <div className="ui-datetime-parts">
                <DateField
                    ariaLabel="Date"
                    value={ parts.date }
                    onChange={ date => emit( { date, time: parts.time } ) }
                    min={ min }
                    max={ max }
                    disabled={ disabled }
                    invalid={ invalid }
                    layer={ layer }
                />
                <TimeField
                    ariaLabel="Time"
                    value={ parts.time }
                    onChange={ time => emit( { date: parts.date, time } ) }
                    step={ step }
                    disabled={ disabled }
                    invalid={ invalid }
                    layer={ layer }
                />
            </div>

            { name !== undefined && <input type="hidden" name={ name } value={ value } /> }
        </div>
    );
};

export default DateTimeField;
