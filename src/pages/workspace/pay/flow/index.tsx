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

interface PP { signOut?: () => void; user?: any; embedded?: boolean; }
interface FC { default_gst_rate: number; default_shipping: number; default_promo: number; gstin: string; default_item_name: string; purposes: string[]; }
interface IR { name: string; unitPrice: string; quantity: string; gstRate: string; }

const EMPTY_FORM = { name: '', phone: '', email: '', shippingAddress: '', billingAddress: '', addressLine1: '', addressLine2: '', city: '', state: '', postalCode: '', landmark: '', gstin: '', houseNumber: '', buildingName: '' };
const NEW_ITEM = (): IR => ( { name: '', unitPrice: '', quantity: '1', gstRate: '18' } );
const EMPTY_INV = { items: [ NEW_ITEM() ] as IR[], shipping: '49', discount: '15', purpose: '', orderId: '' };
const DEF_CFG: FC = { default_gst_rate: 18, default_shipping: 49, default_promo: 15, gstin: DEFAULT_GSTIN || '19AAFFW7196L1Z8', default_item_name: 'Services/Goods', purposes: [ 'BNB Club', 'No Fault', 'Expo Week', 'Ritual Guru', 'Legal Champ', 'WECARE.DIGITAL', 'Gift Card', 'Service Fee', 'Consultation' ] };
const TABS: ShellTab[] = [
  { id: 'customers', label: 'Customers' },
  { id: 'create', label: 'Create' },
  { id: 'invoices', label: 'Invoices' },
  { id: 'dues', label: 'Dues' },
  { id: 'config', label: 'Config' },
];
const CFG_KEY = 'wecare_flow_config';
const loadSavedConfig = (): FC => {
  try { const s = localStorage.getItem( CFG_KEY ); if ( s ) return { ...DEF_CFG, ...JSON.parse( s ) }; } catch { }
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
/* The empty row is a real option, not a `placeholder`, so the DOM still offers "no brand". */
const BRAND_EMPTY_OPTION: SelectOption = { value: '', label: '\u2014 Select \u2014' };
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
    // Parse structured address JSON if available (from subscribe flow)
    let addrFields = { addressLine1: '', addressLine2: '', city: '', state: '', postalCode: '', landmark: '', houseNumber: '', buildingName: '' };
    if ( c.shippingAddressJson )
    {
      try
      {
        const addr = JSON.parse( c.shippingAddressJson );
        addrFields = {
          addressLine1: addr.address || c.addressLine1 || '',
          addressLine2: addr.landmark_area || c.addressLine2 || '',
          city: addr.city || c.city || '',
          state: addr.state || c.state || '',
          postalCode: addr.in_pin_code || c.postalCode || '',
          landmark: addr.landmark_area || c.landmark || '',
          houseNumber: addr.house_number || '',
          buildingName: addr.building_name || '',
        };
      } catch { /* use flat fields */ }
    }
    setEditCust( c );
    setCustForm( {
      name: c.name || '', phone: c.phone || '', email: c.email || '',
      shippingAddress: c.shippingAddress || '', billingAddress: c.billingAddress || '',
      addressLine1: addrFields.addressLine1 || c.addressLine1 || '',
      addressLine2: addrFields.addressLine2 || c.addressLine2 || '',
      city: addrFields.city || c.city || '',
      state: addrFields.state || c.state || '',
      postalCode: addrFields.postalCode || c.postalCode || '',
      landmark: addrFields.landmark || c.landmark || '',
      gstin: ( c as any ).gstin || '',
      houseNumber: addrFields.houseNumber || '',
      buildingName: addrFields.buildingName || '',
    } );
  };
  const closeEditCust = () => { setEditCust( null ); setCustForm( EMPTY_FORM ); };
  const saveCust = async () => {
    if ( !editCust ) return;
    setCustSaving( true );
    try
    {
      const saveData = {
        ...custForm,
        // Build structured address JSON for WhatsApp Payments
        shippingAddressJson: JSON.stringify( {
          name: custForm.name, phone_number: custForm.phone?.replace( '+', '' ) || '',
          address: custForm.addressLine1, city: custForm.city, state: custForm.state,
          in_pin_code: custForm.postalCode, house_number: custForm.houseNumber,
          building_name: custForm.buildingName, landmark_area: custForm.landmark,
        } ),
      };
      if ( editCust.id ) { await api.updateContact( editCust.id, saveData ); showMsg( 'Customer updated' ); }
      else { await api.createContact( saveData ); showMsg( 'Customer created' ); }
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
        purpose: invForm.purpose, orderId: invForm.orderId, gstin: config.gstin,
        preferredGateway: paymentGateway,
        paymentConfiguration: getPGConfigName( paymentGateway, sendPhone ),
      };
      const r = await api.createInvoiceEngine( req );
      if ( r ) { showMsg( `Invoice ${r.invoiceNumber} created \u2014 \u20B9${r.total}` ); setInvForm( { ...EMPTY_INV, items: [ NEW_ITEM() ] } ); setSelCustomer( null ); loadInvoices(); }
      else showMsg( 'Create failed', 'error' );
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
  const brandOptions: SelectOption[] = [
    BRAND_EMPTY_OPTION,
    ...config.purposes.map( p => ( { value: p, label: p } ) ),
  ];
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
    setEditForm( {
      customerName: inv.customerName || '',
      customerPhone: inv.customerPhone || '',
      customerEmail: inv.customerEmail || '',
      shipping: String( inv.shipping || 0 ),
      discount: String( inv.discount || 0 ),
      purpose: inv.purpose || '',
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
      const r = await api.updateInvoiceEngine( editModal.invoiceId, {
        customerName: editForm.customerName,
        customerPhone: editForm.customerPhone,
        customerEmail: editForm.customerEmail,
        shipping: parseFloat( editForm.shipping ) || 0,
        discount: parseFloat( editForm.discount ) || 0,
        purpose: editForm.purpose,
        orderId: editForm.orderId,
        notes: editForm.notes,
        shippingAddress: editForm.shippingAddress,
        billingAddress: editForm.billingAddress,
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
                    <div className="form-group"><label>Delivery Address</label><textarea value={ custForm.shippingAddress } onChange={ e => setCustForm( { ...custForm, shippingAddress: e.target.value, billingAddress: e.target.value } ) } placeholder="Full delivery address (used for billing too)" /></div>
                    <p style={ { fontSize: 12, fontWeight: 600, color: '#1a3a2a', margin: '8px 0 4px' } }>Structured Address (for WhatsApp Payments)</p>
                    <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 } }>
                      <div className="form-group"><label>House / Unit Number</label><input value={ custForm.houseNumber } onChange={ e => setCustForm( { ...custForm, houseNumber: e.target.value } ) } placeholder="e.g. 12" /></div>
                      <div className="form-group"><label>Building</label><input value={ custForm.buildingName } onChange={ e => setCustForm( { ...custForm, buildingName: e.target.value } ) } placeholder="e.g. One BKC" /></div>
                      <div className="form-group"><label>Street / Locality</label><input value={ custForm.addressLine1 } onChange={ e => setCustForm( { ...custForm, addressLine1: e.target.value } ) } placeholder="e.g. Bandra Kurla Complex" /></div>
                      <div className="form-group"><label>Landmark</label><input value={ custForm.landmark } onChange={ e => setCustForm( { ...custForm, landmark: e.target.value } ) } placeholder="e.g. Near BKC Circle" /></div>
                      <div className="form-group"><label>City</label><input value={ custForm.city } onChange={ e => setCustForm( { ...custForm, city: e.target.value } ) } placeholder="e.g. Mumbai" /></div>
                      <div className="form-group"><label>State</label><input value={ custForm.state } onChange={ e => setCustForm( { ...custForm, state: e.target.value } ) } placeholder="e.g. Maharashtra" /></div>
                      <div className="form-group"><label>Postal Code</label><input value={ custForm.postalCode } onChange={ e => setCustForm( { ...custForm, postalCode: e.target.value } ) } placeholder="6-digit code" maxLength={ 6 } /></div>
                    </div>
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
                    <div className="form-group"><label>Express / Shipping ({ '\u20B9' })</label><input type="number" value={ invForm.shipping } onChange={ e => setInvForm( { ...invForm, shipping: e.target.value } ) } /></div>
                    <div className="form-group"><label>Promo / Discount ({ '\u20B9' })</label><input type="number" value={ invForm.discount } onChange={ e => setInvForm( { ...invForm, discount: e.target.value } ) } /></div>

                  </div>
                  <div className="pf-form-grid">
                    <div className="form-group">
                      { /* The `.form-group` captions on this page are UNASSOCIATED labels - no
                           `for`, no wrapped control - so they were never a name source and these
                           controls had no accessible name at all. Each caption stays where it is
                           and the control takes `ariaLabel`, which adds a name where there was
                           none and changes nothing on screen. */ }
                      <label>Brand</label>
                      <Select ariaLabel="Brand" value={ invForm.purpose }
                        onChange={ v => setInvForm( { ...invForm, purpose: v } ) }
                        options={ brandOptions } />
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
                    <div className="pf-preview-row"><span>Promo</span><span>{ '\u2212' }{ fmtMoney( parseFloat( invForm.discount ) || 0 ) }</span></div>
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
                      <div className="pf-detail-row"><span className="label">Promo</span><span>{ '\u2212' }{ fmtMoney( selInvoice.discount ) }</span></div>
                      { selInvoice.convenienceFee > 0 && <div className="pf-detail-row"><span className="label">Conv Fee</span><span>{ fmtMoney( selInvoice.convenienceFee ) }</span></div> }
                      <div className="pf-detail-total"><span>Total</span><span>{ fmtMoney( selInvoice.total ) }</span></div>
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
              <div className="form-group"><label>Default Promo / Discount ({ '\u20B9' })</label><input type="number" value={ config.default_promo } onChange={ e => setConfig( { ...config, default_promo: parseFloat( e.target.value ) || 0 } ) } /></div>
              <div className="form-group"><label>GSTIN</label><input type="text" value={ config.gstin } onChange={ e => setConfig( { ...config, gstin: e.target.value } ) } /></div>
              <div className="form-group"><label>Default Item Name</label><input type="text" value={ config.default_item_name } onChange={ e => setConfig( { ...config, default_item_name: e.target.value } ) } /></div>
              <div className="form-group">
                <label>Brands (one per line)</label>
                <textarea rows={ 6 } value={ config.purposes.join( '\n' ) } onChange={ e => setConfig( { ...config, purposes: e.target.value.split( '\n' ).filter( Boolean ) } ) } />
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
                    <Select ariaLabel="Brand" value={ editForm.purpose }
                      onChange={ v => setEditForm( { ...editForm, purpose: v } ) }
                      options={ brandOptions } />
                  </div>
                  <div className="form-group"><label>Express / Shipping ({ '₹' })</label><input type="number" value={ editForm.shipping } onChange={ e => setEditForm( { ...editForm, shipping: e.target.value } ) } /></div>
                  <div className="form-group"><label>Promo / Discount ({ '₹' })</label><input type="number" value={ editForm.discount } onChange={ e => setEditForm( { ...editForm, discount: e.target.value } ) } /></div>
                  <div className="form-group"><label>Order ID</label><input type="text" value={ editForm.orderId } onChange={ e => setEditForm( { ...editForm, orderId: e.target.value } ) } /></div>
                  <div className="form-group"><label>Notes</label><textarea rows={ 2 } value={ editForm.notes } onChange={ e => setEditForm( { ...editForm, notes: e.target.value } ) } /></div>
                  <div className="form-group"><label>Delivery Address</label><textarea rows={ 2 } value={ editForm.shippingAddress } onChange={ e => setEditForm( { ...editForm, shippingAddress: e.target.value, billingAddress: e.target.value } ) } placeholder="Delivery address (used for billing too)" /></div>
                </div>
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
