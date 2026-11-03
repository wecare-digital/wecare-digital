/**
 * VaultPanel — fresh, mobile-first Vault sub-view for /ws/collect.
 *
 * SCOPE DECISION (recorded in FEAT-002 findings): Vault is the private-file + paid-access half of
 * the SAME proven money surface — the live VaultWorkspace links Collect <-> Vault — so it is built
 * here as a sub-view of /ws/collect rather than as a parallel payment path. The LOOK is redesigned
 * mobile-first; the BEHAVIOUR mirrors src/components/workspace/pay/VaultWorkspace.tsx exactly:
 *   - the full server quote breakdown is rendered from fetchServicePrices().vault and expressPaise
 *     MUST equal 2500 (₹25) before a send is enabled — a quote without it blocks payment;
 *   - requestSecureFilePayment is called with expectedTotalPaise; a VAULT_QUOTE_CHANGED outcome
 *     clears the sent-intent and the quote so staff must re-review;
 *   - upload-init (startVaultUpload) throws VaultUploadRefused on a 4xx and is NEVER retried on an
 *     unknown outcome — the opaque upload intent is persisted in sessionStorage and recovered by
 *     confirmVaultFileUpload, never by starting a second upload;
 *   - staff preview uses a fresh private signed link and does NOT redeem the customer window;
 *   - the send waits until the selected file's private preview has actually painted.
 * No new endpoints and no bare fetch() to the secure-files API are introduced.
 */
import React from 'react';
import Link from 'next/link';
import * as api from '../../../api/client';
import { startVaultUpload, VaultUploadRefused } from '../../../api/vault';
import { collectInvoice } from '../../../api/collect';
import { latestInvoiceImage } from '../../../lib/collect';
import { fetchServicePrices, rupeesFromPaise, type ServicePriceBreakdown } from '../../../lib/servicePricing';
import { useConfirm } from '../../../contexts/ConfirmContext';
import PaymentCustomerPicker from '../../workspace/pay/PaymentCustomerPicker';
import type { WsCollectPreview } from './preview';

const money = ( value: number ) => '₹' + rupeesFromPaise( value );
const when = ( value?: string | number | null ) => {
  if ( !value ) return 'Not recorded';
  const n = Number( value );
  const d = Number.isFinite( n ) && n > 0 ? new Date( n > 1e12 ? n : n * 1000 ) : new Date( value );
  return Number.isNaN( d.getTime() ) ? 'Not recorded' : d.toLocaleString( 'en-IN', { timeZone: 'Asia/Kolkata', dateStyle: 'medium', timeStyle: 'short' } );
};
const UPLOAD_KEY = 'wecare.vault.upload.v1';
const sendKey = ( id: string ) => 'wecare.vault.payment.v1.' + id;

function Breakdown( { quote }: { quote: ServicePriceBreakdown } ) {
  const rows: [ string, number ][] = [
    [ 'Request · Vault', quote.itemSubtotalPaise ],
    [ 'Supply GST (18%)', quote.supplyGstPaise ],
    [ 'Delight', -quote.delightPaise ],
    [ 'Express · always ₹25', quote.expressPaise ],
    [ 'Convenience fee', quote.convenienceFeePaise ],
    [ 'GST on convenience fee (18%)', quote.convenienceGstPaise ],
    [ 'Customer pays', quote.totalPayablePaise ],
  ];
  return (
    <dl className="vt-breakdown">
      { rows.map( ( [ label, value ] ) => (
        <div key={ label } className={ label === 'Customer pays' ? 'vt-total' : undefined }>
          <dt>{ label }</dt>
          <dd>{ value < 0 ? '−' + money( -value ) : money( value ) }</dd>
        </div>
      ) ) }
    </dl>
  );
}

type Mode = 'Create' | 'Log';

interface Props {
  revision: number;
  onPreview: ( p: WsCollectPreview | null ) => void;
  onChanged: () => void;
}

const VaultPanel: React.FC<Props> = ( { revision, onPreview, onChanged } ) => {
  const [ mode, setMode ] = React.useState<Mode>( 'Create' );
  return (
    <div className="vt">
      <div className="vt-switch" role="tablist" aria-label="Vault view">
        { ( [ 'Create', 'Log' ] as const ).map( name => (
          <button key={ name } type="button" role="tab" aria-selected={ mode === name } className={ mode === name ? 'on' : '' } onClick={ () => { setMode( name ); onPreview( null ); } }>{ name }</button>
        ) ) }
      </div>
      { mode === 'Create'
        ? <VaultCreate revision={ revision } onPreview={ onPreview } onChanged={ onChanged } />
        : <VaultLog revision={ revision } onPreview={ onPreview } onChanged={ onChanged } /> }
      <style jsx>{ `
        .vt{ display:grid; gap:14px; min-width:0; }
        .vt-switch{ display:inline-flex; gap:4px; padding:4px; border:1px solid var(--border,#e5e7eb); border-radius:var(--radius-full,9999px); background:var(--bg-secondary,#f9fafb); align-self:start; }
        .vt-switch button{ min-height:var(--tap-min,44px); padding:8px 18px; border:0; border-radius:var(--radius-full,9999px); background:transparent; color:var(--text-muted,#6b7280); font:inherit; font-weight:600; font-size:13px; cursor:pointer; }
        .vt-switch button.on{ background:var(--surface,#fff); color:var(--text,#1a1a1a); box-shadow:var(--shadow-sm,0 1px 2px rgba(0,0,0,.04)); }
      ` }</style>
    </div>
  );
};

