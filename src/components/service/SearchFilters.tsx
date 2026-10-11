/**
 * One search + filter bar for Service Operations lists.
 *
 * WHY THIS EXISTS. The Phase 1 audit found every list page hand-rolling its own `<input>` and
 * `.filter()`, several of them filtering only the rows already loaded (so a match beyond the
 * page cap is invisible). This bar emits a single typed state object the caller passes straight
 * to the API, which keeps search SERVER-BACKED by construction. Debounced so a 2,000-row ledger
 * is not re-queried on every keystroke.
 */
import React, { useEffect, useRef, useState } from 'react';
import Select, { type SelectOption } from '../ui/Select';

export interface FilterDef {
  /** State key this control writes. */
  key: string;
  label: string;
  options: SelectOption[];
}

export interface SearchFiltersState {
  search: string;
  [key: string]: string;
}

export interface SearchFiltersProps {
  value: SearchFiltersState;
  onChange: ( next: SearchFiltersState ) => void;
  filters?: FilterDef[];
  searchPlaceholder?: string;
  /** Debounce for the search box, ms. */
  debounceMs?: number;
}

const wrap: React.CSSProperties = {
  display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center', margin: '0 0 16px',
};
const inputStyle: React.CSSProperties = {
  flex: '1 1 240px', minWidth: 200, maxWidth: 420, padding: '9px 12px',
  border: '1px solid #e2e8f0', borderRadius: 8, fontSize: 14, outline: 'none',
};

const SearchFilters: React.FC<SearchFiltersProps> = ( {
  value, onChange, filters = [], searchPlaceholder = 'Search customer, mobile, order, request, invoice…',
  debounceMs = 300,
} ) => {
  const [text, setText] = useState( value.search );
  const timer = useRef<ReturnType<typeof setTimeout> | null>( null );

  // Keep the local box in sync if the parent resets the state externally.
  useEffect( () => { setText( value.search ); }, [value.search] );

  const pushSearch = ( next: string ) => {
    setText( next );
    if ( timer.current ) clearTimeout( timer.current );
    timer.current = setTimeout( () => onChange( { ...value, search: next.trim() } ), debounceMs );
  };

  useEffect( () => () => { if ( timer.current ) clearTimeout( timer.current ); }, [] );

  return (
    <div style={wrap}>
      <input
        type="search"
        value={text}
        onChange={e => pushSearch( e.target.value )}
        placeholder={searchPlaceholder}
        aria-label="Search"
        style={inputStyle}
      />
      {filters.map( f => (
        <div key={f.key} style={{ minWidth: 160 }}>
          <Select
            options={[{ value: '', label: `All ${f.label.toLowerCase()}` }, ...f.options]}
            value={value[f.key] ?? ''}
            onChange={v => onChange( { ...value, [f.key]: v } )}
            ariaLabel={f.label}
          />
        </div>
      ) )}
    </div>
  );
};

export default SearchFilters;
