/**
 * Workspace Home — the operator launchpad.
 *
 * This page replaces module-menu navigation. It deliberately shows no fabricated counts:
 * until a server aggregate exists, attention rows are real queue destinations rather than
 * decorative numbers computed from partial browser data.
 */
import React from 'react';
import Link from 'next/link';
import Layout from '../../components/Layout';
import SEO from '../../components/SEO';

interface PageProps { signOut?: () => void; user?: any; }

const attention = [
  { label: 'Conversations', detail: 'Unread and customer conversations', href: '/workspace/communications?view=inbox' },
  { label: 'Payments', detail: 'Pending, failed and reconciled payment records', href: '/workspace/payments?view=activity' },
  { label: 'Orders', detail: 'Store and staff-created commerce orders', href: '/workspace/commerce' },
  { label: 'Service requests', detail: 'Customer requests and Flow submissions', href: '/workspace/service?view=requests' },
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
  { label: 'Payments', detail: 'Collect, invoices and activity', href: '/workspace/payments' },
  { label: 'Service', detail: 'Requests, appointments and documents', href: '/workspace/service' },
  { label: 'Content', detail: 'Blog, production, SEO and short links', href: '/workspace/content' },
  { label: 'Automation & AI', detail: 'Staff agent, rules, schedules and knowledge', href: '/workspace/automation' },
  { label: 'Tasks', detail: 'Assignments and follow-ups', href: '/workspace/task' },
];

const Arrow = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
    <path d="M5 12h14M14 7l5 5-5 5"/>
  </svg>
);

const WorkspacePage: React.FC<PageProps> = ( { signOut, user } ) => (
  <Layout user={ user } onSignOut={ signOut } showBreadcrumbs={ false }>
    <SEO title="Workspace" description="WECARE.DIGITAL operational workspace." noindex />
    <div className="workspace-home">
      <header className="home-intro">
        <p className="eyebrow">WECARE.DIGITAL</p>
        <h1>Workspace</h1>
        <p>Start work, find what needs attention, or open an operating area.</p>
      </header>

      <section className="home-section" aria-labelledby="attention-title">
        <div className="section-head">
          <h2 id="attention-title">Needs attention</h2>
          <p>Open the queue that needs review. Counts appear only when they come from an authoritative aggregate.</p>
        </div>
        <div className="attention-list">
          { attention.map( ( item ) => (
            <Link key={ item.href } href={ item.href } className="attention-row">
              <span><strong>{ item.label }</strong><small>{ item.detail }</small></span>
              <Arrow />
            </Link>
          ) ) }
        </div>
      </section>

      <section className="home-section" aria-labelledby="start-title">
        <div className="section-head"><h2 id="start-title">Start</h2></div>
        <div className="start-grid">
          { start.map( ( item ) => (
            <Link key={ item.label } href={ item.href } className="start-card">
              <strong>{ item.label }</strong>
              <span>{ item.detail }</span>
              <Arrow />
            </Link>
          ) ) }
        </div>
      </section>

      <section className="home-section" aria-labelledby="work-title">
        <div className="section-head"><h2 id="work-title">Work</h2></div>
        <div className="work-grid">
          { workspaces.map( ( item ) => (
            <Link key={ item.label } href={ item.href } className="work-card">
              <strong>{ item.label }</strong>
              <span>{ item.detail }</span>
              <Arrow />
            </Link>
          ) ) }
        </div>
      </section>
    </div>

    <style jsx>{`
      .workspace-home{width:min(100%,1180px);margin:0 auto;padding:clamp(20px,4vw,48px);box-sizing:border-box}
      .home-intro{max-width:760px;margin-bottom:clamp(30px,5vw,56px)}
      .eyebrow{margin:0 0 6px;font-size:var(--text-xs);font-weight:750;letter-spacing:.08em;text-transform:uppercase;color:var(--text-muted)}
      h1{margin:0;color:var(--text);font-size:clamp(34px,7vw,64px);line-height:1;letter-spacing:-.045em}
      .home-intro>p:last-child{margin:14px 0 0;color:var(--text-muted);font-size:clamp(16px,2vw,20px);line-height:1.5}
      .home-section{margin-top:clamp(28px,5vw,48px)}
      .section-head{margin-bottom:14px}
      .section-head h2{margin:0;color:var(--text);font-size:clamp(20px,3vw,26px)}
      .section-head p{margin:5px 0 0;color:var(--text-muted);font-size:var(--text-sm);max-width:720px}
      .attention-list{border:1px solid var(--border);border-radius:16px;overflow:hidden;background:#fff}
      .attention-row{min-height:64px;padding:12px 16px;display:flex;align-items:center;justify-content:space-between;gap:18px;text-decoration:none;color:var(--text);border-top:1px solid var(--border-light)}
      .attention-row:first-child{border-top:0}
      .attention-row span:first-child{display:flex;flex-direction:column;gap:3px;min-width:0}
      .attention-row strong{font-size:var(--text-md)}
      .attention-row small{font-size:var(--text-xs);color:var(--text-muted);line-height:1.4}
      .attention-row:hover,.attention-row:focus-visible,.start-card:hover,.start-card:focus-visible,.work-card:hover,.work-card:focus-visible{background:var(--bg-secondary)}
      .attention-row:focus-visible,.start-card:focus-visible,.work-card:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
      .start-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}
      .start-card,.work-card{min-height:112px;padding:16px;border:1px solid var(--border);border-radius:16px;background:#fff;color:var(--text);text-decoration:none;display:flex;flex-direction:column;align-items:flex-start;gap:5px;position:relative}
      .start-card strong,.work-card strong{font-size:var(--text-lg)}
      .start-card span,.work-card span{font-size:var(--text-xs);color:var(--text-muted);line-height:1.45;padding-inline-end:24px}
      .start-card :global(svg),.work-card :global(svg){position:absolute;inset-inline-end:14px;bottom:14px;color:var(--accent)}
      .work-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
      .work-card{min-height:130px}
      @media(max-width:900px){.start-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.work-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
      @media(max-width:520px){
        .workspace-home{padding:20px 14px 28px}
        .start-grid,.work-grid{grid-template-columns:1fr}
        .start-card,.work-card{min-height:88px}
        .attention-row{min-height:68px;padding:12px 14px}
      }
      @media(prefers-reduced-motion:reduce){.attention-row,.start-card,.work-card{scroll-behavior:auto}}
      @media(forced-colors:active){.attention-list,.attention-row,.start-card,.work-card{border-color:CanvasText}}
    `}</style>
  </Layout>
);

export default WorkspacePage;
