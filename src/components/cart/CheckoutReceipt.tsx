import React from 'react';
import type { CheckoutQuote } from '../../lib/checkoutQuote';
import { formatPaiseINR } from '../../lib/money';

/** Presentation only: every monetary value comes from the validated server quote. */
export default function CheckoutReceipt ( { quote }: { quote: CheckoutQuote } ): React.ReactElement {
  const { charges, items } = quote;
  const money = ( paise: number ) => formatPaiseINR( paise, quote.currency );
  return (
    <div className="receipt">
      <ul className="receipt-items" aria-label="Server-verified order items">
        { items.map( ( item, index ) => (
          <li key={ `${index}-${item.name}` }>
            <div><strong>{ item.name }</strong><small>Qty { item.quantity } · { money( item.unitPricePaise ) } base each</small></div>
            <span data-wc-no-translate="true">{ money( item.totalPaise ) }</span>
          </li>
        ) ) }
      </ul>
      <dl className="receipt-charges">
        <div><dt>{ items.length === 1 ? 'Base price' : 'Base price subtotal' }</dt><dd data-wc-no-translate="true">{ money( charges.merchandisePaise ) }</dd></div>
        <div><dt>Supply GST (18%)</dt><dd data-wc-no-translate="true">+{ money( charges.supplyGstPaise ) }</dd></div>
        <div><dt>{ charges.discountLabel === 'Delight' ? 'Delight (0.5%)' : ( charges.discountLabel || 'Delight' ) }</dt><dd data-wc-no-translate="true">−{ money( charges.discountPaise ) }</dd></div>
        <div><dt>{ charges.deliveryLabel || 'Delivery' }</dt><dd data-wc-no-translate="true">{ charges.deliveryPaise > 0 ? `+${money( charges.deliveryPaise )}` : money( 0 ) }</dd></div>
        <div><dt>Convenience fee (2.5%)</dt><dd data-wc-no-translate="true">+{ money( charges.convenienceFeePaise ) }</dd></div>
        <div><dt>GST on convenience fee (18%)</dt><dd data-wc-no-translate="true">+{ money( charges.convenienceGstPaise ) }</dd></div>
        <div className="receipt-total"><dt>Final total<small>Amount payable</small></dt><dd data-wc-no-translate="true">{ money( charges.totalPaise ) }</dd></div>
      </dl>
      <p className="receipt-note">Full breakup shown before payment.</p>
      <style jsx>{`
        .receipt{min-width:0;color:var(--public-text);font-family:var(--font-sans)}
        .receipt-items{list-style:none;margin:0 0 12px;padding:0;background:var(--public-lime-tint);border-radius:10px}
        .receipt-items li{display:flex;justify-content:space-between;gap:14px;padding:13px;font-size:14px;border-bottom:1px solid var(--public-hairline)}
        .receipt-items li:last-child{border-bottom:0}.receipt-items li>div{min-width:0}.receipt-items strong{font-size:15px;overflow-wrap:anywhere}.receipt-items small{display:block;margin-top:5px;font-size:12px;color:var(--public-muted)}.receipt-items li>span{white-space:nowrap;font-variant-numeric:tabular-nums}
        .receipt-charges{margin:0}.receipt-charges>div{display:flex;justify-content:space-between;align-items:baseline;gap:16px;padding:12px 4px;border-bottom:1px dashed var(--public-hairline);font-size:15px;line-height:1.5}.receipt-charges dt{min-width:0}.receipt-charges dd{margin:0;white-space:nowrap;text-align:right;font-variant-numeric:tabular-nums;color:var(--public-heading)}
        .receipt-charges .receipt-total{align-items:center;margin-top:20px;padding:16px;border:0;border-radius:12px;background:var(--public-brand-lime);color:#111}.receipt-total dt{font-size:16px;font-weight:800}.receipt-total small{display:block;font-size:12px;font-weight:500;margin-top:3px}.receipt-total dd{font-size:clamp(24px,3vw,34px);font-weight:850;letter-spacing:-.03em;color:#111}
        .receipt-note{margin:16px 0 0;padding:12px;border-radius:10px;background:var(--public-lime-tint);font-size:13px;color:var(--public-brand-green)}
        @media(max-width:380px){.receipt-charges>div{font-size:13px;gap:10px}.receipt-charges .receipt-total{padding:12px}.receipt-total dt{font-size:14px}.receipt-total dd{font-size:24px}.receipt-items li{padding:10px;font-size:13px;gap:8px}}
      `}</style>
    </div>
  );
}
