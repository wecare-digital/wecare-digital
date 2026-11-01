import React, { useCallback, useEffect, useRef, useState } from 'react';
import { publicActionText } from '../lib/publicActionNotices';
import { useOptionalPublicToast } from './public/PublicToastProvider';
import { useOptionalToastContext } from '../contexts/ToastContext';
import { CUSTOMER_MENU_HREFS, isPrimaryMenuActivation, stashCustomerMenuAction } from '../lib/customerMenuActions';
import { CONTRIBUTION_AMOUNT_LABEL } from '../config/contribution';
import { whatsappShareHref } from '../config/share';
import { symbol } from '../config/materialSymbols';

/**
 * The compact page-tail action dock.
 *
 * _app renders this once for every public HTML surface, including Home.
 * Preserve the owner-approved Stay connected layout and Contribute dropdown.
 * Checkout uses the same one-time authenticated Orders action handoff as Subscribe.
 * The Orders server hook currently fails closed until the exact native payment
 * price and invoice policy is aligned; this control does not charge or send itself.
 * Opening /orders/ or refreshing it never creates a send intent.
 */
export interface PublicShareProps {
  /** Override the shared URL. Defaults to the clean current URL after hydration. */
  url?: string;
  /** Override the shared title. Defaults to document.title after hydration. */
  title?: string;
  /** Share dropdown title / tooltip. Defaults to Share. */
  label?: string;
}

type OpenMenu = 'contribute' | 'share' | null;

const cleanUrl = ( href: string ): string => {
  try {
    const u = new URL( href );
    return `${u.origin}${u.pathname}`;
  } catch {
    return href;
  }
};

