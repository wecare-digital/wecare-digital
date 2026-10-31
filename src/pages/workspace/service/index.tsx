/**
 * Workspace Service — one operational home, one authoritative payment backend.
 *
 * Five paid single-order services share ProductsTable pricing, immutable
 * PaymentAttempts / invoice evidence and Meta Review & Pay images. Their
 * fulfilment is NOT interchangeable:
 * - Submit Request and Request Amendment: paid owner-bound Meta Flows
 * - Drop Docs: paid customer-upload F003 Flow and staff review (never staff file intake)
 * - Vault: private secure download entitlement; NEVER Drop Docs upload Flow
 * - Shipments: owned-order tracking and separately gated paid Pickup Request
 * - Contribute: voluntary catalog purchase, not a request-service Flow
 * - WhatsApp Logs: read-only delivery and signed Flow-response history
 *
 * Prices are read-only previews; no generic staff invoice here can open a
 * private Vault file, upload a document, or issue a pickup request.
 */
import React, { Suspense } from 'react';
import Link from 'next/link';
import dynamic from 'next/dynamic';
import { useRouter } from 'next/router';
import SEO from '../../../components/SEO';
import {
  fetchServiceWorkspacePrices,
  type ServicePrice,
  type ServiceWorkspacePriceSlug,
} from '../../../lib/servicePricing';
import {
  SERVICE_WORKSPACE_VIEWS, serviceWorkspaceQuery, serviceWorkspaceTab,
  serviceWorkspaceView, type ServiceWorkspaceView,
} from '../../../lib/serviceWorkspaceRoutes';
import ServicePriceOverview from '../../../components/workspace/service/ServicePriceOverview';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const SecureFiles = dynamic(
  () => import('../../../components/workspace/service/SecureFiles'),
  { ssr: false },
);
const CustomerDropDocs = dynamic(
  () => import('../../../components/workspace/service/CustomerDropDocs'),
  { ssr: false },
);
const Contribute = dynamic(
  () => import('../../../components/workspace/service/Contribute'),
  { ssr: false },
);
const VaultLogs = dynamic(
  () => import('../../../components/workspace/service/VaultLogs'),
  { ssr: false },
);
const InvoiceRecords = dynamic(
  () => import('../../../components/workspace/pay/InvoiceRecords'),
  { ssr: false },
);
const ShipmentTrackingPanel = dynamic(
  () => import('../../../components/workspace/service/ShipmentTrackingPanel'),
  { ssr: false },
);
const WhatsAppServiceLogs = dynamic(
  () => import('../../../components/workspace/service/WhatsAppServiceLogs'),
  { ssr: false },
);

const VIEW_LABELS: Record<ServiceWorkspaceView, string> = {
  'submit-request': 'Submit Request',
  'request-amendment': 'Request Amendment',
  'drop-docs': 'Drop Docs',
  vault: 'Vault',
  shipments: 'Shipments',
  contribute: 'Contribute',
  'whatsapp-logs': 'WhatsApp Logs',
};

const TABS: Record<ServiceWorkspaceView, readonly { id: string; label: string }[]> = {
  'submit-request': [
    { id: 'overview', label: 'Price & workflow' },
    { id: 'ledger', label: 'Ledger' },
  ],
  'request-amendment': [
    { id: 'overview', label: 'Price & workflow' },
    { id: 'ledger', label: 'Ledger' },
  ],
  'drop-docs': [
    { id: 'upload', label: 'Customer uploads' },
    { id: 'pricing', label: 'Price & workflow' },
    { id: 'ledger', label: 'Ledger' },
  ],
  vault: [
    { id: 'documents', label: 'Documents' },
    { id: 'logs', label: 'Logs' },
    { id: 'pricing', label: 'Price & workflow' },
    { id: 'ledger', label: 'Ledger' },
  ],
  shipments: [
    { id: 'track', label: 'Track' },
    { id: 'pickup', label: 'Pickup Request' },
    { id: 'pickup-ledger', label: 'Pickup ledger' },
  ],
  contribute: [
    { id: 'overview', label: 'Contribute' },
    { id: 'payments', label: 'Payment records' },
  ],
  'whatsapp-logs': [ { id: 'messages', label: 'Delivery & responses' } ],
};

const COMMON_ORDERS = { label: 'Open staff Orders', href: '/workspace/commerce?view=orders' } as const;

