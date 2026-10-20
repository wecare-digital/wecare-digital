/**
 * Global Search Modal Component
 * Universal workspace search across operational records and navigation
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
          {/* Universal search is backed by the operational APIs below; the optional
              contacts/messages props are only an immediate local fast-path. */}
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

      {/*
        Global on purpose. The modal's descendants are all in this component, but the
        production screenshot showed the entire palette as normal document flow because
        only three minor selectors were still defined. This restores the actual modal shell,
        result rows and responsive containment in one prefixed block.
      */}
      <style jsx global>{ `
        .search-overlay{
          position:fixed;
          inset:0;
          z-index:1600;
          display:flex;
          align-items:flex-start;
          justify-content:center;
          padding:clamp(76px,10vh,120px) 20px 24px;
          background:rgba(15,42,29,.18);
          backdrop-filter:blur(5px);
          -webkit-backdrop-filter:blur(5px);
          overflow:auto;
        }

        .search-overlay .search-modal{
          width:min(720px,100%);
          max-height:min(720px,calc(100dvh - 120px));
          display:flex;
          flex-direction:column;
          overflow:hidden;
          border:1px solid var(--border);
          border-radius:20px;
          background:#fff;
          box-shadow:0 24px 80px rgba(15,42,29,.22);
        }

        .search-overlay .search-input-wrapper{
          min-height:66px;
          padding:11px 14px 11px 18px;
          display:grid;
          grid-template-columns:auto minmax(0,1fr) auto;
          align-items:center;
          gap:12px;
          border-bottom:1px solid var(--border);
          background:#fff;
        }

        .search-overlay .search-icon{
          color:var(--accent);
          font-size:var(--text-xs);
          font-weight:800;
          letter-spacing:.06em;
          text-transform:uppercase;
        }

        .search-overlay .search-input-wrapper input{
          width:100%;
          min-width:0;
          min-height:44px;
          margin:0;
          padding:8px 4px;
          border:0;
          border-radius:0;
          background:transparent;
          color:var(--text);
          box-shadow:none;
          outline:0;
          font:inherit;
          font-size:var(--text-lg);
          line-height:1.35;
        }

        .search-overlay .search-input-wrapper input:hover,
        .search-overlay .search-input-wrapper input:focus{
          border:0;
          box-shadow:none;
          outline:0;
        }

        .search-overlay .search-input-wrapper input::placeholder{
          color:var(--text-light);
          opacity:1;
        }

        .search-overlay .search-hint{
          font-size:var(--text-xs);
          color:var(--text-muted);
          padding:5px 8px;
          background:var(--bg-secondary);
          border:1px solid var(--border);
          border-radius:7px;
          white-space:nowrap;
        }

        .search-overlay .search-results{
          flex:1;
          min-height:0;
          overflow-y:auto;
          overscroll-behavior:contain;
          padding:8px;
          background:#fff;
        }

        .search-overlay .search-result-item{
          min-height:62px;
          padding:10px 12px;
          display:grid;
          grid-template-columns:40px minmax(0,1fr) auto;
          align-items:center;
          gap:12px;
          border:1px solid transparent;
          border-radius:12px;
          cursor:pointer;
          color:var(--text);
        }

        .search-overlay .search-result-item:hover,
        .search-overlay .search-result-item.selected{
          background:var(--lime-tint);
          border-color:var(--lime);
        }

        .search-overlay .search-result-icon{
          width:40px;
          height:40px;
          display:flex;
          align-items:center;
          justify-content:center;
          border-radius:10px;
          background:var(--bg-secondary);
          color:var(--accent);
          font-size:18px;
          font-weight:750;
        }

        .search-overlay .search-result-info{
          min-width:0;
          display:flex;
          flex-direction:column;
          gap:3px;
        }

        .search-overlay .search-result-title{
          min-width:0;
          overflow:hidden;
          text-overflow:ellipsis;
          white-space:nowrap;
          color:var(--text);
          font-size:var(--text-md);
          font-weight:700;
          line-height:1.3;
        }

        .search-overlay .search-result-subtitle{
          min-width:0;
          overflow:hidden;
          text-overflow:ellipsis;
          white-space:nowrap;
          color:var(--text-muted);
          font-size:var(--text-xs);
          line-height:1.4;
        }

        .search-overlay .search-result-type{
          font-size:10px;
          font-weight:750;
          letter-spacing:.06em;
          color:var(--text-muted);
          text-transform:uppercase;
          padding:4px 7px;
          background:var(--bg-secondary);
          border-radius:7px;
          white-space:nowrap;
        }

        .search-overlay .search-empty{
          min-height:180px;
          padding:32px;
          display:flex;
          align-items:center;
          justify-content:center;
          color:var(--text-muted);
          text-align:center;
          font-size:var(--text-sm);
        }

        .search-overlay .search-footer{
          display:flex;
          flex-wrap:wrap;
          gap:14px;
          padding:11px 18px;
          background:var(--bg-secondary);
          border-top:1px solid var(--border);
          font-size:var(--text-xs);
          color:var(--text-muted);
        }

        @media(max-width:640px){
          .search-overlay{
            align-items:flex-start;
            padding:
              calc(66px + env(safe-area-inset-top,0px))
              max(10px,env(safe-area-inset-right,0px))
              calc(84px + env(safe-area-inset-bottom,0px))
              max(10px,env(safe-area-inset-left,0px));
            background:rgba(15,42,29,.12);
          }
          .search-overlay .search-modal{
            max-height:calc(100dvh - 160px - env(safe-area-inset-top,0px) - env(safe-area-inset-bottom,0px));
            border-radius:16px;
          }
          .search-overlay .search-input-wrapper{
            grid-template-columns:minmax(0,1fr) auto;
            min-height:60px;
            padding:9px 10px 9px 14px;
          }
          .search-overlay .search-icon{
            display:none;
          }
          .search-overlay .search-input-wrapper input{
            font-size:var(--public-mobile-form-font-size);
          }
          .search-overlay .search-result-item{
            min-height:68px;
            grid-template-columns:40px minmax(0,1fr);
          }
          .search-overlay .search-result-type{
            grid-column:2;
            justify-self:start;
            margin-top:2px;
          }
          .search-overlay .search-footer{
            display:none;
          }
        }

        @media(max-width:340px){
          .search-overlay .search-hint{
            display:none;
          }
          .search-overlay .search-input-wrapper{
            grid-template-columns:1fr;
          }
        }

        @media(prefers-reduced-motion:reduce){
          .search-overlay{
            scroll-behavior:auto;
          }
        }

        @media(forced-colors:active){
          .search-overlay .search-modal,
          .search-overlay .search-input-wrapper,
          .search-overlay .search-result-item{
            border-color:CanvasText;
          }
        }
      `}</style>
    </div>
  );
};

export default SearchModal;
