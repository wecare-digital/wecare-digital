/**
 * Service workspace after retirement of the old service component directory.
 *
 * Customer-facing paid flows remain server-owned. The staff workspace is a
 * verified, read-only service overview; Pay & Flow owns Vault and Contribute
 * customer payment requests. Do not recreate an interactive WhatsApp sender.
 */
import React from 'react';
import Link from 'next/link';
import dynamic from 'next/dynamic';
import { useRouter } from 'next/router';
import SEO from '../../../components/SEO';
import * as api from '../../../api/client';
import { fetchServiceWorkspacePrices, rupeesFromPaise,
  type ServicePrice, type ServiceWorkspacePriceSlug } from '../../../lib/servicePricing';
import { SERVICE_WORKSPACE_VIEWS, serviceWorkspaceQuery, serviceWorkspaceTab,
  serviceWorkspaceView, type ServiceWorkspaceView } from '../../../lib/serviceWorkspaceRoutes';

const InvoiceRecords = dynamic(
  () => import('../../../components/workspace/pay/InvoiceRecords'), { ssr: false });
const ContributePaymentPlan = dynamic(
  () => import('../../../components/workspace/pay/ContributePaymentPlan'), { ssr: false });

const VIEW_LABELS: Record<ServiceWorkspaceView, string> = {
  'submit-request': 'Submit Request', 'request-amendment': 'Request Amendment',
  'drop-docs': 'Drop Docs', vault: 'Vault', shipments: 'Shipments',
  contribute: 'Contribute', 'whatsapp-logs': 'WhatsApp Logs',
};
const TABS: Record<ServiceWorkspaceView, readonly {id: string; label: string}[]> = {
  'submit-request': [{id:'overview',label:'Price & workflow'},{id:'ledger',label:'Ledger'}],
  'request-amendment': [{id:'overview',label:'Price & workflow'},{id:'ledger',label:'Ledger'}],
  'drop-docs': [{id:'upload',label:'Customer documents'},{id:'pricing',label:'Price & workflow'},{id:'ledger',label:'Ledger'}],
  vault: [{id:'documents',label:'Pay & Flow'},{id:'logs',label:'Logs'},{id:'pricing',label:'Price & workflow'},{id:'ledger',label:'Ledger'}],
  shipments: [{id:'track',label:'Track'},{id:'pickup',label:'Pickup Request'},{id:'pickup-ledger',label:'Pickup ledger'}],
  contribute: [{id:'overview',label:'Contribute'},{id:'payments',label:'Payment records'}],
  'whatsapp-logs': [{id:'messages',label:'Delivery & responses'}],
};
const OPERATIONS: Partial<Record<ServiceWorkspacePriceSlug, {
  title: string; summary: string; fulfillment: string; link: string; linkText: string; note?: string;
}>> = {
  'submit-request': {
    title: 'Submit Request', summary: 'Requests are bound to an existing customer order.',
    fulfillment: 'Verified paid Submit Request Meta Flow',
    link: '/workspace/commerce?view=orders', linkText: 'Open Orders',
  },
  'request-amendment': {
    title: 'Request Amendment', summary: 'Amendments require verified ownership of the original order.',
    fulfillment: 'Verified paid Request Amendment Meta Flow',
    link: '/workspace/commerce?view=orders', linkText: 'Open Orders',
  },
  'drop-docs': {
    title: 'Drop Docs', summary: 'Customer uploads arrive through the owner-bound paid F003 workflow.',
    fulfillment: 'Customer-upload Meta Flow; never staff Vault upload',
    link: '/workspace/service?view=drop-docs&tab=upload', linkText: 'View customer documents',
  },
  vault: {
    title: 'Vault', summary: 'One private file, one verified customer, one payment entitlement.',
    fulfillment: 'Approved Review & Pay followed by Access Vault template',
    link: '/workspace/payments?view=vault&tab=display', linkText: 'Open Vault workbench',
  },
  'request-pickup': {
    title: 'Pickup Request', summary: 'Pickup must belong to an existing order.',
    fulfillment: 'Separately gated pickup workflow',
    link: '/workspace/commerce?view=orders', linkText: 'Open Orders',
    note: 'A price is not proof of carrier acceptance or a released checkout.',
  },
  'shipments-track': {
    title: 'Shipments', summary: 'Existing shipping records are viewed through Orders.',
    fulfillment: 'Owned-order tracking, not a new payment request',
    link: '/workspace/commerce?view=orders', linkText: 'Open Orders',
  },
};

