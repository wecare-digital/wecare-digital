/**
 * WsShell — authenticated /ws navigation and content surface.
 *
 * Desktop: one collapsible full-height sidebar with the actual homepage
 * BrandLockup, six routes and persistent icon-only navigation. The account
 * strip and an accessible icon-only Sign out stay pinned to the foot.
 * Collapsed preference survives /ws route changes and reloads. The right
 * side remains content-only, without a repeated header or footer.
 *
 * Mobile: six reachable navigation destinations in a safe-area-aware bottom bar,
 * including Home. Sign out remains available in Settings, without introducing
 * a duplicate mobile header or covering page content.
 *
 * The original Cognito signOut/user contract is passed down from WsAuthShell;
 * customer /auth, /workspace and all private business panels remain unchanged.
 */
import React, { ReactNode, useSyncExternalStore } from 'react';
import Link from 'next/link';
import BrandLockup from '../BrandLockup';
import WsNotionTheme from './WsNotionTheme';

export type WsSection = 'home' | 'inbox' | 'collect' | 'customers' | 'commerce' | 'settings';

export interface WsShellProps {
  children: ReactNode;
  active: WsSection;
  user?: any;
  signOut?: () => void;
}

interface NavItem {
  id: WsSection;
  label: string;
  href: string;
  icon: () => React.JSX.Element;
}

const HomeGlyph = () => (
  <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="m3.5 10 8.5-7 8.5 7v10.5H3.5z" /><path d="M9 20.5v-7h6v7" />
  </svg>
);

const InboxGlyph = () => (
  <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M4 4h16v16H4z" /><path d="M4 14h4l2 3h4l2-3h4" />
  </svg>
);

const CollectGlyph = () => (
  <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M6 3h9l3 3v15H6z" /><path d="M9 8h6M9 12h6M9 16h4" />
  </svg>
);

const CustomersGlyph = () => (
  <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="9" cy="8" r="3.4" /><path d="M3.5 20c.7-3.6 2.9-5.4 5.5-5.4s4.8 1.8 5.5 5.4" /><path d="M16 5.2a3 3 0 0 1 0 5.6M18 14.6c2 .6 3.4 2.2 3.9 4.9" />
  </svg>
);

const CommerceGlyph = () => (
  <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M4 7h16l-1.2 10.5a2 2 0 0 1-2 1.5H7.2a2 2 0 0 1-2-1.5z" /><path d="M9 7a3 3 0 0 1 6 0" />
  </svg>
);

const SettingsGlyph = () => (
  <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="12" cy="12" r="3" /><path d="M12 2.5v2.2M12 19.3v2.2M4.2 7l1.9 1.1M17.9 15.9l1.9 1.1M4.2 17l1.9-1.1M17.9 8.1l1.9-1.1" />
  </svg>
);

const AccountGlyph = () => (
  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="12" cy="8" r="3.5" /><path d="M5 20c0-4.2 2.6-6.5 7-6.5s7 2.3 7 6.5" />
  </svg>
);

const SidebarToggleGlyph = () => (
  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="3.5" y="4" width="17" height="16" rx="3" />
    <path d="M9.5 4v16m6.5-11-3 3 3 3" />
  </svg>
);

const SignOutGlyph = () => (
  <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M15 4h4v16h-4" /><path d="M10 12H3" /><path d="m6 8-4 4 4 4" />
  </svg>
);

const NAV_ITEMS: NavItem[] = [
  { id: 'home', label: 'Home', href: '/ws', icon: HomeGlyph },
  { id: 'inbox', label: 'Inbox', href: '/ws/inbox', icon: InboxGlyph },
  { id: 'collect', label: 'Collect', href: '/ws/collect', icon: CollectGlyph },
  { id: 'customers', label: 'Customers', href: '/ws/customers', icon: CustomersGlyph },
  { id: 'commerce', label: 'Commerce', href: '/ws/commerce', icon: CommerceGlyph },
  { id: 'settings', label: 'Settings', href: '/ws/settings', icon: SettingsGlyph },
];

/* Persist the sidebar affordance across Next page transitions without reading
   browser storage during SSR: useSyncExternalStore has an explicit server
   snapshot and keeps state correct across multiple mounted /ws shells. */
const SIDEBAR_KEY = 'wecare-ws-sidebar-collapsed-v1';
const sidebarSubscribers = new Set<() => void>();
let sidebarFallback = false;

