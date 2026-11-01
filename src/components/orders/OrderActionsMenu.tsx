import React, { useCallback, useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import VoiceSearchMic from '../VoiceSearchMic';
import { CUSTOMER_MENU_HREFS, isPrimaryMenuActivation, menuActionForLabel } from '../../lib/customerMenuActions';
import type { CustomerMenuAction } from '../../lib/customerMenuActions';

/**
 * The Orders history's per-row service navigation. Actions open the
 * authenticated Orders hub, without opening any individual order/receipt UI.
 * Subscribe, Review and Referral use a one-time explicit-click intent; no order ID or
 * phone is sent from the browser. Payment and ownership decisions remain server-owned.
 *
 * Icon paths match the public Header's Request menu (including its indented
 * shipment arrow); the filled Material paths retain their original 960px viewBox.
 * Keep these exact paths in sync with Header.tsx when the homepage icons change.
 */
const ICONS = {
  submit: {
    path: 'M200-120q-33 0-56.5-23.5T120-200v-560q0-33 23.5-56.5T200-840h360v80H200v560h560v-360h80v360q0 33-23.5 56.5T760-120H200Zm120-160v-80h320v80H320Zm0-120v-80h320v80H320Zm0-120v-80h320v80H320Zm360-80v-80h-80v-80h80v-80h80v80h80v80h-80v80h-80Z',
    viewBox: '0 -960 960 960', filled: true,
  },
  amend: {
    path: 'M5 19h4l10-10-4-4L5 15Zm8-12 4 4',
    viewBox: '0 0 24 24', filled: false,
  },
  docs: {
    path: 'M7 3h8l4 4v14H7ZM15 3v5h4M12 17V11m-3 3 3-3 3 3',
    viewBox: '0 0 24 24', filled: false,
  },
  vault: {
    path: 'M480-320 280-520l56-58 104 104v-326h80v326l104-104 56 58-200 200ZM240-160q-33 0-56.5-23.5T160-240v-120h80v120h480v-120h80v120q0 33-23.5 56.5T720-160H240Z',
    viewBox: '0 -960 960 960', filled: true,
  },
  shipments: {
    path: 'M3 7h11v10H3Zm11 4h4l3 3v3h-7ZM7 20a2 2 0 1 0 0-4 2 2 0 0 0 0 4Zm10 0a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z',
    viewBox: '0 0 24 24', filled: false,
  },
  subnav: {
    path: 'M6 7v5a5 5 0 0 0 5 5h7m-3-3 3 3-3 3',
    viewBox: '0 0 24 24', filled: false,
  },
  review: {
    path: 'M4 4h16v12H9l-5 4Zm4 5h8m-8 4h5',
    viewBox: '0 0 24 24', filled: false,
  },
  subscribe: {
    path: 'M12 21a2.5 2.5 0 0 0 2.4-2h-4.8A2.5 2.5 0 0 0 12 21Zm6-5H6l1.5-2V9a4.5 4.5 0 0 1 9 0v5Z',
    viewBox: '0 0 24 24', filled: false,
  },
  referral: {
    path: 'M18 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM6 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM18 22a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM8.7 10.6l6.6-3.3M8.7 13.4l6.6 3.3',
    viewBox: '0 0 24 24', filled: false,
  },
  rupee: {
    // The Indian rupee glyph, drawn as a vector to match the existing 20px menu icons.
    path: 'M6 3h12M6 8h12m-12 5 8.5 8M6 13h3M9 13c6.667 0 6.667-10 0-10',
    viewBox: '0 0 24 24', filled: false,
  },
} as const;

const REQUEST_SECTION_PATH = 'M6 3h12v18H6ZM9 7h6M9 11h6M9 15h4';
const CHEVRON_PATH = 'm9 6 6 6-6 6';

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
  { label: 'Contribute', subtitle: 'Give back', href: '/orders/',
    icon: 'rupee', keywords: 'contribute give back voluntary payment' },
];

type Props = {
  orderNumber: string;
  onInvite: ( action: CustomerMenuAction ) => void;
  inviteBusy: boolean;
};

