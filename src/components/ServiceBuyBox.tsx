import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/router';

import { serviceByKind, type ServiceChoice } from '../config/services';
import {
  fetchServicePrices, type ServicePrice,
} from '../lib/servicePricing';
import { getSession, restoreSession } from '../lib/customerAuth';
import {
  fetchCustomerOrders,
  startRequestService,
  type CustomerOrderChoice,
} from '../lib/requestServiceStart';
import { goToServiceAction } from '../lib/serviceEntry';
import CheckoutAction from './CheckoutAction';
import { trackMetaViewContent } from '../lib/metaPixel';

/**
 * One public request-service handoff.
 *
 * The browser does only three things: authenticate, let the customer choose ONE existing
 * Order Number, and send {serviceCode, selectedOrderNumber}. It never sends a price, SKU,
 * customer id, internal order id or service-request id. The backend re-resolves every one of
 * those facts, then sends the approved native Review & Pay template to the registered WhatsApp
 * number. There is deliberately no cart/second payment chooser on this path.
 */
interface ServiceBuyBoxProps {
  service: ServiceChoice;
}

type Phase =
  | { kind: 'loading' }
  | { kind: 'unavailable' }
  | { kind: 'ready'; price: Extract<ServicePrice, { available: true }> };

function orderDate ( value: number | string | null ): string {
  if ( value === null || value === undefined || value === '' ) return '';
  const raw = typeof value === 'number' && value < 10_000_000_000 ? value * 1000 : value;
  const date = new Date( raw );
  if ( Number.isNaN( date.getTime() ) ) return '';
  return date.toLocaleString( undefined, {
    day: '2-digit', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit',
  } );
}