const SERVICE_OPERATIONS = {
  'submit-request': {
    label: 'Submit Request',
    summary: 'Raise a request for a verified, existing customer order. The request is not started by creating a free-text invoice.',
    fulfilment: 'Paid Submit Request Flow',
    actions: [ COMMON_ORDERS ],
  },
  'request-amendment': {
    label: 'Request Amendment',
    summary: 'Change an existing request only after verifying the owner and original order. Do not create another order to amend one.',
    fulfilment: 'Paid Request Amendment Flow',
    actions: [ COMMON_ORDERS ],
  },
  'drop-docs': {
    label: 'Drop Docs',
    summary: 'Customers upload documents through their paid, owner-bound F003 Flow; staff review received files. Staff upload/publish belongs to Vault.',
    fulfilment: 'Paid document upload Flow',
    actions: [ { label: 'Review customer uploads', href: '/workspace/service?view=drop-docs' } ],
  },
  vault: {
    label: 'Vault',
    summary: 'Secure access to an existing private file. Payment must be bound to its verified owner and file ID; Vault is NOT the Drop Docs upload Flow.',
    fulfilment: 'Owner-bound secure download link',
    actions: [ { label: 'Open Vault in Pay & Flow', href: '/workspace/payments?view=vault' } ],
  },
  'request-pickup': {
    label: 'Pickup Request',
    summary: 'Request collection for an existing customer order. Carrier availability and the separately verified pickup Meta Flow govern fulfilment.',
    fulfilment: 'Release-gated paid pickup Flow',
    actions: [ COMMON_ORDERS ],
    warning: 'Pickup payment initiation remains separately release-gated. A visible catalog price does not mean checkout is enabled or that a courier has accepted pickup.',
  },
  'shipments-track': {
    label: 'Shipments · Track',
    summary: 'Check the status and manual carrier details of an already-owned shipment in Orders. A separately priced Track Shipping catalog item exists; viewing an existing tracking record does not create a new purchase.',
    fulfilment: 'Read existing shipment status',
    actions: [ COMMON_ORDERS ],
    warning: 'This is the separate Track Shipping catalog SKU price, not a charge for opening an existing order. No payment is initiated here.',
  },
} as const;

