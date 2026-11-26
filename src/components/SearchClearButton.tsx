import React from 'react';

interface SearchClearButtonProps {
  query: string;
  onClear: () => void;
  placement?: 'before-mic' | 'end' | 'inline';
}

/** An explicit, keyboard-accessible clear control alongside the shared voice mic.
 * Native search cancellation varies across browsers; keep this target consistent.
 */
export default function SearchClearButton( { query, onClear, placement = 'before-mic' }: SearchClearButtonProps ) {
  if ( !query ) return null;
  return (
    <>
      <button type="button" className={ `public-search-clear is-${placement}` } aria-label="Clear search" title="Clear search"
        onPointerDown={ event => { if ( event.button === 0 ) event.preventDefault(); } }
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
          position:absolute;inset-inline-end:44px;top:50%;transform:translateY(-50%);z-index:2;
          display:grid;place-items:center;width:44px;height:44px;padding:0;
          border:0;background:transparent;color:var(--public-brand-green,#1a3a2a);
          cursor:pointer;
        }
        .public-search-clear.is-end{inset-inline-end:0}
        .public-search-clear.is-inline{position:static;transform:none;flex:0 0 44px}
        .public-search-clear:hover{color:#2f9e44}
        .public-search-clear svg{width:18px;height:18px;display:block}
        .public-search-clear:focus-visible{outline:2px solid #1a3a2a;outline-offset:-3px}
      `}</style>
    </>
  );
}
