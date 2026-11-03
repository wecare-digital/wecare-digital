/**
 * WsShell — authenticated /ws navigation and content surface.
 *
 * Desktop: one full-height sidebar with the official transparent WECARE mark,
 * explicit Home/section navigation, current account and an icon-led Sign out
 * button pinned at the foot. The right side is dedicated to page content:
 * no repeated header or footer.
 *
 * Mobile: six reachable navigation destinations in a safe-area-aware bottom bar,
 * including Home. Sign out remains available in Settings, without introducing
 * a duplicate mobile header or covering page content.
 *
 * The original Cognito signOut/user contract is passed down from WsAuthShell;
 * customer /auth, /workspace and all private business panels remain unchanged.
 */
import React, { ReactNode } from 'react';
import Link from 'next/link';
import BrandMark from '../BrandMark';
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

const WsShell: React.FC<WsShellProps> = ( { children, active, user, signOut } ) => {
  const loginId = user?.signInDetails?.loginId || user?.email || user?.username || '';

  return (
    <div className="ws-shell ws-notion">
      <WsNotionTheme />
      {/* Desktop: all workspace navigation and account actions live here. */}
      <aside className="ws-sidebar" aria-label="Workspace sidebar">
        <Link href="/ws" className="ws-brand ws-brand-side" aria-label="WECARE.DIGITAL workspace home">
          <span className="ws-brand-mark"><BrandMark /></span>
          <span className="ws-brand-copy">
            <span className="ws-brand-name">WECARE.DIGITAL</span>
            <span className="ws-brand-caption">Workspace</span>
          </span>
        </Link>

        <nav className="ws-nav" aria-label="Workspace sections">
          <span className="ws-nav-caption">WORKSPACE</span>
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

        <div className="ws-sidebar-foot">
          <div className="ws-account">
            <span className="ws-account-avatar"><AccountGlyph /></span>
            <span className="ws-account-copy">
              <span className="ws-account-label">Signed in</span>
              <span className="ws-account-id" data-wc-no-translate="true" title={ loginId || undefined }>
                { loginId || 'Workspace account' }
              </span>
            </span>
          </div>
          <button type="button" className="ws-signout" onClick={ () => signOut?.() } disabled={ !signOut }>
            <span className="ws-signout-icon"><SignOutGlyph /></span>
            <span>Sign out</span>
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
          --ws-sidebar-w:260px;
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
        /* Official inline transparent WECARE vector, matching /ws sign-in. */
        .ws-brand{
          display:flex;
          align-items:center;
          gap:12px;
          min-width:0;
          min-height:var(--tap-min,44px);
          text-decoration:none;
          color:var(--accent,#1a3a2a);
          -webkit-tap-highlight-color:transparent;
        }
        .ws-brand-mark{
          display:inline-flex;
          align-items:center;
          justify-content:center;
          width:40px;
          height:40px;
          flex:0 0 40px;
          border-radius:12px;
          background:var(--lime,#d1f470);
          color:var(--public-brand-green,#1a3a2a);
        }
        .ws-brand-copy{display:flex;flex-direction:column;gap:4px;min-width:0}
        .ws-brand-name{
          font-size:14px;
          line-height:1.05;
          font-weight:800;
          letter-spacing:-.035em;
          white-space:nowrap;
          color:var(--accent,#1a3a2a);
        }
        .ws-brand-caption{
          color:var(--text-muted,#6b7280);
          font-size:11px;
          line-height:1.15;
          letter-spacing:.045em;
        }
        .ws-brand:focus-visible{
          outline:2px solid var(--accent,#1a3a2a);
          outline-offset:2px;
          border-radius:12px;
        }

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
          }
          .ws-bottomnav{display:none}
          .ws-main{padding-bottom:0}
          .ws-sidebar{
            position:sticky;
            top:0;
            align-self:start;
            display:flex;
            flex-direction:column;
            height:100vh;
            height:100dvh;
            min-width:0;
            padding:22px 14px
              calc(18px + env(safe-area-inset-bottom,0px))
              max(14px,env(safe-area-inset-left,0px));
            background:var(--bg-secondary,#f7f7f5);
            border-inline-end:1px solid var(--border,#e5e7eb);
            box-sizing:border-box;
          }
          .ws-brand-side{
            padding:4px 10px 22px;
            border-bottom:1px solid var(--border,#e5e7eb);
            margin-bottom:18px;
          }
          .ws-nav{
            display:flex;
            flex-direction:column;
            gap:4px;
            min-height:0;
            flex:1 1 auto;
            overflow-y:auto;
            scrollbar-width:thin;
          }
          .ws-nav-caption{
            padding:0 12px 10px;
            font-size:10px;
            font-weight:700;
            line-height:1.25;
            letter-spacing:.11em;
            color:var(--text-muted,#6b7280);
          }
          .ws-nav-link{
            position:relative;
            display:flex;
            align-items:center;
            gap:12px;
            flex:0 0 auto;
            min-height:46px;
            padding:10px 12px;
            border-radius:11px;
            color:var(--text-muted,#6b7280);
            text-decoration:none;
            font-size:14px;
            font-weight:600;
            transition:background-color .16s ease,color .16s ease;
          }
          .ws-nav-link:hover{
            background:var(--bg-hover,#f0f0ee);
            color:var(--accent,#1a3a2a);
          }
          .ws-nav-link.active{
            background:var(--lime-tint,rgba(209,244,112,.22));
            color:var(--accent,#1a3a2a);
            font-weight:700;
          }
          .ws-nav-link.active::before{
            content:'';
            position:absolute;
            inset-inline-start:0;
            top:11px;
            bottom:11px;
            width:3px;
            border-radius:3px;
            background:var(--lime,#d1f470);
          }
          .ws-nav-icon{
            display:inline-flex;
            align-items:center;
            justify-content:center;
            flex:0 0 22px;
            color:var(--text-muted,#6b7280);
          }
          .ws-nav-link:is(:hover,.active) .ws-nav-icon{color:var(--accent,#1a3a2a)}
          .ws-nav-link:focus-visible{
            outline:2px solid var(--accent,#1a3a2a);
            outline-offset:2px;
          }

          /* Account identity and the real Cognito sign-out action are pinned
             beneath the scrollable nav; neither appears in the content pane. */
          .ws-sidebar-foot{
            display:flex;
            flex-direction:column;
            gap:10px;
            margin-top:14px;
            padding:16px 4px 0;
            border-top:1px solid var(--border,#e5e7eb);
          }
          .ws-account{
            display:flex;
            align-items:center;
            gap:10px;
            min-width:0;
            padding:4px 8px 9px;
          }
          .ws-account-avatar{
            display:inline-flex;
            align-items:center;
            justify-content:center;
            width:36px;
            height:36px;
            flex:0 0 36px;
            color:var(--accent,#1a3a2a);
            background:var(--lime-tint,rgba(209,244,112,.22));
            border-radius:12px;
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
            display:flex;
            align-items:center;
            justify-content:flex-start;
            gap:12px;
            width:100%;
            min-height:var(--tap-min,44px);
            padding:10px 12px;
            border:0;
            border-radius:11px;
            background:transparent;
            color:var(--text-muted,#6b7280);
            font:600 14px/1.35 var(--font-sans,Inter,system-ui,sans-serif);
            text-align:start;
            cursor:pointer;
            transition:background-color .16s ease,color .16s ease;
          }
          .ws-signout-icon{display:inline-flex;align-items:center;justify-content:center;flex:0 0 22px}
          .ws-signout:hover:not(:disabled){
            background:var(--lime-tint,rgba(209,244,112,.22));
            color:var(--accent,#1a3a2a);
          }
          .ws-signout:disabled{opacity:.55;cursor:not-allowed}
          .ws-signout:focus-visible{
            outline:2px solid var(--accent,#1a3a2a);
            outline-offset:2px;
          }
          .ws-content{
            max-width:1250px;
            width:100%;
            margin:0 auto;
            padding:40px clamp(28px,3.5vw,56px) 72px;
          }
        }
        @media(max-width:359px){
          .ws-bottom-label{font-size:9px}
          .ws-bottom-icon svg{width:20px;height:20px}
        }
        @media(prefers-reduced-motion:reduce){
          .ws-nav-link,.ws-bottom-link,.ws-signout{transition:none}
        }
        @media(forced-colors:active){
          .ws-sidebar,.ws-bottomnav{border-color:CanvasText}
          .ws-nav-link.active,.ws-bottom-link.active{background:Highlight;color:HighlightText}
          .ws-signout:focus-visible{outline-color:Highlight}
        }
      `}</style>
    </div>
  );
};

export default WsShell;