const PublicShare: React.FC<PublicShareProps> = ( {
  url,
  title,
  label = 'Share',
} ) => {
  const publicToast = useOptionalPublicToast();
  const workspaceToast = useOptionalToastContext();
  const showToast = publicToast?.showToast;
  const workspaceSuccess = workspaceToast?.success;
  const workspaceError = workspaceToast?.error;
  const [ resolvedUrl, setResolvedUrl ] = useState( url || '' );
  const [ resolvedTitle, setResolvedTitle ] = useState( title || '' );
  const [ openMenu, setOpenMenu ] = useState<OpenMenu>( null );
  const [ canNativeShare, setCanNativeShare ] = useState( false );
  const [ canCopy, setCanCopy ] = useState( false );

  const rootRef = useRef<HTMLElement | null>( null );
  const contributeTriggerRef = useRef<HTMLButtonElement | null>( null );
  const shareTriggerRef = useRef<HTMLButtonElement | null>( null );

  useEffect( () => {
    if ( typeof window === 'undefined' ) return;
    const canonical = document.querySelector<HTMLLinkElement>( 'link[rel="canonical"]' )?.href || '';
    const ogTitle = document.querySelector<HTMLMetaElement>( 'meta[property="og:title"]' )?.content || '';
    const nextUrl = url || ( canonical ? cleanUrl( canonical ) : cleanUrl( window.location.href ) );
    const nextTitle = title || ogTitle || document.title || window.location.hostname;
    setResolvedUrl( nextUrl );
    setResolvedTitle( nextTitle );

    const payload = { title: nextTitle, text: nextTitle, url: nextUrl };
    const native =
      typeof navigator !== 'undefined'
      && typeof navigator.share === 'function'
      && ( typeof navigator.canShare !== 'function' || navigator.canShare( payload ) );

    setCanNativeShare( native );
    setCanCopy(
      typeof navigator !== 'undefined'
      && !!navigator.clipboard
      && window.isSecureContext
    );
  }, [ url, title ] );

  useEffect( () => {
    if ( !openMenu || typeof document === 'undefined' ) return undefined;

    const onPointerDown = ( event: PointerEvent ) => {
      const root = rootRef.current;
      if ( root && !root.contains( event.target as Node ) ) setOpenMenu( null );
    };

    const onKeyDown = ( event: KeyboardEvent ) => {
      if ( event.key !== 'Escape' ) return;
      const closing = openMenu;
      setOpenMenu( null );
      if ( closing === 'contribute' ) contributeTriggerRef.current?.focus();
      if ( closing === 'share' ) shareTriggerRef.current?.focus();
    };

    document.addEventListener( 'pointerdown', onPointerDown );
    document.addEventListener( 'keydown', onKeyDown );
    return () => {
      document.removeEventListener( 'pointerdown', onPointerDown );
      document.removeEventListener( 'keydown', onKeyDown );
    };
  }, [ openMenu ] );

  const toggleMenu = useCallback( ( menu: Exclude<OpenMenu, null> ) => {
    setOpenMenu( current => current === menu ? null : menu );
  }, [] );

  const onNativeShare = useCallback( () => {
    if ( typeof navigator === 'undefined' || typeof navigator.share !== 'function' ) return;
    setOpenMenu( null );
    navigator.share( {
      title: resolvedTitle,
      text: resolvedTitle,
      url: resolvedUrl,
    } ).catch( () => {
      /* Cancellation is a normal outcome of the system share sheet. */
    } );
  }, [ resolvedTitle, resolvedUrl ] );

  const onCopy = useCallback( async () => {
    if ( !resolvedUrl || typeof navigator === 'undefined' || !navigator.clipboard ) return;
    try {
      await navigator.clipboard.writeText( resolvedUrl );
      // Copy feedback has one owner: the mounted public or Workspace toast host.
      // Do not also replace the button label, icon or accessible name with "Copied".
      if ( showToast ) showToast( 'success', { durationMs: 2500 } );
      else workspaceSuccess?.( publicActionText( 'success' ) );
    } catch {
      if ( showToast ) showToast( 'failure', { durationMs: 3500 } );
      else workspaceError?.( publicActionText( 'failure' ) );
    }
  }, [ resolvedUrl, showToast, workspaceSuccess, workspaceError ] );

  const shareMenuClass = 'ps-menu ps-share-menu has-contribute';

  return (
    <section
      className="public-share has-contribute"
      aria-label="Contribute, subscribe and share"
      ref={ rootRef }
    >
      {/* "Stay connected" eyebrow kept on top of the dock (owner request). Carried over from the
          retired PublicFooterBand so the app-owned dock keeps the same visible label on every public route. */}
      <span className="ps-kicker">Stay connected</span>
      <div className="ps-row">
        <section className="contribute" aria-labelledby="ps-contribute-heading">
            <h2 className="ps-sr-only" id="ps-contribute-heading">Contribute</h2>
            <button
              ref={ contributeTriggerRef }
              type="button"
              className="ps-action ps-contribute"
              aria-label={ `Contribute ${CONTRIBUTION_AMOUNT_LABEL}` }
              aria-expanded={ openMenu === 'contribute' }
              aria-controls="ps-contribute-menu"
              onClick={ () => toggleMenu( 'contribute' ) }
            >
              <span className="ps-material" aria-hidden="true">{ symbol( 'currency_rupee' ) }</span>
              <span className="ps-tip" aria-hidden="true">Contribute</span>
            </button>
        </section>

        <a
          className="ps-action ps-subscribe"
          href={ CUSTOMER_MENU_HREFS.subscribe }
          aria-label="Subscribe on WhatsApp through Orders"
          onClick={ event => {
            // Queue a single authenticated invitation only for a deliberate click.
            // Modified/new-tab navigation must never send a message in this tab.
            if ( isPrimaryMenuActivation( event ) ) stashCustomerMenuAction( 'subscribe' );
          } }
        >
          <span className="ps-material" aria-hidden="true">{ symbol( 'notifications_active' ) }</span>
          <span className="ps-tip" aria-hidden="true">Subscribe</span>
        </a>

        <button
          ref={ shareTriggerRef }
          type="button"
          className="ps-action ps-share-trigger"
          aria-label="Share this page"
          aria-expanded={ openMenu === 'share' }
          aria-controls="ps-share-menu"
          onClick={ () => toggleMenu( 'share' ) }
        >
          <span className="ps-material" aria-hidden="true">{ symbol( 'share' ) }</span>
          <span className="ps-tip" aria-hidden="true">{ label }</span>
        </button>
      </div>

      <div
          className={ openMenu === 'contribute' ? 'ps-menu ps-contribute-menu is-open' : 'ps-menu ps-contribute-menu' }
          id="ps-contribute-menu"
          hidden={ openMenu !== 'contribute' }
        >
          <div className="ps-menu-head">
            <div className="ps-menu-title contribute-label">
              { `Contribute ${CONTRIBUTION_AMOUNT_LABEL}` }
            </div>
            <p className="ps-menu-sub">Give back</p>
          </div>

          <div className="ps-menu-list">
            <a
              href={ CUSTOMER_MENU_HREFS.contribute }
              className="ps-menu-item"
              onClick={ event => {
                // Queue only on the deliberate click; Orders owns authentication
                // and consumes this intent once after the /auth/ round-trip.
                if ( isPrimaryMenuActivation( event ) ) stashCustomerMenuAction( 'contribute' );
              } }
              aria-label="Checkout contribution"
            >
              <span className="ps-menu-icon" aria-hidden="true">
                <span className="ps-material">{ symbol( 'shopping_cart_checkout' ) }</span>
              </span>
              <span className="ps-menu-copy">
                <span className="ps-menu-name">Checkout</span>
                <span className="ps-menu-note">Review, then pay on WhatsApp</span>
              </span>
              <span className="ps-material ps-chevron" aria-hidden="true">{ symbol( 'chevron_right' ) }</span>
            </a>
          </div>
      </div>

      <div
        className={ openMenu === 'share' ? `${shareMenuClass} is-open` : shareMenuClass }
        id="ps-share-menu"
        hidden={ openMenu !== 'share' }
      >
        <div className="ps-menu-head">
          <div className="ps-menu-title">{ label }</div>
          <p className="ps-menu-sub">Send or copy this page.</p>
        </div>

        <div className="ps-menu-list">
          <a
            className="ps-menu-item"
            href={ whatsappShareHref( resolvedTitle, resolvedUrl ) }
            target="_blank"
            rel="noopener noreferrer"
            aria-label="Share this page on WhatsApp"
          >
            <span className="ps-menu-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24" focusable="false">
                <path fill="currentColor" d="M17.47 14.38c-.3-.15-1.76-.87-2.03-.97-.27-.1-.47-.15-.67.15-.2.3-.77.97-.94 1.16-.17.2-.35.22-.64.08-.3-.15-1.26-.46-2.4-1.48-.88-.79-1.48-1.76-1.65-2.06-.17-.3-.02-.46.13-.61.13-.13.3-.35.45-.52.15-.17.2-.3.3-.5.1-.2.05-.37-.03-.52-.07-.15-.67-1.61-.91-2.21-.24-.58-.49-.5-.67-.51h-.57c-.2 0-.52.07-.8.37-.27.3-1.03 1.02-1.03 2.48 0 1.46 1.06 2.87 1.21 3.07.15.2 2.1 3.2 5.08 4.49.71.3 1.26.49 1.69.62.71.23 1.36.2 1.87.12.57-.09 1.76-.72 2-1.41.25-.7.25-1.29.18-1.42-.08-.12-.28-.2-.57-.35M12.05 21.79h-.01a9.87 9.87 0 01-5.03-1.38l-.36-.21-3.74.98 1-3.65-.24-.37a9.86 9.86 0 01-1.51-5.26C2.16 6.45 6.6 2.01 12.05 2.01c2.64 0 5.12 1.03 6.99 2.9a9.83 9.83 0 012.89 6.99c0 5.45-4.44 9.89-9.88 9.89M20.46 3.49A11.82 11.82 0 0012.05 0C5.5 0 .16 5.34.16 11.89c0 2.1.55 4.14 1.59 5.95L.06 24l6.3-1.65a11.88 11.88 0 005.69 1.45c6.55 0 11.89-5.34 11.89-11.89 0-3.18-1.24-6.17-3.48-8.42z" />
              </svg>
            </span>
            <span className="ps-menu-copy">
              <span className="ps-menu-name">WhatsApp</span>
              <span className="ps-menu-note">Share on WhatsApp</span>
            </span>
            <span className="ps-material ps-chevron" aria-hidden="true">{ symbol( 'chevron_right' ) }</span>
          </a>

          { canNativeShare && (
            <button
              type="button"
              className="ps-menu-item"
              onClick={ onNativeShare }
              aria-label="Share this page using another app"
            >
              <span className="ps-menu-icon" aria-hidden="true">
                <span className="ps-material">{ symbol( 'ios_share' ) }</span>
              </span>
              <span className="ps-menu-copy">
                <span className="ps-menu-name">More apps</span>
                <span className="ps-menu-note">Choose another app</span>
              </span>
              <span className="ps-material ps-chevron" aria-hidden="true">{ symbol( 'chevron_right' ) }</span>
            </button>
          ) }

          { canCopy && (
            <button
              type="button"
              className="ps-menu-item"
              onClick={ onCopy }
              aria-label="Copy link to this page"
            >
              <span className="ps-menu-icon" aria-hidden="true">
                <span className="ps-material">{ symbol( 'link' ) }</span>
              </span>
              <span className="ps-menu-copy">
                <span className="ps-menu-name">Copy link</span>
                <span className="ps-menu-note">Copy page link</span>
              </span>
              <span className="ps-material ps-chevron" aria-hidden="true">{ symbol( 'chevron_right' ) }</span>
            </button>
          ) }
        </div>
      </div>

      <style jsx>{`
        .public-share{
          position:relative;width:100%;margin-top:32px;padding:12px 0 28px;
          box-sizing:border-box;
          font-family:var(--font-sans);
        }
        .public-share.has-contribute{margin-top:32px}
        /* "Stay connected" eyebrow, on top of the dock. Same green lime pill the retired
           PublicFooterBand used. 17px/700 so the label matches the prominence of the eyebrows on
           Home / Grahak OS / the closing band, rather than reading smaller than them. */
        .ps-kicker{
          /* flex (not inline-flex) + width:max-content keeps the pill shrink-wrapped to its
             text while forcing it onto its own line, so the margin below reliably opens a gap
             between the eyebrow and the Contribute/Subscribe/Share icon row. */
          display:flex;width:max-content;max-width:100%;align-items:center;
          min-height:32px;padding:0 14px;margin:0 0 18px;
          border-radius:999px;background:var(--public-brand-lime);color:var(--public-brand-green);
          font-size:17px;font-weight:700;line-height:1;
        }
        /* flex-wrap only takes effect when three 48px buttons cannot fit, which is a 200%-zoom
           layout on a 320px phone (128px of row): the third button sat 16px off-screen. */
        .ps-row{display:flex;flex-wrap:wrap;align-items:center;gap:12px;width:max-content;max-width:100%}
        .contribute{margin:0;padding:0;border:0;position:static}
        .ps-action{
          position:relative;width:48px;height:48px;box-sizing:border-box;border-radius:50%;
          border:2px solid var(--public-hairline);background:#fff;color:var(--public-brand-green);
          display:inline-flex;align-items:center;justify-content:center;padding:0;flex:0 0 auto;
          cursor:pointer;text-decoration:none;
          transition:background-color .18s,border-color .18s,transform .18s,box-shadow .18s;
        }
        .ps-action:hover{
          border-color:var(--public-brand-green);background:var(--public-brand-lime);transform:translateY(-2px);
          box-shadow:0 4px 12px rgba(26,58,42,.10);
        }
        /* Keep the round rupee icon consistent with Subscribe and Share. The dropdown
           intentionally makes no price or checkout promise while fulfillment is pending. */
        .ps-contribute{background:#eef7d6;border-color:var(--public-brand-green)}
        .ps-subscribe{background:var(--public-brand-lime);border-color:var(--public-brand-green)}
        .ps-subscribe:hover{background:#fff}
        .ps-action:active{transform:translateY(0)}
        .ps-action:focus-visible,.ps-menu-item:focus-visible{
          outline:3px solid var(--public-brand-green);outline-offset:3px;
        }
        .ps-material{
          font-family:'Material Symbols Rounded';font-weight:normal;font-style:normal;
          font-size:25px;line-height:1;letter-spacing:normal;text-transform:none;
          white-space:nowrap;word-wrap:normal;direction:ltr;
          -webkit-font-feature-settings:'liga';font-feature-settings:'liga';
          -webkit-font-smoothing:antialiased;
          font-variation-settings:'FILL' 0,'wght' 500,'GRAD' 0,'opsz' 24;
        }
        .ps-tip{
          position:absolute;inset-inline-start:50%;bottom:calc(100% + 9px);
          transform:translateX(-50%) translateY(4px);
          padding:6px 9px;border-radius:8px;background:var(--public-brand-green);color:#fff;
          white-space:nowrap;font-size:14px;font-weight:650;line-height:1.2;
          opacity:0;pointer-events:none;z-index:40;
          transition:opacity .15s,transform .15s;
        }
        .ps-action:hover .ps-tip,.ps-action:focus-visible .ps-tip{
          opacity:1;transform:translateX(-50%) translateY(0);
        }

        /* ANCHORED TO THE BOTTOM OF THE BUTTON ROW, not a fixed offset. top was 82px (78px on
           phones), set before #761 put the "Stay connected" eyebrow above the row and pushed the
           row down 50px, so every menu opened over the lower ~30px of the button that opened it -
           measured on the live site at 320-430px. 100% of this padding box is the bottom of the
           row plus the block's bottom padding (28px, 24px on phones), so 100% - 18px is 10px
           below the row, and it follows the row when the buttons wrap at 200% zoom. */
        .ps-menu{
          position:absolute;top:calc(100% - 18px);inset-inline-start:0;z-index:30;
          width:min(340px,calc(100vw - 48px));padding:8px;
          background:#fff;border:1px solid var(--public-hairline);border-radius:18px;
          box-shadow:0 18px 46px rgba(26,58,42,.13);box-sizing:border-box;
        }
        .ps-menu[hidden]{display:none}
        .ps-menu::before{
          content:'';position:absolute;top:-6px;width:12px;height:12px;
          background:#fff;border-inline-start:1px solid var(--public-hairline);border-top:1px solid var(--public-hairline);
          transform:rotate(45deg);
        }
        .ps-contribute-menu::before{inset-inline-start:18px}
        .ps-share-menu::before{inset-inline-start:78px}
        .ps-share-menu.has-contribute::before{inset-inline-start:138px}
        .ps-menu-head{padding:9px 11px 10px;border-bottom:1px solid #f0f1ed}
        .ps-menu-title{margin:0;color:#1a1a1a;font-size:18px;font-weight:700;line-height:1.3}
        .ps-menu-sub{margin:4px 0 0;color:var(--public-muted);font-size:15px;font-weight:500;line-height:1.4}
        .ps-menu-list{padding-top:6px}
        .ps-menu-item{
          width:100%;min-height:56px;display:grid;
          grid-template-columns:38px minmax(0,1fr) 20px;gap:10px;align-items:center;
          padding:7px 10px;border:0;border-radius:12px;background:#fff;color:var(--public-brand-green);
          text-decoration:none;cursor:pointer;text-align:start;box-sizing:border-box;
          font:inherit;
        }
        .ps-menu-item:hover{background:#f7fbe9}
        .ps-menu-item:disabled{opacity:.55;cursor:default}
        /* The Contribute Checkout action retains the approved dock layout.
           Authentication and any future payment request belong to Orders. */
        .ps-menu-icon{
          width:38px;height:38px;border-radius:50%;
          display:inline-flex;align-items:center;justify-content:center;
          background:#eef7d6;color:var(--public-brand-green);
        }
        .ps-menu-icon svg{width:18px;height:18px;display:block}
        .ps-menu-icon .ps-material{font-size:20px}
        .ps-menu-copy{min-width:0}
        .ps-menu-name{display:block;color:var(--public-brand-green);font-size:17px;font-weight:700;line-height:1.25}
        .ps-menu-note{display:block;margin-top:3px;color:var(--public-muted);font-size:15px;font-weight:500;line-height:1.35}
        .ps-chevron{display:inline-block;font-size:20px;color:rgba(26,58,42,.55);transform:scaleX(1);transform-origin:center}

        .ps-sr-only{
          position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;
          clip:rect(0,0,0,0);white-space:nowrap;border:0;
        }

        @media(max-width:767px){
          .public-share{padding:10px 0 24px}
          .ps-menu{top:calc(100% - 14px);width:min(330px,calc(100vw - 40px))}
        }
        @media(max-width:390px){
          .ps-row{gap:8px}
          .ps-menu{width:calc(100vw - 40px)}
        }
        /* Below 192px the three 48px buttons and their 8px gaps no longer fit in one row and
           Share wraps under Contribute, so the arrows' fixed offsets would point at the wrong
           button or past the menu's edge. The menu still opens directly under the row. */
        @media(max-width:191.98px){
          .ps-menu::before{display:none}
        }
        @media(prefers-reduced-motion:reduce){
          .ps-action,.ps-tip{transition:none}
          .ps-action:hover{transform:none;box-shadow:none}
        }
      `}</style>
      <style jsx global>{`
        /* Direction is a document-level state owned by SupportWidget. Keep this selector global:
           scoped styled-jsx :global([dir]) did not match the shipped ancestor rule, so Chromium
           computed transform:none even though the source declaration existed. */
        html[dir='rtl'] .public-share .ps-chevron{transform:scaleX(-1)}
      `}</style>
    </section>
  );
};

export default PublicShare;
