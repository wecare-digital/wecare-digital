import React, { useEffect, useMemo, useState } from 'react';

import type { CheckoutLineItem } from '../../lib/cart';
import { basketFingerprint } from '../../lib/cart';
import { formatPaiseINR } from '../../lib/money';

/** Read-only quotation. No payment attempt, gateway order or invoice is created here. */
const QUOTE_URL = `${process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api'}/ecommerce/prepare-checkout`;

interface Quote {
  currency: string;
  subtotalPaise: number;
  supplyGstPaise: number;
  discountPaise: number;
  discountLabel: string;
  deliveryPaise: number;
  requiresDelivery: boolean;
  deliveryLabel: string;
  convenienceFeePaise: number;
  convenienceGstPaise: number;
  totalPayablePaise: number;
}
interface Props {
  accessToken: string;
  lineItems: CheckoutLineItem[];
  onQuoteReady: (fingerprint: string) => void;
}
type State = { kind: 'loading' } | { kind: 'failed' } | { kind: 'ready'; quote: Quote };

const COMPONENTS: ReadonlyArray<keyof Quote> = [
  'subtotalPaise', 'supplyGstPaise', 'discountPaise', 'deliveryPaise',
  'convenienceFeePaise', 'convenienceGstPaise', 'totalPayablePaise',
];

function validQuote ( value: unknown ): value is Quote {
  if ( !value || typeof value !== 'object' ) return false;
  const q = value as Partial<Quote>;
  if ( q.currency !== 'INR' || typeof q.requiresDelivery !== 'boolean' ) return false;
  if ( typeof q.deliveryLabel !== 'string' || q.deliveryLabel.length > 40 ) return false;
  if ( !COMPONENTS.every( key => Number.isSafeInteger( q[ key ] ) && Number( q[ key ] ) >= 0 ) ) return false;
  return q.subtotalPaise! + q.supplyGstPaise! + q.deliveryPaise! - q.discountPaise!
    + q.convenienceFeePaise! + q.convenienceGstPaise! === q.totalPayablePaise!;
}

/**
 * Website-only Phase 1 price display. Uses the SAME server quote computation as
 * Razorpay prepare, but does not trust a browser catalogue price or infer GST.
 * A quote is refreshed on selection changes and recalculated by the backend when
 * Pay here opens Razorpay. The provider's amount remains the final review point.
 */
