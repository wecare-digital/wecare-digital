import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/router';
import BrandLockup from './BrandLockup';
import HeaderCart from './HeaderCart';
import VoiceSearchMic from './VoiceSearchMic';
import SearchClearButton from './SearchClearButton';
import { CUSTOMER_MENU_HREFS, isPrimaryMenuActivation, menuActionForLabel, stashCustomerMenuAction, takeCustomerMenuAction } from '../lib/customerMenuActions';
import { useCustomerMenuQuickSend } from '../hooks/useCustomerMenuQuickSend';
import { PLAY_STORE } from '../config/analytics';
import { rankNavigation, NAV_DISCOVERY, contentSearchText } from '../lib/navigationSearch';
import { orderRequestForLabel, stashOrderRequest, takeOrderRequest } from '../lib/orderRequestSelection';
import {
  NAV_ICON_PATHS, SECTION_ICON_PATHS, FILLED_NAV_ICON_LABELS, MATERIAL_SECTION_ICON_LABELS,
  navIconViewBox, sectionIconViewBox, FALLBACK_NAV_ICON_PATH,
  SUBNAV_ICON_PATH, SUBNAV_DOT_PATH, SUBNAV_ICON_VIEW_BOX, ROW_CHEVRON_PATH, ROW_CHEVRON_VIEW_BOX,
} from '../lib/publicNavigationIcons';

/**
 * No props.
 *
 * There was one - `homeBrand?: boolean` - passed from _app.tsx as
 * `homeBrand={ router.pathname === '/' }` and used to add an `hdr-home` class to the
 * <header>. NO CSS RULE ANYWHERE KEYED OFF THAT CLASS. Four references across two files
 * threading a boolean down to set a class name nothing read, so the home page and every
 * other public page rendered an identical header either way.
 *
 * Removed rather than given a rule, because there is no brief for what a home-specific
 * header should look like, and an unused hook that looks load-bearing is worse than no
 * hook: the next person to touch _app.tsx has to prove it does nothing before they can
 * safely ignore it. If the home header should differ later, the prop is two lines.
 */
interface NavLink {
  label: string;
  /** Omitted only for a visible grouping label such as Elsewhere. */
  href?: string;
  /** router.pathname value that marks this link as the one current page. */
  match?: string;
  /** Extra menu words that should find this destination in navigation search. */
  searchTerms?: string[];
  /** Child destinations shown directly beneath this family item. */
  children?: NavLink[];
  /** True for absolute URLs off this app. Same tab either way. */
  external?: boolean;
}

interface NavSection {
  /** '' renders the links with no structural heading above them. */
  heading: string;
  /** Some structural headings are also real destinations. */
  headingHref?: string;
  headingMatch?: string;
  /** Render this section's destinations with the standard nested-row treatment. */
  nestedLinks?: boolean;
  /** Non-link heading that can disclose its own destination list. */
  collapsible?: boolean;
  links: NavLink[];
}

/** One column of the mega menu. Columns may hold more than one section. */
interface NavColumn {
  sections: NavSection[];
}

interface SearchableNavLink extends NavLink {
  href: string;
  searchText: string;
  description?: string;
  nested?: boolean;
}

/**
 * PUBLIC MENU SOURCE OF TRUTH.
 *
 * Structural headings stay on the existing small uppercase rung.
 * Every family and every destination uses the same 19px/600 navigation rung.
 * Product families are non-clickable labels; only their child destinations are pages.
 * Search is derived from this same graph.
 */
const COLUMNS: NavColumn[] = [
  {
    sections: [
      {
        heading: '',
        links: [
          { label: 'Home', href: '/', match: '/' },
          { label: 'Shop', href: '/shop/', match: '/shop' },
        ],
      },
      {
        heading: 'Products',
        links: [
          { label: 'Relay OS', href: '/relay-os/', match: '/relay-os', searchTerms: [ 'messaging', 'customer engagement', 'WhatsApp', 'SMS', 'RCS', 'email', 'voice' ] },
          {
            label: 'Atmos',
            searchTerms: [ 'environment', 'climate', 'sustainability' ],
            children: [
              { label: 'Nano Climate', href: '/atmos/nano-climate/', match: '/atmos/nano-climate', searchTerms: [ 'air quality', 'weather', 'forecast', 'AQI' ] },
              { label: 'Green Ledger', href: '/atmos/green-ledger/', match: '/atmos/green-ledger', searchTerms: [ 'environmental records', 'sustainability' ] },
            ],
          },
          {
            label: 'Elsewhere',
            searchTerms: [ 'travel' ],
            children: [
              { label: 'Visa', href: '/elsewhere/visa/', match: '/elsewhere/visa', searchTerms: [ 'elsewhere' ] },
              { label: 'Trip', href: '/elsewhere/trip/', match: '/elsewhere/trip', searchTerms: [ 'elsewhere', 'travel' ] },
              { label: 'Activities', href: '/elsewhere/activities/', match: '/elsewhere/activities', searchTerms: [ 'elsewhere' ] },
              { label: 'Rail', href: '/elsewhere/rail/', match: '/elsewhere/rail', searchTerms: [ 'train', 'railway', 'travel' ] },
              { label: 'Cruise', href: '/elsewhere/cruise/', match: '/elsewhere/cruise', searchTerms: [ 'ship', 'voyage', 'travel' ] },
              { label: 'Arogya Yatra', href: '/elsewhere/arogya-yatra/', match: '/elsewhere/arogya-yatra', searchTerms: [ 'medical tourism', 'medical travel', 'health', 'appointment', 'booking' ] },
            ],
          },
          { label: 'Expo Week', href: '/expo-week/', match: '/expo-week' },
          {
            label: 'Dastavez',
            children: [
              { label: 'Drafting', href: '/dastavez/drafting/', match: '/dastavez/drafting', searchTerms: [ 'dastavez' ] },
              { label: 'Registration', href: '/dastavez/registration/', match: '/dastavez/registration', searchTerms: [ 'dastavez' ] },
              { label: 'Legal Reference', href: '/dastavez/legal-reference/', match: '/dastavez/legal-reference', searchTerms: [ 'dastavez' ] },
            ],
          },
          {
            label: 'Clear Closure',
            children: [
              { label: 'Guided Resolution', href: '/shop/guided-resolution/' },
              { label: 'Case Submission', href: '/shop/file-assist/' },
              { label: 'Paperwork', href: '/shop/paperwork/' },
            ],
          },
          {
            label: 'Aastha',
            searchTerms: [ 'ritual guru', 'rituals', 'spiritual guidance' ],
            children: [
              { label: 'Vidhi', href: '/aastha/vidhi/', match: '/aastha/vidhi', searchTerms: [ 'puja guidance', 'ritual sequence' ] },
              { label: 'Samagri', href: '/aastha/samagri/', match: '/aastha/samagri', searchTerms: [ 'diy puja kit', 'puja essentials' ] },
              { label: 'Panchang', href: '/aastha/panchang/', match: '/aastha/panchang', searchTerms: [ 'ritva', 'astrology', 'vastu', 'panchanga', 'panjika', 'ritual calendar', 'tithi', 'nakshatra' ] },
            ],
          },
          { label: 'Anew', href: '/anew/', match: '/anew' },
          {
            label: 'Hunar',
            searchTerms: [ 'skills', 'learning', 'cv', 'resume', 'profile', 'pitch deck' ],
            children: [
              { label: 'Kaushal', href: '/hunar/kaushal/', match: '/hunar/kaushal', searchTerms: [ 'hunar', 'skills', 'learning' ] },
              { label: 'Prastuti', href: '/hunar/prastuti/', match: '/hunar/prastuti', searchTerms: [ 'hunar', 'cv', 'resume', 'profile', 'pitch', 'deck' ] },
            ],
          },
          {
            label: 'Niji Setu',
            searchTerms: [ 'identity', 'bio', 'invoicing' ],
            children: [
              { label: 'Parichay', href: '/niji-setu/parichay/', match: '/niji-setu/parichay', searchTerms: [ 'bio', 'digital identity', 'profile', 'links' ] },
              { label: 'Khata', href: '/niji-setu/khata/', match: '/niji-setu/khata', searchTerms: [ 'invoice', 'billing', 'invoice creation' ] },
            ],
          },
          { label: 'UdyamBids', href: '/udyam-bids/', match: '/udyam-bids', searchTerms: [ 'tenders', 'bids', 'procurement', 'tender information' ] },
          { label: 'GetKosh', href: '/get-kosh/', match: '/get-kosh', searchTerms: [ 'prepaid cards', 'payment cards', 'stored value' ] },
        ],
      },
    ],
  },
  {
    sections: [
      {
        heading: 'Request',
        links: [
          // Service controls will live on the authenticated order history. Preserve
          // Old service URLs now fall through to Home. Explicit authenticated
          // menu actions still open the Orders hub; exact Vault file links stay intact.
          { label: 'Orders', href: '/orders/', match: '/orders' },
          { label: 'Submit Request', href: '/orders/', match: '/orders', searchTerms: [ 'submit request' ] },
          { label: 'Request Amendment', href: '/orders/', match: '/orders', searchTerms: [ 'amend request' ] },
          { label: 'Drop Docs', href: '/orders/', match: '/orders', searchTerms: [ 'upload documents' ] },
          { label: 'Vault', href: '/orders/', match: '/orders', searchTerms: [ 'files' ] },
          {
            label: 'Shipments',
            searchTerms: [ 'track', 'pickup' ],
            children: [
              { label: 'Track', href: '/orders/', match: '/orders', searchTerms: [ 'shipments', 'tracking' ] },
              { label: 'Pickup Request', href: '/orders/', match: '/orders', searchTerms: [ 'shipments', 'pickup' ] },
            ],
          },
          { label: 'Leave Review', href: CUSTOMER_MENU_HREFS['leave-review'], match: '/orders' },
          { label: 'Subscribe', href: CUSTOMER_MENU_HREFS.subscribe, match: '/orders' },
        ],
      },
    ],
  },
  {
    sections: [
      {
        heading: 'Refer & Earn',
        links: [
          {
            label: 'Partner',
            searchTerms: [ 'refer', 'earn' ],
            children: [
              { label: 'Referral', href: CUSTOMER_MENU_HREFS.referral, match: '/orders', searchTerms: [ 'partner', 'refer', 'earn' ] },
              { label: 'Merchandise', href: '/shop/merchandise/', searchTerms: [ 'partner', 'refer', 'earn' ] },
              { label: 'Kiosk', href: '/shop/kiosk/', searchTerms: [ 'partner', 'refer', 'earn' ] },
            ],
          },
        ],
      },
      {
        heading: 'Extras',
        links: [
          {
            label: 'App',
            searchTerms: [ 'mobile apps', 'app download' ],
            children: [
              { label: 'Android', href: PLAY_STORE.developerUrl, external: true, searchTerms: [ 'android', 'play store', 'google play store' ] },
              // Temporary destination explicitly requested by the owner. This is
              // not an App Store listing or a claim that an iOS app is available.
              { label: 'iOS', href: PLAY_STORE.developerUrl, external: true, searchTerms: [ 'ios', 'iphone', 'ipad', 'apple', 'app store' ] },
            ],
          },
          {
            label: 'AI',
            searchTerms: [ 'with ai', 'artificial intelligence', 'assistant' ],
            children: [
              { label: 'ChatGPT', href: 'https://chatgpt.com/', external: true, searchTerms: [ 'ai', 'assistant', 'plugin', 'connect', 'openai' ] },
              { label: 'Claude', href: 'https://claude.ai/', external: true, searchTerms: [ 'ai', 'assistant', 'plugin', 'connect', 'anthropic' ] },
              { label: 'Gemini', href: 'https://gemini.google.com/', external: true, searchTerms: [ 'ai', 'assistant', 'plugin', 'connect', 'google' ] },
            ],
          },
        ],
      },
      {
        heading: 'Contact',
        nestedLinks: true,
        links: [
          { label: 'Contact us', href: '/contact/', match: '/contact' },
        ],
      },
      {
        heading: 'Legal Stuff',
        nestedLinks: true,
        collapsible: true,
        links: [
          { label: 'Terms', href: '/terms/', match: '/terms' },
          { label: 'Privacy', href: '/privacy/', match: '/privacy' },
        ],
      },
    ],
  },
];

