/**
 * Canonical Pay & Flow workspace. ONE route, three scoped sections and three
 * work tabs. This file only routes existing payment/business components:
 * no new money state, template send path, or data store is introduced.
 *
 * Old bookmarked view=collect/vault/contribute/defaults/timing/ledger links
 * remain valid; new navigation uses view=<section>&tab=<display|create|ledger>.
 */
import React from 'react';
import dynamic from 'next/dynamic';
import { useRouter } from 'next/router';
import Link from 'next/link';
import SEO from '../../../components/SEO';
import PageShell from '../../../components/PageShell';
import PayFlowPage from '../../../components/workspace/pay/PayFlow';
import PaymentsActivity from '../../../components/workspace/pay/PaymentsActivity';
import CollectOverview from '../../../components/workspace/pay/CollectOverview';
import InvoiceRecords from '../../../components/workspace/pay/InvoiceRecords';
import PaymentTemplateMedia from '../../../components/workspace/pay/PaymentTemplateMedia';
import { SERVICE_CHOICES, type ServiceChoice, type ServiceSlug } from '../../../config/services';
import { fetchServicePrices, rupeesFromPaise, type ServicePrice } from '../../../lib/servicePricing';

interface PageProps { signOut?: () => void; user?: any; }

const VaultWorkbench = dynamic( () => import('../../../components/workspace/service/SecureFiles'), { ssr: false } );
const VaultDeliveryTiming = dynamic( () => import('../../../components/workspace/pay/VaultDeliveryTiming'), { ssr: false } );
const ContributePaymentPlan = dynamic( () => import('../../../components/workspace/pay/ContributePaymentPlan'), { ssr: false } );

type PaymentSection = 'collect' | 'vault' | 'contribute';
type PaymentTab = 'display' | 'create' | 'ledger';
type LedgerView = 'invoices' | 'activity' | ServiceSlug;
type LegacyPanel = 'defaults' | 'timing' | null;

const SECTION_OPTIONS: {value: PaymentSection; label: string}[] = [
  {value: 'collect', label: 'Collect'},
  {value: 'vault', label: 'Vault'},
  {value: 'contribute', label: 'Contribute'},
];
const WORK_TABS: {value: PaymentTab; label: string}[] = [
  {value: 'display', label: 'Display'},
  {value: 'create', label: 'Create'},
  {value: 'ledger', label: 'Ledger'},
];

function one(raw: string | string[] | undefined): string {
  return Array.isArray(raw) ? (raw[0] || '') : (raw || '');
}

function ledgerMode(rawView: string | string[] | undefined,
                    rawLedger: string | string[] | undefined): LedgerView {
  if (one(rawView) === 'activity' || one(rawLedger) === 'activity') return 'activity';
  const requested = one(rawLedger);
  if (SERVICE_CHOICES.some(service => service.slug === requested)) return requested as ServiceSlug;
  return 'invoices';
}

/** A bookmark's old meaning wins when no new tab was supplied.
 * The bare canonical page opens Collect / Display.
 */
export function resolvePaymentsLocation(
  viewRaw: string | string[] | undefined,
  tabRaw: string | string[] | undefined,
  ledgerRaw: string | string[] | undefined,
  sectionRaw: string | string[] | undefined,
): {section: PaymentSection; tab: PaymentTab; legacy: LegacyPanel} {
  const view = one(viewRaw);
  const tab = one(tabRaw);
  const section = one(sectionRaw);
  if (view === 'defaults') return {section: 'collect', tab: 'create', legacy: 'defaults'};
  if (view === 'timing') return {section: 'vault', tab: 'create', legacy: 'timing'};
  if (view === 'ledger' || view === 'invoices' || view === 'activity') {
    const selectedLedger = ledgerMode(viewRaw, ledgerRaw);
    const scoped = (section === 'collect' || section === 'vault' || section === 'contribute')
      ? section : selectedLedger === 'vault' ? 'vault'
        : one(ledgerRaw) === 'contribute' ? 'contribute' : 'collect';
    return {section: scoped, tab: 'ledger', legacy: null};
  }
  if (view === 'collect' || view === 'vault' || view === 'contribute') {
    const chosenTab: PaymentTab = tab === 'display' || tab === 'create' || tab === 'ledger'
      ? tab : 'create';
    return {section: view, tab: chosenTab, legacy: null};
  }
  return {section: 'collect', tab: 'display', legacy: null};
}

const money = ( paise: number | undefined ): string =>
  typeof paise === 'number' ? `₹${ rupeesFromPaise( paise ) }` : '—';