export default function OrderActionsMenu ( { orderNumber, onInvite, inviteBusy }: Props ): React.ReactElement {
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
    const rect = triggerRef.current?.getBoundingClientRect();
    if ( !rect ) return;
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    const width = Math.min( 440, viewportWidth - 24 );
    const left = Math.max( 12, Math.min( rect.right - width, viewportWidth - width - 12 ) );
    const aboveSpace = rect.top - 16;
    const belowSpace = viewportHeight - rect.bottom - 16;

    if ( Math.max( aboveSpace, belowSpace ) < 220 ) {
      setPosition( { position: 'fixed', left, top: 12, width,
        maxHeight: Math.max( 120, viewportHeight - 24 ) } );
      return;
    }

    const showAbove = aboveSpace > belowSpace || aboveSpace > 450;
    setPosition( {
      position: 'fixed', left, width,
      maxHeight: Math.max( 160, Math.min( 520, ( showAbove ? aboveSpace : belowSpace ) - 8 ) ),
      ...( showAbove
        ? { bottom: viewportHeight - rect.top + 8 }
        : { top: rect.bottom + 8 } ),
    } );
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
      triggerRef.current?.focus();
    };
    const onScroll = ( event: Event ) => {
      if ( panelRef.current?.contains( event.target as Node ) ) return;
      reposition();
    };
    document.addEventListener( 'pointerdown', onPointerDown );
    document.addEventListener( 'keydown', onKeyDown );
    window.addEventListener( 'resize', reposition );
    window.addEventListener( 'scroll', onScroll, true );
    // Like the homepage menu, don't open the mobile keyboard on every tap.
    if ( window.matchMedia?.( '(hover: hover) and (pointer: fine)' ).matches ) {
      searchRef.current?.focus();
    }
    return () => {
      document.removeEventListener( 'pointerdown', onPointerDown );
      document.removeEventListener( 'keydown', onKeyDown );
      window.removeEventListener( 'resize', reposition );
      window.removeEventListener( 'scroll', onScroll, true );
    };
  }, [ open, reposition ] );

  const term = search.trim().toLocaleLowerCase();
  const matches = ( item: Action ) => !term || (
    item.label + ' ' + item.subtitle + ' ' + item.keywords
  ).toLocaleLowerCase().includes( term );
  const requests = REQUEST_ACTIONS.filter( matches );
  const shipments = SHIPMENT_ACTIONS.filter( matches );
  const other = OTHER_ACTIONS.filter( matches );
  const count = requests.length + shipments.length + other.length;

  const onNavigate = ( event: React.MouseEvent<HTMLAnchorElement>, action: Action ) => {
    // This row already has an authenticated customer token. Dispatch the
    // invitation on the deliberate click, not by reloading /orders/ and hoping
    // a sessionStorage handoff survives. All other actions retain their links.
    if ( !action.external && action.href === '/orders/' && isPrimaryMenuActivation( event ) ) {
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
              Native type=search retains the platform clear/close control. */}
          <div className="orm-search-field">
            <input ref={ searchRef } className="orm-search" type="search" value={ search }
              onChange={ event => setSearch( event.target.value ) }
              placeholder="Search" aria-label="Search order actions"
              autoComplete="off" />
            <VoiceSearchMic onTranscript={ setSearch } ariaLabel="Search order actions by voice" />
          </div>
          <div className="orm-section">
            <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
              <path d={ REQUEST_SECTION_PATH } />
            </svg>
            <span>Request</span>
          </div>
          <div className="orm-entries">
            { requests.map( action => (
              <a key={ action.label } href={ action.href } className="orm-item"
                onClick={ event => onNavigate( event, action ) }>
                <svg className={ ICONS[ action.icon ].filled ? 'orm-icon orm-icon-fill' : 'orm-icon' }
                  viewBox={ ICONS[ action.icon ].viewBox } aria-hidden="true" focusable="false">
                  <path d={ ICONS[ action.icon ].path } />
                </svg>
                <span className="orm-copy">
                  <span className="orm-title">{ action.label }</span>
                  <span className="orm-sub">{ action.subtitle }</span>
                </span>
                <svg className="orm-next" viewBox="0 0 24 24" aria-hidden="true">
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
                  <svg className="orm-next" viewBox="0 0 24 24" aria-hidden="true">
                    <path d={ CHEVRON_PATH } />
                  </svg>
                </div>
                { shipments.map( action => (
                  <a key={ action.label } href={ action.href } className="orm-item orm-child"
                    onClick={ event => onNavigate( event, action ) }>
                    <svg className="orm-icon orm-sub-icon" viewBox={ ICONS.subnav.viewBox }
                      aria-hidden="true" focusable="false">
                      <path d={ ICONS.subnav.path } />
                    </svg>
                    <span className="orm-copy">
                      <span className="orm-title">{ action.label }</span>
                      <span className="orm-sub">{ action.subtitle }</span>
                    </span>
                    <svg className="orm-next" viewBox="0 0 24 24" aria-hidden="true">
                      <path d={ CHEVRON_PATH } />
                    </svg>
                  </a>
                ) ) }
              </div>
            ) }
            { other.map( action => (
              <a key={ action.label } href={ action.href } className="orm-item"
                onClick={ event => onNavigate( event, action ) }>
                <svg className="orm-icon" viewBox={ ICONS[ action.icon ].viewBox }
                  aria-hidden="true" focusable="false">
                  <path d={ ICONS[ action.icon ].path } />
                </svg>
                <span className="orm-copy">
                  <span className="orm-title">{ action.label }</span>
                  <span className="orm-sub">{ action.subtitle }</span>
                </span>
                <svg className="orm-next" viewBox="0 0 24 24" aria-hidden="true">
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
          border:0;border-radius:10px;background:var(--public-brand-lime);
          color:var(--public-brand-green);cursor:pointer;
          transition:background-color .18s ease;
        }
        .orm-more svg{width:24px;height:24px;fill:currentColor}
        .orm-more:hover,.orm-more[aria-expanded='true']{
          background:var(--lime-hover);border:0;box-shadow:none;outline:none;
        }
        .orm-more:focus-visible{
          outline:2px solid var(--public-brand-green);outline-offset:2px;
        }
        .orm-menu{
          z-index:1200;box-sizing:border-box;overflow-y:auto;overscroll-behavior:contain;
          border:1px solid var(--public-hairline);
          border-block-start:4px solid var(--public-brand-lime);border-radius:24px;
          background:var(--public-bg);box-shadow:0 20px 52px rgba(20,48,28,.17);
          font-family:'Inter',ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
          color:var(--public-brand-green);text-align:start;white-space:normal;
          -webkit-overflow-scrolling:touch;
        }
        /* The Orders action search shares Header's 44px borderless field and
           its own VoiceSearchMic instance (same speech support, language and
           visual treatment as public navigation and blog search). */
        .orm-search-field{position:relative;margin:12px 16px 12px}
        .orm-search{
          width:100%;margin:0;min-height:44px;box-sizing:border-box;
          border:0;border-block-end:1px solid var(--public-hairline);
          border-radius:0;background:transparent;
          padding-block:0;padding-inline:2px 44px;
          font-size:16px;font-weight:400;line-height:1.3;
          color:var(--public-body);font-family:inherit;outline:none;
          transition:border-color .2s,box-shadow .2s;
        }
        .orm-search::placeholder{color:rgba(0,0,0,.42)}
        .orm-search:focus-visible{
          border-block-end-color:var(--public-brand-green);
          box-shadow:0 1px 0 0 var(--public-brand-lime);
        }
        .orm-section{display:flex;align-items:center;gap:7px;padding:5px 18px;
          font-size:12px;font-weight:700;letter-spacing:.06em;text-transform:uppercase}
        .orm-section svg{
          width:16px;height:16px;fill:none;stroke:currentColor;
          stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round;
        }
        .orm-entries{padding:0 10px 6px}
        .orm-item,.orm-family-title{
          position:relative;display:flex;align-items:center;gap:10px;
          min-block-size:50px;padding:7px 12px;border-radius:8px;
          color:var(--public-brand-green);text-decoration:none;
        }
        .orm-item:hover{background:var(--public-lime-tint)}
        .orm-item:focus-visible{
          background:var(--public-lime-tint);outline:3px solid var(--public-brand-green);
          outline-offset:0;
        }
        .orm-item::after,.orm-family-title::after{
          content:'';position:absolute;inset-inline:12px;bottom:0;
          height:1px;background:linear-gradient(90deg,transparent,#e5eadc 12%,#e5eadc 88%,transparent);
        }
        .orm-icon{
          inline-size:20px;block-size:20px;flex:none;fill:none;stroke:currentColor;
          stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round;
        }
        .orm-icon-fill{fill:currentColor;stroke:none}
        .orm-sub-icon{inline-size:17px;block-size:17px;opacity:.82}
        .orm-copy{min-inline-size:0;display:flex;flex:1;flex-direction:column;gap:1px}
        .orm-title{font-size:17px;line-height:1.25;font-weight:700;overflow-wrap:anywhere}
        .orm-sub{font-size:12px;line-height:1.35;font-weight:400;color:var(--public-muted)}
        .orm-next{
          inline-size:17px;block-size:17px;flex:none;fill:none;
          stroke:currentColor;stroke-width:1.9;
          stroke-linecap:round;stroke-linejoin:round;opacity:.65;
        }
        .orm-family-title{font-size:18px;font-weight:700;cursor:default}
        .orm-family-title span{flex:1}
        .orm-child{padding-inline-start:26px}
        .orm-empty{margin:0;padding:16px;font-size:14px;color:var(--public-muted)}
        .orm-footer{display:flex;justify-content:space-between;gap:12px;
          padding:12px 18px;background:var(--public-lime-tint);
          font-size:12px;font-weight:650}
        @media(max-width:480px){
          .orm-menu{border-radius:18px}
          .orm-title{font-size:16px}
          .orm-item,.orm-family-title{min-block-size:52px}
        }
      `}</style>
    </>
  );
}
