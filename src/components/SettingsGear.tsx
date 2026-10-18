/**
 * The settings gear — everything that is configured rather than worked in.
 *
 * The sidebar used to carry 88 destinations, 30 of them WhatsApp sub-pages. It was
 * a settings tree wearing a sidebar's clothes: "Flow Publish Checklist" sat at the
 * same level as the inbox. This is where that tree went.
 *
 * NOTHING BECAME UNREACHABLE. Three independent routes to every settings page:
 *   1. this panel, grouped and hinted
 *   2. Ctrl+K, which is built from `getAllNavItems()` and walks both trees
 *   3. the sidebar search box, same source
 * That redundancy is deliberate, because 21 of the original 88 paths have no link
 * anywhere else in the app — for those, navigation IS the only way in.
 *
 * It is a panel and not a route on purpose. A `/workspace/settings` page would be one more
 * destination to navigate to before navigating, and it would need its own shell,
 * its own breadcrumb, and a decision about what happens to the page you were on.
 *
 * Self-styling, because styled-jsx does not scope composite components. Values are
 * the inner design system as aligned against the public contract: `#e5e7eb`
 * hairlines at 1px static and 2px where there is a hover, `rgba(0,0,0,.898)` body,
 * `#000` headings, lime only on hover and active.
 */
import React, { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import dynamic from 'next/dynamic';
import { useRouter } from 'next/router';
import { settingsConfig } from '../config/navigation';

// FEAT-003: Sign-in & MFA is no longer a route. TotpSetup renders INSIDE this panel, lazily, so
// it only mounts (and only touches aws-amplify/auth) when the operator actually opens it — not on
// every page that renders the gear. ssr:false keeps it out of the statically exported server
// bundle; it fetches on mount and sits behind auth, so there is nothing to prerender.
const TotpSetup = dynamic( () => import( './security/TotpSetup' ), { ssr: false } );

interface SettingsGearProps {
  /** Collapsed sidebar shows the gear without its label. */
  collapsed?: boolean;
}

const SettingsGear: React.FC<SettingsGearProps> = ( { collapsed = false } ) => {
  const router = useRouter();
  const [ open, setOpen ] = useState( false );
  const [ filter, setFilter ] = useState( '' );
  // Which in-panel surface is showing, if any. 'mfa' renders TotpSetup inline instead of the
  // settings list; null shows the list. (FEAT-003 relocation of Sign-in & MFA.)
  const [ view, setView ] = useState<null | 'mfa'>( null );
  const panelRef = useRef<HTMLDivElement | null>( null );
  const buttonRef = useRef<HTMLButtonElement | null>( null );

  // Close on route change, so the panel never survives the navigation it caused.
  useEffect( () => { setOpen( false ); setFilter( '' ); setView( null ); }, [ router.asPath ] );

  // Escape closes and returns focus to the trigger, which is the one thing a
  // keyboard user cannot recover on their own.
  useEffect( () => {
    if ( !open ) return;
    const onKey = ( e: KeyboardEvent ) => {
      if ( e.key !== 'Escape' ) return;
      // Escape backs out of an in-panel view first, then closes the panel.
      if ( view ) { setView( null ); return; }
      setOpen( false ); buttonRef.current?.focus();
    };
    const onClick = ( e: MouseEvent ) => {
      const t = e.target as Node;
      if ( panelRef.current?.contains( t ) || buttonRef.current?.contains( t ) ) return;
      setOpen( false );
    };
    document.addEventListener( 'keydown', onKey );
    document.addEventListener( 'mousedown', onClick );
    return () => {
      document.removeEventListener( 'keydown', onKey );
      document.removeEventListener( 'mousedown', onClick );
    };
  }, [ open, view ] );

  const groups = useMemo( () => {
    const q = filter.trim().toLowerCase();
    if ( !q ) return settingsConfig;
    return settingsConfig
      .map( ( g ) => ( {
        ...g,
        items: g.items.filter( ( i ) =>
          i.label.toLowerCase().includes( q ) || i.path.toLowerCase().includes( q ) ),
      } ) )
      .filter( ( g ) => g.items.length > 0 );
  }, [ filter ] );

  const go = useCallback( ( path: string ) => {
    setOpen( false );
    router.push( path );
  }, [ router ] );

  // Toggle the panel, and reset any in-panel view when closing so reopening lands on the list.
  const toggle = useCallback( () => {
    setOpen( ( v ) => !v );
    setView( null );
  }, [] );

  const total = useMemo(
    () => settingsConfig.reduce( ( n, g ) => n + g.items.length, 0 ), [] );

  return (
    <div className="sg-wrap">
      <button
        ref={ buttonRef }
        type="button"
        className={ open ? 'sg-btn sg-btn-open' : 'sg-btn' }
        aria-expanded={ open }
        aria-haspopup="true"
        aria-label={ `Settings — ${total} pages` }
        onClick={ toggle }
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6h.09A1.65 1.65 0 0 0 10 3.09V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9v.09a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
        </svg>
        { !collapsed && <span className="sg-btn-label">Settings</span> }
      </button>

      { open && (
        <div className="sg-panel" ref={ panelRef } role="dialog"
          aria-label="Settings">
          { view === 'mfa' ? (
            // FEAT-003: the Sign-in & MFA surface, relocated here from the retired
            // /workspace/access/security route. TotpSetup is preserved verbatim; only the
            // chrome around it (the public-contract heading and intro) moved from that page
            // into this in-panel view.
            <div className="sg-mfa">
              <div className="sg-panel-head">
                <button type="button" className="sg-back" onClick={ () => setView( null ) }
                  aria-label="Back to settings">← Settings</button>
              </div>
              <div className="sg-mfa-body">
                <header className="sg-mfa-head">
                  <h2 className="sg-mfa-h1">Sign-in &amp; MFA</h2>
                  <p className="sg-mfa-sub">
                    Second factors for your own account. Email codes are on and your
                    verified mobile is registered as a fallback.
                  </p>
                </header>
                <Suspense fallback={ <p className="sg-empty">Loading…</p> }>
                  <TotpSetup />
                </Suspense>
              </div>
            </div>
          ) : (
            <>
              <div className="sg-panel-head">
                <input
                  className="sg-filter"
                  type="text"
                  autoFocus
                  placeholder="Filter settings…"
                  value={ filter }
                  onChange={ ( e ) => setFilter( e.target.value ) }
                  aria-label="Filter settings"
                />
                <span className="sg-count">{ total } pages</span>
              </div>

              <div className="sg-groups">
                { groups.length === 0 ? (
                  <p className="sg-empty">
                    Nothing matches. Ctrl+K searches every page, including these.
                  </p>
                ) : groups.map( ( g ) => (
                  <section className="sg-group" key={ g.id }>
                    <h3 className="sg-group-label">{ g.label }</h3>
                    <p className="sg-group-hint">{ g.hint }</p>
                    <ul className="sg-list">
                      { /* FEAT-003: a group's in-panel MFA surface leads the list when it has
                           one and nothing is being filtered out. It opens inline rather than
                           navigating, because TotpSetup needs the signed-in user's own token. */ }
                      { g.mfaPanel && !filter.trim() && (
                        <li key={ g.mfaPanel.id }>
                          <button type="button" className="sg-link"
                            onClick={ () => setView( 'mfa' ) }>{ g.mfaPanel.label }</button>
                        </li>
                      ) }
                      { g.items.map( ( i ) => (
                        <li key={ i.path }>
                          <button type="button" className="sg-link"
                            onClick={ () => go( i.path ) }>{ i.label }</button>
                        </li>
                      ) ) }
                    </ul>
                  </section>
                ) ) }
              </div>
            </>
          ) }
        </div>
      ) }

      <style jsx>{ `
        .sg-wrap{position:relative}

        /* 2px #e5e7eb because it has a hover that swaps to lime — the contract's
           hairline rule. Lime at rest is what makes a control read as focused. */
        .sg-btn{
          display:flex;align-items:center;gap:10px;width:100%;
          font-family:inherit;font-size:15px;font-weight:500;
          color:rgba(0,0,0,.898);background:#fff;
          border:2px solid #e5e7eb;border-radius:13px;padding:10px 14px;
          cursor:pointer;transition:all .2s ease;
        }
        .sg-btn:hover{border-color:#d1f470;background:#fafafa}
        .sg-btn:focus-visible{outline:none;border-color:#d1f470;box-shadow:0 0 0 3px #1a3a2a}
        /* Open is one of our own states, so it takes the lime fill with dark-green
           type — contract treatment 1, the same pair as an active tab. */
        .sg-btn-open{background:#d1f470;border-color:#d1f470;color:#1a3a2a}
        .sg-btn-label{white-space:nowrap}

        .sg-panel{
          position:absolute;bottom:calc(100% + 10px);left:0;z-index:60;
          width:min(560px,calc(100vw - 32px));max-height:min(70vh,620px);
          overflow-y:auto;background:#fff;
          border:1px solid #e5e7eb;border-radius:16px;
          box-shadow:0 12px 40px rgba(0,0,0,.14);
        }
        .sg-panel-head{
          position:sticky;top:0;background:#fff;display:flex;align-items:center;
          gap:12px;padding:16px 18px;border-bottom:1px solid #e5e7eb;
        }
        .sg-filter{
          flex:1;font-family:inherit;font-size:15px;color:rgba(0,0,0,.898);
          background:#fff;border:2px solid #e5e7eb;border-radius:13px;
          padding:9px 12px;min-height:0;
        }
        .sg-filter:focus{outline:none;border-color:#d1f470}
        .sg-count{font-size:14px;color:rgba(0,0,0,.54);white-space:nowrap}

        .sg-groups{padding:6px 18px 18px}
        .sg-group{padding:14px 0;border-bottom:1px solid #e5e7eb}
        .sg-group:last-child{border-bottom:none}
        .sg-group-label{
          font-size:17px;font-weight:600;letter-spacing:-.125px;color:#000;margin:0;
        }
        .sg-group-hint{font-size:14px;color:rgba(0,0,0,.54);margin:2px 0 10px}
        .sg-list{
          list-style:none;margin:0;padding:0;
          display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:2px;
        }
        .sg-link{
          display:block;width:100%;text-align:left;font-family:inherit;
          font-size:15px;color:rgba(0,0,0,.898);background:transparent;
          border:none;border-radius:8px;padding:7px 10px;cursor:pointer;
          transition:background .15s ease;
        }
        /* The .22 lime tint: the palette's TRANSIENT-state value, which is right
           for a hover. Full-strength lime here would read as identity. */
        .sg-link:hover{background:rgba(209,244,112,.22)}
        /* The ring was lime on a white panel, which is about 1.4:1 - lime is a LIGHT colour
           and cannot serve as a ring against white, the same finding BrandLockup records for
           the brand dot. Dark green instead, which is the pair this design language already
           uses for type on lime. The tint stays as the state fill. */
        .sg-link:focus-visible{outline:none;background:rgba(209,244,112,.22);box-shadow:0 0 0 3px #1a3a2a}
        .sg-empty{font-size:15px;color:rgba(0,0,0,.54);margin:14px 0}

        /* FEAT-003: the in-panel Sign-in & MFA view. Back control uses the same lime-tint
           transient state as a settings row; the heading follows the public type contract
           (Inter, 600, -.125px tracking, #000) the retired page carried. */
        .sg-back{
          font-family:inherit;font-size:14px;font-weight:600;color:rgba(0,0,0,.898);
          background:transparent;border:none;border-radius:8px;padding:7px 10px;cursor:pointer;
          transition:background .15s ease;
        }
        .sg-back:hover{background:rgba(209,244,112,.22)}
        .sg-back:focus-visible{outline:none;background:rgba(209,244,112,.22);box-shadow:0 0 0 3px #1a3a2a}
        .sg-mfa-body{padding:6px 18px 18px}
        .sg-mfa-head{margin:8px 0 18px}
        .sg-mfa-h1{font-size:22px;font-weight:600;line-height:1.27;letter-spacing:-.25px;color:#000;margin:0 0 8px}
        .sg-mfa-sub{font-size:20px;font-weight:400;line-height:1.4;letter-spacing:-.125px;color:rgba(0,0,0,.898);margin:0;max-width:560px}

        @media(prefers-reduced-motion:reduce){
          .sg-btn,.sg-link,.sg-back{transition:none}
        }
      `}</style>
    </div>
  );
};

export default SettingsGear;
