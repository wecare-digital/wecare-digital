/**
 * Canonical authenticated WECARE.DIGITAL Workspace shell.
 *
 * Auth responsibility stays in AuthShell/_app. This component owns authenticated chrome only:
 * shared public Header/navigation -> Workspace action layer -> operational content slot ->
 * PublicShare -> Footer. SupportWidget and FloatingAgent are mounted once in _app.
 */
import React, { ReactNode, useEffect, useState } from 'react';
import { useRouter } from 'next/router';
import Header from './Header';
import Footer from './Footer';
import PublicShare from './PublicShare';
import SearchModal from './SearchModal';
import PushOptIn from './PushOptIn';
import { useKeyboardShortcuts } from '../hooks/useKeyboardShortcuts';
import { useUserRole, isPartnerAllowed } from '../hooks/useUserRole';
import { Breadcrumbs, KeyboardShortcuts, useKeyboardShortcutsModal } from './ui';

interface LayoutProps {
  children: ReactNode;
  user?: any;
  onSignOut?: () => void;
  showBreadcrumbs?: boolean;
}

const SearchGlyph = () => (
  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
    <circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/>
  </svg>
);

const TasksGlyph = () => (
  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
    <path d="M9 6h11M9 12h11M9 18h11"/><path d="m3.5 6 1.4 1.4L7 5.1M3.5 12l1.4 1.4L7 11.1M3.5 18l1.4 1.4L7 17.1"/>
  </svg>
);

const PersonGlyph = () => (
  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
    <circle cx="12" cy="8" r="3.5"/><path d="M4.5 21c.8-4.1 3.3-6.2 7.5-6.2s6.7 2.1 7.5 6.2"/>
  </svg>
);

const HomeGlyph = () => (
  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
    <path d="m3 11 9-7 9 7"/><path d="M5.5 10v10h13V10"/><path d="M9.5 20v-6h5v6"/>
  </svg>
);

