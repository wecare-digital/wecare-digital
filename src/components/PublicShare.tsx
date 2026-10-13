import React, { useCallback, useEffect, useRef, useState } from 'react';
import { SUBSCRIBE_CTA_HREF } from '../content/subscribe';
import { CONTRIBUTION_CHOICES } from '../config/contribution';
import { whatsappShareHref } from '../config/share';
import { setContribution } from '../lib/cart';
import {
  CONTRIBUTE_BLOCK_AMOUNT_LABEL,
  CONTRIBUTE_CTA_HREF,
} from './ContributeBlock';

/**
 * The compact page-tail action dock.
 *
 * Home renders Subscribe + Share. Every other public surface passes `contribute` and renders
 * Contribute + Subscribe + Share in the SAME band. Contribute and Share reveal short dropdowns;
 * Subscribe has one destination, so it stays a direct WhatsApp link.
 *
 * The generic glyphs are Google Material Symbols Rounded. WhatsApp deliberately keeps the exact
 * filled mark already used by ShareLinks so the site's WhatsApp affordance does not fork.
 */
export interface PublicShareProps {
  /** Override the shared URL. Defaults to the clean current URL after hydration. */
  url?: string;
  /** Override the shared title. Defaults to document.title after hydration. */
  title?: string;
  /** Share dropdown title / tooltip. Defaults to Share. */
  label?: string;
  /** Include the voluntary-contribution action. Home deliberately leaves this false. */
  contribute?: boolean;
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

const [ SUGGESTED ] = CONTRIBUTION_CHOICES;

const PublicShare: React.FC<PublicShareProps> = ( {
  url,
  title,
  label = 'Share',
  contribute = false,
} ) => {
  const [ resolvedUrl, setResolvedUrl ] = useState( url || '' );
  const [ resolvedTitle, setResolvedTitle ] = useState( title || '' );
  const [ openMenu, setOpenMenu ] = useState<OpenMenu>( null );
  const [ canNativeShare, setCanNativeShare ] = useState( false );
  const [ canCopy, setCanCopy ] = useState( false );
  const [ copied, setCopied ] = useState( false );
  const [ busy, setBusy ] = useState( false );

  const rootRef = useRef<HTMLElement | null>( null );
  const contributeTriggerRef = useRef<HTMLButtonElement | null>( null );
  const shareTriggerRef = useRef<HTMLButtonElement | null>( null );

  useEffect( () => {
    if ( typeof window === 'undefined' ) return;
    const nextUrl = url || cleanUrl( window.location.href );
    const nextTitle = title || document.title || window.location.hostname;
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
    setCopied( false );
    setOpenMenu( current => current === menu ? null : menu );
  }, [] );

  const onCheckout = useCallback( () => {
    if ( busy ) return;
    setBusy( true );
    try {
      setContribution( SUGGESTED.variantId );
    } catch {
      /* A rejected variant writes nothing; /cart/ still loads and remains the safe fallback. */
    }
    if ( typeof window !== 'undefined' ) window.location.assign( '/cart/' );
  }, [ busy ] );

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
      setCopied( true );
      window.setTimeout( () => setCopied( false ), 1800 );
    } catch {
      setCopied( false );
    }
  }, [ resolvedUrl ] );

  const shareMenuClass = contribute
    ? 'ps-menu ps-share-menu has-contribute'
    : 'ps-menu ps-share-menu';

  return (
    <section
      className={ contribute ? 'public-share has-contribute' : 'public-share' }
      aria-label={ contribute ? 'Contribute, subscribe and share' : 'Subscribe and share this page' }
      ref={ rootRef }
    >
      <div className="ps-row">
        { contribute && (
          <section className="contribute" aria-labelledby="ps-contribute-heading">
            <h2 className="ps-sr-only" id="ps-contribute-heading">Contribute</h2>
            <button
              ref={ contributeTriggerRef }
              type="button"
              className="ps-action ps-contribute"
              aria-label={ `Contribute ${CONTRIBUTE_BLOCK_AMOUNT_LABEL}` }
              aria-expanded={ openMenu === 'contribute' }
              aria-controls="ps-contribute-menu"
              onClick={ () => toggleMenu( 'contribute' ) }
            >
              <span className="ps-material" aria-hidden="true">currency_rupee</span>
              <span className="ps-tip" aria-hidden="true">Contribute</span>
            </button>
          </section>
        ) }

        <a
          className="ps-action ps-subscribe"
          href={ SUBSCRIBE_CTA_HREF }
          target="_blank"
          rel="noopener noreferrer"
          aria-label="Subscribe on WhatsApp"
        >
          <span className="ps-material" aria-hidden="true">notifications_active</span>
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
          <span className="ps-material" aria-hidden="true">share</span>
          <span className="ps-tip" aria-hidden="true">{ label }</span>
        </button>
      </div>

      { contribute && (
        <div
          className={ openMenu === 'contribute' ? 'ps-menu ps-contribute-menu is-open' : 'ps-menu ps-contribute-menu' }
          id="ps-contribute-menu"
          hidden={ openMenu !== 'contribute' }
        >
          <div className="ps-menu-head">
            <div className="ps-menu-title contribute-label" data-wc-no-translate="true">
              { `Contribute ${CONTRIBUTE_BLOCK_AMOUNT_LABEL}` }
            </div>
            <p className="ps-menu-sub">Choose how to contribute.</p>
          </div>

          <div className="ps-menu-list">
            <a
              className="ps-menu-item contribute-link"
              href={ CONTRIBUTE_CTA_HREF }
              target="_blank"
              rel="noopener noreferrer"
              aria-label="Contribute on WhatsApp"
            >
              <span className="ps-menu-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24" focusable="false">
                  <path fill="currentColor" d="M17.47 14.38c-.3-.15-1.76-.87-2.03-.97-.27-.1-.47-.15-.67.15-.2.3-.77.97-.94 1.16-.17.2-.35.22-.64.08-.3-.15-1.26-.46-2.4-1.48-.88-.79-1.48-1.76-1.65-2.06-.17-.3-.02-.46.13-.61.13-.13.3-.35.45-.52.15-.17.2-.3.3-.5.1-.2.05-.37-.03-.52-.07-.15-.67-1.61-.91-2.21-.24-.58-.49-.5-.67-.51h-.57c-.2 0-.52.07-.8.37-.27.3-1.03 1.02-1.03 2.48 0 1.46 1.06 2.87 1.21 3.07.15.2 2.1 3.2 5.08 4.49.71.3 1.26.49 1.69.62.71.23 1.36.2 1.87.12.57-.09 1.76-.72 2-1.41.25-.7.25-1.29.18-1.42-.08-.12-.28-.2-.57-.35M12.05 21.79h-.01a9.87 9.87 0 01-5.03-1.38l-.36-.21-3.74.98 1-3.65-.24-.37a9.86 9.86 0 01-1.51-5.26C2.16 6.45 6.6 2.01 12.05 2.01c2.64 0 5.12 1.03 6.99 2.9a9.83 9.83 0 012.89 6.99c0 5.45-4.44 9.89-9.88 9.89M20.46 3.49A11.82 11.82 0 0012.05 0C5.5 0 .16 5.34.16 11.89c0 2.1.55 4.14 1.59 5.95L.06 24l6.3-1.65a11.88 11.88 0 005.69 1.45c6.55 0 11.89-5.34 11.89-11.89 0-3.18-1.24-6.17-3.48-8.42z" />
                </svg>
              </span>
              <span className="ps-menu-copy">
                <span className="ps-menu-name">WhatsApp</span>
                <span className="ps-menu-note">Continue on WhatsApp</span>
              </span>
              <span className="ps-material ps-chevron" aria-hidden="true">chevron_right</span>
            </a>

            <button
              type="button"
              className="ps-menu-item contribute-link-btn"
              onClick={ onCheckout }
              disabled={ busy }
              aria-busy={ busy }
              aria-label="Contribute on the website at checkout"
            >
              <span className="ps-menu-icon" aria-hidden="true">
                <span className="ps-material">shopping_cart_checkout</span>
              </span>
              <span className="ps-menu-copy">
                <span className="ps-menu-name">Website</span>
                <span className="ps-menu-note">{ busy ? 'One moment…' : 'Continue to checkout' }</span>
              </span>
              <span className="ps-material ps-chevron" aria-hidden="true">chevron_right</span>
            </button>
          </div>
        </div>
      ) }

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
            <span className="ps-material ps-chevron" aria-hidden="true">chevron_right</span>
          </a>

          { canNativeShare && (
            <button
              type="button"
              className="ps-menu-item"
              onClick={ onNativeShare }
              aria-label="Share this page using another app"
            >
              <span className="ps-menu-icon" aria-hidden="true">
                <span className="ps-material">ios_share</span>
              </span>
              <span className="ps-menu-copy">
                <span className="ps-menu-name">More apps</span>
                <span className="ps-menu-note">Choose another app</span>
              </span>
              <span className="ps-material ps-chevron" aria-hidden="true">chevron_right</span>
            </button>
          ) }

          { canCopy && (
            <button
              type="button"
              className={ copied ? 'ps-menu-item is-copied' : 'ps-menu-item' }
              onClick={ onCopy }
              aria-label={ copied ? 'Link copied' : 'Copy link to this page' }
            >
              <span className="ps-menu-icon" aria-hidden="true">
                <span className="ps-material">{ copied ? 'check' : 'link' }</span>
              </span>
              <span className="ps-menu-copy">
                <span className="ps-menu-name">{ copied ? 'Copied' : 'Copy link' }</span>
                <span className="ps-menu-note">{ copied ? 'Link copied' : 'Copy page link' }</span>
              </span>
              <span className="ps-material ps-chevron" aria-hidden="true">chevron_right</span>
            </button>
          ) }
        </div>
      </div>

      <span className="ps-status" role="status" aria-live="polite">
        { copied ? 'Link copied to clipboard' : '' }
      </span>

      <style jsx>{`
        .public-share{
          position:relative;width:100%;margin-top:48px;padding:24px 0 28px;
          border-top:1px solid #e5e7eb;box-sizing:border-box;
          font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
        }
        .public-share.has-contribute{margin-top:44px}
        .ps-row{display:flex;align-items:center;gap:12px;width:max-content;max-width:100%}
        .contribute{margin:0;padding:0;border:0;position:static}
        .ps-action{
          position:relative;width:48px;height:48px;box-sizing:border-box;border-radius:50%;
          border:2px solid #e5e7eb;background:#fff;color:#1a3a2a;
          display:inline-flex;align-items:center;justify-content:center;padding:0;flex:0 0 auto;
          cursor:pointer;text-decoration:none;
          transition:background-color .18s,border-color .18s,transform .18s,box-shadow .18s;
        }
        .ps-action:hover{
          border-color:#1a3a2a;background:#d1f470;transform:translateY(-2px);
          box-shadow:0 4px 12px rgba(26,58,42,.10);
        }
        .ps-contribute{background:#eef7d6;border-color:#1a3a2a}
        .ps-subscribe{background:#d1f470;border-color:#1a3a2a}
        .ps-subscribe:hover{background:#fff}
        .ps-action:active{transform:translateY(0)}
        .ps-action:focus-visible,.ps-menu-item:focus-visible{
          outline:3px solid #1a3a2a;outline-offset:3px;
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
          position:absolute;left:50%;bottom:calc(100% + 9px);
          transform:translateX(-50%) translateY(4px);
          padding:6px 9px;border-radius:8px;background:#1a3a2a;color:#fff;
          white-space:nowrap;font-size:12px;font-weight:650;line-height:1.2;
          opacity:0;pointer-events:none;z-index:40;
          transition:opacity .15s,transform .15s;
        }
        .ps-action:hover .ps-tip,.ps-action:focus-visible .ps-tip{
          opacity:1;transform:translateX(-50%) translateY(0);
        }

        .ps-menu{
          position:absolute;top:82px;left:0;z-index:30;
          width:min(340px,calc(100vw - 48px));padding:8px;
          background:#fff;border:1px solid #e5e7eb;border-radius:18px;
          box-shadow:0 18px 46px rgba(26,58,42,.13);box-sizing:border-box;
        }
        .ps-menu[hidden]{display:none}
        .ps-menu::before{
          content:'';position:absolute;top:-6px;width:12px;height:12px;
          background:#fff;border-left:1px solid #e5e7eb;border-top:1px solid #e5e7eb;
          transform:rotate(45deg);
        }
        .ps-contribute-menu::before{left:18px}
        .ps-share-menu::before{left:78px}
        .ps-share-menu.has-contribute::before{left:138px}
        .ps-menu-head{padding:9px 11px 10px;border-bottom:1px solid #f0f1ed}
        .ps-menu-title{margin:0;color:#1a1a1a;font-size:17px;font-weight:700;line-height:1.3}
        .ps-menu-sub{margin:3px 0 0;color:rgba(0,0,0,.54);font-size:13px;font-weight:500;line-height:1.35}
        .ps-menu-list{padding-top:6px}
        .ps-menu-item{
          width:100%;min-height:56px;display:grid;
          grid-template-columns:38px minmax(0,1fr) 20px;gap:10px;align-items:center;
          padding:7px 10px;border:0;border-radius:12px;background:#fff;color:#1a3a2a;
          text-decoration:none;cursor:pointer;text-align:left;box-sizing:border-box;
          font:inherit;
        }
        .ps-menu-item:hover{background:#f7fbe9}
        .ps-menu-item:disabled{opacity:.55;cursor:default}
        .ps-menu-icon{
          width:38px;height:38px;border-radius:50%;
          display:inline-flex;align-items:center;justify-content:center;
          background:#eef7d6;color:#1a3a2a;
        }
        .ps-menu-icon svg{width:18px;height:18px;display:block}
        .ps-menu-icon .ps-material{font-size:20px}
        .ps-menu-copy{min-width:0}
        .ps-menu-name{display:block;color:#1a3a2a;font-size:16px;font-weight:700;line-height:1.25}
        .ps-menu-note{display:block;margin-top:2px;color:rgba(0,0,0,.54);font-size:13px;font-weight:500;line-height:1.3}
        .ps-chevron{font-size:20px;color:rgba(26,58,42,.55)}
        .ps-menu-item.is-copied .ps-menu-icon{background:#d1f470}

        .ps-sr-only,.ps-status{
          position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;
          clip:rect(0,0,0,0);white-space:nowrap;border:0;
        }

        @media(max-width:767px){
          .public-share{padding:22px 0 24px}
          .ps-menu{top:78px;width:min(330px,calc(100vw - 40px))}
        }
        @media(max-width:390px){
          .ps-menu{width:calc(100vw - 40px)}
        }
        @media(prefers-reduced-motion:reduce){
          .ps-action,.ps-tip{transition:none}
          .ps-action:hover{transform:none;box-shadow:none}
        }
      `}</style>
    </section>
  );
};

export default PublicShare;
