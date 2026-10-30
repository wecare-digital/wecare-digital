/**
 * Workspace Home — the operator launchpad.
 *
 * Home is the visual reference for rhythm, hierarchy and restraint, not a template to copy.
 * This page keeps the denser authenticated shell while borrowing the same clear type ladder,
 * generous section spacing and lime interaction accent.
 *
 * Counts are intentionally absent until a server aggregate is authoritative. Attention cards
 * are real queue destinations, never browser-derived vanity numbers.
 */
import React from 'react';
import Link from 'next/link';
import Layout from '../../components/Layout';
import SEO from '../../components/SEO';

interface PageProps { signOut?: () => void; user?: any; }

const attention = [
  { label: 'Conversations', detail: 'Unread and customer conversations', href: '/workspace/communications?view=inbox' },
  { label: 'Payments', detail: 'Pending, failed and reconciled payment records', href: '/workspace/payments?view=ledger&ledger=activity' },
  { label: 'Orders', detail: 'Store and staff-created commerce orders', href: '/workspace/commerce' },
  { label: 'Delivery issues', detail: 'Message delivery history and failures', href: '/workspace/communications?view=manage&section=delivery' },
  { label: 'Tasks', detail: 'Assigned work and follow-ups', href: '/workspace/task' },
];

const start = [
  { label: 'Message', detail: 'Open the unified inbox', href: '/workspace/communications?view=inbox' },
  { label: 'Customer', detail: 'Find or create a customer record', href: '/workspace/customers' },
  { label: 'Order', detail: 'Work with catalog and orders', href: '/workspace/commerce' },
  { label: 'Collect payment', detail: 'Create an authoritative payment request', href: '/workspace/payments?view=collect' },
];

const workspaces = [
  { label: 'Customers', detail: 'Identity, address, consent and customer history', href: '/workspace/customers' },
  { label: 'Communications', detail: 'Inbox and communications management', href: '/workspace/communications' },
  { label: 'Commerce', detail: 'Orders and catalog', href: '/workspace/commerce' },
  { label: 'Payments', detail: 'Collect and ledger', href: '/workspace/payments' },
  { label: 'Vault', detail: 'Manual secure-file delivery and access', href: '/workspace/service' },
  { label: 'Platform', detail: 'Infrastructure, integrations and diagnostics', href: '/workspace/platform' },
];

const Arrow = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M5 12h14M14 7l5 5-5 5"/>
  </svg>
);