const Layout: React.FC<LayoutProps> = ( { children, user, onSignOut, showBreadcrumbs = true } ) => {
  const router = useRouter();
  const { isPartner, loading: roleLoading } = useUserRole();
  const [ searchOpen, setSearchOpen ] = useState( false );
  const [ profileOpen, setProfileOpen ] = useState( false );
  const shortcutsModal = useKeyboardShortcutsModal();

  // Preserve the existing partner route boundary unchanged.
  useEffect( () => {
    if ( !roleLoading && isPartner && !isPartnerAllowed( router.pathname ) ) {
      void router.replace( '/workspace/engage/whatsapp/my-account' );
    }
  }, [ roleLoading, isPartner, router ] );

  useEffect( () => {
    setProfileOpen( false );
  }, [ router.pathname ] );

  useKeyboardShortcuts( [
    { key: 'k', ctrl: true, action: () => setSearchOpen( true ), description: 'Open search' },
    { key: '/', action: () => setSearchOpen( true ), description: 'Open search' },
  ] );

  const isHome = router.pathname === '/workspace';
  const loginId = user?.signInDetails?.loginId || user?.email || '';
  const role = user?.role || 'Operator';

  return (
    <div className={ `layout workspace-shell ${isHome ? 'workspace-home-shell' : ''}` }>
      {/* The exact same shared Header/navigation/search/cart/menu component as /auth and Home. */}
      <Header />

      <div className="workspace-action-band">
        <div className="workspace-action-inner" aria-label="Workspace actions">
          <button type="button" className="workspace-action"
            onClick={ () => void router.push( '/workspace' ) } aria-label="Workspace home">
            <HomeGlyph /><span>Workspace</span>
          </button>

          <button type="button" className="workspace-action workspace-search"
            onClick={ () => setSearchOpen( true ) } aria-label="Search workspace">
            <SearchGlyph /><span>Search</span><kbd>⌘K</kbd>
          </button>

          <button type="button" className="workspace-action"
            onClick={ () => void router.push( '/workspace/task' ) } aria-label="Tasks">
            <TasksGlyph /><span>Tasks</span>
          </button>

          <div className="workspace-profile-wrap">
            <button type="button" className={ `workspace-action ${profileOpen ? 'active' : ''}` }
              aria-label="Profile" aria-expanded={ profileOpen }
              onClick={ () => setProfileOpen( value => !value ) }>
              <PersonGlyph /><span>Profile</span>
            </button>
            { profileOpen && (
              <>
                <button type="button" className="profile-scrim" aria-label="Close profile"
                  onClick={ () => setProfileOpen( false ) } />
                <section className="profile-menu" aria-label="Profile menu">
                  <div className="profile-identity" data-wc-no-translate="true">
                    <strong>{ role }</strong>
                    { loginId && <span>{ loginId }</span> }
                  </div>
                  <PushOptIn />
                  { onSignOut && (
                    <button type="button" className="profile-signout" onClick={ onSignOut }>
                      Sign out
                    </button>
                  ) }
                </section>
              </>
            ) }
          </div>
        </div>
      </div>

      {/*
        This is the operational-data privacy boundary for every Workspace route. Customer
        names, phones, addresses, messages, invoices, payments, orders, ids and references
        must never be machine-translated in place.
      */}
      <main id="main-content" className="main-content workspace-main" data-wc-no-translate="true">
        <div className="workspace-content-frame">
          { showBreadcrumbs && <Breadcrumbs /> }
          <div className="inner-content-container">
            { children }
          </div>
        </div>
      </main>

      <div className="workspace-public-share">
        <PublicShare />
      </div>
      <Footer />

      <SearchModal isOpen={ searchOpen } onClose={ () => setSearchOpen( false ) } />
      <KeyboardShortcuts isOpen={ shortcutsModal.isOpen } onClose={ shortcutsModal.close } />

      <style jsx>{`
        .workspace-shell{
          display:block;
          min-height:100vh;
          min-height:100dvh;
          min-width:0;
          overflow-x:hidden;
          overflow-x:clip;
          background:var(--public-bg,#fff);
          color:var(--public-text,#111);
          font-family:var(--font-sans,Inter,system-ui,sans-serif);
        }

        /* Header is fixed by the shared public component. This band is deliberately NOT fixed:
           it keeps Workspace utilities available without creating a second competing global header. */
        .workspace-action-band{
          width:100%;
          padding-top:108px;
          background:#fff;
          border-bottom:1px solid var(--public-hairline,#e5e7eb);
          box-sizing:border-box;
        }
        .workspace-action-inner{
          width:min(100%,var(--public-content-max,1300px));
          min-width:0;
          margin:0 auto;
          padding:12px var(--public-page-gutter,24px);
          box-sizing:border-box;
          display:flex;
          align-items:center;
          justify-content:flex-end;
          gap:8px;
          flex-wrap:wrap;
        }
        .workspace-action{
          display:inline-flex;
          align-items:center;
          justify-content:center;
          gap:8px;
          min-width:0;
          padding:9px 14px;
          border:1px solid var(--public-hairline,#e5e7eb);
          border-radius:12px;
          background:#fff;
          color:var(--public-brand-green,#1a3a2a);
          font:700 13px/1.2 var(--font-sans,Inter,system-ui,sans-serif);
          cursor:pointer;
          -webkit-tap-highlight-color:transparent;
        }
        .workspace-action:hover,.workspace-action.active{
          border-color:var(--public-brand-lime,#d1f470);
          background:#f8faf3;
        }
        .workspace-action:focus-visible,.profile-signout:focus-visible{
          outline:2px solid var(--public-brand-green,#1a3a2a);
          outline-offset:2px;
        }
        .workspace-search{min-width:min(280px,32vw);justify-content:flex-start}
        .workspace-search kbd{
          margin-inline-start:auto;
          padding:2px 6px;
          border:1px solid var(--public-hairline,#e5e7eb);
          border-radius:6px;
          background:#f8faf9;
          color:var(--public-muted,#667085);
          font:inherit;
          font-size:11px;
        }
        .workspace-profile-wrap{position:relative;display:inline-flex;min-width:0}
        .profile-scrim{position:fixed;inset:0;z-index:1190;border:0;background:transparent;cursor:default}
        .profile-menu{
          position:absolute;
          z-index:1200;
          top:calc(100% + 8px);
          inset-inline-end:0;
          width:min(300px,calc(100vw - 32px));
          max-height:min(70dvh,520px);
          overflow:auto;
          overscroll-behavior:contain;
          border:1px solid var(--public-hairline,#e5e7eb);
          border-radius:16px;
          background:#fff;
          box-shadow:0 14px 38px rgba(26,58,42,.12);
        }
        .profile-identity{display:flex;flex-direction:column;gap:4px;padding:16px;min-width:0}
        .profile-identity strong{font-size:14px;color:var(--public-text,#111)}
        .profile-identity span{font-size:12px;color:var(--public-muted,#667085);overflow-wrap:anywhere}
        .profile-signout{
          width:100%;
          padding:12px 16px;
          border:0;
          border-top:1px solid var(--public-hairline,#e5e7eb);
          background:#fff;
          color:var(--public-text,#111);
          font:700 14px/1.3 var(--font-sans,Inter,system-ui,sans-serif);
          text-align:start;
          cursor:pointer;
        }
        .profile-signout:hover{background:#f8faf3}

        .workspace-main{
          width:100%;
          max-width:none;
          min-width:0;
          min-height:calc(100vh - 108px);
          min-height:calc(100dvh - 108px);
          margin:0;
          padding:0;
          overflow-x:hidden;
          overflow-x:clip;
          background:#fff;
          box-sizing:border-box;
        }
        .workspace-content-frame{
          width:min(100%,var(--public-content-max,1300px));
          min-width:0;
          margin:0 auto;
          padding:var(--public-section-gap,96px) var(--public-page-gutter,24px);
          box-sizing:border-box;
          overflow-x:hidden;
          overflow-x:clip;
        }
        .workspace-shell :global(.inner-content-container){
          width:100%;
          min-width:0;
          max-width:none;
          margin:0;
          padding:0;
          border:0;
          border-radius:0;
          overflow:visible;
          background:transparent;
          box-sizing:border-box;
        }

        /* Central containment defaults. Wide data components may scroll inside their own wrapper,
           but flex/grid descendants cannot set a min-content width on the whole document. */
        .workspace-main :global(.page-shell),
        .workspace-main :global(.ps-content),
        .workspace-main :global(section),
        .workspace-main :global(article),
        .workspace-main :global(form),
        .workspace-main :global(.card),
        .workspace-main :global(.panel){
          min-width:0;
          max-width:100%;
          box-sizing:border-box;
        }
        .workspace-main :global(img),
        .workspace-main :global(video),
        .workspace-main :global(canvas),
        .workspace-main :global(svg:not([width])){
          max-width:100%;
          height:auto;
        }
        .workspace-main :global(input),
        .workspace-main :global(select),
        .workspace-main :global(textarea){
          max-width:100%;
          box-sizing:border-box;
        }

        .workspace-public-share{
          width:min(100%,var(--public-content-max,1300px));
          min-width:0;
          margin:0 auto;
          padding:8px var(--public-page-gutter,24px) 48px;
          overflow-x:hidden;
          overflow-x:clip;
          box-sizing:border-box;
        }

        @media(max-width:767px){
          .workspace-action-band{padding-top:96px}
          .workspace-action-inner{
            padding:10px var(--public-mobile-page-gutter,16px);
            justify-content:flex-start;
            flex-wrap:nowrap;
            overflow-x:auto;
            overscroll-behavior-inline:contain;
            scrollbar-width:none;
            -webkit-overflow-scrolling:touch;
          }
          .workspace-action-inner::-webkit-scrollbar{display:none}
          .workspace-action{flex:0 0 auto}
          .workspace-search{min-width:0}
          .workspace-search kbd{display:none}
          .workspace-content-frame{
            padding:
              var(--public-mobile-hero-top,48px)
              var(--public-mobile-page-gutter,16px)
              var(--public-mobile-section-gap,64px);
          }
          .workspace-main{
            min-height:calc(100vh - 96px);
            min-height:calc(100dvh - 96px);
          }
          .workspace-public-share{
            padding-inline:var(--public-mobile-page-gutter,16px);
            padding-bottom:max(40px,env(safe-area-inset-bottom,0px));
          }
          .profile-menu{
            position:fixed;
            top:auto;
            right:max(var(--public-mobile-page-gutter,16px),env(safe-area-inset-right,0px));
            bottom:max(16px,env(safe-area-inset-bottom,0px));
            left:max(var(--public-mobile-page-gutter,16px),env(safe-area-inset-left,0px));
            width:auto;
            max-height:min(70dvh,520px);
          }
          .workspace-main :global(input:not([type="checkbox"]):not([type="radio"])),
          .workspace-main :global(select),
          .workspace-main :global(textarea){
            font-size:max(16px,1em);
          }
        }
        @media(max-width:399px){
          .workspace-action-inner{gap:6px}
          .workspace-action{padding:8px 10px}
        }
        @media(max-width:279px){
          .workspace-action-inner{
            flex-wrap:wrap;
            overflow-x:visible;
          }
          .workspace-action{max-width:100%;white-space:normal}
          .workspace-content-frame{padding-inline:max(8px,env(safe-area-inset-left,0px))}
        }
        @media(prefers-reduced-motion:reduce){
          .workspace-action,.profile-signout{transition:none}
          .workspace-action-inner{scroll-behavior:auto}
        }
        @media(forced-colors:active){
          .workspace-action,.profile-menu,.profile-signout{border-color:CanvasText}
        }
      `}</style>
    </div>
  );
};

export default Layout;
