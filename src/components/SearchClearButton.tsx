import React from 'react';

interface SearchClearButtonProps {
  query: string;
  onClear: () => void;
}

/** An explicit, keyboard-accessible clear control alongside the shared voice mic.
 * Native search cancellation varies across browsers; keep this target consistent.
 */
export default function SearchClearButton( { query, onClear }: SearchClearButtonProps ) {
  if ( !query ) return null;
  return (
    <>
      <button type="button" className="public-search-clear" aria-label="Clear search" title="Clear search"
        onClick={ event => {
          const input = event.currentTarget.parentElement?.querySelector<HTMLInputElement>( 'input' );
          onClear();
          input?.focus( { preventScroll: true } );
        } }>
        <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
          <path d="M6 6l12 12M18 6L6 18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
      </button>
      <style jsx>{`
        .public-search-clear{
          position:absolute;inset-inline-end:44px;bottom:0;z-index:2;
          display:grid;place-items:center;width:44px;height:44px;padding:0;
          border:0;background:transparent;color:var(--public-brand-green,#1a3a2a);
          cursor:pointer;
        }
        .public-search-clear svg{width:18px;height:18px;display:block}
        .public-search-clear:focus-visible{outline:2px solid #1a3a2a;outline-offset:-3px}
      `}</style>
    </>
  );
}
