/**
 * Commerce — [retired public path]/commerce
 * Admin UI for WhatsApp native commerce: send the catalog, compose & send a
 * native order_details (Review & Pay) bill, view orders/payments, and see the
 * live Razorpay payment configs per WABA. Backed by:
 *   POST /whatsapp/send            (catalog_message / isInteractivePayment order_details)
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

const WABAS = [
    { label: 'WABA1 · +91 93309 94400', phoneId: 'phone-number-id-waba1-direct-1016149501586345', catalog: 'wecare_catalog', catalogId: '1607047307067517', payConfig: 'Razorpay_wecare.digital' },
    { label: 'WABA2 · +91 99033 00044', phoneId: 'phone-number-id-waba-t-direct-1055232054343117', catalog: 'Catalogue_Products', catalogId: '1424934879646296', payConfig: 'WECAREDIGITAL' },
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
    const [ products, setProducts ] = useState<any[]>( [] );
    const [ productSearch, setProductSearch ] = useState( '' );
    const [ feeds, setFeeds ] = useState<any[]>( [] );
    const [ feedUrl, setFeedUrl ] = useState( '' );
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
        // Backend (/whatsapp/send isInteractivePayment) reads orderDetails.order.items[]
        // where each item = { name, amount:{value(paise),offset:100}, quantity, gstRate, retailer_id }.
        // Backend auto-adds 18% GST (per item gstRate) + 2.2% convenience fee and computes totals.
        const li = items
            .filter( i => i.name.trim() && Number( i.amount ) > 0 )
            .map( ( i, idx ) => ( {
                retailer_id: `ADMIN_${idx + 1}`,
                name: i.name.trim(),
                amount: { value: Math.round( Number( i.amount ) * 100 ), offset: 100 },
                quantity: Math.max( 1, Number( i.quantity ) || 1 ),
                gstRate: 18,
            } ) );
        if ( !digits( toPhone ) ) { toast.error( 'Enter a customer phone' ); return; }
        if ( !li.length ) { toast.error( 'Add at least one line item with amount' ); return; }
        const subtotal = li.reduce( ( s, i ) => s + ( i.amount.value / 100 ) * i.quantity, 0 );
        setBusy( 'bill' );
        try
        {
            const r = await call( '/whatsapp/send', 'POST', {
                recipientPhone: digits( toPhone ), phoneNumberId: phoneId,
                isInteractivePayment: true,
                orderDetails: {
                    type: goodsType,
                    currency: 'INR',
                    gstin: '19AAFFW7196L1Z8',
                    reference_id: `ADMINBILL-${Date.now()}`,
                    order: { items: li },
                },
            } );
            if ( r ) toast.success( `Bill sent (subtotal ₹${subtotal.toFixed( 2 )} + 18% GST + 2% convenience)` );
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

    const loadProducts = useCallback( async () => {
        const waba = WABAS.find( w => w.phoneId === phoneId ) || WABAS[ 0 ];
        const qs = `?catalogId=${encodeURIComponent( waba.catalogId )}${productSearch.trim() ? `&search=${encodeURIComponent( productSearch.trim() )}` : ''}`;
        const r = await call( `/wa-business/catalog-products${qs}` );
        setProducts( Array.isArray( r?.products ) ? r.products : [] );
    }, [ phoneId, productSearch ] );

    const loadFeeds = useCallback( async () => {
        const waba = WABAS.find( w => w.phoneId === phoneId ) || WABAS[ 0 ];
        const r = await call( `/wa-business/catalog-feed?catalogId=${encodeURIComponent( waba.catalogId )}` );
        const list = Array.isArray( r?.feeds ) ? r.feeds : [];
        setFeeds( list );
        setFeedUrl( list[ 0 ]?.url || '' );
    }, [ phoneId ] );

    const saveFeed = async () => {
        if ( !feedUrl.trim().startsWith( 'https://' ) ) { toast.error( 'Enter a valid https feed URL' ); return; }
        const waba = WABAS.find( w => w.phoneId === phoneId ) || WABAS[ 0 ];
        setBusy( 'feed' );
        try
        {
            const r = await call( '/wa-business/catalog-feed', 'POST', {
                catalogId: waba.catalogId, url: feedUrl.trim(), name: 'WECARE Wix Feed', interval: 'DAILY', hour: 4,
            } );
            if ( r?.success ) { toast.success( `Feed ${r.action} (daily auto-sync)` ); loadFeeds(); }
            else toast.error( 'Feed save failed' );
        } finally { setBusy( '' ); }
    };

    const syncFeedNow = async ( feedId: string ) => {
        setBusy( 'feedsync' );
        try
        {
            const r = await call( '/wa-business/catalog-feed/fetch', 'POST', { feedId } );
            if ( r?.success ) toast.success( 'Sync started — products refresh shortly' );
            else toast.error( 'Sync failed' );
        } finally { setBusy( '' ); }
    };

    const loadPostpay = useCallback( async () => {
        const reg = await call( '/wa-business/flow-registry?flowCode=02.WD_POSTPAY' );
        const flows = Array.isArray( reg?.flows ) ? reg.flows : [];
        setPostpayFlow( flows[ 0 ] || null );
        const subs = await call( '/wa-business/flow-submissions?flowCode=02.WD_POSTPAY&limit=25' );
        setPostpaySubs( Array.isArray( subs?.flows ) ? subs.flows : ( Array.isArray( subs?.submissions ) ? subs.submissions : [] ) );
    }, [] );

    useEffect( () => { loadOrders(); loadPayments(); }, [ loadOrders, loadPayments ] );
    useEffect( () => { loadProducts(); loadFeeds(); loadPostpay(); }, [ loadProducts, loadFeeds, loadPostpay ] );

    const addProductToBill = ( p: any ) => {
        // price like "100.00 INR" or "₹100.00"; extract the numeric rupee value
        const num = ( String( p.price || '' ).match( /[\d.]+/ ) || [ '' ] )[ 0 ];
        const first = items[ 0 ];
        const empty = items.length === 1 && !first.name.trim() && !first.amount;
        const next = { name: p.name || p.retailerId, amount: num, quantity: '1' };
        setItems( empty ? [ next ] : [ ...items, next ] );
        toast.success( `Added "${next.name}" to bill` );
    };

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
                        <Button variant="secondary" onClick={ loadProducts }>Refresh</Button>
                    </div>
                    <div style={ { display: 'flex', gap: 6, marginBottom: 10 } }>
                        <input value={ productSearch } onChange={ e => setProductSearch( e.target.value ) } placeholder="Search products…" style={ { flex: 1 } } />
                    </div>
                    { products.length === 0 ? <p style={ muted }>No products found in this catalog.</p> : (
                        <ul style={ list }>
                            { products.slice( 0, 50 ).map( ( p: any, i: number ) => (
                                <li key={ p.retailerId || i } style={ row }>
                                    <span style={ { fontSize: 13, display: 'flex', alignItems: 'center', gap: 8 } }>
                                        { p.imageUrl && <img src={ p.imageUrl } alt="" style={ { width: 32, height: 32, objectFit: 'cover', borderRadius: 4 } } /> }
                                        <span>{ p.name || p.retailerId } · { p.price || '—' }{ p.availability ? ` · ${p.availability}` : '' }</span>
                                    </span>
                                    <span style={ { display: 'flex', gap: 4 } }>
                                        <button onClick={ () => addProductToBill( p ) } style={ pill }>+ Bill</button>
                                    </span>
                                </li>
                            ) ) }
                        </ul>
                    ) }
                </div>

                <div style={ card }>
                    <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 } }>
                        <h2 style={ h2 }>Catalog data feed (Wix → Meta auto-sync)</h2>
                        <Button variant="secondary" onClick={ loadFeeds }>Refresh</Button>
                    </div>
                    <p style={ { fontSize: 12, color: 'var(--text-muted)', margin: '0 0 8px' } }>
                        Paste the Wix Facebook-channel feed URL. Meta fetches it daily and keeps <b>{ activeWaba.catalog }</b> in sync — product name, price and availability changes flow through automatically. The URL holds a secret token; treat it like a password.
                    </p>
                    <input value={ feedUrl } onChange={ e => setFeedUrl( e.target.value ) } placeholder="https://manage.wix.com/catalog-feed/v2/feed.tsv?channel=facebook&..." style={ { width: '100%' } } />
                    <div style={ { display: 'flex', gap: 8, marginTop: 8, alignItems: 'center' } }>
                        <Button onClick={ saveFeed } disabled={ busy !== '' }>{ busy === 'feed' ? 'Saving…' : 'Save feed (daily)' }</Button>
                        { feeds[ 0 ]?.feedId && <Button variant="secondary" onClick={ () => syncFeedNow( feeds[ 0 ].feedId ) } disabled={ busy !== '' }>{ busy === 'feedsync' ? 'Syncing…' : 'Sync now' }</Button> }
                    </div>
                    { feeds.length > 0 && (
                        <p style={ { fontSize: 12, color: 'var(--text-muted)', margin: '8px 0 0' } }>
                            Feed: <b>{ feeds[ 0 ].name }</b> · { feeds[ 0 ].interval }{ feeds[ 0 ].lastUploadEnd ? ` · last sync ${feeds[ 0 ].lastUploadEnd}` : '' }{ feeds[ 0 ].lastItems !== '' ? ` · ${feeds[ 0 ].lastItems} items` : '' }
                        </p>
                    ) }
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
