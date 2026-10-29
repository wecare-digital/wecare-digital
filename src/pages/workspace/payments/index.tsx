/**
 * Canonical Payments workspace.
 *
 * Product rule: daily payment work has two primary modes.
 * - Collect: create a server-authoritative invoice/payment request.
 * - Ledger: inspect invoice records, delivery evidence and latest stored payment state.
 *
 * The proven PayFlow and InvoiceRecords components are reused first; their old /workspace/pay
 * wrapper becomes a compatibility redirect after this page lands.
 */
import React from 'react';
import { useRouter } from 'next/router';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import PageShell, { ShellTab } from '../../../components/PageShell';
import PayFlowPage from '../../../components/workspace/pay/PayFlow';
import PaymentsActivity from '../../../components/workspace/pay/PaymentsActivity';
import { SERVICE_CHOICES, type ServiceChoice } from '../../../config/services';
import { fetchServicePrices, rupeesFromPaise, type ServicePrice } from '../../../lib/servicePricing';

interface PageProps { signOut?: () => void; user?: any; }

const TABS: ShellTab[] = [
  { id: 'collect', label: 'Collect' },
  { id: 'defaults', label: 'Default invoice items' },
  { id: 'ledger', label: 'Ledger', divider: true },
];

type PaymentsView = 'collect' | 'defaults' | 'ledger';
type LedgerView = 'invoices' | 'activity';

function one ( raw: string | string[] | undefined ): string {
  return Array.isArray( raw ) ? ( raw[ 0 ] || '' ) : ( raw || '' );
}

function mode ( raw: string | string[] | undefined ): PaymentsView {
  const value = one( raw );
  if ( value === 'collect' ) return 'collect';
  if ( value === 'defaults' ) return 'defaults';
  return 'ledger';
}

function ledgerMode ( rawView: string | string[] | undefined, rawLedger: string | string[] | undefined ): LedgerView {
  if ( one( rawView ) === 'activity' || one( rawLedger ) === 'activity' ) return 'activity';
  return 'invoices';
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

  return (
    <section className="default-items" aria-label="Default invoice items">
      <div className="default-items-head">
        <div>
          <div className="default-items-kicker">Server-priced presets</div>
          <h2>Default invoice items</h2>
          <p>Vault, Drop Docs and request services use live ProductsTable pricing. Use a row to open Collect with that service already loaded.</p>
        </div>
        <span>{ loading ? 'Loading live prices' : 'Live catalog' }</span>
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
                      Use
                    </button>
                  </td>
                </tr>
              );
            } ) }
          </tbody>
        </table>
      </div>
    </section>
  );
};

