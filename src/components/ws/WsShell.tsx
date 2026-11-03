/**
 * WsShell — the fresh, mobile-first authenticated shell for the /ws workspace.
 *
 * This is a ground-up rebuild, NOT a wrapper around WorkspaceShell. It owns authenticated
 * chrome for the new /ws surface only:
 *   - Desktop (>=768px): a left sidebar carrying the brand mark (links to /ws Home) above the
 *     five nav items, with the signed-in identity and a Sign out control pinned to the foot.
 *   - Mobile (<768px): a compact top bar with the brand mark, and a fixed bottom navigation bar
 *     carrying the same five items. The bottom bar honours --safe-bottom and --tap-min (44px),
 *     and the content reserves bottom padding so the bar never covers it.
 *
 * Auth stays in AuthShell/_app: a /ws page is rendered directly with { signOut, user } and
 * renders this shell itself (see src/pages/_app.tsx — the WorkspaceShell wrap is /workspace-only).
 *
 * All colours/spacing/radii come from src/styles/tokens.css via co-located styled-jsx, the repo
 * convention (see src/components/WorkspaceShell.tsx). Nav icons are inline SVG so the shell does
 * not depend on the small global Material Symbols subset.
 */
import React, { ReactNode, useEffect, useState } from 'react';
import Link from 'next/link';

export type WsSection = 'inbox' | 'collect' | 'customers' | 'commerce' | 'settings';

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

const SignOutGlyph = () => (
  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M15 4h4v16h-4" /><path d="M10 12H3" /><path d="m6 8-4 4 4 4" />
  </svg>
);

const NAV_ITEMS: NavItem[] = [
  { id: 'inbox', label: 'Inbox', href: '/ws/inbox', icon: InboxGlyph },
  { id: 'collect', label: 'Collect', href: '/ws/collect', icon: CollectGlyph },
  { id: 'customers', label: 'Customers', href: '/ws/customers', icon: CustomersGlyph },
  { id: 'commerce', label: 'Commerce', href: '/ws/commerce', icon: CommerceGlyph },
  { id: 'settings', label: 'Settings', href: '/ws/settings', icon: SettingsGlyph },
];

const BrandMark = () => (
  <span className="ws-brand-mark" aria-hidden="true">
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 13.5 5.5 7l3 8L12 5l3.5 10 3-8L21 13.5" />
    </svg>
  </span>
);

