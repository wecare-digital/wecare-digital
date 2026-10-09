/**
 * Commerce — [retired public path]/commerce
 * Admin UI for WhatsApp native commerce: send the catalog, compose & send a
 * native order_details (Review & Pay) bill, view orders/payments, and see the
 * live Razorpay payment configs per WABA. Backed by:
 *   POST /whatsapp/send            (catalog_message only)
 *   POST /invoices + /invoices/{id}/send-payment-link (payment requests)
 *   GET  /wa-business/orders       + PATCH /wa-business/orders/{id}
 *   GET  /payments                 (recent payments)
 */
import React, { useState, useEffect, useCallback } from 'react';
import Layout from '../../../../components/Layout';
import SEO from '../../../../components/SEO';
import Button from '../../../../components/ui/Button';
import { useToastContext } from '../../../../contexts/ToastContext';
import Select, { type SelectOption } from '../../../../components/ui/Select';
import { fetchAuthSession } from 'aws-amplify/auth';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api';

/**
 * Named exactly, because the old behaviour named it wrongly.
 *
 * Product listing and feed sync used to be interactive here, against
 * /wa-business/catalog-products and /wa-business/catalog-feed. Neither has a live
 * route. The `call` helper below returns the parsed 404 BODY rather than throwing,
 * so the failure was invisible in three different ways: the product list silently
 * set to empty and rendered "No products found in this catalog", which reads as an
 * empty catalog; the feed list silently set to empty; and Save-feed reported "Feed
 * save failed", blaming the save for a route that was never there.
 *
 * Both panels stay, with their headings and copy, because the capability is real on
 * Meta's side and someone has to be told why it is not wired here. A missing
 * capability stated once is cheaper than a control that quietly does nothing.
 */
const CATALOG_SYNC_UNAVAILABLE = 'Meta catalog product listing and feed sync are not available on this deployment: /wa-business/catalog-products and /wa-business/catalog-feed have no live route.';

const WABAS = [
    { label: 'WABA1 · +91 93309 94400', phoneId: 'phone-number-id-waba1-direct-1016149501586345', catalog: 'wecare_shop', catalogId: '1457045652952851', payConfig: 'Razorpay_wecare.digital' },
    { label: 'WABA2 · +91 99033 00044', phoneId: 'phone-number-id-waba-t-direct-1055232054343117', catalog: 'wecare_shop', catalogId: '1457045652952851', payConfig: 'WECAREDIGITAL' },
];

/* Hoisted option rows. Same order, same values, same visible text as the <option>s they
   replaced. The business-number list is derived from WABAS so the two cannot drift. */
const PHONE_ID_OPTIONS: SelectOption[] = WABAS.map(
    w => ( { value: w.phoneId, label: w.label } )
);
const GOODS_TYPE_OPTIONS: SelectOption[] = [
    { value: 'physical-goods', label: 'Physical goods (collect address)' },
    { value: 'digital-goods', label: 'Digital goods' },
];

/* LAYOUT ONLY - what the inline `width: '100%'` carried; the box is the trigger's. The goods
   chooser is a flex child beside a caption, and a native select sized itself to its widest
   option while the trigger shows the selected one. */
const FULL_WIDTH: React.CSSProperties = { width: '100%' };
const GOODS_SELECT_STYLE: React.CSSProperties = { flex: '0 1 300px' };

interface LineItem { name: string; amount: string; quantity: string; }

