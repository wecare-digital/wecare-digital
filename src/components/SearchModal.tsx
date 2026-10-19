/**
 * Global Search Modal Component
 * Quick search across contacts, messages, and navigation
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useRouter } from 'next/router';
import { getAllNavItems } from '../config/navigation';

interface SearchResult {
  id: string;
  type: 'contact' | 'message' | 'page' | 'action';
  title: string;
  subtitle?: string;
  icon: string;
  path?: string;
  action?: () => void;
}

interface SearchModalProps {
  isOpen: boolean;
  onClose: () => void;
  contacts?: { id: string; name: string; phone: string }[];
  messages?: { id: string; content: string; contactId: string }[];
}

/**
 * Derived from navigation.ts, NOT a second hand-written list.
 *
 * This used to be 14 hardcoded entries and it had drifted badly: 8 of the 14 were
 * WhatsApp sub-pages, and Ctrl+K could not find [retired public path]/inbox, [retired public path]/sms, [retired public path]/rcs,
 * [retired public path]/ses, [retired public path]/settings, [retired public path]/security or any of the SEO pages - 88 real
 * destinations exist and it knew about 14. A palette that cannot find the unified
 * inbox is worse than no palette, because the user stops trying it.
 *
 * Deriving it means the palette cannot fall behind the sidebar again: adding a
 * route to navigation.ts adds it here. `parent` becomes the subtitle, which is
 * what disambiguates the several pages called "Inbox", "Logs" and "Campaign".
 */
const NAVIGATION_ITEMS: SearchResult[] = getAllNavItems().map( ( item, index ) => ( {
  id: `nav-${index}-${item.path}`,
  type: 'page' as const,
  title: item.label,
  subtitle: item.parent,
  icon: '⊞',
  path: item.path,
} ) );

/** The handful worth offering before anything is typed. */
// FEAT-003: '/workspace/access/security' left this list — Sign-in & MFA relocated into the gear
// panel and is no longer a URL, so it is reached through the gear rather than the palette. The
// Channel Settings hub takes its slot as the sixth default.
const DEFAULT_PATHS = [ '/workspace', '/workspace/communications', '/workspace/customers', '/workspace/commerce',
  '/workspace/payments', '/workspace/service' ];
const DEFAULT_RESULTS: SearchResult[] = DEFAULT_PATHS
  .map( ( p ) => NAVIGATION_ITEMS.find( ( i ) => i.path === p ) )
  .filter( ( i ): i is SearchResult => !!i );

/**
 * Stable empty defaults, and they are load-bearing rather than tidiness.
 *
 * These were inline `contacts = []` / `messages = []` default parameters, which
 * construct a NEW array on every render. Both appear in the search effect's
 * dependency list, so the deps compared unequal every render: type one character,
 * the effect runs, calls setResults with a fresh array, that re-renders, the
 * defaults are new arrays again, the effect runs again - an unbounded render loop
 * the moment anyone typed in the palette.
 *
 * It stayed hidden because the effect returns early while the query is empty, so
 * merely OPENING the palette is fine; only typing trips it. Found by a test that
 * typed into it, which hung.
 */
const NO_CONTACTS: NonNullable<SearchModalProps[ 'contacts' ]> = [];
const NO_MESSAGES: NonNullable<SearchModalProps[ 'messages' ]> = [];