const WsShell: React.FC<WsShellProps> = ( { children, active, user, signOut } ) => {
  const [ mounted, setMounted ] = useState( false );
  useEffect( () => { setMounted( true ); }, [] );

  const loginId = user?.signInDetails?.loginId || user?.email || '';

  return (
    <div className="ws-shell">
      {/* Mobile top bar: brand mark -> Home */}
      <header className="ws-topbar">
        <Link href="/ws" className="ws-brand" aria-label="Workspace home">
          <BrandMark />
          <span className="ws-brand-name">WECARE</span>
        </Link>
      </header>

      {/* Desktop sidebar */}
      <aside className="ws-sidebar" aria-label="Workspace">
        <Link href="/ws" className="ws-brand ws-brand-side" aria-label="Workspace home">
          <BrandMark />
          <span className="ws-brand-name">WECARE</span>
        </Link>

        <nav className="ws-nav" aria-label="Primary">
          { NAV_ITEMS.map( item => {
            const Icon = item.icon;
            const isActive = item.id === active;
            return (
              <Link
                key={ item.id }
                href={ item.href }
                className={ `ws-nav-link ${isActive ? 'active' : ''}` }
                aria-current={ isActive ? 'page' : undefined }
              >
                <span className="ws-nav-icon"><Icon /></span>
                <span className="ws-nav-label">{ item.label }</span>
              </Link>
            );
          } ) }
        </nav>

        <div className="ws-foot">
          <div className="ws-identity" data-wc-no-translate="true">
            <span className="ws-identity-label">Signed in</span>
            { loginId
              ? <span className="ws-identity-id">{ loginId }</span>
              : <span className="ws-identity-id ws-identity-muted">{ mounted ? 'Account' : '\u00a0' }</span> }
          </div>
          <button type="button" className="ws-signout" onClick={ () => signOut?.() }>
            <SignOutGlyph /><span>Sign out</span>
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main id="ws-main" className="ws-main" data-wc-no-translate="true">
        <div className="ws-content">{ children }</div>
      </main>

      {/* Mobile bottom navigation */}
      <nav className="ws-bottomnav" aria-label="Primary">
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
          --ws-sidebar-w:248px;
          --ws-topbar-h:56px;
          --ws-bottomnav-h:60px;
          min-height:100vh;
          min-height:100dvh;
          min-width:0;
          background:var(--bg,#fff);
          color:var(--text,#1a1a1a);
          font-family:var(--font-sans,Inter,system-ui,sans-serif);
          overflow-x:hidden;
          overflow-x:clip;
        }

        /* ---- Brand mark (shared) ---- */
        .ws-brand{
          display:inline-flex;
          align-items:center;
          gap:10px;
          text-decoration:none;
          color:var(--accent,#1a3a2a);
          min-height:var(--tap-min,44px);
          -webkit-tap-highlight-color:transparent;
        }
        .ws-brand-mark{
          display:inline-flex;
          align-items:center;
          justify-content:center;
          width:34px;
          height:34px;
          border-radius:var(--radius-lg,12px);
          background:var(--lime,#d1f470);
          color:var(--accent,#1a3a2a);
          flex:0 0 auto;
        }
        .ws-brand-name{
          font-weight:700;
          font-size:16px;
          letter-spacing:-0.3px;
          color:var(--accent,#1a3a2a);
        }

        /* ---- Mobile top bar (hidden on desktop) ---- */
        .ws-topbar{
          position:sticky;
          top:0;
          z-index:1100;
          display:flex;
          align-items:center;
          height:calc(var(--ws-topbar-h) + env(safe-area-inset-top,0px));
          padding:0 16px;
          padding-top:env(safe-area-inset-top,0px);
          padding-inline-start:max(16px,env(safe-area-inset-left,0px));
          padding-inline-end:max(16px,env(safe-area-inset-right,0px));
          background:var(--surface,#fff);
          border-bottom:1px solid var(--border,#e5e7eb);
          box-sizing:border-box;
        }

        /* ---- Desktop sidebar (hidden on mobile) ---- */
        .ws-sidebar{ display:none; }

        /* ---- Main content ---- */
        .ws-main{
          min-width:0;
          box-sizing:border-box;
          overflow-x:hidden;
          overflow-x:clip;
        }
        .ws-content{
          width:100%;
          min-width:0;
          box-sizing:border-box;
          /* leave room for the fixed bottom nav + safe area so it never covers content */
          padding:16px
            max(16px,env(safe-area-inset-right,0px))
            calc(var(--ws-bottomnav-h) + 16px + env(safe-area-inset-bottom,0px))
            max(16px,env(safe-area-inset-left,0px));
        }

        /* ---- Mobile bottom navigation ---- */
        .ws-bottomnav{
          position:fixed;
          z-index:1100;
          left:0;
          right:0;
          bottom:0;
          display:flex;
          align-items:stretch;
          height:calc(var(--ws-bottomnav-h) + env(safe-area-inset-bottom,0px));
          padding-bottom:env(safe-area-inset-bottom,0px);
          padding-inline:max(0px,env(safe-area-inset-left,0px)) max(0px,env(safe-area-inset-right,0px));
          background:var(--surface,#fff);
          border-top:1px solid var(--border,#e5e7eb);
          box-sizing:border-box;
        }
        .ws-bottom-link{
          flex:1 1 0;
          display:flex;
          flex-direction:column;
          align-items:center;
          justify-content:center;
          gap:3px;
          min-width:0;
          min-height:var(--tap-min,44px);
          padding:6px 2px;
          text-decoration:none;
          color:var(--text-muted,#6b7280);
          -webkit-tap-highlight-color:transparent;
        }
        .ws-bottom-link.active{ color:var(--accent,#1a3a2a); }
        .ws-bottom-icon{ display:inline-flex; }
        .ws-bottom-label{
          font-size:11px;
          font-weight:600;
          line-height:1;
          max-width:100%;
          overflow:hidden;
          text-overflow:ellipsis;
          white-space:nowrap;
        }
        .ws-bottom-link.active .ws-bottom-icon{
          color:var(--accent,#1a3a2a);
        }
        .ws-bottom-link:focus-visible{
          outline:2px solid var(--accent,#1a3a2a);
          outline-offset:-2px;
          border-radius:var(--radius-md,8px);
        }

        /* ======================================================================
         * DESKTOP (>=768px): left sidebar replaces the top bar + bottom nav.
         * ====================================================================== */
        @media (min-width:768px){
          .ws-shell{
            display:grid;
            grid-template-columns:var(--ws-sidebar-w) minmax(0,1fr);
          }
          .ws-topbar{ display:none; }
          .ws-bottomnav{ display:none; }

          .ws-sidebar{
            position:sticky;
            top:0;
            align-self:start;
            display:flex;
            flex-direction:column;
            height:100vh;
            height:100dvh;
            padding:20px 14px
              calc(16px + env(safe-area-inset-bottom,0px))
              max(14px,env(safe-area-inset-left,0px));
            background:var(--surface,#fff);
            border-right:1px solid var(--border,#e5e7eb);
            box-sizing:border-box;
          }
          .ws-brand-side{ padding:4px 8px 20px; }

          .ws-nav{
            display:flex;
            flex-direction:column;
            gap:4px;
            flex:1 1 auto;
            min-height:0;
            overflow-y:auto;
          }
          .ws-nav-link{
            display:flex;
            align-items:center;
            gap:12px;
            min-height:var(--tap-min,44px);
            padding:10px 12px;
            border-radius:var(--radius-lg,12px);
            text-decoration:none;
            color:var(--text,#1a1a1a);
            font-size:15px;
            font-weight:600;
          }
          .ws-nav-link:hover{ background:var(--bg-hover,#f5f5f5); }
          .ws-nav-link.active{
            background:var(--accent,#1a3a2a);
            color:#fff;
          }
          .ws-nav-link.active .ws-nav-icon{ color:var(--lime,#d1f470); }
          .ws-nav-icon{ display:inline-flex; flex:0 0 auto; }
          .ws-nav-link:focus-visible{
            outline:2px solid var(--accent,#1a3a2a);
            outline-offset:2px;
          }

          .ws-foot{
            flex:0 0 auto;
            padding-top:12px;
            border-top:1px solid var(--border,#e5e7eb);
          }
          .ws-identity{
            display:flex;
            flex-direction:column;
            gap:2px;
            padding:4px 8px 10px;
            min-width:0;
          }
          .ws-identity-label{
            font-size:11px;
            font-weight:600;
            text-transform:uppercase;
            letter-spacing:0.4px;
            color:var(--text-muted,#6b7280);
          }
          .ws-identity-id{
            font-size:13px;
            color:var(--text,#1a1a1a);
            overflow-wrap:anywhere;
          }
          .ws-identity-muted{ color:var(--text-muted,#6b7280); }
          .ws-signout{
            display:inline-flex;
            align-items:center;
            justify-content:center;
            gap:8px;
            width:100%;
            min-height:var(--tap-min,44px);
            padding:10px 12px;
            border:1px solid var(--border,#e5e7eb);
            border-radius:var(--radius-lg,12px);
            background:var(--surface,#fff);
            color:var(--text,#1a1a1a);
            font-size:14px;
            font-weight:700;
            cursor:pointer;
          }
          .ws-signout:hover{
            border-color:var(--danger,#dc2626);
            color:var(--danger,#dc2626);
          }
          .ws-signout:focus-visible{
            outline:2px solid var(--accent,#1a3a2a);
            outline-offset:2px;
          }

          .ws-content{
            max-width:1100px;
            margin:0 auto;
            padding:28px 28px 48px;
          }
        }

        @media (prefers-reduced-motion:reduce){
          .ws-nav-link,.ws-bottom-link,.ws-signout{ transition:none; }
        }
        @media (forced-colors:active){
          .ws-sidebar,.ws-topbar,.ws-bottomnav{ border-color:CanvasText; }
          .ws-nav-link.active{ background:Highlight; color:HighlightText; }
        }
      `}</style>
    </div>
  );
};

export default WsShell;
