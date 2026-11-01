/* Pay Flow CRM - WECARE.DIGITAL */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useRouter } from 'next/router';
import Layout from '../../../components/Layout';
import PageShell, { ShellTab } from '../../../components/PageShell';
import Button from '../../../components/ui/Button';
import Select, { type SelectOption } from '../../../components/ui/Select';
import * as api from '../../../api/client';
import { useConfirm } from '../../../contexts/ConfirmContext';
import type { Invoice, InvoiceDeliveryLog, Contact, CreateInvoiceEngineRequest, CreateInvoiceEngineResult, ApiResult, SendPaymentLinkResult } from '../../../api/client';
import { DEFAULT_GSTIN } from '../../../config/constants';
import { COUNTRY_OPTIONS, countryCodeForName } from '../../../config/countryOptions';
import { SERVICE_CHOICES, type ServiceChoice } from '../../../config/services';
import { fetchServicePrices, rupeesFromPaise, type ServicePrice } from '../../../lib/servicePricing';
import {
  ADDRESS_FIELDS, EMPTY_ADDRESS_FIELDS, addressPayload, addressFieldsFromContact,
  contactDeliveryAddress, formatAddress, type AddressFormFields,
} from '../../../lib/address-format';

interface PP {
  signOut?: () => void; user?: any; embedded?: boolean; mode?: 'collect' | 'invoices';
  /** Only Collect -> Create -> Saved invoices may send existing Collect invoices. */
  allowSendInInvoices?: boolean;
}
interface FC { default_gst_rate: number; default_shipping: number; gstin: string; default_item_name: string; purposes: string[]; }
interface IR { name: string; unitPrice: string; quantity: string; gstRate: string; hsnSac: string; }

/*
 * ONE ADDRESS FIELD SET, shared with the Contacts form through src/lib/address-format.ts.
 *
 * `landmark`, `houseNumber` and `buildingName` are gone from this form's state. They were three
 * extra CRM columns standing in for `locality` and `addressLine2`, and nothing in the payment
 * path reads them: `contact_address._RULES` has eight fields and the `payment_address`
 * projections (the order payload and `for_meta_beneficiary`) project those eight. The stored
 * flat columns are NOT deleted and are NOT overwritten with blanks - the WhatsApp subscribe flow
 * still writes them - they are simply
 * no longer edited here, and `openEditCust` folds whatever is in them into `addressLine2` /
 * `locality` so an existing contact loads with its address intact.
 */
const EMPTY_FORM = {
  name: '', phone: '', email: '', shippingAddress: '', billingAddress: '', gstin: '',
  ...EMPTY_ADDRESS_FIELDS,
};
const NEW_ITEM = (): IR => ( { name: '', unitPrice: '', quantity: '1', gstRate: '18', hsnSac: '' } );
/*
 * THE ONE BRAND, hardcoded. The owner asked for the brand section removed with WECARE.DIGITAL as
 * the default, so the nine-entry list (BNB Club, No Fault, Expo Week, Ritual Guru, Legal Champ,
 * WECARE.DIGITAL, Service Fee, Consultation) is reduced to one and `loadSavedConfig`
 * refuses to restore a saved list over it - otherwise a browser that saved the old config before
 * this change would keep offering all nine forever.
 */
const DEFAULT_BRAND = 'WECARE.DIGITAL';
const EMPTY_INV = { items: [ NEW_ITEM() ] as IR[], shipping: '0', purpose: DEFAULT_BRAND, orderId: '' };
const DEF_CFG: FC = { default_gst_rate: 18, default_shipping: 0, gstin: DEFAULT_GSTIN || '19AAFFW7196L1Z8', default_item_name: 'Services/Goods', purposes: [ DEFAULT_BRAND ] };
const TABS: ShellTab[] = [
  { id: 'create', label: 'Collect' },
  { id: 'invoices', label: 'Invoices' },
];
const CFG_KEY = 'wecare_flow_config';
const loadSavedConfig = (): FC => {
  // `purposes` is pinned AFTER the spread on purpose: the brand list is hardcoded now, so a
  // config saved into localStorage before that decision must not restore the nine old brands.
  try { const s = localStorage.getItem( CFG_KEY ); if ( s ) return { ...DEF_CFG, ...JSON.parse( s ), purposes: DEF_CFG.purposes }; } catch { }
  return DEF_CFG;
};
/*
 * D4, mirrored from `invoice-engine._is_issued` — the ONE question the Edit button turns on.
 *
 * An invoice is a document of record the moment a number leaves the GST series, whatever its
 * status says, and the server refuses a financial edit from that moment on with
 * 409 INVOICE_ISSUED_IMMUTABLE. Since `create_invoice` assigns the number at creation, in
 * practice EVERY invoice this page lists is issued: the Edit button therefore disappears, and
 * the route for a wrong unpaid invoice is Cancel Invoice and raise a new one. Offering an edit
 * that the server will refuse is worse than not offering it.
 *
 * The modal is kept for a row that genuinely carries no number (a legacy or imported invoice),
 * which is the only state in which the edit it sends can succeed.
 */
const UNISSUED_STATUSES = [ '', 'claiming', 'created' ];
const isIssued = ( inv: Invoice ): boolean =>
  Boolean( ( inv.invoiceNumber || '' ).trim() ) || !UNISSUED_STATUSES.includes( inv.status || '' );
const canCancelInvoice = ( inv: Invoice ): boolean =>
  [ 'created', 'pending_payment', 'pending', 'failed' ].includes( ( inv.status || '' ).toLowerCase() )
  && [ '', 'pending', 'failed', 'created' ].includes( ( inv.paymentStatus || '' ).toLowerCase() );
const STATUS_FILTERS = [
  { id: 'active', label: 'Active' },
  { id: 'all', label: 'All' },
  { id: 'created', label: 'Created' },
  { id: 'pending_payment', label: 'Pending' },
  { id: 'paid', label: 'Paid' },
  { id: 'cancelled', label: 'Cancelled' },
];
/*
 * BATCH 2f - the payment path. The nine choosers on this page are now our own combobox, and
 * the one thing that may not change is what they EMIT: the same values, in the same order,
 * with the same visible text as the <option> rows they replaced. The two fixed lists are
 * hoisted here; the brand list is built per render from `config.purposes`, which is loaded
 * state. GOODS_TYPE keeps both literals exactly, because `goodsType` travels into the invoice
 * request at :217 and a third spelling would be a new value rather than a new control.
 */
/* LAYOUT ONLY - the box is the trigger's. Both sit in flex rows inside the invoice detail
   panel and the dues table, so each one states its own flex basis rather than a width. */
const DETAIL_SELECT_STYLE: React.CSSProperties = { flex: 1 };
const DUES_PHONE_SELECT_STYLE: React.CSSProperties = { flex: '0 0 180px' };
const badgeClass = ( inv: Invoice ) => inv.status === 'paid' || inv.paymentStatus === 'captured' ? 'success' : inv.status === 'cancelled' ? 'danger' : 'muted';
const hasPayableDeliveryAddress = ( contact: Contact ): boolean => {
  const a = addressFieldsFromContact( contact );
  return [ a.addressLine1, a.city, a.state, a.postalCode, a.country ].every( v => String( v || '' ).trim().length > 0 );
};

const fmtDate = ( ts: number ) => {
  if ( !ts ) return '\u2014';
  const ms = ts > 1e12 ? ts : ts * 1000;
  return new Date( ms ).toLocaleDateString( 'en-IN', { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'Asia/Kolkata' } );
};
const fmtDateTime = ( ts: number ) => {
  if ( !ts ) return '\u2014';
  const ms = ts > 1e12 ? ts : ts * 1000;
  return new Date( ms ).toLocaleString( 'en-IN', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: true, timeZone: 'Asia/Kolkata' } );
};
const fmtMoney = ( n: number ) => `\u20B9${( n || 0 ).toLocaleString( 'en-IN', { minimumFractionDigits: 2 } )}`;
const PAYMENT_REQUEST_DELIVERY_SUCCESS = new Set( [ 'accepted', 'sent', 'delivered', 'read' ] );
const hasConfirmedPaymentRequestDelivery = ( logs: InvoiceDeliveryLog[] | undefined ): boolean =>
  Boolean( logs?.some( row =>
    row.channel === 'whatsapp_payment'
    && PAYMENT_REQUEST_DELIVERY_SUCCESS.has( String( row.status || '' ).toLowerCase() )
    && !String( row.error || '' ).trim()
  ) );

/*
 * THE ONE SEND-OUTCOME INTERPRETER, shared by all three send paths (the create-and-send flow,
 * the Invoices-mode send/retry button, and anywhere else `sendPaymentLinkResult` is read).
 *
 * The server's `send_payment_link` command answers with distinct, non-interchangeable verdicts and
 * the operator needs DIFFERENT guidance for each — telling them to "retry" a terminally refused
 * send, or to resend one that is already in flight, is how a customer gets charged twice or an
 * operator chases a send that already happened. Routing every path through this function keeps the
 * guidance identical everywhere and keeps the one safety rule in one place: a non-sent command is
 * reconciled against durable delivery evidence (`deliveryConfirmed`) BEFORE any retry is suggested,
 * and nothing here ever triggers a resend.
 *
 * `text` is the actionable core sentence; callers append their own "Open this saved invoice…" /
 * "Check this invoice before retrying." tail where the surface calls for it.
 */
const SEND_SUCCESS_COMMAND = 'WhatsApp payment request sent.';
const SEND_SUCCESS_RECONCILED = 'WhatsApp accepted the payment request for delivery.';
const describeSendOutcome = (
  result: ApiResult<SendPaymentLinkResult>,
  deliveryConfirmed: boolean,
): { tone: 'success' | 'error'; text: string } => {
  // Durable delivery evidence is authoritative over an ambiguous command response, but never over
  // a terminal refusal — a refused send cannot have been delivered, so refusal is checked first.
  const rejected = result.ok
    ? ( result.data.status === 'payment_link_rejected'
        || String( result.data.sendStatus || '' ).toUpperCase() === 'REJECTED' )
    : ( result.failure.status === 409
        || /\brefused\b|\brejected\b/i.test( result.failure.message ) );
  if ( rejected ) {
    return {
      tone: 'error',
      text: 'This payment request was refused and was NOT sent. Cancel and raise the collection again — do not retry. Nothing has been charged.',
    };
  }

  if ( result.ok && result.data.status === 'payment_link_sent' ) {
    return { tone: 'success', text: SEND_SUCCESS_COMMAND };
  }
  if ( deliveryConfirmed ) {
    return { tone: 'success', text: SEND_SUCCESS_RECONCILED };
  }

  if ( result.ok && ( result.data.status === 'send_in_progress' || result.data.deduplicated ) ) {
    return {
      tone: 'error',
      text: 'A send is already in progress; do not resend. Refresh to see its delivery status.',
    };
  }

  // 502 / PENDING / anything else the command could not resolve: genuinely unknown, so reconcile
  // before any retry. "Unknown" never means "not paid" and never means "safe to resend".
  const pending = result.ok
    ? String( result.data.sendStatus || '' ).toUpperCase() === 'PENDING'
    : ( result.failure.status === 502 || result.failure.kind === 'unavailable' );
  if ( pending ) {
    return {
      tone: 'error',
      text: 'Outcome unknown. Reconcile in the ledger before retrying — nothing has been charged.',
    };
  }

  if ( !result.ok ) {
    // A genuine transient/network failure: surface the server's own message and the downstream
    // status when present (Finding 10b), then allow a plain retry.
    const downstream = result.failure.status ? ` (status ${result.failure.status})` : '';
    const retryHint = result.failure.retryable ? ' You can retry.' : '';
    return { tone: 'error', text: `${result.failure.message}${downstream}${retryHint}` };
  }

  // A 200 that is neither sent, rejected, in-progress nor pending — treat as unconfirmed, not sent.
  return {
    tone: 'error',
    text: 'Sending is not confirmed.',
  };
};
/*
 * Why a create produced no invoice, in the server's own words.
 *
 * Two outcomes that must not be confused. A deliberate refusal (any 4xx, or a 5xx the engine
 * marked `retryable`) wrote nothing, so the operator is told what to fix. No answer, a 2xx with
 * no invoice id, or a gateway 5xx is UNKNOWN: the write may have landed, and a second click mints
 * a fresh referenceId the server cannot dedupe against, so the ledger comes before the button.
 */