const SearchModal: React.FC<SearchModalProps> = ( {
  isOpen, onClose, contacts = NO_CONTACTS, messages = NO_MESSAGES,
} ) => {
  const router = useRouter();
  const [ query, setQuery ] = useState( '' );
  const [ results, setResults ] = useState<SearchResult[]>( DEFAULT_RESULTS );
  const [ selectedIndex, setSelectedIndex ] = useState( 0 );
  const inputRef = useRef<HTMLInputElement>( null );

  // Focus input when modal opens
  useEffect( () => {
    if ( isOpen )
    {
      setQuery( '' );
      setSelectedIndex( 0 );
      setResults( DEFAULT_RESULTS );
      setTimeout( () => inputRef.current?.focus(), 100 );
    }
  }, [ isOpen ] );

  // Search logic - only run when query changes
  useEffect( () => {
    if ( !query.trim() )
    {
      return; // Keep default results
    }

    const q = query.toLowerCase();
    const searchResults: SearchResult[] = [];

    // Search navigation
    NAVIGATION_ITEMS.forEach( item => {
      if ( item.title.toLowerCase().includes( q ) || item.subtitle?.toLowerCase().includes( q ) )
      {
        searchResults.push( item );
      }
    } );

    // Search contacts
    contacts.forEach( contact => {
      if ( contact.name?.toLowerCase().includes( q ) || contact.phone?.includes( q ) )
      {
        searchResults.push( {
          id: `contact-${contact.id}`,
          type: 'contact',
          title: contact.name || contact.phone,
          subtitle: contact.phone,
          icon: '◎',
          path: `/workspace/communications?view=inbox&contact=${contact.id}`,
        } );
      }
    } );

    // Search messages (limited)
    messages.slice( 0, 100 ).forEach( msg => {
      if ( msg.content?.toLowerCase().includes( q ) )
      {
        searchResults.push( {
          id: `msg-${msg.id}`,
          type: 'message',
          title: msg.content.substring( 0, 50 ) + ( msg.content.length > 50 ? '...' : '' ),
          subtitle: `Message`,
          icon: '◇',
        } );
      }
    } );

    setResults( searchResults.slice( 0, 10 ) );
    setSelectedIndex( 0 );
  }, [ query, contacts, messages ] );

  // Keyboard navigation
  const handleKeyDown = useCallback( ( e: React.KeyboardEvent ) => {
    if ( e.key === 'ArrowDown' )
    {
      e.preventDefault();
      setSelectedIndex( prev => Math.min( prev + 1, results.length - 1 ) );
    } else if ( e.key === 'ArrowUp' )
    {
      e.preventDefault();
      setSelectedIndex( prev => Math.max( prev - 1, 0 ) );
    } else if ( e.key === 'Enter' && results[ selectedIndex ] )
    {
      e.preventDefault();
      const result = results[ selectedIndex ];
      if ( result.path )
      {
        router.push( result.path );
        onClose();
      } else if ( result.action )
      {
        result.action();
        onClose();
      }
    } else if ( e.key === 'Escape' )
    {
      onClose();
    }
  }, [ results, selectedIndex, router, onClose ] );

  if ( !isOpen ) return null;

  return (
    <div className="search-overlay" onClick={ onClose }>
      <div className="search-modal" onClick={ e => e.stopPropagation() }>
        <div className="search-input-wrapper">
          <span className="search-icon">Search</span>
          {/* Placeholder says "pages" only. It said "Search contacts, messages,
              pages..." but Layout.tsx renders this component with neither the
              `contacts` nor the `messages` prop, so both default to [] and
              neither is ever searched - it advertised two capabilities that could
              not fire. Widen it again when those props are wired. */}
          <input
            ref={ inputRef }
            type="text"
            value={ query }
            onChange={ e => setQuery( e.target.value ) }
            onKeyDown={ handleKeyDown }
            placeholder="Search pages…"
            role="combobox"
            aria-expanded={ results.length > 0 }
            aria-controls="search-results-list"
            aria-activedescendant={ results[ selectedIndex ] ? `search-result-${results[ selectedIndex ].id}` : undefined }
            aria-label="Search contacts, messages, and pages"
          />
          <span className="search-hint">ESC to close</span>
        </div>

        <div className="search-results" id="search-results-list" role="listbox">
          { results.length === 0 ? (
            <div className="search-empty">
              <span>No results found</span>
            </div>
          ) : (
            results.map( ( result, index ) => (
              <div
                key={ result.id }
                id={ `search-result-${result.id}` }
                role="option"
                aria-selected={ index === selectedIndex }
                className={ `search-result-item ${index === selectedIndex ? 'selected' : ''}` }
                onClick={ () => {
                  if ( result.path )
                  {
                    router.push( result.path );
                    onClose();
                  } else if ( result.action )
                  {
                    result.action();
                    onClose();
                  }
                } }
                onMouseEnter={ () => setSelectedIndex( index ) }
              >
                <div className="search-result-icon">{ result.icon }</div>
                <div className="search-result-info">
                  <div className="search-result-title">{ result.title }</div>
                  { result.subtitle && (
                    <div className="search-result-subtitle">{ result.subtitle }</div>
                  ) }
                </div>
                <div className="search-result-type">{ result.type }</div>
              </div>
            ) )
          ) }
        </div>

        <div className="search-footer">
          <span>↑↓ Navigate</span>
          <span>↵ Select</span>
          <span>ESC Close</span>
        </div>
      </div>

      {/* R5 token adoption: palette chrome reads the home-page tokens from tokens.css
          (--text-*, --text-light/muted, --bg-hover, --bg-secondary, --border) instead of
          hardcoded greys, so it matches the rest of the workspace. */}
      <style jsx>{ `
        .search-hint {
          font-size: var(--text-xs);
          color: var(--text-light);
          padding: 4px 8px;
          background: var(--bg-hover);
          border-radius: 4px;
        }
        .search-result-type {
          font-size: 10px;
          color: var(--text-light);
          text-transform: uppercase;
          padding: 2px 6px;
          background: var(--bg-hover);
          border-radius: 4px;
        }
        .search-footer {
          display: flex;
          gap: 16px;
          padding: 12px 20px;
          background: var(--bg-secondary);
          border-top: 1px solid var(--border);
          font-size: var(--text-xs);
          color: var(--text-muted);
        }
      `}</style>
    </div>
  );
};

export default SearchModal;
