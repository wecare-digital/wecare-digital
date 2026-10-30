/**
 * Canonical authenticated WECARE.DIGITAL Workspace shell.
 *
 * Authentication stays in AuthShell/_app. This component owns authenticated chrome only:
 * shared public Header -> Workspace action layer -> route content -> PublicShare -> Footer.
 *
 * Layout is intentionally also a compatibility boundary. A large retained Workspace surface
 * imports Layout from nested components; nested Layout calls collapse to content-only so a child
 * can never introduce a second Header/PublicShare/Footer.
 */
import React, {
  ReactNode, createContext, useContext, useEffect, useState,
} from 'react';
import { useRouter } from 'next/router';
import Link from 'next/link';
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
  shellClassName?: string;
}

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

const WorkspaceShell: React.FC<LayoutProps> = ( {
  children, user, onSignOut, showBreadcrumbs = true, shellClassName = '',
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
    <WorkspaceShellContext.Provider value>
      <div className={ `layout workspace-shell ${ isHome ? 'workspace-home-shell' : '' } ${ shellClassName }`.trim() }>
        <Header />

        <div className="workspace-after-header">
          <nav className="workspace-action-layer" aria-label="Workspace actions">
            <div className="workspace-action-layer-inner">
              <div className="workspace-action-leading">
                { !isHome && (
                  <Link href="/workspace" className="workspace-back" aria-label="Back to Workspace">
                    <span aria-hidden="true">←</span>
                    <span>Workspace</span>
                  </Link>
                ) }
                <span className="workspace-context-label">Workspace</span>
              </div>

              <div className="workspace-actions">
                <button type="button" className="workspace-action workspace-search"
                  onClick={ () => setSearchOpen( true ) } aria-label="Search workspace">
                  <SearchGlyph /><span>Search</span><kbd>⌘K</kbd>
                </button>
                <button type="button" className="workspace-action"
                  onClick={ () => void router.push( '/workspace/task' ) } aria-label="Tasks">
                  <TasksGlyph /><span>Tasks</span>
                </button>
                <div className="workspace-profile-wrap">
                  <button type="button" className={ `workspace-action ${ profileOpen ? 'active' : '' }` }
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
          </nav>

          {/*
            Operational/customer records remain outside the language system. Shared Header,
            Workspace action copy, Stay connected and Footer remain translatable.
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
        </div>

        <SearchModal isOpen={ searchOpen } onClose={ () => setSearchOpen( false ) } />
        <KeyboardShortcuts isOpen={ shortcutsModal.isOpen } onClose={ shortcutsModal.close } />

        <style jsx>{`
          .workspace-shell{
            display:block;
            min-width:0;
            min-height:100vh;
            min-height:100dvh;
            overflow-x:hidden;
            overflow-x:clip;
            background:var(--public-bg,#fff);
            color:var(--public-text,#111);
            font-family:var(--font-sans);
          }
          .workspace-after-header{
            min-width:0;
            min-height:calc(100vh - 108px);
            min-height:calc(100dvh - 108px);
            padding-top:108px;
            overflow-x:hidden;
            overflow-x:clip;
          }
          .workspace-action-layer{
            width:100%;
            border-bottom:1px solid var(--public-hairline,var(--border));
            background:#fff;
          }
          .workspace-action-layer-inner{
            width:100%;
            max-width:var(--public-content-max);
            min-width:0;
            margin:0 auto;
            padding:14px var(--public-page-gutter);
            display:flex;
            align-items:center;
            justify-content:space-between;
            gap:16px;
            box-sizing:border-box;
          }
          .workspace-action-leading,.workspace-actions{
            display:flex;
            align-items:center;
            gap:8px;
            min-width:0;
          }
          .workspace-context-label{
            color:var(--public-muted,var(--text-muted));
            font-size:var(--public-meta-size,14px);
            font-weight:700;
            white-space:nowrap;
          }
          .workspace-back,.workspace-action{
            min-width:0;
            border:1px solid var(--public-hairline,var(--border));
            border-radius:12px;
            background:#fff;
            color:var(--public-brand-green,var(--text));
            font:650 var(--public-supporting-size,16px)/1.2 var(--font-sans);
            cursor:pointer;
            display:inline-flex;
            align-items:center;
            justify-content:center;
            gap:8px;
            padding:9px 12px;
            text-decoration:none;
            -webkit-tap-highlight-color:transparent;
          }
          .workspace-back{
            border-color:transparent;
            padding-inline-start:0;
          }
          .workspace-action:hover,.workspace-action.active,.workspace-back:hover{
            background:var(--public-lime-tint,var(--bg-secondary));
            border-color:var(--public-brand-lime,var(--lime));
          }
          .workspace-action:focus-visible,.workspace-back:focus-visible,.profile-signout:focus-visible{
            outline:2px solid var(--public-brand-green,var(--accent));
            outline-offset:2px;
          }
          .workspace-search{min-width:min(28vw,260px);justify-content:flex-start}
          .workspace-search kbd{
            margin-inline-start:auto;
            color:var(--public-muted,var(--text-muted));
            background:var(--public-lime-tint,var(--bg-secondary));
            border:1px solid var(--public-hairline,var(--border));
            border-radius:6px;
            padding:2px 6px;
            font:inherit;
            font-size:var(--public-meta-size,14px);
          }
          .workspace-profile-wrap{position:relative;display:inline-flex;min-width:0}
          .profile-scrim{position:fixed;inset:0;z-index:1190;border:0;background:transparent;cursor:default}
          .profile-menu{
            position:absolute;
            z-index:1200;
            top:calc(100% + 8px);
            inset-inline-end:0;
            width:min(300px,calc(100vw - 32px));
            max-height:min(70vh,70dvh);
            overflow:auto;
            border:1px solid var(--public-hairline,var(--border));
            border-radius:14px;
            background:#fff;
            box-shadow:0 12px 36px rgba(0,0,0,.14);
          }
          .profile-identity{display:flex;flex-direction:column;gap:4px;padding:16px}
          .profile-identity strong{font-size:var(--public-card-size,18px);color:var(--public-text,var(--text))}
          .profile-identity span{font-size:var(--public-meta-size,14px);color:var(--public-muted,var(--text-muted));overflow-wrap:anywhere}
          .profile-signout{
            width:100%;
            border:0;
            border-top:1px solid var(--public-hairline,var(--border));
            background:#fff;
            color:var(--public-brand-green,var(--text));
            font:650 16px/1.3 var(--font-sans);
            text-align:start;
            padding:13px 16px;
            cursor:pointer;
          }
          .profile-signout:hover{background:var(--public-lime-tint,var(--bg-secondary))}
          .workspace-shell :global(.workspace-main){
            width:100%;
            max-width:none;
            min-width:0;
            min-height:0;
            margin:0;
            padding:0;
            overflow-x:hidden;
            overflow-x:clip;
            box-sizing:border-box;
          }
          .workspace-content-frame{
            width:100%;
            max-width:var(--public-content-max);
            min-width:0;
            margin:0 auto;
            padding:0 var(--public-page-gutter);
            box-sizing:border-box;
            overflow-x:hidden;
            overflow-x:clip;
          }
          .workspace-shell :global(.inner-content-container){
            width:100% !important;
            max-width:100% !important;
            min-width:0;
            margin:0 auto !important;
            box-sizing:border-box;
          }
          .workspace-public-share{
            width:100%;
            max-width:var(--public-content-max);
            min-width:0;
            margin:0 auto;
            padding:8px var(--public-page-gutter) 48px;
            box-sizing:border-box;
            overflow-x:hidden;
            overflow-x:clip;
          }
          @media(max-width:767px){
            .workspace-after-header{
              min-height:calc(100vh - 96px);
              min-height:calc(100dvh - 96px);
              padding-top:96px;
            }
            .workspace-action-layer-inner{
              padding:
                10px max(var(--public-mobile-page-gutter),env(safe-area-inset-right,0px))
                10px max(var(--public-mobile-page-gutter),env(safe-area-inset-left,0px));
              align-items:flex-start;
              gap:10px;
            }
            .workspace-action-leading{padding-top:2px}
            .workspace-context-label{display:none}
            .workspace-actions{
              justify-content:flex-end;
              flex-wrap:wrap;
            }
            .workspace-action{
              padding:8px 10px;
              font-size:14px;
            }
            .workspace-search{min-width:0}
            .workspace-search kbd{display:none}
            .workspace-content-frame{
              padding-inline:
                max(var(--public-mobile-page-gutter),env(safe-area-inset-left,0px))
                max(var(--public-mobile-page-gutter),env(safe-area-inset-right,0px));
            }
            .workspace-public-share{
              padding-inline:
                max(var(--public-mobile-page-gutter),env(safe-area-inset-left,0px))
                max(var(--public-mobile-page-gutter),env(safe-area-inset-right,0px));
              padding-bottom:calc(40px + env(safe-area-inset-bottom,0px));
            }
            .profile-menu{
              position:fixed;
              inset-inline:max(var(--public-mobile-page-gutter),env(safe-area-inset-left,0px))
                max(var(--public-mobile-page-gutter),env(safe-area-inset-right,0px));
              top:auto;
              bottom:calc(var(--public-mobile-page-gutter) + env(safe-area-inset-bottom,0px));
              width:auto;
              max-height:min(70vh,70dvh);
            }
          }
          @media(max-width:399px){
            .workspace-action-layer-inner{display:block}
            .workspace-action-leading{margin-bottom:8px}
            .workspace-actions{justify-content:flex-start}
            .workspace-action{font-size:13px}
          }
          @media(max-width:279px){
            .workspace-actions{display:grid;grid-template-columns:minmax(0,1fr)}
            .workspace-action,.workspace-profile-wrap{width:100%}
            .workspace-action{justify-content:flex-start}
          }
          @media(prefers-reduced-motion:reduce){
            .workspace-action,.workspace-back,.profile-signout{transition:none}
          }
          @media(forced-colors:active){
            .workspace-action,.workspace-back,.profile-menu{border-color:CanvasText}
          }
        `}</style>
      </div>
    </WorkspaceShellContext.Provider>
  );
};

const Layout: React.FC<LayoutProps> = props => {
  const nested = useContext( WorkspaceShellContext );
  return nested ? <>{ props.children }</> : <WorkspaceShell { ...props } />;
};

export default Layout;