function ServicePriceCard({slug, price, loading}: {
  slug: ServiceWorkspacePriceSlug; price?: ServicePrice; loading: boolean;
}) {
  const spec = OPERATIONS[slug];
  if (!spec) return null;
  const live = price?.available ? price : null;
  return (
    <section className="service-panel" aria-label={spec.title + ' pricing'}>
      <p className="kicker">SERVICE / SERVER-PRICED</p>
      <h2>{spec.title}</h2>
      <p>{spec.summary}</p>
      <dl>
        <div><dt>Live catalogue price</dt><dd>{loading ? 'Checking…'
          : live ? '₹' + rupeesFromPaise(live.paise) : 'Unavailable'}</dd></div>
        <div><dt>Fulfilment</dt><dd>{spec.fulfillment}</dd></div>
        {live?.breakdown && <div><dt>Server-calculated total payable</dt>
          <dd>₹{rupeesFromPaise(live.breakdown.totalPayablePaise)}</dd></div>}
      </dl>
      <p>Pricing is displayed from the server. This page never fabricates a payment,
        opens a Flow without verified eligibility, or grants file access.</p>
      {spec.note && <p role="status">{spec.note}</p>}
      <Link href={spec.link}>{spec.linkText}</Link>
    </section>
  );
}

function CustomerDocuments() {
  const [docs, setDocs] = React.useState<api.Document[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState('');
  React.useEffect(() => {
    let active = true;
    void api.listDocuments({source: 'flow', limit: 100})
      .then(result => { if (active) setDocs(
        (result.documents || []).filter(doc => !!doc.dropDocsRequestId)); })
      .catch(() => { if (active) setError('Document register could not be verified.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);
  return (
    <section className="service-panel">
      <h2>Customer Drop Docs records · read only</h2>
      <p>Only records linked to a paid F003 service request are shown. Files are not published
        to Vault or sent through WhatsApp from this screen.</p>
      {error && <p role="alert">{error}</p>}
      {loading ? <p>Loading customer document records…</p>
        : docs.length === 0 ? <p>No verified F003 documents found in this list.</p>
        : <div className="service-records">
          {docs.map(doc => <div key={doc.documentId}>
            <strong>{doc.originalFileName || doc.fileName || 'Customer document'}</strong>
            <code>{doc.documentRef || doc.documentId}</code>
            <span>{doc.status || 'unknown'} · {doc.orderNumber || 'Order not listed'}</span>
          </div>)}
        </div>}
    </section>
  );
}

export default function ServicePage({signOut, user}: {
  signOut?: () => void; user?: unknown;
}) {
  const router = useRouter();
  const active = serviceWorkspaceView(router.query.view);
  const tab = serviceWorkspaceTab(active, router.query.tab);
  const [prices, setPrices] = React.useState<Record<string, ServicePrice>>({});
  const [loadingPrices, setLoadingPrices] = React.useState(true);
  React.useEffect(() => {
    if (!router.isReady || router.query.view !== 'vault') return;
    void router.replace(tab === 'ledger'
      ? '/workspace/payments?view=vault&tab=ledger'
      : '/workspace/payments?view=vault&tab=display');
  }, [router.isReady, router.query.view, tab, router]);
  React.useEffect(() => {
    let activeRead = true;
    void fetchServiceWorkspacePrices()
      .then(next => { if (activeRead) setPrices(next); })
      .catch(() => { if (activeRead) setPrices({}); })
      .finally(() => { if (activeRead) setLoadingPrices(false); });
    return () => { activeRead = false; };
  }, []);

  const go = (view: ServiceWorkspaceView, nextTab?: string) =>
    void router.push({pathname: '/workspace/service',
      query: serviceWorkspaceQuery(view, nextTab)});
  const price = (slug: ServiceWorkspacePriceSlug) =>
    <ServicePriceCard slug={slug} price={prices[slug]} loading={loadingPrices} />;
  const ledger = (kind: string) =>
    <InvoiceRecords signOut={signOut} user={user} embedded serviceKind={kind} />;

  const content = () => {
    if (active === 'vault') return <section className="service-panel">
      <h2>Vault moved to Pay &amp; Flow</h2>
      <p>Private files and paid access are managed in one owner-bound workbench.</p>
      <Link href="/workspace/payments?view=vault&tab=display">Open Vault</Link>
    </section>;
    if (active === 'contribute') return tab === 'payments'
      ? <section className="service-panel">
          <h2>Contribute payment records</h2>
          <p>Contribute belongs to a verified commerce order, not a Vault or request-service invoice.</p>
          <Link href="/workspace/payments?view=contribute&tab=ledger">Open Contribute ledger</Link>
        </section>
      : <ContributePaymentPlan workspaceView="display" />;
    if (active === 'whatsapp-logs') return <section className="service-panel">
      <h2>WhatsApp delivery and responses</h2>
      <p>Read current provider message evidence in the communications inbox.
        A delivered or read message does not establish payment.</p>
      <Link href="/workspace/communications?view=inbox">Open Communications inbox</Link>
    </section>;
    if (active === 'drop-docs')
      return tab === 'ledger' ? ledger('DROP_DOCS')
        : tab === 'pricing' ? price('drop-docs') : <CustomerDocuments />;
    if (active === 'shipments')
      return tab === 'pickup-ledger' ? ledger('REQUEST_PICKUP')
        : tab === 'pickup' ? price('request-pickup') : price('shipments-track');
    if (active === 'request-amendment')
      return tab === 'ledger' ? ledger('REQUEST_AMENDMENT') : price('request-amendment');
    return tab === 'ledger' ? ledger('SUBMIT_REQUEST') : price('submit-request');
  };

  return (
    <>
      <SEO title="Service" description="Server-priced request services and owner-bound evidence" noindex />
      <div className="service-shell">
        <nav className="service-switch" aria-label="Service workspace">
          {SERVICE_WORKSPACE_VIEWS.filter(view => view !== 'vault').map(view =>
            <button key={view} type="button" aria-pressed={active === view}
              className={active === view ? 'active' : ''} onClick={() => go(view)}>
              {VIEW_LABELS[view]}</button>)}
        </nav>
        <nav className="service-tabs" aria-label={VIEW_LABELS[active] + ' operations'}>
          {TABS[active].map(item =>
            <button key={item.id} type="button" aria-pressed={tab === item.id}
              className={tab === item.id ? 'active' : ''} onClick={() => go(active,item.id)}>
              {item.label}</button>)}
        </nav>
        {content()}
      </div>
      <style jsx>{`
        .service-shell{padding:14px 0 40px;max-width:1300px;margin:0 auto}
        .service-switch,.service-tabs{display:flex;gap:6px;overflow-x:auto;max-width:100%;padding:6px;background:var(--bg-secondary);border:1px solid var(--border);border-radius:12px;margin-bottom:15px}
        .service-switch button,.service-tabs button{font:inherit;font-weight:700;font-size:12px;white-space:nowrap;padding:12px;border:0;border-radius:8px;cursor:pointer;background:transparent;color:var(--text-muted)}
        .service-switch button.active,.service-tabs button.active{background:var(--surface);color:var(--text-primary)}
        .service-switch button:focus-visible,.service-tabs button:focus-visible{outline:3px solid var(--accent)}
        :global(.service-panel){padding:24px;max-width:850px;margin:12px 0;border:1px solid var(--border);border-radius:14px;background:var(--surface)}
        :global(.service-panel h2){font-size:25px;margin:0 0 8px}
        :global(.service-panel p){font-size:13px;color:var(--text-muted);line-height:1.6}
        :global(.service-panel .kicker){font-weight:800;letter-spacing:.08em}
        :global(.service-panel dl){display:grid;gap:9px}
        :global(.service-panel dl>div){display:flex;justify-content:space-between;gap:15px;border-bottom:1px solid var(--border);padding:8px 0}
        :global(.service-panel dd){margin:0;font-weight:750;text-align:right}
        :global(.service-panel a){display:inline-flex;margin-top:12px;min-height:42px;align-items:center;padding:10px 14px;border:1px solid var(--border);border-radius:9px;font-size:13px;font-weight:750;text-decoration:none;color:var(--text-primary)}
        :global(.service-records){display:grid;gap:8px}
        :global(.service-records>div){display:grid;gap:4px;padding:10px;border:1px solid var(--border);border-radius:8px}
        :global(.service-records code){font-size:11px}
      `}</style>
    </>
  );
}
