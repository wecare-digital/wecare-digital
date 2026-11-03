/**
 * CollectLogPanel — fresh, mobile-first Collect "Log" surface for /ws/collect.
 *
 * The LOOK is a ground-up mobile-first redesign. The BEHAVIOUR mirrors the proven live log
 * (src/components/workspace/pay/CollectLog.tsx) exactly:
 *   - lists are scoped with collectScope and read through collectApi only (collectInvoices /
 *     collectInvoice / collectDelivery), never a bare fetch;
 *   - the receipt resend is a single explicit request guarded by a sessionStorage intent whose
 *     identity is retained until the server resolves it ACCEPTED/REFUSED, and the resend is
 *     refused if the saved image key drifts (no silent re-authorisation of a different image);
 *   - recoverPayment reuses the existing payment-request identity via api.sendPaymentLinkResult;
 *     reconcileCollectReceipt and repairCollectImage never send a new message;
 *   - the PNG download verifies the private link is https and the bytes are a real PNG signature.
 * No new endpoints and no bare fetch() to the payments API are introduced (the only raw fetch is
 * the GET of an already server-issued private https asset URL, byte-verified — exactly as the
 * live CollectLog does it).
 */
import React from 'react';
import Link from 'next/link';
import { useConfirm } from '../../../contexts/ConfirmContext';
import * as api from '../../../api/client';
import * as service from '../../../api/collect';
import { capturedCollect, collectScope, latestInvoiceImage } from '../../../lib/collect';
import type { WsCollectPreview } from './preview';

const intentKey = ( id: string ) => 'wecare.collect.resend.v1.' + id;

interface Props {
  revision: number;
  onPreview: ( p: WsCollectPreview | null ) => void;
}

