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
import InvoiceRecords from '../../../components/workspace/pay/InvoiceRecords';
import PaymentTemplateMedia from '../../../components/workspace/pay/PaymentTemplateMedia';
import { SERVICE_CHOICES, type ServiceChoice, type ServiceSlug } from '../../../config/services';
import { fetchServicePrices, rupeesFromPaise, type ServicePrice } from '../../../lib/servicePricing';

interface PageProps { signOut?: () => void; user?: any; }

const PaymentFramework = dynamic(() => import('../../../components/workspace/pay/PaymentFramework'), {ssr: false});
const VaultWorkbench = dynamic( () => import('../../../components/workspace/pay/VaultWorkbench'), { ssr: false } );
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
 * The bare canonical page opens the live Collect workbench.
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
  return {section: 'collect', tab: 'create', legacy: null};
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
  const showFramework = one(router.query.panel) === 'framework';
  const ledgerView = ledgerMode(router.query.view, router.query.ledger);
  const serviceLedger = SERVICE_CHOICES.find(choice => choice.slug === ledgerView);

  const navigate = (query: Record<string, string>) => {
    void router.push({pathname: '/workspace/payments', query});
  };
  const changeSection = (next: PaymentSection) => {
    // Open the live workbench immediately; preserve the message inspector when selected.
    navigate({view: next, tab: showFramework ? 'display' : 'create', ...(showFramework ? {panel: 'framework'} : {})});
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

  const nav = <nav className="payment-rail" aria-label="Payment sections">
    <p className="rail-label">PAYMENTS</p>
    {SECTION_OPTIONS.map(option=><button type="button" key={option.value} aria-pressed={section===option.value} onClick={()=>changeSection(option.value)}><strong>{option.label}</strong><small>{option.value==='collect'?'Invoices & collections':option.value==='vault'?'Files & paid access':'₹300 contribution'}</small></button>)}
    <div className="rail-help"><strong>One customer. One request.</strong><p>Review the customer and total before confirming a WhatsApp send.</p></div>
  </nav>;

  return (
    <>
      <SEO title="Pay & Flow"
        description="Collect, Vault and Contribute: Display, Create and Ledger." noindex />
      <PageShell key={`${section}-${tab}`} className="payments-shell"
        title="Pay & Flow"
        subtitle="Choose a customer, review the total and send an approved payment request."
        tabs={[]} showChrome={false}
      >
        {() => (
          <div className="payment-console">
            <header className="console-header"><div><p>WORKSPACE</p><h1>Payments</h1></div><span>Live customer records · approved WhatsApp payments</span></header>
            <div className="console-layout"><aside>{nav}</aside><div className="console-main">
            <nav className="console-tools" aria-label="Payment tools">
              <Link className={!showFramework && tab!=='ledger'?'current':''} href={{pathname:'/workspace/payments',query:{view:section,tab:'create'}}}>Workspace</Link>
              <Link className={!showFramework && tab==='ledger'?'current':''} href={{pathname:'/workspace/payments',query:{view:section,tab:'ledger'}}}>Records</Link>
              <Link className={showFramework?'current':''} href={{pathname:'/workspace/payments',query:{view:section,tab:'display',panel:'framework'}}}>Messages &amp; timing</Link>
            </nav>
            {showFramework ? <PaymentFramework section={section} /> : <>
            {section === 'collect' && tab === 'display' && <PayFlowPage signOut={signOut} user={user} embedded mode="collect" />}
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
                    <nav className="pay-collect-create-links" aria-label="Collect creation tools">
                      <Link href="/workspace/payments?view=collect&tab=create">
                        Compose new invoice
                      </Link>
                      <Link href="/workspace/payments?view=collect&tab=create&invoices=saved">
                        Saved invoices · Review &amp; send
                      </Link>
                      <Link href="/workspace/payments?view=defaults">
                        Default invoice items and pricing presets
                      </Link>
                    </nav>
                    {one(router.query.invoices) === 'saved'
                      ? <PayFlowPage key="saved-invoices" signOut={signOut} user={user} embedded
                          mode="invoices" allowSendInInvoices />
                      : <PayFlowPage key="create-invoice" signOut={signOut} user={user}
                          embedded mode="collect" />}
                  </>
                )}
              </section>
            )}
            {section === 'vault' && tab === 'display' && (
              <VaultWorkbench signOut={signOut} user={user} embedded workspaceView="create" />
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
                <nav className="pay-collect-create-links" aria-label="Vault ledger records">
                  <Link href="/workspace/payments?view=vault&tab=ledger"
                    aria-current={one(router.query.records) !== 'files' ? 'page' : undefined}>
                    Vault invoices
                  </Link>
                  <Link href="/workspace/payments?view=vault&tab=ledger&records=files"
                    aria-current={one(router.query.records) === 'files' ? 'page' : undefined}>
                    File and delivery history
                  </Link>
                </nav>
                {one(router.query.records) === 'files'
                  ? <VaultWorkbench key="vault-history" embedded workspaceView="display" initialHistorical />
                  : <InvoiceRecords signOut={signOut} user={user} embedded serviceKind="VAULT" />}
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
            </>}
            </div></div>
          </div>
        )}
      </PageShell>
      <style jsx>{`
        .payment-console{width:100%;min-width:0;padding:22px 0 40px}.console-header{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:0 0 22px;border-bottom:1px solid var(--border);margin-bottom:22px}.console-header p,.rail-label{font-size:10px;letter-spacing:.14em;font-weight:750;color:var(--text-muted);margin:0 0 5px}.console-header h1{font-size:30px;line-height:1.1;margin:0}.console-header>span{font-size:12px;color:var(--text-muted)}.console-layout{display:grid;grid-template-columns:200px minmax(0,1fr);gap:30px;align-items:start}.console-main{min-width:0}.console-tools{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 24px;border-bottom:1px solid var(--border);padding-bottom:10px}.console-tools :global(a){display:inline-flex;align-items:center;min-height:42px;padding:9px 15px;text-decoration:none;font-size:13px;color:var(--text-muted);border-radius:8px}.console-tools :global(a.current){color:var(--text-primary);background:var(--bg-secondary);font-weight:750}.payment-rail{display:grid;gap:8px}.payment-rail button{display:grid;gap:4px;text-align:left;border:1px solid transparent;padding:14px;border-radius:12px;min-height:66px;color:var(--text-primary);background:transparent;cursor:pointer;font:inherit}.payment-rail button[aria-pressed=true]{background:var(--lime);border-color:var(--accent)}.payment-rail small{font-size:11px;color:var(--text-muted)}.rail-help{margin-top:28px;padding-top:18px;border-top:1px solid var(--border)}.rail-help strong{font-size:12px}.rail-help p{font-size:12px;color:var(--text-muted);line-height:1.6}.console-tools :global(a:focus-visible),.payment-rail button:focus-visible{outline:3px solid var(--accent);outline-offset:2px}@media(max-width:900px){.console-layout{grid-template-columns:1fr;gap:18px}.payment-rail{grid-template-columns:repeat(3,minmax(0,1fr));gap:6px}.rail-label,.rail-help{display:none}.payment-rail button{padding:12px;min-height:58px}.console-header>span{display:none}.console-tools{margin-bottom:18px}.console-header{margin-bottom:16px;padding-bottom:16px}}@media(max-width:430px){.payment-rail button{padding:10px 7px}.payment-rail small{font-size:10px}.console-tools :global(a){padding:8px 10px;font-size:12px}}

        .pay-collect-create-links{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin:8px 0 16px}
        .pay-collect-create-links :global(a){display:inline-flex;align-items:center;min-height:44px;border:1px solid var(--border);border-radius:10px;padding:10px 14px;background:var(--surface);color:var(--text-primary);font-size:12px;font-weight:750;text-decoration:none}
        .pay-collect-create-links :global(a:focus-visible){outline:3px solid var(--accent);outline-offset:2px}
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
