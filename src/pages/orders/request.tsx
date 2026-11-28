import Head from 'next/head';
import Link from 'next/link';
import { useRouter } from 'next/router';
import React, { useEffect, useState } from 'react';
import PageMeta from '../../components/PageMeta';
import SubmitRequestJourney from '../../components/orders/SubmitRequestJourney';
import { clearSession, getSession, restoreSession } from '../../lib/customerAuth';
import { isOrderNumber } from '../../lib/paymentVocabulary';

/** Private customer-session task, not a public order-detail or payment link.
 * The fragment is only a selection hint. The checkout API owns the order check. */
export default function OrderRequestPage (): React.ReactElement {
  const router = useRouter();
  const [ selection, setSelection ] = useState<{ orderNumber: string; accessToken: string } | null>( null );
  const [ missing, setMissing ] = useState( false );
  useEffect( () => {
    let live = true;
    const open = async () => {
      const fields = new URLSearchParams( window.location.hash.slice( 1 ) );
      const number = String( fields.get( 'order' ) || '' ).toUpperCase();
      if ( !isOrderNumber( number ) ) { if ( live ) setMissing( true ); return; }
      let session = getSession();
      if ( !session ) {
        try { session = await restoreSession(); } catch { session = null; }
      }
      if ( !live ) return;
      if ( !session ) { window.location.replace( '/auth?return=/orders/' ); return; }
      setSelection( { orderNumber: number, accessToken: session.accessToken } );
    };
    const timer = window.setTimeout( () => { void open(); }, 0 );
    return () => { live = false; window.clearTimeout( timer ); };
  }, [] );
  const done = () => { void router.push( '/orders/' ); };
  const expire = () => { clearSession(); window.location.replace( '/auth?return=/orders/' ); };
  return <>
    <PageMeta title="Submit Request" description="Submit a request for an existing order." path="/orders/request/" />
    <Head><meta name="robots" content="noindex, nofollow" key="robots" /></Head>
    <main className="order-request-page" aria-label="Submit Request">
      <nav aria-label="Orders"><Link href="/orders/">My Orders</Link><span aria-hidden="true"> / </span><span>Submit Request</span></nav>
      { selection ? <SubmitRequestJourney key={ selection.orderNumber }
        orderNumber={ selection.orderNumber } accessToken={ selection.accessToken }
        onDone={ done } onExpired={ expire } />
        : <section className="request-loading" role="status">
          <h1>Submit Request</h1>
          <p>{ missing ? 'Choose an order from My Orders.' : 'Checking your session…' }</p>
          { missing && <Link href="/orders/">Back to orders</Link> }
        </section> }
      <style jsx>{`
        .order-request-page{width:100%;min-width:0;box-sizing:border-box;padding:calc(120px + var(--safe-top,0px)) 16px max(32px,env(safe-area-inset-bottom));color:var(--public-text);background:var(--public-bg)}
        nav{max-width:440px;margin:0 auto 16px;display:flex;flex-wrap:wrap;align-items:center;gap:8px;font:600 14px/1.5 var(--font-sans);color:var(--public-brand-green)}
        .request-loading{width:min(100%,440px);margin:0 auto;border:1px solid var(--public-hairline);border-radius:var(--public-card-radius);padding:24px;box-sizing:border-box}
        .request-loading h1{font-size:26px;margin:0 0 12px}
        @media(min-width:768px){.order-request-page{padding-top:calc(156px + var(--safe-top,0px))}}
      `}</style>
    </main>
  </>;
}
