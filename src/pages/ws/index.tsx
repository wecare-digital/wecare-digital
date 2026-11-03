/**
 * /ws — Workspace Home (launchpad).
 *
 * The brand mark in WsShell links here. This is a real mobile-first launchpad: large tappable
 * cards to each of the five sections. Auth is automatic (see src/pages/_app.tsx): this page is
 * rendered through AuthShell and receives { signOut, user }. It is NOT public — SEO is noindex.
 *
 * NOTE: Home has no single matching bottom-nav item, so WsShell's `active` is given 'inbox' only
 * to satisfy the type; no nav item is highlighted in a way that misrepresents the current page on
 * mobile because the brand mark (not a nav item) is what points here.
 */
import React from 'react';
import Link from 'next/link';
import SEO from '../../components/SEO';
import WsShell from '../../components/ws/WsShell';

interface PageProps { signOut?: () => void; user?: any; }

interface Launch {
  href: string;
  title: string;
  blurb: string;
  icon: () => React.JSX.Element;
}

const InboxIcon = () => (
  <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M4 4h16v16H4z" /><path d="M4 14h4l2 3h4l2-3h4" />
  </svg>
);
const CollectIcon = () => (
  <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M6 3h9l3 3v15H6z" /><path d="M9 8h6M9 12h6M9 16h4" />
  </svg>
);
const CustomersIcon = () => (
  <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="9" cy="8" r="3.4" /><path d="M3.5 20c.7-3.6 2.9-5.4 5.5-5.4s4.8 1.8 5.5 5.4" /><path d="M16 5.2a3 3 0 0 1 0 5.6M18 14.6c2 .6 3.4 2.2 3.9 4.9" />
  </svg>
);
const CommerceIcon = () => (
  <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M4 7h16l-1.2 10.5a2 2 0 0 1-2 1.5H7.2a2 2 0 0 1-2-1.5z" /><path d="M9 7a3 3 0 0 1 6 0" />
  </svg>
);
const SettingsIcon = () => (
  <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="12" cy="12" r="3" /><path d="M12 2.5v2.2M12 19.3v2.2M4.2 7l1.9 1.1M17.9 15.9l1.9 1.1M4.2 17l1.9-1.1M17.9 8.1l1.9-1.1" />
  </svg>
);

const LAUNCH: Launch[] = [
  { href: '/ws/inbox', title: 'Inbox', blurb: 'Conversations across every channel.', icon: InboxIcon },
  { href: '/ws/collect', title: 'Collect', blurb: 'Custom invoices, receipts and the private Vault.', icon: CollectIcon },
  { href: '/ws/customers', title: 'Customers', blurb: 'Your people, their history and records.', icon: CustomersIcon },
  { href: '/ws/commerce', title: 'Commerce', blurb: 'Orders and your product catalog.', icon: CommerceIcon },
  { href: '/ws/settings', title: 'Settings', blurb: 'Your identity and account controls.', icon: SettingsIcon },
];

const WsHome: React.FC<PageProps> = ( { signOut, user } ) => {
  const loginId = user?.signInDetails?.loginId || user?.email || '';

  return (
    <>
      <SEO title="Workspace" description="WECARE workspace home." noindex />
      <WsShell active="inbox" user={ user } signOut={ signOut }>
        <section className="ws-home">
          <header className="ws-home-head">
            <p className="ws-home-eyebrow">Workspace</p>
            <h1 className="ws-home-title">Welcome back</h1>
            { loginId
              ? <p className="ws-home-sub" data-wc-no-translate="true">{ loginId }</p>
              : <p className="ws-home-sub">Pick a section to get started.</p> }
          </header>

          <div className="ws-home-grid">
            { LAUNCH.map( item => {
              const Icon = item.icon;
              return (
                <Link key={ item.href } href={ item.href } className="ws-home-card">
                  <span className="ws-home-card-icon"><Icon /></span>
                  <span className="ws-home-card-text">
                    <span className="ws-home-card-title">{ item.title }</span>
                    <span className="ws-home-card-blurb">{ item.blurb }</span>
                  </span>
                  <span className="ws-home-card-chev" aria-hidden="true">
                    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="m9 6 6 6-6 6" />
                    </svg>
                  </span>
                </Link>
              );
            } ) }
          </div>
        </section>

        <style jsx>{`
          .ws-home{ width:100%; min-width:0; }
          .ws-home-head{ margin-bottom:20px; }
          .ws-home-eyebrow{
            margin:0 0 4px;
            font-size:12px;
            font-weight:700;
            text-transform:uppercase;
            letter-spacing:0.6px;
            color:var(--text-muted,#6b7280);
          }
          .ws-home-title{
            margin:0;
            font-size:26px;
            font-weight:700;
            letter-spacing:-0.5px;
            color:var(--text,#1a1a1a);
          }
          .ws-home-sub{
            margin:6px 0 0;
            font-size:15px;
            color:var(--text-muted,#6b7280);
            overflow-wrap:anywhere;
          }
          .ws-home-grid{
            display:grid;
            grid-template-columns:1fr;
            gap:12px;
          }
          .ws-home-card{
            display:flex;
            align-items:center;
            gap:14px;
            min-height:var(--tap-min,44px);
            padding:16px;
            border:1px solid var(--border,#e5e7eb);
            border-radius:var(--radius-xl,14px);
            background:var(--surface,#fff);
            text-decoration:none;
            color:var(--text,#1a1a1a);
            -webkit-tap-highlight-color:transparent;
            transition:border-color var(--transition-normal,0.15s ease), box-shadow var(--transition-normal,0.15s ease);
          }
          .ws-home-card:hover{
            border-color:var(--accent,#1a3a2a);
            box-shadow:var(--shadow-md,0 2px 8px rgba(0,0,0,0.06));
          }
          .ws-home-card:focus-visible{
            outline:2px solid var(--accent,#1a3a2a);
            outline-offset:2px;
          }
          .ws-home-card-icon{
            display:inline-flex;
            align-items:center;
            justify-content:center;
            width:44px;
            height:44px;
            flex:0 0 auto;
            border-radius:var(--radius-lg,12px);
            background:var(--lime,#d1f470);
            color:var(--accent,#1a3a2a);
          }
          .ws-home-card-text{
            display:flex;
            flex-direction:column;
            gap:3px;
            min-width:0;
            flex:1 1 auto;
          }
          .ws-home-card-title{
            font-size:16px;
            font-weight:700;
            color:var(--text,#1a1a1a);
          }
          .ws-home-card-blurb{
            font-size:13px;
            color:var(--text-muted,#6b7280);
          }
          .ws-home-card-chev{
            display:inline-flex;
            flex:0 0 auto;
            color:var(--text-muted,#6b7280);
          }

          @media (min-width:768px){
            .ws-home-title{ font-size:30px; }
            .ws-home-grid{ grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; }
          }
        `}</style>
      </WsShell>
    </>
  );
};

export default WsHome;
