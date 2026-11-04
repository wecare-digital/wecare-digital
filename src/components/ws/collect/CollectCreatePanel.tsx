/**
 * CollectCreatePanel — fresh, mobile-first Collect "Create" flow for /ws/collect.
 *
 * The LOOK is a ground-up mobile-first redesign. The BEHAVIOUR is a faithful mirror of the proven
 * live money surface (src/components/workspace/pay/CollectCreate.tsx). Every money-safety invariant
 * is preserved unchanged:
 *   - the debounced server quote comes from collectApi.quoteCollect(request) only;
 *   - confirmation is blocked until a CURRENT server quote AND the server-rendered
 *     previewImageBase64/previewFingerprint matching the current input key exist;
 *   - createCollectOnce is intent-deduped via an opaque recovery reference persisted in
 *     sessionStorage and is NEVER auto-retried (a <500 failure clears the intent so staff may
 *     review; a >=500/unknown outcome retains it for explicit recovery);
 *   - sending the approved Review & Pay template (api.sendPaymentLinkResult) is a SEPARATE step
 *     AFTER creation; the saved invoice total is compared against the reviewed preview before the
 *     send is attempted.
 * No new endpoints and no bare fetch() are introduced here.
 */
import React from 'react';
import * as api from '../../../api/client';
import * as collectApi from '../../../api/collect';
import { blankCollectLine, collectDraft, collectInputKey, verifiedCollectRecovery, type CollectLine } from '../../../lib/collect';
import { useConfirm } from '../../../contexts/ConfirmContext';
import { useToastContext } from '../../../contexts/ToastContext';
import PaymentCustomerPicker from '../../workspace/pay/PaymentCustomerPicker';
import type { WsCollectPreview } from './preview';

const PENDING_KEY = 'wecare.collect.pending-create.v1';

interface Props {
  onPreview: ( p: WsCollectPreview | null ) => void;
  onCreated: () => void;
}

