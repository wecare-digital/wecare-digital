/* Pay Flow CRM - WECARE.DIGITAL */
import React, { useState, useEffect, useCallback } from 'react';
import Layout from '../../../../components/Layout';
import PageShell, { ShellTab } from '../../../../components/PageShell';
import Button from '../../../../components/ui/Button';
import Select, { type SelectOption } from '../../../../components/ui/Select';
import * as api from '../../../../api/client';
import { useConfirm } from '../../../../contexts/ConfirmContext';
import type { Invoice, InvoiceDeliveryLog, Contact, CreateInvoiceEngineRequest } from '../../../../api/client';
import { DEFAULT_GSTIN } from '../../../../config/constants';
import {
  ADDRESS_FIELDS, EMPTY_ADDRESS_FIELDS, addressPayload, formatAddress,
  type AddressFormFields,
} from '../../../../lib/address-format';

interface PP { signOut?: () => void; user?: any; embedded?: boolean; }
interface FC { default_gst_rate: number; default_shipping: number; default_promo: number; gstin: string; default_item_name: string; purposes: string[]; }
interface IR { name: string; unitPrice: string; quantity: string; gstRate: string; }

/*
 * ONE ADDRESS FIELD SET, shared with the Contacts form through src/lib/address-format.ts.
 *
 * `landmark`, `houseNumber` and `buildingName` are gone from this form's state. They were three
 * extra CRM columns standing in for `locality` and `addressLine2`, and nothing in the payment
 * path reads them: `contact_address._RULES` has eight fields and `payment_address.for_wix` /
 * `for_meta_beneficiary` project those eight. The stored flat columns are NOT deleted and are
 * NOT overwritten with blanks - the WhatsApp subscribe flow still writes them - they are simply
 * no longer edited here, and `openEditCust` folds whatever is in them into `addressLine2` /
 * `locality` so an existing contact loads with its address intact.
 */
const EMPTY_FORM = {
  name: '', phone: '', email: '', shippingAddress: '', billingAddress: '', gstin: '',
  ...EMPTY_ADDRESS_FIELDS,
};
const NEW_ITEM = (): IR => ( { name: '', unitPrice: '', quantity: '1', gstRate: '18' } );
/*
 * THE ONE BRAND, hardcoded. The owner asked for the brand section removed with WECARE.DIGITAL as
 * the default, so the nine-entry list (BNB Club, No Fault, Expo Week, Ritual Guru, Legal Champ,
 * WECARE.DIGITAL, Gift Card, Service Fee, Consultation) is reduced to one and `loadSavedConfig`
 * refuses to restore a saved list over it - otherwise a browser that saved the old config before
 * this change would keep offering all nine forever.
 */
const DEFAULT_BRAND = 'WECARE.DIGITAL';
/*
 * `discount` DEFAULTS TO '0', and that single character is the point of decision D4.
 *
 * It was '15' (with DEF_CFG.default_promo 15 to match), so EVERY Pay Flow invoice was discounted
 * by Rs.15 before anyone typed anything - a silent, unrequested, unrecorded price change on every
 * document. That default was the real duplicate of the coupon system. The field itself stays,
 * relabelled "Manual adjustment": a goodwill credit is a legitimate staff line and is not a
 * coupon, and it is now previewed on its own row beside the coupon's.
 */
const EMPTY_INV = { items: [ NEW_ITEM() ] as IR[], shipping: '49', discount: '0', purpose: DEFAULT_BRAND, orderId: '' };
const DEF_CFG: FC = { default_gst_rate: 18, default_shipping: 49, default_promo: 0, gstin: DEFAULT_GSTIN || '19AAFFW7196L1Z8', default_item_name: 'Services/Goods', purposes: [ DEFAULT_BRAND ] };
/**
 * Human copy per server-returned refusal code, mirroring cart.tsx's COUPON_MESSAGES /
 * GIFT_CARD_MESSAGES. Keyed on the `errorCode` FEAT-002 answers with, never on prose, and the
 * fallback is honest about not knowing rather than guessing the nearest reason.
 */
const REDEMPTION_MESSAGES: Record<string, string> = {
  UNKNOWN_CODE: 'That coupon code is not valid.',
  COUPON_EXPIRED: 'That coupon has expired.',
  COUPON_INELIGIBLE: 'That coupon cannot be used on this invoice.',
  COUPON_KIND_UNSUPPORTED: 'That kind of coupon cannot be applied to an invoice.',
  MINIMUM_SUBTOTAL: 'The invoice total is below that coupon\u2019s minimum.',
  HELD_BY_ANOTHER_CART: 'That coupon is being used elsewhere right now. Try again shortly.',
  COUPON_STORE_UNAVAILABLE: 'Coupons are not available right now. Try again shortly.',
  GIFT_CARD_INVALID: 'That gift-card code is not valid.',
  GIFT_CARD_EXPIRED: 'That gift card has expired.',
  GIFT_CARD_INELIGIBLE: 'That gift card cannot be used for this invoice.',
  INSUFFICIENT_BALANCE: 'That gift card has no balance left to use.',
  GIFT_CARD_STORE_UNAVAILABLE: 'Gift cards are not available right now. Try again shortly.',
  UNSUPPORTED_CURRENCY: 'Codes can only be applied to an invoice in rupees.',
  AMOUNT_MISMATCH: 'The discount did not reconcile against the total, so nothing was applied.',
  PAYABLE_BELOW_GATEWAY_MINIMUM: 'That would leave less than \u20B91 to pay, which cannot be charged.',
};
const REDEMPTION_UNKNOWN = 'The coupon or gift card could not be applied.';
const TABS: ShellTab[] = [
  { id: 'customers', label: 'Customers' },
  { id: 'create', label: 'Create' },
  { id: 'invoices', label: 'Invoices' },
  { id: 'dues', label: 'Dues' },
  { id: 'config', label: 'Config' },
];
const CFG_KEY = 'wecare_flow_config';
const loadSavedConfig = (): FC => {
  // `purposes` is pinned AFTER the spread on purpose: the brand list is hardcoded now, so a
  // config saved into localStorage before that decision must not restore the nine old brands.
  try { const s = localStorage.getItem( CFG_KEY ); if ( s ) return { ...DEF_CFG, ...JSON.parse( s ), purposes: DEF_CFG.purposes }; } catch { }
  return DEF_CFG;
};
const STATUS_FILTERS = [
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
const GOODS_TYPE_OPTIONS: SelectOption[] = [
  { value: 'digital-goods', label: 'Digital Goods' },
  { value: 'physical-goods', label: 'Physical Goods' },
];
/* LAYOUT ONLY - the box is the trigger's. Both sit in flex rows inside the invoice detail
   panel and the dues table, so each one states its own flex basis rather than a width. */
const DETAIL_SELECT_STYLE: React.CSSProperties = { flex: 1 };
const DUES_PHONE_SELECT_STYLE: React.CSSProperties = { flex: '0 0 180px' };
const DUES_PG_SELECT_STYLE: React.CSSProperties = { flex: '0 0 130px' };
const badgeClass = ( inv: Invoice ) => inv.status === 'paid' || inv.paymentStatus === 'captured' ? 'success' : inv.status === 'cancelled' ? 'danger' : 'muted';
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
/** Integer paise -> a rupee string. The gift-card ledger's unit, formatted without dividing. */
const fmtPaise = ( paise: number ) => {
  const digits = String( Math.max( 0, Math.trunc( paise || 0 ) ) );
  const whole = digits.length > 2 ? digits.slice( 0, -2 ) : '0';
  return `\u20B9${Number( whole ).toLocaleString( 'en-IN' )}.${digits.slice( -2 ).padStart( 2, '0' )}`;
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
      <p style={ { fontSize: 12, fontWeight: 600, color: '#1a3a2a', margin: '8px 0 4px' } }>Delivery Address</p>
      <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 } }>
        { ADDRESS_FIELDS.map( spec => (
          <div className="form-group" key={ spec.key }>
            <label htmlFor={ `${idPrefix}-${spec.key}` }>{ spec.label }</label>
            <input
              id={ `${idPrefix}-${spec.key}` }
              type="text"
              value={ value[ spec.key ] }
              maxLength={ spec.maxLength }
              placeholder={ spec.placeholder }
              onChange={ e => onChange( { ...value, [ spec.key ]: e.target.value } ) }
            />
          </div>
        ) ) }
      </div>
      <div className="form-group">
        <span style={ { fontSize: 12, fontWeight: 600, color: '#1a3a2a' } }>Composed address</span>
        <div
          data-address-preview={ idPrefix }
          aria-readonly="true"
          style={ { fontSize: 12, color: '#555', background: '#f8faf9', border: '1px solid #e0e8e3', borderRadius: 8, padding: '8px 12px', minHeight: 34, wordBreak: 'break-word' } }
        >
          { composed || fallback || '\u2014' }
        </div>
      </div>
    </>
  );
};

