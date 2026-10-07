/**
 * Invoice records — the payment ledger, read-only.
 *
 * WHY READ-ONLY IS THE POINT
 * --------------------------
 * `api` exposes plenty of mutating invoice calls: `cancelInvoice`,
 * `deleteInvoice`, `updateInvoiceEngine`, `sendInvoiceWhatsApp`, `sendPaymentLink`.
 * None of them is wired here, deliberately.
 *
 * This page's job is to answer "what was billed, was it paid, and what was sent to
 * whom". Every one of those mutations either moves money, messages a customer, or
 * renumbers an invoice sequence — and `deleteInvoice` takes an `adjustSequence`
 * flag, meaning a mis-click can renumber a statutory GST series. A records screen
 * that can silently do that is not a records screen.
 *
 * So: read, filter, and open the delivery log. Sending and cancelling stay on the
 * surfaces built for them, where the confirmation is part of the flow.
 *
 * WHAT IS REAL HERE. `listInvoicesEngine` is a live API with `status`, `contactId`
 * and `paymentId` filters, and `Invoice` carries the full GST breakdown — subtotal,
 * discount, shipping, gstRate, tax, convenienceFee, total. `getInvoiceDeliveryLog`
 * is also real, which is why the delivery drawer exists rather than being promised.
 *
 * Money is rendered from the stored `currency` and never re-computed. The invoice is
 * the record; recomputing a total in the browser would invent a second answer to a
 * question that already has one, and the two would disagree the first time a rounding
 * rule changed.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import Button from '../../../components/ui/Button';
import Pagination from '../../../components/ui/Pagination';
import Select, { type SelectOption } from '../../../components/ui/Select';
import { useToastContext } from '../../../contexts/ToastContext';
import * as api from '../../../api/client';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const PER_PAGE = 25;

// Paint drawn from the repo's own semantic scale: --success, --warning, --danger.
const PAID: Record<string, { bg: string; fg: string }> = {
  captured: { bg: '#f0fdf4', fg: '#15803d' },
  paid: { bg: '#f0fdf4', fg: '#15803d' },
  pending: { bg: '#fffbeb', fg: '#b45309' },
  failed: { bg: '#fef2f2', fg: '#b91c1c' },
  refunded: { bg: '#eff6ff', fg: '#1d4ed8' },
  cancelled: { bg: '#f9fafb', fg: 'rgba(0,0,0,.54)' },
};

const paint = ( s?: string ) =>
  PAID[ ( s || '' ).toLowerCase() ] || { bg: '#f9fafb', fg: 'rgba(0,0,0,.54)' };

/**
 * Money, from the invoice's own currency field.
 *
 * Falls back to INR rather than to a bare number: an amount with no currency beside
 * it is the kind of ambiguity that gets read as the wrong figure, and every invoice
 * in this system is raised in one.
 */
function money ( amount?: number, currency?: string ): string {
  const value = typeof amount === 'number' && Number.isFinite( amount ) ? amount : 0;
  try
  {
    return new Intl.NumberFormat( 'en-IN', {
      style: 'currency', currency: currency || 'INR', maximumFractionDigits: 2,
    } ).format( value );
  } catch
  {
    // An unknown currency code throws rather than degrading, so say the code.
    return `${currency || 'INR'} ${value.toFixed( 2 )}`;
  }
}

