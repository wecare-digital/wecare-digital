/**
 * Global Search Modal Component
 * Quick search across contacts, messages, and navigation
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useRouter } from 'next/router';
import { getAllNavItems } from '../config/navigation';
import * as api from '../api/client';

interface SearchResult {
  id: string;
  type: 'contact' | 'message' | 'page' | 'action' | 'order' | 'invoice' | 'service' | 'link';
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

  // Universal record search. Navigation matches are immediate; operational records are
  // loaded after a short debounce so Ctrl+K does not turn every keystroke into six API calls.
  useEffect( () => {
    const trimmed = query.trim();
    if ( !trimmed )
    {
      setResults( DEFAULT_RESULTS );
      return;
    }

    const q = trimmed.toLowerCase();
    const navigation = NAVIGATION_ITEMS.filter( item =>
      item.title.toLowerCase().includes( q ) || item.subtitle?.toLowerCase().includes( q )
    );
    const local: SearchResult[] = [ ...navigation ];

    contacts.forEach( contact => {
      if ( contact.name?.toLowerCase().includes( q ) || contact.phone?.includes( trimmed ) )
      {
        local.push( {
          id: `contact-local-${contact.id}`, type: 'contact',
          title: contact.name || contact.phone, subtitle: contact.phone, icon: '◎',
          path: `/workspace/customers?contact=${encodeURIComponent( contact.id )}`,
        } );
      }
    } );
    messages.slice( 0, 100 ).forEach( msg => {
      if ( msg.content?.toLowerCase().includes( q ) )
      {
        local.push( {
          id: `msg-${msg.id}`, type: 'message',
          title: msg.content.substring( 0, 50 ) + ( msg.content.length > 50 ? '…' : '' ),
          subtitle: 'Message', icon: '◇',
          path: `/workspace/communications?view=inbox&contact=${encodeURIComponent( msg.contactId )}`,
        } );
      }
    } );
    setResults( local.slice( 0, 10 ) );

    let cancelled = false;
    const timer = window.setTimeout( () => {
      void ( async () => {
        const [ contactResult, orderResult, invoiceResult, serviceResult, linkResult ] = await Promise.allSettled( [
          api.searchContacts( trimmed, 8 ),
          api.listOrders( { search: trimmed, limit: 25 } ),
          api.listInvoicesEngine( { limit: 500 } ),
          api.listFlowSubmissions( { limit: 250 } ),
          fetch( '/api/links' ).then( response => response.ok ? response.json() : { links: [] } ),
        ] );
        if ( cancelled ) return;

        const records: SearchResult[] = [];

        if ( contactResult.status === 'fulfilled' )
        {
          contactResult.value.forEach( contact => records.push( {
            id: `contact-${contact.contactId}`, type: 'contact',
            title: contact.name || contact.phone || contact.customerUuid || 'Customer',
            subtitle: [ contact.customerUuid, contact.phone, contact.email ].filter( Boolean ).join( ' · ' ),
            icon: '◎',
            path: `/workspace/customers?contact=${encodeURIComponent( contact.contactId )}`,
          } ) );
        }

        if ( orderResult.status === 'fulfilled' )
        {
          ( orderResult.value.orders || [] ).slice( 0, 8 ).forEach( order => records.push( {
            id: `order-${order.orderId}`, type: 'order',
            title: order.orderNumber || order.shortId || order.orderId,
            subtitle: [ order.customerName, order.customerPhone, order.paymentStatus, order.source ].filter( Boolean ).join( ' · ' ),
            icon: '□',
            path: `/workspace/commerce?view=orders&search=${encodeURIComponent( order.orderNumber || order.orderId )}`,
          } ) );
        }

        if ( invoiceResult.status === 'fulfilled' )
        {
          invoiceResult.value.invoices.filter( invoice =>
            [ invoice.invoiceNumber, invoice.invoiceId, invoice.orderId, invoice.customerName,
              invoice.customerPhone, invoice.customerEmail, invoice.paymentId, invoice.referenceId ]
              .some( value => String( value || '' ).toLowerCase().includes( q ) )
          ).slice( 0, 8 ).forEach( invoice => records.push( {
            id: `invoice-${invoice.invoiceId}`, type: 'invoice',
            title: invoice.invoiceNumber || invoice.invoiceId,
            subtitle: [ invoice.customerName, invoice.paymentStatus, invoice.orderId ].filter( Boolean ).join( ' · ' ),
            icon: '▤',
            path: `/workspace/payments?view=ledger&ledger=invoices&search=${encodeURIComponent( invoice.invoiceNumber || invoice.invoiceId )}`,
          } ) );
        }

        if ( serviceResult.status === 'fulfilled' )
        {
          serviceResult.value.filter( item =>
            [ item.submissionNumber, item.requestId, item.referenceId, item.orderId, item.orderNumber,
              item.invoiceId, item.customerUuid, item.senderName, item.customerName, item.phone, item.subject ]
              .some( value => String( value || '' ).toLowerCase().includes( q ) )
          ).slice( 0, 8 ).forEach( item => records.push( {
            id: `service-${item.submissionId}`, type: 'service',
            title: item.submissionNumber || item.requestId || item.referenceId || item.submissionId,
            subtitle: [ item.subject, item.customerName || item.senderName, item.status ].filter( Boolean ).join( ' · ' ),
            icon: '◇',
            path: `/workspace/service?view=requests&search=${encodeURIComponent( item.submissionNumber || item.requestId || item.submissionId )}`,
          } ) );
        }

        if ( linkResult.status === 'fulfilled' )
        {
          const links = Array.isArray( linkResult.value?.links ) ? linkResult.value.links : [];
          links.filter( ( link: any ) =>
            [ link.shortCode, link.shortUrl, link.originalUrl, link.title ]
              .some( value => String( value || '' ).toLowerCase().includes( q ) )
          ).slice( 0, 8 ).forEach( ( link: any ) => records.push( {
            id: `link-${link.shortCode}`, type: 'link',
            title: `/r/${link.shortCode}`,
            subtitle: link.title || link.originalUrl,
            icon: '↗',
            path: '/workspace/communications?view=manage&section=links',
          } ) );
        }

        const seen = new Set<string>();
        const merged = [ ...navigation, ...records, ...local ].filter( item => {
          const key = `${item.type}:${item.id}`;
          if ( seen.has( key ) ) return false;
          seen.add( key );
          return true;
        } );
        setResults( merged.slice( 0, 12 ) );
        setSelectedIndex( 0 );
      } )();
    }, 250 );

    return () => {
      cancelled = true;
      window.clearTimeout( timer );
    };
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
            placeholder="Search customer, order, invoice, payment, service or link…"
            role="combobox"
            aria-expanded={ results.length > 0 }
            aria-controls="search-results-list"
            aria-activedescendant={ results[ selectedIndex ] ? `search-result-${results[ selectedIndex ].id}` : undefined }
            aria-label="Search workspace records and pages"
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
