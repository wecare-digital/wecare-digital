import React, { useEffect, useRef, useState } from 'react';

import PillButton from '../PillButton';
import { formatPaiseINR } from '../../lib/money';
import { stashPendingOrder } from '../../lib/orderPage';
import {
  FULFILMENT_STATUS_LABEL, PAYMENT_STATUS_LABEL, PAYMENT_STATUS_NOTE,
} from '../../lib/orderStatusLabels';

/**
 * The order page body: one of the signed-in customer's own orders, at /orders/?o=<orderNumber>.
 *
 * This is where both purchase channels end. A website purchase arrives here from
 * /checkout/status/ once the payment is confirmed; a WhatsApp catalog purchase arrives from the
 * "View your order" button sent after the paid invoice. Either way it shows what was bought,
 * where it ships, what was paid and the order's current status. A WhatsApp-paid order has no
 * fulfilment status to show (the server sends none: its row holds the payment-order state).
 *
 * ONE AUTHENTICATED READ. `POST /ecommerce/checkout/status` with `{action:'order', orderNumber}`
 * (checkout `_order_detail`). The server answers only for an order the session owns and returns
 * the identical 404 for an order that does not exist and for someone else's, so this screen says
 * "not found on this account" and never "not yours".
 *
 * NOTHING HERE IS COMPUTED. Every amount is integer paise from the server, rendered by
 * `formatPaiseINR`; the breakdown is shown only when the server has proved it closes to the
 * amount paid, otherwise the total stands alone. The delivery address is the one frozen on the
 * order when it was paid, not the profile's current address, which may have changed since.
 *
 * Rendered entirely inside this one return tree because styled-jsx scopes only the JSX it
 * compiles alongside its styles (see the note at the foot of OrdersPage).
 */

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api';
/** The checkout function's read route; `action:'order'` selects the order read. */
const ORDER_URL = `${ API_BASE }/ecommerce/checkout/status`;

interface OrderItem {
  name: string;
  quantity: number;
  unitPricePaise: number;
  totalPaise: number;
}

interface OrderCharges {
  merchandisePaise: number;
  deliveryPaise: number;
  discountPaise: number;
  convenienceFeePaise: number;
  convenienceGstPaise: number;
  totalPaise: number;
  /** The one display name for the always-on discount, from the server. */
  discountLabel?: string;
}

interface DeliveryAddress {
  addressLine1?: string;
  addressLine2?: string;
  locality?: string;
  city?: string;
  state?: string;
  postalCode?: string;
  country?: string;
}

interface OrderView {
  orderNumber: string;
  referenceId: string;
  /** INT epoch SECONDS, UTC; formatted here so an IST reader sees their own day. */
  createdAt: number | null;
  /** 'website' | 'whatsapp', canonicalised server-side. */
  channel: string;
  currency: string;
  amountPaise: number | null;
  /** The canonical payment word ('captured', 'refunded', ...). */
  paymentStatus: string;
  /** Meta's order_status word ('processing', 'shipped', ...), or '' when unknown. */
  fulfilmentStatus: string;
  items: OrderItem[];
  charges: OrderCharges | null;
  delivery: { recipient: string; address: DeliveryAddress } | null;
  invoiceNumber: string;
  customerDisplayId: string;
}

type Load =
  | { kind: 'loading' }
  | { kind: 'ready'; order: OrderView }
  | { kind: 'notFound' }
  | { kind: 'unavailable' };

type Outcome = Exclude<Load, { kind: 'loading' }> | { kind: 'expired' };

async function fetchOrder ( token: string, orderNumber: string ): Promise<Outcome> {
  try
  {
    const response = await fetch( ORDER_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
        Authorization: `Bearer ${ token }`,
      },
      body: JSON.stringify( { action: 'order', orderNumber } ),
    } );
    // A 401 is the normal end of an hour-long token. The page returns to its sign-in state.
    if ( response.status === 401 ) return { kind: 'expired' };
    // 404 is "no such order on this account" (the server does not distinguish someone else's);
    // 400 is a number the server would not even look up. Neither is cleared by retrying.
    if ( response.status === 404 || response.status === 400 ) return { kind: 'notFound' };
    if ( !response.ok ) return { kind: 'unavailable' };
    const data = ( await response.json() ) as { status?: string; order?: OrderView };
    if ( data.status !== 'ORDER_READY' || !data.order || data.order.orderNumber !== orderNumber )
    {
      return { kind: 'unavailable' };
    }
    return { kind: 'ready', order: data.order };
  }
  catch
  {
    return { kind: 'unavailable' };
  }
}

