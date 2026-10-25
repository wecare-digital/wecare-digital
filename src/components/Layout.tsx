/**
 * Authenticated WECARE.DIGITAL workspace shell.
 *
 * Product rule: there is no global business sidebar and no workspace/module dropdown.
 * Workspace Home + search are the navigation system; topic pages own their local tabs/actions.
 * Profile contains personal/session controls only.
 */
import React, { ReactNode, useEffect, useState } from 'react';
import { useRouter } from 'next/router';
import Link from 'next/link';
import SearchModal from './SearchModal';
import BottomNav from './BottomNav';
import BrandLockup from './BrandLockup';
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

const Layout: React.FC<LayoutProps> = ( { children, user, onSignOut, showBreadcrumbs = true } ) => {
  const router = useRouter();
  const { isPartner, loading: roleLoading } = useUserRole();
  const [ searchOpen, setSearchOpen ] = useState( false );
  const [ profileOpen, setProfileOpen ] = useState( false );
  const shortcutsModal = useKeyboardShortcutsModal();

  // Keep the existing partner boundary intact while the workspace IA is rebuilt.
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
      <header className="workspace-topbar">
        <div className="workspace-topbar-inner">
          <div className="workspace-leading">
            { !isHome && (
              <button type="button" className="workspace-back" onClick={ () => void router.push( '/workspace' ) }>
                <span aria-hidden="true">←</span>
                <span>Workspace</span>
              </button>
            ) }
            <Link href="/workspace" className="workspace-brand" aria-label="WECARE.DIGITAL Workspace Home">
              <BrandLockup compact />
            </Link>
          </div>

          <div className="workspace-actions" aria-label="Workspace actions">
            <button type="button" className="workspace-action workspace-search"
              onClick={ () => setSearchOpen( true ) } aria-label="Search workspace">
              <SearchGlyph /><span>Search</span><kbd>⌘K</kbd>
            </button>
            <button type="button" className="workspace-action workspace-tasks"
              onClick={ () => void router.push( '/workspace/task' ) } aria-label="Tasks">
              <TasksGlyph /><span className="desktop-action-label">Tasks</span>
            </button>
            <div className="workspace-profile-wrap">
              <button type="button" className={ `workspace-action ${profileOpen ? 'active' : ''}` }
                aria-label="Profile" aria-expanded={ profileOpen }
                onClick={ () => setProfileOpen( ( value ) => !value ) }>
                <PersonGlyph /><span className="desktop-action-label">Profile</span>
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
                    {/* Native shells only - renders nothing on the web. The one place this
                        app asks for notification permission, and only on a tap. */}
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
      </header>

      {/*
        data-wc-no-translate is a data-integrity guard. Customer names, phone numbers, message
        bodies, order lines and money are operational records; translating them in place can
        mutate what an operator believes the source data says.
      */}
      <main id="main-content" className="main-content workspace-main" data-wc-no-translate="true">
        { showBreadcrumbs && <Breadcrumbs /> }
        <div className="inner-content-container">
          { children }
        </div>
      </main>

      <BottomNav
        onSearch={ () => setSearchOpen( true ) }
        onProfile={ () => setProfileOpen( ( value ) => !value ) }
        profileOpen={ profileOpen }
      />
      <SearchModal isOpen={ searchOpen } onClose={ () => setSearchOpen( false ) } />
      <KeyboardShortcuts isOpen={ shortcutsModal.isOpen } onClose={ shortcutsModal.close } />

      <style jsx>{`
        .workspace-shell{
          display:block;
          min-height:100dvh;
          min-height:100svh;
          background:#fff;
        }
        .workspace-topbar{
          position:sticky;
          top:0;
          z-index:1100;
          background:rgba(255,255,255,.96);
          border-bottom:1px solid var(--border);
          backdrop-filter:blur(16px);
          -webkit-backdrop-filter:blur(16px);
          padding-top:env(safe-area-inset-top,0px);
        }
        .workspace-topbar-inner{
          min-height:60px;
          width:min(100%,1440px);
          margin:0 auto;
          padding:8px max(16px,env(safe-area-inset-right,0px)) 8px max(16px,env(safe-area-inset-left,0px));
          display:flex;
          align-items:center;
          justify-content:space-between;
          gap:16px;
          box-sizing:border-box;
        }
        .workspace-leading,.workspace-actions{display:flex;align-items:center;gap:8px;min-width:0}
        .workspace-brand{display:inline-flex;align-items:center;text-decoration:none;border-radius:10px;min-height:44px}
        .workspace-back,.workspace-action{
          min-height:44px;
          min-width:44px;
          border:1px solid var(--border);
          border-radius:12px;
          background:#fff;
          color:var(--text);
          font:inherit;
          font-size:var(--text-sm);
          font-weight:650;
          cursor:pointer;
          display:inline-flex;
          align-items:center;
          justify-content:center;
          gap:8px;
          padding:8px 12px;
          -webkit-tap-highlight-color:transparent;
        }
        .workspace-back{border-color:transparent;padding-inline-start:4px}
        .workspace-action:hover,.workspace-action.active,.workspace-back:hover{background:var(--bg-secondary);border-color:var(--lime)}
        .workspace-action:focus-visible,.workspace-back:focus-visible,.workspace-brand:focus-visible,.profile-signout:focus-visible{
          outline:2px solid var(--accent);outline-offset:2px
        }
        .workspace-search{min-width:min(32vw,260px);justify-content:flex-start}
        .workspace-search kbd{
          margin-inline-start:auto;
          color:var(--text-muted);
          background:var(--bg-secondary);
          border:1px solid var(--border);
          border-radius:6px;
          padding:2px 6px;
          font:inherit;
          font-size:var(--text-xs);
        }
        .workspace-profile-wrap{position:relative;display:inline-flex}
        .profile-scrim{position:fixed;inset:0;z-index:1;border:0;background:transparent;cursor:default}
        .profile-menu{
          position:absolute;
          z-index:2;
          top:calc(100% + 8px);
          inset-inline-end:0;
          width:min(300px,calc(100vw - 24px));
          border:1px solid var(--border);
          border-radius:14px;
          background:#fff;
          box-shadow:0 12px 36px rgba(0,0,0,.14);
          overflow:hidden;
        }
        .profile-identity{display:flex;flex-direction:column;gap:4px;padding:16px}
        .profile-identity strong{font-size:var(--text-md);color:var(--text)}
        .profile-identity span{font-size:var(--text-xs);color:var(--text-muted);overflow-wrap:anywhere}
        .profile-signout{
          width:100%;min-height:48px;border:0;border-top:1px solid var(--border);
          background:#fff;color:var(--text);font:inherit;font-weight:650;text-align:start;padding:12px 16px;cursor:pointer
        }
        .profile-signout:hover{background:var(--bg-secondary)}
        .workspace-shell :global(.workspace-main){
          margin-inline-start:0;
          width:100%;
          max-width:none;
          min-height:calc(100dvh - 60px);
          box-sizing:border-box;
          overflow-x:clip;
          padding:0;
        }
        .workspace-shell :global(.inner-content-container){
          width:min(100%,1440px);
          margin:0 auto;
          box-sizing:border-box;
          border-radius:0;
        }
        /* Workspace Home is a launchpad, not an inner tool panel. Layout.css gives every
           inner-content-container a bordered 30px card; keeping that on /workspace created
           the giant framed rectangle visible in the production screenshot. Other workspace
           pages keep their existing panel contract. */
        .workspace-home-shell :global(.inner-content-container){
          border:0;
          border-radius:0;
          margin:0 auto;
          overflow:visible;
          background:#fff;
        }
        @media(max-width:768px){
          .workspace-topbar-inner{min-height:56px;padding-block:6px}
          .workspace-search{min-width:44px;width:44px;padding:0}
          .workspace-search span,.workspace-search kbd,.desktop-action-label{display:none}
          .workspace-back span:last-child{display:none}
          .workspace-brand{max-width:150px;overflow:hidden}
          .workspace-shell :global(.workspace-main){
            min-height:calc(100dvh - 56px);
            padding-bottom:calc(68px + env(safe-area-inset-bottom,0px));
          }
          .workspace-shell :global(.inner-content-container){margin:0;padding:0}
        }
        @media(max-width:360px){
          .workspace-topbar-inner{
            gap:8px;
            padding-inline:
              max(8px,env(safe-area-inset-left,0px))
              max(8px,env(safe-area-inset-right,0px));
          }
          .workspace-brand{max-width:112px}
          .workspace-actions{gap:4px}
          /* Search and Tasks already have permanent bottom-nav destinations on phones.
             Hiding the duplicated top-bar buttons is what lets Back + brand + Profile
             reflow at the ~280px foldable harness without clipping. */
          .workspace-search,.workspace-tasks{display:none}
          .workspace-action,.workspace-back{padding:0}
        }
        @media(prefers-reduced-motion:reduce){
          .workspace-topbar{scroll-behavior:auto}
        }
        @media(forced-colors:active){
          .workspace-action,.workspace-back,.profile-menu{border:1px solid CanvasText}
        }
      `}</style>
    </div>
  );
};

export default Layout;