const flattenMenuLinks = (): SearchableNavLink[] => {
  const result: SearchableNavLink[] = [];
  const push = ( link: NavLink, inheritedTerms: string[], nested = false ) => {
    const terms = [ ...inheritedTerms, ...( link.searchTerms || [] ) ];
    if ( link.href ) {
      result.push( {
        ...link,
        href: link.href,
        nested,
        description: NAV_DISCOVERY[ link.label ]?.[0],
        searchText: contentSearchText( [ link.label, ...terms, ...( NAV_DISCOVERY[ link.label ] || [] ) ] ),
      } );
    }
    for ( const child of link.children || [] ) push( child, [ ...terms, link.label ], true );
  };

  for ( const column of COLUMNS ) {
    for ( const section of column.sections ) {
      if ( section.headingHref ) {
        result.push( {
          label: section.heading,
          href: section.headingHref,
          match: section.headingMatch,
          searchText: section.heading.toLocaleLowerCase(),
        } );
      }
      for ( const link of section.links ) push( link, section.heading ? [ section.heading ] : [], section.nestedLinks === true );
    }
  }

  const seen = new Set<string>();
  return result.filter( link => {
    const key = link.href + '\n' + link.label;
    if ( seen.has( key ) ) return false;
    seen.add( key );
    return true;
  } );
};

const MENU_SEARCH_LINKS = flattenMenuLinks();
const menuSearchKey = ( link: Pick<NavLink, 'label' | 'href'> ) => `${link.href || ''}\n${link.label}`;


const PUBLIC_NAV_ID = 'public-navigation-menu';