const CollectCreatePanel: React.FC<Props> = ( { onPreview, onCreated } ) => {
  const confirm = useConfirm();
  const toast = useToastContext();

  const [ customer, setCustomer ] = React.useState<api.Contact | null>( null );
  const [ express, setExpress ] = React.useState( '' );
  const [ lines, setLines ] = React.useState<CollectLine[]>( [ blankCollectLine() ] );
  const [ quote, setQuote ] = React.useState<{ key: string; value: api.InvoiceEnginePreview } | null>( null );
  const [ previewRevision, setPreviewRevision ] = React.useState( 0 );
  const [ loading, setLoading ] = React.useState( false );
  const [ busy, setBusy ] = React.useState( false );
  const [ notice, setNotice ] = React.useState( '' );
  const [ pending, setPending ] = React.useState( '' );
  const [ created, setCreated ] = React.useState<api.Invoice | null>( null );

  const flight = React.useRef( false );
  const currentKey = React.useRef( '' );

  const request = React.useMemo( () => collectDraft( customer, lines, express ), [ customer, lines, express ] );
  const key = collectInputKey( request );
  React.useLayoutEffect( () => { currentKey.current = key; }, [ key ] );

  const ready = !!key && quote?.key === key && !!quote.value.previewFingerprint && !!quote.value.previewImageBase64 && !loading;

  // Restore a retained recovery reference: a prior create whose outcome is unknown.
  React.useEffect( () => {
    try { const saved = sessionStorage.getItem( PENDING_KEY ); if ( saved ) setPending( saved ); }
    catch { /* The server reference still guards this page's intent. */ }
  }, [] );

  // Debounced server quote + server-rendered preview image, bound to the current input key.
  React.useEffect( () => {
    let active = true;
    setQuote( null );
    onPreview( null );
    setLoading( !!key );
    if ( !request || !key ) return () => { active = false; };
    const timer = setTimeout( () => {
      void collectApi.quoteCollect( request ).then( value => {
        if ( !active || currentKey.current !== key ) return;
        if ( !value?.previewFingerprint || !value.previewImageBase64 ) {
          setNotice( 'A current server quote and invoice image are required before confirmation. Reload the customer if their saved details changed.' );
          return;
        }
        setQuote( { key, value } );
        setNotice( '' );
        onPreview( {
          src: `data:image/png;base64,${ value.previewImageBase64 }`,
          label: 'Server-rendered draft · no invoice number issued',
        } );
      } ).catch( () => {
        if ( active ) setNotice( 'Server preview could not be loaded. Nothing can be confirmed yet.' );
      } ).finally( () => { if ( active ) setLoading( false ); } );
    }, 350 );
    return () => { active = false; clearTimeout( timer ); };
  }, [ key, request, onPreview, previewRevision ] );

  const select = ( c: api.Contact | null ) => { setCustomer( c ); setCreated( null ); };
  const update = ( index: number, field: keyof CollectLine, value: string ) =>
    setLines( rows => rows.map( ( row, n ) => n === index ? { ...row, [ field ]: value } : row ) );

  const recover = async () => {
    if ( !pending || flight.current ) return;
    flight.current = true; setBusy( true );
    try {
      const rows = await collectApi.collectInvoices( pending );
      if ( rows.length === 1 ) {
        const invoice = await collectApi.collectInvoice( rows[ 0 ].invoiceId );
        if ( !verifiedCollectRecovery( invoice, { referenceId: pending, invoiceId: rows[ 0 ].invoiceId } ) ) {
          setNotice( 'The saved invoice is incomplete or does not match this recovery reference. Keep this request pending and reconcile it in Log.' );
          return;
        }
        setCreated( invoice );
        setPending( '' );
        sessionStorage.removeItem( PENDING_KEY );
        setNotice( 'The existing invoice was found. No new invoice or payment request was sent. Open Log to review it.' );
        onCreated();
      } else {
        setNotice( 'Creation is not yet reconciled. Keep this request pending and check Log; do not raise a second invoice.' );
      }
    } catch { setNotice( 'Recovery read failed. The pending request is retained.' ); }
    finally { flight.current = false; setBusy( false ); }
  };

  const create = async () => {
    if ( !ready || !request || !quote || pending || flight.current ) return;
    flight.current = true; setBusy( true );
    const reviewedKey = key, reviewed = quote.value;
    try {
      const yes = await confirm( {
        title: 'Confirm custom invoice and payment template',
        message: `${ customer?.name } · ${ customer?.phone }. Amount ₹${ reviewed.total }. Create this invoice and send one approved Review and Pay template?`,
        confirmText: 'Create & send template',
      } );
      if ( !yes ) return;
      if ( currentKey.current !== reviewedKey ) { setNotice( 'The draft changed. Review the new server preview.' ); return; }
      const reference = 'WD-PAY-' + crypto.randomUUID().replaceAll( '-', '' ).slice( 0, 16 ).toUpperCase();
      // Persist only the opaque recovery reference, never customer data or credentials.
      try { sessionStorage.setItem( PENDING_KEY, reference ); }
      catch { setNotice( 'This browser cannot retain the invoice recovery reference. Enable session storage before creating.' ); return; }
      setPending( reference );
      const result = await collectApi.createCollectOnce( { ...request, referenceId: reference, confirmedPreviewFingerprint: reviewed.previewFingerprint } );
      if ( !result.ok ) {
        if ( result.status !== null && result.status < 500 ) {
          sessionStorage.removeItem( PENDING_KEY );
          setPending( '' );
          setQuote( null );
          onPreview( null );
        }
        setNotice( result.message || 'Creation is unconfirmed. Check the saved invoice before another action.' );
        return;
      }
      const inv = await collectApi.collectInvoice( result.invoice.invoiceId );
      if ( !verifiedCollectRecovery( inv, { referenceId: reference, invoiceId: result.invoice.invoiceId } ) ) {
        setNotice( 'The saved invoice is incomplete or does not match this request. The recovery reference is retained; no payment request was sent.' );
        return;
      }
      setCreated( inv );
      sessionStorage.removeItem( PENDING_KEY );
      setPending( '' );
      onCreated();
      if ( Number( inv.total ).toFixed( 2 ) !== Number( reviewed.total ).toFixed( 2 ) ) {
        setNotice( 'Invoice saved, but its total differs from the reviewed preview. Payment was not sent. Review Log.' );
        return;
      }
      const sent = await api.sendPaymentLinkResult( inv.invoiceId );
      const ok = sent.ok && sent.data.status === 'payment_link_sent';
      setNotice( ok
        ? 'Invoice saved. The approved payment request was accepted; delivery and payment remain separate.'
        : 'Invoice saved. Payment-request delivery is not confirmed. Check Log before another send.' );
      if ( ok ) toast.success( 'Invoice saved and payment request accepted.' );
    } catch {
      setNotice( 'The action outcome is unconfirmed. Use the saved recovery reference or Log before another action.' );
    } finally { flight.current = false; setBusy( false ); }
  };

  const resetForm = () => {
    setCreated( null );
    setLines( [ blankCollectLine() ] );
    setExpress( '' );
    select( null );
    setNotice( '' );
    onPreview( null );
  };

  return (
    <div className="cc">
      { pending && (
        <div className="cc-recovery" role="status">
          <strong>Creation needs reconciliation</strong>
          <p>Reference: <code>{ pending }</code></p>
          <button type="button" className="cc-btn" disabled={ busy } onClick={ () => void recover() }>Check saved invoice</button>
        </div>
      ) }

      <fieldset className="cc-fieldset" disabled={ busy || !!pending || !!created }>
        <PaymentCustomerPicker customer={ customer } onSelect={ select } />

        <section className="cc-card">
          <span className="cc-step">2 · Invoice values</span>
          <h2 className="cc-h2">Custom invoice items</h2>

          <div className="cc-lines">
            { lines.map( ( line, index ) => (
              <div className="cc-line" key={ index }>
                <label className="cc-field cc-desc">
                  <span>Description</span>
                  <input value={ line.name } onChange={ e => update( index, 'name', e.target.value ) } />
                </label>
                <div className="cc-line-grid">
                  <label className="cc-field"><span>Qty</span>
                    <input type="number" min="1" step="1" inputMode="numeric" value={ line.quantity } onChange={ e => update( index, 'quantity', e.target.value ) } />
                  </label>
                  <label className="cc-field"><span>Unit ₹</span>
                    <input type="number" min="0.01" step="0.01" inputMode="decimal" value={ line.amount } onChange={ e => update( index, 'amount', e.target.value ) } />
                  </label>
                  <label className="cc-field"><span>GST %</span>
                    <input type="number" min="0" max="100" step="0.01" inputMode="decimal" value={ line.gstRate } onChange={ e => update( index, 'gstRate', e.target.value ) } />
                  </label>
                  <button type="button" className="cc-remove" disabled={ lines.length === 1 } aria-label={ `Remove item ${ index + 1 }` } onClick={ () => setLines( rows => rows.filter( ( _, n ) => n !== index ) ) }>×</button>
                </div>
              </div>
            ) ) }
          </div>

          <button type="button" className="cc-btn cc-add" onClick={ () => setLines( rows => [ ...rows, blankCollectLine() ] ) }>＋ Add item</button>

          <div className="cc-express">
            <label className="cc-field" htmlFor="ws-collect-express">
              <span>Express ₹ (required)</span>
              <input id="ws-collect-express" type="number" min="0" step="0.01" inputMode="decimal" required value={ express } onChange={ e => setExpress( e.target.value ) } placeholder="Enter amount" aria-describedby="ws-collect-express-help" />
            </label>
            <p id="ws-collect-express-help" className="cc-help">Enter the Express charge for this invoice. Enter 0 when there is no Express charge. The server recalculates the breakdown and preview from this value.</p>
          </div>
        </section>
      </fieldset>

      <section className="cc-card">
        <span className="cc-step">3 · Review</span>
        <h2 className="cc-h2">Preview &amp; confirmation</h2>
        <p className="cc-help">
          { loading
            ? 'Updating the server quote and image…'
            : ready
              ? 'The current server invoice image is shown in the preview above.'
              : 'Select a saved customer with a complete address and enter valid invoice rows and an Express amount. Confirmation requires a current server quote and image.' }
        </p>
        { customer && !request && (
          <p className="cc-alert" role="alert">Complete the invoice items and Express amount. Check the saved customer details and address; use Edit customer to correct them.</p>
        ) }

        { ready && quote && (
          <dl className="cc-breakdown">
            { ( [
              [ 'Item base', quote.value.subtotal ],
              [ 'Supply GST', quote.value.tax ],
              [ 'Delight −', quote.value.discount ],
              [ 'Express +', quote.value.shipping ],
              [ 'Convenience +', quote.value.convenienceFeeNet ],
              [ 'Fee GST +', quote.value.convenienceFeeGst ],
              [ 'Customer pays', quote.value.total ],
            ] as const ).map( ( [ label, value ] ) => (
              <div key={ label } className={ label === 'Customer pays' ? 'cc-total' : undefined }>
                <dt>{ label }</dt><dd>₹{ value }</dd>
              </div>
            ) ) }
          </dl>
        ) }

        <div className="cc-actions">
          <button type="button" className="cc-btn" disabled={ busy || !!pending || !request } onClick={ () => setPreviewRevision( n => n + 1 ) }>Refresh server preview</button>
          <button type="button" className="cc-btn cc-primary" disabled={ !ready || busy || !!pending || !!created } onClick={ () => void create() }>{ busy ? 'Checking…' : 'Confirm invoice & send template' }</button>
        </div>

        { created && (
          <div className="cc-done" role="status">
            <p>Saved invoice <strong>{ created.invoiceNumber }</strong>. Review payment, receipt and order evidence in Log.</p>
            <button type="button" className="cc-btn" onClick={ resetForm }>New custom invoice</button>
          </div>
        ) }
        { notice && <p className="cc-notice" role="status">{ notice }</p> }
      </section>

      <style jsx>{ `
        .cc{ display:grid; gap:16px; min-width:0; }
        .cc-fieldset{ border:0; margin:0; padding:0; min-width:0; display:grid; gap:16px; }
        .cc-card,.cc-recovery{
          padding:18px;
          border:1px solid var(--border,#e5e7eb);
          border-radius:var(--radius-xl,14px);
          background:var(--surface,#fff);
          min-width:0;
        }
        .cc-recovery{ background:var(--warning-bg,#fffbeb); border-color:#f3dca0; display:grid; gap:10px; }
        .cc-recovery code{ font-family:var(--font-mono,monospace); font-size:12px; overflow-wrap:anywhere; }
        .cc-step{
          display:block; font-size:11px; font-weight:700; letter-spacing:.08em;
          text-transform:uppercase; color:var(--text-muted,#6b7280); margin-bottom:6px;
        }
        .cc-h2{ font-size:17px; font-weight:700; margin:0 0 14px; color:var(--text,#1a1a1a); }
        .cc-field{ display:grid; gap:6px; min-width:0; }
        .cc-field > span{ font-size:12px; font-weight:600; color:var(--text-muted,#6b7280); }
        .cc-field input{
          width:100%; min-width:0; box-sizing:border-box;
          min-height:var(--tap-min,44px); padding:10px 12px;
          border:1px solid var(--border,#e5e7eb); border-radius:var(--radius-md,8px);
          background:var(--surface,#fff); color:var(--text,#1a1a1a); font:inherit;
        }
        .cc-field input:focus{ outline:none; border-color:var(--lime,#d1f470); box-shadow:var(--focus-ring,0 0 0 2px rgba(209,244,112,.35)); }
        .cc-lines{ display:grid; gap:14px; }
        .cc-line{
          display:grid; gap:10px; padding-top:14px; border-top:1px solid var(--border,#e5e7eb);
        }
        .cc-line:first-child{ border-top:0; padding-top:0; }
        .cc-line-grid{
          display:grid; grid-template-columns:72px 1fr 84px var(--tap-min,44px); gap:8px; align-items:end;
        }
        .cc-remove{
          min-height:var(--tap-min,44px); min-width:var(--tap-min,44px);
          border:1px solid var(--border,#e5e7eb); border-radius:var(--radius-md,8px);
          background:var(--surface,#fff); color:var(--danger,#dc2626); font-size:20px; line-height:1; cursor:pointer;
        }
        .cc-remove:disabled{ opacity:.4; cursor:default; color:var(--text-muted,#6b7280); }
        .cc-add{ justify-self:start; margin-top:14px; }
        .cc-express{
          display:grid; gap:8px; margin-top:16px; padding-top:16px; border-top:1px solid var(--border,#e5e7eb);
        }
        .cc-express .cc-field{ max-width:220px; }
        .cc-help{ font-size:12px; line-height:1.6; color:var(--text-muted,#6b7280); margin:0; }
        .cc-alert{ font-size:12px; line-height:1.6; color:var(--danger,#dc2626); margin:10px 0 0; }
        .cc-breakdown{ margin:14px 0; display:grid; gap:0; }
        .cc-breakdown > div{
          display:flex; justify-content:space-between; gap:12px; font-size:13px; padding:8px 0;
          border-bottom:1px solid var(--border-light,#f0f0f0);
        }
        .cc-breakdown dt{ color:var(--text-muted,#6b7280); }
        .cc-breakdown dd{ margin:0; font-variant-numeric:tabular-nums; color:var(--text,#1a1a1a); }
        .cc-breakdown .cc-total{ border-bottom:0; font-weight:700; }
        .cc-breakdown .cc-total dt,.cc-breakdown .cc-total dd{ color:var(--text,#1a1a1a); font-size:15px; }
        .cc-actions{ display:flex; flex-wrap:wrap; gap:10px; margin-top:4px; }
        .cc-btn{
          min-height:var(--tap-min,44px); padding:10px 16px;
          border:1px solid var(--border,#e5e7eb); border-radius:var(--radius-md,8px);
          background:var(--surface,#fff); color:var(--text,#1a1a1a); font:inherit; font-size:14px; font-weight:600; cursor:pointer;
        }
        .cc-btn:disabled{ opacity:.45; cursor:default; }
        .cc-primary{ background:var(--accent,#1a3a2a); color:#fff; border-color:var(--accent,#1a3a2a); flex:1 1 auto; }
        .cc-primary:not(:disabled):hover{ background:var(--accent-hover,#0f2a1d); }
        .cc-done{ margin-top:14px; display:grid; gap:10px; }
        .cc-done p{ font-size:13px; line-height:1.6; margin:0; color:var(--text,#1a1a1a); }
        .cc-notice{ margin-top:14px; font-size:12px; line-height:1.6; color:var(--text,#1a1a1a); background:var(--bg-secondary,#f9fafb); border:1px solid var(--border,#e5e7eb); border-radius:var(--radius-md,8px); padding:12px; }

        @media (min-width:560px){
          .cc-express .cc-field{ max-width:240px; }
        }
      ` }</style>
    </div>
  );
};

export default CollectCreatePanel;
