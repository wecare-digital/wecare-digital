/**
 * Workspace hub — the parent namespace index.
 *
 * WHY THIS FILE EXISTS
 * --------------------
 * On 2026-09-26 the 14 authenticated route families were nested under
 * `/workspace/`, and every child served correctly, but `/workspace/` itself
 * returned 404: this is a static export, so a directory with no `index.tsx`
 * produces no page. The parent of the namespace was the one path in it that did
 * not resolve.
 *
 * It matters more than a missing landing page usually would, because `[retired public path]/`
 * and `[retired public path]/` both 301 *into* `/workspace/engage/`. A user who trimmed the URL
 * back to `/workspace/` — the obvious way to look for the parent — hit a dead
 * end inside a namespace whose whole point is to be the parent.
 *
 * ON THE REDIRECT ORDERING
 * ------------------------
 * The earlier `/workspace`, `/workspace/` and `/workspace/<*>` -> `[retired public path]/*`
 * rules are GONE, deliberately. A wildcard cannot point inside its own source
 * prefix without swallowing every route beneath it, so while those rules existed
 * they sat in front of all 14 families and bounced each one straight back out.
 * The surviving `workspace`-sourced rules are intra-namespace canonicalisations
 * only (e.g. `/workspace/engage/calls` -> `/workspace/engage/inbox/?channel=voice`),
 * and the traffic now flows inward: `[retired public path]/<*>` and `[retired public path]/<*>` -> `/workspace/engage/<*>`.
 * Verified live before this page was added: all 13 indexed families 200.
 *
 * `settings` is the one family with no `index.tsx` — it holds a single page — so
 * it links straight to that page rather than to a directory that would 404.
 * Linking a hub tile to a known-404 is worse than omitting the tile.
 */

import React from 'react';
import { useRouter } from 'next/router';
import Layout from '../../components/Layout';
import SEO from '../../components/SEO';
import {
  MessageIcon, ContactsIcon, StoreIcon, PaymentIcon, LinkIcon,
  FormIcon, DocumentIcon, CheckListIcon, SearchIcon, AdvisorIcon,
  OverviewIcon, SettingsIcon,
} from '../../lib/icons';

interface PageProps { signOut?: () => void; user?: any; }

interface Family {
  id: string;
  label: string;
  desc: string;
  path: string;
  Icon: React.FC<{ size?: number; color?: string }>;
  color: string;
}

/**
 * Every tile's `path` was confirmed to return 200 live on 2026-09-27. Keep it
 * that way: a hub whose links 404 is worse than no hub, because it looks
 * authoritative.
 *
 * NO TILE POINTS AT A REDIRECT STUB (2026-10-15). Five tiles used to: forms/, docs/,
 * service/ and admin/ are router.replace signposts kept only so old bookmarks land
 * somewhere, and access/ is the sign-in landing, which sends a signed-in user straight
 * to the workspace landing. A 200 from a signpost is not a destination, so each tile now
 * names the page its signpost delivers, and says what that page is:
 *   forms/   -> forms/responses              (label kept: it is the forms queue)
 *   docs/    -> engage/documents             ("Drop Docs" — the old "Provider
 *               documentation and changelog" text described the Docs Scraper, which
 *               this tile never reached; that is engage/docs, in the gear)
 *   service/ -> engage/service-ops           (label kept)
 *   admin/   -> settings/platform/system-architecture ("Architecture snapshot", the
 *               gear's label for the same page — it is a document, not an admin console)
 * The Dashboard tile and the Access tile are both GONE: the Dashboard section was
 * removed and the workspace landing is now /workspace/engage/inbox, and the Access
 * signpost lands there too, while nothing in the app is "Users, roles and permissions".
 * Sign-in & MFA is in the gear's account group. Navigation.test.tsx asserts each path
 * below is a real page and none is a signpost.
 */