const PaymentsPage: React.FC<PageProps> = ( { signOut, user } ) => {
  const router = useRouter();
  const active = mode( router.query.view );
  const ledgerView = ledgerMode( router.query.view, router.query.ledger );

  const goLedger = ( next: LedgerView ) => {
    const query: Record<string, string> = { view: 'ledger', ledger: next };
    const invoice = one( router.query.invoice );
    if ( invoice && next === 'invoices' ) query.invoice = invoice;
    void router.push( { pathname: '/workspace/payments', query } );
  };

  return (
    <Layout user={ user } onSignOut={ signOut }>
      <SEO title="Payments" description="Collect payments and review the authoritative payment ledger." noindex />
      <PageShell
        key={ active }
        title="Payments"
        subtitle="Collect through the invoice engine, then use one ledger for invoices, delivery evidence and payment state."
        tabs={ TABS }
        activeTab={ active }
        defaultTab={ active }
        onTabChange={ next => {
          const view = mode( next );
          void router.push( {
            pathname: '/workspace/payments',
            query: view === 'ledger'
              ? { view: 'ledger', ledger: 'invoices' }
              : view === 'defaults'
                ? { view: 'defaults' }
                : { view: 'collect' },
          } );
        } }
      >
        { ( tab ) => (
          <>
            { tab === 'collect' && <PayFlowPage signOut={ signOut } user={ user } embedded mode="collect" /> }
            { tab === 'defaults' && (
              <DefaultInvoiceItems onUse={ choice => {
                void router.push( {
                  pathname: '/workspace/payments',
                  query: { view: 'collect', preset: choice.slug },
                } );
              } } />
            ) }
            { tab === 'ledger' && (
              <section className="ledger" aria-label="Payment ledger">
                <div className="ledger-switch" role="group" aria-label="Ledger view">
                  <button type="button" className={ ledgerView === 'invoices' ? 'active' : '' }
                    aria-pressed={ ledgerView === 'invoices' } onClick={ () => goLedger( 'invoices' ) }>
                    Invoices
                  </button>
                  <button type="button" className={ ledgerView === 'activity' ? 'active' : '' }
                    aria-pressed={ ledgerView === 'activity' } onClick={ () => goLedger( 'activity' ) }>
                    Activity
                  </button>
                </div>
                { ledgerView === 'invoices'
                  ? <PayFlowPage signOut={ signOut } user={ user } embedded mode="invoices" />
                  : <PaymentsActivity /> }
              </section>
            ) }
          </>
        ) }
      </PageShell>
      <style jsx>{`
        .default-items{min-width:0;padding:18px 0 8px}
        .default-items-head{display:flex;align-items:flex-start;justify-content:space-between;gap:24px;margin-bottom:22px;padding:24px 26px;border-radius:22px;background:#fff;box-shadow:0 14px 38px rgba(26,58,42,.07)}
        .default-items-head:before{content:"";position:absolute}
        .default-items-head h2{margin:4px 0 8px;color:#1a3a2a;font-size:clamp(30px,3vw,46px);line-height:1;letter-spacing:-.05em}
        .default-items-head p{max-width:760px;margin:0;color:#6e7782;font-size:14px;line-height:1.55}
        .default-items-kicker{color:#1a3a2a;font-size:11px;font-weight:800;letter-spacing:.09em;text-transform:uppercase}
        .default-items-head>span{flex:0 0 auto;padding:7px 11px;border-radius:999px;background:#d1f470;color:#1a3a2a;font-size:11px;font-weight:800}
        .default-items-table-wrap{overflow-x:auto;border-radius:22px;background:#fff;box-shadow:0 16px 40px rgba(26,58,42,.07)}
        .default-items-table{width:100%;min-width:880px;border-collapse:collapse;font-size:13px}
        .default-items-table th,.default-items-table td{padding:14px 16px;text-align:left;border-bottom:1px solid #edf0ed;white-space:nowrap}
        .default-items-table th{background:#f8faf3;color:#66716c;font-size:11px;text-transform:uppercase;letter-spacing:.04em}
        .default-items-table tbody tr:last-child td{border-bottom:0}
        .default-items-table td:first-child{white-space:normal;min-width:180px}
        .default-items-table td:first-child strong,.default-items-table td:first-child small{display:block}
        .default-items-table td:first-child small{margin-top:3px;color:#8a9490;font-size:10px}
        .default-items-table button{min-height:38px;padding:8px 14px;border:0;border-radius:12px;background:#d1f470;color:#1a3a2a;font:inherit;font-weight:800;cursor:pointer}
        .default-items-table button:disabled{opacity:.45;cursor:not-allowed}
        .ledger{min-width:0}
        .ledger-switch{display:inline-flex;gap:4px;margin:0 0 16px;padding:4px;border:1px solid var(--border);border-radius:12px;background:var(--bg-secondary)}
        .ledger-switch button{min-height:44px;padding:8px 14px;border:0;border-radius:9px;background:transparent;color:var(--text-muted);font:inherit;font-weight:650;cursor:pointer}
        .ledger-switch button.active{background:#fff;color:var(--text);box-shadow:0 1px 2px rgba(0,0,0,.06)}
        .ledger-switch button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
        @media(max-width:520px){.ledger-switch{display:grid;grid-template-columns:1fr 1fr;width:100%;box-sizing:border-box}.ledger-switch button{width:100%}}
        @media(forced-colors:active){.ledger-switch{border-color:CanvasText}.ledger-switch button.active{outline:1px solid CanvasText}}
      `}</style>
    </Layout>
  );
};

export default PaymentsPage;