const ServiceBuyBox: React.FC<ServiceBuyBoxProps> = ( { service } ) => {
  const router = useRouter();
  const [ phase, setPhase ] = useState<Phase>( { kind: 'loading' } );
  const [ signedIn, setSignedIn ] = useState( false );
  const [ orders, setOrders ] = useState<CustomerOrderChoice[] | null>( null );
  const [ ordersLoading, setOrdersLoading ] = useState( false );
  const [ chosenOrder, setChosenOrder ] = useState( '' );
  const [ busy, setBusy ] = useState( false );
  const [ sent, setSent ] = useState( false );
  const [ error, setError ] = useState<string | null>( null );
  const alive = useRef( true );

  useEffect( () => () => { alive.current = false; }, [] );

  useEffect( () => {
    let cancelled = false;
    void ( async () => {
      const prices = await fetchServicePrices();
      if ( cancelled || !alive.current ) return;
      const price = prices[ service.slug ];
      setPhase( price && price.available ? { kind: 'ready', price } : { kind: 'unavailable' } );
    } )();
    return () => { cancelled = true; };
  }, [ service.slug ] );

  useEffect( () => {
    if ( phase.kind !== 'ready' ) return;
    trackMetaViewContent( {
      productId: service.productId,
      variantId: service.variantId,
      name: service.label,
      value: phase.price.paise / 100,
      currency: 'INR',
    } );
  }, [ phase, service ] );

  useEffect( () => {
    let cancelled = false;
    void ( async () => {
      let live = getSession() !== null;
      if ( !live ) {
        try { live = ( await restoreSession() ) !== null; } catch { live = false; }
      }
      if ( !cancelled && alive.current ) setSignedIn( live );
    } )();
    return () => { cancelled = true; };
  }, [] );

  useEffect( () => {
    if ( !signedIn || orders !== null ) return;
    const session = getSession();
    if ( !session ) return;
    let cancelled = false;
    void ( async () => {
      setOrdersLoading( true );
      const outcome = await fetchCustomerOrders( session.accessToken );
      if ( cancelled || !alive.current ) return;
      if ( outcome.kind === 'expired' ) {
        setSignedIn( false );
        setOrders( [] );
      } else {
        setOrders( outcome.kind === 'ok' ? outcome.orders : [] );
      }
      setOrdersLoading( false );
    } )();
    return () => { cancelled = true; };
  }, [ signedIn, orders ] );

  const onContinue = useCallback( async () => {
    if ( phase.kind !== 'ready' || busy || sent ) return;
    setError( null );

    if ( !signedIn ) {
      await goToServiceAction( router, {
        destination: service.path,
        action: { kind: service.slug, variantId: service.variantId, label: service.label },
      } );
      return;
    }

    const session = getSession();
    if ( !session ) { setSignedIn( false ); return; }
    if ( !chosenOrder ) {
      setError( 'Choose which order this is for.' );
      return;
    }

    setBusy( true );
    try {
      const outcome = await startRequestService(
        session.accessToken,
        service.kind,
        chosenOrder,
      );
      if ( !alive.current ) return;
      if ( outcome.kind === 'expired' ) {
        setSignedIn( false );
        setBusy( false );
        return;
      }
      if ( outcome.kind !== 'sent' ) {
        setError(
          outcome.kind === 'notAvailable'
            ? 'That order cannot be used for this service.'
            : 'We could not send the payment request. Nothing has been charged. Please try again.'
        );
        setBusy( false );
        return;
      }
      setSent( true );
      setBusy( false );
    } catch {
      if ( alive.current ) {
        setError( 'Something went wrong. Nothing has been charged. Please try again.' );
        setBusy( false );
      }
    }
  }, [ phase, busy, sent, signedIn, router, service, chosenOrder ] );

  if ( phase.kind === 'loading' || phase.kind === 'unavailable' ) return null;

  const noOrders = orders !== null && orders.length === 0;
  const disabled = busy || sent || ( signedIn && ( noOrders || !chosenOrder ) );

  return (
    <div className="sbb">
      { signedIn && !sent && (
        <div className="sbb-target">
          { ordersLoading && <p className="sbb-hint">Loading your orders…</p> }
          { noOrders && (
            <p className="sbb-hint">You have no eligible orders for this service.</p>
          ) }
          { orders !== null && orders.length > 0 && (
            <label className="sbb-pick">
              <span className="sbb-pick-label">Choose your order</span>
              <select
                className="sbb-select"
                value={ chosenOrder }
                onChange={ event => { setChosenOrder( event.target.value ); setError( null ); } }
                disabled={ busy }
              >
                <option value="">Choose an order…</option>
                { orders.map( row => {
                  const when = orderDate( row.createdAt );
                  return (
                    <option key={ row.orderNumber } value={ row.orderNumber }>
                      { row.orderNumber }{ when ? ` · ${ when }` : '' }
                    </option>
                  );
                } ) }
              </select>
            </label>
          ) }
        </div>
      ) }

      { !sent && (
        <CheckoutAction
          onClick={ () => { void onContinue(); } }
          disabled={ disabled }
          busy={ busy }
        >
          { busy ? 'One moment…' : 'Checkout' }
        </CheckoutAction>
      ) }

      { sent && (
        <p className="sbb-sent" role="status">
          Payment request sent to your registered WhatsApp number.
        </p>
      ) }

      <p className="sbb-buy">
        <span className="sbb-price" data-wc-no-translate="true">{ `₹${ phase.price.rupees }` }</span>
      </p>
      <p className="sbb-offer-note">One-time service</p>

      { error && <p className="sbb-error" role="alert">{ error }</p> }

      <style jsx>{`
        .sbb{display:flex;flex-direction:column;align-items:flex-start;gap:0;margin-top:12px}
        .sbb-target{margin:0 0 14px;width:100%}
        .sbb-pick{display:flex;flex-direction:column;gap:6px}
        .sbb-pick-label{font-size:15px;font-weight:600;color:var(--public-brand-green)}
        .sbb-select{
          min-height:48px;padding:0 14px;border:1px solid #d1d5db;border-radius:10px;
          background:#fff;font-size:15px;color:var(--public-body);width:min(100%,520px);
        }
        .sbb-select:focus-visible{outline:3px solid var(--public-brand-green);outline-offset:2px}
        .sbb-hint{margin:0 0 2px;font-size:14px;color:var(--public-muted)}
        .sbb-sent{
          margin:0;font-size:15px;font-weight:600;line-height:1.5;color:var(--public-brand-green);
        }
        .sbb-buy{display:flex;flex-wrap:wrap;align-items:baseline;gap:16px;margin:22px 0 0}
        .sbb-price{font-size:var(--public-card-size);font-weight:var(--public-card-weight);line-height:var(--public-card-leading);letter-spacing:var(--public-card-tracking);color:var(--public-brand-green);font-variant-numeric:tabular-nums}
        .sbb-offer-note{
          max-width:var(--public-copy-max);margin:7px 0 0;font-family:var(--font-sans);
          font-size:var(--public-body-size);font-weight:var(--public-body-weight);
          line-height:var(--public-body-leading);letter-spacing:var(--public-body-tracking);
          color:var(--public-muted);text-wrap:balance;
        }
        .sbb-error{margin:12px 0 0;font-size:14px;color:#b91c1c}
      `}</style>
    </div>
  );
};

export default ServiceBuyBox;
export { serviceByKind };