const DefaultInvoiceItems: React.FC<{ onUse: ( choice: ServiceChoice ) => void }> = ( { onUse } ) => {
  const [ prices, setPrices ] = React.useState<Record<string, ServicePrice>>( {} );
  const [ loading, setLoading ] = React.useState( true );

  React.useEffect( () => {
    let active = true;
    setLoading( true );
    fetchServicePrices()
      .then( next => { if ( active ) setPrices( next ); } )
      .finally( () => { if ( active ) setLoading( false ); } );
    return () => { active = false; };
  }, [] );

  // All five request services now expose the same approved Meta images.
  // Preview whichever live server-priced service supplied the verified media;
  // do not couple the shared asset display to Vault availability.
  const templatePreview = SERVICE_CHOICES
    .map( choice => prices[ choice.slug ] )
    .find( price => price?.available && !!price.templates );

  return (
    <section className="default-items" aria-label="Default invoice items">
      <div className="default-items-panel">
      <div className="default-items-head">
        <div>
          <div className="default-items-kicker">Server-priced presets</div>
          <h2>Default invoice items</h2>
          <p>All amounts come from live server pricing. File-bound services open their own verified service workflow; a generic invoice cannot unlock a Vault file.</p>
        </div>
        <span>{ loading ? 'Loading live prices' : 'Live pricing' }</span>
      </div>
      <div className="default-items-table-wrap">
        <table className="default-items-table">
          <thead>
            <tr><th>Request item</th><th>Item price</th><th>GST</th><th>Delight</th><th>Express</th><th>Payable</th><th></th></tr>
          </thead>
          <tbody>
            { SERVICE_CHOICES.map( choice => {
              const price = prices[ choice.slug ];
              const b = price?.available ? price.breakdown : undefined;
              return (
                <tr key={ choice.kind }>
                  <td><strong>{ choice.label }</strong><small>{ choice.sku }</small></td>
                  <td>{ price?.available ? `₹${ price.rupees }` : 'Unavailable' }</td>
                  <td>{ b ? money( b.supplyGstPaise ) : 'Auto' }</td>
                  <td>{ b ? `−${ money( b.delightPaise ) }` : 'Auto' }</td>
                  <td>{ b && b.expressPaise > 0 ? money( b.expressPaise ) : '—' }</td>
                  <td>{ b ? money( b.totalPayablePaise ) : 'Preview after use' }</td>
                  <td>
                    <button type="button" disabled={ !price?.available } onClick={ () => onUse( choice ) }>
                      { choice.needsTarget ? 'Open service' : 'Use in Collect' }
                    </button>
                  </td>
                </tr>
              );
            } ) }
          </tbody>
        </table>
      </div>
      <details className="default-media-preview">
        <summary>Approved WhatsApp Review &amp; Pay header and item icon</summary>
        <PaymentTemplateMedia
          serviceLabel="All request services"
          templates={ templatePreview?.available ? templatePreview.templates : null }
        />
      </details>
      </div>
    </section>
  );
};