const families: Family[] = [
  { id: 'engage', label: 'Messages', desc: 'WhatsApp, SMS, Voice, Email, RCS and Push', path: '/workspace/engage/', Icon: MessageIcon, color: '#25D366' },
  { id: 'contacts', label: 'Contacts', desc: 'Contact records, segments and history', path: '/workspace/contacts/', Icon: ContactsIcon, color: '#8B5CF6' },
  { id: 'commerce', label: 'Commerce', desc: 'Catalogue, orders and store integration', path: '/workspace/commerce/', Icon: StoreIcon, color: '#F59E0B' },
  { id: 'pay', label: 'Payments', desc: 'Invoices, collections and reconciliation', path: '/workspace/pay/', Icon: PaymentIcon, color: '#10B981' },
  { id: 'link', label: 'Links', desc: 'Short links and click analytics', path: '/workspace/link/', Icon: LinkIcon, color: '#6366F1' },
  // FEAT-005: Form responses and Drop Docs are tabs on the Service hub now; the tiles deep-link
  // the hub with a ?tab= id (the standalone forms/responses and engage/documents routes were
  // relocated out of the pages tree).
  { id: 'forms', label: 'Forms', desc: 'Customer service forms and submissions', path: '/workspace/engage/service-ops?tab=form-responses', Icon: FormIcon, color: '#EC4899' },
  { id: 'docs', label: 'Drop Docs', desc: 'Documents customers send in, for review and approval', path: '/workspace/engage/service-ops?tab=documents', Icon: DocumentIcon, color: '#0EA5E9' },
  { id: 'task', label: 'Tasks', desc: 'Work items, assignments and follow-ups', path: '/workspace/task/', Icon: CheckListIcon, color: '#14B8A6' },
  { id: 'seo', label: 'SEO', desc: 'Sitemaps, metadata and search tooling', path: '/workspace/seo/', Icon: SearchIcon, color: '#A855F7' },
  { id: 'service', label: 'Service', desc: 'Customer requests and service desk', path: '/workspace/engage/service-ops/', Icon: AdvisorIcon, color: '#EF4444' },
  { id: 'admin', label: 'Architecture snapshot', desc: 'Hand-maintained map of routes, functions, storage and risks', path: '/workspace/settings/platform?tab=system-architecture', Icon: OverviewIcon, color: '#64748B' },
  // No index.tsx under settings/ — link the page that exists, not the directory.
  { id: 'settings', label: 'Settings', desc: 'Internal agent and system configuration', path: '/workspace/settings/internal-agent/', Icon: SettingsIcon, color: '#6B7280' },
];

const WorkspacePage: React.FC<PageProps> = ({ signOut, user }) => {
  const router = useRouter();

  return (
    <Layout user={user} onSignOut={signOut}>
      <SEO
        title="Workspace"
        description="Workspace hub — dashboard, messaging, contacts, commerce, payments and administration"
      />
      <div className="inner-page-container" style={{ maxWidth: 960 }}>
        <div style={{ marginBottom: 24 }}>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: 'var(--text)', margin: '0 0 4px' }}>Workspace</h1>
          <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: 0 }}>
            Everything in one place. Pick an area to get started.
          </p>
        </div>

        <div
          style={{ fontSize: 12, fontWeight: 600, color: 'var(--accent)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 10 }}
        >
          Areas
        </div>

        <nav aria-label="Workspace areas">
          <ul className="ws-grid">
            {families.map((f) => (
              <li key={f.id} className="ws-item">
                <button
                  type="button"
                  onClick={() => router.push(f.path)}
                  className="ws-btn"
                  aria-label={`${f.label} — ${f.desc}`}
                >
                  <span className="ws-icon" style={{ background: f.color + '15' }}>
                    <f.Icon size={18} color={f.color} />
                  </span>
                  <span className="ws-text">
                    <span className="ws-label">{f.label}</span>
                    <span className="ws-desc">{f.desc}</span>
                  </span>
                  <svg
                    className="ws-chev"
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="#9ca3af"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden="true"
                    focusable="false"
                  >
                    <polyline points="9 18 15 12 9 6" />
                  </svg>
                </button>
              </li>
            ))}
          </ul>
        </nav>
      </div>

      <style jsx>{`
        .ws-grid {
          display: grid;
          grid-template-columns: repeat(2, 1fr);
          gap: 10px;
          margin: 0 0 28px;
          padding: 0;
          list-style: none;
        }
        .ws-item { display: block; }
        .ws-btn {
          display: flex;
          align-items: center;
          gap: 14px;
          width: 100%;
          padding: 14px 16px;
          background: var(--surface);
          border: 1.5px solid var(--border);
          border-radius: 13px;
          cursor: pointer;
          transition: all 0.15s;
          text-align: left;
          font-family: var(--font-sans);
          -webkit-tap-highlight-color: transparent;
        }
        .ws-btn:hover,
        .ws-btn:active {
          border-color: var(--lime);
          background: rgba(209, 244, 112, 0.04);
        }
        /* Keyboard users get the same affordance as a pointer hover, plus a ring. */
        .ws-btn:focus-visible {
          outline: 2px solid var(--accent);
          outline-offset: 2px;
          border-color: var(--lime);
        }
        .ws-icon {
          width: 40px;
          height: 40px;
          border-radius: 10px;
          display: flex;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
        }
        .ws-text { display: block; flex: 1; min-width: 0; }
        .ws-label { display: block; font-size: var(--text-md); font-weight: 600; color: var(--text); }
        .ws-desc { display: block; font-size: var(--text-xs); color: var(--text-muted); margin-top: 1px; }
        .ws-chev { flex-shrink: 0; }

        @media (max-width: 768px) {
          .ws-grid { grid-template-columns: 1fr; gap: 8px; }
          .ws-btn { padding: 16px; min-height: 60px; }
          .ws-label { font-size: var(--text-base); }
          .ws-desc { font-size: var(--text-sm); }
          .ws-icon { width: 44px; height: 44px; }
        }
        @media (max-width: 480px) {
          .ws-btn { padding: 14px 12px; }
        }
        @media (prefers-reduced-motion: reduce) {
          .ws-btn { transition: none; }
        }
      `}</style>
    </Layout>
  );
};

export default WorkspacePage;