const InvoiceRecordsPage: React.FC<PageProps> = ( { signOut, user, embedded } ) => {
  const toast = useToastContext();
  const [ invoices, setInvoices ] = useState<api.Invoice[]>( [] );
  const [ loading, setLoading ] = useState( true );
  const [ statusFilter, setStatusFilter ] = useState( 'all' );
  const [ search, setSearch ] = useState( '' );
  const [ page, setPage ] = useState( 1 );
  const [ openLog, setOpenLog ] = useState<string | null>( null );
  const [ logs, setLogs ] = useState<api.InvoiceDeliveryLog[]>( [] );
  const [ logLoading, setLogLoading ] = useState( false );

  const load = useCallback( async () => {
    setLoading( true );
    try
    {
      // No status passed: filtering happens client-side so switching filters does
      // not re-hit the API on every keystroke of a 2,000-row ledger.
      const r = await api.listInvoicesEngine( { limit: 2000 } );
      setInvoices( r.invoices || [] );
    } catch
    {
      toast.error( 'Could not load invoice records' );
    } finally
    {
      setLoading( false );
    }
  }, [ toast ] );

  useEffect( () => { load(); }, [ load ] );
  useEffect( () => { setPage( 1 ); }, [ statusFilter, search ] );

  const statuses = useMemo( () => {
    const set = new Set<string>();
    invoices.forEach( ( i ) => {
      if ( i.paymentStatus ) set.add( i.paymentStatus.toLowerCase() );
    } );
    return Array.from( set ).sort();
  }, [ invoices ] );

  /*
   * The filter's rows, derived from the statuses actually present in the loaded page - the
   * same list the <option> rows were built from, in the same order, with 'all' first. The
   * spellings come from the records themselves and are deliberately not canonicalised here:
   * `lambda_utils/payment_status.py` owns the paid-versus-captured vocabulary on the server,
   * and a browser filter that rewrote a stored spelling would hide rows rather than filter
   * them.
   */
  const statusOptions: SelectOption[] = useMemo( () => [
    { value: 'all', label: 'All' },
    ...statuses.map( ( s ) => ( { value: s, label: s } ) ),
  ], [ statuses ] );

  const filtered = useMemo( () => {
    const q = search.trim().toLowerCase();
    return invoices.filter( ( i ) => {
      if ( statusFilter !== 'all'
        && ( i.paymentStatus || '' ).toLowerCase() !== statusFilter ) return false;
      if ( !q ) return true;
      return [ i.invoiceNumber, i.customerName, i.customerPhone, i.customerEmail,
        i.orderId, i.invoiceId ]
        .some( ( f ) => String( f || '' ).toLowerCase().includes( q ) );
    } );
  }, [ invoices, statusFilter, search ] );

  const totals = useMemo( () => {
    // Summed from the stored totals, never recomputed from line items - the invoice
    // is the record, and a second calculation is a second answer.
    const paidRows = filtered.filter( ( i ) =>
      [ 'captured', 'paid' ].includes( ( i.paymentStatus || '' ).toLowerCase() ) );
    const sum = ( rows: api.Invoice[] ) =>
      rows.reduce( ( n, i ) => n + ( Number( i.total ) || 0 ), 0 );
    return {
      count: filtered.length,
      billed: sum( filtered ),
      collected: sum( paidRows ),
      tax: filtered.reduce( ( n, i ) => n + ( Number( i.tax ) || 0 ), 0 ),
      currency: filtered[ 0 ]?.currency || 'INR',
    };
  }, [ filtered ] );

  const totalPages = Math.max( 1, Math.ceil( filtered.length / PER_PAGE ) );
  const rows = filtered.slice( ( page - 1 ) * PER_PAGE, page * PER_PAGE );

  const showLog = useCallback( async ( invoiceId: string ) => {
    if ( openLog === invoiceId ) { setOpenLog( null ); return; }
    setOpenLog( invoiceId );
    setLogLoading( true );
    setLogs( [] );
    try
    {
      const r = await api.getInvoiceDeliveryLog( invoiceId );
      setLogs( r.deliveryLogs || [] );
    } catch { toast.error( 'Could not load the delivery log' ); }
    finally { setLogLoading( false ); }
  }, [ openLog, toast ] );

  const when = ( ts?: number ) => ts
    ? new Date( ts ).toLocaleDateString( 'en-IN', {
      day: '2-digit', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit' } )
    : '—';

  const content = (
    <div className="ir-page">
      <div className="ir-inner">
        { !embedded && (
          <header className="ir-head">
            <h1 className="ir-h1">Invoice records</h1>
            <p className="ir-sub">
              What was billed, whether it was paid, and what was delivered. Read-only:
              sending, cancelling and renumbering stay on the screens built for them.
            </p>
          </header>
        ) }

        <div className="ir-cards">
          <div className="ir-card">
            <span className="ir-n">{ totals.count }</span>
            <span className="ir-l">Invoices</span>
          </div>
          <div className="ir-card">
            <span className="ir-n">{ money( totals.billed, totals.currency ) }</span>
            <span className="ir-l">Billed</span>
          </div>
          <div className="ir-card">
            <span className="ir-n">{ money( totals.collected, totals.currency ) }</span>
            <span className="ir-l">Collected</span>
          </div>
          <div className="ir-card">
            <span className="ir-n">{ money( totals.tax, totals.currency ) }</span>
            <span className="ir-l">Tax</span>
          </div>
        </div>

        <div className="ir-filters">
          <div className="ir-fg">
            <label htmlFor="ir-q">Search</label>
            <input id="ir-q" type="text" value={ search }
              placeholder="Invoice no, name, phone, order"
              onChange={ ( e ) => setSearch( e.target.value ) } />
          </div>
          <div className="ir-fg">
            { /* MIGRATION SHAPE (b) - the external <label> is RETAINED with an `id`, its `for`
                 is dropped, and the control points at it with `labelledBy`. Shape (a) would
                 have moved the caption into the component, and `.ir-fg label` gives it a 14px
                 muted grey that `.ui-field-label` does not render - the two captions in this
                 filter row would then disagree. The `for` goes because the trigger is a
                 <button>, which takes its accessible name from its contents, so a `for`
                 pointing at it is misleading rather than harmful. */ }
            <label id="ir-st-label">Payment status</label>
            <Select labelledBy="ir-st-label" id="ir-st" value={ statusFilter }
              onChange={ ( v ) => setStatusFilter( v ) }
              options={ statusOptions } style={ { width: 200 } } />
          </div>
          <div className="ir-actions">
            <Button variant="secondary" icon="refresh" onClick={ load }
              disabled={ loading } loading={ loading }>Refresh</Button>
          </div>
        </div>

        <div className="ir-table-wrap">
          <table className="ir-table">
            <thead>
              <tr>
                <th>Invoice</th>
                <th>Customer</th>
                <th>Total</th>
                <th>Payment</th>
                <th>Raised</th>
                <th>Paid</th>
                <th aria-label="Delivery" />
              </tr>
            </thead>
            <tbody>
              { loading ? (
                <tr><td colSpan={ 7 } className="ir-state">Loading…</td></tr>
              ) : rows.length === 0 ? (
                <tr>
                  <td colSpan={ 7 } className="ir-state">
                    { invoices.length === 0
                      ? 'No invoices have been raised yet.'
                      : 'Nothing matches these filters.' }
                  </td>
                </tr>
              ) : rows.map( ( inv ) => {
                const p = paint( inv.paymentStatus );
                return (
                  <React.Fragment key={ inv.invoiceId }>
                    <tr>
                      <td className="ir-mono">{ inv.invoiceNumber || inv.invoiceId }</td>
                      <td>
                        <div className="ir-cust">{ inv.customerName || '—' }</div>
                        <div className="ir-muted">
                          { inv.customerPhone
                            ? `…${String( inv.customerPhone ).slice( -4 )}`
                            : inv.customerEmail || '' }
                        </div>
                      </td>
                      <td className="ir-total">{ money( inv.total, inv.currency ) }</td>
                      <td>
                        <span className="ir-badge"
                          style={ { background: p.bg, color: p.fg } }>
                          { inv.paymentStatus || 'unknown' }
                        </span>
                      </td>
                      <td className="ir-when">{ when( inv.createdAt ) }</td>
                      <td className="ir-when">{ when( inv.paidAt ) }</td>
                      <td>
                        <button type="button" className="ir-pill"
                          onClick={ () => showLog( inv.invoiceId ) }>
                          { openLog === inv.invoiceId ? 'Hide' : 'Delivery' }
                        </button>
                      </td>
                    </tr>
                    { openLog === inv.invoiceId && (
                      <tr className="ir-log-row">
                        <td colSpan={ 7 }>
                          { logLoading ? (
                            <span className="ir-muted">Loading delivery log…</span>
                          ) : logs.length === 0 ? (
                            <span className="ir-muted">
                              Nothing was delivered for this invoice.
                            </span>
                          ) : (
                            <ul className="ir-log">
                              { logs.map( ( l, n ) => (
                                <li key={ `${inv.invoiceId}-${n}` }>
                                  <strong>{ l.channel || 'delivery' }</strong>
                                  { ' · ' }{ l.status || 'unknown' }
                                  { /* Last four only. This is a customer's number and
                                       every log site in this codebase masks to four. */ }
                                  { l.toNumber
                                    ? ` · …${String( l.toNumber ).slice( -4 )}` : '' }
                                  { l.timestamp ? ` · ${when( l.timestamp )}` : '' }
                                  { l.error ? (
                                    <span className="ir-err"> · { l.error }</span>
                                  ) : null }
                                </li>
                              ) ) }
                            </ul>
                          ) }
                        </td>
                      </tr>
                    ) }
                  </React.Fragment>
                );
              } ) }
            </tbody>
          </table>
        </div>

        { totalPages > 1 && (
          <Pagination currentPage={ page } totalPages={ totalPages }
            onPageChange={ setPage } />
        ) }

        <p className="ir-note">
          Totals are summed from each invoice&apos;s stored total, never recomputed
          from line items — the invoice is the record. Phone numbers show the last
          four digits only.
        </p>
      </div>

      <style jsx>{ `
        .ir-page{
          font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
          background:#fafafa;min-height:100%;padding:40px 0;box-sizing:border-box;
        }
        .ir-inner{max-width:1300px;margin:0 auto;padding:0 24px;box-sizing:border-box}
        .ir-head{margin:0 0 28px}
        .ir-h1{
          font-size:clamp(32px,4.2vw,54px);font-weight:700;line-height:1.04;
          letter-spacing:-1.875px;color:rgba(0,0,0,.95);margin:0 0 14px;
        }
        .ir-sub{
          font-size:20px;font-weight:400;line-height:1.4;letter-spacing:-.125px;
          color:rgba(0,0,0,.898);margin:0;max-width:640px;
        }

        .ir-cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:0 0 22px}
        /* 1px static: these are figures, not controls. */
        .ir-card{
          display:flex;flex-direction:column;gap:2px;background:#fff;
          border:1px solid #e5e7eb;border-radius:13px;padding:16px 18px;
        }
        .ir-n{font-size:22px;font-weight:700;color:#000;line-height:1.27;letter-spacing:-.25px}
        .ir-l{font-size:14px;color:rgba(0,0,0,.54)}

        .ir-filters{display:flex;gap:16px;align-items:flex-end;flex-wrap:wrap;margin:0 0 20px}
        .ir-fg{display:flex;flex-direction:column;gap:6px}
        .ir-fg label{font-size:14px;color:rgba(0,0,0,.54)}
        /* The select arm of the next two rules is now UNREACHED - batch 2f replaced this
           page's one select with our own combobox, whose box comes from form-controls.css.
           Left in place rather than edited, as the earlier batches left theirs: the input arm
           is live, and retiring a selector from a list is a separate consolidation.
           No backtick in a styled-jsx comment: this block is a template literal. */
        .ir-fg input,.ir-fg select{
          font-family:inherit;font-size:15px;color:rgba(0,0,0,.898);background:#fff;
          border:2px solid #e5e7eb;border-radius:13px;padding:9px 12px;min-height:0;
        }
        .ir-fg input{width:260px}
        .ir-fg input:focus,.ir-fg select:focus{outline:none;border-color:#d1f470}
        .ir-actions{margin-left:auto}

        .ir-table-wrap{
          background:#fff;border:1px solid #e5e7eb;border-radius:13px;
          overflow:hidden;margin:0 0 16px;
        }
        .ir-table{width:100%;border-collapse:collapse}
        .ir-table th{
          background:#fafafa;padding:11px 16px;text-align:left;font-size:14px;
          font-weight:600;color:rgba(0,0,0,.54);border-bottom:1px solid #e5e7eb;
        }
        .ir-table td{
          padding:11px 16px;border-bottom:1px solid #e5e7eb;font-size:14px;
          color:rgba(0,0,0,.898);
        }
        .ir-table tr:last-child td{border-bottom:none}
        .ir-mono{font-family:'SF Mono',Monaco,Consolas,monospace;font-size:13px}
        .ir-cust{font-weight:500}
        .ir-total{font-weight:600;white-space:nowrap}
        .ir-muted{color:rgba(0,0,0,.54);font-size:13px}
        .ir-when{color:rgba(0,0,0,.54);font-size:13px;white-space:nowrap}
        .ir-state{text-align:center;padding:40px;color:rgba(0,0,0,.54)}
        .ir-badge{
          display:inline-flex;align-items:center;padding:4px 12px;border-radius:50px;
          font-size:13px;font-weight:600;text-transform:capitalize;
        }
        .ir-pill{
          font-family:inherit;font-size:13px;font-weight:500;color:rgba(0,0,0,.898);
          background:#fff;border:2px solid #e5e7eb;border-radius:50px;
          padding:6px 14px;cursor:pointer;transition:all .2s ease;
        }
        .ir-pill:hover{border-color:#d1f470;color:#1a3a2a}
        .ir-log-row td{background:#fafafa}
        .ir-log{margin:0;padding-left:18px}
        .ir-log li{font-size:14px;line-height:1.6;color:rgba(0,0,0,.898)}
        /* --danger, not the success green: a failed delivery must not read as
           a confirmation. */
        .ir-err{color:#dc2626}
        .ir-note{
          font-size:14px;line-height:1.5;color:rgba(0,0,0,.54);margin:0;max-width:720px;
        }

        @media(max-width:900px){
          .ir-cards{grid-template-columns:repeat(2,1fr)}
          .ir-table-wrap{overflow-x:auto}
          .ir-fg input{width:100%}
          .ir-sub{font-size:17px}
        }
        @media(prefers-reduced-motion:reduce){ .ir-pill{transition:none} }
      `}</style>
    </div>
  );

  if ( embedded ) return content;

  return (
    <Layout user={ user } onSignOut={ signOut }>
      <SEO
        title="Invoice records"
        description="Payment ledger: what was billed, paid and delivered."
        noindex
      />
      { content }
    </Layout>
  );
};

export default InvoiceRecordsPage;
