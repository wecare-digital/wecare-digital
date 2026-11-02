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
import InvoiceRecords from '../../../components/workspace/pay/InvoiceRecords';
import FixedInvoiceItems from '../../../components/workspace/pay/FixedInvoiceItems';
import UnifiedPaymentWorkspace from '../../../components/workspace/pay/UnifiedPaymentWorkspace';
import { SERVICE_CHOICES, type ServiceSlug } from '../../../config/services';

interface PageProps { signOut?: () => void; user?: any; }

const PaymentFramework = dynamic(() => import('../../../components/workspace/pay/PaymentFramework'), {ssr: false});
const VaultDeliveryTiming = dynamic( () => import('../../../components/workspace/pay/VaultDeliveryTiming'), { ssr: false } );

type PaymentSection = 'collect' | 'vault' | 'contribute';
type PaymentTab = 'display' | 'create' | 'ledger';
type LedgerView = 'invoices' | 'activity' | ServiceSlug;
type LegacyPanel = 'defaults' | 'timing' | null;

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

const PaymentsPage: React.FC<PageProps> = ({signOut, user}) => {
  const router = useRouter();
  const location = resolvePaymentsLocation(
    router.query.view, router.query.tab, router.query.ledger, router.query.section,
  );
  const {section, tab, legacy} = location;
  const showFramework = one(router.query.panel) === 'framework';





  return (
    <>
      <SEO title="Payments"
        description="Live invoices, Vault delivery and contributions." noindex />
      <PageShell key={`payments-${tab}`} className="payments-shell"
        title="Payments"
        subtitle="Choose a customer, review the total and send an approved payment request."
        tabs={[]} showChrome={false}
      >
        {() => (
          <div className="payment-console">
            <header className="console-header"><div><p>WORKSPACE</p><h1>Payments</h1></div></header>
            <div className="console-layout"><div className="console-main">
            <nav className="console-tools" aria-label="Payment tools">
              <Link className={!showFramework && legacy!=='defaults' && tab!=='ledger'?'current':''} href={{pathname:'/workspace/payments',query:{view:'collect',tab:'create',...(one(router.query.item)?{item:one(router.query.item)}:{})}}}>Workspace</Link>
              <Link className={!showFramework && tab==='ledger'?'current':''} href={{pathname:'/workspace/payments',query:{view:section,tab:'ledger'}}}>Records</Link>
              <Link className={legacy==='defaults'?'current':''} href="/workspace/payments?view=defaults">Invoice items (29)</Link>
              <Link className={showFramework?'current':''} href={{pathname:'/workspace/payments',query:{view:section,tab:'display',panel:'framework',...(one(router.query.item)?{item:one(router.query.item)}:{})}}}>Messages &amp; timing</Link>
            </nav>
            {showFramework ? <PaymentFramework section={section} /> :
              tab === 'ledger' ? <InvoiceRecords signOut={signOut} user={user} embedded /> :
                legacy === 'defaults' ? <FixedInvoiceItems /> :
                  legacy === 'timing' ? <VaultDeliveryTiming /> :
                    <UnifiedPaymentWorkspace signOut={signOut} user={user} />}
            </div></div>
          </div>
        )}
      </PageShell>
      <style jsx>{`
        .payment-console{width:100%;min-width:0;padding:22px 0 40px}
        .console-header{display:flex;align-items:center;justify-content:space-between;gap:24px;padding:0 0 22px;border-bottom:1px solid var(--border);margin-bottom:22px}
        .console-header p{font-size:10px;letter-spacing:.14em;font-weight:750;color:var(--text-muted);margin:0 0 5px}.console-header h1{font-size:30px;line-height:1.1;margin:0}
        .payment-type-picker{display:grid;gap:7px;min-width:240px;font-size:12px;font-weight:650;color:var(--text-muted)}
        .payment-type-picker select{width:100%;min-height:46px;padding:10px 36px 10px 14px;border:1px solid var(--border);border-radius:10px;background:var(--surface);font:inherit;font-size:15px;font-weight:650;color:var(--text-primary);cursor:pointer}
        .payment-type-picker select:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
        .console-layout,.console-main{width:100%;min-width:0}
        .console-tools{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 24px;border-bottom:1px solid var(--border);padding-bottom:10px}.console-tools :global(a){display:inline-flex;align-items:center;min-height:42px;padding:9px 15px;text-decoration:none;font-size:13px;color:var(--text-muted);border-radius:8px}.console-tools :global(a.current){color:var(--text-primary);background:var(--bg-secondary);font-weight:750}.console-tools :global(a:focus-visible){outline:3px solid var(--accent);outline-offset:2px}
        @media(max-width:600px){.console-header{align-items:stretch;flex-direction:column;gap:18px;margin-bottom:16px;padding-bottom:16px}.payment-type-picker{min-width:0}.console-tools{margin-bottom:18px}}
        @media(max-width:430px){.console-tools :global(a){padding:8px 10px;font-size:12px}}


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