function VaultCreate( { revision, onPreview, onChanged }: Props ) {
  const confirm = useConfirm();
  const [ customer, setCustomer ] = React.useState<api.Contact | null>( null );
  const [ local, setLocal ] = React.useState<File | null>( null );
  const [ files, setFiles ] = React.useState<api.SecureFile[]>( [] );
  const [ selected, setSelected ] = React.useState<api.SecureFile | null>( null );
  const [ quote, setQuote ] = React.useState<ServicePriceBreakdown | null>( null );
  const [ notice, setNotice ] = React.useState( '' );
  const [ busy, setBusy ] = React.useState( false );
  const [ refresh, setRefresh ] = React.useState( 0 );
  const [ pending, setPending ] = React.useState( '' );
  const [ uploadBlocked, setUploadBlocked ] = React.useState( false );
  const [ payBlocked, setPayBlocked ] = React.useState( false );
  const [ filePreviewReady, setFilePreviewReady ] = React.useState( false );

  const flight = React.useRef( false );
  const ownerSequence = React.useRef( 0 );
  const previewSequence = React.useRef( 0 );

  const loadQuote = React.useCallback( async () => {
    setQuote( null );
    const value = ( await fetchServicePrices() ).vault;
    if ( !value?.available || !value.breakdown || value.breakdown.expressPaise !== 2500 ) throw Error( 'The current Vault quote with ₹25 Express is unavailable. Nothing can be sent.' );
    setQuote( value.breakdown );
    return value.breakdown;
  }, [] );

  React.useEffect( () => {
    void loadQuote().catch( e => setNotice( e.message ) );
    try {
      const p = JSON.parse( sessionStorage.getItem( UPLOAD_KEY ) || 'null' );
      if ( p ) { setUploadBlocked( true ); setPending( p.fileId || '' ); setNotice( 'An earlier upload needs checking in Log. Confirm its known file ID below; do not start a duplicate upload.' ); }
    } catch { setUploadBlocked( true ); setNotice( 'The previous upload state could not be read. Inspect Log before another upload.' ); }
  }, [ loadQuote ] );

  React.useEffect( () => {
    const seq = ++ownerSequence.current;
    setFiles( [] ); setSelected( null ); setLocal( null ); setPayBlocked( false ); setFilePreviewReady( false );
    previewSequence.current++; onPreview( null );
    if ( !customer ) return;
    void api.listSecureFiles( customer.phone ).then( r => {
      if ( seq !== ownerSequence.current ) return;
      if ( !r.ok ) throw Error( r.failure.message );
      setFiles( r.data.files );
      if ( r.data.truncated ) setNotice( 'Listing is partial. Refine the customer or inspect Log.' );
    } ).catch( () => { if ( seq === ownerSequence.current ) setNotice( 'Saved files could not be loaded. Reload before taking action.' ); } );
    return () => { ownerSequence.current++; };
  }, [ customer, revision, refresh, onPreview ] );

  React.useEffect( () => {
    if ( local ) {
      const url = URL.createObjectURL( local );
      onPreview( { src: url, label: local.name + ' · local preview · not uploaded', type: local.type } );
      return () => { URL.revokeObjectURL( url ); };
    }
    onPreview( null );
  }, [ local, onPreview ] );

  const chooseCustomer = ( value: api.Contact | null ) => { if ( !flight.current ) setCustomer( value ); };

  const chooseFile = async ( file: api.SecureFile ) => {
    if ( flight.current ) return;
    setLocal( null ); setSelected( file ); setFilePreviewReady( false );
    const request = ++previewSequence.current;
    setPayBlocked( !!sessionStorage.getItem( sendKey( file.fileId ) ) );
    onPreview( null );
    const seq = ownerSequence.current;
    try {
      const url = await api.getVaultStaffDownloadUrl( file.fileId );
      if ( seq !== ownerSequence.current || request !== previewSequence.current ) return;
      if ( !url ) throw Error();
      onPreview( { src: url, label: file.originalFilename + ' · verified private file', type: file.contentType, onReady: () => { if ( seq === ownerSequence.current && request === previewSequence.current ) setFilePreviewReady( true ); } } );
    } catch { if ( seq === ownerSequence.current ) setNotice( 'Private file preview unavailable. Refresh the saved file before sending.' ); }
  };

  const recoverUpload = async () => {
    if ( !pending || flight.current ) return;
    flight.current = true; setBusy( true );
    try {
      const result = await api.confirmVaultFileUpload( pending );
      if ( !result.ok || result.data.status !== 'active' ) throw Error( 'The uploaded bytes are not verified. Inspect this file in Log; no payment is enabled.' );
      sessionStorage.removeItem( UPLOAD_KEY ); setPending( '' ); setUploadBlocked( false );
      setNotice( 'Existing upload verified. Select its saved customer and file.' );
      setRefresh( n => n + 1 ); onChanged();
    } catch ( e ) { setNotice( e instanceof Error ? e.message : 'Upload confirmation unavailable.' ); }
    finally { flight.current = false; setBusy( false ); }
  };

  const upload = async () => {
    if ( flight.current || !customer || !local || uploadBlocked ) return;
    const owner = customer, file = local;
    const seq = ownerSequence.current;
    flight.current = true; setBusy( true );
    try {
      if ( !await confirm( { title: 'Upload this private file?', message: `${ file.name } · ${ file.size.toLocaleString( 'en-IN' ) } bytes. Owner: ${ owner.name } · ${ owner.phone }. Upload verifies storage; it does not send a message or request payment.`, confirmText: 'Upload & verify' } ) ) return;
      sessionStorage.setItem( UPLOAD_KEY, JSON.stringify( { fileId: null } ) ); setUploadBlocked( true );
      const ticket = await startVaultUpload( { name: owner.name, mobile: owner.phone, originalFilename: file.name, contentType: file.type, sizeBytes: file.size } );
      setPending( ticket.fileId ); sessionStorage.setItem( UPLOAD_KEY, JSON.stringify( { fileId: ticket.fileId } ) );
      const sent = await api.uploadVaultFileBytes( ticket.uploadUrl, file, ticket.contentType );
      if ( !sent ) throw Error( 'Upload response is uncertain. Confirm the known file below before starting another upload.' );
      const checked = await api.confirmVaultFileUpload( ticket.fileId );
      if ( !checked.ok || checked.data.status !== 'active' ) throw Error( 'File verification is pending. Use Confirm existing upload below.' );
      sessionStorage.removeItem( UPLOAD_KEY ); setPending( '' ); setUploadBlocked( false );
      setNotice( 'Private file uploaded and verified. Select it below to review payment.' );
      if ( seq === ownerSequence.current ) { setLocal( null ); setRefresh( n => n + 1 ); }
      onChanged();
    } catch ( e ) {
      if ( e instanceof VaultUploadRefused ) { sessionStorage.removeItem( UPLOAD_KEY ); setPending( '' ); setUploadBlocked( false ); }
      setNotice( e instanceof Error ? e.message : 'Upload outcome is uncertain. Inspect Log before trying again.' );
    } finally { flight.current = false; setBusy( false ); }
  };

  const payment = async () => {
    if ( flight.current || !selected || !customer || !quote || payBlocked ) return;
    const file = selected, owner = customer;
    flight.current = true; setBusy( true );
    try {
      const fresh = await loadQuote();
      if ( fresh.totalPayablePaise !== quote.totalPayablePaise ) { setNotice( 'The quote changed. Review the new amount before sending.' ); return; }
      const current = await api.listSecureFiles( owner.phone );
      const verified = current.ok ? current.data.files.find( row => row.fileId === file.fileId ) : null;
      if ( !verified || verified.status !== 'active' || verified.accessState !== 'UNPAID' || verified.lastPaymentRequestedAt ) throw Error( 'This exact file is no longer eligible for a new payment request. Refresh and inspect Log.' );
      if ( !await confirm( { title: 'Send Review & Pay once?', message: `${ owner.name } · ${ owner.phone }. File: ${ file.originalFilename }. Total ${ money( fresh.totalPayablePaise ) }, including ₹25 Express. The backend rechecks owner, storage, price and approved template.`, confirmText: 'Send approved payment template' } ) ) return;
      sessionStorage.setItem( sendKey( file.fileId ), 'requested' ); setPayBlocked( true );
      const r = await api.requestSecureFilePayment( file.fileId, undefined, fresh.totalPayablePaise );
      if ( r.outcome === 'VAULT_QUOTE_CHANGED' ) { sessionStorage.removeItem( sendKey( file.fileId ) ); setPayBlocked( false ); setQuote( null ); }
      setNotice( `${ r.ok ? 'Server response' : 'Not confirmed' }: ${ r.outcome } · ${ r.message } Check Log before another action.` );
      setRefresh( n => n + 1 ); onChanged();
    } catch ( e ) { setNotice( e instanceof Error ? e.message : 'Payment outcome is uncertain. Inspect Log before another action.' ); }
    finally { flight.current = false; setBusy( false ); }
  };

  const payable = selected?.status === 'active' && selected.accessState === 'UNPAID' && !selected.lastPaymentRequestedAt && !payBlocked;
  const canPay = payable && filePreviewReady;

  return (
    <div className="vc">
      <div style={ busy ? { pointerEvents: 'none', opacity: .7 } : undefined }>
        <PaymentCustomerPicker customer={ customer } onSelect={ chooseCustomer } />
      </div>

      <section className="vc-card">
        <span className="vc-step">2 · Private file</span>
        <h2 className="vc-h2">Upload for this customer</h2>
        <p className="vc-help">The file is bound to the saved customer. Staff preview does not start customer access.</p>
        <label className="vc-field">
          <span>PDF, JPEG or PNG</span>
          <input type="file" accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png" disabled={ !customer || busy || uploadBlocked } onChange={ e => {
            const file = e.target.files?.[ 0 ] || null;
            setSelected( null );
            if ( file && ( ![ 'application/pdf', 'image/jpeg', 'image/png' ].includes( file.type ) || file.size <= 0 || file.size > ( file.type === 'application/pdf' ? 100 : 5 ) * 1024 * 1024 ) ) {
              setNotice( 'Choose a non-empty PDF up to 100 MB, or JPEG/PNG up to 5 MB.' ); setLocal( null ); return;
            }
            setLocal( file );
          } } />
        </label>
        { local && <p className="vc-help">{ local.name } · { ( local.size / 1024 ).toFixed( 1 ) } KB · local preview</p> }
        <div className="vc-actions">
          <button type="button" className="vc-btn vc-primary" disabled={ !customer || !local || busy || uploadBlocked } onClick={ () => void upload() }>{ busy ? 'Checking…' : 'Upload & verify private file' }</button>
          <button type="button" className="vc-btn" disabled={ busy } onClick={ () => setRefresh( n => n + 1 ) }>Reload saved files</button>
        </div>
        { uploadBlocked && (
          <div className="vc-recovery">
            <p>Previous upload requires verification{ pending ? ` · ${ pending }` : '. Registration result is unknown; inspect Log before another upload.' }</p>
            { pending && <button type="button" className="vc-btn" disabled={ busy } onClick={ () => void recoverUpload() }>Confirm existing upload</button> }
          </div>
        ) }
        { customer && (
          <div className="vc-files">
            <h3 className="vc-h3">Or use this customer’s saved file</h3>
            { files.length === 0 && <p className="vc-help">No current saved files loaded for this customer.</p> }
            { files.map( file => (
              <article className={ `vc-file ${ selected?.fileId === file.fileId ? 'sel' : '' }` } key={ file.fileId }>
                <strong>{ file.originalFilename || file.displayName }</strong>
                <span className="vc-meta">{ file.accessState || 'Unverified' } · { file.status } · { when( file.createdAt ) }</span>
                <code>{ file.fileId }</code>
                <button type="button" className="vc-btn" disabled={ busy } onClick={ () => void chooseFile( file ) }>{ selected?.fileId === file.fileId ? 'Refresh file preview' : 'Select & preview file' }</button>
              </article>
            ) ) }
          </div>
        ) }
      </section>

      <section className="vc-card">
        <span className="vc-step">3 · Review &amp; send</span>
        <h2 className="vc-h2">Request · Vault</h2>
        { quote ? <Breakdown quote={ quote } /> : <p className="vc-help">Live pricing unavailable. Payment is disabled.</p> }
        <p className="vc-help">Express is always ₹25. The server owns all amounts. Payment unlocks this exact file; customer identity verification is required.</p>
        { selected && (
          <div className="vc-summary">
            <strong>{ selected.originalFilename }</strong>
            <p>{ customer?.name } · { customer?.phone } · { selected.accessState || 'Unverified' }</p>
          </div>
        ) }
        <div className="vc-actions">
          <button type="button" className="vc-btn" disabled={ busy } onClick={ () => void loadQuote().catch( e => setNotice( e.message ) ) }>Refresh live quote</button>
          <button type="button" className="vc-btn vc-primary" disabled={ busy || !canPay || !quote } onClick={ () => void payment() }>Review &amp; send payment template</button>
        </div>
        { selected && !canPay && (
          <p className="vc-help">{ !payable ? 'A new payment is blocked for paid, expired, unverified or previously requested files. Check Log for the existing payment and access evidence.' : 'Waiting for the selected file preview. If it fails, refresh the file preview before reviewing payment.' }</p>
        ) }
      </section>
      { notice && <p className="vc-notice" role="status">{ notice }</p> }

      <style jsx>{ `
        .vc{ display:grid; gap:14px; min-width:0; }
        .vc-card{ padding:18px; border:1px solid var(--border,#e5e7eb); border-radius:var(--radius-xl,14px); background:var(--surface,#fff); min-width:0; }
        .vc-step{ display:block; font-size:11px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; color:var(--text-muted,#6b7280); margin-bottom:6px; }
        .vc-h2{ font-size:17px; font-weight:700; margin:0 0 10px; color:var(--text,#1a1a1a); }
        .vc-h3{ font-size:14px; font-weight:700; margin:16px 0 8px; color:var(--text,#1a1a1a); }
        .vc-field{ display:grid; gap:6px; min-width:0; margin-bottom:12px; }
        .vc-field > span{ font-size:12px; font-weight:600; color:var(--text-muted,#6b7280); }
        .vc-field input{ width:100%; min-width:0; box-sizing:border-box; min-height:var(--tap-min,44px); padding:10px 12px; border:1px solid var(--border,#e5e7eb); border-radius:var(--radius-md,8px); background:var(--surface,#fff); color:var(--text,#1a1a1a); font:inherit; }
        .vc-help{ font-size:12px; line-height:1.6; color:var(--text-muted,#6b7280); margin:0; }
        .vc-actions{ display:flex; flex-wrap:wrap; gap:8px; margin-top:12px; }
        .vc-btn{ min-height:var(--tap-min,44px); padding:10px 14px; border:1px solid var(--border,#e5e7eb); border-radius:var(--radius-md,8px); background:var(--surface,#fff); color:var(--text,#1a1a1a); font:inherit; font-size:13px; font-weight:600; cursor:pointer; }
        .vc-btn:disabled{ opacity:.45; cursor:default; }
        .vc-primary{ background:var(--accent,#1a3a2a); color:#fff; border-color:var(--accent,#1a3a2a); flex:1 1 auto; }
        .vc-recovery{ margin-top:12px; padding:12px; border:1px solid #f3dca0; background:var(--warning-bg,#fffbeb); border-radius:var(--radius-md,8px); display:grid; gap:8px; }
        .vc-recovery p{ margin:0; font-size:12px; line-height:1.6; color:var(--text,#1a1a1a); overflow-wrap:anywhere; }
        .vc-files{ margin-top:14px; display:grid; gap:10px; }
        .vc-file{ display:grid; gap:4px; padding:12px; border:1px solid var(--border,#e5e7eb); border-radius:var(--radius-lg,12px); min-width:0; }
        .vc-file.sel{ border-color:var(--accent,#1a3a2a); box-shadow:inset 0 0 0 1px var(--accent,#1a3a2a); }
        .vc-file strong{ font-size:14px; overflow-wrap:anywhere; }
        .vc-file .vc-meta{ font-size:12px; color:var(--text-muted,#6b7280); }
        .vc-file code{ font-family:var(--font-mono,monospace); font-size:11px; color:var(--text-muted,#6b7280); overflow-wrap:anywhere; }
        .vc-file .vc-btn{ justify-self:start; margin-top:4px; }
        .vc-breakdown{ margin:12px 0; display:grid; gap:0; }
        .vc-breakdown > div{ display:flex; justify-content:space-between; gap:12px; font-size:13px; padding:8px 0; border-bottom:1px solid var(--border-light,#f0f0f0); }
        .vc-breakdown dt{ color:var(--text-muted,#6b7280); }
        .vc-breakdown dd{ margin:0; font-variant-numeric:tabular-nums; color:var(--text,#1a1a1a); }
        .vc-breakdown .vc-total{ border-bottom:0; font-weight:700; }
        .vc-breakdown .vc-total dt,.vc-breakdown .vc-total dd{ color:var(--text,#1a1a1a); font-size:15px; }
        .vc-summary{ margin:12px 0; padding:12px; background:var(--bg-secondary,#f9fafb); border-radius:var(--radius-md,8px); }
        .vc-summary strong{ font-size:14px; overflow-wrap:anywhere; }
        .vc-summary p{ margin:4px 0 0; font-size:12px; color:var(--text-muted,#6b7280); }
        .vc-notice{ font-size:12px; line-height:1.6; color:var(--text,#1a1a1a); background:var(--bg-secondary,#f9fafb); border:1px solid var(--border,#e5e7eb); border-radius:var(--radius-md,8px); padding:12px; margin:0; }
      ` }</style>
    </div>
  );
}

