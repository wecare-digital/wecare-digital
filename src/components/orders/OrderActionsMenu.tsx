import React, { useCallback, useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import VoiceSearchMic from '../VoiceSearchMic';
import SearchClearButton from '../SearchClearButton';
import { authCountryPanelGeometry } from '../../lib/authCountryPanelGeometry';
import { CUSTOMER_MENU_HREFS, isPrimaryMenuActivation, menuActionForLabel } from '../../lib/customerMenuActions';
import type { CustomerMenuAction } from '../../lib/customerMenuActions';
import { orderRequestForLabel, orderRequestMenuHref, type OrderRequestId } from '../../lib/orderRequestSelection';
import { rankNavigation, NAV_DISCOVERY, contentSearchText } from '../../lib/navigationSearch';
import { NAV_ICON_PATHS, SECTION_ICON_PATHS, FILLED_NAV_ICON_LABELS, MATERIAL_SECTION_ICON_LABELS, navIconViewBox, sectionIconViewBox, SUBNAV_ICON_PATH, SUBNAV_DOT_PATH, SUBNAV_ICON_VIEW_BOX, ROW_CHEVRON_PATH, ROW_CHEVRON_VIEW_BOX } from '../../lib/publicNavigationIcons';

/**
 * The Orders history's per-row service navigation. Actions open the
 * authenticated Orders hub, without opening any individual order/receipt UI.
 * Subscribe, Review and Referral use a one-time explicit-click intent; no order ID or
 * phone is sent from the browser. Payment and ownership decisions remain server-owned.
 *
 * Reuse the public Header icon paths, optical crops and design tokens.
 */
const sharedIcon = ( label: string ) => ( {
  path: NAV_ICON_PATHS[ label ], viewBox: navIconViewBox( label ), filled: FILLED_NAV_ICON_LABELS.has( label ),
} );
const ICONS = {
  submit: sharedIcon( 'Submit Request' ),
  amend: sharedIcon( 'Request Amendment' ),
  docs: sharedIcon( 'Drop Docs' ),
  vault: sharedIcon( 'Vault' ),
  shipments: sharedIcon( 'Shipments' ),
  subnav: { path: SUBNAV_ICON_PATH, viewBox: SUBNAV_ICON_VIEW_BOX, filled: false },
  review: sharedIcon( 'Leave Review' ),
  subscribe: sharedIcon( 'Subscribe' ),
  referral: { path: SECTION_ICON_PATHS['Refer & Earn'], viewBox: sectionIconViewBox( 'Refer & Earn' ), filled: true },
  rupee: { path: 'M6 3h12M6 8h12m-12 5 8.5 8M6 13h3M9 13c6.667 0 6.667-10 0-10', viewBox: '2 1 22 22', filled: false },
} as const;

const REQUEST_SECTION_PATH = SECTION_ICON_PATHS.Request;
const CHEVRON_PATH = ROW_CHEVRON_PATH;

type IconName = keyof typeof ICONS;
type Action = {
  label: string;
  subtitle: string;
  href: string;
  icon: IconName;
  keywords: string;
  external?: boolean;
};

const REQUEST_ACTIONS: readonly Action[] = [
  { label: 'Submit Request', subtitle: 'Raise a request', href: '/orders/',
    icon: 'submit', keywords: 'request order product service' },
  { label: 'Request Amendment', subtitle: 'Change a request', href: '/orders/',
    icon: 'amend', keywords: 'amend modify edit request' },
  { label: 'Drop Docs', subtitle: 'Upload documents', href: '/orders/',
    icon: 'docs', keywords: 'documents upload files' },
  { label: 'Vault', subtitle: 'Access your files', href: '/orders/',
    icon: 'vault', keywords: 'secure download files' },
];

const SHIPMENT_ACTIONS: readonly Action[] = [
  { label: 'Track', subtitle: 'Track your shipment', href: '/orders/',
    icon: 'subnav', keywords: 'shipments tracking delivery shipping status' },
  { label: 'Pickup Request', subtitle: 'Arrange a pickup', href: '/orders/',
    icon: 'subnav', keywords: 'shipments courier pickup collect' },
];

const OTHER_ACTIONS: readonly Action[] = [
  { label: 'Leave Review', subtitle: 'Share feedback', href: CUSTOMER_MENU_HREFS['leave-review'],
    icon: 'review', keywords: 'review feedback rating' },
  { label: 'Subscribe', subtitle: 'Update your profile', href: CUSTOMER_MENU_HREFS.subscribe,
    icon: 'subscribe', keywords: 'profile address account' },
  { label: 'Referral', subtitle: 'Refer & earn', href: CUSTOMER_MENU_HREFS.referral,
    icon: 'referral', keywords: 'refer referral partner earn reward' },
  { label: 'Contribute', subtitle: 'Give back', href: CUSTOMER_MENU_HREFS.contribute,
    icon: 'rupee', keywords: 'contribute give back voluntary payment' },
];

type Props = {
  orderNumber: string;
  onInvite: ( action: CustomerMenuAction ) => void;
  inviteBusy: boolean;
  onRequest: ( id: OrderRequestId ) => void;
};

export default function OrderActionsMenu ( { orderNumber, onInvite, inviteBusy, onRequest }: Props ): React.ReactElement {
  const panelId = useId();
  const triggerRef = useRef<HTMLButtonElement>( null );
  const panelRef = useRef<HTMLDivElement>( null );
  const searchRef = useRef<HTMLInputElement>( null );
  const [ open, setOpen ] = useState( false );
  const [ search, setSearch ] = useState( '' );
  const [ position, setPosition ] = useState<React.CSSProperties | null>( null );

  // A portal is intentional: the Orders table scrolls horizontally on mobile.
  // An absolutely positioned menu inside its cell would be clipped by overflow-x:auto.
  const reposition = useCallback( () => {
    if ( typeof window === 'undefined' ) return;
    const trigger = triggerRef.current;
    if ( !trigger ) return;
    const rect = trigger.getBoundingClientRect();
    const viewport = window.visualViewport;
    const layoutWidth = document.documentElement.clientWidth || window.innerWidth;
    const layoutHeight = document.documentElement.clientHeight || window.innerHeight;
    setPosition( { position: 'fixed', ...authCountryPanelGeometry( {
      layoutWidth, layoutHeight,
      viewportLeft: viewport?.offsetLeft ?? 0,
      viewportTop: viewport?.offsetTop ?? 0,
      viewportWidth: viewport?.width ?? layoutWidth,
      viewportHeight: viewport?.height ?? layoutHeight,
      anchor: rect,
      rtl: getComputedStyle( trigger ).direction === 'rtl',
    } ) } );
  }, [] );

  useEffect( () => {
    if ( !open ) return undefined;
    reposition();
    const onPointerDown = ( event: PointerEvent ) => {
      const target = event.target as Node;
      if ( !triggerRef.current?.contains( target ) && !panelRef.current?.contains( target ) ) {
        setOpen( false );
      }
    };
    const onKeyDown = ( event: KeyboardEvent ) => {
      if ( event.key !== 'Escape' ) return;
      setOpen( false );
      triggerRef.current?.focus( { preventScroll: true } );
    };
    const onScroll = ( event: Event ) => {
      if ( event.target instanceof Node && panelRef.current?.contains( event.target ) ) return;
      reposition();
    };
    document.addEventListener( 'pointerdown', onPointerDown );
    document.addEventListener( 'keydown', onKeyDown );
    window.addEventListener( 'resize', reposition );
    window.addEventListener( 'scroll', onScroll, true );
    window.visualViewport?.addEventListener( 'resize', reposition );
    window.visualViewport?.addEventListener( 'scroll', reposition );
    // Like the homepage menu, don't open the mobile keyboard on every tap.
    if ( window.matchMedia?.( '(hover: hover) and (pointer: fine)' ).matches ) {
      searchRef.current?.focus();
    }
    return () => {
      document.removeEventListener( 'pointerdown', onPointerDown );
      document.removeEventListener( 'keydown', onKeyDown );
      window.removeEventListener( 'resize', reposition );
      window.removeEventListener( 'scroll', onScroll, true );
      window.visualViewport?.removeEventListener( 'resize', reposition );
      window.visualViewport?.removeEventListener( 'scroll', reposition );
    };
  }, [ open, reposition ] );

  const term = search.trim().toLocaleLowerCase();
  const matching = ( items: readonly Action[] ) => !term ? items : rankNavigation( items.map( item => ( { ...item, searchText: contentSearchText( [ item.label, item.subtitle, item.keywords, ...( NAV_DISCOVERY[ item.label ] || [] ) ].filter( ( value ): value is string => typeof value === 'string' ) ) } ) ), term );
  const requests = matching( REQUEST_ACTIONS );
  const shipments = matching( SHIPMENT_ACTIONS );
  const other = matching( OTHER_ACTIONS );
  const count = requests.length + shipments.length + other.length;

  const onNavigate = ( event: React.MouseEvent<HTMLAnchorElement>, action: Action ) => {
    // This row already has an authenticated customer token. Dispatch the
    // invitation on the deliberate click, not by reloading /orders/ and hoping
    // a sessionStorage handoff survives. All other actions retain their links.
    if ( !action.external && action.href === '/orders/' && isPrimaryMenuActivation( event ) ) {
      const request = orderRequestForLabel( action.label );
      if ( request ) {
        event.preventDefault();
        onRequest( request.id );
        setOpen( false );
        setSearch( '' );
        return;
      }
      const sendAction = menuActionForLabel( action.label );
      if ( sendAction ) {
        event.preventDefault();
        onInvite( sendAction );
      }
    }
    setOpen( false );
    setSearch( '' );
    // Mirror Header's external-link handling in the Capacitor app.
    const capacitor = typeof window === 'undefined'
      ? undefined
      : ( window as typeof window & {
          Capacitor?: { isNativePlatform?: () => boolean };
        } ).Capacitor;
    if ( !action.external || !capacitor?.isNativePlatform?.() ) return;
    event.preventDefault();
    void import( '@capacitor/browser' )
      .then( ( { Browser } ) => Browser.open( { url: action.href } ) )
      .catch( () => { window.location.href = action.href; } );
  };

  return (
    <>
      <button
        ref={ triggerRef }
        type="button"
        disabled={ inviteBusy }
        aria-busy={ inviteBusy ? true : undefined }
        className="orm-more"
        aria-label={ 'More actions for ' + ( orderNumber || 'this order' ) }
        title="More order actions"
        aria-haspopup="dialog"
        aria-expanded={ open }
        aria-controls={ panelId }
        onClick={ () => {
          if ( open ) { setOpen( false ); return; }
          setSearch( '' );
          reposition();
          setOpen( true );
        } }
      >
        <svg aria-hidden="true" focusable="false" viewBox="0 0 24 24">
          <circle cx="5" cy="12" r="1.6" />
          <circle cx="12" cy="12" r="1.6" />
          <circle cx="19" cy="12" r="1.6" />
        </svg>
      </button>

      { open && position && typeof document !== 'undefined' && createPortal(
        <div ref={ panelRef } id={ panelId } className="orm-menu"
          role="dialog" aria-label="Order actions" style={ position }>
          {/* Same borderless search + shared microphone as Header and BlogSearch.
              Use the shared explicit clear control instead of browser-specific icons. */}
          <div className="orm-search-field" data-public-search-field="compact">
            <input ref={ searchRef } className="orm-search" type="search" value={ search }
              onChange={ event => setSearch( event.target.value.slice( 0, 120 ) ) }
              onKeyDown={ event => { if ( event.nativeEvent.isComposing ) return; if ( event.key === 'Escape' && search ) { event.preventDefault(); event.stopPropagation(); setSearch( '' ); } } }
              placeholder="Search actions" maxLength={ 120 } aria-label="Search order actions"
              autoComplete="off" />
            <SearchClearButton query={ search } onClear={ () => setSearch( '' ) } />
            <VoiceSearchMic onTranscript={ value => setSearch( value.slice( 0, 120 ) ) } ariaLabel="Search order actions by voice" />
          </div>
          <div className="orm-section">
            <svg className={ MATERIAL_SECTION_ICON_LABELS.has( 'Request' ) ? 'orm-section-icon-fill' : undefined } viewBox={ sectionIconViewBox( 'Request' ) } aria-hidden="true" focusable="false">
              <path d={ REQUEST_SECTION_PATH } />
            </svg>
            <span>Request</span>
          </div>
          <div className="orm-entries">
            { requests.map( action => (
              <a key={ action.label } href={ orderRequestMenuHref( action.label, action.href ) } className="orm-item"
                onClick={ event => onNavigate( event, action ) }>
                <svg className={ ICONS[ action.icon ].filled ? 'orm-icon orm-icon-fill' : 'orm-icon' }
                  viewBox={ ICONS[ action.icon ].viewBox } aria-hidden="true" focusable="false">
                  <path d={ ICONS[ action.icon ].path } />
                </svg>
                <span className="orm-copy">
                  <span className="orm-title">{ action.label }</span>
                  <span className="orm-sub">{ action.subtitle }</span>
                </span>
                <svg className="orm-next" viewBox={ ROW_CHEVRON_VIEW_BOX } aria-hidden="true">
                  <path d={ CHEVRON_PATH } />
                </svg>
              </a>
            ) ) }
            { shipments.length > 0 && (
              <div className="orm-family" role="group" aria-label="Shipments">
                <div className="orm-family-title">
                  <svg className="orm-icon" viewBox={ ICONS.shipments.viewBox } aria-hidden="true">
                    <path d={ ICONS.shipments.path } />
                  </svg>
                  <span>Shipments</span>
                  <svg className="orm-next" viewBox={ ROW_CHEVRON_VIEW_BOX } aria-hidden="true">
                    <path d={ CHEVRON_PATH } />
                  </svg>
                </div>
                { shipments.map( action => (
                  <a key={ action.label } href={ orderRequestMenuHref( action.label, action.href ) } className="orm-item orm-child"
                    onClick={ event => onNavigate( event, action ) }>
                    <svg className="orm-icon orm-sub-icon" viewBox={ ICONS.subnav.viewBox }
                      aria-hidden="true" focusable="false">
                      <path d={ ICONS.subnav.path } />
                      <path className="orm-sub-dots" d={ SUBNAV_DOT_PATH } />
                    </svg>
                    <span className="orm-copy">
                      <span className="orm-title">{ action.label }</span>
                      <span className="orm-sub">{ action.subtitle }</span>
                    </span>
                    <svg className="orm-next" viewBox={ ROW_CHEVRON_VIEW_BOX } aria-hidden="true">
                      <path d={ CHEVRON_PATH } />
                    </svg>
                  </a>
                ) ) }
              </div>
            ) }
            { other.map( action => (
              <a key={ action.label } href={ orderRequestMenuHref( action.label, action.href ) } className="orm-item"
                onClick={ event => onNavigate( event, action ) }>
                <svg className={ ICONS[ action.icon ].filled ? 'orm-icon orm-icon-fill' : 'orm-icon' } viewBox={ ICONS[ action.icon ].viewBox }
                  aria-hidden="true" focusable="false">
                  <path d={ ICONS[ action.icon ].path } />
                </svg>
                <span className="orm-copy">
                  <span className="orm-title">{ action.label }</span>
                  <span className="orm-sub">{ action.subtitle }</span>
                </span>
                <svg className="orm-next" viewBox={ ROW_CHEVRON_VIEW_BOX } aria-hidden="true">
                  <path d={ CHEVRON_PATH } />
                </svg>
              </a>
            ) ) }
            { count === 0 && (
              <p className="orm-empty" role="status">No matching actions.</p>
            ) }
          </div>
          <div className="orm-footer">
            <span>For this order</span>
            <span role="status" aria-live="polite">
              { count } { count === 1 ? 'action' : 'actions' }
            </span>
          </div>
        </div>,
        document.body
      ) }

      <style jsx>{`
        .orm-more{
          box-sizing:border-box;inline-size:44px;min-inline-size:44px;
          block-size:44px;min-block-size:44px;display:inline-flex;
          align-items:center;justify-content:center;padding:0;
          border:0;border-radius:var(--public-hover-radius);background:var(--public-lime-tint);
          color:var(--public-brand-green);cursor:pointer;
          transition:background-color .18s ease;
        }
        .orm-more svg{width:var(--public-nav-icon-size);height:var(--public-nav-icon-size);fill:currentColor}
        @media (hover:hover) and (pointer:fine){.orm-more:hover:not(:disabled){background:var(--public-button-hover)}}
        .orm-more[aria-expanded='true']{background:var(--public-lime-tint);box-shadow:inset 0 -2px 0 var(--public-brand-green)}
        .orm-more:disabled{opacity:.6;cursor:not-allowed}
        .orm-more:focus-visible{
          outline:2px solid var(--public-brand-green);outline-offset:2px;
        }
        .orm-menu{
          z-index:1200;box-sizing:border-box;overflow-y:auto;overflow-x:hidden;overscroll-behavior:contain;
          border:1px solid var(--public-hairline);border-radius:var(--public-popover-radius,8px);
          background:var(--public-bg);box-shadow:0 6px 20px rgba(26,58,42,.10);
          font-family:'Inter',ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
          color:var(--public-brand-green);text-align:start;white-space:normal;
          -webkit-overflow-scrolling:touch;
        }
        /* The Orders action search shares Header's 44px borderless field and
           its own VoiceSearchMic instance (same speech support, language and
           visual treatment as public navigation and blog search). */
        .orm-search-field{position:relative;margin:8px 8px 6px;min-width:0}
        .orm-search{
          width:100%;margin:0;min-height:var(--public-search-compact-height);box-sizing:border-box;
          border:0;border-block-end:2px solid var(--public-search-underline);
          border-radius:var(--public-hover-radius);background:transparent;
          padding-block:0;padding-inline:10px var(--public-search-end-padding,44px);
          font-size:16px;font-weight:400;line-height:1.3;
          color:var(--public-body);font-family:inherit;outline:none;
          transition:border-color .2s,box-shadow .2s;
        }
        .orm-search:not(:placeholder-shown){padding-inline-end:90px;padding-inline-end:var(--public-search-end-padding,90px)}
        .orm-search::-webkit-search-cancel-button,.orm-search::-webkit-search-decoration{display:none;-webkit-appearance:none}
        .orm-search::-ms-clear{display:none}
        .orm-search::placeholder{color:var(--public-muted)}
        .orm-search:focus-visible{
          border-block-end-color:var(--public-search-underline);
          box-shadow:var(--public-search-focus-shadow);
        }
        .orm-section{display:flex;align-items:center;gap:9px;padding:6px 22px;min-height:var(--tap-min);box-sizing:border-box;
          font-family:inherit;font-size:var(--public-nav-heading-size);font-weight:var(--public-nav-heading-weight);line-height:var(--public-nav-heading-leading);letter-spacing:.025em;color:var(--public-brand-green);text-transform:uppercase}
        .orm-section svg{
          width:var(--public-nav-icon-size);height:var(--public-nav-icon-size);flex:none;fill:none;stroke:currentColor;
          stroke-width:var(--public-nav-stroke);stroke-linecap:round;stroke-linejoin:round;
        }
        .orm-section .orm-section-icon-fill{fill:currentColor;stroke:none}
        .orm-entries{padding:0 6px 6px}
        .orm-item,.orm-family-title{
          position:relative;display:flex;align-items:center;gap:10px;
          min-block-size:48px;padding:7px 10px;border-radius:var(--public-nav-radius);
          color:var(--public-brand-green);text-decoration:none;
        }
        @media (hover:hover) and (pointer:fine){.orm-item:hover{background:var(--public-nav-hover)}}
        .orm-item:focus-visible{
          background:var(--public-nav-hover);outline:var(--public-focus-ring) solid var(--public-brand-green);
          outline-offset:0;
        }
        .orm-item::after,.orm-family-title::after{
          content:'';position:absolute;inset-inline:12px;bottom:0;
          height:1px;background:linear-gradient(90deg,transparent,#e5eadc 12%,#e5eadc 88%,transparent);
        }
        .orm-icon{
          inline-size:var(--public-nav-icon-size);block-size:var(--public-nav-icon-size);flex:none;fill:none;stroke:currentColor;
          stroke-width:var(--public-nav-stroke);stroke-linecap:round;stroke-linejoin:round;
        }
        .orm-icon-fill{fill:currentColor;stroke:none}
        .orm-icon path,.orm-section path,.orm-next path{vector-effect:non-scaling-stroke}
        .orm-sub-icon{color:var(--public-nav-arrow)}
        .orm-sub-dots{fill:currentColor;stroke:none}
        :global([dir='rtl']) .orm-sub-icon{transform:scaleX(-1)}
        .orm-copy{min-inline-size:0;display:flex;flex:1;flex-direction:column;gap:1px}
        .orm-title{font-size:17px;line-height:1.25;font-weight:700;overflow-wrap:anywhere}
        .orm-sub{font-size:12px;line-height:1.35;font-weight:400;color:var(--public-muted)}
        .orm-next{
          inline-size:var(--public-nav-icon-size);block-size:var(--public-nav-icon-size);flex:none;fill:var(--public-nav-arrow);
          stroke:none;
        }
        :global([dir='rtl']) .orm-next{transform:scaleX(-1)}
        .orm-family-title{font-size:18px;font-weight:700;cursor:default}
        .orm-family-title span{flex:1}
        .orm-child{padding-inline-start:26px}
        .orm-empty{margin:0;padding:16px;font-size:14px;color:var(--public-muted)}
        .orm-footer{display:flex;justify-content:space-between;gap:12px;
          padding:12px 18px;background:var(--public-lime-tint);
          font-size:12px;font-weight:650}
        @media(max-width:480px){
          .orm-title{font-size:16px}
          .orm-item,.orm-family-title{min-block-size:var(--public-nav-row-mobile)}
        }
        /* The 280px acceptance fixture caught a clipped voice-search target.
           Reserve a separate row for both compact controls rather than squeeze
           them beside the editable input. This also fits the 160px stress case. */
        @media(max-width:359px){
          .orm-search-field{display:flex;flex-wrap:wrap;gap:8px;align-items:center;justify-content:flex-end}
          .orm-search-field > .orm-search{flex:0 0 100%;inline-size:100%;min-inline-size:0}
          .orm-search-field > :global(button.public-search-clear),
          .orm-search-field > :global(button.voice-search-mic){position:static;inset:auto;transform:none;flex:0 0 46px;inline-size:46px;min-inline-size:46px;block-size:46px;min-block-size:46px}
        }
        @media(max-width:279px){
          .orm-item,.orm-family-title{gap:6px;padding-inline:6px}
          .orm-child{padding-inline-start:14px}
          .orm-section{padding-inline:10px}
          .orm-footer{flex-wrap:wrap;padding-inline:10px}
        }
      `}</style>
    </>
  );
}