const getSidebarCollapsed = (): boolean => {
  if (typeof window === 'undefined') return false;
  try {
    const saved = window.localStorage.getItem(SIDEBAR_KEY);
    return saved === null ? sidebarFallback : saved === 'true';
  } catch {
    return sidebarFallback;
  }
};
const getServerSidebarCollapsed = (): boolean => false;
const subscribeSidebar = (notify: () => void): (() => void) => {
  sidebarSubscribers.add(notify);
  const onStorage = (event: StorageEvent) => {
    if (event.key === SIDEBAR_KEY || event.key === null) notify();
  };
  if (typeof window !== 'undefined') window.addEventListener('storage', onStorage);
  return () => {
    sidebarSubscribers.delete(notify);
    if (typeof window !== 'undefined') window.removeEventListener('storage', onStorage);
  };
};
const saveSidebarCollapsed = (next: boolean): void => {
  sidebarFallback = next;
  if (typeof window !== 'undefined') {
    try { window.localStorage.setItem(SIDEBAR_KEY, String(next)); }
    catch { /* Private browsing/storage-disabled: in-memory state still works. */ }
  }
  sidebarSubscribers.forEach(notify => notify());
};

const WsShell: React.FC<WsShellProps> = ( { children, active, user, signOut } ) => {
  const collapsed = useSyncExternalStore(subscribeSidebar, getSidebarCollapsed, getServerSidebarCollapsed);
  const toggleSidebar = () => saveSidebarCollapsed(!collapsed);
  const loginId = user?.signInDetails?.loginId || user?.email || user?.username || '';

  return (
    <div className="ws-shell ws-notion" data-ws-collapsed={ collapsed ? 'true' : 'false' }>
      <WsNotionTheme />
      {/* Desktop: one responsive sidebar, with the exact public brand lockup. */}
      <aside className="ws-sidebar" aria-label="Workspace sidebar">
        <div className="ws-sidebar-brand">
          <Link
            href="/ws"
            className="ws-brand-side"
            aria-label="WECARE.DIGITAL workspace home"
            title={ collapsed ? 'WECARE.DIGITAL — Home' : undefined }
          >
            <BrandLockup compact />
          </Link>
          <button
            type="button"
            className="ws-sidebar-toggle"
            onClick={ toggleSidebar }
            aria-label={ collapsed ? 'Expand sidebar' : 'Collapse sidebar' }
            aria-expanded={ !collapsed }
            aria-controls="ws-sidebar-navigation"
            title={ collapsed ? 'Expand sidebar' : 'Collapse sidebar' }
          >
            <SidebarToggleGlyph />
          </button>
        </div>

        <nav id="ws-sidebar-navigation" className="ws-nav" aria-label="Workspace sections">
          <span className="ws-nav-caption">NAVIGATION</span>
          { NAV_ITEMS.map( item => {
            const Icon = item.icon;
            const isActive = item.id === active;
            return (
              <Link
                key={ item.id }
                href={ item.href }
                className={ `ws-nav-link ${isActive ? 'active' : ''}` }
                aria-label={ item.label }
                title={ collapsed ? item.label : undefined }
                aria-current={ isActive ? 'page' : undefined }
              >
                <span className="ws-nav-icon"><Icon /></span>
                <span className="ws-nav-label">{ item.label }</span>
              </Link>
            );
          } ) }
        </nav>

        <div className="ws-sidebar-foot">
          <div className="ws-account" title={ loginId || 'Workspace account' }>
            <span className="ws-account-avatar"><AccountGlyph /></span>
            <span className="ws-account-copy">
              <span className="ws-account-label">Signed in</span>
              <span className="ws-account-id" data-wc-no-translate="true" title={ loginId || undefined }>
                { loginId || 'Workspace account' }
              </span>
            </span>
          </div>
          <button
            type="button"
            className="ws-signout"
            onClick={ () => signOut?.() }
            disabled={ !signOut }
            aria-label="Sign out"
            title="Sign out"
          >
            <SignOutGlyph />
          </button>
        </div>
      </aside>

      {/* Only business-page content remains on the right; no extra header/footer. */}
      <main id="ws-main" className="ws-main" data-wc-no-translate="true">
        <div className="ws-content">{ children }</div>
      </main>

      {/* Mobile bottom navigation */}
      <nav className="ws-bottomnav" aria-label="Mobile workspace navigation">
        { NAV_ITEMS.map( item => {
          const Icon = item.icon;
          const isActive = item.id === active;
          return (
            <Link
              key={ item.id }
              href={ item.href }
              className={ `ws-bottom-link ${isActive ? 'active' : ''}` }
              aria-current={ isActive ? 'page' : undefined }
            >
              <span className="ws-bottom-icon"><Icon /></span>
              <span className="ws-bottom-label">{ item.label }</span>
            </Link>
          );
        } ) }
      </nav>

      <style jsx>{`
        .ws-shell{
          --ws-sidebar-w:274px;
          --ws-sidebar-mini-w:80px;
          --ws-bottomnav-h:64px;
          min-height:100vh;
          min-height:100dvh;
          min-width:0;
          background:var(--bg,#fff);
          color:var(--text,#1a1a1a);
          font-family:var(--font-sans,Inter,system-ui,sans-serif);
          overflow-x:hidden;
          overflow-x:clip;
        }
        /* Homepage BrandLockup owns its PNG and stacked wordmark; the sidebar
           only clips the extra wordmark when collapsed. No badge/square behind
           the logo, and no second source of brand geometry. */
        .ws-sidebar-brand{
          position:relative;
          display:flex;
          align-items:center;
          min-height:72px;
          min-width:0;
          padding:0 0 22px;
          margin-bottom:20px;
          border-bottom:1px solid var(--border,#e5e7eb);
        }
        .ws-brand-side{
          display:inline-flex;
          align-items:center;
          width:100%;
          min-width:0;
          min-height:54px;
          overflow:hidden;
          color:var(--public-brand-green,#1a3a2a);
          text-decoration:none;
          -webkit-tap-highlight-color:transparent;
        }
        .ws-brand-side:focus-visible{
          outline:2px solid var(--public-brand-green,#1a3a2a);
          outline-offset:-2px;
          border-radius:10px;
        }
        .ws-sidebar-toggle{
          position:absolute;
          z-index:4;
          top:12px;
          right:-35px;
          display:inline-flex;
          align-items:center;
          justify-content:center;
          width:34px;
          height:34px;
          padding:0;
          border:1px solid var(--border,#e5e7eb);
          border-radius:12px;
          background:var(--surface,#fff);
          color:var(--public-brand-green,#1a3a2a);
          box-shadow:0 2px 8px rgba(26,58,42,.08);
          cursor:pointer;
          -webkit-tap-highlight-color:transparent;
          transition:background-color .18s ease,border-color .18s ease,box-shadow .18s ease;
        }
        .ws-sidebar-toggle:hover{
          background:var(--public-lime-tint,rgba(209,244,112,.22));
          border-color:var(--public-brand-lime,#d1f470);
          box-shadow:0 2px 12px rgba(26,58,42,.11);
        }
        .ws-sidebar-toggle:focus-visible{
          outline:2px solid var(--public-brand-green,#1a3a2a);
          outline-offset:3px;
        }
        .ws-sidebar-toggle svg{display:block}

        /* The entire right side is a single open reading surface. */
        .ws-sidebar{display:none}
        .ws-main{
          display:block;
          min-width:0;
          min-height:100vh;
          min-height:100dvh;
          padding-bottom:calc(var(--ws-bottomnav-h) + env(safe-area-inset-bottom,0px));
          background:var(--surface,#fff);
          overflow-x:hidden;
          overflow-x:clip;
          box-sizing:border-box;
        }
        .ws-content{
          width:100%;
          min-width:0;
          box-sizing:border-box;
          margin-inline:auto;
          padding:24px
            max(16px,env(safe-area-inset-right,0px))
            32px
            max(16px,env(safe-area-inset-left,0px));
        }

        /* All six sections, including Home, stay reachable without a top bar. */
        .ws-bottomnav{
          position:fixed;
          z-index:1100;
          inset-inline:0;
          bottom:0;
          display:flex;
          align-items:stretch;
          height:calc(var(--ws-bottomnav-h) + env(safe-area-inset-bottom,0px));
          padding-bottom:env(safe-area-inset-bottom,0px);
          padding-inline:env(safe-area-inset-left,0px) env(safe-area-inset-right,0px);
          background:var(--surface,#fff);
          border-top:1px solid var(--border,#e5e7eb);
          box-sizing:border-box;
        }
        .ws-bottom-link{
          position:relative;
          flex:1 1 0;
          display:flex;
          flex-direction:column;
          align-items:center;
          justify-content:center;
          gap:4px;
          min-width:0;
          min-height:var(--tap-min,44px);
          padding:7px 1px;
          color:var(--text-muted,#6b7280);
          text-decoration:none;
          -webkit-tap-highlight-color:transparent;
          transition:background-color .16s ease,color .16s ease;
        }
        .ws-bottom-link.active{
          color:var(--accent,#1a3a2a);
          background:var(--lime-tint,rgba(209,244,112,.22));
        }
        .ws-bottom-link.active::before{
          content:'';
          position:absolute;
          top:0;
          left:50%;
          transform:translateX(-50%);
          width:28px;
          height:3px;
          border-radius:0 0 3px 3px;
          background:var(--lime,#d1f470);
        }
        .ws-bottom-icon{display:inline-flex;align-items:center;justify-content:center}
        .ws-bottom-label{
          max-width:100%;
          overflow:hidden;
          text-overflow:ellipsis;
          white-space:nowrap;
          color:inherit;
          font-size:10px;
          font-weight:650;
          line-height:1.2;
          letter-spacing:-.03em;
        }
        .ws-bottom-link:focus-visible{
          outline:2px solid var(--accent,#1a3a2a);
          outline-offset:-3px;
          border-radius:7px;
        }

        @media(min-width:768px){
          .ws-shell{
            display:grid;
            grid-template-columns:var(--ws-sidebar-w) minmax(0,1fr);
            transition:grid-template-columns .2s ease;
          }
          .ws-shell[data-ws-collapsed='true']{--ws-sidebar-w:var(--ws-sidebar-mini-w)}
          .ws-bottomnav{display:none}
          .ws-main{padding-bottom:0}
          .ws-sidebar{
            position:sticky;
            z-index:20;
            top:0;
            align-self:start;
            display:flex;
            flex-direction:column;
            height:100vh;
            height:100dvh;
            min-width:0;
            padding:22px 18px
              calc(20px + env(safe-area-inset-bottom,0px))
              max(18px,env(safe-area-inset-left,0px));
            background:var(--bg-secondary,#fcfdfb);
            border-inline-end:1px solid var(--border,#e5e7eb);
            box-sizing:border-box;
          }
          .ws-nav{
            display:flex;
            flex-direction:column;
            gap:5px;
            min-height:0;
            flex:1 1 auto;
            overflow-y:auto;
            overflow-x:hidden;
            scrollbar-width:thin;
          }
          .ws-nav-caption{
            padding:2px 12px 10px;
            color:var(--text-muted,#6b7280);
            font-size:10px;
            font-weight:750;
            line-height:1.25;
            letter-spacing:.11em;
          }
          .ws-nav-link{
            position:relative;
            display:flex;
            align-items:center;
            gap:11px;
            flex:0 0 auto;
            min-height:48px;
            padding:6px 9px;
            border-radius:13px;
            color:var(--text-muted,#6b7280);
            text-decoration:none;
            font-size:14px;
            font-weight:600;
            line-height:1.35;
            white-space:nowrap;
            transition:background-color .16s ease,color .16s ease;
          }
          .ws-nav-link:hover{
            background:var(--public-lime-tint,rgba(209,244,112,.22));
            color:var(--public-brand-green,#1a3a2a);
          }
          .ws-nav-link.active{
            background:var(--public-lime-tint,rgba(209,244,112,.22));
            color:var(--public-brand-green,#1a3a2a);
            font-weight:700;
          }
          .ws-nav-link.active::before{
            content:'';
            position:absolute;
            inset-inline-start:0;
            top:12px;
            bottom:12px;
            width:3px;
            border-radius:3px;
            background:var(--public-brand-lime,#d1f470);
          }
          .ws-nav-icon{
            display:inline-flex;
            align-items:center;
            justify-content:center;
            width:34px;
            height:34px;
            flex:0 0 34px;
            border-radius:10px;
            color:var(--text-muted,#6b7280);
            transition:background-color .16s ease,color .16s ease;
          }
          .ws-nav-link:is(:hover,.active) .ws-nav-icon{
            color:var(--public-brand-green,#1a3a2a);
          }
          .ws-nav-link.active .ws-nav-icon{
            background:var(--public-brand-lime,#d1f470);
          }
          .ws-nav-link:focus-visible{
            outline:2px solid var(--public-brand-green,#1a3a2a);
            outline-offset:2px;
          }

          /* The account and sign-out sit together as a single compact footer.
             Sign out is icon-only at every sidebar width, but has an accessible
             name and tooltip; it is not a dead glyph. */
          .ws-sidebar-foot{
            display:flex;
            align-items:center;
            gap:8px;
            min-width:0;
            margin-top:16px;
            padding:18px 2px 0;
            border-top:1px solid var(--border,#e5e7eb);
          }
          .ws-account{
            display:flex;
            align-items:center;
            gap:9px;
            flex:1 1 auto;
            min-width:0;
            padding:0;
          }
          .ws-account-avatar{
            display:inline-flex;
            align-items:center;
            justify-content:center;
            width:38px;
            height:38px;
            flex:0 0 38px;
            border-radius:12px;
            background:var(--public-lime-tint,rgba(209,244,112,.22));
            color:var(--public-brand-green,#1a3a2a);
          }
          .ws-account-copy{
            display:flex;
            flex-direction:column;
            gap:3px;
            min-width:0;
          }
          .ws-account-label{
            color:var(--text-muted,#6b7280);
            font-size:11px;
            line-height:1.2;
          }
          .ws-account-id{
            color:var(--text,#1a1a1a);
            font-size:12px;
            font-weight:650;
            line-height:1.35;
            overflow:hidden;
            white-space:nowrap;
            text-overflow:ellipsis;
          }
          .ws-signout{
            display:inline-flex;
            align-items:center;
            justify-content:center;
            width:44px;
            height:44px;
            flex:0 0 44px;
            padding:0;
            border:1px solid var(--border,#e5e7eb);
            border-radius:13px;
            background:var(--surface,#fff);
            color:var(--public-brand-green,#1a3a2a);
            cursor:pointer;
            -webkit-tap-highlight-color:transparent;
            transition:background-color .16s ease,border-color .16s ease,transform .16s ease;
          }
          .ws-signout:hover:not(:disabled){
            background:var(--public-brand-lime,#d1f470);
            border-color:var(--public-brand-lime,#d1f470);
            transform:translateY(-1px);
          }
          .ws-signout:disabled{opacity:.5;cursor:not-allowed}
          .ws-signout:focus-visible{
            outline:2px solid var(--public-brand-green,#1a3a2a);
            outline-offset:3px;
          }
          .ws-content{
            max-width:1250px;
            width:100%;
            margin:0 auto;
            padding:40px clamp(28px,3.5vw,56px) 72px;
          }

          /* Collapsed sidebar: every route remains visible as an icon.
             Content grows automatically because the GRID track actually
             shrinks, rather than merely covering a full-width sidebar. */
          .ws-shell[data-ws-collapsed='true'] .ws-sidebar{
            padding-inline:12px;
          }
          .ws-shell[data-ws-collapsed='true'] .ws-sidebar-brand{
            justify-content:center;
            margin-bottom:16px;
          }
          .ws-shell[data-ws-collapsed='true'] .ws-brand-side{
            width:44px;
            max-width:44px;
            flex:0 0 44px;
            overflow:hidden;
          }
          .ws-shell[data-ws-collapsed='true'] .ws-sidebar-toggle{
            right:-30px;
            top:12px;
          }
          .ws-shell[data-ws-collapsed='true'] .ws-sidebar-toggle svg{
            transform:rotate(180deg);
          }
          .ws-shell[data-ws-collapsed='true'] .ws-nav-caption,
          .ws-shell[data-ws-collapsed='true'] .ws-nav-label,
          .ws-shell[data-ws-collapsed='true'] .ws-account-copy{
            display:none;
          }
          .ws-shell[data-ws-collapsed='true'] .ws-nav-link{
            justify-content:center;
            width:100%;
            min-width:0;
            padding:7px 3px;
          }
          .ws-shell[data-ws-collapsed='true'] .ws-nav-icon{
            width:38px;
            height:38px;
            flex-basis:38px;
          }
          .ws-shell[data-ws-collapsed='true'] .ws-sidebar-foot{
            flex-direction:column;
            gap:10px;
            padding-top:14px;
          }
          .ws-shell[data-ws-collapsed='true'] .ws-account{
            flex:0 0 auto;
          }
          .ws-shell[data-ws-collapsed='true'] .ws-signout{
            width:44px;
            height:44px;
          }
        }
        @media(max-width:359px){
          .ws-bottom-label{font-size:9px}
          .ws-bottom-icon svg{width:20px;height:20px}
        }
        @media(prefers-reduced-motion:reduce){
          .ws-shell,.ws-nav-link,.ws-nav-icon,.ws-bottom-link,.ws-signout,.ws-sidebar-toggle{
            transition:none
          }
          .ws-signout:hover:not(:disabled){transform:none}
        }
        @media(forced-colors:active){
          .ws-sidebar,.ws-bottomnav{border-color:CanvasText}
          .ws-nav-link.active,.ws-bottom-link.active{background:Highlight;color:HighlightText}
          .ws-signout,.ws-sidebar-toggle{border-color:ButtonText}
          .ws-signout:focus-visible,.ws-sidebar-toggle:focus-visible{outline-color:Highlight}
        }
      `}</style>
    </div>
  );
};

export default WsShell;