/* ── Component ── */
const PayFlowPage: React.FC<PP> = ( { signOut, user, embedded } ) => {
  const [ customers, setCustomers ] = useState<Contact[]>( [] );
  const [ custSearch, setCustSearch ] = useState( '' );
  const [ custLoading, setCustLoading ] = useState( false );
  const [ editCust, setEditCust ] = useState<Partial<Contact> | null>( null );
  const [ custForm, setCustForm ] = useState( EMPTY_FORM );
  const [ custSaving, setCustSaving ] = useState( false );
  const [ selCustomer, setSelCustomer ] = useState<Contact | null>( null );
  const [ invForm, setInvForm ] = useState( { ...EMPTY_INV } );
  const [ creating, setCreating ] = useState( false );
  const [ invoices, setInvoices ] = useState<Invoice[]>( [] );
  const [ invLoading, setInvLoading ] = useState( false );
  const [ statusFilter, setStatusFilter ] = useState( 'all' );
  const [ selInvoice, setSelInvoice ] = useState<Invoice | null>( null );
  const [ deliveryLogs, setDeliveryLogs ] = useState<InvoiceDeliveryLog[]>( [] );
  const [ actionLoading, setActionLoading ] = useState( '' );
  const [ paymentGateway, setPaymentGateway ] = useState( 'razorpay' );
  const [ goodsType, setGoodsType ] = useState<'digital-goods' | 'physical-goods'>( 'digital-goods' );
  const [ sendPhone, setSendPhone ] = useState( 'phone-number-id-waba-t-direct-1055232054343117' );
  const [ remarkModal, setRemarkModal ] = useState<{ inv: Invoice; type: 'remark' | 'refund' | 'credit_note' } | null>( null );
  const [ remarkText, setRemarkText ] = useState( '' );
  const [ remarkAmount, setRemarkAmount ] = useState( '' );
  const [ editModal, setEditModal ] = useState<Invoice | null>( null );
  const [ editForm, setEditForm ] = useState<{ customerName: string; customerPhone: string; customerEmail: string; shipping: string; discount: string; purpose: string; orderId: string; notes: string; shippingAddress: string; billingAddress: string }>( { customerName: '', customerPhone: '', customerEmail: '', shipping: '0', discount: '0', purpose: '', orderId: '', notes: '', shippingAddress: '', billingAddress: '' } );
  /* The invoice-edit modal's address, structured. `update_invoice` accepts only the two address
     STRINGS (handler.py's `allowed` list), so this composes into them - which is exactly the
     point: one typed field set, one composed string, no second free-text input to disagree. */
  const [ editAddress, setEditAddress ] = useState<AddressFormFields>( EMPTY_ADDRESS_FIELDS );
  /*
   * COUPON AND GIFT CARD: a code, and nothing else, ever leaves this form.
   *
   * There is no state here for a discount AMOUNT and no arithmetic anywhere in this file that
   * touches one. `redemption` holds what the SERVER returned on a 201 and `redemptionMsg` holds
   * the message for the typed `errorCode` it refused with - the same discipline cart.tsx's
   * RedemptionPanel follows, for the same reason: a browser-computed discount is a figure the
   * customer can see and the ledger never agreed to.
   */
  const [ couponCode, setCouponCode ] = useState( '' );
  const [ giftCardCode, setGiftCardCode ] = useState( '' );
  const [ redemption, setRedemption ] = useState<api.CreateInvoiceEngineResponse | null>( null );
  const [ redemptionMsg, setRedemptionMsg ] = useState( '' );
  const [ config, setConfig ] = useState<FC>( () => loadSavedConfig() );
  const [ configSaving, setConfigSaving ] = useState( false );
  const [ msg, setMsg ] = useState<{ text: string; type: 'success' | 'error' } | null>( null );
  const showMsg = ( text: string, type: 'success' | 'error' = 'success' ) => { setMsg( { text, type } ); setTimeout( () => setMsg( null ), 4000 ); };
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
      const params = statusFilter === 'all' ? {} : { status: statusFilter };
      const r = await api.listInvoicesEngine( params );
      setInvoices( r.invoices || [] );
    } catch ( e ) { console.error( e ); }
    setInvLoading( false );
  }, [ statusFilter ] );
  const loadDeliveryLogs = useCallback( async ( id: string ) => {
    try { const r = await api.getInvoiceDeliveryLog( id ); setDeliveryLogs( r.deliveryLogs || [] ); } catch ( e ) { console.error( e ); }
  }, [] );
  useEffect( () => { loadCustomers(); loadInvoices(); }, [ loadCustomers, loadInvoices ] );

  /* Customer handlers */
  const openEditCust = ( c: Contact ) => {
    /*
     * PRE-FILL INTO THE EIGHT CANONICAL FIELDS, from whichever of the three places this contact's
     * address actually lives in. A contact may carry: the Meta `shipping_info` JSON the WhatsApp
     * subscribe flow writes (`address`, `in_pin_code`, `landmark_area`, `house_number`,
     * `building_name`), the flat CRM columns, or the validated `checkoutDeliveryAddress` map.
     *
     * `checkoutDeliveryAddress` WINS where it exists, because it is the only one of the three
     * that went through `contact_address.normalize_for_storage` - it is the stored result of this
     * same field set. The legacy house/building/tower/floor columns fold into `addressLine2`
     * rather than being dropped: they are real data, this form no longer offers four extra inputs
     * for them, and folding is what turns them into the one format.
     */
    const checkout = c.checkoutDeliveryAddress;
    let json: any = {};
    if ( c.shippingAddressJson )
    {
      try { json = JSON.parse( c.shippingAddressJson ) || {}; } catch { json = {}; }
    }
    const legacyLine2 = [ c.houseNumber, c.buildingName, c.towerNumber, c.floorNumber,
      json.house_number, json.building_name ]
      .map( v => String( v || '' ).trim() )
      .filter( ( v, i, all ) => v && all.indexOf( v ) === i )
      .join( ', ' );
    setEditCust( c );
    setCustForm( {
      name: c.name || '', phone: c.phone || '', email: c.email || '',
      shippingAddress: c.shippingAddress || '', billingAddress: c.billingAddress || '',
      gstin: ( c as any ).gstin || '',
      addressLine1: checkout?.addressLine1 || json.address || c.addressLine1 || '',
      addressLine2: checkout?.addressLine2 || c.addressLine2 || legacyLine2,
      locality: checkout?.locality || json.landmark_area || c.landmark || '',
      city: checkout?.city || json.city || c.city || '',
      state: checkout?.state || json.state || c.state || '',
      postalCode: checkout?.postalCode || json.in_pin_code || c.postalCode || '',
      country: checkout?.country || c.country || EMPTY_ADDRESS_FIELDS.country,
      countryCode: checkout?.countryCode || EMPTY_ADDRESS_FIELDS.countryCode,
    } );
  };
  const closeEditCust = () => { setEditCust( null ); setCustForm( EMPTY_FORM ); };
  const saveCust = async () => {
    if ( !editCust ) return;
    setCustSaving( true );
    try
    {
      const composed = formatAddress( custForm );
      const saveData = {
        name: custForm.name, phone: custForm.phone, email: custForm.email, gstin: custForm.gstin,
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
      if ( editCust.id ) { await api.updateContact( editCust.id, saveData as any ); showMsg( 'Customer updated' ); }
      else { await api.createContact( saveData as any ); showMsg( 'Customer created' ); }
      closeEditCust(); loadCustomers();
    } catch ( e ) { showMsg( 'Save failed', 'error' ); }
    setCustSaving( false );
  };

  /* Invoice form handlers */
  const updateItem = ( idx: number, field: keyof IR, val: string ) => {
    const items = [ ...invForm.items ]; items[ idx ] = { ...items[ idx ], [ field ]: val }; setInvForm( { ...invForm, items } );
  };
  const addItem = () => {
    const items = [ ...invForm.items ];
    // Insert new item before charge items (Green Packing, Notification Fee) at the end
    const chargeNames = [ 'green packing', 'notification fee' ];
    let insertIdx = items.length;
    for ( let i = items.length - 1; i >= 0; i-- )
    {
      if ( chargeNames.some( cn => items[ i ].name.toLowerCase().includes( cn.split( ' ' )[ 0 ] ) ) ) insertIdx = i;
      else break;
    }
    items.splice( insertIdx, 0, NEW_ITEM() );
    setInvForm( { ...invForm, items } );
  };
  const removeItem = ( idx: number ) => { if ( invForm.items.length <= 1 ) return; setInvForm( { ...invForm, items: invForm.items.filter( ( _, i ) => i !== idx ) } ); };
  const calcSubtotal = () => invForm.items.reduce( ( s, it ) => s + ( parseFloat( it.unitPrice ) || 0 ) * ( parseInt( it.quantity ) || 0 ), 0 );
  const calcTax = () => invForm.items.reduce( ( s, it ) => { const line = ( parseFloat( it.unitPrice ) || 0 ) * ( parseInt( it.quantity ) || 0 ); return s + line * ( parseFloat( it.gstRate ) || 0 ) / 100; }, 0 );
  const calcTotal = () => {
    const sub = calcSubtotal();
    const tax = calcTax();
    const ship = parseFloat( invForm.shipping ) || 0;
    const disc = parseFloat( invForm.discount ) || 0;
    const collection = sub + tax + ship - disc;
    const convBase = Math.round( collection * 0.02 * 100 ) / 100;
    const convGst = Math.round( convBase * 0.18 * 100 ) / 100;
    const convFee = convBase + convGst;
    return collection + convFee;
  };
  const calcConvFee = () => {
    const collection = calcSubtotal() + calcTax() + ( parseFloat( invForm.shipping ) || 0 ) - ( parseFloat( invForm.discount ) || 0 );
    const base = Math.round( collection * 0.02 * 100 ) / 100;
    const gst = Math.round( base * 0.18 * 100 ) / 100;
    return base + gst;
  };

  const submitInvoice = async () => {
    if ( !selCustomer ) { showMsg( 'Select a customer first', 'error' ); return; }
    if ( !invForm.items.some( it => parseFloat( it.unitPrice ) > 0 ) ) { showMsg( 'Add at least one item', 'error' ); return; }
    setCreating( true );
    setRedemptionMsg( '' );
    try
    {
      const req: CreateInvoiceEngineRequest = {
        customerPhone: selCustomer.phone, customerEmail: selCustomer.email || '',
        customerName: selCustomer.name, contactId: selCustomer.id,
        shippingAddress: selCustomer.shippingAddress || '', billingAddress: selCustomer.billingAddress || '',
        // Structured address for WhatsApp Payments shipping_info
        addressLine1: selCustomer.addressLine1 || '',
        addressLine2: selCustomer.addressLine2 || '',
        city: selCustomer.city || '',
        state: selCustomer.state || '',
        postalCode: selCustomer.postalCode || '',
        landmark: selCustomer.landmark || '',
        goodsType: goodsType,
        items: invForm.items.map( it => ( { name: it.name || config.default_item_name, amount: parseFloat( it.unitPrice ) || 0, quantity: parseInt( it.quantity ) || 1, gstRate: parseFloat( it.gstRate ) || config.default_gst_rate } ) ),
        shipping: parseFloat( invForm.shipping ) || 0,
        discount: parseFloat( invForm.discount ) || 0, gstRate: config.default_gst_rate,
        purpose: DEFAULT_BRAND, orderId: invForm.orderId, gstin: config.gstin,
        preferredGateway: paymentGateway,
        paymentConfiguration: getPGConfigName( paymentGateway, sendPhone ),
        // A CODE, and only when one was typed. Omitted entirely otherwise, because FEAT-002
        // guarantees the no-codes path behaves byte for byte as it did before coupons existed -
        // sending '' would put it through the redemption branch for nothing.
        ...( couponCode.trim() ? { couponCode: couponCode.trim() } : {} ),
        ...( giftCardCode.trim() ? { giftCardCode: giftCardCode.trim() } : {} ),
      };
      /*
       * `createInvoiceEngineResult`, not `createInvoiceEngine`, because a coupon refusal is a 400
       * carrying a typed `errorCode` and the plain wrapper collapses every non-2xx to `null`.
       * "Create failed" in front of a staff member who typed a valid-looking code is not an
       * answer; "That coupon has expired" is.
       */
      const result = await api.createInvoiceEngineResult( req );
      if ( result.ok )
      {
        const r = result.invoice;
        showMsg( `Invoice ${r.invoiceNumber} created \u2014 \u20B9${r.total}` );
        // Every figure here is the SERVER's. Nothing on this page recomputes a discount.
        setRedemption( r );
        setInvForm( { ...EMPTY_INV, items: [ NEW_ITEM() ] } );
        // The gift-card code is a bearer secret: it is cleared and never echoed back into a
        // visible label. The coupon code is not a secret, and the server's NORMALISED spelling of
        // it comes back on the response, so that is what gets shown.
        setCouponCode( '' );
        setGiftCardCode( '' );
        setSelCustomer( null );
        loadInvoices();
      }
      else
      {
        setRedemption( null );
        /*
         * The server's typed code decides the words, and only when a code was actually sent. A
         * create can fail for a dozen reasons that have nothing to do with a coupon, and
         * answering "the coupon could not be applied" to one of those would send a staff member
         * to retype a code that was never the problem. An UNRECOGNISED errorCode on a request
         * that did carry a code degrades to the honest unknown-reason line.
         */
        if ( req.couponCode || req.giftCardCode )
        {
          setRedemptionMsg( REDEMPTION_MESSAGES[ result.errorCode ] || REDEMPTION_UNKNOWN );
        }
        showMsg( 'Create failed', 'error' );
      }
    } catch ( e ) { showMsg( 'Create failed', 'error' ); }
    setCreating( false );
  };

  /* Invoice action handlers */
  const PHONE_OPTIONS = [
    { id: 'phone-number-id-waba-t-direct-1055232054343117', label: '+91 99033 00044' },
    { id: 'phone-number-id-waba1-direct-1016149501586345', label: '+91 93309 94400' },
  ];
  // PayU removed 2026-08-23 - no PayU payment configuration exists on either
  // WABA. Both WABAs expose only WECAREDIGITAL (Razorpay) and WECAREUPI.
  const PG_OPTIONS = [
    { id: 'razorpay', label: 'Razorpay' },
  ];
  /*
   * The same two lists in the shape Select takes - `id` becomes `value`, nothing else moves.
   * Derived here beside the arrays they come from, which are themselves rebuilt per render.
   * The phone id is the Meta phone-number id the payment link is sent FROM, so the value set
   * is fixed by the account rather than by this page.
   */
  const phoneSelectOptions: SelectOption[] = PHONE_OPTIONS.map( p => ( { value: p.id, label: p.label } ) );
  const pgSelectOptions: SelectOption[] = PG_OPTIONS.map( pg => ( { value: pg.id, label: pg.label } ) );
  // Map gateway + phone to the correct Meta config name
  // CRITICAL: Each WABA has its own config names — never cross-WABA
  const getPGConfigName = ( pg: string, phoneId: string ) => {
    // Both WABAs now expose the identical pair WECAREDIGITAL / WECAREUPI, so the
    // phone no longer affects the config name and cross-WABA mixing is impossible.
    return 'WECAREDIGITAL';
  };
  const doSendPaymentLink = async ( inv: Invoice ) => {
    setActionLoading( 'send' );
    try
    {
      const pgConfig = getPGConfigName( paymentGateway, sendPhone );
      const r = await api.sendPaymentLink( inv.invoiceId, sendPhone, pgConfig || undefined );
      const pgLabel = 'Razorpay';
      const phoneLabel = PHONE_OPTIONS.find( p => p.id === sendPhone )?.label || sendPhone;
      if ( r ) { showMsg( `Sent via ${pgLabel} from ${phoneLabel}` ); loadInvoices(); } else showMsg( 'Send failed', 'error' );
    } catch ( e ) { showMsg( 'Send failed', 'error' ); }
    setActionLoading( '' );
  };
  const doCancelInvoice = async ( inv: Invoice ) => {
    if ( !( await confirm( 'Cancel this invoice?' ) ) ) return;
    setActionLoading( 'cancel' );
    try { const r = await api.cancelInvoice( inv.invoiceId ); if ( r ) { showMsg( 'Invoice cancelled' ); setSelInvoice( null ); loadInvoices(); } else showMsg( 'Cancel failed', 'error' ); } catch ( e ) { showMsg( 'Cancel failed', 'error' ); }
    setActionLoading( '' );
  };
  const doGenerateImage = async ( inv: Invoice ) => {
    setActionLoading( 'img' );
    try { await api.generateInvoiceImage( inv.invoiceId ); showMsg( 'Image generated' ); } catch ( e ) { showMsg( 'Failed', 'error' ); }
    setActionLoading( '' );
  };
  const doGeneratePdf = async ( inv: Invoice ) => {
    setActionLoading( 'pdf' );
    try { await api.generateInvoicePdf( inv.invoiceId ); showMsg( 'PDF generated' ); } catch ( e ) { showMsg( 'Failed', 'error' ); }
    setActionLoading( '' );
  };
  const doDeleteInvoice = async ( inv: Invoice ) => {
    const adjustSeq = await confirm( { message: 'Delete this invoice?\n\nConfirm to also adjust sequence, Cancel to keep sequence.', title: 'Adjust Sequence?', confirmText: 'Adjust', cancelText: 'Keep' } );
    if ( !( await confirm( `Permanently delete invoice ${inv.invoiceNumber || inv.referenceId}?` ) ) ) return;
    setActionLoading( 'delete' );
    try { const r = await api.deleteInvoice( inv.invoiceId, adjustSeq ); if ( r?.deleted ) { showMsg( 'Invoice deleted' ); setSelInvoice( null ); loadInvoices(); } else showMsg( 'Delete failed', 'error' ); } catch ( e ) { showMsg( 'Delete failed', 'error' ); }
    setActionLoading( '' );
  };
  const openRemarkModal = ( inv: Invoice, type: 'remark' | 'refund' | 'credit_note' ) => { setRemarkModal( { inv, type } ); setRemarkText( '' ); setRemarkAmount( '' ); };
  const submitRemark = async () => {
    if ( !remarkModal ) return;
    setActionLoading( 'remark' );
    try
    {
      const r = await api.addInvoiceRemark( remarkModal.inv.invoiceId, remarkModal.type, remarkText, parseFloat( remarkAmount ) || 0 );
      if ( r ) { showMsg( `${remarkModal.type === 'remark' ? 'Remark' : remarkModal.type === 'refund' ? 'Refund' : 'Credit note'} added` ); setRemarkModal( null ); loadInvoices(); }
      else showMsg( 'Failed', 'error' );
    } catch ( e ) { showMsg( 'Failed', 'error' ); }
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
      shipping: String( inv.shipping || 0 ),
      discount: String( inv.discount || 0 ),
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
        shipping: parseFloat( editForm.shipping ) || 0,
        discount: parseFloat( editForm.discount ) || 0,
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
  const selectInvoice = ( inv: Invoice ) => { setSelInvoice( inv ); loadDeliveryLogs( inv.invoiceId ); };

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
    <PageShell title="Flow" subtitle="Customers, Invoices & Payments" tabs={ TABS } defaultTab="customers">
      { ( activeTab ) => (
        <div className="inner-page">
          { msg && <div className={ `msg-bar ${msg.type}` } style={ { margin: '0 0 16px' } }>{ msg.text }<button onClick={ () => setMsg( null ) } style={ { background: 'none', border: 'none', cursor: 'pointer', marginLeft: 8 } }>{ '\u2715' }</button></div> }

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
              { editCust && (
                <div className="pf-modal-overlay" onClick={ closeEditCust }>
                  <div className="pf-modal-box" onClick={ e => e.stopPropagation() }>
                    <div className="pf-modal-header">
                      <h3>{ editCust.id ? 'Edit Customer' : 'New Customer' }</h3>
                      <Button variant="ghost" size="sm" onClick={ closeEditCust }>{ '\u2715' }</Button>
                    </div>
                    <div className="form-group"><label>Name</label><input type="text" value={ custForm.name } onChange={ e => setCustForm( { ...custForm, name: e.target.value } ) } placeholder="Enter full name" /></div>
                    <div className="form-group"><label>Phone</label><input type="tel" value={ custForm.phone } onChange={ e => setCustForm( { ...custForm, phone: e.target.value } ) } placeholder="Include country code" /></div>
                    <div className="form-group"><label>Email</label><input type="email" value={ custForm.email } onChange={ e => setCustForm( { ...custForm, email: e.target.value } ) } placeholder="Enter email address" /></div>
                    { /* ONE address input group. The free-text "Delivery Address" textarea that
                         used to sit here is the read-only composed preview inside this block
                         now, so the eight fields are the only place an address is typed. */ }
                    <AddressFieldGroup
                      idPrefix="pf-cust-addr"
                      value={ custForm }
                      onChange={ next => setCustForm( { ...custForm, ...next } ) }
                      fallback={ custForm.shippingAddress }
                    />
                    <div className="pf-modal-actions">
                      <Button variant="secondary" size="sm" onClick={ closeEditCust }>Cancel</Button>
                      <Button variant="primary" size="sm" loading={ custSaving } onClick={ saveCust }>Save</Button>
                    </div>
                  </div>
                </div>
              ) }
            </div>
          ) }

          {/* CREATE INVOICE TAB */ }
          { activeTab === 'create' && (
            <div className="pf-tab-body">
              { /*
                 * WHAT THE SERVER DECIDED ABOUT THE COUPON AND THE GIFT CARD.
                 *
                 * Outside the customer-step branch on purpose: a successful create clears
                 * `selCustomer` to reset the form, so anything rendered inside that branch
                 * unmounts at exactly the moment it has something to say. Every figure below is
                 * read straight off the response — there is no arithmetic on this page that
                 * produces a discount, and `fmtPaise` formats the gift-card leg by slicing the
                 * integer-paise string rather than dividing it.
                 */ }
              { redemptionMsg && (
                <div className="msg-bar error" style={ { margin: '0 0 12px', fontSize: 12 } } role="status">{ redemptionMsg }</div>
              ) }
              { redemption && (
                <div className="inner-card" style={ { marginBottom: 16, maxWidth: 500, padding: '10px 14px' } }>
                  <h4 style={ { margin: '0 0 6px', fontSize: 13, color: '#1a3a2a' } }>Applied on the last invoice</h4>
                  { redemption.couponCode && typeof redemption.couponDiscount === 'number' && (
                    <div className="pf-preview-row"><span>Coupon { redemption.couponCode }</span><span>{ '\u2212' }{ fmtMoney( redemption.couponDiscount ) }</span></div>
                  ) }
                  { typeof redemption.giftCardAppliedPaise === 'number' && (
                    <div className="pf-preview-row"><span>Paid by gift card</span><span>{ '\u2212' }{ fmtPaise( redemption.giftCardAppliedPaise ) }</span></div>
                  ) }
                  { typeof redemption.amountPayable === 'number' && (
                    <div className="pf-preview-row"><span>Left to pay</span><span>{ fmtMoney( redemption.amountPayable ) }</span></div>
                  ) }
                  { redemption.giftCardFullyCovered && (
                    <p style={ { fontSize: 11, color: '#6b7280', margin: '6px 0 0' } }>
                      Fully covered by the gift card, so no payment link can be sent for it.
                    </p>
                  ) }
                </div>
              ) }
              { !selCustomer ? (
                <div>
                  <h3 style={ { margin: '0 0 12px', fontSize: 18 } }>Step 1 { '\u2014' } Select Customer</h3>
                  <input className="search-input" placeholder="Search\u2026" value={ custSearch } onChange={ e => setCustSearch( e.target.value ) } style={ { marginBottom: 16, maxWidth: 400 } } />
                  <div className="pf-cust-grid">
                    { filteredCust.map( c => (
                      <div key={ c.id } onClick={ () => {
                        setSelCustomer( c );
                        // Don't auto-set goods type — default is digital-goods.
                        // Admin should explicitly select physical-goods when needed.
                        // Auto-switching caused invoices to incorrectly trigger address collection.
                        // Auto-append Green Packing + Notification Fee as last items
                        setInvForm( prev => {
                          const items = [ ...prev.items ];
                          const names = items.map( it => it.name.toLowerCase() );
                          if ( !names.some( n => n.includes( 'green' ) && n.includes( 'pack' ) ) ) items.push( { name: 'Green Packing', unitPrice: '49', quantity: '1', gstRate: '18' } );
                          if ( !names.some( n => n.includes( 'notification' ) || n.includes( 'alert' ) ) ) items.push( { name: 'Notification Fee', unitPrice: '19', quantity: '1', gstRate: '18' } );
                          return { ...prev, items };
                        } );
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
                <div>
                  <div className="info-banner" style={ { marginBottom: 16 } }>
                    <div style={ { flex: 1 } }><strong>{ selCustomer.name }</strong> { '\u2014' } { selCustomer.phone } { selCustomer.email ? ` \u00B7 ${selCustomer.email}` : '' }</div>
                    <Button variant="ghost" size="sm" onClick={ () => setSelCustomer( null ) }>Change</Button>
                  </div>
                  {/* Address display */ }
                  { selCustomer.shippingAddress && (
                    <div className="inner-card" style={ { marginBottom: 16, maxWidth: 600, padding: '10px 14px', fontSize: 12, color: '#555', background: '#f8faf9', border: '1px solid #e0e8e3', borderRadius: 8 } }>
                      <div><strong>Delivery Address:</strong> { selCustomer.shippingAddress }</div>
                    </div>
                  ) }
                  <h3 style={ { margin: '0 0 12px', fontSize: 18 } }>Step 2 { '\u2014' } Invoice Details</h3>
                  <div className="table-container" style={ { marginBottom: 16 } }>
                    <table className="inner-table">
                      <thead><tr><th>#</th><th>Item Name</th><th>Price ({ '\u20B9' })</th><th>Qty</th><th>GST %</th><th>Line Total</th><th></th></tr></thead>
                      <tbody>
                        { invForm.items.map( ( it, i ) => {
                          const line = ( parseFloat( it.unitPrice ) || 0 ) * ( parseInt( it.quantity ) || 0 );
                          const gst = line * ( parseFloat( it.gstRate ) || 0 ) / 100;
                          return (
                            <tr key={ i }>
                              <td>{ i + 1 }</td>
                              <td><input type="text" value={ it.name } onChange={ e => updateItem( i, 'name', e.target.value ) } placeholder={ config.default_item_name } className="pf-inline-input" /></td>
                              <td><input type="number" value={ it.unitPrice } onChange={ e => updateItem( i, 'unitPrice', e.target.value ) } className="pf-num-input" /></td>
                              <td><input type="number" value={ it.quantity } onChange={ e => updateItem( i, 'quantity', e.target.value ) } className="pf-num-input-sm" /></td>
                              <td><input type="number" value={ it.gstRate } onChange={ e => updateItem( i, 'gstRate', e.target.value ) } className="pf-num-input-sm" /></td>
                              <td style={ { fontWeight: 600 } }>{ fmtMoney( line + gst ) }</td>
                              <td>{ invForm.items.length > 1 && <button onClick={ () => removeItem( i ) } className="pf-remove-btn">{ '\u2715' }</button> }</td>
                            </tr>
                          );
                        } ) }
                      </tbody>
                    </table>
                  </div>
                  <Button variant="secondary" size="sm" onClick={ addItem } style={ { marginBottom: 4 } }>+ Add Item</Button>
                  { ' ' }
                  <Button variant="ghost" size="sm" onClick={ () => {
                    const items = [ ...invForm.items ];
                    const names = items.map( it => it.name.toLowerCase() );
                    if ( !names.some( n => n.includes( 'green' ) && n.includes( 'pack' ) ) ) items.push( { name: 'Green Packing', unitPrice: '49', quantity: '1', gstRate: '18' } );
                    if ( !names.some( n => n.includes( 'notification' ) || n.includes( 'alert' ) ) ) items.push( { name: 'Notification Fee', unitPrice: '19', quantity: '1', gstRate: '18' } );
                    setInvForm( { ...invForm, items } );
                  } } style={ { marginBottom: 4, fontSize: 12, color: '#1a3a2a' } }>+ Green Packing & Notification Fee</Button>
                  <h4 style={ { margin: '12px 0 8px', fontSize: 15 } }>Additional Charges</h4>
                  <div className="pf-form-grid">
                    <div className="form-group"><label htmlFor="pf-shipping">Express / Shipping ({ '\u20B9' })</label><input id="pf-shipping" type="number" value={ invForm.shipping } onChange={ e => setInvForm( { ...invForm, shipping: e.target.value } ) } /></div>
                    { /* DECISION D4: "Manual adjustment", not "Promo / Discount", and it defaults
                         to 0. A goodwill credit a staff member decides on is a different fact
                         from a coupon the store issued, and the old shared label over a silent
                         Rs.15 default was what made them look like one mechanism. */ }
                    <div className="form-group"><label htmlFor="pf-manual-adjustment">Manual adjustment ({ '\u20B9' })</label><input id="pf-manual-adjustment" type="number" value={ invForm.discount } onChange={ e => setInvForm( { ...invForm, discount: e.target.value } ) } /></div>

                  </div>
                  { /* COUPON + GIFT CARD. Codes only: there is no input on this page through
                       which an amount could be sent, and no arithmetic here that produces one.
                       Everything displayed below comes back from the server. */ }
                  <h4 style={ { margin: '12px 0 8px', fontSize: 15 } }>Coupon &amp; Gift Card</h4>
                  <div className="pf-form-grid">
                    <div className="form-group">
                      <label htmlFor="pf-coupon-code">Coupon code</label>
                      <input id="pf-coupon-code" type="text" autoComplete="off" value={ couponCode }
                        onChange={ e => setCouponCode( e.target.value ) } placeholder="Optional" />
                    </div>
                    <div className="form-group">
                      <label htmlFor="pf-giftcard-code">Gift card code</label>
                      <input id="pf-giftcard-code" type="text" autoComplete="off" value={ giftCardCode }
                        onChange={ e => setGiftCardCode( e.target.value ) } placeholder="Optional" />
                    </div>
                  </div>
                  { /* The server's answer about these codes is rendered ABOVE the customer step,
                       outside this branch, because a successful create clears the selected
                       customer and would otherwise unmount the one record of what was applied. */ }
                  <div className="pf-form-grid">
                    <div className="form-group">
                      { /* The `.form-group` captions on this page are UNASSOCIATED labels - no
                           `for`, no wrapped control - so they were never a name source and these
                           controls had no accessible name at all. Each caption stays where it is
                           and the control takes `ariaLabel`, which adds a name where there was
                           none and changes nothing on screen. */ }
                      <label>Brand</label>
                      <input aria-label="Brand" value={ DEFAULT_BRAND } readOnly />
                    </div>
                    <div className="form-group"><label>Order ID</label><input type="text" value={ invForm.orderId } onChange={ e => setInvForm( { ...invForm, orderId: e.target.value } ) } placeholder="Optional" /></div>
                  </div>
                  <div className="pf-form-grid">
                    <div className="form-group">
                      <label>Send From</label>
                      <Select ariaLabel="Send from" value={ sendPhone }
                        onChange={ v => setSendPhone( v ) }
                        options={ phoneSelectOptions } />
                    </div>
                    <div className="form-group">
                      <label>Payment Gateway</label>
                      <Select ariaLabel="Payment gateway" value={ paymentGateway }
                        onChange={ v => setPaymentGateway( v ) }
                        options={ pgSelectOptions } />
                    </div>
                    <div className="form-group">
                      <label>Goods Type</label>
                      { /* The cast is preserved verbatim and the two option values are exactly
                           the two members of that union - `goodsType` travels into the invoice
                           request, so the value contract may not be loosened. */ }
                      <Select ariaLabel="Goods type" value={ goodsType }
                        onChange={ v => setGoodsType( v as any ) }
                        options={ GOODS_TYPE_OPTIONS } />
                    </div>
                  </div>
                  { goodsType === 'physical-goods' && !selCustomer?.shippingAddress && (
                    <div className="msg-bar error" style={ { margin: '0 0 12px', fontSize: 12 } }>Physical goods require a shipping address. Add one in the Customers tab.</div>
                  ) }
                  <div className="inner-card" style={ { marginBottom: 20, maxWidth: 500 } }>
                    <h4 style={ { margin: '0 0 8px', fontSize: 14 } }>Preview</h4>
                    { goodsType === 'physical-goods' && selCustomer?.shippingAddress && (
                      <div style={ { fontSize: 11, color: '#1e40af', background: '#dbeafe', padding: '4px 8px', borderRadius: 6, marginBottom: 8 } }>📦 Physical Goods — Delivery: { selCustomer.shippingAddress }</div>
                    ) }
                    <div className="pf-preview-row"><span>Subtotal</span><span>{ fmtMoney( calcSubtotal() ) }</span></div>
                    { invForm.items.map( ( it, i ) => {
                      const line = ( parseFloat( it.unitPrice ) || 0 ) * ( parseInt( it.quantity ) || 0 );
                      return line > 0 ? <div key={ i } className="pf-preview-row" style={ { fontSize: 12, color: '#666' } }><span>{ '\u00A0\u00A0' }{ it.name || `Item ${i + 1}` } { '\u00D7' }{ it.quantity || 1 }</span><span>{ fmtMoney( line ) }</span></div> : null;
                    } ) }
                    <div className="pf-preview-row"><span>Tax (GST)</span><span>{ fmtMoney( calcTax() ) }</span></div>
                    <div className="pf-preview-row"><span>Express</span><span>{ fmtMoney( parseFloat( invForm.shipping ) || 0 ) }</span></div>
                    { /* The manual adjustment gets its OWN preview row, and there is deliberately
                         no coupon row beside it: a coupon's value is the server's answer and is
                         not known until the create comes back, so showing one here would mean
                         computing a discount in the browser. The applied coupon and gift-card
                         figures appear above, after the server has decided them. */ }
                    <div className="pf-preview-row"><span>Manual adjustment</span><span>{ '\u2212' }{ fmtMoney( parseFloat( invForm.discount ) || 0 ) }</span></div>
                    <div className="pf-preview-row"><span>Conv Fee</span><span>{ fmtMoney( calcConvFee() ) }</span></div>
                    <div className="pf-preview-total"><span>Total</span><span>{ fmtMoney( calcTotal() ) }</span></div>
                  </div>

                  {/* Post-payment messaging options */ }
                  <div className="inner-card" style={ { marginBottom: 16, maxWidth: 500, padding: '10px 14px' } }>
                    <h4 style={ { margin: '0 0 6px', fontSize: 13, color: '#1a3a2a' } }>After Payment</h4>
                    <p style={ { fontSize: 11, color: '#6b7280', margin: '0 0 8px' } }>
                      When payment is captured, these messages are sent automatically via WhatsApp.
                    </p>
                    <div style={ { display: 'flex', flexDirection: 'column', gap: 4 } }>
                      <label style={ { display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#374151' } }>
                        <input type="checkbox" defaultChecked disabled style={ { accentColor: '#1a3a2a' } } />
                        Invoice PDF + payment confirmation
                      </label>
                      <label style={ { display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#374151' } }>
                        <input type="checkbox" defaultChecked disabled style={ { accentColor: '#1a3a2a' } } />
                        Order status interactive message
                      </label>
                      <label style={ { display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#6b7280' } }>
                        <input type="checkbox" disabled style={ { accentColor: '#1a3a2a' } } />
                        Template message (requires approved template)
                      </label>
                    </div>
                  </div>

                  <Button variant="primary" size="md" loading={ creating } onClick={ submitInvoice }>Create Invoice</Button>
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
                        { invoices.length === 0 && <tr className="empty-row"><td colSpan={ 8 }>No invoices</td></tr> }
                        { invoices.map( ( inv, i ) => (
                          <tr key={ inv.invoiceId } onClick={ () => selectInvoice( inv ) } style={ { cursor: 'pointer' } } className={ selInvoice?.invoiceId === inv.invoiceId ? 'pf-row-selected' : '' }>
                            <td>{ i + 1 }</td>
                            <td style={ { fontFamily: 'monospace', fontSize: 12 } }>{ inv.referenceId || '\u2014' }</td>
                            <td style={ { fontWeight: 600 } }>{ inv.customerName || inv.customerPhone || '\u2014' }</td>
                            <td>{ fmtMoney( inv.total ) }</td>
                            <td><span className={ `status-badge ${badgeClass( inv )}` }>{ inv.status }</span></td>
                            <td><span style={ { padding: '2px 8px', borderRadius: 12, fontSize: 11, fontWeight: 500, background: '#f9fafb', color: '#1a3a2a' } }>{ inv.entryPoint || 'manual' }</span></td>
                            <td>{ fmtDate( inv.createdAt ) }</td>
                            <td onClick={ e => e.stopPropagation() }><button onClick={ () => doDeleteInvoice( inv ) } style={ { background: 'none', border: 'none', cursor: 'pointer', color: '#dc2626', fontSize: 13, padding: '2px 6px' } } title="Delete">🗑</button></td>
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
                    <div className="pf-detail-row"><span className="label">Source</span><span style={ { padding: '2px 8px', borderRadius: 12, fontSize: 11, fontWeight: 500, background: '#f9fafb', color: '#1a3a2a' } }>{ selInvoice.entryPoint || 'manual' }</span></div>
                    <div className="pf-detail-row"><span className="label">Ref</span><span className="mono">{ selInvoice.referenceId || '\u2014' }</span></div>
                    <div className="pf-detail-row"><span className="label">Customer</span><span>{ selInvoice.customerName || '\u2014' }</span></div>
                    <div className="pf-detail-row"><span className="label">Phone</span><span>{ selInvoice.customerPhone || '\u2014' }</span></div>
                    <div className="pf-detail-row"><span className="label">Brand</span><span>{ selInvoice.purpose || '\u2014' }</span></div>
                    <div className="pf-detail-row"><span className="label">Order</span><span>{ selInvoice.orderId || '\u2014' }</span></div>
                    { selInvoice.goodsType && <div className="pf-detail-row"><span className="label">Type</span><span style={ { padding: '2px 8px', borderRadius: 12, fontSize: 11, fontWeight: 500, background: selInvoice.goodsType === 'physical-goods' ? '#dbeafe' : '#f3e8ff', color: selInvoice.goodsType === 'physical-goods' ? '#1e40af' : '#6b21a8' } }>{ selInvoice.goodsType === 'physical-goods' ? 'Physical' : 'Digital' }</span></div> }
                    { selInvoice.shippingAddress && <div className="pf-detail-row" style={ { alignItems: 'flex-start' } }><span className="label">Delivery Address</span><span style={ { fontSize: 11, color: '#555', maxWidth: 200, wordBreak: 'break-word' } }>{ selInvoice.shippingAddress }</span></div> }
                    <div className="pf-section-divider">
                      <div className="pf-detail-row"><span className="label">Subtotal</span><span>{ fmtMoney( selInvoice.subtotal ) }</span></div>
                      <div className="pf-detail-row"><span className="label">Tax</span><span>{ fmtMoney( selInvoice.tax ) }</span></div>
                      <div className="pf-detail-row"><span className="label">Express</span><span>{ fmtMoney( selInvoice.shipping ) }</span></div>
                      { /* TWO LINES FOR TWO FACTS, matching what `_build_invoice_html` and
                           `_generate_receipt_png` now print. `invoice.discount` is the SUM of the
                           staff adjustment and the coupon (Meta validates
                           total == subtotal + tax + shipping - discount, so it has to be), which
                           makes the manual part `discount - couponDiscount`. An invoice raised
                           before coupons existed carries no `couponDiscount` at all, and that
                           absence is why the coupon row is conditional rather than showing
                           Rs.0.00 - which would claim a coupon was applied and was worthless. */ }
                      { typeof selInvoice.couponDiscount === 'number' && (
                        <div className="pf-detail-row"><span className="label">Coupon { selInvoice.couponCode || '' }</span><span>{ '\u2212' }{ fmtMoney( selInvoice.couponDiscount ) }</span></div>
                      ) }
                      <div className="pf-detail-row"><span className="label">Manual adjustment</span><span>{ '\u2212' }{ fmtMoney( selInvoice.discount - ( selInvoice.couponDiscount || 0 ) ) }</span></div>
                      { selInvoice.convenienceFee > 0 && <div className="pf-detail-row"><span className="label">Conv Fee</span><span>{ fmtMoney( selInvoice.convenienceFee ) }</span></div> }
                      <div className="pf-detail-total"><span>Total</span><span>{ fmtMoney( selInvoice.total ) }</span></div>
                      { /* Gift-card tender, below the total because it is NOT a price change: the
                           total is what the invoice is for, `amountPayable` is what Razorpay will
                           collect. `giftCardLast4` is the only part of a code ever stored or
                           shown in clear. */ }
                      { typeof selInvoice.giftCardRequiredPaise === 'number' && (
                        <div className="pf-detail-row"><span className="label">Paid by gift card { selInvoice.giftCardLast4 ? `****${selInvoice.giftCardLast4}` : '' }</span><span>{ '\u2212' }{ fmtPaise( selInvoice.giftCardRequiredPaise ) }</span></div>
                      ) }
                      { typeof selInvoice.amountPayable === 'number' && (
                        <div className="pf-detail-row"><span className="label">Left to pay</span><span>{ fmtMoney( selInvoice.amountPayable ) }</span></div>
                      ) }
                    </div>
                    { selInvoice.items && selInvoice.items.length > 0 && (
                      <div className="pf-section-divider">
                        <div className="pf-section-title">Items</div>
                        { selInvoice.items.map( ( it, i ) => (
                          <div key={ i } style={ { display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 4 } }>
                            <span>{ it.name } { '\u00D7' }{ it.quantity }</span><span>{ fmtMoney( it.amount * it.quantity ) }</span>
                          </div>
                        ) ) }
                      </div>
                    ) }
                    <div className="pf-action-stack">
                      { ( selInvoice.status === 'created' || selInvoice.status === 'pending_payment' ) && (
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
                            <label style={ { fontSize: 12, fontWeight: 500, whiteSpace: 'nowrap' } }>From</label>
                            <Select ariaLabel="Send from" value={ sendPhone }
                              onChange={ v => setSendPhone( v ) }
                              options={ phoneSelectOptions } style={ DETAIL_SELECT_STYLE } />
                          </div>
                          <div style={ { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 } }>
                            <label style={ { fontSize: 12, fontWeight: 500, whiteSpace: 'nowrap' } }>PG</label>
                            <Select ariaLabel="Payment gateway" value={ paymentGateway }
                              onChange={ v => setPaymentGateway( v ) }
                              options={ pgSelectOptions } style={ DETAIL_SELECT_STYLE } />
                          </div>
                          <Button variant="primary" size="sm" loading={ actionLoading === 'send' } onClick={ () => doSendPaymentLink( selInvoice ) }>
                            { selInvoice.status === 'pending_payment' ? 'Resend Payment Link' : 'Send Payment Link' }
                          </Button>
                        </>
                      ) }
                      <Button variant="secondary" size="sm" loading={ actionLoading === 'img' } onClick={ () => doGenerateImage( selInvoice ) }>Generate Image</Button>
                      <Button variant="secondary" size="sm" loading={ actionLoading === 'pdf' } onClick={ () => doGeneratePdf( selInvoice ) }>Generate PDF</Button>
                      { selInvoice.status !== 'paid' && selInvoice.status !== 'cancelled' && (
                        <Button variant="secondary" size="sm" loading={ actionLoading === 'edit' } onClick={ () => openEditModal( selInvoice ) }>Edit Invoice</Button>
                      ) }
                      <Button variant="secondary" size="sm" onClick={ () => openRemarkModal( selInvoice, 'remark' ) }>Add Remark</Button>
                      { ( selInvoice.status === 'paid' || selInvoice.paymentStatus === 'captured' ) && (
                        <>
                          <Button variant="secondary" size="sm" onClick={ () => openRemarkModal( selInvoice, 'refund' ) }>Refund</Button>
                          <Button variant="secondary" size="sm" onClick={ () => openRemarkModal( selInvoice, 'credit_note' ) }>Credit Note</Button>
                        </>
                      ) }
                      { selInvoice.status !== 'paid' && selInvoice.status !== 'cancelled' && (
                        <Button variant="danger" size="sm" loading={ actionLoading === 'cancel' } onClick={ () => doCancelInvoice( selInvoice ) }>Cancel Invoice</Button>
                      ) }
                      <Button variant="danger" size="sm" loading={ actionLoading === 'delete' } onClick={ () => doDeleteInvoice( selInvoice ) }>Delete</Button>
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
                                <div style={ { fontSize: 12, marginTop: 2 } }>{ r.text }</div>
                                <div style={ { fontSize: 11, color: '#888' } }>{ r.author } { '\u00B7' } { fmtDate( r.createdAt ) }</div>
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
                        <td style={ { fontFamily: 'monospace', fontSize: 12 } }>{ inv.referenceId || '\u2014' }</td>
                        <td style={ { fontWeight: 600 } }>{ inv.customerName || '\u2014' }</td>
                        <td>{ inv.customerPhone || '\u2014' }</td>
                        <td>{ fmtMoney( inv.total ) }</td>
                        <td>{ fmtDate( inv.createdAt ) }</td>
                        <td>
                          <div style={ { display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap' } }>
                            { /* The two in-table choosers on the Dues row. These were the
                                 smallest controls on the page - 4px/6px padding around 11px
                                 type, well under the 44px tap floor - so they get visibly
                                 taller, which is the same move every other in-table control in
                                 this migration made. They state a flex basis because the cell
                                 is a wrapping flex row and the trigger fills its field. */ }
                            <Select ariaLabel="Send from" value={ sendPhone }
                              onChange={ v => setSendPhone( v ) }
                              options={ phoneSelectOptions } style={ DUES_PHONE_SELECT_STYLE } />
                            <Select ariaLabel="Payment gateway" value={ paymentGateway }
                              onChange={ v => setPaymentGateway( v ) }
                              options={ pgSelectOptions } style={ DUES_PG_SELECT_STYLE } />
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
              <h3 style={ { margin: '0 0 16px', fontSize: 18 } }>Flow Configuration</h3>
              <div className="form-group"><label>Default GST Rate (%)</label><input type="number" value={ config.default_gst_rate } onChange={ e => setConfig( { ...config, default_gst_rate: parseFloat( e.target.value ) || 0 } ) } /></div>
              <div className="form-group"><label>Default Express / Shipping ({ '\u20B9' })</label><input type="number" value={ config.default_shipping } onChange={ e => setConfig( { ...config, default_shipping: parseFloat( e.target.value ) || 0 } ) } /></div>
              <div className="form-group"><label>Default Manual adjustment ({ '\u20B9' })</label><input type="number" value={ config.default_promo } onChange={ e => setConfig( { ...config, default_promo: parseFloat( e.target.value ) || 0 } ) } /></div>
              <div className="form-group"><label>GSTIN</label><input type="text" value={ config.gstin } onChange={ e => setConfig( { ...config, gstin: e.target.value } ) } /></div>
              <div className="form-group"><label>Default Item Name</label><input type="text" value={ config.default_item_name } onChange={ e => setConfig( { ...config, default_item_name: e.target.value } ) } /></div>
              { /* THE BRAND LIST EDITOR IS GONE, not hidden. The owner asked for the brand
                   section removed with WECARE.DIGITAL hardcoded as the default, and
                   `loadSavedConfig` now pins `purposes` to DEF_CFG - so a textarea here would
                   have been an input whose value is discarded on the next load, which is worse
                   than no control at all. */ }
              <div className="form-group">
                <label>Brand</label>
                <input type="text" value={ DEFAULT_BRAND } readOnly aria-readonly="true" />
                <p style={ { fontSize: 11, color: '#6b7280', margin: '4px 0 0' } }>Invoices are issued by WECARE.DIGITAL.</p>
              </div>
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
                  <div className="form-group"><label>Brand</label>
                    <input aria-label="Brand" value={ DEFAULT_BRAND } readOnly />
                  </div>
                  <div className="form-group"><label>Express / Shipping ({ '₹' })</label><input type="number" value={ editForm.shipping } onChange={ e => setEditForm( { ...editForm, shipping: e.target.value } ) } /></div>
                  <div className="form-group"><label>Manual adjustment ({ '₹' })</label><input type="number" value={ editForm.discount } onChange={ e => setEditForm( { ...editForm, discount: e.target.value } ) } /></div>
                  <div className="form-group"><label>Order ID</label><input type="text" value={ editForm.orderId } onChange={ e => setEditForm( { ...editForm, orderId: e.target.value } ) } /></div>
                  <div className="form-group"><label>Notes</label><textarea rows={ 2 } value={ editForm.notes } onChange={ e => setEditForm( { ...editForm, notes: e.target.value } ) } /></div>
                </div>
                { /* The same eight fields and the same composition as the customer modal, from
                     the same module. The free-text address textarea that was here is the
                     read-only preview now; a coupon or gift-card code is NOT editable from here
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
                  <h3>{ remarkModal.type === 'remark' ? 'Add Remark' : remarkModal.type === 'refund' ? 'Record Refund' : 'Credit Note' }</h3>
                  <Button variant="ghost" size="sm" onClick={ () => setRemarkModal( null ) }>{ '\u2715' }</Button>
                </div>
                <div className="pf-detail-row" style={ { marginBottom: 12 } }>
                  <span className="label">Invoice</span>
                  <span className="mono">{ remarkModal.inv.referenceId || remarkModal.inv.invoiceNumber }</span>
                </div>
                { ( remarkModal.type === 'refund' || remarkModal.type === 'credit_note' ) && (
                  <div className="form-group">
                    <label>Amount ({ '\u20B9' })</label>
                    <input type="number" value={ remarkAmount } onChange={ e => setRemarkAmount( e.target.value ) } placeholder="0" />
                  </div>
                ) }
                <div className="form-group">
                  <label>{ remarkModal.type === 'remark' ? 'Note' : 'Reason' }</label>
                  <textarea rows={ 3 } value={ remarkText } onChange={ e => setRemarkText( e.target.value ) } placeholder={ remarkModal.type === 'remark' ? 'Enter remark...' : 'Reason for ' + remarkModal.type.replace( '_', ' ' ) + '...' } />
                </div>
                <div className="pf-modal-actions">
                  <Button variant="secondary" size="sm" onClick={ () => setRemarkModal( null ) }>Cancel</Button>
                  <Button variant={ remarkModal.type === 'refund' ? 'danger' : 'primary' } size="sm" loading={ actionLoading === 'remark' } onClick={ submitRemark }>
                    { remarkModal.type === 'remark' ? 'Save Remark' : remarkModal.type === 'refund' ? 'Confirm Refund' : 'Issue Credit Note' }
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
