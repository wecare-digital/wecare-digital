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

interface PageProps { signOut?: () => void; user?: any; }

const TABS: ShellTab[] = [
  { id: 'collect', label: 'Collect' },
  { id: 'ledger', label: 'Ledger', divider: true },
];

type PaymentsView = 'collect' | 'ledger';
type LedgerView = 'invoices' | 'activity';

function one ( raw: string | string[] | undefined ): string {
  return Array.isArray( raw ) ? ( raw[ 0 ] || '' ) : ( raw || '' );
}

function mode ( raw: string | string[] | undefined ): PaymentsView {
  return one( raw ) === 'collect' ? 'collect' : 'ledger';
}

function ledgerMode ( rawView: string | string[] | undefined, rawLedger: string | string[] | undefined ): LedgerView {
  if ( one( rawView ) === 'activity' || one( rawLedger ) === 'activity' ) return 'activity';
  return 'invoices';
}

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
            query: view === 'ledger' ? { view: 'ledger', ledger: 'invoices' } : { view: 'collect' },
          } );
        } }
      >
        { ( tab ) => (
          <>
            { tab === 'collect' && <PayFlowPage signOut={ signOut } user={ user } embedded mode="collect" /> }
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