const PaymentsPage: React.FC<PageProps> = ({signOut, user}) => {
  const router = useRouter();
  const location = resolvePaymentsLocation(
    router.query.view, router.query.tab, router.query.ledger, router.query.section,
  );
  const {section, tab, legacy} = location;
  const ledgerView = ledgerMode(router.query.view, router.query.ledger);
  const serviceLedger = SERVICE_CHOICES.find(choice => choice.slug === ledgerView);

  const navigate = (query: Record<string, string>) => {
    void router.push({pathname: '/workspace/payments', query});
  };
  const changeSection = (next: PaymentSection) => {
    // Switching sections starts with its read-only overview.
    navigate({view: next, tab: 'display'});
  };
  const changeTab = (next: PaymentTab) => {
    if (next === 'ledger') {
      const ledger = section === 'vault' ? 'vault'
        : section === 'contribute' ? 'contribute' : 'invoices';
      navigate({view: 'ledger', ledger, section});
      return;
    }
    navigate({view: section, tab: next});
  };
  const goLedger = (next: LedgerView) => {
    const query: Record<string, string> = {
      view: 'ledger',
      ledger: next,
      section: next === 'vault' ? 'vault' : next === 'invoices' || next === 'activity'
        ? 'collect' : section,
    };
    const invoice = one(router.query.invoice);
    if (invoice && next === 'invoices') query.invoice = invoice;
    navigate(query);
  };
  const useDefaultItem = (choice: ServiceChoice) => {
    // File or service targets must always go through their bound workflow.
    if (choice.needsTarget) {
      void router.push(choice.kind === 'VAULT'
        ? '/workspace/payments?view=vault&tab=create' : choice.path);
      return;
    }
    navigate({view: 'collect', tab: 'create', preset: choice.slug});
  };

  const nav = (
    <div className="pay-flow-navigation" aria-label="Pay and Flow navigation">
      <div className="pay-flow-section-picker">
        <label htmlFor="pay-flow-section">Choose payment section</label>
        <select id="pay-flow-section" value={section}
          onChange={event => changeSection(event.target.value as PaymentSection)}>
          {SECTION_OPTIONS.map(option => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>
        <p>Collect payments, manage exact-file Vault deliveries and review Contribute collections.</p>
      </div>
      <div className="pay-flow-work-tabs" role="tablist"
        aria-label={`${SECTION_OPTIONS.find(option => option.value === section)?.label || 'Payment'} workspace tabs`}>
        {WORK_TABS.map(option => (
          <button key={option.value} type="button" role="tab"
            aria-selected={tab === option.value}
            className={tab === option.value ? 'active' : ''}
            onClick={() => changeTab(option.value)}>
            {option.label}
          </button>
        ))}
      </div>
      <style jsx>{`
        .pay-flow-navigation{max-width:1340px;display:grid;gap:14px;padding:2px 0 14px}
        .pay-flow-section-picker{display:grid;grid-template-columns:minmax(180px,400px) 1fr;gap:6px 18px;align-items:end}
        .pay-flow-section-picker label{grid-column:1/-1;font-size:12px;font-weight:800;color:var(--text-muted)}
        .pay-flow-section-picker select{width:100%;min-width:0;min-height:48px;padding:10px 14px;border:1px solid var(--border);border-radius:11px;background:var(--surface);color:var(--text-primary);font:inherit;font-size:15px;font-weight:750;cursor:pointer}
        .pay-flow-section-picker p{margin:0;align-self:center;color:var(--text-muted);font-size:12px;line-height:1.5;max-width:510px}
        .pay-flow-work-tabs{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;border:1px solid var(--border);padding:5px;background:var(--bg-secondary);border-radius:13px;max-width:650px}
        .pay-flow-work-tabs button{min-height:45px;border:1px solid transparent;border-radius:9px;background:transparent;font:inherit;font-size:13px;font-weight:750;color:var(--text-muted);cursor:pointer;padding:8px 13px}
        .pay-flow-work-tabs button.active{color:var(--text-primary);border-color:var(--border);background:var(--surface);box-shadow:0 1px 4px rgba(0,0,0,.06)}
        .pay-flow-work-tabs button:hover:not(.active){color:var(--text-primary)}
        .pay-flow-section-picker select:focus-visible,.pay-flow-work-tabs button:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
        @media(max-width:700px){.pay-flow-navigation{gap:12px}.pay-flow-section-picker{grid-template-columns:1fr}.pay-flow-section-picker p{font-size:12px}.pay-flow-work-tabs{max-width:none}.pay-flow-work-tabs button{min-height:48px}}
      `}</style>
    </div>
  );

  return (
    <>
      <SEO title="Pay & Flow"
        description="Collect, Vault and Contribute: Display, Create and Ledger." noindex />
      <PageShell key={`${section}-${tab}`} className="payments-shell"
        title="Pay & Flow"
        subtitle="One workspace for payment creation, verified Vault delivery and collection records."
        tabs={[]} navigation={nav}
      >
        {() => (
          <>
            {section === 'collect' && tab === 'display' && <CollectOverview />}
            {section === 'collect' && tab === 'create' && (
              <section aria-label="Collect payment creation">
                {legacy === 'defaults' ? (
                  <>
                    <div className="pay-context-link">
                      <Link href="/workspace/payments?view=collect&tab=create">Back to Collect Create</Link>
                    </div>
                    <DefaultInvoiceItems onUse={useDefaultItem} />
                  </>
                ) : (
                  <>
                    <div className="pay-context-link">
                      <Link href="/workspace/payments?view=defaults">Default invoice items and pricing presets</Link>
                    </div>
                    <PayFlowPage signOut={signOut} user={user} embedded mode="collect" />
                  </>
                )}
              </section>
            )}
            {section === 'vault' && tab === 'display' && (
              <VaultWorkbench signOut={signOut} user={user} embedded workspaceView="display" />
            )}
            {section === 'vault' && tab === 'create' && (
              legacy === 'timing' ? (
                <section aria-label="Vault access delay settings">
                  <VaultDeliveryTiming />
                </section>
              ) : (
                <VaultWorkbench signOut={signOut} user={user} embedded workspaceView="create" />
              )
            )}
            {section === 'contribute' && tab === 'display' && (
              <ContributePaymentPlan workspaceView="display" />
            )}
            {section === 'contribute' && tab === 'create' && (
              <ContributePaymentPlan workspaceView="create" />
            )}
            {section === 'vault' && tab === 'ledger' && (
              <section className="pay-ledger-scoped" aria-label="Vault ledger">
                <InvoiceRecords signOut={signOut} user={user} embedded serviceKind="VAULT" />
              </section>
            )}
            {section === 'contribute' && tab === 'ledger' && (
              <section className="pay-contribute-ledger" aria-labelledby="contribute-ledger-heading">
                <p className="pay-contribute-kicker">CONTRIBUTE / LEDGER</p>
                <h2 id="contribute-ledger-heading">Contribution payment records</h2>
                <p>Contribute is a catalog-order payment, not a Vault-style request-service
                  purchase. Its money and receipt evidence stay in the existing Commerce
                  order, payment and invoice records. A name or amount alone is not verified
                  proof that an invoice belongs to a contribution.</p>
                <div className="pay-contribute-ledger-links">
                  <Link href="/workspace/service?view=contribute&tab=payments">
                    Existing Contribute records
                  </Link>
                  <Link href="/workspace/commerce?view=orders">Staff orders</Link>
                  <Link href="/workspace/payments?view=ledger&ledger=invoices">
                    All invoice records
                  </Link>
                  <Link href="/workspace/payments?view=ledger&ledger=activity">
                    Payment activity
                  </Link>
                </div>
                <p className="pay-contribute-note">
                  No separate contribution ledger or unsupported invoice service filter is
                  created. Verify the catalog order reference and provider capture before
                  marking a contribution received.
                </p>
              </section>
            )}
            {section === 'collect' && tab === 'ledger' && (
              <section className="ledger" aria-label="Invoice and payment ledger">
                <div className="ledger-switch" role="group" aria-label="Ledger view">
                  <button type="button" className={ledgerView === 'invoices' ? 'active' : ''}
                    aria-pressed={ledgerView === 'invoices'}
                    onClick={() => goLedger('invoices')}>Invoices</button>
                  <button type="button" className={ledgerView === 'activity' ? 'active' : ''}
                    aria-pressed={ledgerView === 'activity'}
                    onClick={() => goLedger('activity')}>Activity</button>
                  <label htmlFor="pay-service-ledger">Service ledger</label>
                  <select id="pay-service-ledger" aria-label="Select service ledger"
                    value={serviceLedger?.slug || ''}
                    onChange={event => {
                      const choice = SERVICE_CHOICES.find(item => item.slug === event.target.value);
                      if (choice) goLedger(choice.slug);
                      else goLedger('invoices');
                    }}>
                    <option value="">All services</option>
                    {SERVICE_CHOICES.map(choice => (
                      <option key={choice.kind} value={choice.slug}>{choice.label}</option>
                    ))}
                  </select>
                </div>
                {ledgerView === 'invoices'
                  ? <PayFlowPage signOut={signOut} user={user} embedded mode="invoices" />
                  : serviceLedger
                    ? <InvoiceRecords signOut={signOut} user={user} embedded
                        serviceKind={serviceLedger.kind} />
                    : <PaymentsActivity />}
              </section>
            )}
          </>
        )}
      </PageShell>
      <style jsx>{`
        .pay-context-link{display:flex;justify-content:flex-end;margin:5px 0 10px}
        .pay-context-link :global(a){border:1px solid var(--border);border-radius:10px;display:inline-flex;align-items:center;min-height:44px;padding:10px 15px;text-decoration:none;color:var(--text-primary);font-weight:750;font-size:12px}
        .pay-context-link :global(a:focus-visible){outline:3px solid var(--accent);outline-offset:2px}
        .pay-ledger-scoped{min-width:0}
        .pay-contribute-ledger{display:grid;gap:13px;max-width:960px;min-width:0;padding:10px 0 32px}
        .pay-contribute-kicker{color:var(--text-muted);font-weight:800;letter-spacing:.08em;font-size:11px;margin:0}
        .pay-contribute-ledger h2{font-size:clamp(23px,3vw,30px);color:var(--text-primary);margin:0}
        .pay-contribute-ledger p:not(.pay-contribute-kicker){color:var(--text-muted);font-size:13px;line-height:1.6;max-width:780px;margin:0}
        .pay-contribute-ledger-links{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
        .pay-contribute-ledger-links :global(a){min-height:52px;display:flex;align-items:center;padding:12px 16px;border:1px solid var(--border);border-radius:12px;color:var(--text-primary);background:var(--surface);font-size:13px;font-weight:750;text-decoration:none}
        .pay-contribute-ledger-links :global(a:hover){border-color:var(--accent)}
        .pay-contribute-ledger-links :global(a:focus-visible){outline:3px solid var(--accent);outline-offset:2px}
        @media(max-width:720px){.pay-contribute-ledger-links{grid-template-columns:1fr}}
      `}</style>
    </>
  );
};

export default PaymentsPage;