const CREATE_NOT_CONFIRMED = 'Check Invoices before creating another.';
const describeCreateFailure = ( result: Extract<CreateInvoiceEngineResult, { ok: false }> ): string => {
  const { status, message, retryable } = result;
  if ( status === null ) return `Creation was not confirmed. ${ CREATE_NOT_CONFIRMED }`;
  if ( status < 400 || ( status >= 500 && !retryable ) ) {
    return `Creation was not confirmed (status ${ status }). ${ CREATE_NOT_CONFIRMED }`;
  }
  const said = message ? `: ${ message.replace( /\.$/, '' ) }` : '';
  const next = status === 401 ? ' Sign in again, then retry.' : retryable ? ' You can retry.' : '';
  return `Invoice not created (status ${ status })${ said }.${ next }`;
};

/**
 * THE ADDRESS BLOCK, rendered from `ADDRESS_FIELDS` and composed through `formatAddress`.
 *
 * ONE COMPONENT FOR BOTH CALL SITES on this page - the customer modal and the invoice-edit modal
 * - and the same eight fields the Contacts form renders, because both import the field list from
 * src/lib/address-format.ts rather than spelling it out. The free-text "Delivery Address"
 * textarea that used to sit above each of these blocks is GONE as an input: it is now the
 * read-only derived preview below, so there is exactly one place an address can be typed and
 * exactly one string composed from it. Two inputs for one fact is how the two halves came to
 * disagree in the first place.
 *
 * `fallback` is what the preview shows when nothing has been typed yet: the address string
 * already stored on the record. Without it, opening an existing customer would display an empty
 * preview over a stored address and read as data loss.
 */