const CommercePage: React.FC<PageProps> = ( { signOut, user, embedded = false } ) => {
    const toast = useToastContext();
    const [ phoneId, setPhoneId ] = useState( WABAS[ 0 ].phoneId );
    const [ toPhone, setToPhone ] = useState( '' );
    const [ busy, setBusy ] = useState( '' );
    const [ items, setItems ] = useState<LineItem[]>( [ { name: '', amount: '', quantity: '1' } ] );
    const [ goodsType, setGoodsType ] = useState<'physical-goods' | 'digital-goods'>( 'physical-goods' );
    const [ orders, setOrders ] = useState<any[]>( [] );
    const [ payments, setPayments ] = useState<any[]>( [] );
    // `products`, `productSearch`, `feeds` and `feedUrl` were declared here. All four
    // existed only to hold the result of a call with no route — see
    // CATALOG_SYNC_UNAVAILABLE above.
    const [ postpayFlow, setPostpayFlow ] = useState<any>( null );
    const [ postpaySubs, setPostpaySubs ] = useState<any[]>( [] );

    const call = async ( path: string, method = 'GET', body?: any ) => {
        let token: string | null = null;
        try { token = ( await fetchAuthSession() ).tokens?.accessToken?.toString() ?? null; } catch { token = null; }
        const res = await fetch( `${API_BASE}${path}`, {
            method,
            headers: { 'Content-Type': 'application/json', ...( token ? { Authorization: `Bearer ${token}` } : {} ) },
            body: body ? JSON.stringify( body ) : undefined,
        } );
        if ( res.status === 401 || res.status === 403 ) { toast.error( 'Not authorized — sign in again' ); return null; }
        try { return await res.json(); } catch { return null; }
    };

    const digits = ( p: string ) => p.replace( /\D/g, '' );

    const sendCatalog = async () => {
        if ( !digits( toPhone ) ) { toast.error( 'Enter a customer phone' ); return; }
        setBusy( 'catalog' );
        try
        {
            const r = await call( '/whatsapp/send', 'POST', {
                recipientPhone: digits( toPhone ), phoneNumberId: phoneId,
                isInteractive: true, interactiveType: 'catalog_message',
                interactiveData: { body: 'Browse our catalog and add items to your cart.', footer: 'WECARE.DIGITAL' },
            } );
            if ( r ) toast.success( 'Catalog sent' ); else toast.error( 'Send failed' );
        } finally { setBusy( '' ); }
    };

    const sendBill = async () => {
        const li = items
            .filter( i => i.name.trim() && Number( i.amount ) > 0 )
            .map( i => ( {
                name: i.name.trim(),
                amount: Number( i.amount ),
                quantity: Math.max( 1, Number( i.quantity ) || 1 ),
                gstRate: 18,
            } ) );
        if ( !digits( toPhone ) ) { toast.error( 'Enter a customer phone' ); return; }
        if ( !li.length ) { toast.error( 'Add at least one line item with amount' ); return; }
        setBusy( 'bill' );
        try
        {
            // A payment request must first become a server-owned invoice. The invoice engine
            // mints/reserves the reference and constructs the approved order_details template.
            const invoice = await call( '/invoices', 'POST', {
                customerPhone: `+${digits( toPhone )}`,
                customerEmail: '',
                shippingAddress: '',
                billingAddress: '',
                goodsType,
                items: li,
                currency: 'INR',
                gstin: '19AAFFW7196L1Z8',
                entryPoint: 'workspace_commerce',
            } );
            if ( !invoice?.invoiceId ) { toast.error( 'Invoice creation failed' ); return; }

            const sent = await call(
                `/invoices/${encodeURIComponent( invoice.invoiceId )}/send-payment-link`,
                'POST',
                { invoiceId: invoice.invoiceId, phoneNumberId: phoneId },
            );
            if ( sent ) toast.success( 'Bill sent securely through the invoice payment flow' );
            else toast.error( 'Send failed' );
        } finally { setBusy( '' ); }
    };

    const loadOrders = useCallback( async () => {
        const r = await call( '/wa-business/orders' );
        setOrders( Array.isArray( r?.orders ) ? r.orders : ( Array.isArray( r ) ? r : ( r?.data || [] ) ) );
    }, [] );
    const loadPayments = useCallback( async () => {
        const r = await call( '/payments' );
        setPayments( Array.isArray( r?.payments ) ? r.payments : ( Array.isArray( r ) ? r : ( r?.data || [] ) ) );
    }, [] );

    // `loadProducts`, `loadFeeds`, `saveFeed` and `syncFeedNow` were here — the four
    // call sites against /wa-business/catalog-products and /wa-business/catalog-feed.
    // Removed rather than left to fail, because the `call` helper swallows the 404 and
    // the UI reported it as empty data or as a failed save. See
    // CATALOG_SYNC_UNAVAILABLE at the top of this file.

    const loadPostpay = useCallback( async () => {
        const reg = await call( '/wa-business/flow-registry?flowCode=02.WD_POSTPAY' );
        const flows = Array.isArray( reg?.flows ) ? reg.flows : [];
        setPostpayFlow( flows[ 0 ] || null );
        const subs = await call( '/wa-business/flow-submissions?flowCode=02.WD_POSTPAY&limit=25' );
        setPostpaySubs( Array.isArray( subs?.flows ) ? subs.flows : ( Array.isArray( subs?.submissions ) ? subs.submissions : [] ) );
    }, [] );

    useEffect( () => { loadOrders(); loadPayments(); }, [ loadOrders, loadPayments ] );
    // Was `loadProducts(); loadFeeds(); loadPostpay();`. Two of those three fired on
    // every mount against a route that does not exist, so the page opened with two
    // guaranteed 404s. Only the postpay load remains, and it is live.
    useEffect( () => { loadPostpay(); }, [ loadPostpay ] );

    // `addProductToBill` was here. It took a product out of the list the dead call
    // populated, so it could never be reached. The bill composer's manual line-item
    // entry below is unaffected and stays fully working.

    const setItem = ( idx: number, k: keyof LineItem, v: string ) =>
        setItems( items.map( ( it, i ) => ( i === idx ? { ...it, [ k ]: v } : it ) ) );
    const addItem = () => setItems( [ ...items, { name: '', amount: '', quantity: '1' } ] );
    const delItem = ( idx: number ) => setItems( items.filter( ( _, i ) => i !== idx ) );

    const patchOrderStatus = async ( orderId: string, status: string ) => {
        const r = await call( `/wa-business/orders/${orderId}`, 'PATCH', { status } );
        if ( r ) { toast.success( `Order → ${status}` ); loadOrders(); } else toast.error( 'Update failed' );
    };

    const activeWaba = WABAS.find( w => w.phoneId === phoneId ) || WABAS[ 0 ];

    const body = (
        <>
            <SEO title="Commerce" description="WhatsApp catalog, orders & native payments" />
            <div style={ { padding: embedded ? 0 : 'var(--space-6)', maxWidth: 900 } }>
                <h1 style={ { fontSize: 'var(--h2)', fontWeight: 700, margin: '0 0 var(--space-4)', color: 'var(--text)' } }>Commerce</h1>

                <div style={ card }>
                    { /* The `lbl` caption is an UNASSOCIATED <label> - no `for`, no wrapped
                         control - so it was never a name source. It stays, keeping its own type
                         and spacing, and the control takes `ariaLabel`. */ }
                    <label style={ lbl }>Business number</label>
                    <Select ariaLabel="Business number" value={ phoneId }
                        onChange={ v => setPhoneId( v ) }
                        options={ PHONE_ID_OPTIONS } style={ FULL_WIDTH } />
                    <p style={ { fontSize: 12, color: 'var(--text-muted)', margin: '8px 0 0' } }>
                        Catalog: <b>{ activeWaba.catalog }</b> · Payments: <b>{ activeWaba.payConfig }</b> (Razorpay)
                    </p>
                    <label style={ { ...lbl, marginTop: 12 } }>Customer phone (E.164 digits)</label>
                    <input value={ toPhone } onChange={ e => setToPhone( e.target.value ) } placeholder="918100640044" style={ { width: '100%' } } />
                    <div style={ { marginTop: 12 } }>
                        <Button onClick={ sendCatalog } disabled={ busy !== '' }>{ busy === 'catalog' ? 'Sending…' : 'Send catalog' }</Button>
                    </div>
                </div>

                <div style={ card }>
                    <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 } }>
                        <h2 style={ h2 }>Catalog — { activeWaba.catalog }</h2>
                    </div>
                    { /* The Refresh button, the product search input and the product list
                         (each row with a "+ Bill" action) were here. All of them drove
                         /wa-business/catalog-products, which has no live route, so the
                         list was permanently empty and read as an empty catalog. */ }
                    <p style={ muted }>{ CATALOG_SYNC_UNAVAILABLE }</p>
                </div>

                <div style={ card }>
                    <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 } }>
                        <h2 style={ h2 }>Catalog data feed (Wix → Meta auto-sync)</h2>
                    </div>
                    <p style={ { fontSize: 12, color: 'var(--text-muted)', margin: '0 0 8px' } }>
                        The intended arrangement: paste the Wix Facebook-channel feed URL, and Meta fetches it daily to keep <b>{ activeWaba.catalog }</b> in sync — product name, price and availability changes flowing through automatically. The URL holds a secret token; treat it like a password.
                    </p>
                    { /* The feed URL input, Save-feed and Sync-now were here. They drove
                         /wa-business/catalog-feed and /wa-business/catalog-feed/fetch,
                         neither of which has a live route, and the save reported "Feed save
                         failed" — which blamed the save rather than the missing route. */ }
                    <p style={ muted }>{ CATALOG_SYNC_UNAVAILABLE }</p>
                </div>

                <div style={ card }>
                    <h2 style={ h2 }>Compose a bill (native Review &amp; Pay)</h2>
                    <div style={ { display: 'flex', gap: 8, alignItems: 'center', marginBottom: 10 } }>
                        <label style={ { fontSize: 13, color: 'var(--text-secondary)' } }>Goods:</label>
                        <Select ariaLabel="Goods type" value={ goodsType }
                            onChange={ v => setGoodsType( v as any ) }
                            options={ GOODS_TYPE_OPTIONS } style={ GOODS_SELECT_STYLE } />
                    </div>
                    { items.map( ( it, idx ) => (
                        <div key={ idx } style={ { display: 'flex', gap: 6, marginBottom: 6 } }>
                            <input value={ it.name } onChange={ e => setItem( idx, 'name', e.target.value ) } placeholder="Item name" style={ { flex: 3 } } />
                            <input value={ it.amount } onChange={ e => setItem( idx, 'amount', e.target.value ) } placeholder="₹ price" style={ { flex: 1 } } type="number" />
                            <input value={ it.quantity } onChange={ e => setItem( idx, 'quantity', e.target.value ) } placeholder="Qty" style={ { width: 60 } } type="number" />
                            { items.length > 1 && <button onClick={ () => delItem( idx ) } style={ delBtn }>✕</button> }
                        </div>
                    ) ) }
                    <div style={ { display: 'flex', gap: 8, marginTop: 8 } }>
                        <Button variant="secondary" onClick={ addItem } disabled={ busy !== '' }>+ Item</Button>
                        <Button onClick={ sendBill } disabled={ busy !== '' }>{ busy === 'bill' ? 'Sending…' : 'Send bill (Review & Pay)' }</Button>
                    </div>
                    <p style={ { fontSize: 12, color: 'var(--text-muted)', margin: '8px 0 0' } }>18% GST + 2.2% convenience fee are added automatically; a GST invoice is generated on payment.</p>
                </div>

                <div style={ card }>
                    <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 } }>
                        <h2 style={ h2 }>Post-payment flow</h2>
                        <Button variant="secondary" onClick={ loadPostpay }>Refresh</Button>
                    </div>
                    <p style={ { fontSize: 12, color: 'var(--text-muted)', margin: '0 0 8px' } }>
                        After a payment is captured, the customer gets a WhatsApp Flow (data_exchange) that shows the real Order # and Payment ID and collects order details. One flow per payment (idempotent).
                    </p>
                    { postpayFlow ? (
                        <p style={ { fontSize: 13, margin: '0 0 8px' } }>
                            Flow: <b>{ postpayFlow.flowName || postpayFlow.flowCode }</b> · { postpayFlow.status } · id { postpayFlow.flowId }
                        </p>
                    ) : <p style={ muted }>No post-payment flow registered.</p> }
                    { postpaySubs.length === 0 ? <p style={ muted }>No post-payment submissions yet.</p> : (
                        <ul style={ list }>
                            { postpaySubs.slice( 0, 15 ).map( ( s: any, i: number ) => (
                                <li key={ s.submissionId || i } style={ row }>
                                    <span style={ { fontSize: 13 } }>{ s.referenceId || s.orderId || s.submissionNumber } · { s.phone } · <b>{ s.paymentStatus || s.status }</b></span>
                                    <span style={ { fontSize: 12, color: 'var(--text-muted)' } }>{ s.createdAt ? new Date( Number( s.createdAt ) * 1000 ).toLocaleDateString() : '' }</span>
                                </li>
                            ) ) }
                        </ul>
                    ) }
                </div>

                <div style={ card }>
                    <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 } }>
                        <h2 style={ h2 }>Orders</h2>
                        <Button variant="secondary" onClick={ loadOrders }>Refresh</Button>
                    </div>
                    { orders.length === 0 ? <p style={ muted }>No orders yet.</p> : (
                        <ul style={ list }>
                            { orders.slice( 0, 25 ).map( ( o: any, i: number ) => (
                                <li key={ o.orderId || o.id || i } style={ row }>
                                    <span style={ { fontSize: 13 } }>{ o.orderId || o.referenceId || o.id }{ o.customerName ? ` · ${o.customerName}` : '' } · ₹{ o.total ?? o.amount ?? '—' } · <b>{ o.orderStatus || o.status || 'pending' }</b></span>
                                    <span style={ { display: 'flex', gap: 4 } }>
                                        { [ 'processing', 'shipped', 'completed', 'canceled' ].map( s => (
                                            <button key={ s } onClick={ () => patchOrderStatus( o.orderId || o.id, s ) } style={ pill }>{ s }</button>
                                        ) ) }
                                    </span>
                                </li>
                            ) ) }
                        </ul>
                    ) }
                </div>

                <div style={ card }>
                    <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 } }>
                        <h2 style={ h2 }>Recent payments</h2>
                        <Button variant="secondary" onClick={ loadPayments }>Refresh</Button>
                    </div>
                    { payments.length === 0 ? <p style={ muted }>No payments yet.</p> : (
                        <ul style={ list }>
                            { payments.slice( 0, 25 ).map( ( p: any, i: number ) => (
                                <li key={ p.id || p.paymentId || p.referenceId || i } style={ row }>
                                    { /* amountRupees is a string derived from integer paise by the
                                         API; amountInRupees is the legacy numeric field. `amount`
                                         is paise, so it is deliberately NOT a fallback here - it
                                         would render a 2500 rupee payment as 250000. */ }
                                    <span style={ { fontSize: 13 } }>{ p.referenceId || p.paymentId || p.id } · ₹{ p.amountRupees ?? p.amountInRupees ?? '—' } · <b>{ p.status || '—' }</b></span>
                                    <span style={ { fontSize: 12, color: 'var(--text-muted)' } }>{ p.method || p.source || 'razorpay' }</span>
                                </li>
                            ) ) }
                        </ul>
                    ) }
                </div>
            </div>
        </>
    );

    return embedded ? body : <Layout user={ user } onSignOut={ signOut }>{ body }</Layout>;
};

const card: React.CSSProperties = { background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)', padding: 'var(--space-4)', marginBottom: 'var(--space-4)', boxShadow: 'var(--shadow-sm)' };
const h2: React.CSSProperties = { fontSize: 'var(--h4)', fontWeight: 600, margin: 0, color: 'var(--text)' };
const lbl: React.CSSProperties = { display: 'block', fontSize: 13, color: 'var(--text-secondary)', marginBottom: 6 };
const muted: React.CSSProperties = { color: 'var(--text-muted)', fontSize: 13 };
const list: React.CSSProperties = { listStyle: 'none', padding: 0, margin: 0 };
const row: React.CSSProperties = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, padding: '6px 0', borderBottom: '1px solid var(--border)' };
const pill: React.CSSProperties = { fontSize: 11, padding: '2px 6px', border: '1px solid var(--border)', borderRadius: 999, background: '#fff', cursor: 'pointer' };
const delBtn: React.CSSProperties = { border: 'none', background: 'none', color: 'var(--danger, #dc2626)', cursor: 'pointer', fontSize: 14 };

export default CommercePage;