const CollectLogPanel: React.FC<Props> = ( { revision, onPreview } ) => {
  const confirm = useConfirm();

  const [ rows, setRows ] = React.useState<api.Invoice[]>( [] );
  const [ selected, setSelected ] = React.useState( '' );
  const [ invoice, setInvoice ] = React.useState<api.Invoice | null>( null );
  const [ order, setOrder ] = React.useState<api.Order | null>( null );
  const [ history, setHistory ] = React.useState<Awaited<ReturnType<typeof service.collectDelivery>> | null>( null );
  const [ notice, setNotice ] = React.useState( '' );
  const [ busy, setBusy ] = React.useState( false );
  const [ refresh, setRefresh ] = React.useState( 0 );
  const [ modal, setModal ] = React.useState( false );

  const flight = React.useRef( false );
  const sequence = React.useRef( 0 );

  React.useEffect( () => {
    let active = true;
    void service.collectInvoices().then( data => {
      if ( active ) { setRows( data.filter( collectScope ) ); setNotice( '' ); }
    } ).catch( () => { if ( active ) setNotice( 'Collect records could not be loaded. Retry to check the current records.' ); } );
    return () => { active = false; };
  }, [ revision, refresh ] );

  React.useEffect( () => {
    const seq = ++sequence.current;
    setInvoice( null ); setHistory( null ); setOrder( null ); onPreview( null );
    if ( !selected ) return;
    void service.collectInvoice( selected ).then( async inv => {
      if ( sequence.current !== seq ) return;
      if ( !collectScope( inv ) ) throw new Error( 'This invoice is outside Collect.' );
      setInvoice( inv );
      const asset = latestInvoiceImage( inv );
      if ( asset?.url && /^https:\/\//.test( asset.url ) ) onPreview( { src: asset.url, label: `Saved invoice ${ inv.invoiceNumber } · image version ${ asset.version || 1 }` } );
      const internal = inv.internalOrderId || ( /^[a-f0-9-]{36}$/i.test( inv.orderId || '' ) ? inv.orderId : '' );
      if ( internal ) {
        const linked = await api.getOrder( internal );
        if ( sequence.current === seq && linked?.invoiceId === inv.invoiceId && ( !inv.orderNumber || linked.orderNumber === inv.orderNumber ) ) setOrder( linked );
      }
    } ).catch( () => { if ( sequence.current === seq ) setNotice( 'Invoice details could not be verified. Refresh before taking action.' ); } );
    void service.collectDelivery( selected ).then( data => { if ( sequence.current === seq ) setHistory( data ); } )
      .catch( () => { if ( sequence.current === seq ) setNotice( 'Delivery evidence is unavailable. No delivery or read status is assumed.' ); } );
    return () => { sequence.current++; };
  }, [ selected, refresh, onPreview ] );

  const reload = () => { setModal( false ); setRefresh( n => n + 1 ); };

  const download = async () => {
    if ( !invoice || flight.current ) return;
    flight.current = true; setBusy( true );
    try {
      const fresh = await service.collectInvoice( invoice.invoiceId ), asset = latestInvoiceImage( fresh );
      if ( !asset?.url || !/^https:\/\//.test( asset.url ) ) throw Error();
      const r = await fetch( asset.url, { cache: 'no-store' } );
      if ( !r.ok ) throw Error();
      const blob = await r.blob(), bytes = new Uint8Array( await blob.slice( 0, 8 ).arrayBuffer() );
      if ( bytes.join( ',' ) !== '137,80,78,71,13,10,26,10' ) throw Error();
      const url = URL.createObjectURL( blob ), a = document.createElement( 'a' );
      a.href = url; a.download = invoice.invoiceNumber.replaceAll( '/', '-' ) + '.png'; a.click();
      setTimeout( () => URL.revokeObjectURL( url ), 1000 );
      setNotice( 'The saved PNG was downloaded.' );
    } catch { setNotice( 'PNG download failed. Refresh the saved image to obtain a new private link; no image was regenerated.' ); }
    finally { flight.current = false; setBusy( false ); }
  };

  const openResend = async () => {
    if ( !invoice || flight.current ) return;
    flight.current = true; setBusy( true );
    try {
      const fresh = await service.collectInvoice( invoice.invoiceId ), asset = latestInvoiceImage( fresh );
      setInvoice( fresh );
      if ( !capturedCollect( fresh ) || !asset?.s3Key || !asset.url || asset.generatedAt < fresh.paidAt || [ 'SENDING', 'UNCONFIRMED' ].includes( fresh.collectResendState || '' ) ) throw Error();
      onPreview( { src: asset.url, label: `Exact saved receipt ${ fresh.invoiceNumber } · version ${ asset.version || 1 }` } );
      setModal( true );
    } catch { setNotice( 'A paid receipt with a saved image and no unresolved resend is required. Refresh delivery evidence.' ); }
    finally { flight.current = false; setBusy( false ); }
  };

  const resend = async () => {
    if ( !invoice || flight.current ) return;
    flight.current = true; setBusy( true );
    try {
      const asset = latestInvoiceImage( invoice );
      if ( !asset ) throw Error();
      const storage = intentKey( invoice.invoiceId );
      let intent = JSON.parse( sessionStorage.getItem( storage ) || 'null' );
      if ( intent && intent.resendRequestId === invoice.collectResendRequestId && [ 'ACCEPTED', 'REFUSED' ].includes( invoice.collectResendState || '' ) ) intent = null;
      if ( !intent ) {
        intent = { invoiceId: invoice.invoiceId, resendRequestId: crypto.randomUUID().replaceAll( '-', '' ), previousRequestId: invoice.collectResendRequestId || '', expectedAssetKey: asset.s3Key };
        sessionStorage.setItem( storage, JSON.stringify( intent ) );
      }
      // A retained unknown intent must never silently authorize another image.
      if ( intent.expectedAssetKey !== asset.s3Key ) throw Error();
      const result = await service.resendCollectInvoice( intent );
      setModal( false );
      if ( result.state === 'ACCEPTED' || result.state === 'REFUSED' ) sessionStorage.removeItem( storage );
      setNotice( result.state === 'ACCEPTED'
        ? 'Receipt accepted by WhatsApp. Delivery and read remain separate.'
        : result.state === 'REFUSED'
          ? 'Resend was refused. Refresh the invoice and review the reason before another request.'
          : 'Resend outcome is unresolved. The original request identity is retained; check delivery evidence before another action.' );
      setRefresh( n => n + 1 );
    } catch { setModal( false ); setNotice( 'Resend could not be confirmed. Check delivery evidence; do not create another resend request.' ); }
    finally { flight.current = false; setBusy( false ); }
  };

  const recoverPayment = async () => {
    if ( !invoice || flight.current ) return;
    flight.current = true; setBusy( true );
    try {
      const fresh = await service.collectInvoice( invoice.invoiceId );
      if ( !collectScope( fresh ) || ![ 'pending', 'created', 'authorized', 'failed' ].includes( fresh.paymentStatus ) || [ 'paid', 'cancelled' ].includes( fresh.status ) ) {
        setNotice( 'The invoice is paid, cancelled or outside Collect. No payment request was sent.' ); return;
      }
      const yes = await confirm( {
        title: 'Recover saved payment request',
        message: `${ fresh.invoiceNumber } · ${ fresh.customerName } · ${ fresh.customerPhone } · ₹${ fresh.total }. Use the same saved invoice and its existing payment-request identity? The approved native payment template will be used.`,
        confirmText: 'Recover original request',
      } );
      if ( !yes ) return;
      const result = await api.sendPaymentLinkResult( fresh.invoiceId );
      setNotice( result.ok
        ? ( result.data.status === 'payment_link_sent' ? 'Original payment request accepted.' : 'Original payment request is already reserved or in progress. Check evidence; no duplicate request is created.' )
        : ( result.failure.message || 'Payment-request outcome is unresolved. Check evidence before retrying.' ) );
      setRefresh( n => n + 1 );
    } catch { setNotice( 'Payment-request outcome is unresolved. Refresh evidence before retrying the original request.' ); }
    finally { flight.current = false; setBusy( false ); }
  };

  const reconcile = async () => {
    if ( !invoice || flight.current ) return;
    flight.current = true; setBusy( true );
    try {
      const result = await service.reconcileCollectReceipt( invoice.invoiceId );
      setNotice( 'Original resend request: ' + result.state + '. No message was sent by reconciliation.' );
      setRefresh( n => n + 1 );
    } catch { setNotice( 'Original resend is still unresolved. No new message was sent.' ); }
    finally { flight.current = false; setBusy( false ); }
  };

  const repair = async () => {
    if ( !invoice || flight.current ) return;
    flight.current = true; setBusy( true );
    try {
      await service.repairCollectImage( invoice.invoiceId );
      setNotice( 'Saved receipt image checked. Payment and invoice amounts were not changed.' );
      setRefresh( n => n + 1 );
    } catch { setNotice( 'Image recovery is unconfirmed. Refresh the invoice before another attempt.' ); }
    finally { flight.current = false; setBusy( false ); }
  };

  const image = invoice && latestInvoiceImage( invoice );
  const paid = !!invoice && capturedCollect( invoice );
  const paidImage = !!image && image.generatedAt >= ( invoice?.paidAt || 0 );

  return (
    <section className="cl">
      <header className="cl-head">
        <h2 className="cl-h2">Collect Log</h2>
        <button type="button" className="cl-btn" disabled={ busy } onClick={ reload }>Refresh evidence</button>
      </header>
      { notice && <p className="cl-notice" role="status">{ notice }</p> }

      <div className="cl-records">
        { rows.length === 0 && <p className="cl-empty">No Collect invoices loaded yet.</p> }
        { rows.map( row => (
          <button type="button" key={ row.invoiceId } className={ `cl-record ${ selected === row.invoiceId ? 'sel' : '' }` } onClick={ () => { setSelected( row.invoiceId ); setModal( false ); } }>
            <strong>{ row.invoiceNumber }</strong>
            <span>{ row.customerName } · ₹{ row.total }</span>
            <small>{ capturedCollect( row ) ? 'Payment captured' : 'Payment ' + row.paymentStatus }</small>
          </button>
        ) ) }
      </div>

      { invoice && (
        <article className="cl-detail">
          <h3 className="cl-h3">{ invoice.invoiceNumber }</h3>
          <dl className="cl-dl">
            <div><dt>Payment</dt><dd>{ paid ? 'Captured' : invoice.paymentStatus || 'Unverified' }</dd></div>
            <div><dt>Receipt</dt><dd>{ history?.receiptDelivery?.status || ( history ? ( invoice.receiptStatus === 'sent' ? 'Accepted · delivery/read unverified' : 'Acceptance not verified' ) : 'Evidence unavailable' ) }</dd></div>
            <div><dt>Service fulfilment</dt><dd>{ order?.fulfillmentStatus || 'Not recorded' }</dd></div>
            <div><dt>Linked order status</dt><dd>{ order?.status || 'Not verified' }</dd></div>
            <div><dt>Saved recipient</dt><dd>{ invoice.customerPhone }</dd></div>
          </dl>

          { paid && ( !paidImage || !history || [ 'Failed', 'Acceptance not verified' ].includes( history.receiptDelivery?.status || '' ) ) && (
            <p className="cl-warn">Paid — receipt pending. Recover the receipt without requesting payment again.</p>
          ) }

          <div className="cl-actions">
            { [ 'pending', 'created', 'authorized', 'failed' ].includes( invoice.paymentStatus ) && ![ 'paid', 'cancelled' ].includes( invoice.status ) && (
              <button type="button" className="cl-btn" disabled={ busy } onClick={ () => void recoverPayment() }>Recover original payment request</button>
            ) }
            <button type="button" className="cl-btn" disabled={ !image || busy } onClick={ reload }>View saved image</button>
            <button type="button" className="cl-btn" disabled={ !image || busy } onClick={ () => void download() }>Download PNG</button>
            <button type="button" className="cl-btn" disabled={ !paid || !paidImage || busy || [ 'SENDING', 'UNCONFIRMED' ].includes( invoice.collectResendState || '' ) } onClick={ () => void openResend() }>Review paid receipt resend</button>
            { paid && <button type="button" className="cl-btn" disabled={ busy } onClick={ () => void repair() }>Recover receipt image</button> }
            { order?.orderNumber && <Link className="cl-link" href={ '/workspace/commerce?view=orders&search=' + encodeURIComponent( order.orderNumber ) }>Open order { order.orderNumber }</Link> }
          </div>

          { [ 'SENDING', 'UNCONFIRMED' ].includes( invoice.collectResendState || '' ) && (
            <button type="button" className="cl-btn cl-reconcile" disabled={ busy } onClick={ () => void reconcile() }>Reconcile original resend</button>
          ) }
          { invoice.collectResendState && <p className="cl-meta">Last manual resend: { invoice.collectResendState }. Check evidence to reconcile an unresolved request.</p> }

          <h3 className="cl-h3">Message history &amp; measured timing</h3>
          { history?.evidenceTimeline?.gaps.map( ( gap, i ) => (
            <p className="cl-meta" key={ 'g' + i }>{ gap.label }: { gap.seconds === null ? 'Unverified' : gap.seconds + ' seconds' } · { gap.basis }</p>
          ) ) }
          { history?.deliveryLogs.map( ( row, i ) => (
            <p className="cl-meta" key={ 'd' + i }>{ new Date( row.timestamp * 1000 ).toLocaleString( 'en-IN' ) } · { row.channel } · { row.status }{ row.error ? ' · ' + row.error : '' }</p>
          ) ) }
        </article>
      ) }

      { modal && invoice && image && (
        <div className="cl-overlay" onClick={ () => setModal( false ) }>
          <section role="dialog" aria-modal="true" aria-labelledby="ws-resend-title" className="cl-dialog" onClick={ e => e.stopPropagation() }>
            <h2 id="ws-resend-title" className="cl-h2">Confirm this saved paid receipt</h2>
            <p className="cl-meta">From WECARE.DIGITAL · +91 93309 94400<br />To { invoice.customerPhone }<br />Template: wecare_default_invoice_image_template · 1782246473079550</p>
            <img className="cl-img" src={ image.url } alt={ 'Exact saved receipt ' + invoice.invoiceNumber } />
            <p className="cl-meta">One explicit resend request. The server rechecks payment, recipient and this saved image.</p>
            <div className="cl-actions">
              <button type="button" className="cl-btn cl-primary" disabled={ busy } onClick={ () => void resend() }>Confirm receipt resend</button>
              <button type="button" className="cl-btn" disabled={ busy } onClick={ () => setModal( false ) }>Cancel</button>
            </div>
          </section>
        </div>
      ) }

      <style jsx>{ `
        .cl{ min-width:0; display:grid; gap:14px; }
        .cl-head{ display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap; }
        .cl-h2{ font-size:19px; font-weight:700; margin:0; color:var(--text,#1a1a1a); }
        .cl-h3{ font-size:14px; font-weight:700; margin:18px 0 8px; color:var(--text,#1a1a1a); }
        .cl-btn,.cl-link{
          display:inline-flex; align-items:center; justify-content:center;
          min-height:var(--tap-min,44px); padding:10px 14px;
          border:1px solid var(--border,#e5e7eb); border-radius:var(--radius-md,8px);
          background:var(--surface,#fff); color:var(--text,#1a1a1a); font:inherit; font-size:13px; font-weight:600;
          text-decoration:none; cursor:pointer;
        }
        .cl-btn:disabled{ opacity:.45; cursor:default; }
        .cl-primary{ background:var(--accent,#1a3a2a); color:#fff; border-color:var(--accent,#1a3a2a); }
        .cl-reconcile{ justify-self:start; margin-top:4px; }
        .cl-notice{ font-size:12px; line-height:1.6; color:var(--text,#1a1a1a); background:var(--bg-secondary,#f9fafb); border:1px solid var(--border,#e5e7eb); border-radius:var(--radius-md,8px); padding:12px; margin:0; }
        .cl-empty{ font-size:13px; color:var(--text-muted,#6b7280); margin:0; }
        .cl-records{ display:grid; gap:8px; }
        .cl-record{
          text-align:left; display:grid; gap:4px; min-height:var(--tap-min,44px); padding:12px 14px;
          border:1px solid var(--border,#e5e7eb); border-radius:var(--radius-lg,12px);
          background:var(--surface,#fff); color:var(--text,#1a1a1a); font:inherit; cursor:pointer;
        }
        .cl-record strong{ font-size:14px; }
        .cl-record span,.cl-record small{ font-size:12px; color:var(--text-muted,#6b7280); }
        .cl-record.sel{ border-color:var(--accent,#1a3a2a); box-shadow:inset 0 0 0 1px var(--accent,#1a3a2a); }
        .cl-detail{ border:1px solid var(--border,#e5e7eb); border-radius:var(--radius-xl,14px); padding:18px; min-width:0; }
        .cl-dl{ margin:0; display:grid; gap:0; }
        .cl-dl > div{ display:flex; gap:12px; justify-content:space-between; padding:9px 0; font-size:13px; border-bottom:1px solid var(--border-light,#f0f0f0); }
        .cl-dl dt{ color:var(--text-muted,#6b7280); }
        .cl-dl dd{ margin:0; text-align:right; overflow-wrap:anywhere; color:var(--text,#1a1a1a); }
        .cl-warn{ font-size:12px; line-height:1.6; color:var(--warning,#b45309); margin:12px 0 0; }
        .cl-meta{ font-size:12px; line-height:1.6; color:var(--text-muted,#6b7280); margin:6px 0 0; overflow-wrap:anywhere; }
        .cl-actions{ display:flex; flex-wrap:wrap; gap:8px; margin-top:12px; }
        .cl-overlay{ position:fixed; inset:0; z-index:var(--z-modal,1410); background:#0008; display:grid; place-items:center; padding:16px; }
        .cl-dialog{ background:var(--surface,#fff); border-radius:var(--radius-2xl,16px); padding:20px; width:min(560px,100%); max-height:90vh; overflow:auto; display:grid; gap:12px; }
        .cl-img{ display:block; max-width:100%; height:auto; max-height:40vh; margin:0 auto; }
      ` }</style>
    </section>
  );
};

export default CollectLogPanel;
