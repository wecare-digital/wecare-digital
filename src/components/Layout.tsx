/**
 * Canonical authenticated WECARE.DIGITAL Workspace shell.
 *
 * Header/navigation, Workspace tools, Stay connected and Footer remain shared.
 * Route pages provide only their section header, local tabs/actions and content.
 */
import React, { ReactNode, createContext, useContext, useEffect, useState } from 'react';
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

/** Nested legacy Layout imports become content-only adapters inside the one root shell. */
const WorkspaceShellContext = createContext( false );

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

const WorkspaceLayout: React.FC<LayoutProps> = ( {
  children,
  user,
  onSignOut,
  showBreadcrumbs = false,
} ) => {
  const router = useRouter();
  const { isPartner, loading: roleLoading } = useUserRole();
  const [ searchOpen, setSearchOpen ] = useState( false );
  const [ profileOpen, setProfileOpen ] = useState( false );
  const shortcutsModal = useKeyboardShortcutsModal();

  useEffect( () => {
    if ( !roleLoading && isPartner && !isPartnerAllowed( router.pathname ) ) {
      void router.replace( '/workspace/engage/whatsapp/my-account' );
    }
  }, [ roleLoading, isPartner, router ] );
  useEffect( () => { setProfileOpen( false ); }, [ router.pathname ] );
  useKeyboardShortcuts( [
    { key: 'k', ctrl: true, action: () => setSearchOpen( true ), description: 'Open search' },
    { key: '/', action: () => setSearchOpen( true ), description: 'Open search' },
  ] );

  const isHome = router.pathname === '/workspace';
  const isPayments = router.pathname === '/workspace/payments' || router.pathname === '/workspace/pay';
  const loginId = user?.signInDetails?.loginId || user?.email || '';
  const role = user?.role || 'Operator';

  return (
    <WorkspaceShellContext.Provider value={ true }>
      <div className={ `layout workspace-shell workspace-public-shell ${isHome ? 'workspace-home-shell' : ''} ${isPayments ? 'payments-public-layout' : ''}`.trim() }>
        <Header />

        <div className="workspace-shell-body">
          <section className="workspace-utility" aria-label="Workspace tools">
            <div className="workspace-utility-inner">
              <div className="workspace-context">
                { !isHome ? (
                  <button type="button" className="workspace-back" onClick={ () => void router.push( '/workspace' ) }>
                    <span aria-hidden="true">←</span><span>Workspace</span>
                  </button>
                ) : <span className="workspace-context-label">Workspace</span> }
              </div>

              <div className="workspace-actions" aria-label="Workspace actions">
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
                        <div className="profile-identity">
                          <strong>{ role }</strong>
                          { loginId && <span>{ loginId }</span> }
                        </div>
                        <PushOptIn />
                        { onSignOut && <button type="button" className="profile-signout" onClick={ onSignOut }>Sign out</button> }
                      </section>
                    </>
                  ) }
                </div>
              </div>
            </div>
          </section>

          <main id="main-content" className="main-content workspace-main" data-wc-no-translate="true">
            <div className="workspace-content-shell">
              { showBreadcrumbs && <Breadcrumbs /> }
              <div className="inner-content-container">{ children }</div>
            </div>
          </main>
        </div>

        <div className="workspace-public-action-tail"><PublicShare /></div>
        <Footer />
        <SearchModal isOpen={ searchOpen } onClose={ () => setSearchOpen( false ) } />
        <KeyboardShortcuts isOpen={ shortcutsModal.isOpen } onClose={ shortcutsModal.close } />

        <style jsx global>{`
          .workspace-public-shell{
            display:block;min-height:100vh;min-height:100dvh;min-width:0;
            overflow-x:hidden;overflow-x:clip;background:var(--public-bg,#fff);
            color:var(--public-text,#111);font-family:var(--font-sans)
          }
          .workspace-shell-body{
            min-height:calc(100vh - 108px);min-height:calc(100dvh - 108px);
            padding-top:108px;box-sizing:border-box
          }
          .workspace-public-shell .workspace-main{
            width:100%;max-width:none;min-width:0;margin:0;box-sizing:border-box;
            overflow-x:hidden;overflow-x:clip;background:#fff
          }
          .workspace-utility{width:100%;border-bottom:1px solid var(--public-hairline,#e5e7eb);background:rgba(255,255,255,.96)}
          .workspace-utility-inner{
            width:min(100%,var(--public-content-max,1300px));min-width:0;margin:0 auto;
            padding:14px var(--public-page-gutter,24px);box-sizing:border-box;
            display:flex;align-items:center;justify-content:space-between;gap:16px
          }
          .workspace-context,.workspace-actions{min-width:0;display:flex;align-items:center;gap:8px}
          .workspace-context-label{color:var(--public-brand-green,#1a3a2a);font-size:var(--public-supporting-size,16px);font-weight:700}
          .workspace-back,.workspace-action,.profile-signout{
            display:inline-flex;align-items:center;justify-content:center;gap:8px;
            width:auto;min-width:0;min-height:0;padding:9px 12px;
            border:1px solid var(--public-hairline,#e5e7eb);border-radius:10px;background:#fff;
            color:var(--public-brand-green,#1a3a2a);font:650 14px/1.25 var(--font-sans);
            cursor:pointer;-webkit-tap-highlight-color:transparent
          }
          .workspace-back{padding-inline-start:4px;border-color:transparent;background:transparent}
          .workspace-action:hover,.workspace-action.active,.workspace-back:hover,.profile-signout:hover{
            border-color:var(--public-brand-lime,#d1f470);background:var(--public-lime-tint,#f8faf3)
          }
          .workspace-action:focus-visible,.workspace-back:focus-visible,.profile-signout:focus-visible{
            outline:2px solid var(--public-brand-green,#1a3a2a);outline-offset:2px
          }
          .workspace-search{width:min(32vw,260px);justify-content:flex-start}
          .workspace-search kbd{
            margin-inline-start:auto;padding:2px 6px;border:1px solid var(--public-hairline,#e5e7eb);
            border-radius:6px;background:#f8faf3;color:var(--public-muted,#6b7280);font:inherit;font-size:12px
          }
          .workspace-profile-wrap{position:relative;display:inline-flex}
          .profile-scrim{position:fixed;inset:0;z-index:1190;border:0;background:transparent}
          .profile-menu{
            position:absolute;z-index:1200;top:calc(100% + 8px);inset-inline-end:0;
            width:min(320px,calc(100vw - 32px));padding:14px;
            border:1px solid var(--public-hairline,#e5e7eb);border-top:4px solid var(--public-brand-lime,#d1f470);
            border-radius:16px;background:#fff;box-shadow:0 18px 46px rgba(26,58,42,.15)
          }
          .profile-identity{display:flex;flex-direction:column;gap:3px;margin-bottom:12px;min-width:0}
          .profile-identity strong{font-size:14px}.profile-identity span{font-size:12px;color:var(--public-muted,#6b7280);overflow-wrap:anywhere}
          .profile-signout{width:100%;margin-top:10px}
          .workspace-content-shell{
            width:100%;max-width:var(--public-content-max,1300px);min-width:0;margin:0 auto;
            box-sizing:border-box;overflow-x:hidden;overflow-x:clip
          }
          .workspace-public-shell .breadcrumbs{
            width:auto!important;max-width:none!important;margin:0!important;
            padding:14px var(--public-page-gutter,24px) 0!important;border:0!important;
            border-radius:0!important;background:transparent!important;box-shadow:none!important
          }
          .workspace-public-shell .inner-content-container{
            width:100%!important;max-width:var(--public-content-max,1300px)!important;min-width:0;
            margin:0 auto!important;box-sizing:border-box;overflow:visible!important
          }
          .workspace-public-action-tail{
            width:100%;max-width:var(--public-content-max,1300px);min-width:0;margin:0 auto;
            padding:8px var(--public-page-gutter,24px) 48px;box-sizing:border-box;
            overflow-x:hidden;overflow-x:clip
          }
          .workspace-public-shell .contacts-auth-modal input,
          .workspace-public-shell .contacts-auth-modal select,
          .workspace-public-shell .contacts-auth-modal textarea{font-size:16px!important}
          .workspace-public-shell .contacts-auth-modal .contacts-form-contact{grid-template-columns:minmax(0,1fr)!important}
          .workspace-public-shell .contacts-auth-modal .contacts-modal-body{min-width:0;overflow-y:auto;overscroll-behavior:contain;-webkit-overflow-scrolling:touch}
          @media(max-width:767px){
            .workspace-shell-body{min-height:calc(100vh - 96px);min-height:calc(100dvh - 96px);padding-top:96px}
            .workspace-utility-inner{
              padding:12px max(var(--public-mobile-page-gutter,16px),env(safe-area-inset-right,0px))
                12px max(var(--public-mobile-page-gutter,16px),env(safe-area-inset-left,0px));
              align-items:stretch;flex-direction:column;gap:10px
            }
            .workspace-context{width:100%;justify-content:flex-start}
            .workspace-actions{width:100%;display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:8px}
            .workspace-search{width:100%;min-width:0}.workspace-action span,.workspace-back span{white-space:nowrap}
            .workspace-public-shell .breadcrumbs{
              padding-inline:max(var(--public-mobile-page-gutter,16px),env(safe-area-inset-left,0px))!important;
              overflow-x:auto;scrollbar-width:none
            }
            .workspace-public-action-tail{
              padding-inline:max(var(--public-mobile-page-gutter,16px),env(safe-area-inset-left,0px));
              padding-bottom:calc(40px + env(safe-area-inset-bottom,0px))
            }
            .workspace-public-shell .customer-modal-overlay{
              align-items:flex-end!important;
              padding:max(8px,env(safe-area-inset-top,0px)) max(8px,env(safe-area-inset-right,0px))
                max(8px,env(safe-area-inset-bottom,0px)) max(8px,env(safe-area-inset-left,0px))!important
            }
            .workspace-public-shell .customer-modal-panel{
              width:100%!important;max-width:100%!important;
              max-height:calc(100dvh - 16px - env(safe-area-inset-top,0px) - env(safe-area-inset-bottom,0px))!important;
              border-radius:18px 18px 0 0!important
            }
            .workspace-public-shell .contacts-form-grid{grid-template-columns:minmax(0,1fr)!important}
            .workspace-public-shell .contacts-phone-control{grid-template-columns:minmax(76px,92px) minmax(0,1fr)!important}
            .workspace-public-shell .contacts-modal-actions{
              position:sticky;bottom:0;padding-bottom:max(14px,env(safe-area-inset-bottom,0px))!important;background:#fff
            }
          }
          @media(max-width:420px){
            .workspace-actions{grid-template-columns:minmax(0,1fr) auto auto}
            .workspace-actions .workspace-action:not(.workspace-search){padding-inline:10px}
            .workspace-actions .workspace-action:not(.workspace-search) span{
              position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)
            }
            .workspace-search kbd{display:none}
          }
          @media(prefers-reduced-motion:reduce){
            .workspace-public-shell *{scroll-behavior:auto!important;transition-duration:.01ms!important;animation-duration:.01ms!important}
          }
          @media(forced-colors:active){.workspace-action,.workspace-back,.profile-menu,.profile-signout{border-color:CanvasText}}
        `}</style>
      </div>
    </WorkspaceShellContext.Provider>
  );
};

const Layout: React.FC<LayoutProps> = props => {
  const nested = useContext( WorkspaceShellContext );
  if ( nested ) return <>{ props.children }</>;
  return <WorkspaceLayout { ...props } />;
};

export default Layout;
