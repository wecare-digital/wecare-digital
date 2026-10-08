/**
 * useSyncedDraft - a local draft of a controlled string prop, re-derived when the prop moves.
 *
 * All four Layer 2 pickers need the same thing: the caller owns the value, but the control has
 * to hold a DRAFT while the operator is mid-type or has chosen only one half of a pair.
 * DateField holds `DD/MM/YYYY` text that is not yet a date, TimeField holds an hour with no
 * minute, DateTimeField holds a date with no time, ColorField holds `#d1f4` on the way to
 * `#d1f470`. In each case the draft must be replaced when, and only when, the prop changes -
 * an unrelated parent re-render must not interrupt typing.
 *
 * IT ADJUSTS STATE DURING RENDER RATHER THAN IN AN EFFECT, and that is the point of extracting
 * it. The obvious spelling is `useEffect( () => setDraft( derive( value ) ), [ value ] )`, which
 * works but paints the stale draft first and then immediately re-renders - and
 * `react-hooks/set-state-in-effect` flags it, correctly. React's documented alternative is to
 * compare against the last seen prop during render and call setState there: React discards the
 * render in progress and re-runs the component before touching the DOM, so there is no
 * intermediate paint and no second commit.
 *
 * Calling setState during render is only legal for a component's OWN state, which is exactly
 * what this is - both pieces of state are created here.
 */
import { useState } from 'react';

export function useSyncedDraft<T> (
    value: string,
    derive: ( value: string ) => T
): [ T, ( next: T ) => void ] {
    const [ draft, setDraft ] = useState<T>( () => derive( value ) );
    /** The prop as it was when the draft was last derived. The comparison, not a ref. */
    const [ seen, setSeen ] = useState( value );

    if ( value !== seen ) {
        setSeen( value );
        setDraft( derive( value ) );
    }

    return [ draft, setDraft ];
}

export default useSyncedDraft;