const Header: React.FC = () => {
  const [ open, setOpen ] = useState( false );
  const [ query, setQuery ] = useState( '' );
  const [ familyOverrides, setFamilyOverrides ] = useState<Record<string, boolean>>( {} );
  const [ showProductsMore, setShowProductsMore ] = useState( false );
  const [ productsOverflowing, setProductsOverflowing ] = useState( false );
  const [ localizedSearchText, setLocalizedSearchText ] = useState<Record<string, string>>( {} );
  const router = useRouter();
  const quickSend = useCustomerMenuQuickSend();
  const rootRef = useRef<HTMLDivElement | null>( null );
  const triggerRef = useRef<HTMLButtonElement | null>( null );
  const hasOpened = useRef( false );

  const term = query.trim().toLocaleLowerCase();
  const searching = term.length > 0;

  // Search results come only from the menu graph. Family and section names are inherited
  // search terms, so "Elsewhere" returns Visa, Trip and Activities without a dead parent link.
  const filtered = useMemo( () => (
    searching
      ? rankNavigation( MENU_SEARCH_LINKS, term, link => localizedSearchText[ menuSearchKey( link ) ] || '' )
      : MENU_SEARCH_LINKS
  ), [ localizedSearchText, searching, term ] );

  // SupportWidget translates the public menu in-place after render. The canonical search graph
  // above deliberately stays English, so harvest the CURRENT rendered labels just before a query
  // changes the menu into its flat-results view. This makes translated destination, family and
  // section labels searchable without duplicating translations in navigation data or calling the
  // translation API from Header. data-nav-search-key remains stable because data attributes are
  // intentionally outside SupportWidget's translation allowlist.
  const syncLocalizedSearchText = useCallback( () => {
    const root = rootRef.current;
    if ( !root ) return;
    const aliases: Record<string, string> = {};
    for ( const anchor of Array.from( root.querySelectorAll<HTMLAnchorElement>( 'a[data-nav-search-key]' ) ) ) {
      const key = anchor.dataset.navSearchKey;
      if ( !key ) continue;
      const pieces = [ anchor.textContent || '' ];
      const family = anchor.closest<HTMLElement>( '.nav-tree-item[aria-label]' )?.getAttribute( 'aria-label' );
      if ( family ) pieces.push( family );
      const heading = anchor.closest<HTMLElement>( '.nav-group' )
        ?.querySelector<HTMLElement>( '.nav-group-label' )?.textContent;
      if ( heading ) pieces.push( heading );
      aliases[ key ] = pieces.join( ' ' ).toLocaleLowerCase();
    }
    setLocalizedSearchText( previous => {
      const next = { ...previous };
      for ( const [ key, value ] of Object.entries( aliases ) )
      {
        const prior = next[ key ] || '';
        // Preserve aliases harvested before the menu switched into flat search results.
        // Otherwise a translated family term (for example Elsewhere) is lost when a
        // translated child is searched first and React re-renders that child in English.
        next[ key ] = prior.includes( value ) ? prior : ( prior ? `${prior} ${value}` : value ).slice( -512 );
      }
      return next;
    } );
  }, [] );

  const applySearchQuery = useCallback( ( value: string ) => {
    syncLocalizedSearchText();
    setQuery( value.slice( 0, 120 ) );
  }, [ syncLocalizedSearchText ] );

  const close = useCallback( () => {
    setOpen( false );
    setQuery( '' );
    setFamilyOverrides( {} );
    setLocalizedSearchText( {} );
    setShowProductsMore( false );
    setProductsOverflowing( false );
  }, [] );

  // Derive the desktop panel width from its actual viewport position instead of a hard-coded
  // allowance for the brand lockup. This keeps the menu safe if the logo, type size, locale or
  // header spacing changes later. Mobile uses its fixed safe-area insets and ignores this value.
  const syncMenuAvailableWidth = useCallback( () => {
    if ( typeof window === 'undefined' ) return;
    const root = rootRef.current;
    if ( !root ) return;
    const box = root.getBoundingClientRect();
    const direction = window.getComputedStyle( root ).direction;
    const edgeGap = 24;
    const available = direction === 'rtl'
      ? box.right - edgeGap
      : window.innerWidth - box.left - edgeGap;
    root.style.setProperty( '--nav-menu-available-width', `${Math.max( 0, Math.floor( available ) )}px` );
  }, [] );

  useEffect( () => {
    if ( !open || typeof window === 'undefined' ) return undefined;
    syncMenuAvailableWidth();
    window.addEventListener( 'resize', syncMenuAvailableWidth );

    const observed = rootRef.current?.closest<HTMLElement>( '.hdr-in' ) || rootRef.current;
    const observer = typeof ResizeObserver !== 'undefined' && observed
      ? new ResizeObserver( syncMenuAvailableWidth )
      : null;
    if ( observer && observed ) observer.observe( observed );

    return () => {
      window.removeEventListener( 'resize', syncMenuAvailableWidth );
      observer?.disconnect();
    };
  }, [ open, syncMenuAvailableWidth ] );

  // Escape closes from anywhere, an outside pointerdown dismisses, AND the menu closes
  // when the mouse LEAVES it (hover-out), on owner request. None of these existed
  // originally: the menu could only be closed by clicking the trigger again or following
  // a link. Matches the language widget, so both menus answer to the same keys.
  useEffect( () => {
    if ( !open ) return undefined;
    const onKeyDown = ( event: KeyboardEvent ) => { if ( event.key === 'Escape' ) close(); };
    const onPointerDown = ( event: PointerEvent ) => {
      if ( rootRef.current && !rootRef.current.contains( event.target as Node ) ) close();
    };

    // HOVER-OUT CLOSE, mouse only. When the pointer leaves the dropdown the menu closes
    // after a short grace period. The grace (180ms) forgives a pointer that clips a
    // corner or crosses the 8px gap between the trigger and the panel - without it the
    // menu snaps shut on the smallest wobble and feels twitchy. A re-entry cancels the
    // pending close.
    // GUARDED TO FINE POINTERS (mouse/trackpad). On a touch screen there is no hover, and
    // a synthetic mouseleave fires on the tap that dismisses the on-screen keyboard or on
    // a scroll fling - closing the menu then would fight the user. matchMedia('(hover:hover)
    // and (pointer:fine)') is the standard capability query for "has a real hovering
    // pointer", and it is read at event time so a hybrid device that switches input modes
    // is handled correctly.
    let hoverCloseTimer = 0;
    const canHover = () =>
      typeof window.matchMedia === 'function'
      && window.matchMedia( '(hover: hover) and (pointer: fine)' ).matches;
    const onMouseLeave = () => {
      if ( !canHover() ) return;
      window.clearTimeout( hoverCloseTimer );
      hoverCloseTimer = window.setTimeout( close, 180 );
    };
    const onMouseEnter = () => window.clearTimeout( hoverCloseTimer );
    const root = rootRef.current;

    document.addEventListener( 'keydown', onKeyDown );
    document.addEventListener( 'pointerdown', onPointerDown );
    root?.addEventListener( 'mouseleave', onMouseLeave );
    root?.addEventListener( 'mouseenter', onMouseEnter );
    return () => {
      window.clearTimeout( hoverCloseTimer );
      document.removeEventListener( 'keydown', onKeyDown );
      document.removeEventListener( 'pointerdown', onPointerDown );
      root?.removeEventListener( 'mouseleave', onMouseLeave );
      root?.removeEventListener( 'mouseenter', onMouseEnter );
    };
  }, [ close, open ] );

  // Focus returns to the trigger on close, so a keyboard user is not dropped onto
  // <body> and made to tab from the top of the document again.
  useEffect( () => {
    if ( open ) { hasOpened.current = true; return; }
    if ( hasOpened.current ) triggerRef.current?.focus();
  }, [ open ] );

  // Exact selection uses the concrete browser URL when Next.js exposes it. Dynamic
  // /shop/[slug] pages share one router.pathname, so pathname alone can select more than
  // one menu row. asPath distinguishes Guided Resolution, Case Submission and Paperwork.
  const normalizePath = ( value?: string ) => {
    if ( !value || /^[a-z][a-z0-9+.-]*:/i.test( value ) ) return '';
    const path = value.split( /[?#]/, 1 )[ 0 ] || '/';
    return path === '/' ? '/' : ( path.replace( /\/+$/, '' ) || '/' );
  };
  const concretePath = normalizePath( router.asPath );
  const currentPath = concretePath || normalizePath( router.pathname );
  const isActive = ( link: NavLink ) => {
    if ( !link.href ) return false;
    // Orders is the only navigation destination. Customer template links are
    // actions even though their destination is the same clean /orders/ URL.
    if ( link.href === '/orders/' && link.label !== 'Orders' ) return false;
    const destination = normalizePath( link.href );
    if ( !destination ) return false;
    if ( concretePath ) return destination === currentPath;
    return link.match ? router.pathname === link.match : destination === currentPath;
  };

  // When the current page is low in the capped Products rail, opening the menu reveals it
  // immediately on every viewport. Desktop and mobile both show seven product rows now.
  useEffect( () => {
    if ( !open || searching || typeof window === 'undefined' ) return;
    const scroller = rootRef.current?.querySelector<HTMLElement>( '.nav-products-scroll' );
    const active = scroller?.querySelector<HTMLElement>( '.nav-item.active' );
    if ( !scroller || !active ) return;
    const box = scroller.getBoundingClientRect();
    const row = active.getBoundingClientRect();
    if ( row.top < box.top ) scroller.scrollTop -= box.top - row.top;
    else if ( row.bottom > box.bottom ) scroller.scrollTop += row.bottom - box.bottom;
  }, [ currentPath, open, searching ] );

  // The Products rail is intentionally capped at seven rows on desktop and mobile. A scrollbar
  // alone is easy to miss inside the menu, so expose one small icon-only continuation cue while
  // content remains below the fold. The cue is derived from real scroll geometry, not product
  // count, so it stays correct if row heights or the catalogue hierarchy change.
  useEffect( () => {
    if ( !open || searching || typeof window === 'undefined' ) {
      setShowProductsMore( false );
      setProductsOverflowing( false );
      return undefined;
    }
    const scroller = rootRef.current?.querySelector<HTMLElement>( '.nav-products-scroll' );
    if ( !scroller ) {
      setShowProductsMore( false );
      setProductsOverflowing( false );
      return undefined;
    }

    const update = () => {
      const overflow = scroller.scrollHeight - scroller.clientHeight > 2;
      const remaining = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
      setProductsOverflowing( overflow );
      setShowProductsMore( overflow && remaining > 2 );
    };

    update();
    scroller.addEventListener( 'scroll', update, { passive: true } );
    window.addEventListener( 'resize', update );
    return () => {
      scroller.removeEventListener( 'scroll', update );
      window.removeEventListener( 'resize', update );
    };
  }, [ currentPath, familyOverrides, open, searching ] );

  const scrollProductsForward = useCallback( () => {
    if ( typeof window === 'undefined' ) return;
    const scroller = rootRef.current?.querySelector<HTMLElement>( '.nav-products-scroll' );
    if ( !scroller ) return;

    const reduceMotion = typeof window.matchMedia === 'function'
      && window.matchMedia( '(prefers-reduced-motion: reduce)' ).matches;
    const rowHeight = window.matchMedia( '(max-width: 767px)' ).matches ? 52 : 46;
    scroller.scrollBy( {
      top: Math.max( rowHeight, scroller.clientHeight - rowHeight ),
      behavior: reduceMotion ? 'auto' : 'smooth',
    } );
  }, [] );

  // Internal destinations stay inside the site/WebView. In a Capacitor shell an external
  // destination is handed to the native browser instead of being trapped inside the WebView.
  const handleNavClick = useCallback( ( event: React.MouseEvent<HTMLAnchorElement>, link: NavLink ) => {
    const request = orderRequestForLabel( link.label );
    if ( isPrimaryMenuActivation( event ) && link.href === '/orders/' ) {
      // Explicit new navigation supersedes an interrupted selection. Selecting
      // a request is not permission to dispatch any earlier unsent invitation.
      if ( request ) {
        void takeCustomerMenuAction();
        stashOrderRequest( request.id );
      } else void takeOrderRequest();
    }
    const sendAction = menuActionForLabel( link.label );
    if ( sendAction && isPrimaryMenuActivation( event ) ) {
      // For an existing customer session, issue this explicit invitation HERE:
      // a detour through Orders and its hydration is not required for the send.
      // The shared hook owns the one-in-flight guard and fails closed on ambiguity.
      if ( quickSend.start( sendAction ) ) {
        event.preventDefault();
        close();
        return;
      }
      stashCustomerMenuAction( sendAction );
    }
    const capacitor = typeof window !== 'undefined'
      ? ( window as typeof window & { Capacitor?: { isNativePlatform?: () => boolean } } ).Capacitor
      : undefined;
    if ( link.external && link.href && capacitor?.isNativePlatform?.() ) {
      event.preventDefault();
      close();
      void import( '@capacitor/browser' )
        .then( ( { Browser } ) => Browser.open( { url: link.href! } ) )
        .catch( () => { window.location.href = link.href!; } );
      return;
    }
    close();
  }, [ close, quickSend.start ] );

  // NO renderLink() HELPER. The anchor markup is duplicated inline in both branches
  // below, on purpose, and it must stay that way.
  //
  // It was briefly a shared renderLink( link, extraClass ) helper, which silently
  // unstyled the entire menu. styled-jsx only attaches its scoping class to JSX it
  // can see statically inside the return tree; markup produced by a separate function
  // gets a different hash, so none of the .nav-item rules in the style block below
  // matched, and every row fell through to the unscoped global .nav-item in
  // Layout.css:659 - 15px at weight 560 with no lime hover and no active tint.
  //
  // This is the first trap in the design contract, and it is invisible to the tests:
  // 112 browser assertions passed while every row was unstyled, because they assert
  // text, href and aria-current and never read computed style. Only
  // CSS.getMatchedStylesForNode showed that the jsx rules were not matching at all.
  // menucheck.js asserts computed font-size, weight and the active background in Chromium,
  // Firefox and WebKit so this cannot recur silently.

  return (
    <header className={ router.pathname === '/' ? 'hdr is-home' : 'hdr' }>
      <div className="hdr-in">
        <div className="logo-nav">
          {/* Plain <a>, not next/link, for the same styled-jsx reason as Footer's lockup:
              styled-jsx does not scope capitalised components, so `<Link className="logo">`
              renders with no styles at all. Recorded in
              `.kiro/steering/grahak-os-design.md` (retired 2026-10-09, af7858fa). */}
          {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
          <a href="/" className="logo" aria-label="WECARE.DIGITAL home">
            <BrandLockup className="public-header" />
          </a>
          <div className="nav-dropdown" ref={ rootRef }>
            {/* This must stay the FIRST button in the header. Header.test.tsx reaches
                the trigger with container.querySelector('button') to assert the chevron
                is drawn rather than typed, so the search field below is an input and no
                control is added ahead of this element. */}
            <button
              ref={ triggerRef }
              type="button"
              className="nav-trigger"
              aria-label="Open navigation"
              aria-expanded={ open }
              aria-controls={ PUBLIC_NAV_ID }
              aria-keyshortcuts="Enter Space Escape"
              onClick={ () => {
                if ( open ) close();
                else {
                  syncMenuAvailableWidth();
                  setOpen( true );
                  setQuery( '' );
                }
              } }
            >
              <svg className="nav-trigger-icon" viewBox="5.45 5.75 13.1 13.1" aria-hidden="true" focusable="false">
                <path d="M7.41 8.59 12 13.17l4.59-4.58L18 10l-6 6-6-6z" />
              </svg>
            </button>
            <nav id={ PUBLIC_NAV_ID } className={ `nav-menu ${open ? 'open' : ''}` } aria-label="Public navigation">
              {/* Not autofocused. The language panel autofocuses its search because
                  searching is the only way to use it, but this menu is readable at a
                  glance - popping the on-screen keyboard over the whole catalogue on a
                  phone would cost more than it saves. */}
              <div className="nav-search-field">
                <input
                  className="nav-search"
                  type="search"
                  value={ query }
                  placeholder="Search products and services"
                  maxLength={ 120 }
                  aria-label="Search navigation"
                  onFocus={ syncLocalizedSearchText }
                  onChange={ event => applySearchQuery( event.target.value ) }
                  onKeyDown={ event => { if ( event.key === 'Escape' && query ) { event.preventDefault(); event.stopPropagation(); applySearchQuery( '' ); } } }
                />
                <SearchClearButton query={ query } onClear={ () => applySearchQuery( '' ) } />
                <VoiceSearchMic onTranscript={ applySearchQuery } />
              </div>

              {/* Flat results while searching: column headings over a filtered list
                  describe categories that are no longer all present, which reads as
                  missing items rather than as a narrowed list. */}
              { searching && (
                <>
                  <p className="nav-search-status" role="status" aria-live="polite" aria-atomic="true">
                    { filtered.length } menu { filtered.length === 1 ? 'result' : 'results' }.
                  </p>
                  <div className="nav-results">
                  { filtered.map( link => (
                    <a
                      key={ link.label + link.href }
                      href={ link.href }
                      data-nav-search-key={ menuSearchKey( link ) }
                      className={ `nav-item ${isActive( link ) ? 'active' : ''}`.trim() }
                      aria-current={ isActive( link ) ? 'page' : undefined }
                      onClick={ event => handleNavClick( event, link ) }
                    >
                      { link.nested ? (
                        <svg className="nav-sub-icon" viewBox={ SUBNAV_ICON_VIEW_BOX } aria-hidden="true" focusable="false">
                          <path d={ SUBNAV_ICON_PATH } />
                          <path className="nav-sub-dots" d={ SUBNAV_DOT_PATH } />
                        </svg>
                      ) : (
                        <svg
                          className={ `nav-row-icon ${FILLED_NAV_ICON_LABELS.has( link.label ) ? 'nav-row-icon-material' : ''}`.trim() }
                          viewBox={ navIconViewBox( link.label ) }
                          aria-hidden="true"
                          focusable="false"
                        >
                          <path d={ NAV_ICON_PATHS[ link.label ] || FALLBACK_NAV_ICON_PATH } />
                        </svg>
                      ) }
                      <span className="nav-item-label">{ link.label }{ link.description && <span className="nav-result-description">{ link.description }</span> }</span>
                    </a>
                  ) ) }
                  { !filtered.length && <div className="nav-empty"><p>No matching page. Try a service or product name.</p><div className="nav-suggestions">{ [ 'Visa', 'Invoice', 'Orders', 'Contact' ].map( suggestion => <button type="button" key={ suggestion } onClick={ () => applySearchQuery( suggestion ) }>{ suggestion }</button> ) }</div></div> }
                  </div>
                </>
              ) }

              { !searching && (
                <div className="nav-cols">
                  { COLUMNS.map( ( column, columnIndex ) => (
                    <div key={ columnIndex } className="nav-col">
                      { column.sections.map( ( section, sectionIndex ) => {
                        const isProducts = section.heading === 'Products';
                        const headingActive = Boolean(
                          section.headingHref && section.headingMatch && router.pathname === section.headingMatch
                        );
                        const sectionIconPath = SECTION_ICON_PATHS[ section.heading ];
                        const sectionId = `nav-section-${columnIndex}-${sectionIndex}`;
                        const sectionOpen = familyOverrides[ sectionId ] ?? section.links.some( isActive );
                        const label = section.heading && ( section.headingHref
                          ? (
                            <a
                              href={ section.headingHref }
                              data-nav-search-key={ menuSearchKey( { label: section.heading, href: section.headingHref } ) }
                              className={ `nav-group-label nav-group-link ${headingActive ? 'active' : ''}`.trim() }
                              aria-current={ headingActive ? 'page' : undefined }
                              onClick={ close }
                            >
                              { sectionIconPath ? (
                                <svg
                                  className={ `nav-section-icon ${MATERIAL_SECTION_ICON_LABELS.has( section.heading ) ? 'nav-section-icon-material' : ''}`.trim() }
                                  viewBox={ sectionIconViewBox( section.heading ) }
                                  aria-hidden="true"
                                  focusable="false"
                                >
                                  <path d={ sectionIconPath } />
                                </svg>
                              ) : null }
                              <span>{ section.heading }</span>
                            </a>
                          )
                          : section.collapsible ? (
                            <button type="button" className="nav-group-label nav-section-toggle"
                              aria-expanded={ sectionOpen } aria-controls={ sectionId }
                              onClick={ () => setFamilyOverrides( previous => ( { ...previous, [ sectionId ]: !sectionOpen } ) ) }>
                              { sectionIconPath ? (
                                <svg
                                  className={ `nav-section-icon ${MATERIAL_SECTION_ICON_LABELS.has( section.heading ) ? 'nav-section-icon-material' : ''}`.trim() }
                                  viewBox={ sectionIconViewBox( section.heading ) }
                                  aria-hidden="true"
                                  focusable="false"
                                >
                                  <path d={ sectionIconPath } />
                                </svg>
                              ) : null }
                              <span>{ section.heading }</span>
                              <svg className="nav-row-chevron" viewBox={ ROW_CHEVRON_VIEW_BOX } aria-hidden="true" focusable="false">
                                <path d={ ROW_CHEVRON_PATH } />
                              </svg>
                            </button>
                          ) : (
                            <span className="nav-group-label">
                              { sectionIconPath ? (
                                <svg
                                  className={ `nav-section-icon ${MATERIAL_SECTION_ICON_LABELS.has( section.heading ) ? 'nav-section-icon-material' : ''}`.trim() }
                                  viewBox={ sectionIconViewBox( section.heading ) }
                                  aria-hidden="true"
                                  focusable="false"
                                >
                                  <path d={ sectionIconPath } />
                                </svg>
                              ) : null }
                              <span>{ section.heading }</span>
                            </span>
                          )
                        );

                        const items = section.links.map( link => {
                          const familyOpen = familyOverrides[ link.label ] ?? Boolean( link.children?.some( isActive ) );
                          const familyId = `nav-family-${columnIndex}-${sectionIndex}-${link.label.toLowerCase().replace( /[^a-z0-9]+/g, '-' )}`;
                          return (
                          <div
                            key={ link.label + ( link.href || '' ) }
                            className={ `nav-tree-item ${link.children?.length ? 'has-children' : ''}`.trim() }
                            role={ link.children?.length ? 'group' : undefined }
                            aria-label={ link.children?.length ? link.label : undefined }
                          >
                            { link.href ? (
                              <a
                                href={ link.href }
                                data-nav-search-key={ menuSearchKey( link ) }
                                className={ `nav-item ${section.nestedLinks ? 'nav-child' : ''} ${isActive( link ) ? 'active' : ''}`.trim() }
                                aria-current={ isActive( link ) ? 'page' : undefined }
                                onClick={ event => handleNavClick( event, link ) }
                              >
                                { section.nestedLinks ? (
                                  <svg className="nav-sub-icon" viewBox={ SUBNAV_ICON_VIEW_BOX } aria-hidden="true" focusable="false">
                                    <path d={ SUBNAV_ICON_PATH } />
                                    <path className="nav-sub-dots" d={ SUBNAV_DOT_PATH } />
                                  </svg>
                                ) : (
                                  <svg
                                    className={ `nav-row-icon ${FILLED_NAV_ICON_LABELS.has( link.label ) ? 'nav-row-icon-material' : ''}`.trim() }
                                    viewBox={ navIconViewBox( link.label ) }
                                    aria-hidden="true"
                                    focusable="false"
                                  >
                                    <path d={ NAV_ICON_PATHS[ link.label ] || FALLBACK_NAV_ICON_PATH } />
                                  </svg>
                                ) }
                                <span className="nav-item-label">{ link.label }</span>
                                { link.children?.length ? (
                                  <svg className="nav-row-chevron" viewBox={ ROW_CHEVRON_VIEW_BOX } aria-hidden="true" focusable="false">
                                    <path d={ ROW_CHEVRON_PATH } />
                                  </svg>
                                ) : null }
                              </a>
                            ) : (
                              <button type="button" className="nav-item nav-family-label"
                                aria-expanded={ familyOpen } aria-controls={ familyId }
                                onClick={ () => setFamilyOverrides( previous => ( { ...previous, [ link.label ]: !familyOpen } ) ) }>
                                { (
                                  <svg
                                    className={ `nav-row-icon ${FILLED_NAV_ICON_LABELS.has( link.label ) ? 'nav-row-icon-material' : ''}`.trim() }
                                    viewBox={ navIconViewBox( link.label ) }
                                    aria-hidden="true"
                                    focusable="false"
                                  >
                                    <path d={ NAV_ICON_PATHS[ link.label ] || FALLBACK_NAV_ICON_PATH } />
                                  </svg>
                                ) }
                                <span className="nav-item-label">{ link.label }</span>
                                { link.children?.length ? (
                                  <svg className="nav-row-chevron" viewBox={ ROW_CHEVRON_VIEW_BOX } aria-hidden="true" focusable="false">
                                    <path d={ ROW_CHEVRON_PATH } />
                                  </svg>
                                ) : null }
                              </button>
                            ) }

                            { link.children?.length ? <div className="nav-family-children" id={ familyId } hidden={ !familyOpen }>
                            { link.children.map( child => child.href && (
                              <a
                                key={ child.label + child.href }
                                href={ child.href }
                                data-nav-search-key={ menuSearchKey( child ) }
                                className={ `nav-item nav-child ${isActive( child ) ? 'active' : ''}`.trim() }
                                aria-current={ isActive( child ) ? 'page' : undefined }
                                onClick={ event => handleNavClick( event, child ) }
                              >
                                <svg className="nav-sub-icon" viewBox={ SUBNAV_ICON_VIEW_BOX } aria-hidden="true" focusable="false">
                                  <path d={ SUBNAV_ICON_PATH } />
                                  <path className="nav-sub-dots" d={ SUBNAV_DOT_PATH } />
                                </svg>
                                <span className="nav-item-label">{ child.label }</span>
                              </a>
                            ) ) }
                            </div> : null }
                          </div>
                          );
                        } );

                        return (
                          <div key={ section.heading || sectionIndex } className={ `nav-group ${isProducts ? 'nav-group-products' : ''}`.trim() }>
                            { label }
                            { isProducts
                              ? (
                                <>
                                  <div className="nav-products-scroll">{ items }</div>
                                  { productsOverflowing && (
                                    <div className={ `nav-products-cue-row ${showProductsMore ? '' : 'is-hidden'}`.trim() }>
                                      <button
                                        type="button"
                                        className="nav-products-more"
                                        aria-label="Scroll to more products"
                                        aria-hidden={ !showProductsMore }
                                        tabIndex={ showProductsMore ? 0 : -1 }
                                        onClick={ scrollProductsForward }
                                      >
                                        <svg
                                          className="nav-products-more-icon"
                                          viewBox="188.18 -759.32 583.64 583.64"
                                          aria-hidden="true"
                                          focusable="false"
                                        >
                                          <path d="M480-200 240-440l42-42 198 198 198-198 42 42-240 240Zm0-253L240-693l42-42 198 198 198-198 42 42-240 240Z" />
                                        </svg>
                                      </button>
                                    </div>
                                  ) }
                                </>
                              )
                              : section.collapsible ? <div className="nav-section-children" id={ sectionId } hidden={ !sectionOpen }>{ items }</div> : items }
                          </div>
                        );
                      } ) }
                    </div>
                  ) ) }
                </div>
              ) }
            </nav>
          </div>
        </div>

        {/* THE SHOPPING BAG, AND IT MUST STAY AFTER .logo-nav IN THE DOM.
            Header.test.tsx reaches the menu trigger with container.querySelector('button') to
            assert the chevron is drawn rather than typed, so the trigger has to remain the FIRST
            button in this header. This control is an anchor, like the logo and every nav row, so
            it adds no button at all - but putting it earlier in the tree would still move the
            reading and tab order ahead of the brand.
            It paints itself: styled-jsx cannot scope a capitalised component, so the <style jsx>
            block below cannot reach it and HeaderCart owns its CSS, including the
            margin-inline-start:auto that pushes it to the end of this flex row. */}
        <HeaderCart />
      </div>
      { quickSend.error && (
        <div className="hdr-send-error" role="alert">
          <span>{ quickSend.error }</span>
          <button type="button" onClick={ quickSend.dismissError }>Dismiss</button>
        </div>
      ) }
      <style jsx>{`
        /* OPAQUE BY DEFAULT, translucent only where the blur actually works.
           It was rgba(255,255,255,.97) with backdrop-filter:blur(20px) unconditionally.
           Measured, backdrop-filter computes to the keyword none in environments that
           do not support it - and without the blur the 3% translucency is not a frosted
           effect, it is just bleed-through. On the marketing pages that is invisible
           because almost nothing scrolls under the header; on /terms/ and /privacy/,
           which are 40,000 characters of dense prose, lines were faintly legible
           through it and behind the logo.
           So the base rule is a solid #fff, and the translucent treatment is restored
           inside @supports where the blur it depends on is real. */
        /* THE TYPEFACE IS DECLARED HERE, not inherited, and that is the whole point of the
           line. The brand lockup had no font-family of its own: it took body's, which is set
           in src/styles/Layout.css. Nothing was visibly wrong - both stacks begin with Inter
           and measure identically (195.59px vs 195.59px at 800/23px, with Inter present AND
           with it blocked), and font-feature-settings is inherited so both already get Inter's
           cv02/cv03/cv04/cv11 variants. The reason to own it is that the brand mark's typeface
           should not depend on a global stylesheet a refactor could move: with that body rule
           absent the lockup falls to a serif at 98px while the h1 stays Inter at 106px,
           because the h1 declares its own stack. Observed, not imagined.

           This is index.tsx:797's declaration, byte for byte. A shared token both files
           reference would be better still, and is deliberately not done here - it is wider
           than this change. */
        /* inset-inline:0 for the symmetric left/right pair - identical in ltr, and it stops
           the bar being anchored to physical sides in a mirrored document. */
        .hdr{position:fixed;top:0;inset-inline:0;z-index:1001;background:#fff;
          font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif}
        /* Fail closed on an uncertain WhatsApp send: persistent and dismissible,
           not a transient success toast or an automatic retry. */
        .hdr-send-error{
          position:absolute;inset-block-start:calc(100% + 8px);inset-inline-end:16px;
          display:flex;align-items:center;gap:12px;box-sizing:border-box;
          width:min(420px,calc(100vw - 32px));padding:12px 14px;
          border:1px solid var(--public-brand-green);border-inline-start:4px solid var(--public-brand-lime);
          border-radius:12px;background:#fff;color:var(--public-brand-green);
          box-shadow:0 10px 30px rgba(26,58,42,.14);font-size:15px;line-height:1.45;
        }
        .hdr-send-error span{flex:1;min-inline-size:0;overflow-wrap:anywhere}
        .hdr-send-error button{
          flex:none;min-block-size:44px;padding:0 8px;
          border:0;background:transparent;color:inherit;font:inherit;font-weight:700;cursor:pointer;
        }
        .hdr-send-error button:focus-visible{outline:2px solid var(--public-brand-green);outline-offset:2px}
        @supports ((backdrop-filter:blur(20px)) or (-webkit-backdrop-filter:blur(20px))){
          .hdr{background:rgba(255,255,255,.97);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px)}
        }
        /* overflow-x:clip is ZOOM CONTAINMENT (unified-mobile Phase 1). The header is position:
           fixed, so its content is NOT clipped by html's overflow-x guard - at a 200%-zoom reflow
           to a ~160 CSS-px layout viewport the nowrap brand lockup (WECARE.DIGITAL ~158px) plus the
           46px menu trigger overflow the bar and let the PAGE scroll ~18px horizontally. Clipping
           on the x axis only (overflow-y stays visible, so this is not a scroll container) contains
           that without reflowing the lockup. The desktop mega-menu is position:absolute and
           width:min(760px,...), which fits inside this 1300px box, so it is not clipped; at
           max-width:767px it is position:fixed and escapes this box entirely. Normal-zoom layout is
           unchanged - nothing reaches the clip there. overflow-x:hidden is the clip fallback. NO
           backtick in this comment. */
        .hdr-in{max-width:var(--public-content-max);margin:0 auto;padding:18px 24px;display:flex;align-items:center;box-sizing:border-box;height:108px;min-width:0;overflow-x:hidden;overflow-x:clip}
        /* min-width:0 for the same reason as .logo-nav below: the brand lockup inside is nowrap,
           so this flex item would otherwise hold its full intrinsic width and keep the cluster
           from compressing at a 200%-zoom reflow. The overflow is absorbed by .hdr-in's
           overflow-x:clip, not reflowed onto the page. */
        .logo{display:flex;align-items:center;text-decoration:none;min-width:0}
        /* min-width:0 is the ZOOM-CONTAINMENT floor (unified-mobile Phase 1, unit 3). A flex item
           defaults to min-width:auto, which refuses to shrink below the intrinsic width of its
           content - here the nowrap brand lockup (WECARE.DIGITAL ~158px) plus the 46px menu
           trigger. Without this, .logo-nav keeps its full intrinsic width at a 200%-zoom reflow to
           a ~160 CSS-px layout viewport and, because .hdr-cart is pushed to the end with
           margin-inline-start:auto, the cart glyph's right edge is driven past the viewport
           (measured ~265px at a 160 CSS-px reflow) and the PAGE scrolls horizontally. min-width:0
           lets this cluster compress so the overflow lands inside .hdr-in's overflow-x:clip
           instead of reaching the page. max-width:100% keeps it from ever exceeding the row.
           Normal-zoom layout is unchanged - nothing reaches this floor there. */
        .logo-nav{display:flex;align-items:center;gap:10px;min-width:0;max-width:100%}
        .nav-dropdown{position:relative;min-width:0}
        /* SOFT NEUTRAL CHIP at rest, not a bare invisible button. It was
           background:none, so the chevron floated with no target - it read as
           decoration rather than a control. A soft #f4f7ee fill with a #e3ecc9
           hairline gives it a visible, tappable chip while staying quieter than the
           lime hover state below it. Hover/focus/expanded still brighten to the lime
           tint, so the interaction feedback is unchanged. */
        .nav-trigger{min-width:46px;min-height:46px;background:#f4f7ee;border:0;border-radius:10px;cursor:pointer;padding:8px;display:flex;align-items:center;justify-content:center;
          transition:background-color .18s ease}
        /* THE HOVER STATE INVERTS NOW, because the old one was not a state change at all.
           rgba(209,244,112,.22) over the white header composites to rgb(245,253,224), which
           measures 1.032:1 against this chip's own #f4f7ee - an RGB move of 15 out of a possible
           441. That is not a hover effect, it is a rounding error, and it is why the owner
           reported the menu icon as having none.

           WHY IT CANNOT SIMPLY BE MORE LIME. Lime is a LIGHT colour, so no lime fill can carry a
           state change on a near-white chip. Measured against #f4f7ee:
             rgba(209,244,112,.22)   1.03:1   (move 15)    <- what shipped
             solid #d1f470           1.15:1   (move 131)
             #1a3a2a                11.52:1  (move 349)
           Only an inversion produces a luminance step. Solid lime is a hue move: fine for most
           people, close to nothing for anyone with reduced colour discrimination.

           AND WHY NOT RECOLOUR THE CHEVRON ALONE, which was the narrower reading. On a chip this
           pale the glyph can only go to a colour that clears 3:1 on it - lime 1.15:1, amber
           1.88:1 and green 2.94:1 all fail, leaving blue 4.77:1, purple 4.35:1 or red 4.46:1.
           None of those mean anything in this palette and red reads as an error on a menu button,
           so a glyph-only colour change would have had to invent a hue. Inverting the chip lets
           the pairing that already exists - lime on dark green - do the work.

           The chip's resting border also firms up from #e3ecc9 (1.23:1 on white) to #cfe0a6, so
           the control reads as a button before it is touched; the fill is unchanged at 1.08:1,
           which is deliberate - this is chrome beside a wordmark, not a call to action.

           This icon-only iteration did not change the panel. The separate lime top border
           and rounded corners requested later live on .nav-menu below. */
        /* ROUND TWO: LIME FILL WITH A DARK EDGE, not a solid dark-green block.
           The inversion above was correct about the measurement and wrong about the mass. The
           owner's words on the shipped result were "on select too much green": filling all
           2116px² of a 46x46 chip with #1a3a2a makes the control the heaviest thing in a header
           whose other elements are a wordmark and text.

           Everything round one measured still holds and is why this is not a return to a tint.
           Against the #f4f7ee rest fill: rgba(209,244,112,.22) is 1.03:1 (RGB move 21/441) and
           solid #d1f470 is 1.15:1. A lime FILL cannot carry the state on its own.

           So the state is carried by the EDGE instead, and the fill is free to be lime - which is
           what "on" looks like everywhere else on this site. #1a3a2a against the resting #cfe0a6
           border measures 8.84:1, and it goes to 2px so the edge has weight to match the brighter
           fill. Three independent signals now say "open": the border darkens, the fill brightens,
           and the chevron rotates 45deg -> 225deg. Round one's objection to a hue-only move was
           that it says nothing to a visitor with reduced colour discrimination; a 8.84:1 edge and
           a rotation both survive that.

           Dark area drops from 2116px² to 352px², 16.6% of what shipped. The five options and
           their computed numbers are in docs/menu-icon-options.md, rendered by
           tools/browser/menuiconshots.js - this is G4.

           border-width IS transitioned. Without it the 1px -> 2px step snaps while the colours
           glide, which reads as two events. box-sizing is border-box (measured, not assumed:
           computed 46x46 outer at rest, hover and open), so the thicker border changes nothing
           outside the chip - the header stays 108px and the chip stays at x=210.34. */
        .nav-trigger:hover,.nav-trigger:focus-visible,.nav-trigger[aria-expanded='true']{
          background:var(--public-brand-lime);outline:none;
        }
        /* A TWO-TONE RING, because this control inverts on focus and a single-colour ring
           cannot work against both of its states.
           The ring was rgba(26,58,42,.2), which composites to rgb(200,209,199) over the
           header and measures 1.44:1 against it - under the 3:1 WCAG 1.4.11 asks of a focus
           indicator. Note the rule above also sets outline:none, so that faint shadow was
           the only ring present.
           Going opaque #1a3a2a alone does not fix it either: the :focus-visible rule above
           fills this chip with #1a3a2a, so a dark green ring drawn tight against a dark
           green chip has no edge at all - it just reads as a slightly bigger chip.
           So: a 2px white spacer first, then 3px of opaque #1a3a2a outside it. The white
           separates the ring from the inverted chip, and the dark green measures 12.48:1
           against the white header behind it. The same pair works if the chip is ever
           returned to its pale resting fill, which is what makes it the durable answer.
           The chip's own inversion still carries the state; this makes the ring carry it
           too, rather than relying on a colour change a low-vision visitor may not catch. */
        .nav-trigger:focus-visible{box-shadow:0 0 0 2px #fff,0 0 0 5px #1a3a2a}
        /* THE CHEVRON NO LONGER CHANGES COLOUR, and that is the simplification the lime fill
           buys. It had to flip to lime because the chip went dark underneath it; on a lime chip
           #1a3a2a measures 10.04:1, so the same dark glyph works in both states and there is one
           less thing moving. The rule that used to flip it to #d1f470 is gone rather than
           neutralised - a rule that sets a colour to the colour it already has is a thing the
           next reader has to work out. */
        /* 3px STROKES AND FULL OPACITY, because the previous "chunkier" change never rendered.
           The comment here used to say the strokes went from 2px to 2.5px so the arrow would stop
           reading as a hairline. MEASURED on the built page at devicePixelRatio 1:
           getComputedStyle(.nav-arrow).borderRightWidth was **2px**. A 2.5px border is rounded
           down to 2px on a 1x display, so the thickening existed only in the stylesheet and the
           glyph was still exactly the hairline it was meant to stop being. That is the likeliest
           reading of the owner's "menu icon is looking dull", and it is why this goes to a whole
           3px rather than nudging the fraction again - 3px cannot be rounded away.

           opacity:.85 is also gone. It was there to soften a dark glyph on a light ground, but it
           was softening the one element that carries the meaning; at full strength the chevron is
           11.52:1 on the resting chip and 10.04:1 on the lime one.

           NO LINES HERE, deliberately: a three-line burger was mocked in round one
           (docs/menu-mock/a4-three-lines.png) and the owner kept the chevron. */
        .nav-trigger-icon{margin:0;fill:#1a3a2a;transform:rotate(0deg);transition:transform .2s}
        .nav-trigger[aria-expanded='true'] .nav-trigger-icon{transform:rotate(180deg)}

        /* MEGA PANEL.
           WIDTH IS 760px, NOT THE PAGE MEASURE. It was first built at the site's
           1252px measure, which measured 1252x393 with its three columns only
           158/308/148px tall - a panel more than half empty, and it looked it. Twelve
           rows do not need the full page width. 760px is what the content asks for:
           the widest label, "Request Amendment" at 17px/600, needs ~210px of row, so
           three of those plus the 20px gutters and 14px padding comes to ~700px.
           Anchored left of the trigger rather than centred, because a narrow panel
           centred in the viewport under a left-aligned trigger reads as unrelated to
           it. min() against calc(100vw - 256px) is what stops the absolute
           positioning overflowing on a narrow window before the mobile rule takes
           over.

           DESKTOP WIDTH IS MEASURED FROM THE ACTUAL TRIGGER POSITION. Older versions
           subtracted a hard-coded 256px from 100vw to approximate the brand lockup plus
           trigger offset. That value broke whenever the lockup size changed. The component
           now writes --nav-menu-available-width from getBoundingClientRect(), keeps a 24px
           viewport gutter, and refreshes it while open on resize/header ResizeObserver.
           RTL measures from the opposite edge. The browser sweep still verifies that the
           resulting panel never leaves the viewport.

           max-height CLEARS THE WHATSAPP BUTTON GEOMETRICALLY, which is the only way
           to clear it. #wecarewa-widget is injected by an external script at
           z-index 2147483647, the maximum 32-bit integer, so nothing can ever be
           stacked above it - measured here, the full-height mobile panel ran straight
           through it and the green circle painted over the Customer service rows. The
           design contract records this for .wc-langbar; it applies to any floating
           panel. The measured footprint (60x60, 80px from the bottom) does not match
           the documented one (64x64, 120px), so the reserve clears the LARGER of the
           two plus a gap. overflow-y:auto is what keeps the rows reachable once the
           panel is capped.

           z-index is declared rather than left at auto. It cannot win against the
           widget above, but leaving it implicit meant the panel's stacking depended
           entirely on .hdr's context, which is fragile to reorder.

           Opening is driven ONLY by React state now. It used to also open on
           :hover and :focus-within, which meant the panel could be visible while
           aria-expanded was false - the arrow unrotated and a screen reader announcing
           it as collapsed. A mega panel appearing on an accidental mouse-over is also
           far more disruptive than a small dropdown was. */
        /* MAX-HEIGHT IS ANCHORED TO THE HEADER, and dvh rather than vh.
           It was calc(100vh - 320px). 320 corresponded to no element in this layout, and the
           failure needs a viewport that is WIDE and SHORT - rare on a phone or a laptop, and
           the normal shape of a folded-landscape device. Measured with the menu open:
             844x390  ->  70px of menu holding 700px of content
             880x360  ->  40px   (Z Flip 5, landscape)
             882x344  ->  24px   (Z Fold 5 cover, landscape)
             653x280  ->   0px   (Galaxy Fold folded, landscape) - the 32px box was padding
           Twenty links in a strip of chrome. 140 = the 108px header plus 32px of air, both
           nameable; dvh accounts for mobile browser chrome, the same unit fix index.tsx
           already made for .home-shell. Now: 280 -> 140px, 344 -> 204px, 360 -> 220px,
           390 -> 250px. See also the mobile override further down - BOTH carried a magic
           subtrahend and fixing only this one left the worst case untouched. */
        /* ANCHORED WITH A VARIABLE, for the specificity reason documented at length on
           .wc-langbar in SupportWidget.tsx. Short version: Lightning CSS rewrites any
           direction-conditional rule into a matched pair of :lang() rules, which adds a
           specificity class, so a logical inset here out-specified the mobile override below
           and pinned the panel to left:0 on phones where the media query asks for 16px.
           --nav-menu-inset is set once, overridden by the media query, and consumed by the
           two direction rules underneath.
           NO BACKTICKS IN THIS COMMENT: it sits inside a styled-jsx template literal, and a
           single backtick closes it - turning the rest of the stylesheet into JSX and failing
           the build hundreds of lines later with an unrelated-looking "Unexpected token". */
        /* Match the public checkout/auth card's rounded lime top accent without changing
           the menu's existing fill, shadow, positioning or scroll behavior. */
        .nav-menu{--nav-menu-inset:0px;position:absolute;top:calc(100% + 8px);left:var(--nav-menu-inset);right:auto;z-index:1002;width:min(760px,var(--nav-menu-available-width,760px));max-height:calc(100vh - 140px);max-height:calc(100dvh - 140px - var(--safe-bottom));overflow-y:auto;-webkit-overflow-scrolling:touch;touch-action:pan-y;background:#fcfdfb;border:1px solid var(--public-hairline);border-top:4px solid var(--public-brand-lime);border-radius:24px;padding:14px;opacity:0;visibility:hidden;transform:translateY(4px);transition:opacity .2s,transform .2s,visibility 0s linear .2s;box-shadow:0 8px 28px rgba(0,0,0,.10)}
        .nav-menu.open{opacity:1;visibility:visible;transform:translateY(0);transition:opacity .2s,transform .2s,visibility 0s}

        /* Search field. Sized off the language panel's input rather than a new set of
           numbers - same 42px row, same 10px radius, same focus ring - so the two
           search fields on the site are recognisably the same control. */
        /* THE SITE-WIDE SEARCH LOOK: borderless bottom hairline plus the shared lime voice mic. */
        .nav-search-field{position:relative;margin:0 0 12px}
        .nav-search{width:100%;margin:0;min-height:44px;box-sizing:border-box;border:0;border-bottom:1px solid var(--public-hairline);border-radius:0;background:transparent;padding-block:0;padding-inline:2px 44px;font-size:16px;font-weight:400;line-height:1.3;color:var(--public-body);font-family:inherit;outline:none;transition:border-color .2s,box-shadow .2s}
        .nav-search:not(:placeholder-shown){padding-inline-end:90px}
        .nav-search::-webkit-search-cancel-button,.nav-search::-webkit-search-decoration{display:none;-webkit-appearance:none}
        .nav-search::-ms-clear{display:none}
        .nav-search::placeholder{color:rgba(0,0,0,.42)}
        .nav-search:focus-visible{border-bottom-color:var(--public-brand-green);box-shadow:0 1px 0 0 var(--public-brand-lime)}

        /* Three equal columns with minmax(0,1fr) rather than 1fr: a bare 1fr uses
           min-content as its floor, so "Request Amendment" would force its column
           wider than a third and push the others narrow. */
        .nav-cols{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px 20px;align-items:start}
        .nav-col{display:flex;flex-direction:column;gap:10px;min-width:0}
        .nav-results{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:2px 20px}

        /* 12px/500 muted, matching the language panel's group label. A heading over
           menu items must read as a category and not as a disabled item, which is why
           it is well below the 19px the items themselves use. */
        .nav-group{display:flex;flex-direction:column}
        /* Section labels read as headers, not as faint disabled rows. They were
           rgba(0,0,0,.42) grey, weight 500, text-transform:none - so "Products",
           "Legal Stuff" etc. blended into the item names below them. Now #1a3a2a
           (the brand's deep green, NOT the grassy #3da35a a first pass used - that
           bright green clashed with the palette), weight 700, UPPERCASE, with a
           touch more tracking so the caps stay legible. */
        .nav-group-label{display:flex;align-items:center;gap:9px;min-height:var(--tap-min);box-sizing:border-box;padding:6px 12px;font-family:inherit;font-size:var(--public-nav-heading-size);font-weight:var(--public-nav-heading-weight);line-height:var(--public-nav-heading-leading);letter-spacing:.025em;color:var(--public-brand-green);text-transform:uppercase}
        .nav-group-label span{min-width:0;overflow-wrap:anywhere}
        /* Shared menu icon footprint, from section headings to child and search rows.
           The measured crops give each glyph approximately 22px of visible extent
           within its 24px slot, regardless of original SVG padding or units. */
        .nav-section-icon,.nav-row-icon,.nav-sub-icon,.nav-row-chevron,.nav-trigger-icon,.nav-products-more-icon{display:block;width:var(--public-nav-icon-size);height:var(--public-nav-icon-size);flex:0 0 var(--public-nav-icon-size)}
        .nav-section-icon,.nav-row-icon,.nav-sub-icon,.nav-row-chevron{fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
        .nav-section-icon path,.nav-row-icon path,.nav-sub-icon path,.nav-row-chevron path{vector-effect:non-scaling-stroke}
        .nav-section-icon-material,.nav-row-icon-material{fill:currentColor;stroke:none}
        .nav-sub-icon .nav-sub-dots{fill:currentColor;stroke:none}
        :global([dir='rtl']) .nav-sub-icon{transform:scaleX(-1)}

        /* PRODUCTS SCROLL. The catalogue is meant to reach 100+ entries, so Products
           keeps its own capped rail on desktop AND mobile. Desktop shows seven 46px rows;
           mobile shows seven 52px rows. On mobile the vertical scroll chain stays AUTO so a
           swipe can continue into the main menu after the Products rail reaches its end. */
        .nav-group-products{min-height:0}
        /* The heading stays PINNED above its own scrolling list. Sticky against the
           scroll container's top; the #fcfdfb backer stops list rows showing through the
           label as they pass under it. z-index clears the rows. */
        .nav-group-products .nav-group-label{position:sticky;top:0;z-index:2;background:#fcfdfb}
        .nav-products-scroll{
          /* Seven desktop rows. Mobile overrides only the row-height-derived ceiling
             (7 x 52px = 364px); the same overflow rail and continuation cue stay active. */
          max-height:322px;
          overflow-y:auto;
          -webkit-overflow-scrolling:touch;
          /* Contain the scroll chain so flicking the product list to its end does not
             then scroll the page behind the menu. */
          overscroll-behavior:contain;
          /* FULL COLUMN WIDTH so the lime scrollbar aligns with the right edge of the
             Home tab above it, plus a FAINT LIME TINT BOX so the bar reads as anchored to
             this list rather than floating in the empty space right of the short product
             names. The product labels are much narrower than the column, so a bare
             full-width bar looked detached; the tint (rgba(209,244,112,.08)) and the 10px
             radius give the scroll area a subtle surface the bar belongs to. This is the
             one place a background is used - it earns it because this is the only
             scrolling group; the static columns stay plain. */
          width:100%;
          padding:4px 8px 4px 0;
          background:rgba(209,244,112,.08);
          border-radius:10px;
          /* scrollbar-width STAYS and the colour does NOT. Gecko does not inherit
             scrollbar-width and the canonical block in src/styles/inner-ux.css declares it on
             html only, so dropping this line hands Firefox a system-default gutter inside the
             nav group. A LIME-THEMED SCROLLBAR WAS DELETED HERE: the Gecko half
             (scrollbar-color, a lime thumb on a transparent track) and the Blink half (four
             .nav-products-scroll::-webkit-scrollbar* rules, lime thumb, darker-lime hover,
             8px wide). A lime thumb is 1.18:1 on its own track, far under the 3:1 WCAG 1.4.11
             asks of a control boundary, and this nav mounts on every public page. The brand
             shows in the TRACK; the thumb is the --scrollbar-thumb token. Do not restore
             either half - src/test/ScrollbarDeclarations.test.ts pins the file set. */
          scrollbar-width:thin;
        }
        /* GOOGLE DOUBLE-DOWN CUE. The exact path comes from the Google Material icon supplied
           for this change. It lives in a dedicated row BELOW the scrolling list instead of
           floating over it, so product names can never sit underneath the affordance.
           The button keeps a 44px interaction target while the visible icon stays only 24px.
           There is no pill, circle, label or shadow: just the double chevron. */
        .nav-products-cue-row{height:46px;display:flex;align-items:center;justify-content:flex-end;flex:0 0 46px;margin-top:6px;padding-inline-end:4px;box-sizing:border-box}
        .nav-products-cue-row.is-hidden{visibility:hidden;pointer-events:none}
        .nav-products-more{display:flex;align-items:center;justify-content:center;width:46px;height:46px;min-width:46px;min-height:46px;padding:0;border:0;border-radius:50%;background:var(--public-brand-lime);color:#0f2a1d;cursor:pointer;transition:background-color .16s ease,transform .16s ease,box-shadow .16s ease}
        .nav-products-more:hover{background:#c5ed51;transform:translateY(-1px) scale(1.06);box-shadow:0 4px 12px rgba(26,58,42,.16)}
        .nav-products-more:focus-visible{outline:none;box-shadow:0 0 0 2px #fff,0 0 0 5px #1a3a2a}
        .nav-products-more-icon{fill:currentColor}
        /* The Customer service heading is a link, so it needs an affordance the plain
           headings do not have - without one it looks like the same inert label. */
        .nav-group-link{color:var(--public-brand-green);text-decoration:none;border-radius:8px}
        /* Split, same reason as .lgd-toc-link: this was one rule giving hover and
           focus-visible the same lime tint plus outline:none, so a keyboard user's only
           focus cue was a tint that composites to rgb(245,253,224) over white. The tint is
           a pointer affordance on hover; focus needs a ring that measures 3:1, and opaque
           #1a3a2a on the panel is 12.48:1. */
        .nav-group-link:hover{background:var(--public-lime-tint)}
        .nav-group-link:focus-visible{background:var(--public-lime-tint);outline:3px solid var(--public-brand-green);outline-offset:1px}
        .nav-empty{margin:0;padding:10px 12px 12px;font-size:14px;color:var(--public-muted)}
        .nav-search-status{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0}

        /* 15px/46px was undersized against a 108px header and a 24px brand lockup,
           and it sat below the 16-17px the global .nav-item rules use for the same
           control elsewhere. 19px puts the type-to-row ratio at ~2.8, near the
           2.5-ish a notion-style menu sits at, and keeps a deliberate step down from
           the 24px brand lockup instead of near-matching it.
           Nothing global was fighting this: the styled-jsx rule carries a jsx class,
           so it beats Layout.css's plain .nav-item on specificity, and
           inner-pages.css's .layout .nav-item block is empty and out of scope for the
           public header anyway.
           The row is 46px here, not the 54px of the old single column: three columns
           of 19px rows at 54px made the panel taller than the Customer service list needs,
           and 46px still clears the 44px minimum touch target. */
        /* position:relative so the divider hairline and the animated sweep (::after /
           ::before below) can be absolutely positioned within each row. */
        .nav-item{position:relative;display:flex;align-items:center;gap:9px;min-height:var(--public-nav-row-desktop);padding:0 12px;font-size:19px;font-weight:600;color:var(--public-brand-green);text-decoration:none;border-radius:var(--public-nav-radius)}
        .nav-row-chevron{margin-inline-start:auto;fill:currentColor;stroke:none}
        .nav-item-label{flex:1;min-width:0;white-space:normal;overflow-wrap:anywhere;line-height:1.25;padding-block:5px}
        /* ACTIVE AND HOVER MUST READ AS DIFFERENT STATES. They were both the same
           rgba(209,244,112,.22) pale tint, so the current page ("you are here") looked
           identical to whatever row the mouse was over - you could not tell which page
           you were on. Hover/focus is now a stronger-but-still-transparent tint (.38);
           the active row is SOLID #d1f470 with #0f2a1d type, which is the palette's
           own-surface treatment (.msg.sent, .tab.active) and unmistakably marks the
           current page. */
        /* Split, same reason. .38 is a stronger tint than the .22 above but still only
           reaches rgb(238,251,201) over white - darker than nothing, nowhere near 3:1, and
           outline:none removed the fallback. Tint on hover, opaque ring on focus. */
        .nav-item:not(.active):hover{background:var(--public-nav-hover)}
        .nav-item:focus-visible{outline:var(--public-focus-ring) solid var(--public-brand-green);outline-offset:1px}.nav-item:not(.active):focus-visible{background:var(--public-nav-hover)}
        .nav-item.active{font-weight:800;background:var(--public-brand-lime);color:#0f2a1d}
        /* DIVIDER LINE AFTER EACH ROW + a lime SWEEP on hover.
           ::after is the faint resting hairline (#f1f3ec - deliberately very light, so it
           separates rows without drawing attention). ::before is the lime accent that
           SWEEPS in on hover: scaleX(0)->(1) from the left, 0.2s, so a thin lime line
           draws left-to-right under the row. Inset 12px each side to line up with the row
           padding. Reduced-motion users get the end state with no transition. */
        /* inset-inline:12px collapses the symmetric pair. The ::before underline reveal grows
           with scaleX from transform-origin, which has no logical keyword, so the rtl case is
           stated explicitly - otherwise the underline would wipe in from the end of the line
           a right-to-left reader finishes on, reading as a retreat rather than a reveal. */
        .nav-item::after{content:'';position:absolute;inset-inline:12px;bottom:0;height:1px;background:linear-gradient(90deg,transparent 0,#e5eadc 12%,#e5eadc 88%,transparent 100%)}
        .nav-item::before{content:'';position:absolute;inset-inline:12px;bottom:0;height:2px;background:var(--public-brand-lime);opacity:0;transform:scaleX(.16);transform-origin:left center;transition:transform .22s cubic-bezier(.16,1,.3,1),opacity .14s ease}
        :global([dir='rtl']) .nav-item::before{transform-origin:right center}
        /* The desktop panel hangs off its trigger, so under rtl it has to hang off the other
           edge. Paired with the --nav-menu-inset base rule above. */
        :global([dir='rtl']) .nav-menu{left:auto;right:var(--nav-menu-inset)}
        .nav-item:not(.active):hover::before,.nav-item:not(.active):focus-visible::before{opacity:1;transform:scaleX(1)}
        /* The last row in a group has nothing after it, so no divider. */
        .nav-group > .nav-item:last-child::after,.nav-tree-item:last-child > .nav-item:last-child::after{display:none}
        @media(prefers-reduced-motion:reduce){.nav-item::before{transition:none}}
        /* Family children use the exact same 19px/600 navigation typography as their
           parent. Hierarchy is expressed by grouping and indentation, never smaller text. */
        .nav-tree-item.has-children + .nav-tree-item{margin-top:6px}
         .nav-family-label{box-sizing:border-box;width:100%;border:0;background:none;font-family:inherit;text-align:start;cursor:pointer}
        .nav-family-label[aria-expanded='true'] .nav-row-chevron,.nav-section-toggle[aria-expanded='true'] .nav-row-chevron{transform:rotate(90deg)}
        :global([dir='rtl']) .nav-family-label:not([aria-expanded='true']) .nav-row-chevron,:global([dir='rtl']) .nav-section-toggle:not([aria-expanded='true']) .nav-row-chevron{transform:scaleX(-1)}
        .nav-family-children[hidden],.nav-section-children[hidden]{display:none}
        .nav-section-toggle{width:100%;box-sizing:border-box;min-height:var(--tap-min);background:none;border:0;border-radius:var(--public-nav-radius);font-family:inherit;text-align:start;cursor:pointer}
        .nav-section-toggle span{flex:1;min-width:0;overflow-wrap:anywhere}
        .nav-section-toggle:hover{background:var(--public-nav-hover)}
        .nav-section-toggle:focus-visible{outline:var(--public-focus-ring) solid var(--public-brand-green);outline-offset:1px}
        .nav-result-description{display:block;font-size:var(--public-meta-size);font-weight:400;color:var(--public-muted);line-height:1.35;margin-top:3px}
        .nav-empty{grid-column:1/-1}.nav-empty p{margin:0 0 8px}
        .nav-suggestions{display:flex;flex-wrap:wrap;gap:8px}.nav-suggestions button{min-height:var(--tap-min);border:1px solid var(--public-hairline);border-radius:var(--public-nav-radius);background:var(--public-bg);padding:6px 12px;color:var(--public-brand-green);font:inherit;cursor:pointer}.nav-suggestions button:focus-visible{outline:var(--public-focus-ring) solid var(--public-brand-green);outline-offset:2px}
        .nav-child{font-size:19px;font-weight:600;min-height:var(--public-nav-row-desktop);padding-inline-start:24px;gap:8px}

        /* The panel breaks to fewer columns before the columns get too narrow to hold
           "Request Amendment" on one line. Measured rather than guessed: at 19px/17px
           the widest label needs ~210px of row, so three columns stop fitting inside
           the 1252px measure once the viewport is under ~820px. */
        @media(max-width:1024px){.nav-cols,.nav-results{grid-template-columns:repeat(2,minmax(0,1fr))}}
        /* NOTE: .hdr-in must stay the first rule inside this media query - Header.test
           asserts the literal string "@media(max-width:767px){.hdr-in{height:96px".
           Below 768px the panel is a single scrolling column pinned to the viewport
           with a 16px gutter, sitting just under the 96px mobile header. max-height
           plus overflow-y is what stops twelve rows running off the bottom of a
           phone - the old six-item dropdown never needed it. */
        /* The mobile panel spans the viewport, so it sets BOTH insets rather than the
           variable - symmetric, therefore direction-neutral, therefore no rtl override
           needed. It still has to beat the base rule's compiled :lang() selector, which the
           extra .hdr-in ancestor class does. */
        @media(max-width:767px){.hdr-in{height:96px;padding:14px 16px}.logo-nav{gap:8px}.hdr-in .nav-menu{position:fixed;top:100px;left:max(16px,var(--safe-left));right:max(16px,var(--safe-right));width:calc(100vw - max(16px,var(--safe-left)) - max(16px,var(--safe-right)));max-width:none;box-sizing:border-box;max-height:calc(100vh - 140px);max-height:calc(100dvh - 140px - var(--safe-bottom))}.nav-cols,.nav-results{grid-template-columns:minmax(0,1fr)}.nav-item,.nav-child{font-size:20px;font-weight:600;min-height:var(--public-nav-row-mobile)}.nav-products-scroll{max-height:364px;overflow-y:auto;overscroll-behavior:auto}.nav-products-cue-row{height:44px;flex-basis:44px;margin-top:4px}.nav-products-more{width:44px;height:44px;min-width:44px;min-height:44px}}

        /* ROOM FOR THE SHOPPING BAG ON THE NARROWEST DEVICE THAT SHIPS, derived rather than
           nudged. Measured on the built header at 280px (Galaxy Fold, folded) before the bag
           existed: the 16px gutter leaves a 248px content box, and .logo-nav occupies 212.8px of
           it, so 35.2px remained - 8.8px short of the 44px tap target devicecheck.js enforces on
           every header control.
           10px of gutter returns 12px and a 6px .logo-nav gap returns 2px, giving 49.2px: a 44px
           chip with 5.2px of air beside the menu trigger. Neither height moves, and the trigger
           stays 46x46 at border-box - both re-measured after this change.
           340px is RotatingHero's own narrow rung, reused so the site has one narrow breakpoint
           rather than a new one invented for the header. 344px (Z Fold cover) is above it and
           keeps the full 16px gutter, which is why the ceiling is 340 and not 360.
           padding-inline is symmetric, so Lightning CSS emits a plain left/right pair with no
           :lang() specificity class - it cannot out-specify the 767px rule above it, which is the
           trap documented on .nav-menu. */
        @media(max-width:340px){
          .hdr-in{padding-inline:10px}
          .logo-nav{gap:6px}
          /* Keep the 24px icon visible on Fold-width screens. Give long labels
             room to wrap instead of hiding their icons or shrinking tap targets. */
          .nav-item,.nav-child{font-size:18px;padding-inline:10px;gap:7px}
          .nav-group-label{padding-inline:10px;gap:7px}
          .nav-child{padding-inline-start:18px}
        }

        /* Home's edge-to-edge WebView trial: body already contributes the top
           safe inset to document content, but a fixed header sits outside that
           flow. Reserve it in the header itself and adjust its popup. Keep the
           existing desktop/phone heights and other route chrome unchanged. */
        .hdr.is-home{padding-top:var(--safe-top,0px)}
        .hdr.is-home .hdr-in{
          padding-left:max(var(--public-page-gutter),var(--safe-left,0px));
          padding-right:max(var(--public-page-gutter),var(--safe-right,0px));
        }
        .hdr.is-home .nav-menu{
          max-height:calc(100vh - 140px - var(--safe-top,0px) - var(--safe-bottom,0px));
          max-height:calc(100dvh - 140px - var(--safe-top,0px) - var(--safe-bottom,0px));
        }
        @media(max-width:767px){
          .hdr.is-home .hdr-in{
            padding-left:max(var(--public-mobile-page-gutter),var(--safe-left,0px));
            padding-right:max(var(--public-mobile-page-gutter),var(--safe-right,0px));
          }
          .hdr.is-home .hdr-in .nav-menu{top:calc(100px + var(--safe-top,0px))}
        }
        @media(max-width:340px){
          .hdr.is-home .hdr-in{padding-left:max(10px,var(--safe-left,0px));padding-right:max(10px,var(--safe-right,0px))}
        }

        @media(prefers-reduced-motion:reduce){
          .nav-menu{transition:none}
          .nav-trigger-icon{transition:none}
          .nav-products-more{transition:none}
        }
      `}</style>
    </header>
  );
};

export default Header;