/** Date and time of the order, or '' for an unreadable value (never "Invalid Date"). */
function placedLabel ( createdAt: number | null ): string {
  if ( createdAt === null || !Number.isFinite( createdAt ) || createdAt <= 0 ) return '';
  return new Date( createdAt * 1000 ).toLocaleString( 'en-IN', {
    day: 'numeric', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit',
  } );
}

/** The address as label lines, dropping empty parts rather than leaving `, ,` gaps. */
function addressLines ( address: DeliveryAddress | undefined ): string[] {
  if ( !address ) return [];
  const cityLine = [ address.city, address.state ].map( part => String( part || '' ).trim() )
    .filter( Boolean ).join( ', ' );
  const postLine = [ cityLine, String( address.postalCode || '' ).trim() ].filter( Boolean ).join( ' ' );
  return [ address.addressLine1, address.addressLine2, address.locality, postLine, address.country ]
    .map( part => String( part || '' ).trim() )
    .filter( Boolean );
}

interface OrderDetailProps {
  accessToken: string;
  orderNumber: string;
  /** Called when the session has expired; the page drops back to its sign-in state. */
  onExpired: () => void;
}

export default function OrderDetail (
  { accessToken, orderNumber, onExpired }: OrderDetailProps,
): React.ReactElement {
  const [ load, setLoad ] = useState<Load>( { kind: 'loading' } );
  const [ attempt, setAttempt ] = useState( 0 );

  // The parent's expiry handler is a fresh function on every render. Read through a ref so the
  // fetch effect depends only on what it actually fetches and never re-runs on a parent render.
  const expiredRef = useRef( onExpired );
  useEffect( () => { expiredRef.current = onExpired; }, [ onExpired ] );

  useEffect( () => {
    let live = true;
    ( async () => {
      const outcome = await fetchOrder( accessToken, orderNumber );
      if ( !live ) return;
      if ( outcome.kind === 'expired' )
      {
        // The order survives the sign-in the customer is about to do.
        stashPendingOrder( orderNumber );
        expiredRef.current();
        return;
      }
      setLoad( outcome );
    } )();
    return () => { live = false; };
  }, [ accessToken, orderNumber, attempt ] );

  const retry = () => {
    setLoad( { kind: 'loading' } );
    setAttempt( count => count + 1 );
  };

  const order = load.kind === 'ready' ? load.order : null;
  const amount = order ? formatPaiseINR( order.amountPaise, order.currency ) : '';
  const paid = order?.paymentStatus === 'captured';
  const paymentLabel = order
    ? ( PAYMENT_STATUS_LABEL[ order.paymentStatus ] || 'Payment status unavailable' ) : '';
  const paymentNote = order ? ( PAYMENT_STATUS_NOTE[ order.paymentStatus ] || '' ) : '';
  const fulfilmentLabel = order ? ( FULFILMENT_STATUS_LABEL[ order.fulfilmentStatus ] || '' ) : '';
  const items = order && Array.isArray( order.items ) ? order.items : [];
  const charges = order?.charges || null;
  const delivery = order?.delivery || null;
  const deliveryLines = addressLines( delivery?.address );
  const placed = order ? placedLabel( order.createdAt ) : '';
  const money = ( paise: number ) => formatPaiseINR( paise, order?.currency || '' );

  return (
    <section className="odt" aria-labelledby="odt-title" aria-busy={ load.kind === 'loading' }>
      { load.kind === 'loading' && (
        <>
          <h2 className="odt-h2" id="odt-title">
            Order <span data-wc-no-translate>{ orderNumber }</span>
          </h2>
          <p className="odt-p" role="status">Loading your order…</p>
        </>
      ) }

      { load.kind === 'notFound' && (
        <div className="odt-gate">
          <h2 className="odt-h2" id="odt-title">
            Order <span data-wc-no-translate>{ orderNumber }</span>
          </h2>
          <p className="odt-notice" role="status">
            We could not find this order on your account. Check that you signed in with the
            WhatsApp number you ordered from.
          </p>
          <PillButton as="a" href="/orders/" action="See all your orders" />
        </div>
      ) }

      { load.kind === 'unavailable' && (
        <div className="odt-gate">
          <h2 className="odt-h2" id="odt-title">
            Order <span data-wc-no-translate>{ orderNumber }</span>
          </h2>
          <p className="odt-notice" role="status">
            We could not load this order just now. Try again shortly.
          </p>
          <button type="button" className="odt-quiet" onClick={ retry }>Try again</button>
        </div>
      ) }

      { order && (
        <>
          <header className="odt-head">
            { /* The confirmation the customer came here for, in words rather than a colour. */ }
            <p className="odt-kicker">{ paid ? 'Payment received' : paymentLabel }</p>
            <h2 className="odt-h2" id="odt-title">
              Order <span data-wc-no-translate>{ order.orderNumber }</span>
            </h2>
            <p className="odt-status" role="status">
              <span className="odt-status-label">{ paymentLabel }</span>
              { fulfilmentLabel && (
                <>
                  <span className="odt-dot" aria-hidden="true">·</span>
                  <span className="odt-status-label">{ fulfilmentLabel }</span>
                </>
              ) }
            </p>
            { paymentNote && <p className="odt-note">{ paymentNote }</p> }
            { /* No promise of further WhatsApp updates: the WhatsApp payment rail sends its
                 status templates at payment, and a later change to the order row is not
                 guaranteed to send a message. This page reads that row, so it is the place that
                 stays current. */ }
            { paid && (
              <p className="odt-p">This page shows the latest status of your order.</p>
            ) }
          </header>

          <div className="odt-grid">
            <section className="odt-card" aria-labelledby="odt-items">
              <h3 className="odt-h3" id="odt-items">Items</h3>
              { items.length > 0
                ? (
                  <ul className="odt-items">
                    { items.map( ( item, index ) => (
                      <li className="odt-item" key={ `${ item.name }-${ index }` }>
                        <span className="odt-item-name">{ item.name }</span>
                        <span className="odt-item-qty">
                          Qty <span data-wc-no-translate>{ item.quantity }</span>
                        </span>
                        <span className="odt-item-amount" data-wc-no-translate>
                          { money( item.totalPaise ) }
                        </span>
                      </li>
                    ) ) }
                  </ul>
                )
                : <p className="odt-p">Item details are not available for this order.</p> }

              <dl className="odt-sum">
                { charges && (
                  <>
                    <div className="odt-sum-row">
                      <dt>Subtotal</dt>
                      <dd data-wc-no-translate>{ money( charges.merchandisePaise ) }</dd>
                    </div>
                    { charges.discountPaise > 0 && (
                      <div className="odt-sum-row">
                        <dt>{ charges.discountLabel || 'Discount' }</dt>
                        <dd data-wc-no-translate>−{ money( charges.discountPaise ) }</dd>
                      </div>
                    ) }
                    <div className="odt-sum-row">
                      <dt>Delivery</dt>
                      <dd>
                        { charges.deliveryPaise > 0
                          ? <span data-wc-no-translate>{ money( charges.deliveryPaise ) }</span>
                          : 'Free' }
                      </dd>
                    </div>
                    { charges.convenienceFeePaise > 0 && (
                      <div className="odt-sum-row">
                        <dt>Convenience fee</dt>
                        <dd data-wc-no-translate>{ money( charges.convenienceFeePaise ) }</dd>
                      </div>
                    ) }
                    { charges.convenienceGstPaise > 0 && (
                      <div className="odt-sum-row">
                        <dt>GST on convenience fee</dt>
                        <dd data-wc-no-translate>{ money( charges.convenienceGstPaise ) }</dd>
                      </div>
                    ) }
                  </>
                ) }
                <div className="odt-sum-row odt-sum-total">
                  <dt>{ paid ? 'Total paid' : 'Total' }</dt>
                  <dd>
                    { amount
                      ? <span data-wc-no-translate>{ amount }</span>
                      : 'Amount unavailable' }
                  </dd>
                </div>
              </dl>
            </section>

            <div className="odt-side">
              <section className="odt-card" aria-labelledby="odt-delivery">
                <h3 className="odt-h3" id="odt-delivery">Delivery address</h3>
                { delivery && deliveryLines.length > 0
                  ? (
                    <p className="odt-address">
                      { delivery.recipient && (
                        <span className="odt-address-name">{ delivery.recipient }</span>
                      ) }
                      { deliveryLines.map( ( line, index ) => (
                        <span className="odt-address-line" key={ `${ index }-${ line }` }>{ line }</span>
                      ) ) }
                    </p>
                  )
                  : (
                    <p className="odt-p">No delivery address is recorded for this order.</p>
                  ) }
              </section>

              <section className="odt-card" aria-labelledby="odt-facts-title">
                <h3 className="odt-h3" id="odt-facts-title">Order details</h3>
                <dl className="odt-facts">
                  { placed && (
                    <>
                      <dt>Placed</dt>
                      <dd>{ placed }</dd>
                    </>
                  ) }
                  <dt>Ordered on</dt>
                  <dd>{ order.channel === 'whatsapp' ? 'WhatsApp' : 'Website' }</dd>
                  { order.referenceId && (
                    <>
                      <dt>Payment reference</dt>
                      <dd><span data-wc-no-translate>{ order.referenceId }</span></dd>
                    </>
                  ) }
                  { order.invoiceNumber && (
                    <>
                      <dt>Invoice</dt>
                      <dd><span data-wc-no-translate>{ order.invoiceNumber }</span></dd>
                    </>
                  ) }
                  { order.customerDisplayId && (
                    <>
                      <dt>Customer ID</dt>
                      <dd><span data-wc-no-translate>{ order.customerDisplayId }</span></dd>
                    </>
                  ) }
                </dl>
              </section>
            </div>
          </div>

          <div className="odt-actions">
            { /* Plain navigations, not client-side links: /orders/ without `?o=` must remount
                 the page so it shows the history rather than this order again. */ }
            <PillButton as="a" href="/orders/" action="See all your orders" />
            { /* eslint-disable-next-line @next/next/no-html-link-for-pages */ }
            <a className="odt-link" href="/shop/">Continue shopping</a>
          </div>
        </>
      ) }

      <style jsx>{`
        /* odt- prefixed throughout, for the reason OrdersPage gives for ord-: the global
           stylesheets declare unscoped rules for generic class names. The font stack is
           DECLARED on each text rung, never inherited, for the same reason. */
        .odt{color-scheme:light;display:flex;flex-direction:column;gap:28px;min-inline-size:0;max-width:1100px}
        .odt-gate,.odt-head{display:flex;flex-direction:column;align-items:flex-start;gap:14px}
        .odt-head{gap:10px}

        .odt-h2,.odt-h3,.odt-kicker,.odt-p,.odt-note,.odt-status,.odt-notice,.odt-address,
        .odt-items,.odt-sum,.odt-facts,.odt-quiet,.odt-link{
          font-family:'Inter',ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
        }
        .odt-h2{
          font-size:var(--public-section-size);font-weight:var(--public-section-weight);
          line-height:var(--public-section-leading);letter-spacing:var(--public-section-tracking);
          color:var(--public-heading);margin:0;overflow-wrap:anywhere;
        }
        .odt-h3{font-size:20px;font-weight:700;line-height:1.3;color:var(--public-heading);margin:0 0 14px}
        .odt-kicker{margin:0;font-size:14px;font-weight:700;letter-spacing:.2px;color:var(--public-brand-green)}
        .odt-p{
          font-size:var(--public-body-size);font-weight:var(--public-body-weight);
          line-height:var(--public-body-leading);letter-spacing:var(--public-body-tracking);
          color:var(--public-body);margin:0;
        }
        .odt-note{margin:0;font-size:16px;line-height:1.5;color:var(--public-muted)}

        /* The status line: a lime edge and a weight step, never a hue on its own, and every
           state is also stated in words. */
        .odt-status{
          display:inline-flex;flex-wrap:wrap;align-items:center;gap:6px 10px;margin:0;
          padding:12px 16px;border-inline-start:4px solid var(--public-brand-lime);border-radius:10px;
          background:var(--public-lime-tint);color:var(--public-brand-green);font-size:16px;line-height:1.5;
        }
        .odt-status-label{font-weight:700}
        .odt-dot{font-weight:700}
        .odt-notice{
          margin:0;padding:14px 16px;border-inline-start:4px solid var(--public-brand-lime);border-radius:10px;
          background:var(--public-lime-tint);color:var(--public-brand-green);font-size:16px;font-weight:700;line-height:1.5;
        }

        /* Mobile-first: one column; the items card beside a side column from 1024px. */
        .odt-grid{display:grid;grid-template-columns:minmax(0,1fr);gap:20px;align-items:start}
        .odt-side{display:flex;flex-direction:column;gap:20px;min-inline-size:0}
        .odt-card{
          min-inline-size:0;padding:20px;border:1px solid var(--public-hairline);
          border-radius:16px;background:#fff;
        }

        .odt-items{list-style:none;margin:0 0 16px;padding:0;display:flex;flex-direction:column}
        .odt-item{
          display:grid;grid-template-columns:minmax(0,1fr) auto;grid-template-areas:'name amount' 'qty amount';
          gap:2px 16px;padding:12px 0;border-block-end:1px solid var(--public-hairline);
        }
        .odt-item-name{grid-area:name;font-size:16px;font-weight:600;line-height:1.4;color:#1a1a1a;overflow-wrap:anywhere}
        .odt-item-qty{grid-area:qty;font-size:14px;color:var(--public-muted)}
        .odt-item-amount{grid-area:amount;align-self:center;font-size:16px;font-weight:700;color:#1a1a1a;font-variant-numeric:tabular-nums;white-space:nowrap}

        .odt-sum{margin:0;display:flex;flex-direction:column;gap:8px}
        .odt-sum-row{display:flex;justify-content:space-between;align-items:baseline;gap:16px}
        .odt-sum-row dt{font-size:15px;color:var(--public-muted)}
        .odt-sum-row dd{margin:0;font-size:15px;color:#1a1a1a;font-variant-numeric:tabular-nums;text-align:end}
        .odt-sum-total{margin-block-start:6px;padding-block-start:12px;border-block-start:1px solid var(--public-hairline)}
        .odt-sum-total dt,.odt-sum-total dd{font-size:18px;font-weight:700;color:var(--public-heading)}

        .odt-address{margin:0;display:flex;flex-direction:column;gap:2px;font-size:16px;line-height:1.5;color:#1a1a1a;font-style:normal}
        .odt-address-name{font-weight:700}
        .odt-address-line{overflow-wrap:anywhere}

        .odt-facts{margin:0;display:grid;grid-template-columns:132px minmax(0,1fr);gap:8px 12px;align-items:baseline}
        .odt-facts dt{font-size:12px;font-weight:700;color:var(--public-brand-green)}
        .odt-facts dd{margin:0;font-size:16px;line-height:1.5;color:#1a1a1a;overflow-wrap:anywhere}

        .odt-actions{display:flex;flex-wrap:wrap;align-items:center;gap:16px 24px}
        .odt-link{
          display:inline-flex;align-items:center;min-height:var(--tap-min);
          font-size:17px;font-weight:600;color:var(--public-brand-green);
          text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:2px;
        }
        .odt-link:hover,.odt-link:focus-visible{text-decoration-thickness:2px}
        .odt-link:focus-visible{outline:3px solid #1a3a2a;outline-offset:3px}
        /* The quiet secondary from OrdersPage: a lime EDGE, a dark label and a dark focus ring. */
        .odt-quiet{
          display:inline-flex;align-items:center;justify-content:center;min-height:var(--tap-min);
          padding:0 24px;border:2px solid #d1f470;border-radius:50px;background:#fff;
          color:var(--public-brand-green);font-size:17px;font-weight:600;cursor:pointer;
        }
        .odt-quiet:hover{background:var(--public-lime-tint)}
        .odt-quiet:focus-visible{outline:3px solid #1a3a2a;outline-offset:3px}

        @media(min-width:1024px){
          .odt-grid{grid-template-columns:minmax(0,1fr) 360px;gap:28px}
        }
        @media(max-width:767px){
          .odt-card{padding:16px;border-radius:14px}
          .odt-p{font-size:18px}
          .odt-facts{grid-template-columns:1fr;gap:2px}
          .odt-facts dd{margin-block-end:8px}
        }
      `}</style>
    </section>
  );
}