const AddressFieldGroup: React.FC<{
  value: AddressFormFields;
  onChange: ( next: AddressFormFields ) => void;
  idPrefix: string;
  fallback?: string;
}> = ( { value, onChange, idPrefix, fallback } ) => {
  const composed = formatAddress( value );
  return (
    <>
      <p style={ { fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--accent)', margin: '8px 0 4px' } }>Delivery Address</p>
      <div className="pf-address-field-grid">
        { ADDRESS_FIELDS.map( spec => (
          <div className="form-group" key={ spec.key }>
            <label htmlFor={ `${idPrefix}-${spec.key}` }>
              { spec.label }{ !spec.required && <span style={ { color: '#8a9490', fontWeight: 400, marginLeft: 5 } }>Optional</span> }
            </label>
            { spec.key === 'country' ? (
              <select
                id={ `${idPrefix}-${spec.key}` }
                value={ value.country }
                onChange={ e => onChange( {
                  ...value,
                  country: e.target.value,
                  countryCode: countryCodeForName( e.target.value ),
                } ) }
              >
                { COUNTRY_OPTIONS.map( option => <option key={ option.code } value={ option.name }>{ option.name }</option> ) }
              </select>
            ) : (
              <input
                id={ `${idPrefix}-${spec.key}` }
                type="text"
                value={ value[ spec.key ] }
                maxLength={ spec.maxLength }
                placeholder={ spec.placeholder }
                onChange={ e => onChange( { ...value, [ spec.key ]: e.target.value } ) }
              />
            ) }
          </div>
        ) ) }
      </div>
      <div className="form-group">
        <span style={ { fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--accent)' } }>Composed address</span>
        <div
          data-address-preview={ idPrefix }
          aria-readonly="true"
          style={ { fontSize: 'var(--text-xs)', color: '#555', background: '#f8faf9', border: '1px solid #e0e8e3', borderRadius: 8, padding: '8px 12px', minHeight: 34, wordBreak: 'break-word' } }
        >
          { composed || fallback || '\u2014' }
        </div>
      </div>
    </>
  );
};

/* ── Component ── */
const PayFlowPage: React.FC<PP> = ( { signOut, user, embedded, mode = 'collect', allowSendInInvoices = false } ) => {
  const router = useRouter();
  const [ flowTab, setFlowTab ] = useState( mode === 'invoices' ? 'invoices' : 'create' );
  const activeFlowTab = embedded ? ( mode === 'invoices' ? 'invoices' : 'create' ) : flowTab;
  const [ openingCreated, setOpeningCreated ] = useState( false );
  const [ customers, setCustomers ] = useState<Contact[]>( [] );
  const [ custSearch, setCustSearch ] = useState( '' );
  const [ custLoading, setCustLoading ] = useState( false );
  const [ editCust, setEditCust ] = useState<Partial<Contact> | null>( null );
  const [ custForm, setCustForm ] = useState( EMPTY_FORM );
  const [ custSaving, setCustSaving ] = useState( false );
  const [ custError, setCustError ] = useState( '' );
  const [ selCustomer, setSelCustomer ] = useState<Contact | null>( null );
  const [ invForm, setInvForm ] = useState( { ...EMPTY_INV } );
  const [ showAdvancedTax, setShowAdvancedTax ] = useState( false );
  const [ invoicePreview, setInvoicePreview ] = useState<api.InvoiceEnginePreview | null>( null );
  const [ previewLoading, setPreviewLoading ] = useState( false );
  const [ previewError, setPreviewError ] = useState( '' );
  const [ servicePrices, setServicePrices ] = useState<Record<string, ServicePrice>>( {} );
  const appliedPresetRef = useRef( '' );
  const appliedCustomerRef = useRef( '' );
  const previewRequestSeq = useRef( 0 );
  const [ creating, setCreating ] = useState( false );
  const [ invoices, setInvoices ] = useState<Invoice[]>( [] );
  // Create's saved-invoice picker never offers Vault/Contribute invoice send.
  const visibleInvoices = allowSendInInvoices
    ? invoices.filter( row => row.entryPoint === 'pay_flow' ) : invoices;
  const [ invLoading, setInvLoading ] = useState( false );
  const [ statusFilter, setStatusFilter ] = useState( 'active' );
  const [ selInvoice, setSelInvoice ] = useState<Invoice | null>( null );
  const [ deliveryLogs, setDeliveryLogs ] = useState<InvoiceDeliveryLog[]>( [] );
  const [ actionLoading, setActionLoading ] = useState( '' );
  const goodsType = 'physical-goods' as const;
  /* WABA1, the only number permitted to take a payment (`wa_payment_request.PAYMENT_SENDERS`).
     This defaulted to WABA2, so every staff send from a freshly loaded page was refused
     WA_PAY_SENDER_NOT_PERMITTED before it reached Meta - a default that guaranteed a refusal. */
  const [ sendPhone, setSendPhone ] = useState( 'phone-number-id-waba1-direct-1016149501586345' );
  const [ remarkModal, setRemarkModal ] = useState<{ inv: Invoice; type: 'remark' | 'refund' | 'credit_note' } | null>( null );
  const [ remarkText, setRemarkText ] = useState( '' );
  const [ remarkAmount, setRemarkAmount ] = useState( '' );
  const [ refundId, setRefundId ] = useState( '' );
  const [ editModal, setEditModal ] = useState<Invoice | null>( null );
  // `shipping` and `discount` are GONE from this form (D4/D6). They are financial fields, and
  // the server refuses them on an issued invoice - which is every invoice that has a number -
  // so an input for them could only produce a 409. Subtractive: nothing replaces them here, and
  // a wrong amount is corrected by cancelling and reissuing.
  const [ editForm, setEditForm ] = useState<{ customerName: string; customerPhone: string; customerEmail: string; purpose: string; orderId: string; notes: string; shippingAddress: string; billingAddress: string }>( { customerName: '', customerPhone: '', customerEmail: '', purpose: '', orderId: '', notes: '', shippingAddress: '', billingAddress: '' } );
  /* The invoice-edit modal's address, structured. `update_invoice` accepts only the two address
     STRINGS (handler.py's `allowed` list), so this composes into them - which is exactly the
     point: one typed field set, one composed string, no second free-text input to disagree. */
  const [ editAddress, setEditAddress ] = useState<AddressFormFields>( EMPTY_ADDRESS_FIELDS );
  /*
   * DISCOUNT: nothing about one ever leaves this form.
   *
   * There is no state here for a discount amount and no arithmetic anywhere in this file that
   * touches one. `redemption` holds only what the SERVER returned on a 201, so the applied Delight
   * figure can be previewed - the same discipline cart.tsx follows: a browser-computed discount is
   * a figure the customer can see and the ledger never agreed to.
   */
  // The always-on Delight discount is applied automatically by the invoice engine on every
  // customer-origin invoice. There is no coupon code to type and no manual discount to set, so
  // the only redemption state is the SERVER's answer, held to preview the applied Delight line.
  const invoiceCreateInFlight = useRef( false );
  // The exact send-outcome sentence from `describeSendOutcome`, held so the created-invoice card
  // renders the same state-aware text the banner showed. Empty for a plain save (no send).
  const [ createdDeliveryMessage, setCreatedDeliveryMessage ] = useState( '' );
  const [ createdDelivery, setCreatedDelivery ] = useState<'saved' | 'sending' | 'sent' | 'unconfirmed'>( 'saved' );
  const [ redemption, setRedemption ] = useState<api.CreateInvoiceEngineResponse | null>( null );
  const [ config, setConfig ] = useState<FC>( () => loadSavedConfig() );
  const [ configSaving, setConfigSaving ] = useState( false );
  const [ msg, setMsg ] = useState<{ text: string; type: 'success' | 'error' } | null>( null );
  // Success banners self-dismiss; error banners are STICKY. A money/delivery error that vanishes
  // after four seconds is how an operator misses "do not retry" and resends — errors stay until the
  // ✕ is pressed or another banner replaces them.
  const showMsg = ( text: string, type: 'success' | 'error' = 'success' ) => {
    setMsg( { text, type } );
    if ( type !== 'error' ) setTimeout( () => setMsg( null ), 4000 );
  };
  const confirm = useConfirm();

  /* Loaders */
  const loadCustomers = useCallback( async () => {
    setCustLoading( true );
    try { const c = await api.listContacts(); setCustomers( c || [] ); } catch ( e ) { console.error( e ); }
    setCustLoading( false );
  }, [] );
  const loadInvoices = useCallback( async () => {
    setInvLoading( true );
    try
    {
      const params = [ 'all', 'active' ].includes( statusFilter ) ? {} : { status: statusFilter };
      const r = await api.listInvoicesEngine( params );
      const rows = r.invoices || [];
      setInvoices( statusFilter === 'active' ? rows.filter( i => i.status !== 'cancelled' ) : rows );
    } catch ( e ) { console.error( e ); }
    setInvLoading( false );
  }, [ statusFilter ] );
  const loadDeliveryLogs = useCallback( async ( id: string ) => {
    try { const r = await api.getInvoiceDeliveryLog( id ); setDeliveryLogs( r.deliveryLogs || [] ); } catch ( e ) { console.error( e ); }
  }, [] );
  useEffect( () => { loadCustomers(); loadInvoices(); }, [ loadCustomers, loadInvoices ] );

  // After creating an invoice, the new Collect -> Create -> Saved invoices link
  // carries the exact invoice id. The summary list may not contain it because
  // lists are paged. Fetch the authoritative detail directly, then select only
  // an actual Collect-created invoice. Never open another service's payment
  // record as a sendable Collect invoice. This is a read-only lookup.
  useEffect( () => {
    if ( !router.isReady || mode !== 'invoices' || !allowSendInInvoices ) return;
    const raw = router.query.invoice;
    const invoiceId = ( Array.isArray( raw ) ? raw[ 0 ] || '' : raw || '' ).trim();
    if ( !invoiceId ) return;
    let active = true;
    void api.getInvoiceEngine( invoiceId )
      .then( invoice => {
        if ( !active ) return;
        if ( !invoice || invoice.entryPoint !== 'pay_flow' ) {
          setSelInvoice( null );
          setMsg( { text: 'This invoice is not available for Collect Review & Pay.', type: 'error' } );
          return;
        }
        setSelInvoice( invoice );
        setInvoices( previous => [ invoice, ...previous.filter( row => row.invoiceId !== invoice.invoiceId ) ] );
        void loadDeliveryLogs( invoice.invoiceId );
      } )
      .catch( () => {
        if ( active ) {
          setSelInvoice( null );
          setMsg( { text: 'Saved invoice could not be opened. Check the invoice ledger before sending.', type: 'error' } );
        }
      } );
    return () => { active = false; };
  }, [ router.isReady, router.query.invoice, mode, allowSendInInvoices, loadDeliveryLogs ] );

  useEffect( () => {
    const raw = router.query.customer;
    const wanted = Array.isArray( raw ) ? ( raw[ 0 ] || '' ) : ( raw || '' );
    if ( !wanted || appliedCustomerRef.current === wanted || customers.length === 0 ) return;
    const match = customers.find( customer =>
      customer.contactId === wanted ||
      customer.customerUuid === wanted ||
      customer.id === wanted ||
      customer.customerDisplayId === wanted
    );
    if ( match ) {
      setSelCustomer( match );
      appliedCustomerRef.current = wanted;
    }
  }, [ router.query.customer, customers ] );

  /* Customer handlers */
  const openEditCust = ( c: Contact, focus?: 'phone' | 'address' ) => {
    setCustError( '' );
    const address = addressFieldsFromContact( c );
    const composed = contactDeliveryAddress( c );
    setEditCust( c );
    setCustForm( {
      name: c.name || '', phone: c.phone || '', email: c.email || '',
      shippingAddress: composed, billingAddress: composed || c.billingAddress || '',
      gstin: ( c as any ).gstin || '',
      ...address,
    } );
    if ( focus ) {
      window.setTimeout( () => {
        const targetId = focus === 'phone' ? 'pf-cust-phone' : 'pf-cust-addr-addressLine1';
        document.getElementById( targetId )?.focus();
      }, 0 );
    }
  };
  const closeEditCust = () => { setEditCust( null ); setCustForm( EMPTY_FORM ); setCustError( '' ); };
  const saveCust = async () => {
    if ( !editCust ) return;
    if ( !custForm.name.trim() ) { setCustError( 'Enter the full name.' ); return; }
    if ( !custForm.phone.trim() ) { setCustError( 'Enter the WhatsApp number, including its country code.' ); return; }
    setCustError( '' );
    setCustSaving( true );
    try
    {
      const composed = formatAddress( custForm );
      const saveData = {
        name: custForm.name.trim(), phone: custForm.phone.trim(),
        // Hidden email/GSTIN values are retained on the canonical record by omission.
        // The composed string, so the two legacy address strings cannot disagree with the fields.
        // A composition is only written when there is something to compose: an untouched form must
        // not blank a stored address.
        shippingAddress: composed || custForm.shippingAddress || undefined,
        billingAddress: composed || custForm.billingAddress || undefined,
        // The flat CRM columns, still written because other readers (the contacts table, the
        // invoice-engine fallback lookup) read them. `landmark` carries `locality`: one concept,
        // and `locality` is the name `contact_address._RULES` gives it.
        addressLine1: custForm.addressLine1 || undefined,
        addressLine2: custForm.addressLine2 || undefined,
        landmark: custForm.locality || undefined,
        city: custForm.city || undefined,
        state: custForm.state || undefined,
        postalCode: custForm.postalCode || undefined,
        country: custForm.country || undefined,
        // THE VALIDATED WRITE PATH, and the same one the Contacts form uses. `undefined` until the
        // four required fields are present, because the server refuses a partial address with
        // 400 FIELD_REQUIRED and writes nothing - which would fail the whole customer save over a
        // half-typed address.
        address: addressPayload( custForm ),
        /*
         * Meta's `shipping_info.addresses[]` keys, UNCHANGED.
         *
         * FEAT-003's step said to keep the keys `payment_address.for_meta_beneficiary` expects.
         * Reading that module shows those are the BENEFICIARY keys (`address_line1`, `postal_code`,
         * …), which is a different Meta block from the one this field holds. Four live readers
         * parse THESE names - invoice-engine's display-address fallback and `shipping_info`
         * builder, outbound-whatsapp, inbound-whatsapp-handler and whatsapp-business-api all read
         * `in_pin_code` / `address` / `landmark_area` - so renaming them would break the WhatsApp
         * address prompt. The key set stays; only which field feeds each key changed.
         */
        shippingAddressJson: JSON.stringify( {
          name: custForm.name, phone_number: custForm.phone?.replace( '+', '' ) || '',
          address: custForm.addressLine1, city: custForm.city, state: custForm.state,
          in_pin_code: custForm.postalCode, landmark_area: custForm.locality,
        } ),
      };
      if ( editCust.id ) {
        const result = await api.updateContactResult( editCust.id, saveData as any );
        if ( !result.ok ) {
          const message = result.failure.message || 'Customer update was refused.';
          setCustError( message );
          showMsg( message, 'error' );
          return;
        }
        if ( !result.data ) {
          const message = 'Customer update returned no refreshed record. Reload before collecting payment.';
          setCustError( message );
          showMsg( message, 'error' );
          return;
        }
        if ( selCustomer?.id === editCust.id ) setSelCustomer( result.data );
        showMsg( 'Customer updated' );
      } else {
        const result = await api.createContactResult( saveData as any );
        if ( !result.ok ) {
          const message = result.failure.message || 'Customer creation was refused.';
          setCustError( message );
          showMsg( message, 'error' );
          return;
        }
        showMsg( 'Customer created' );
      }
      closeEditCust();
      void loadCustomers();
    } catch ( e ) { setCustError( 'Could not save customer. Check your connection and try again.' ); showMsg( 'Save failed', 'error' ); }
    finally { setCustSaving( false ); }
  };

  useEffect( () => {
    let active = true;
    fetchServicePrices().then( prices => { if ( active ) setServicePrices( prices ); } );
    return () => { active = false; };
  }, [] );

  const applyServicePreset = ( choice: ServiceChoice ) => {
    if ( choice.needsTarget ) {
      // An unbound invoice does not create a Vault file entitlement or a
      // service intent. Refuse old bookmarked ?preset= URLs, not just new buttons.
      showMsg( `${choice.label} requires a verified service target. Open the service first; nothing was added or charged.`, 'error' );
      return;
    }
    const price = servicePrices[ choice.slug ];
    if ( !price?.available ) {
      showMsg( `${ choice.label } live price is unavailable. Nothing was added.`, 'error' );
      return;
    }
    const expressPaise = price.breakdown?.expressPaise || 0;
    setInvForm( current => ( {
      ...current,
      items: [ {
        name: choice.label,
        unitPrice: rupeesFromPaise( price.paise ),
        quantity: '1',
        gstRate: '18',
        hsnSac: '',
      } ],
      shipping: rupeesFromPaise( expressPaise ),
    } ) );
    setShowAdvancedTax( false );
  };

  useEffect( () => {
    const raw = router.query.preset;
    const preset = Array.isArray( raw ) ? ( raw[ 0 ] || '' ) : ( raw || '' );
    if ( !preset || appliedPresetRef.current === preset ) return;
    const choice = SERVICE_CHOICES.find( item => item.slug === preset );
    const price = servicePrices[ preset ];
    if ( !choice || !price?.available ) return;
    appliedPresetRef.current = preset;
    applyServicePreset( choice );
  }, [ router.query.preset, servicePrices ] );

  /* Invoice form handlers */
  const buildInvoiceRequest = useCallback( ( referenceId?: string ): CreateInvoiceEngineRequest | null => {
    if ( !selCustomer ) return null;
    const a = addressFieldsFromContact( selCustomer );
    const req: CreateInvoiceEngineRequest = {
      customerPhone: selCustomer.phone,
      customerEmail: selCustomer.email || '',
      customerName: selCustomer.name,
      contactId: selCustomer.id,
      shippingAddress: contactDeliveryAddress( selCustomer ),
      billingAddress: contactDeliveryAddress( selCustomer ) || selCustomer.billingAddress || '',
      addressLine1: a.addressLine1,
      addressLine2: a.addressLine2,
      city: a.city,
      state: a.state,
      postalCode: a.postalCode,
      landmark: a.locality,
      countryCode: a.countryCode || countryCodeForName( a.country ),
      goodsType,
      items: invForm.items.map( it => ( {
        name: it.name || config.default_item_name,
        amount: parseFloat( it.unitPrice ) || 0,
        quantity: parseInt( it.quantity ) || 1,
        gstRate: it.gstRate.trim() === '' ? config.default_gst_rate : Number( it.gstRate ),
        hsnSac: it.hsnSac.trim(),
      } ) ),
      shipping: parseFloat( invForm.shipping ) || 0,
      gstRate: config.default_gst_rate,
      purpose: DEFAULT_BRAND,
      orderId: invForm.orderId,
      gstin: config.gstin,
      buyerGstin: ( selCustomer as Contact & { gstin?: string } ).gstin || undefined,
      entryPoint: 'pay_flow',
    };
    if ( referenceId ) req.referenceId = referenceId;
    return req;
  }, [ selCustomer, invForm, config.default_item_name, config.default_gst_rate, config.gstin ] );

  useEffect( () => {
    if ( !selCustomer || !hasPayableDeliveryAddress( selCustomer )
      || !invForm.items.some( it => parseFloat( it.unitPrice ) > 0 ) ) {
      previewRequestSeq.current += 1;
      setInvoicePreview( null );
      setPreviewLoading( false );
      setPreviewError( '' );
      return;
    }

    const request = buildInvoiceRequest();
    if ( !request ) return;
    const seq = ++previewRequestSeq.current;
    setPreviewLoading( true );
    setPreviewError( '' );

    const timer = window.setTimeout( async () => {
      try {
        const result = await api.previewInvoiceEngine( request, true );
        if ( seq !== previewRequestSeq.current ) return;
        if ( result ) {
          setInvoicePreview( result );
          setPreviewError( '' );
        } else {
          setInvoicePreview( null );
          setPreviewError( 'Preview unavailable. The invoice can still be created from server pricing.' );
        }
      } catch {
        if ( seq !== previewRequestSeq.current ) return;
        setInvoicePreview( null );
        setPreviewError( 'Preview unavailable. The invoice can still be created from server pricing.' );
      } finally {
        if ( seq === previewRequestSeq.current ) setPreviewLoading( false );
      }
    }, 750 );

    return () => window.clearTimeout( timer );
  }, [ buildInvoiceRequest, selCustomer, invForm.items ] );

  const updateItem = ( idx: number, field: keyof IR, val: string ) => {
    const items = [ ...invForm.items ]; items[ idx ] = { ...items[ idx ], [ field ]: val }; setInvForm( { ...invForm, items } );
  };
  const addItem = () => setInvForm( { ...invForm, items: [ ...invForm.items, NEW_ITEM() ] } );
  const removeItem = ( idx: number ) => { if ( invForm.items.length <= 1 ) return; setInvForm( { ...invForm, items: invForm.items.filter( ( _, i ) => i !== idx ) } ); };
  const submitInvoice = async ( sendAfterCreate = false ) => {
    if ( invoiceCreateInFlight.current ) return;
    if ( !selCustomer ) { showMsg( 'Select a customer first', 'error' ); return; }
    if ( !hasPayableDeliveryAddress( selCustomer ) ) {
      showMsg( 'Complete Street address, City, State / region, Postal code and Country before creating the invoice.', 'error' );
      openEditCust( selCustomer );
      return;
    }
    if ( !invForm.items.some( it => parseFloat( it.unitPrice ) > 0 ) ) { showMsg( 'Add at least one item', 'error' ); return; }
    invoiceCreateInFlight.current = true;
    setCreating( true );
    try
    {
      const req = buildInvoiceRequest(
        'WD-PAY-' + crypto.randomUUID().replace( /-/g, '' ).slice( 0, 16 ).toUpperCase()
      );
      if ( !req ) {
        showMsg( 'Select a customer first', 'error' );
        return;
      }
      // The result wrapper keeps the server's refusal, so the banner can say WHY a create was
      // refused instead of "Create failed". The success body carries the applied Delight figure
      // for the preview below.
      const created = await api.createInvoiceEngineResult( req );
      if ( created.ok )
      {
        const r = created.invoice;
        showMsg( `Review invoice ${r.invoiceNumber} and send the payment request below.` );
        // Every figure here is the SERVER's. Nothing on this page recomputes a discount.
        setRedemption( r );
        setCreatedDelivery( 'saved' );
        setCreatedDeliveryMessage( '' );
        setInvForm( { ...EMPTY_INV, items: [ NEW_ITEM() ] } );
        setShowAdvancedTax( false );
        setSelCustomer( null );
        if ( sendAfterCreate ) {
          setCreatedDelivery( 'sending' );
          try {
            const sent = await api.sendPaymentLinkResult( r.invoiceId, sendPhone );

            // The command response can be ambiguous even after Meta has accepted the message.
            // Reconcile once against the durable invoice delivery log before deciding how to
            // describe the outcome. This is a read only check and never re-sends the request.
            let deliveryConfirmed = false;
            if ( !( sent.ok && sent.data.status === 'payment_link_sent' ) ) {
              try {
                const delivery = await api.getInvoiceDeliveryLog( r.invoiceId );
                deliveryConfirmed = hasConfirmedPaymentRequestDelivery( delivery.deliveryLogs );
              } catch {
                // A failed read must not invent success.
              }
            }

            // ONE interpreter for every send path. The card and the banner show the same sentence.
            const outcome = describeSendOutcome( sent, deliveryConfirmed );
            setCreatedDeliveryMessage( outcome.text );
            setCreatedDelivery( outcome.tone === 'success' ? 'sent' : 'unconfirmed' );
            showMsg( outcome.text, outcome.tone );
          } catch {
            setCreatedDelivery( 'unconfirmed' );
            setCreatedDeliveryMessage( 'Sending is not confirmed.' );
            showMsg( 'Sending is not confirmed. Open this saved invoice and check its status before retrying.', 'error' );
          }
        }
        // Avoid an immediate full invoice-list reload after create. One detail read gives us the
        // authoritative stored row and lets the existing list update in place; this removes a
        // redundant list scan from the hottest staff collection path.
        try {
          const createdInvoice = await api.getInvoiceEngine( r.invoiceId );
          if ( createdInvoice ) {
            setInvoices( current => [
              createdInvoice,
              ...current.filter( row => row.invoiceId !== createdInvoice.invoiceId ),
            ] );
          }
        } catch {
          // The create itself succeeded; a failed enrichment read must not turn success into error.
        }
      }
      else
      {
        setRedemption( null );
        // Refusals with one clear fix get that fix; everything else says what the server said.
        const fixes: Record<string, string> = {
          DELIVERY_REQUIRED: 'Add a complete structured delivery address before creating this physical invoice.',
          INVALID_PIN: 'The saved postal code is not payable for WhatsApp payment. Update the customer address.',
          INVALID_AMOUNT: 'Check item amount, quantity, GST and delivery values.',
        };
        showMsg( fixes[ created.errorCode ] || describeCreateFailure( created ), 'error' );
      }
    } catch ( e ) { showMsg( 'Creation was not confirmed. Check Invoices before creating another.', 'error' ); }
    finally { invoiceCreateInFlight.current = false; setCreating( false ); }
  };

  /* Invoice action handlers */
  /* ONE entry, and it is WABA1. All three "Send from" selectors drive `doSendPaymentLink`, and
     the server's allowlist (`wa_payment_request.PAYMENT_SENDERS`) permits exactly this id - so
     listing WABA2 was offering a sender whose every send is refused. The Select stays: with one
     option it still states which number the customer will see, which is worth more than the
     markup it costs. The allowlist keeps its one home on the server; no env var is added here. */
  const PHONE_OPTIONS = [
    { id: 'phone-number-id-waba1-direct-1016149501586345', label: '+91 93309 94400' },
  ];
  /* The phone id is the Meta phone-number id the payment template is sent FROM. */
  const phoneSelectOptions: SelectOption[] = PHONE_OPTIONS.map( p => ( { value: p.id, label: p.label } ) );
  /* `brandOptions` (and the "— Select —" empty row it opened with) stood here and is GONE with
     the two Brand choosers it fed: `purposes` is the single entry WECARE.DIGITAL, so the list
     could only ever offer one brand and a placeholder. `config.purposes` is still read by the
     settings tab, so the state it comes from is untouched. */
  const doSendPaymentLink = async ( inv: Invoice ) => {
    // Create is the only embedded surface allowed to send a saved invoice.
    // Other service invoices must use their own verified payment workflow.
    if ( mode === 'invoices' && ( !allowSendInInvoices || inv.entryPoint !== 'pay_flow' ) ) {
      showMsg( 'This invoice cannot be sent from Collect Create.', 'error' );
      return;
    }
    const approved = await confirm( {
      title: 'Send this invoice payment request?',
      message: 'Confirm the invoice, saved customer and amount. WhatsApp acceptance does not mean payment. If an earlier send is uncertain, check delivery evidence before retrying.',
      confirmText: 'Send payment request',
    } );
    if ( !approved ) return;
    setActionLoading( 'send' );
    try
    {
      const r = await api.sendPaymentLinkResult( inv.invoiceId, sendPhone );
      // Reconcile an ambiguous command against the durable delivery log before describing the
      // outcome. Read only; this never re-sends the payment request.
      let deliveryConfirmed = false;
      if ( !( r.ok && r.data.status === 'payment_link_sent' ) ) {
        try {
          const delivery = await api.getInvoiceDeliveryLog( inv.invoiceId );
          deliveryConfirmed = hasConfirmedPaymentRequestDelivery( delivery.deliveryLogs );
        } catch {
          // Keep the command result if delivery evidence is unavailable.
        }
      }
      // SAME interpreter as the create-and-send flow, so the guidance is identical everywhere.
      const outcome = describeSendOutcome( r, deliveryConfirmed );
      showMsg( outcome.text, outcome.tone );
      loadInvoices();
    } catch ( e ) { showMsg( 'Send failed', 'error' ); }
    setActionLoading( '' );
  };
  // Every issued invoice retains its GST number. There is no safe hard-delete pathway.
  // Void is conditional on the current unpaid money state, enforced again by invoice-engine.
  const doCancelInvoice = async ( inv: Invoice ) => {
    if ( !canCancelInvoice( inv ) ) {
      showMsg( 'Only an eligible unpaid invoice can be voided. Use refund/credit-note review for paid records.', 'error' );
      return;
    }
    const ok = await confirm( {
      title: 'Void this unpaid invoice?',
      message: 'The invoice number, line items, payment/delivery evidence and GST history will be kept. WhatsApp messages already sent cannot be recalled. Paid invoices cannot be voided.',
      confirmText: 'Void invoice',
      danger: true,
    } );
    if ( !ok ) return;
    setActionLoading( 'cancel' );
    try {
      const result = await api.cancelInvoiceResult( inv.invoiceId, 'Voided from Workspace Payments after staff confirmation' );
      if ( result.ok && result.data?.status === 'cancelled' ) {
        showMsg( 'Invoice voided; its GST number and history are retained.' );
        setSelInvoice( null );
        loadInvoices();
      } else if ( !result.ok ) {
        showMsg( result.failure.message || 'Invoice void was refused.', 'error' );
      } else {
        showMsg( 'Void not confirmed. Refresh the invoice status before retrying.', 'error' );
      }
    } catch {
      showMsg( 'Void request failed. Check the invoice before retrying.', 'error' );
    } finally {
      setActionLoading( '' );
    }
  };
  const doGenerateImage = async ( inv: Invoice ) => {
    setActionLoading( 'img' );
    try
    {
      await api.generateInvoiceImage( inv.invoiceId );
      const refreshed = await api.getInvoiceEngine( inv.invoiceId );
      if ( refreshed ) setSelInvoice( refreshed );
      showMsg( 'Invoice image generated' );
    } catch ( e ) { showMsg( 'Image generation failed', 'error' ); }
    setActionLoading( '' );
  };
  const downloadGstWorkpaper = ( inv: Invoice ) => {
    if ( !inv.gstWorkpaper ) { showMsg( 'GST workpaper is unavailable for this invoice', 'error' ); return; }
    const blob = new Blob( [ JSON.stringify( inv.gstWorkpaper, null, 2 ) + '\n' ], { type: 'application/json' } );
    const url = URL.createObjectURL( blob );
    const link = document.createElement( 'a' );
    link.href = url;
    link.download = `wecare-gst-workpaper-${inv.referenceId || inv.invoiceNumber || inv.invoiceId}.json`;
    document.body.appendChild( link );
    link.click();
    link.remove();
    URL.revokeObjectURL( url );
  };

  const openRemarkModal = ( inv: Invoice, type: 'remark' | 'refund' | 'credit_note' ) => {
    setRemarkModal( { inv, type } );
    setRemarkText( '' );
    setRemarkAmount( '' );
    setRefundId( inv.refundId || '' );
  };
  const submitRemark = async () => {
    if ( !remarkModal ) return;
    if ( remarkModal.type === 'refund' && !refundId.trim() )
    {
      showMsg( 'Provider refund ID is required. This screen does not initiate refunds.', 'error' );
      return;
    }
    setActionLoading( 'remark' );
    try
    {
      const r = await api.addInvoiceRemark(
        remarkModal.inv.invoiceId,
        remarkModal.type,
        remarkText,
        parseFloat( remarkAmount ) || 0,
        remarkModal.type === 'refund'
          ? { refundId: refundId.trim(), paymentId: remarkModal.inv.paymentId }
          : undefined,
      );
      if ( r )
      {
        showMsg( remarkModal.type === 'refund'
          ? 'Refund evidence verified and reconciled'
          : `${remarkModal.type === 'remark' ? 'Remark' : 'Credit note record'} added` );
        setRemarkModal( null );
        loadInvoices();
      } else
      {
        showMsg( remarkModal.type === 'refund'
          ? 'Refund could not be verified. No refund was initiated and payment state was not changed.'
          : 'Failed', 'error' );
      }
    } catch ( e )
    {
      showMsg( remarkModal.type === 'refund'
        ? 'Refund could not be verified. No refund was initiated and payment state was not changed.'
        : 'Failed', 'error' );
    }
    setActionLoading( '' );
  };
  const openEditModal = ( inv: Invoice ) => {
    setEditModal( inv );
    // An invoice row carries only the two address STRINGS, so the structured block opens empty
    // and the stored string shows as the preview's fallback. Typing anything composes a new
    // string; typing nothing leaves the stored one exactly as it is.
    setEditAddress( EMPTY_ADDRESS_FIELDS );
    setEditForm( {
      customerName: inv.customerName || '',
      customerPhone: inv.customerPhone || '',
      customerEmail: inv.customerEmail || '',
      purpose: DEFAULT_BRAND,
      orderId: inv.orderId || '',
      notes: inv.notes || '',
      shippingAddress: inv.shippingAddress || '',
      billingAddress: inv.billingAddress || '',
    } );
  };
  const submitEdit = async () => {
    if ( !editModal ) return;
    setActionLoading( 'edit' );
    try
    {
      // One composition, one string. `update_invoice`'s `allowed` list takes shippingAddress and
      // billingAddress only, so the eight typed fields land there - and an untouched block
      // composes to '' and leaves the stored value in place rather than blanking it.
      const composedAddress = formatAddress( editAddress );
      const r = await api.updateInvoiceEngine( editModal.invoiceId, {
        customerName: editForm.customerName,
        customerPhone: editForm.customerPhone,
        customerEmail: editForm.customerEmail,
        purpose: DEFAULT_BRAND,
        orderId: editForm.orderId,
        notes: editForm.notes,
        shippingAddress: composedAddress || editForm.shippingAddress,
        billingAddress: composedAddress || editForm.billingAddress,
      } );
      if ( r ) { showMsg( 'Invoice updated' ); setEditModal( null ); setSelInvoice( null ); loadInvoices(); }
      else showMsg( 'Update failed', 'error' );
    } catch ( e ) { showMsg( 'Update failed', 'error' ); }
    setActionLoading( '' );
  };
  const openCreatedInvoice = async () => {
    if ( !redemption ) return;
    setOpeningCreated( true );
    try {
      await router.push( {
        pathname: '/workspace/payments',
        query: { view: 'collect', tab: 'create', invoices: 'saved', invoice: redemption.invoiceId },
      } );
    } catch { showMsg( 'Could not open Invoices. The saved invoice remains available there.', 'error' ); }
    finally { setOpeningCreated( false ); }
  };
  const selectInvoice = async ( inv: Invoice ) => {
    // The list endpoint intentionally stays light. The detail call adds items + signed asset URLs,
    // so the right pane shows the ACTUAL generated receipt rather than a browser imitation.
    setSelInvoice( inv );
    loadDeliveryLogs( inv.invoiceId );
    try
    {
      const full = await api.getInvoiceEngine( inv.invoiceId );
      if ( full ) setSelInvoice( full );
    } catch {
      // Keep the list row visible if detail enrichment is temporarily unavailable.
    }
  };

  /* Computed */
  const filteredCust = customers.filter( c => {
    if ( !custSearch ) return true;
    const q = custSearch.toLowerCase();
    return ( c.name || '' ).toLowerCase().includes( q ) || ( c.phone || '' ).includes( q ) || ( c.email || '' ).toLowerCase().includes( q );
  } );
  const invStats = {
    total: invoices.length,
    paid: invoices.filter( i => i.status === 'paid' || i.paymentStatus === 'captured' ).length,
    pending: invoices.filter( i => i.status === 'pending_payment' ).length,
    totalAmt: invoices.reduce( ( s, i ) => s + i.total, 0 ),
  };

  /* ═══ RENDER ═══ */
  const shellContent = (
    <PageShell
      title={ activeFlowTab === 'invoices' ? 'Invoices' : 'Collect payment' }
      subtitle={ activeFlowTab === 'invoices'
        ? 'Invoice records, payment actions, delivery evidence and fulfilment.'
        : 'Create a server-authoritative invoice and optionally send its payment request.' }
      tabs={ TABS }
      activeTab={ activeFlowTab }
      onTabChange={ setFlowTab }
      defaultTab={ activeFlowTab }
      showChrome={ !embedded }
    >
      { ( activeTab ) => (
        <div className="inner-page pf-auth-surface">
          { msg && <div className={ `msg-bar ${msg.type}` } style={ { margin: '0 0 16px' } }>{ msg.text }<button onClick={ () => setMsg( null ) } style={ { background: 'none', border: 'none', cursor: 'pointer', marginLeft: 8 } }>{ '\u2715' }</button></div> }

              { editCust && (
                <div className="pf-modal-overlay" onClick={ closeEditCust }>
                  <div className="pf-modal-box pf-customer-editor" role="dialog" aria-modal="true" aria-label={ editCust.id ? 'Edit Customer' : 'New Customer' } onClick={ e => e.stopPropagation() }>
                    <div className="pf-modal-header">
                      <h3>{ editCust.id ? 'Edit Customer' : 'New Customer' }</h3>
                      <Button variant="ghost" size="sm" onClick={ closeEditCust }>{ '\u2715' }</Button>
                    </div>
                    <div className="form-group"><label htmlFor="pf-cust-name">Full name *</label><input id="pf-cust-name" type="text" value={ custForm.name } onChange={ e => { setCustForm( { ...custForm, name: e.target.value } ); setCustError( '' ); } } placeholder="Enter full name" /></div>
                    <div className="form-group"><label htmlFor="pf-cust-phone">Linked WhatsApp number *</label><input id="pf-cust-phone" type="tel" value={ custForm.phone } onChange={ e => { setCustForm( { ...custForm, phone: e.target.value } ); setCustError( '' ); } } placeholder="Include country code" /></div>
                    { /* ONE address input group. The free-text "Delivery Address" textarea that
                         used to sit here is the read-only composed preview inside this block
                         now, so the eight fields are the only place an address is typed. */ }
                    <AddressFieldGroup
                      idPrefix="pf-cust-addr"
                      value={ custForm }
                      onChange={ next => { setCustForm( { ...custForm, ...next } ); setCustError( '' ); } }
                      fallback={ custForm.shippingAddress }
                    />
                    { custError && <div className="pf-modal-error" role="alert">{ custError }</div> }
                    <div className="pf-modal-actions">
                      <Button variant="secondary" size="sm" onClick={ closeEditCust }>Cancel</Button>
                      <Button variant="primary" size="sm" loading={ custSaving } onClick={ saveCust }>Save</Button>
                    </div>
                  </div>
                </div>
              ) }

          {/* CUSTOMERS TAB */ }
          { activeTab === 'customers' && (
            <div className="pf-tab-body">
              <div className="pf-toolbar">
                <input className="search-input" placeholder="Search customers\u2026" value={ custSearch } onChange={ e => setCustSearch( e.target.value ) } />
                <Button variant="primary" size="sm" onClick={ () => { setEditCust( {} as Contact ); setCustForm( EMPTY_FORM ); } }>+ New Customer</Button>
                <Button variant="secondary" size="sm" icon="refresh" loading={ custLoading } onClick={ loadCustomers }>Refresh</Button>
              </div>
              <div className="stats-grid" style={ { marginBottom: 16 } }>
                <div className="stat-card accent"><div className="pf-stat-value">{ customers.length }</div><div className="pf-stat-label">Total Customers</div></div>
              </div>
              <div className="table-container">
                <table className="inner-table">
                  <thead><tr><th>#</th><th>Name</th><th>Phone</th><th>Email</th><th>Delivery Address</th><th>Updated</th><th>Actions</th></tr></thead>
                  <tbody>
                    { filteredCust.length === 0 && <tr className="empty-row"><td colSpan={ 7 }>No customers found</td></tr> }
                    { filteredCust.map( ( c, i ) => (
                      <tr key={ c.id }>
                        <td>{ i + 1 }</td>
                        <td style={ { fontWeight: 600 } }>{ c.name || '\u2014' }</td>
                        <td>{ c.phone || '\u2014' }</td>
                        <td>{ c.email || '\u2014' }</td>
                        <td className="pf-cell-truncate">{ c.shippingAddress || '\u2014' }</td>
                        <td>{ fmtDate( new Date( c.updatedAt || c.createdAt || '' ).getTime() ) }</td>
                        <td><Button variant="ghost" size="sm" onClick={ () => openEditCust( c ) }>Edit</Button></td>
                      </tr>
                    ) ) }
                  </tbody>
                </table>
              </div>
            </div>
          ) }

          {/* CREATE INVOICE TAB */ }
          { activeTab === 'create' && (
            <div className="pf-tab-body">
              { /*
                 * WHAT THE SERVER DECIDED ABOUT THE Delight discount.
                 *
                 * Outside the customer-step branch on purpose: a successful create clears
                 * `selCustomer` to reset the form, so anything rendered inside that branch
                 * unmounts at exactly the moment it has something to say. The figure below is
                 * read straight off the response — there is no arithmetic on this page that
                 * produces a discount.
                 */ }
              { redemption && (
                <div className="inner-card pf-created-card">
                  <div className="pf-created-head">
                    <div>
                      <div className="pf-created-kicker">Invoice created</div>
                      <h4>{ redemption.invoiceNumber }</h4>
                      <div className="pf-created-ref">{ redemption.referenceId }</div>
                    </div>
                    <div className="pf-created-amount">{ fmtMoney( redemption.total ) }</div>
                  </div>
                  <div className={ `pf-created-state ${createdDelivery}` }>
                    { createdDelivery === 'sent' ? ( createdDeliveryMessage || 'WhatsApp payment request sent.' ) : createdDelivery === 'sending' ? 'Sending the WhatsApp payment request…' : createdDelivery === 'unconfirmed' ? `${createdDeliveryMessage || 'Sending is not confirmed.'} Open this saved invoice and check its status before retrying.` : 'Invoice saved without sending a WhatsApp payment request.' }
                  </div>
                  <Button variant="primary" size="sm" loading={ openingCreated } onClick={ openCreatedInvoice }>{ createdDelivery === 'saved' ? 'Review and send payment request' : 'View payment request' }</Button>
                  { typeof redemption.couponDiscount === 'number' && redemption.couponDiscount > 0 && (
                    <>
                      <p>Applied on the last invoice</p>
                      <div className="pf-preview-row"><span>Delight</span><span>{ '\u2212' }{ fmtMoney( redemption.couponDiscount ) }</span></div>
                    </>
                  ) }
                </div>
              ) }
              { !selCustomer ? (
                <div>
                  <h3 style={ { margin: '0 0 12px', fontSize: 'var(--text-xl)' } }>Step 1 { '\u2014' } Select Customer</h3>
                  <input className="search-input" placeholder="Search\u2026" value={ custSearch } onChange={ e => setCustSearch( e.target.value ) } style={ { marginBottom: 16, maxWidth: 400 } } />
                  <div className="pf-cust-grid">
                    { filteredCust.map( c => (
                      <div key={ c.id } onClick={ () => {
                        setSelCustomer( c );
                        // Selecting a customer never mutates price lines. The operator supplies
                        // invoice inputs; the invoice engine owns Delight, convenience fee and total.
                      } } className="pf-cust-card">
                        <div className="pf-cust-avatar">{ ( c.name || '?' )[ 0 ].toUpperCase() }</div>
                        <div className="pf-cust-info">
                          <div className="pf-cust-name">{ c.name || 'Unknown' }</div>
                          <div className="pf-cust-phone">{ c.phone || '\u2014' }</div>
                        </div>
                      </div>
                    ) ) }
                    { filteredCust.length === 0 && <div className="pf-empty">No customers. Create one in the Customers tab.</div> }
                  </div>
                </div>
              ) : (
                <div className="pf-create-layout">
                  <div className="pf-composer-main">
                  <div className="pf-context-grid">
                    <div className="info-banner pf-customer-summary">
                      <div className="pf-context-copy">
                        <span className="pf-context-label">Customer</span>
                        <strong>{ selCustomer.name }</strong>
                        <span>{ selCustomer.phone }{ selCustomer.email ? ' · ' + selCustomer.email : '' }</span>
                      </div>
                      <div className="pf-context-actions">
                        <Button variant="secondary" size="sm" onClick={ () => openEditCust( selCustomer, 'phone' ) }>Edit number</Button>
                        <Button variant="ghost" size="sm" onClick={ () => setSelCustomer( null ) }>Change customer</Button>
                      </div>
                    </div>
                    { hasPayableDeliveryAddress( selCustomer ) ? (
                      <div className="inner-card pf-delivery-summary">
                        <div className="pf-context-copy">
                          <span className="pf-context-label">Delivery</span>
                          <div>{ formatAddress( addressFieldsFromContact( selCustomer ) ) }</div>
                        </div>
                        <div className="pf-context-actions">
                          <Button variant="secondary" size="sm" onClick={ () => openEditCust( selCustomer, 'address' ) }>Edit address</Button>
                        </div>
                      </div>
                    ) : (
                      <div className="info-banner pf-address-warning">
                        <div className="pf-context-copy">
                          <span className="pf-context-label">Delivery</span>
                          <div>Add street address, city, state / region, postal code and country before creating a physical-goods payment.</div>
                        </div>
                        <div className="pf-context-actions">
                          <Button variant="primary" size="sm" onClick={ () => openEditCust( selCustomer, 'address' ) }>Add address</Button>
                        </div>
                      </div>
                    ) }
                  </div>
                  <div className="pf-composer-heading">
                    <div>
                      <div className="pf-composer-kicker">Step 2</div>
                      <h3>Invoice composer</h3>
                      <p>Add the goods being collected for. Pricing, Delight, GST, convenience fee and the final payable remain server-authoritative.</p>
                    </div>
                  </div>

                  <div className="pf-composer-card">
                    <div className="pf-composer-card-head">
                      <div>
                        <h4>Items</h4>
                        <p>Use one card per line. HSN/SAC stays under Advanced tax details.</p>
                      </div>
                      <Button variant="secondary" size="sm" onClick={ addItem }>+ Add item</Button>
                    </div>
                    <div className="pf-item-card-list">
                      { invForm.items.map( ( it, i ) => (
                        <div className="pf-item-card" key={ i }>
                          <div className="pf-item-card-top">
                            <span className="pf-item-index">Item { i + 1 }</span>
                            { invForm.items.length > 1 && <button type="button" onClick={ () => removeItem( i ) } className="pf-remove-btn" aria-label={ `Remove item ${i + 1}` }>{ '\u2715' }</button> }
                          </div>
                          <div className="form-group pf-item-name">
                            <label htmlFor={ `pf-item-name-${i}` }>Description</label>
                            <input id={ `pf-item-name-${i}` } type="text" value={ it.name } onChange={ e => updateItem( i, 'name', e.target.value ) } placeholder={ config.default_item_name } />
                          </div>
                          <div className="pf-item-fields">
                            <div className="form-group">
                              <label htmlFor={ `pf-item-price-${i}` }>Unit amount ({ '\u20B9' })</label>
                              <input id={ `pf-item-price-${i}` } type="number" min="0" step="0.01" value={ it.unitPrice } onChange={ e => updateItem( i, 'unitPrice', e.target.value ) } />
                            </div>
                            <div className="form-group">
                              <label htmlFor={ `pf-item-qty-${i}` }>Qty</label>
                              <input id={ `pf-item-qty-${i}` } type="number" min="1" step="1" value={ it.quantity } onChange={ e => updateItem( i, 'quantity', e.target.value ) } />
                            </div>
                            <div className="form-group">
                              <label htmlFor={ `pf-item-gst-${i}` }>GST %</label>
                              <input id={ `pf-item-gst-${i}` } type="number" min="0" max="100" step="0.01" value={ it.gstRate } onChange={ e => updateItem( i, 'gstRate', e.target.value ) } />
                            </div>
                          </div>
                          { showAdvancedTax && (
                            <div className="pf-advanced-tax">
                              <div className="form-group">
                                <label htmlFor={ `pf-item-hsn-${i}` }>HSN/SAC <span>internal accounting</span></label>
                                <input id={ `pf-item-hsn-${i}` } type="text" inputMode="numeric" value={ it.hsnSac } onChange={ e => updateItem( i, 'hsnSac', e.target.value.replace( /\D/g, '' ).slice( 0, 8 ) ) } placeholder="4, 6 or 8 digits" />
                              </div>
                            </div>
                          ) }
                        </div>
                      ) ) }
                    </div>
                    <button type="button" className="pf-advanced-toggle" onClick={ () => setShowAdvancedTax( value => !value ) } aria-expanded={ showAdvancedTax }>
                      { showAdvancedTax ? 'Hide advanced tax details' : 'Advanced tax details' }
                    </button>
                  </div>

                  <div className="pf-composer-card">
                    <div className="pf-composer-card-head">
                      <div>
                        <h4>Delivery</h4>
                        <p>Physical-goods collection stays mandatory-address. Express is the customer-facing delivery charge.</p>
                      </div>
                    </div>
                    <div className="pf-form-grid">
                      <div className="form-group"><label htmlFor="pf-shipping">Express ({ '\u20B9' })</label><input id="pf-shipping" type="number" min="0" step="0.01" value={ invForm.shipping } onChange={ e => setInvForm( { ...invForm, shipping: e.target.value } ) } /><span className="pf-field-help">Delivery / shipping charge shown to the customer as Express.</span></div>
                    </div>
                  </div>
                  <div className="pf-composer-card pf-auto-discount-card">
                    <div className="pf-composer-card-head">
                      <div>
                        <h4>Automatic Delight</h4>
                        <p>Read-only. The invoice engine calculates the eligible Delight discount automatically.</p>
                      </div>
                      <span className="pf-authority-badge">Server calculated</span>
                    </div>
                    <div className="pf-auto-discount-value">
                      <span>Delight</span>
                      <strong>{ invoicePreview && Number( invoicePreview.couponDiscount ) > 0 ? `−${ fmtMoney( Number( invoicePreview.couponDiscount ) ) }` : 'Calculated in preview' }</strong>
                    </div>
                  </div>
                  { /* The server's answer about these codes is rendered ABOVE the customer step,
                       outside this branch, because a successful create clears the selected
                       customer and would otherwise unmount the one record of what was applied. */ }
                  <div className="pf-composer-card pf-payment-request-card">
                    <div className="pf-composer-card-head">
                      <div>
                        <h4>Payment request</h4>
                        <p>Choose the sender and optional order reference. Final fees and payable remain server-authoritative.</p>
                      </div>
                      <span className="pf-authority-badge">ORDER_DETAILS</span>
                    </div>
                    <div className="pf-payment-grid">
                      <div className="form-group">
                        <label>Order ID</label>
                        <input type="text" value={ invForm.orderId } onChange={ e => setInvForm( { ...invForm, orderId: e.target.value } ) } placeholder="Optional" />
                      </div>
                      <div className="form-group">
                        <label>Send From</label>
                        <Select ariaLabel="Send from" value={ sendPhone }
                          onChange={ v => setSendPhone( v ) }
                          options={ phoneSelectOptions } />
                      </div>
                    </div>
                    <div className="pf-payment-meta">
                      <div>
                        <span>WhatsApp payment</span>
                        <strong>WECAREDIGITAL · ORDER_DETAILS</strong>
                      </div>
                      <div>
                        <span>Goods type</span>
                        <strong>Physical goods</strong>
                      </div>
                      <div>
                        <span>Delivery</span>
                        <strong>Confirmed address required</strong>
                      </div>
                    </div>
                    { goodsType === 'physical-goods' && !hasPayableDeliveryAddress( selCustomer ) && (
                      <div className="msg-bar error" style={ { margin: '14px 0 0', fontSize: 'var(--text-xs)' } }>Physical goods require a complete delivery address. Use Add address above before creating the payment request.</div>
                    ) }
                    <div className="pf-server-note">
                      Convenience fee and final total are calculated by the server. The stored invoice remains the authority for subtotal, tax, Delight and total.
                    </div>
                    <div className="pf-composer-actions">
                      <Button variant="primary" size="lg" loading={ creating } disabled={ creating } onClick={ () => submitInvoice( true ) }>Create and send payment request</Button>
                      <Button variant="secondary" size="lg" disabled={ creating } onClick={ () => submitInvoice( false ) }>Save invoice for review</Button>
                    </div>
                  </div>
                  </div>

                  <aside className="pf-live-preview" aria-live="polite">
                    <div className="pf-live-preview-head">
                      <div>
                        <div className="pf-composer-kicker">Invoice preview</div>
                        <h4>Customer receipt</h4>
                      </div>
                      <span className="pf-authority-badge">Server authoritative</span>
                    </div>
                    <p className="pf-live-preview-note">No invoice number or record is created while previewing.</p>

                    { previewLoading && <div className="pf-preview-loading">Updating server preview…</div> }
                    { previewError && !previewLoading && <div className="pf-preview-error">{ previewError }</div> }
                    { invoicePreview && (
                      <>
                        { invoicePreview.previewImageBase64 && (
                          <div className="pf-preview-image-shell">
                            <img
                              src={ `data:${invoicePreview.previewImageContentType || 'image/png'};base64,${invoicePreview.previewImageBase64}` }
                              alt="Server-rendered customer receipt preview"
                            />
                          </div>
                        ) }
                        <div className="pf-preview-totals">
                          <div><span>Items Subtotal</span><strong>{ fmtMoney( Number( invoicePreview.subtotal ) ) }</strong></div>
                          { Number( invoicePreview.couponDiscount ) > 0 && <div><span>Delight</span><strong>−{ fmtMoney( Number( invoicePreview.couponDiscount ) ) }</strong></div> }
                          { Number( invoicePreview.shipping ) > 0 && <div><span>Express</span><strong>{ fmtMoney( Number( invoicePreview.shipping ) ) }</strong></div> }
                          { Number( invoicePreview.convenienceFeeNet ) > 0 && <div><span>Convenience Fee</span><strong>{ fmtMoney( Number( invoicePreview.convenienceFeeNet ) ) }</strong></div> }
                          <div><span>{ invoicePreview.sellerGstin }</span><strong>{ fmtMoney( Number( invoicePreview.totalGst ) ) }</strong></div>
                          <div className="pf-preview-total"><span>Amount Payable</span><strong>{ fmtMoney( Number( invoicePreview.total ) ) }</strong></div>
                        </div>
                      </>
                    ) }
                    { !invoicePreview && !previewLoading && !previewError && (
                      <div className="pf-preview-empty">Enter a positive item amount to generate the server preview.</div>
                    ) }
                  </aside>
                </div>
              ) }
            </div>
          ) }

          {/* INVOICES TAB */ }
          { activeTab === 'invoices' && (
            <div className="pf-tab-body">
              <div className="pf-filter-bar">
                { STATUS_FILTERS.map( f => (
                  <button key={ f.id } className={ `btn btn-sm ${statusFilter === f.id ? 'btn-primary' : 'btn-secondary'}` } onClick={ () => setStatusFilter( f.id ) }>{ f.label }</button>
                ) ) }
                <div style={ { flex: 1 } } />
                <Button variant="secondary" size="sm" icon="refresh" loading={ invLoading } onClick={ loadInvoices }>Refresh</Button>
              </div>
              <p>Invoices cannot be permanently deleted once numbered. Use <strong>Void invoice</strong> for eligible unpaid invoices; paid invoices require refund or credit-note review. Voided invoices remain in Cancelled or All with their GST numbers and history.</p>
              <div className="stats-grid" style={ { marginBottom: 16 } }>
                <div className="stat-card accent"><div className="pf-stat-value">{ invStats.total }</div><div className="pf-stat-label">Total</div></div>
                <div className="stat-card"><div className="pf-stat-value">{ invStats.paid }</div><div className="pf-stat-label">Paid</div></div>
                <div className="stat-card"><div className="pf-stat-value">{ invStats.pending }</div><div className="pf-stat-label">Pending</div></div>
                <div className="stat-card"><div className="pf-stat-value">{ fmtMoney( invStats.totalAmt ) }</div><div className="pf-stat-label">Total Value</div></div>
              </div>
              <div className="pf-inv-layout">
                <div className="pf-inv-list">
                  <div className="table-container">
                    <table className="inner-table">
                      <thead><tr><th>#</th><th>Ref</th><th>Customer</th><th>Amount</th><th>Status</th><th>Source</th><th>Date</th><th></th></tr></thead>
                      <tbody>
                        { visibleInvoices.length === 0 && <tr className="empty-row"><td colSpan={ 8 }>No matching invoices</td></tr> }
                        { visibleInvoices.map( ( inv, i ) => (
                          <tr key={ inv.invoiceId } onClick={ () => selectInvoice( inv ) } style={ { cursor: 'pointer' } } className={ selInvoice?.invoiceId === inv.invoiceId ? 'pf-row-selected' : '' }>
                            <td>{ i + 1 }</td>
                            <td style={ { fontFamily: 'monospace', fontSize: 'var(--text-xs)' } }>{ inv.referenceId || '\u2014' }</td>
                            <td style={ { fontWeight: 600 } }>{ inv.customerName || inv.customerPhone || '\u2014' }</td>
                            <td>{ fmtMoney( inv.total ) }</td>
                            <td><span className={ `status-badge ${badgeClass( inv )}` }>{ inv.status }</span></td>
                            <td><span style={ { padding: '2px 8px', borderRadius: 12, fontSize: 'var(--text-xs)', fontWeight: 500, background: 'var(--bg-secondary)', color: 'var(--accent)' } }>{ inv.entryPoint || 'manual' }</span></td>
                            <td>{ fmtDate( inv.createdAt ) }</td>
                            <td onClick={ e => e.stopPropagation() }>{ canCancelInvoice( inv ) && <Button variant="danger" size="sm" loading={ actionLoading === 'cancel' } onClick={ () => doCancelInvoice( inv ) }>Void invoice</Button> }</td>
                          </tr>
                        ) ) }
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Side Panel */ }
                { selInvoice && (
                  <div className="pf-side-panel">
                    <div className="pf-side-panel-header">
                      <h3>Invoice Detail</h3>
                      <button onClick={ () => setSelInvoice( null ) } className="pf-close-btn">{ '\u2715' }</button>
                    </div>
                    <div className={ `status-badge ${badgeClass( selInvoice )}` } style={ { marginBottom: 12 } }>{ selInvoice.status }</div>
                    <div className="pf-detail-row"><span className="label">Source</span><span style={ { padding: '2px 8px', borderRadius: 12, fontSize: 'var(--text-xs)', fontWeight: 500, background: 'var(--bg-secondary)', color: 'var(--accent)' } }>{ selInvoice.entryPoint || 'manual' }</span></div>
                    <div className="pf-detail-row"><span className="label">Ref</span><span className="mono">{ selInvoice.referenceId || '\u2014' }</span></div>
                    <div className="pf-detail-row"><span className="label">Customer</span><span>{ selInvoice.customerName || '\u2014' }</span></div>
                    <div className="pf-detail-row"><span className="label">Phone</span><span>{ selInvoice.customerPhone || '\u2014' }</span></div>
                    <div className="pf-detail-row"><span className="label">Order</span><span>{ selInvoice.orderId || '\u2014' }</span></div>
                    { selInvoice.goodsType && <div className="pf-detail-row"><span className="label">Type</span><span style={ { padding: '2px 8px', borderRadius: 12, fontSize: 'var(--text-xs)', fontWeight: 500, background: selInvoice.goodsType === 'physical-goods' ? '#dbeafe' : '#f3e8ff', color: selInvoice.goodsType === 'physical-goods' ? '#1e40af' : '#6b21a8' } }>{ selInvoice.goodsType === 'physical-goods' ? 'Physical' : 'Digital' }</span></div> }
                    { selInvoice.shippingAddress && <div className="pf-detail-row" style={ { alignItems: 'flex-start' } }><span className="label">Delivery Address</span><span style={ { fontSize: 'var(--text-xs)', color: '#555', maxWidth: 200, wordBreak: 'break-word' } }>{ selInvoice.shippingAddress }</span></div> }
                    { selInvoice.assets?.find( a => a.assetType === 'image' || a.assetType.startsWith( 'image#' ) ) && ( () => {
                      const imageAsset = [ ...( selInvoice.assets || [] ) ]
                        .filter( a => a.assetType === 'image' || a.assetType.startsWith( 'image#' ) )
                        .sort( ( a, b ) => ( b.generatedAt || b.version || 0 ) - ( a.generatedAt || a.version || 0 ) )[ 0 ];
                      return imageAsset?.url ? (
                        <div className="pf-section-divider">
                          <div className="pf-section-title">Customer receipt</div>
                          <div style={ {
                            borderRadius: 12, padding: 12, overflow: 'hidden',
                            backgroundImage: 'linear-gradient(45deg,#f2f4f3 25%,transparent 25%),linear-gradient(-45deg,#f2f4f3 25%,transparent 25%),linear-gradient(45deg,transparent 75%,#f2f4f3 75%),linear-gradient(-45deg,transparent 75%,#f2f4f3 75%)',
                            backgroundSize: '20px 20px', backgroundPosition: '0 0,0 10px,10px -10px,-10px 0px',
                          } }>
                            <img src={ imageAsset.url } alt={ `Customer receipt ${selInvoice.referenceId || selInvoice.invoiceNumber}` }
                              style={ { width: '100%', maxHeight: 520, objectFit: 'contain', display: 'block' } } />
                          </div>
                          <div style={ { display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' } }>
                            <a className="btn btn-secondary btn-sm" href={ imageAsset.url } target="_blank" rel="noreferrer">Open receipt</a>
                            <a className="btn btn-secondary btn-sm" href={ imageAsset.url } download>Download PNG</a>
                            { selInvoice.gstWorkpaper && <Button variant="secondary" size="sm" onClick={ () => downloadGstWorkpaper( selInvoice ) }>Download GST JSON</Button> }
                          </div>
                        </div>
                      ) : null;
                    } )() }
                    <div className="pf-section-divider">
                      <div className="pf-detail-row"><span className="label">Items subtotal</span><span>{ fmtMoney( selInvoice.subtotal ) }</span></div>
                      <div className="pf-detail-row"><span className="label">Supply GST</span><span>{ fmtMoney( selInvoice.gstAccounting?.supplyTax ?? selInvoice.tax ) }</span></div>
                      <div className="pf-detail-row"><span className="label">Express</span><span>{ fmtMoney( selInvoice.shipping ) }</span></div>
                      { /* The Delight discount line. `couponDiscount` holds the Delight figure
                           (the field name is legacy on the stored row). A legacy invoice raised
                           before manual entry was retired may carry a manual remainder in
                           `discount - couponDiscount`; it is shown as "Promo" only when non-zero so
                           a modern Delight-only invoice does not print an empty line. */ }
                      { typeof selInvoice.couponDiscount === 'number' && selInvoice.couponDiscount > 0 && (
                        <div className="pf-detail-row"><span className="label">Delight</span><span>{ '\u2212' }{ fmtMoney( selInvoice.couponDiscount ) }</span></div>
                      ) }
                      { ( selInvoice.discount - ( selInvoice.couponDiscount || 0 ) ) > 0 && (
                        <div className="pf-detail-row"><span className="label">Discount</span><span>{ '\u2212' }{ fmtMoney( selInvoice.discount - ( selInvoice.couponDiscount || 0 ) ) }</span></div>
                      ) }
                      { ( selInvoice.convenienceFeeNet ?? selInvoice.convenienceFee ) > 0 && <div className="pf-detail-row"><span className="label">Convenience fee</span><span>{ fmtMoney( selInvoice.convenienceFeeNet ?? selInvoice.convenienceFee ) }</span></div> }
                      { ( selInvoice.convenienceFeeGst || 0 ) > 0 && <div className="pf-detail-row"><span className="label">Fee GST</span><span>{ fmtMoney( selInvoice.convenienceFeeGst || 0 ) }</span></div> }
                      <div className="pf-detail-row"><span className="label">Total GST</span><span>{ fmtMoney( selInvoice.totalGst ?? selInvoice.tax ) }</span></div>
                      <div className="pf-detail-row"><span className="label">GSTIN</span><span className="mono">{ selInvoice.gstAccounting?.sellerGstin || selInvoice.gstin }</span></div>
                      <div className="pf-detail-total"><span>Total</span><span>{ fmtMoney( selInvoice.total ) }</span></div>
                    </div>
                    { selInvoice.items && selInvoice.items.length > 0 && (
                      <div className="pf-section-divider">
                        <div className="pf-section-title">Items</div>
                        { selInvoice.items.map( ( it, i ) => (
                          <div key={ i } style={ { display: 'flex', justifyContent: 'space-between', fontSize: 'var(--text-xs)', marginBottom: 4 } }>
                            <span>{ it.name } { '\u00D7' }{ it.quantity }{ typeof it.gstRate === 'number' ? ` · GST ${it.gstRate}%` : '' }{ it.hsnSac ? ` · HSN/SAC ${it.hsnSac}` : '' }</span><span>{ fmtMoney( it.amount * it.quantity ) }</span>
                          </div>
                        ) ) }
                      </div>
                    ) }
                    <div className="pf-action-stack">
                      { /* FINDING 10a: Ledger (mode='invoices') is the read-only evidence surface.
                           The mutating Send/Retry payment-request action is suppressed here — a
                           resend belongs on Collect, which is built for it. The read-only fields,
                           delivery logs, remarks and image/PDF export below stay, because none of
                           them send a payment request. In Collect/standalone mode this block is
                           rendered exactly as before. */ }
                      { ( mode !== 'invoices' || ( allowSendInInvoices && selInvoice.entryPoint === 'pay_flow' ) )
                        && ( selInvoice.status === 'created' || selInvoice.status === 'pending_payment' ) && (
                        <>
                          { /* The two choosers above the Send button. Their inline objects
                               carried APPEARANCE - a 1.5px dark-green border, an 8px radius,
                               6px/10px padding, 13px type - and that is now the shared token
                               box, so only `flex: 1` survives as layout. The dark-green edge
                               goes with it rather than being reproduced: an inline border on
                               one page is how the fleet came to have eleven different control
                               boxes. The caption is an unassociated label, so it stays and the
                               control takes `ariaLabel`. */ }
                          <div style={ { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 } }>
                            <label style={ { fontSize: 'var(--text-xs)', fontWeight: 500, whiteSpace: 'nowrap' } }>From</label>
                            <Select ariaLabel="Send from" value={ sendPhone }
                              onChange={ v => setSendPhone( v ) }
                              options={ phoneSelectOptions } style={ DETAIL_SELECT_STYLE } />
                          </div>
                          <Button variant="primary" size="sm" loading={ actionLoading === 'send' } onClick={ () => doSendPaymentLink( selInvoice ) }>
                            { selInvoice.status === 'pending_payment' ? 'Review delivery & request payment' : 'Send payment request' }
                          </Button>
                        </>
                      ) }
                      <Button variant="secondary" size="sm" loading={ actionLoading === 'img' } onClick={ () => doGenerateImage( selInvoice ) }>Generate Image</Button>
                      { !isIssued( selInvoice ) && (
                        <Button variant="secondary" size="sm" loading={ actionLoading === 'edit' } onClick={ () => openEditModal( selInvoice ) }>Edit Invoice</Button>
                      ) }
                      <Button variant="secondary" size="sm" onClick={ () => openRemarkModal( selInvoice, 'remark' ) }>Add Remark</Button>
                      { ( selInvoice.status === 'paid' || selInvoice.paymentStatus === 'captured' ) && (
                        <>
                          <Button variant="secondary" size="sm" onClick={ () => openRemarkModal( selInvoice, 'refund' ) }>Reconcile Refund</Button>
                          <Button variant="secondary" size="sm" onClick={ () => openRemarkModal( selInvoice, 'credit_note' ) }>Record Credit Note</Button>
                          <div style={ { display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginTop: 4 } }>
                            <span style={ { fontSize: 'var(--text-xs)', fontWeight: 500 } }>
                              WhatsApp payment order · { selInvoice.waOrderStatus || selInvoice.orderStatus || 'pending' }
                            </span>
                            <span style={ { fontSize: 'var(--text-xs)', color: '#777' } }>
                              Payment capture advances this automatically to completed.
                            </span>
                          </div>
                        </>
                      ) }
                      { canCancelInvoice( selInvoice ) && (
                        <Button variant="danger" size="sm" loading={ actionLoading === 'cancel' } onClick={ () => doCancelInvoice( selInvoice ) }>Void invoice</Button>
                      ) }
                      <p className="pf-invoice-retention-note">Delete is unavailable for issued GST invoices. Unpaid invoices can be voided with history retained; paid invoices require financial adjustment.</p>
                    </div>
                    { deliveryLogs.length > 0 && (
                      <div className="pf-section-divider">
                        <div className="pf-section-title">Delivery Logs</div>
                        { deliveryLogs.map( ( log, i ) => (
                          <div key={ i } className="pf-log-entry">
                            <div><strong>{ log.channel }</strong> { '\u2192' } { log.toNumber }</div>
                            <div>Status: { log.status } { '\u00B7' } { new Date( log.timestamp * 1000 ).toLocaleString( 'en-IN', { timeZone: 'Asia/Kolkata' } ) }</div>
                            { log.error && <div className="pf-log-error">{ log.error }</div> }
                          </div>
                        ) ) }
                      </div>
                    ) }
                    { selInvoice.remarks && ( () => {
                      try
                      {
                        const remarks = typeof selInvoice.remarks === 'string' ? JSON.parse( selInvoice.remarks ) : selInvoice.remarks; return remarks.length > 0 ? (
                          <div className="pf-section-divider">
                            <div className="pf-section-title">Remarks / Notes</div>
                            { remarks.map( ( r: any, i: number ) => (
                              <div key={ i } className="pf-log-entry">
                                <div><span className={ `status-badge ${r.type === 'refund' ? 'danger' : r.type === 'credit_note' ? 'warning' : 'muted'}` }>{ r.type }</span> { r.amount > 0 && <span>{ fmtMoney( r.amount ) }</span> }</div>
                                <div style={ { fontSize: 'var(--text-xs)', marginTop: 2 } }>{ r.text }</div>
                                <div style={ { fontSize: 'var(--text-xs)', color: '#888' } }>{ r.author } { '\u00B7' } { fmtDate( r.createdAt ) }</div>
                              </div>
                            ) ) }
                          </div>
                        ) : null;
                      } catch { return null; }
                    } )() }
                  </div>
                ) }
              </div>
            </div>
          ) }

          {/* PENDING DUES TAB */ }
          { activeTab === 'dues' && (
            <div className="pf-tab-body">
              <div className="stats-grid" style={ { marginBottom: 16 } }>
                <div className="stat-card accent"><div className="pf-stat-value">{ invoices.filter( i => i.status === 'pending_payment' ).length }</div><div className="pf-stat-label">Pending Invoices</div></div>
                <div className="stat-card"><div className="pf-stat-value">{ fmtMoney( invoices.filter( i => i.status === 'pending_payment' ).reduce( ( s, i ) => s + i.total, 0 ) ) }</div><div className="pf-stat-label">Total Dues</div></div>
              </div>
              <div className="table-container">
                <table className="inner-table">
                  <thead><tr><th>#</th><th>Ref</th><th>Customer</th><th>Phone</th><th>Amount</th><th>Created</th><th>Actions</th></tr></thead>
                  <tbody>
                    { invoices.filter( i => i.status === 'pending_payment' ).length === 0 && <tr className="empty-row"><td colSpan={ 7 }>No pending dues</td></tr> }
                    { invoices.filter( i => i.status === 'pending_payment' ).map( ( inv, i ) => (
                      <tr key={ inv.invoiceId }>
                        <td>{ i + 1 }</td>
                        <td style={ { fontFamily: 'monospace', fontSize: 'var(--text-xs)' } }>{ inv.referenceId || '\u2014' }</td>
                        <td style={ { fontWeight: 600 } }>{ inv.customerName || '\u2014' }</td>
                        <td>{ inv.customerPhone || '\u2014' }</td>
                        <td>{ fmtMoney( inv.total ) }</td>
                        <td>{ fmtDate( inv.createdAt ) }</td>
                        <td>
                          <div style={ { display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap' } }>
                            { /* The two in-table choosers on the Dues row. These were the
                                 smallest controls on the page - 4px/6px padding around 11px
                                 type - so they keep enough component padding to remain readable
                                 without inheriting a blanket phone-height floor. They state a
                                 flex basis because the cell is a wrapping flex row and the
                                 trigger fills its field. */ }
                            <Select ariaLabel="Send from" value={ sendPhone }
                              onChange={ v => setSendPhone( v ) }
                              options={ phoneSelectOptions } style={ DUES_PHONE_SELECT_STYLE } />
                            <Button variant="primary" size="sm" loading={ actionLoading === 'send' } onClick={ () => doSendPaymentLink( inv ) }>Send</Button>
                          </div>
                        </td>
                      </tr>
                    ) ) }
                  </tbody>
                </table>
              </div>
            </div>
          ) }

          {/* CONFIG TAB */ }
          { activeTab === 'config' && (
            <div className="pf-config">
              <h3 style={ { margin: '0 0 16px', fontSize: 'var(--text-xl)' } }>Flow Configuration</h3>
              <div className="form-group"><label>Default GST Rate (%)</label><input type="number" value={ config.default_gst_rate } onChange={ e => setConfig( { ...config, default_gst_rate: parseFloat( e.target.value ) || 0 } ) } /></div>
              <div className="form-group"><label>Default Express / Shipping ({ '\u20B9' })</label><input type="number" value={ config.default_shipping } onChange={ e => setConfig( { ...config, default_shipping: parseFloat( e.target.value ) || 0 } ) } /></div>
              <div className="form-group"><label>GSTIN</label><input type="text" value={ config.gstin } onChange={ e => setConfig( { ...config, gstin: e.target.value } ) } /></div>
              <div className="form-group"><label>Default Item Name</label><input type="text" value={ config.default_item_name } onChange={ e => setConfig( { ...config, default_item_name: e.target.value } ) } /></div>
              { /* THE BRAND LIST EDITOR IS GONE, not hidden. The owner asked for the brand
                   section removed with WECARE.DIGITAL hardcoded as the default, and
                   `loadSavedConfig` now pins `purposes` to DEF_CFG - so a textarea here would
                   have been an input whose value is discarded on the next load, which is worse
                   than no control at all. The read-only Brand field that replaced it is gone
                   too (owner instruction 2026-10-25). */ }
              <Button variant="primary" size="sm" loading={ configSaving } onClick={ () => { setConfigSaving( true ); try { localStorage.setItem( CFG_KEY, JSON.stringify( config ) ); } catch { } setTimeout( () => { setConfigSaving( false ); showMsg( 'Config saved' ); }, 300 ); } }>Save Config</Button>
            </div>
          ) }

          {/* EDIT INVOICE MODAL */ }
          { editModal && (
            <div className="pf-modal-overlay" onClick={ () => setEditModal( null ) }>
              <div className="pf-modal-box" onClick={ e => e.stopPropagation() } style={ { maxWidth: 520 } }>
                <div className="pf-modal-header">
                  <h3>Edit Invoice</h3>
                  <Button variant="ghost" size="sm" onClick={ () => setEditModal( null ) }>×</Button>
                </div>
                <div className="pf-detail-row" style={ { marginBottom: 12 } }>
                  <span className="label">Ref</span>
                  <span className="mono">{ editModal.referenceId || editModal.invoiceNumber }</span>
                </div>
                <div className="pf-form-grid">
                  <div className="form-group"><label>Customer Name</label><input type="text" value={ editForm.customerName } onChange={ e => setEditForm( { ...editForm, customerName: e.target.value } ) } /></div>
                  <div className="form-group"><label>Phone</label><input type="tel" value={ editForm.customerPhone } onChange={ e => setEditForm( { ...editForm, customerPhone: e.target.value } ) } /></div>
                  <div className="form-group"><label>Email</label><input type="email" value={ editForm.customerEmail } onChange={ e => setEditForm( { ...editForm, customerEmail: e.target.value } ) } /></div>
                  { /* No Brand field (owner instruction 2026-10-25). `editForm.purpose` is
                       deliberately left as loaded from the invoice, so editing an older record
                       does not rewrite the brand it was raised under. */ }
                  { /* The Express/Shipping and Manual adjustment inputs are REMOVED, not
                       disabled. `update_invoice` refuses either field on an issued invoice with
                       409 INVOICE_ISSUED_IMMUTABLE, so the control could only collect a figure
                       and then fail - and a disabled input still advertises an edit that is not
                       available. */ }
                  <div className="form-group"><label>Order ID</label><input type="text" value={ editForm.orderId } onChange={ e => setEditForm( { ...editForm, orderId: e.target.value } ) } /></div>
                  <div className="form-group"><label>Notes</label><textarea rows={ 2 } value={ editForm.notes } onChange={ e => setEditForm( { ...editForm, notes: e.target.value } ) } /></div>
                </div>
                { /* The same eight fields and the same composition as the customer modal, from
                     the same module. The free-text address textarea that was here is the
                     read-only preview now; a coupon code is NOT editable from here
                     at all, because `update_invoice` answers 400 USE_CREATE for one. */ }
                <AddressFieldGroup
                  idPrefix="pf-inv-addr"
                  value={ editAddress }
                  onChange={ setEditAddress }
                  fallback={ editForm.shippingAddress }
                />
                <div className="pf-modal-actions">
                  <Button variant="secondary" size="sm" onClick={ () => setEditModal( null ) }>Cancel</Button>
                  <Button variant="primary" size="sm" loading={ actionLoading === 'edit' } onClick={ submitEdit }>Save Changes</Button>
                </div>
              </div>
            </div>
          ) }

          {/* REMARK / REFUND / CREDIT NOTE MODAL */ }
          { remarkModal && (
            <div className="pf-modal-overlay" onClick={ () => setRemarkModal( null ) }>
              <div className="pf-modal-box" onClick={ e => e.stopPropagation() }>
                <div className="pf-modal-header">
                  <h3>{ remarkModal.type === 'remark' ? 'Add Remark' : remarkModal.type === 'refund' ? 'Reconcile Refund' : 'Record Credit Note' }</h3>
                  <Button variant="ghost" size="sm" onClick={ () => setRemarkModal( null ) }>{ '\u2715' }</Button>
                </div>
                <div className="pf-detail-row" style={ { marginBottom: 12 } }>
                  <span className="label">Invoice</span>
                  <span className="mono">{ remarkModal.inv.referenceId || remarkModal.inv.invoiceNumber }</span>
                </div>
                { remarkModal.type === 'refund' && (
                  <div className="msg-bar" style={ { marginBottom: 12 } }>
                    This does not issue a refund. Refund in the payment gateway dashboard first; after the webhook lands, enter the provider refund ID here to verify and reconcile the ledger.
                  </div>
                ) }
                { ( remarkModal.type === 'refund' || remarkModal.type === 'credit_note' ) && (
                  <div className="form-group">
                    <label>Amount ({ '\u20B9' })</label>
                    <input type="number" value={ remarkAmount } onChange={ e => setRemarkAmount( e.target.value ) } placeholder="0" />
                  </div>
                ) }
                { remarkModal.type === 'refund' && (
                  <div className="form-group">
                    <label>Provider refund ID *</label>
                    <input type="text" value={ refundId } onChange={ e => setRefundId( e.target.value ) } placeholder="rfnd_..." autoComplete="off" />
                  </div>
                ) }
                <div className="form-group">
                  <label>{ remarkModal.type === 'remark' ? 'Note' : 'Reason' }</label>
                  <textarea rows={ 3 } value={ remarkText } onChange={ e => setRemarkText( e.target.value ) } placeholder={ remarkModal.type === 'remark' ? 'Enter remark...' : 'Reason for ' + remarkModal.type.replace( '_', ' ' ) + '...' } />
                </div>
                <div className="pf-modal-actions">
                  <Button variant="secondary" size="sm" onClick={ () => setRemarkModal( null ) }>Cancel</Button>
                  <Button variant={ remarkModal.type === 'refund' ? 'danger' : 'primary' } size="sm" loading={ actionLoading === 'remark' } onClick={ submitRemark }>
                    { remarkModal.type === 'remark' ? 'Save Remark' : remarkModal.type === 'refund' ? 'Verify & Record Refund' : 'Record Credit Note' }
                  </Button>
                </div>
              </div>
            </div>
          ) }

        </div>
      ) }
    </PageShell>
  );

  if ( embedded ) return shellContent;
  return <Layout user={ user } onSignOut={ signOut }>{ shellContent }</Layout>;
};

export default PayFlowPage;