const WorkspacePage: React.FC<PageProps> = ( { signOut, user } ) => (
  <Layout user={ user } onSignOut={ signOut } showBreadcrumbs={ false }>
    <SEO title="Workspace" description="WECARE.DIGITAL operational workspace." noindex />

    <div className="workspace-home">
      <header className="workspace-hero">
        <p className="workspace-kicker">Operations</p>
        <h1>Workspace</h1>
        <p className="workspace-subtitle">Start work, find what needs attention, or open an operating area.</p>
      </header>

      <section className="workspace-section" aria-labelledby="attention-title">
        <div className="workspace-section-head">
          <div>
            <p className="section-kicker">Today</p>
            <h2 id="attention-title">Needs attention</h2>
          </div>
          <p>Open the queue that needs review. Counts appear only when they come from an authoritative aggregate.</p>
        </div>

        <div className="attention-grid">
          { attention.map( ( item ) => (
            <Link key={ item.href } href={ item.href } className="attention-card">
              <span className="attention-dot" aria-hidden="true" />
              <span className="card-copy">
                <strong>{ item.label }</strong>
                <small>{ item.detail }</small>
              </span>
              <span className="card-arrow" aria-hidden="true"><Arrow /></span>
            </Link>
          ) ) }
        </div>
      </section>

      <section className="workspace-section" aria-labelledby="start-title">
        <div className="workspace-section-head compact">
          <div>
            <p className="section-kicker">Quick start</p>
            <h2 id="start-title">Start</h2>
          </div>
          <p>Jump directly into the work you do most often.</p>
        </div>

        <div className="start-grid">
          { start.map( ( item ) => (
            <Link key={ item.label } href={ item.href } className="start-card">
              <span className="card-copy">
                <strong>{ item.label }</strong>
                <small>{ item.detail }</small>
              </span>
              <span className="card-arrow" aria-hidden="true"><Arrow /></span>
            </Link>
          ) ) }
        </div>
      </section>

      <section className="workspace-section" aria-labelledby="work-title">
        <div className="workspace-section-head compact">
          <div>
            <p className="section-kicker">Operating areas</p>
            <h2 id="work-title">Work</h2>
          </div>
          <p>Open a full operating area when the task needs more context.</p>
        </div>

        <div className="work-grid">
          { workspaces.map( ( item ) => (
            <Link key={ item.label } href={ item.href } className="work-card">
              <span className="work-card-top">
                <strong>{ item.label }</strong>
                <span className="card-arrow" aria-hidden="true"><Arrow /></span>
              </span>
              <small>{ item.detail }</small>
            </Link>
          ) ) }
        </div>
      </section>
    </div>

    {/*
      Global on purpose. Next/Link is a child component, so scoped styled-jsx selectors do
      not reliably reach the generated <a>. That was the production defect visible in the
      2026-10-20 screenshot: headings were styled while every Link card collapsed to inline
      text. Prefix every rule with .workspace-home so the global reach cannot leak elsewhere.
    */}
    <style jsx global>{`
      .workspace-home{
        width:min(100%,1240px);
        margin:0 auto;
        padding:56px 48px 80px;
        box-sizing:border-box;
        color:var(--text);
      }

      .workspace-home .workspace-hero{
        max-width:820px;
        margin:0 0 72px;
      }

      .workspace-home .workspace-kicker,
      .workspace-home .section-kicker{
        margin:0 0 8px;
        color:var(--accent);
        font-size:var(--text-xs);
        font-weight:800;
        letter-spacing:.09em;
        line-height:1.2;
        text-transform:uppercase;
      }

      .workspace-home h1{
        margin:0;
        color:var(--text);
        font-size:clamp(48px,5.2vw,68px);
        font-weight:800;
        line-height:.98;
        letter-spacing:-.048em;
      }

      .workspace-home .workspace-subtitle{
        max-width:700px;
        margin:18px 0 0;
        color:var(--text-muted);
        font-size:clamp(18px,1.7vw,21px);
        line-height:1.55;
      }

      .workspace-home .workspace-section{
        margin-top:72px;
      }

      .workspace-home .workspace-section-head{
        display:grid;
        grid-template-columns:minmax(0,1fr) minmax(280px,520px);
        align-items:end;
        gap:28px;
        margin-bottom:22px;
      }

      .workspace-home .workspace-section-head.compact{
        align-items:end;
      }

      .workspace-home .workspace-section-head h2{
        margin:0;
        color:var(--text);
        font-size:clamp(28px,3vw,36px);
        font-weight:760;
        line-height:1.08;
        letter-spacing:-.035em;
      }

      .workspace-home .workspace-section-head>p{
        margin:0;
        color:var(--text-muted);
        font-size:var(--text-sm);
        line-height:1.55;
      }

      .workspace-home .attention-grid{
        display:grid;
        grid-template-columns:repeat(2,minmax(0,1fr));
        gap:12px;
      }

      .workspace-home .attention-card,
      .workspace-home .start-card,
      .workspace-home .work-card{
        color:var(--text);
        text-decoration:none;
        background:#fff;
        border:1px solid var(--border);
        border-radius:18px;
        transition:border-color .16s ease,background-color .16s ease,transform .16s ease;
      }

      .workspace-home .attention-card{
        min-height:82px;
        padding:14px 16px;
        display:grid;
        grid-template-columns:12px minmax(0,1fr) 40px;
        align-items:center;
        gap:12px;
      }

      .workspace-home .attention-dot{
        width:10px;
        height:10px;
        border-radius:50%;
        background:var(--lime);
        box-shadow:0 0 0 1px var(--accent);
      }

      .workspace-home .card-copy{
        display:flex;
        flex-direction:column;
        min-width:0;
        gap:5px;
      }

      .workspace-home .card-copy strong,
      .workspace-home .work-card strong{
        color:var(--text);
        font-size:var(--text-lg);
        font-weight:720;
        line-height:1.2;
      }

      .workspace-home .card-copy small,
      .workspace-home .work-card>small{
        color:var(--text-muted);
        font-size:var(--text-sm);
        line-height:1.45;
      }

      .workspace-home .card-arrow{
        width:40px;
        height:40px;
        display:inline-flex;
        align-items:center;
        justify-content:center;
        flex:0 0 40px;
        border-radius:50%;
        color:var(--accent);
        background:var(--lime-tint);
        transition:background-color .16s ease,transform .16s ease;
      }

      .workspace-home .start-grid{
        display:grid;
        grid-template-columns:repeat(4,minmax(0,1fr));
        gap:12px;
      }

      .workspace-home .start-card{
        min-height:154px;
        padding:20px;
        display:flex;
        flex-direction:column;
        justify-content:space-between;
        align-items:flex-start;
        gap:22px;
      }

      .workspace-home .start-card .card-arrow{
        align-self:flex-end;
      }

      .workspace-home .work-grid{
        display:grid;
        grid-template-columns:repeat(3,minmax(0,1fr));
        gap:12px;
      }

      .workspace-home .work-card{
        min-height:150px;
        padding:20px;
        display:flex;
        flex-direction:column;
        gap:18px;
      }

      .workspace-home .work-card-top{
        display:flex;
        align-items:center;
        justify-content:space-between;
        gap:16px;
      }

      .workspace-home .work-card>small{
        max-width:31ch;
      }

      .workspace-home .attention-card:hover,
      .workspace-home .start-card:hover,
      .workspace-home .work-card:hover{
        border-color:var(--lime);
        background:var(--lime-tint);
        transform:translateY(-2px);
      }

      .workspace-home .attention-card:hover .card-arrow,
      .workspace-home .start-card:hover .card-arrow,
      .workspace-home .work-card:hover .card-arrow{
        background:var(--lime);
        transform:translateX(2px);
      }

      .workspace-home .attention-card:focus-visible,
      .workspace-home .start-card:focus-visible,
      .workspace-home .work-card:focus-visible{
        outline:3px solid var(--accent);
        outline-offset:3px;
      }

      @media(max-width:960px){
        .workspace-home{
          padding-inline:32px;
        }
        .workspace-home .workspace-section-head{
          grid-template-columns:1fr;
          gap:10px;
        }
        .workspace-home .workspace-section-head>p{
          max-width:680px;
        }
        .workspace-home .start-grid{
          grid-template-columns:repeat(2,minmax(0,1fr));
        }
        .workspace-home .work-grid{
          grid-template-columns:repeat(2,minmax(0,1fr));
        }
      }

      @media(max-width:640px){
        .workspace-home{
          padding:var(--public-mobile-hero-top) var(--public-mobile-page-gutter) 48px;
        }
        .workspace-home .workspace-hero{
          margin-bottom:var(--public-mobile-section-gap);
        }
        .workspace-home h1{
          font-size:var(--public-mobile-hero-size);
          line-height:1.02;
        }
        .workspace-home .workspace-subtitle{
          margin-top:16px;
          font-size:var(--public-body-size);
          line-height:1.5;
        }
        .workspace-home .workspace-section{
          margin-top:var(--public-mobile-section-gap);
        }
        .workspace-home .workspace-section-head{
          margin-bottom:18px;
        }
        .workspace-home .workspace-section-head h2{
          font-size:var(--public-mobile-section-size);
        }
        .workspace-home .workspace-section-head>p{
          font-size:var(--text-base);
        }
        .workspace-home .attention-grid,
        .workspace-home .start-grid,
        .workspace-home .work-grid{
          grid-template-columns:1fr;
        }
        .workspace-home .attention-card{
          min-height:88px;
          padding:14px;
        }
        .workspace-home .start-card,
        .workspace-home .work-card{
          min-height:124px;
          padding:18px;
        }
        .workspace-home .card-copy strong,
        .workspace-home .work-card strong{
          font-size:var(--public-mobile-card-size);
        }
        .workspace-home .card-copy small,
        .workspace-home .work-card>small{
          font-size:var(--text-base);
        }
      }

      @media(max-width:340px){
        .workspace-home .attention-card{
          grid-template-columns:10px minmax(0,1fr) 36px;
          gap:9px;
          padding-inline:12px;
        }
        .workspace-home .card-arrow{
          width:36px;
          height:36px;
          flex-basis:36px;
        }
      }

      @media(prefers-reduced-motion:reduce){
        .workspace-home .attention-card,
        .workspace-home .start-card,
        .workspace-home .work-card,
        .workspace-home .card-arrow{
          transition:none;
        }
        .workspace-home .attention-card:hover,
        .workspace-home .start-card:hover,
        .workspace-home .work-card:hover,
        .workspace-home .attention-card:hover .card-arrow,
        .workspace-home .start-card:hover .card-arrow,
        .workspace-home .work-card:hover .card-arrow{
          transform:none;
        }
      }

      @media(forced-colors:active){
        .workspace-home .attention-card,
        .workspace-home .start-card,
        .workspace-home .work-card{
          border-color:CanvasText;
        }
        .workspace-home .attention-dot{
          background:CanvasText;
          box-shadow:none;
        }
      }
    `}</style>
  </Layout>
);

export default WorkspacePage;