export default function ServicePage({ signOut, user }: PageProps) {
  const router = useRouter();
  const active = serviceWorkspaceView(router.query.view);
  const tab = serviceWorkspaceTab(active, router.query.tab);
  const [prices, setPrices] = React.useState<Record<string, ServicePrice>>({});
  const [loadingPrices, setLoadingPrices] = React.useState(true);

  // Preserve old bookmarks, but Vault's only new operating tab is Pay & Flow.
  React.useEffect(() => {
    if (!router.isReady || router.query.view !== 'vault') return;
    const oldTab = Array.isArray(router.query.tab) ? router.query.tab[0] : router.query.tab;
    const destination = oldTab === 'ledger'
      ? '/workspace/payments?view=ledger&ledger=vault'
      : '/workspace/payments?view=vault';
    void router.replace(destination);
  }, [router.isReady, router.query.view, router.query.tab]);

  React.useEffect(() => {
    let alive = true;
    setLoadingPrices(true);
    void fetchServiceWorkspacePrices()
      .then(result => { if (alive) setPrices(result); })
      .finally(() => { if (alive) setLoadingPrices(false); });
    return () => { alive = false; };
  }, []);

  const go = (view: ServiceWorkspaceView, nextTab?: string) => {
    void router.push({
      pathname: '/workspace/service',
      query: serviceWorkspaceQuery(view, nextTab),
    });
  };

  const pricePanel = (slug: ServiceWorkspacePriceSlug) => {
    const config = SERVICE_OPERATIONS[slug as keyof typeof SERVICE_OPERATIONS];
    if (!config) return null;
    return (
      <ServicePriceOverview
        slug={slug} label={config.label} summary={config.summary}
        fulfilment={config.fulfilment} actions={config.actions}
        price={prices[slug]} loading={loadingPrices}
        warning={'warning' in config ? config.warning : undefined}
      />
    );
  };

  const serviceLedger = (kind: string) => (
    <InvoiceRecords signOut={signOut} user={user} embedded serviceKind={kind} />
  );

  const content = () => {
    if (active === 'whatsapp-logs') return <WhatsAppServiceLogs />;
    if (active === 'vault') {
      if (tab === 'logs') return <VaultLogs />;
      if (tab === 'ledger') return serviceLedger('VAULT');
      if (tab === 'pricing') return pricePanel('vault');
      return <SecureFiles signOut={signOut} user={user} embedded />;
    }
    if (active === 'drop-docs') {
      if (tab === 'ledger') return serviceLedger('DROP_DOCS');
      if (tab === 'pricing') return pricePanel('drop-docs');
      // Customer F003 owns uploads. Staff review them here; Vault owns staff upload and publish.
      return <CustomerDropDocs />;
    }
    if (active === 'shipments') {
      if (tab === 'pickup-ledger') return serviceLedger('REQUEST_PICKUP');
      if (tab === 'pickup') return pricePanel('request-pickup');
      return (
        <>
          {pricePanel('shipments-track')}
          <ShipmentTrackingPanel />
        </>
      );
    }
    if (active === 'contribute') {
      if (tab === 'payments') return (
        <section className="service-contribute-records">
          <h1>Contribute · payment records</h1>
          <p>New catalog contributions use the shared commerce payment and invoice records.
            Legacy standalone contributions are provider-verified payments with no order or
            GST invoice. They must not be counted as paid request-service invoices.</p>
          <Link href="/workspace/payments?view=ledger&ledger=invoices">Open all invoice records</Link>
          <Link href="/workspace/payments?view=ledger&ledger=activity">Open payment activity</Link>
        </section>
      );
      return <Contribute />;
    }
    if (active === 'request-amendment') {
      return tab === 'ledger' ? serviceLedger('REQUEST_AMENDMENT') : pricePanel('request-amendment');
    }
    return tab === 'ledger' ? serviceLedger('SUBMIT_REQUEST') : pricePanel('submit-request');
  };

  return (
    <>
      <SEO title="Service" description="Request operations, customer Drop Docs upload review, staff Vault upload, shipment tracking, pickup, contributions, and WhatsApp service logs." noindex />

      <nav className="service-switch" aria-label="Service workspace">
        {SERVICE_WORKSPACE_VIEWS.filter(view => view !== 'vault').map(view => (
          <button key={view} type="button" aria-pressed={active === view}
            className={active === view ? 'active' : ''}
            onClick={() => go(view)}>
            {VIEW_LABELS[view]}
          </button>
        ))}
      </nav>

      <nav className="service-tabs" aria-label={VIEW_LABELS[active] + ' operations'}>
        {TABS[active].map(item => (
          <button key={item.id} type="button" aria-pressed={tab === item.id}
            className={tab === item.id ? 'active' : ''}
            onClick={() => go(active, item.id)}>
            {item.label}
          </button>
        ))}
      </nav>

      <Suspense fallback={<p className="service-loading">Loading {VIEW_LABELS[active]}…</p>}>
        {content()}
      </Suspense>

      <style jsx>{`
        .service-switch,.service-tabs{display:flex;max-width:100%;width:max-content;min-width:0;gap:5px;padding:5px;border:1px solid var(--border);overflow-x:auto;overflow-y:hidden;scrollbar-width:none;overscroll-behavior-inline:contain}
        .service-switch::-webkit-scrollbar,.service-tabs::-webkit-scrollbar{display:none}
        .service-switch{margin:0 0 13px;border-radius:14px;background:var(--surface)}
        .service-tabs{margin:0 0 24px;border-radius:11px;background:#fff}
        .service-switch button,.service-tabs button{flex-shrink:0;border:0;background:transparent;color:var(--text-muted);font:700 13px/1 var(--font-sans);cursor:pointer;white-space:nowrap}
        .service-switch button{min-height:43px;padding:0 15px;border-radius:10px}
        .service-tabs button{min-height:38px;padding:0 14px;border-radius:8px}
        .service-switch button.active{background:var(--lime);color:var(--accent)}
        .service-tabs button.active{background:rgba(209,244,112,.38);color:var(--accent)}
        .service-switch button:focus-visible,.service-tabs button:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
        .service-loading{padding:46px 15px;color:var(--text-muted)}
        .service-contribute-records{padding:8px 0 40px;max-width:800px;color:var(--text)}
        .service-contribute-records h1{font-size:clamp(27px,3vw,39px);margin:0 0 8px}
        .service-contribute-records p{line-height:1.6;color:var(--text-muted);margin:0 0 22px}
        .service-contribute-records a{display:inline-flex;margin:0 10px 10px 0;padding:12px 16px;border:1px solid var(--border);border-radius:10px;background:#fff;color:var(--accent);font-weight:750;text-decoration:none}
        @media(max-width:760px){.service-switch,.service-tabs{width:100%}.service-switch button{padding:0 12px}}
      `}</style>
    </>
  );
}
