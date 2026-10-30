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
import Header from '../../../components/Header';
import Footer from '../../../components/Footer';
import PublicShare from '../../../components/PublicShare';
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
      <div className="default-items-panel">
      <div className="default-items-head">
        <div>
          <div className="default-items-kicker">Server-priced presets</div>
          <h2>Default invoice items</h2>
          <p>Vault, Drop Docs and request services use live server pricing. Use a row to open Collect with that service already loaded.</p>
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
                      Use
                    </button>
                  </td>
                </tr>
              );
            } ) }
          </tbody>
        </table>
      </div>
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
    <>
      <SEO title="Payments" description="Collect payments and review the authoritative payment ledger." noindex />
      { /*
          Payments is a deliberate authenticated exception to the normal Workspace chrome.
          The owner asked for the same public shell as /auth: the real Header/navigation,
          Stay connected dock and Footer. We therefore do NOT render Layout here; two fixed
          headers would collide. The structural .layout/.workspace-shell classes are retained
          so existing payment styling and SupportWidget's authenticated translation boundary
          still work. The operational surface stays data-wc-no-translate so customer names,
          numbers, addresses and invoice details are never machine-translated.
        */ }
      <div className="layout workspace-shell payments-public-layout">
        <Header />

        <main id="main-content" className="main-content workspace-main payments-public-main" data-wc-no-translate="true">
          <div className="inner-content-container">
            <PageShell
              key={ active }
              className="payments-shell"
              title="Payments"
              subtitle="Collect through the invoice engine, then use one ledger for invoices, delivery evidence and payment state."
              tabs={ TABS }
              activeTab={ active }
              defaultTab={ active }
              actions={
                <div className="payments-public-actions">
                  <button type="button" onClick={ () => void router.push( '/workspace/' ) }>Workspace</button>
                  { signOut && <button type="button" onClick={ signOut }>Sign out</button> }
                </div>
              }
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
          </div>
        </main>

        <div className="payments-public-action-tail">
          <PublicShare />
        </div>
        <Footer />

        <style jsx>{`
          .payments-public-layout{
            display:block;
            min-height:100vh;
            min-height:100dvh;
            background:var(--public-bg,#fff);
            color:var(--public-text,#111);
            font-family:var(--font-sans);
          }
          .payments-public-main{
            width:100%;
            max-width:none;
            min-width:0;
            min-height:calc(100vh - 108px);
            min-height:calc(100dvh - 108px);
            margin:0;
            padding:108px 0 0;
            box-sizing:border-box;
            overflow-x:hidden;
            overflow-x:clip;
            overflow-y:visible;
            background:#fff;
          }
          .payments-public-actions{
            display:flex;
            align-items:center;
            justify-content:flex-end;
            flex-wrap:wrap;
            gap:8px;
          }
          .payments-public-actions button{
            padding:8px 12px;
            border:0;
            border-radius:10px;
            background:var(--public-lime-tint,#f8faf3);
            color:var(--public-brand-green,#1a3a2a);
            font:600 var(--public-supporting-size,16px)/1.3 var(--font-sans);
            text-decoration:underline;
            text-decoration-thickness:1.5px;
            text-underline-offset:4px;
            cursor:pointer;
            transition:background-color .18s,transform .18s,box-shadow .18s,text-decoration-color .18s;
          }
          .payments-public-actions button:hover{
            background:var(--public-brand-lime,#d1f470);
            transform:translateY(-1px);
            box-shadow:var(--public-lift-shadow);
            text-decoration-color:transparent;
          }
          .payments-public-actions button:focus-visible{
            outline:2px solid var(--public-brand-green,#1a3a2a);
            outline-offset:2px;
          }
          .payments-public-action-tail{
            width:100%;
            max-width:var(--public-content-max);
            min-width:0;
            margin:0 auto;
            padding:8px var(--public-page-gutter) 48px;
            overflow-x:hidden;
            overflow-x:clip;
            box-sizing:border-box;
            font-family:var(--font-sans);
            color:var(--public-text);
          }
          @media(max-width:767px){
            .payments-public-main{
              min-height:calc(100vh - 96px);
              min-height:calc(100dvh - 96px);
              padding-top:96px;
            }
            .payments-public-actions{
              width:100%;
              display:grid;
              grid-template-columns:1fr 1fr;
            }
            .payments-public-actions button{width:100%}
            .payments-public-action-tail{
              padding-inline:var(--public-mobile-page-gutter);
              padding-bottom:40px;
            }
          }
          @media(max-width:480px){
            .payments-public-actions{grid-template-columns:1fr}
          }
        `}</style>
      </div>
      { /*
          SupportWidget is intentionally not mounted here. _app.tsx already mounts the one
          authenticated WhatsApp + language widget after this page, and its contentRoot()
          resolves to the .layout above. Duplicating it would create two fixed support pills.
        */ }
    </>
  );
};

export default PaymentsPage;