export default function CheckoutPriceBreakdown (
  { accessToken, lineItems, onQuoteReady }: Props,
): React.ReactElement {
  const fingerprint = lineItems.length === 1 ? basketFingerprint( lineItems ) : '';
  const serial = JSON.stringify( lineItems );
  const [ refresh, setRefresh ] = useState( 0 );
  const [ state, setState ] = useState<State>( { kind: 'loading' } );

  // An immutable, validated payload for this cart revision. Keep the effect's
  // request data stable across parent rerenders while its amount never comes
  // from a catalogue display string.
  const currentLines = useMemo( () => JSON.parse( serial ) as CheckoutLineItem[], [ serial ] );

  useEffect( () => {
    onQuoteReady( '' );
    if ( !fingerprint || !accessToken ) return undefined;
    let alive = true;
    setState( { kind: 'loading' } );
    void ( async () => {
      try {
        const response = await fetch( QUOTE_URL, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${accessToken}`,
          },
          body: JSON.stringify( { action: 'quote', lineItems: currentLines } ),
        } );
        const data = await response.json().catch( () => ( {} ) ) as {
          status?: string;
          quote?: unknown;
        };
        if ( !alive ) return;
        if ( !response.ok || data.status !== 'QUOTE_READY' || !validQuote( data.quote ) ) {
          setState( { kind: 'failed' } );
          return;
        }
        setState( { kind: 'ready', quote: data.quote } );
        onQuoteReady( fingerprint );
      } catch {
        if ( alive ) setState( { kind: 'failed' } );
      }
    } )();
    return () => { alive = false; };
  }, [ accessToken, currentLines, fingerprint, onQuoteReady, refresh ] );

  const line = ( amount: number ) => formatPaiseINR( amount, 'INR' );
  return (
    <section className="cq" aria-label="Checkout price breakdown">
      <h2 className="cq-heading">Price breakdown</h2>
      { !accessToken
        ? <p className="cq-note">Sign in to review the full amount before payment.</p>
        : state.kind === 'loading' || !fingerprint
          ? <p className="cq-note" role="status">Calculating your total securely…</p>
          : state.kind === 'failed'
            ? (
              <div className="cq-retry">
                <p className="cq-note" role="status">
                  We could not confirm the price. Nothing has been charged.
                </p>
                <button type="button" onClick={ () => setRefresh( n => n + 1 ) }>Try again</button>
              </div>
            )
            : (
              <>
                <dl className="cq-list">
                  <div><dt>Item subtotal</dt><dd data-wc-no-translate>{ line( state.quote.subtotalPaise ) }</dd></div>
                  { state.quote.supplyGstPaise > 0 && (
                    <div><dt>Supply GST</dt><dd data-wc-no-translate>{ line( state.quote.supplyGstPaise ) }</dd></div>
                  ) }
                  { state.quote.discountPaise > 0 && (
                    <div><dt>{ state.quote.discountLabel || 'Discount' }</dt>
                      <dd data-wc-no-translate>−{ line( state.quote.discountPaise ) }</dd></div>
                  ) }
                  { state.quote.requiresDelivery && (
                    <div><dt>Delivery</dt><dd data-wc-no-translate>
                      { state.quote.deliveryPaise ? line( state.quote.deliveryPaise ) : 'Free' }
                    </dd></div>
                  ) }
                  { state.quote.deliveryPaise > 0 && !state.quote.requiresDelivery && (
                    <div><dt>{ state.quote.deliveryLabel }</dt><dd data-wc-no-translate>{ line( state.quote.deliveryPaise ) }</dd></div>
                  ) }
                  { state.quote.convenienceFeePaise > 0 && (
                    <div><dt>Convenience fee</dt><dd data-wc-no-translate>{ line( state.quote.convenienceFeePaise ) }</dd></div>
                  ) }
                  { state.quote.convenienceGstPaise > 0 && (
                    <div><dt>GST on convenience fee</dt><dd data-wc-no-translate>{ line( state.quote.convenienceGstPaise ) }</dd></div>
                  ) }
                  <div className="cq-total"><dt>Total payable</dt>
                    <dd data-wc-no-translate>{ line( state.quote.totalPayablePaise ) }</dd></div>
                </dl>
                <p className="cq-note">The final amount is rechecked by Razorpay before you confirm payment.</p>
              </>
            ) }
      <style jsx>{`
        .cq{margin:16px 0 22px;padding:18px 0;border-top:1px solid var(--public-hairline);border-bottom:1px solid var(--public-hairline);font-family:var(--font-sans)}
        .cq-heading{margin:0 0 12px;color:var(--public-heading);font-size:var(--public-card-size);font-weight:var(--public-card-weight);line-height:var(--public-card-leading)}
        .cq-list{margin:0;display:flex;flex-direction:column;gap:10px}
        .cq-list>div{display:flex;align-items:baseline;justify-content:space-between;gap:18px}
        .cq-list dt{color:var(--public-muted);font-size:15px}
        .cq-list dd{margin:0;text-align:end;color:var(--public-heading);font-size:15px;font-variant-numeric:tabular-nums}
        .cq-list .cq-total{padding-top:12px;border-top:1px solid var(--public-hairline)}
        .cq-total dt,.cq-total dd{color:var(--public-brand-green);font-size:18px;font-weight:700}
        .cq-note{margin:10px 0 0;font-size:14px;line-height:1.5;color:var(--public-muted)}
        .cq-retry button{margin-top:12px;min-height:44px;border:0;border-radius:10px;background:var(--public-lime-tint);color:var(--public-brand-green);padding:0 16px;font-weight:700;text-decoration:underline;cursor:pointer}
      `}</style>
    </section>
  );
}