function VaultLog( { revision, onPreview, onChanged }: Props ) {
  const confirm = useConfirm();
  const [ rows, setRows ] = React.useState<api.SecureFileLog[]>( [] );
  const [ selected, setSelected ] = React.useState<api.SecureFileLog | null>( null );
  const [ customer, setCustomer ] = React.useState<api.Contact | null>( null );
  const [ history, setHistory ] = React.useState( false );
  const [ refresh, setRefresh ] = React.useState( 0 );
  const [ notice, setNotice ] = React.useState( '' );
  const [ busy, setBusy ] = React.useState( false );
  const [ delivery, setDelivery ] = React.useState<api.VaultMessageDeliveryLog | null>( null );
  const [ invoice, setInvoice ] = React.useState<api.Invoice | null>( null );
  const [ order, setOrder ] = React.useState<api.Order | null>( null );

  const flight = React.useRef( false );
  const sequence = React.useRef( 0 );

  React.useEffect( () => {
    let active = true;
    setRows( [] ); setSelected( null ); setDelivery( null ); setInvoice( null ); setOrder( null ); onPreview( null );
    void ( history ? api.listSecureFileLogs( customer?.phone ) : api.listSecureFiles( customer?.phone ) ).then( r => {
      if ( !active ) return;
      if ( !r.ok ) throw Error( r.failure.message );
      setRows( 'logs' in r.data ? r.data.logs : r.data.files );
      setNotice( r.data.truncated ? 'Partial listing. Select a customer to narrow the results.' : '' );
    } ).catch( () => { if ( active ) setNotice( 'Vault Log could not be loaded. No payment or delivery is assumed.' ); } );
    return () => { active = false; sequence.current++; };
  }, [ customer, history, refresh, revision, onPreview ] );

  const inspect = async ( file: api.SecureFileLog ) => {
    const seq = ++sequence.current;
    setSelected( file ); setDelivery( null ); setInvoice( null ); setOrder( null ); onPreview( null );
    try {
      const r = await api.readVaultMessageDeliveryLog( file.fileId );
      if ( seq !== sequence.current ) return;
      if ( !r.ok ) throw Error();
      setDelivery( r.data );
      if ( r.data.verifiedInvoice ) {
        const inv = await collectInvoice( r.data.verifiedInvoice.invoiceId );
        if ( seq !== sequence.current ) return;
        if ( inv.invoiceId !== r.data.verifiedInvoice.invoiceId ) throw Error();
        setInvoice( inv );
        const internal = inv.internalOrderId || ( /^[a-f0-9-]{36}$/i.test( inv.orderId || '' ) ? inv.orderId : '' );
        if ( internal ) {
          const linked = await api.getOrder( internal );
          if ( seq === sequence.current && linked?.invoiceId === inv.invoiceId && ( !inv.orderNumber || linked.orderNumber === inv.orderNumber ) ) setOrder( linked );
        }
      }
    } catch { if ( seq === sequence.current ) setNotice( 'Payment/receipt evidence is unavailable. Refresh this record; no invoice or order link is guessed.' ); }
  };

  const filePreview = async () => {
    if ( !selected ) return;
    const seq = sequence.current;
    try {
      const url = await api.getVaultStaffDownloadUrl( selected.fileId );
      if ( seq !== sequence.current ) return;
      if ( !url ) throw Error();
      onPreview( { src: url, type: selected.contentType, label: selected.originalFilename + ' · saved private file' } );
    } catch { setNotice( 'A fresh private-file link could not be obtained.' ); }
  };

  const receipt = async ( download = false ) => {
    if ( !invoice || flight.current ) return;
    const id = invoice.invoiceId, seq = sequence.current;
    flight.current = true; setBusy( true );
    try {
      const inv = await collectInvoice( id ), asset = latestInvoiceImage( inv );
      if ( !asset?.url || !/^https:\/\//.test( asset.url ) ) throw Error();
      if ( !download ) { if ( seq === sequence.current ) onPreview( { src: asset.url, type: 'invoice', label: inv.invoiceNumber + ' · saved image version ' + ( asset.version || 1 ) } ); return; }
      const r = await fetch( asset.url, { cache: 'no-store' } );
      if ( !r.ok ) throw Error();
      const blob = await r.blob(), bytes = new Uint8Array( await blob.slice( 0, 8 ).arrayBuffer() );
      if ( bytes.join( ',' ) !== '137,80,78,71,13,10,26,10' ) throw Error();
      const url = URL.createObjectURL( blob ), a = document.createElement( 'a' );
      a.href = url; a.download = inv.invoiceNumber.replaceAll( '/', '-' ) + '.png'; a.click();
      setTimeout( () => URL.revokeObjectURL( url ), 1000 );
    } catch { setNotice( 'Saved PNG unavailable. Refresh its private link; the issued image was not regenerated.' ); }
    finally { flight.current = false; setBusy( false ); }
  };

  const resend = async () => {
    if ( !selected || flight.current || history ) return;
    const file = selected;
    flight.current = true; setBusy( true );
    try {
      const live = await api.listSecureFiles( customer?.phone );
      const current = live.ok ? live.data.files.find( f => f.fileId === file.fileId ) : null;
      if ( !current || ![ 'READY', 'OPEN' ].includes( current.accessState || '' ) ) throw Error( 'Paid access is not currently eligible. No link was sent.' );
      if ( current.accessResendRequestId && current.accessResendState !== 'ACCEPTED' ) throw Error( 'The previous access send is unresolved. Inspect provider evidence before another request.' );
      if ( !await confirm( { title: 'Resend approved Access Vault?', message: `${ current.originalFilename }. Saved owner: ${ current.ownerName || 'Verified owner' } · ${ current.ownerPhoneMasked || 'number hidden' }. The backend rechecks the saved owner and paid entitlement. This does not create another payment or extend an open window.`, confirmText: 'Resend approved access template' } ) ) return;
      let requestId = sessionStorage.getItem( accessKey( file.fileId ) );
      if ( !requestId ) { requestId = crypto.randomUUID(); sessionStorage.setItem( accessKey( file.fileId ), requestId ); }
      const r = await api.sendSecureFileAccess( file.fileId, requestId, current.accessResendRequestId || '' );
      if ( r.ok && r.status === 200 ) sessionStorage.removeItem( accessKey( file.fileId ) );
      setNotice( `${ r.outcome } · ${ r.message } A timeout is not permission to create another send.` );
      onChanged();
    } catch ( e ) { setNotice( e instanceof Error ? e.message : 'Access send is unconfirmed. Check provider evidence; do not retry blindly.' ); }
    finally { flight.current = false; setBusy( false ); }
  };

  const stages: [ keyof api.VaultMessageDeliveryLog['evidence'], string ][] = [
    [ 'nativePay', 'Review & Pay' ], [ 'processing', 'Payment Processing' ], [ 'completed', 'Payment Completed' ],
    [ 'invoice', 'Paid invoice image' ], [ 'autoAccess', 'Automatic Access Vault' ], [ 'access', 'Manual access resend' ],
  ];

  return (
    <div className="vl">
      <PaymentCustomerPicker customer={ customer } onSelect={ setCustomer } />
      <section className="vl-card">
        <div className="vl-head">
          <h2 className="vl-h2">File, payment &amp; access Log</h2>
          <button type="button" className="vl-btn" disabled={ busy } onClick={ () => setRefresh( n => n + 1 ) }>Refresh Log</button>
          <label className="vl-check"><input type="checkbox" checked={ history } disabled={ busy } onChange={ e => setHistory( e.target.checked ) } />Include retained history</label>
        </div>
        <p className="vl-help">{ rows.length } loaded records. Payment, template delivery and customer access are separate states.</p>
        <div className="vl-files">
          { rows.map( file => (
            <article key={ file.fileId } className={ `vl-file ${ selected?.fileId === file.fileId ? 'sel' : '' }` }>
              <strong>{ file.originalFilename || file.displayName }</strong>
              <p>{ file.ownerName } · { file.ownerPhoneMasked } · { file.status }</p>
              <code>{ file.fileId }</code>
              <p>Access: { file.accessState || 'Unverified' } · Downloads: { file.downloadCount } · Created: { when( file.createdAt ) }</p>
              <button type="button" className="vl-btn" disabled={ busy } onClick={ () => void inspect( file ) }>Inspect file &amp; payment</button>
            </article>
          ) ) }
        </div>
      </section>

      { selected && (
        <section className="vl-card">
          <h2 className="vl-h2">{ selected.originalFilename || selected.displayName }</h2>
          <p className="vl-help">Payment: { invoice ? invoice.paymentStatus : selected.vaultPaymentStatus || 'Not verified' } · Access: { selected.accessState || 'Not verified' }</p>
          <p className="vl-help">Window ends: { when( selected.accessWindowEndsAt ) }. A paid file with missing receipt or delivery evidence must be reconciled; never request payment again.</p>
          <div className="vl-actions">
            <button type="button" className="vl-btn" disabled={ busy } onClick={ () => void filePreview() }>Preview saved private file</button>
            { invoice && <>
              <button type="button" className="vl-btn" disabled={ busy } onClick={ () => void receipt() }>View saved invoice</button>
              <button type="button" className="vl-btn" disabled={ busy } onClick={ () => void receipt( true ) }>Download invoice PNG</button>
            </> }
            { order && <Link className="vl-link" href={ '/workspace/commerce?view=orders&search=' + encodeURIComponent( order.orderNumber || '' ) }>Open order { order.orderNumber } ↗</Link> }
            { !history && [ 'READY', 'OPEN' ].includes( selected.accessState || '' ) && (
              <button type="button" className="vl-btn" disabled={ busy || !!( selected.accessResendRequestId && selected.accessResendState !== 'ACCEPTED' ) } onClick={ () => void resend() }>Resend approved access link</button>
            ) }
          </div>

          { delivery && <>
            <h3 className="vl-h3">Verified message evidence</h3>
            <div className="vl-table">
              <table>
                <thead><tr><th>Stage</th><th>Provider status</th><th>Observed (IST)</th><th>Observed gap</th></tr></thead>
                <tbody>
                  { stages.map( ( [ key, label ], i ) => {
                    const evidence = delivery.evidence[ key ];
                    const previous = i ? delivery.evidence[ stages[ i - 1 ][ 0 ] ] : null;
                    const gap = evidence?.observedAt && previous?.observedAt ? evidence.observedAt - previous.observedAt : null;
                    return <tr key={ key }><td>{ label }</td><td>{ evidence?.status || 'NOT_TRACKED' }{ evidence?.source === 'SEND_LOG' ? ' · acceptance evidence' : '' }</td><td>{ when( evidence?.observedAt ) }</td><td>{ gap === null || gap < 0 ? 'Not measurable' : `${ gap } seconds` }</td></tr>;
                  } ) }
                </tbody>
              </table>
            </div>
            <p className="vl-help">Observed gaps compare recorded event times; they are not configured delays or proof of fulfilment. Missing provider evidence stays unverified.</p>
            <p className="vl-help">Invoice: { invoice?.invoiceNumber || 'No verified paid invoice linked' } · Order: { order?.orderNumber || 'No verified order link available' }</p>
          </> }
        </section>
      ) }
      { notice && <p className="vl-notice" role="status">{ notice }</p> }

      <style jsx>{ `
        .vl{ display:grid; gap:14px; min-width:0; }
        .vl-card{ padding:18px; border:1px solid var(--border,#e5e7eb); border-radius:var(--radius-xl,14px); background:var(--surface,#fff); min-width:0; }
        .vl-head{ display:flex; flex-wrap:wrap; align-items:center; gap:12px; }
        .vl-h2{ font-size:17px; font-weight:700; margin:0; color:var(--text,#1a1a1a); }
        .vl-h3{ font-size:14px; font-weight:700; margin:18px 0 8px; color:var(--text,#1a1a1a); }
        .vl-check{ display:inline-flex; align-items:center; gap:8px; font-size:12px; color:var(--text-muted,#6b7280); }
        .vl-check input{ width:18px; height:18px; }
        .vl-help{ font-size:12px; line-height:1.6; color:var(--text-muted,#6b7280); margin:8px 0 0; overflow-wrap:anywhere; }
        .vl-btn,.vl-link{ display:inline-flex; align-items:center; justify-content:center; min-height:var(--tap-min,44px); padding:10px 14px; border:1px solid var(--border,#e5e7eb); border-radius:var(--radius-md,8px); background:var(--surface,#fff); color:var(--text,#1a1a1a); font:inherit; font-size:13px; font-weight:600; text-decoration:none; cursor:pointer; }
        .vl-btn:disabled{ opacity:.45; cursor:default; }
        .vl-files{ margin-top:12px; display:grid; gap:10px; }
        .vl-file{ display:grid; gap:4px; padding:12px; border:1px solid var(--border,#e5e7eb); border-radius:var(--radius-lg,12px); min-width:0; }
        .vl-file.sel{ border-color:var(--accent,#1a3a2a); box-shadow:inset 0 0 0 1px var(--accent,#1a3a2a); }
        .vl-file strong{ font-size:14px; overflow-wrap:anywhere; }
        .vl-file p{ margin:0; font-size:12px; color:var(--text-muted,#6b7280); overflow-wrap:anywhere; }
        .vl-file code{ font-family:var(--font-mono,monospace); font-size:11px; color:var(--text-muted,#6b7280); overflow-wrap:anywhere; }
        .vl-file .vl-btn{ justify-self:start; margin-top:4px; }
        .vl-actions{ display:flex; flex-wrap:wrap; gap:8px; margin-top:12px; }
        .vl-table{ overflow-x:auto; margin-top:8px; -webkit-overflow-scrolling:touch; }
        .vl-table table{ width:100%; border-collapse:collapse; font-size:12px; min-width:420px; }
        .vl-table th,.vl-table td{ text-align:left; padding:8px 10px; border-bottom:1px solid var(--border-light,#f0f0f0); }
        .vl-table th{ color:var(--text-muted,#6b7280); font-weight:600; }
        .vl-notice{ font-size:12px; line-height:1.6; color:var(--text,#1a1a1a); background:var(--bg-secondary,#f9fafb); border:1px solid var(--border,#e5e7eb); border-radius:var(--radius-md,8px); padding:12px; margin:0; }
      ` }</style>
    </div>
  );
}

const accessKey = ( id: string ) => 'wecare.vault.access.v1.' + id;

export default VaultPanel;
