/**
 * Layout Component - WECARE.DIGITAL
 */
import React, { ReactNode, useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { useRouter } from 'next/router';
import Link from 'next/link';
import SearchModal from './SearchModal';
import SettingsGear from './SettingsGear';
import { useKeyboardShortcuts } from '../hooks/useKeyboardShortcuts';
import { navigationConfig, NavItem, getAllNavItems, isNavItemActive } from '../config/navigation';
import { useUserRole, isPartnerAllowed } from '../hooks/useUserRole';
import { IconMap, ChevronRightIcon, MenuIcon, CloseIcon } from '../lib/icons';
import BottomNav from './BottomNav';
// The SAME lockup the public header and footer render. The sidebar used to carry its own
// inline "Bharat" / "Stack" wordmark, which meant the dashboard shipped a different brand
// from the public site; "Bharat Stack" is retired and this is the single source for it.
import BrandLockup from './BrandLockup';

// Minimal navigation shown to limited-access partner (customer) users.
const PARTNER_NAV: NavItem[] = [
  {
    // The parent row targets the partner's own page. It was /workspace/engage/whatsapp, the
    // shared inbox (since 2026-10-15 a signpost to it) - a page a partner may not open, so
    // the click only reached my-account by way of the redirect in the effect below.
    path: '/workspace/engage/whatsapp/my-account', label: 'WhatsApp', icon: 'whatsapp', children: [
      { path: '/workspace/engage/whatsapp/my-account', label: 'My WhatsApp Account' },
      // Inbox intentionally omitted until tenant-scoped (avoids data leakage).
    ],
  },
];
import { Breadcrumbs, KeyboardShortcuts, useKeyboardShortcutsModal } from './ui';

const LOGO_URL = 'https://wecare.digital/get/o/stream/media/m/wecaredigital.png';
const CONTACT_URL = 'https://wecare.digital/contact';

interface LayoutProps {
  children: ReactNode;
  user?: any;
  onSignOut?: () => void;
  showBreadcrumbs?: boolean;
}

const Layout: React.FC<LayoutProps> = ( { children, user, onSignOut, showBreadcrumbs = true } ) => {
  const router = useRouter();
  const { isPartner, loading: roleLoading } = useUserRole();

  // Redirect limited-access customers away from admin routes.
  useEffect( () => {
    if ( !roleLoading && isPartner && !isPartnerAllowed( router.pathname ) )
    {
      router.replace( '/workspace/engage/whatsapp/my-account' );
    }
  }, [ roleLoading, isPartner, router.pathname ] );

  // Customers see a minimal nav; internal team sees the full config.
  const navForRole = useMemo( () => ( isPartner ? PARTNER_NAV : navigationConfig ), [ isPartner ] );

  const [ isMobileMenuOpen, setIsMobileMenuOpen ] = useState( false );
  const [ searchOpen, setSearchOpen ] = useState( false );
  const [ sidebarSearch, setSidebarSearch ] = useState( '' );
  const [ brandDropdownOpen, setBrandDropdownOpen ] = useState( false );
  // Home-page-style scroll cue under the flat nav. `navOverflowing` is whether the
  // scroller has content below the fold at all; `showNavMore` is whether there is still
  // room to scroll down from where we are. Both derive from real scroll geometry, ported
  // from Header.tsx's Products rail, so they stay correct as rows or the viewport change.
  const navScrollRef = useRef<HTMLElement | null>( null );
  const [ navOverflowing, setNavOverflowing ] = useState( false );
  const [ showNavMore, setShowNavMore ] = useState( false );
  const [ sidebarCollapsed, setSidebarCollapsed ] = useState( () => {
    if ( typeof window !== 'undefined' )
    {
      return localStorage.getItem( 'sidebarCollapsed' ) === 'true';
    }
    return false;
  } );
  const shortcutsModal = useKeyboardShortcutsModal();

  // Persist sidebar collapsed state
  useEffect( () => {
    localStorage.setItem( 'sidebarCollapsed', String( sidebarCollapsed ) );
  }, [ sidebarCollapsed ] );

  useKeyboardShortcuts( [
    { key: 'k', ctrl: true, action: () => setSearchOpen( true ), description: 'Open search' },
    { key: '/', action: () => setSearchOpen( true ), description: 'Open search' },
  ] );

  // Get all nav items for sidebar search
  const allNavItems = useMemo( () => getAllNavItems(), [] );

  // Filter nav items based on search
  const filteredNavItems = useMemo( () => {
    if ( !sidebarSearch.trim() ) return [];
    const query = sidebarSearch.toLowerCase();
    return allNavItems.filter( item =>
      item.label.toLowerCase().includes( query ) ||
      item.parent?.toLowerCase().includes( query )
    ).slice( 0, 8 );
  }, [ sidebarSearch, allNavItems ] );

  useEffect( () => { setIsMobileMenuOpen( false ); }, [ router.pathname ] );

  // Keep the scroll cue in step with real scroll geometry on the flat nav. Ported from
  // Header.tsx's Products rail: `overflow` is content below the fold; `remaining` is how
  // much of it is still unseen. The cue appears only while there is more below.
  useEffect( () => {
    if ( typeof window === 'undefined' ) return undefined;
    const scroller = navScrollRef.current;
    if ( !scroller )
    {
      setNavOverflowing( false );
      setShowNavMore( false );
      return undefined;
    }
    const update = () => {
      const overflow = scroller.scrollHeight - scroller.clientHeight > 2;
      const remaining = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
      setNavOverflowing( overflow );
      setShowNavMore( overflow && remaining > 2 );
    };
    update();
    scroller.addEventListener( 'scroll', update, { passive: true } );
    window.addEventListener( 'resize', update );
    return () => {
      scroller.removeEventListener( 'scroll', update );
      window.removeEventListener( 'resize', update );
    };
  }, [ router.pathname, sidebarCollapsed, sidebarSearch, isPartner ] );

  const scrollNavForward = useCallback( () => {
    if ( typeof window === 'undefined' ) return;
    const scroller = navScrollRef.current;
    if ( !scroller ) return;
    const reduceMotion = typeof window.matchMedia === 'function'
      && window.matchMedia( '(prefers-reduced-motion: reduce)' ).matches;
    scroller.scrollBy( {
      top: Math.max( 46, scroller.clientHeight - 46 ),
      behavior: reduceMotion ? 'auto' : 'smooth',
    } );
  }, [] );

  const renderIcon = ( iconName?: string, size: number = 16 ) => {
    if ( !iconName ) return null;
    const Icon = IconMap[ iconName ];
    return Icon ? <Icon size={ size } /> : null;
  };

  const handleSearchItemClick = ( path: string ) => {
    setSidebarSearch( '' );
    router.push( path );
  };

  // The flat sidebar — ONE level, no expand/collapse. Each row is its own destination;
  // the dense sections open as single pages with in-page tabs, so there is no tree to
  // render. Active state uses `isNavItemActive`, which strips channel query strings.
  const renderNavItems = ( items: NavItem[] ) => {
    const query = sidebarSearch.trim().toLowerCase();
    const matchesSearch = ( item: NavItem ): boolean => {
      if ( !query ) return true;
      if ( item.label.toLowerCase().includes( query ) ) return true;
      return !!item.children?.some( ( c ) => c.label.toLowerCase().includes( query ) );
    };

    return items.filter( matchesSearch ).map( ( item ) => {
      const isActive = isNavItemActive( item, router.pathname );
      return (
        <div className="nav-group" key={ item.path }>
          <span
            className={ `nav-item ${isActive ? 'nav-item-active' : ''}` }
            onClick={ () => router.push( item.path ) }
            title={ sidebarCollapsed ? item.label : undefined }
          >
            <span className="nav-icon">{ renderIcon( item.icon, 16 ) }</span>
            <span className="nav-label">{ item.label }</span>
            { item.badge && <span className="nav-badge-soon">{ item.badge }</span> }
          </span>
        </div>
      );
    } );
  };

  return (
    <>
      <div className={ `layout ${sidebarCollapsed ? 'sidebar-collapsed' : ''}` }>
        <button className="mobile-menu-toggle" onClick={ () => setIsMobileMenuOpen( !isMobileMenuOpen ) } aria-label="Toggle menu">
          { isMobileMenuOpen ? <CloseIcon size={ 18 } /> : <MenuIcon size={ 18 } /> }
        </button>
        {/*
          Phone bottom bar. Rendered unconditionally and hidden by CSS above 768px
          rather than gated on a JS width check: a width read during render is wrong on
          the first paint of a statically exported page, and it desynchronises from the
          media queries that do the rest of the responsive work.

          `onMore` opens the SAME drawer the hamburger opens. The bar is a shortcut to
          four streams, not a second navigation surface with its own state.
        */}
        <BottomNav onMore={ () => setIsMobileMenuOpen( !isMobileMenuOpen ) } moreOpen={ isMobileMenuOpen } />
        <aside className={ `sidebar ${isMobileMenuOpen ? 'open' : ''} ${sidebarCollapsed ? 'collapsed' : ''}` }>
          {/* Brand */ }
          <div style={ { padding: '10px 12px 6px', flexShrink: 0, borderBottom: '2px solid #d1f470' } }>
            { !sidebarCollapsed ? (
              /* ONE BRAND, SHARED WITH THE PUBLIC HEADER.
                 This used to be a hand-rolled inline lockup reading "Bharat" / "Stack" at
                 19px/800 beside a 44px logo - a second, divergent brand that shipped only
                 inside the dashboard. "Bharat Stack" is retired on owner instruction: the
                 product is WECARE.DIGITAL everywhere, so this now renders the SAME
                 BrandLockup component the public header and footer use, which owns the
                 logo, the two-line WECARE. / DIGITAL wordmark and the red accent dot.
                 BrandLockup is self-styling (styled-jsx cannot be reached into from here),
                 so it deliberately takes no size props - the sidebar gets the same 60px /
                 23px scale as the public header, which fits the 226px content box. */
              <div style={ { display: 'flex', alignItems: 'center', gap: 4, minHeight: 46 } }>
                <BrandLockup />
                <span style={ { position: 'relative', display: 'inline-flex' } }>
                  {/* DRAWN CHEVRON IN A CHIP, not a literal "▼". The glyph rendered at a
                      different weight on every platform and read as text rather than a
                      control; this is the public header's treatment - two borders on a
                      rotated box inside a lime chip - so both surfaces have the same
                      affordance. It rotates 180deg when the dropdown is open. */}
                  <button
                    type="button"
                    onClick={ () => setBrandDropdownOpen( !brandDropdownOpen ) }
                    aria-label="Open brand menu"
                    aria-expanded={ brandDropdownOpen }
                    style={ {
                      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                      width: 22, height: 22, padding: 0, cursor: 'pointer',
                      borderRadius: 7, border: '1px solid #e3ecc9',
                      background: 'rgba(209,244,112,.22)',
                    } }
                  >
                    <span style={ {
                      width: 6, height: 6, boxSizing: 'border-box',
                      borderRight: '2px solid #1a3a2a', borderBottom: '2px solid #1a3a2a',
                      opacity: .85,
                      transform: brandDropdownOpen ? 'translateY(1px) rotate(225deg)' : 'translateY(-1px) rotate(45deg)',
                      transition: 'transform .2s',
                    } } />
                  </button>
                  { brandDropdownOpen && (
                    <>
                      <div onClick={ () => setBrandDropdownOpen( false ) } style={ { position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, zIndex: 9998 } } />
                      <div style={ { position: 'absolute', top: 'calc(100% + 4px)', left: 0, background: '#fcfdfb', border: '1px solid #e5e7eb', borderTop: '3px solid #d1f470', borderRadius: 14, padding: '8px 0', minWidth: 170, boxShadow: '0 8px 28px rgba(0,0,0,0.12)', zIndex: 9999, display: 'flex', flexDirection: 'column' } }>
                        <Link href="/" onClick={ () => setBrandDropdownOpen( false ) } style={ { display: 'block', padding: '10px 20px', fontSize: 14, fontWeight: 500, color: '#1a3a2a', textDecoration: 'none' } }>Home</Link>
                        <Link href="/workspace/engage/inbox" onClick={ () => setBrandDropdownOpen( false ) } style={ { display: 'block', padding: '10px 20px', fontSize: 14, fontWeight: 500, color: '#1a3a2a', textDecoration: 'none' } }>CRM</Link>
                        <Link href="/workspace/access" onClick={ () => setBrandDropdownOpen( false ) } style={ { display: 'block', padding: '10px 20px', fontSize: 14, fontWeight: 500, color: '#1a3a2a', textDecoration: 'none' } }>Sign in</Link>
                      </div>
                    </>
                  ) }
                </span>
              </div>
            ) : (
              <div style={ { display: 'flex', justifyContent: 'center' } }>
                <img src={ LOGO_URL } alt="" style={ { height: 36, width: 36, borderRadius: 8 } } onError={ ( e ) => { ( e.target as HTMLImageElement ).style.display = 'none'; } } />
              </div>
            ) }
            <button className="sidebar-collapse-btn" onClick={ () => setSidebarCollapsed( !sidebarCollapsed ) } aria-label={ sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar' } title={ sidebarCollapsed ? 'Expand' : 'Collapse' } style={ { marginTop: 6 } }>
              <ChevronRightIcon size={ 14 } />
            </button>
          </div>

          {/* Sidebar Search */ }
          { !sidebarCollapsed && (
            <div className="sidebar-search">
              <div className="sidebar-search-input-wrapper">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" style={ { marginLeft: 10, flexShrink: 0 } }>
                  <path stroke="#1a3a2a" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="m21 21-4.35-4.35M11 6a5 5 0 0 1 5 5m3 0a8 8 0 1 1-16 0 8 8 0 0 1 16 0" />
                </svg>
                <input
                  type="text"
                  placeholder="Search pages..."
                  value={ sidebarSearch }
                  onChange={ e => setSidebarSearch( e.target.value ) }
                  className="sidebar-search-input"
                  aria-label="Search pages"
                />
                { sidebarSearch && (
                  <button className="sidebar-search-clear" onClick={ () => setSidebarSearch( '' ) }>×</button>
                ) }
              </div>
            </div>
          ) }

          <nav className="sidebar-nav" ref={ navScrollRef }>
            { renderNavItems( navForRole ) }
          </nav>
          {/* Home-page-style scroll cue. Rendered only when the nav overflows, and truly
              hidden (not just dimmed) once fully scrolled: aria-hidden + tabIndex -1 take
              it out of the a11y and tab order, and `.is-hidden` removes it visually. The
              double-chevron SVG is the exact path the public header's Products rail uses. */}
          { navOverflowing && (
            <div className={ `sidebar-nav-cue-row ${showNavMore ? '' : 'is-hidden'}`.trim() }>
              <button
                type="button"
                className="sidebar-nav-more"
                aria-label="Scroll to more navigation"
                aria-hidden={ !showNavMore }
                tabIndex={ showNavMore ? 0 : -1 }
                onClick={ scrollNavForward }
              >
                <svg
                  className="sidebar-nav-more-icon"
                  viewBox="0 -960 960 960"
                  aria-hidden="true"
                  focusable="false"
                >
                  <path d="M480-200 240-440l42-42 198 198 198-198 42 42-240 240Zm0-253L240-693l42-42 198 198 198-198 42 42-240 240Z" />
                </svg>
              </button>
            </div>
          ) }
          {/* The gear. Below the daily streams because it is the "everything
              else" door, not a destination you aim for. Hidden from partner users,
              who see a deliberately minimal nav. */}
          { !isPartner && (
            <div className="sidebar-gear">
              <SettingsGear collapsed={ sidebarCollapsed } />
            </div>
          ) }
          <div className="sidebar-footer">
            { user && !sidebarCollapsed && (
              <div className="user-info">
                <span className="user-role">{ user.role || 'Operator' }</span>
                <span className="user-email">{ user.signInDetails?.loginId || user.email }</span>
                <button className="btn-signout" onClick={ onSignOut }>Sign Out</button>
              </div>
            ) }
            { user && sidebarCollapsed && (
              <button className="btn-signout" onClick={ onSignOut } style={ { width: '100%', fontSize: 11 } }>Out</button>
            ) }
            { !sidebarCollapsed && (
              <a href={ CONTACT_URL } target="_blank" rel="noopener noreferrer" style={ { display: 'block', marginTop: 8, fontSize: 13, fontWeight: 500, color: '#6b7280', textDecoration: 'none', transition: 'color 0.2s' } }>
                Contact Us
              </a>
            ) }
          </div>
        </aside>
        { isMobileMenuOpen && <div className="mobile-overlay" onClick={ () => setIsMobileMenuOpen( false ) } /> }
        {/* data-wc-no-translate IS A DATA-INTEGRITY GUARD, NOT A PREFERENCE.
            SupportWidget's translator replaces text nodes in place, and on the dashboard
            those nodes are customer names, phone numbers, message bodies, order lines and
            invoice amounts. Machine-translating live operational data corrupts what an
            operator is reading, and afterwards it cannot be told apart from real data.
            collectTextNodes rejects a node if any ancestor up to its root carries this
            attribute, so putting it here exempts EVERY dashboard page's content in one
            place - no per-page opt-in to forget.
            The sidebar sits outside this element and is deliberately left translatable:
            SupportWidget starts its walk at `.layout`, so navigation labels DO translate,
            which is the half an operator who reads Hindi or Tamil actually benefits from.
            Do not remove this to "make translation work on the dashboard" - that is the
            defect it prevents. */}
        <main id="main-content" className="main-content" data-wc-no-translate="true">
          { showBreadcrumbs && <Breadcrumbs /> }
          <div className="inner-content-container">
            { children }
          </div>
        </main>
        <SearchModal isOpen={ searchOpen } onClose={ () => setSearchOpen( false ) } />
        <KeyboardShortcuts isOpen={ shortcutsModal.isOpen } onClose={ shortcutsModal.close } />
      </div>
    </>
  );
};

export default Layout;
