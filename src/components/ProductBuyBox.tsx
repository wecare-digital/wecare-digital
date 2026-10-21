import React, { useCallback, useRef, useState } from 'react';
import { useRouter } from 'next/router';

import { addItem, type CartItem } from '../lib/cart';
import type { ShopProduct } from '../content/shop';
import { CHECKOUT_PATH } from '../lib/serviceEntry';
import { productCheckoutLine } from '../config/productCheckout';

/**
 * THE PRODUCT "CONTINUE TO CHECKOUT" ACTION, mounted under the WhatsApp CTA on configured public
 * commerce pages.
 *
 * SAME SHAPE AS ServiceBuyBox, DIFFERENT RAIL. A product is an ORDINARY cart line — no
 * pre-payment intent, no target order — so this uses the plain shop path: `addItem` writes a
 * catalogue reference + quantity, then it navigates to `/cart/`, where the existing checkout
 * prices and collects. The WhatsApp pill above is untouched; this renders beneath it through
 * ProductPage's `belowCta` slot.
 *
 * A product buy box renders only when a fresh configured checkout line exists. There is no
 * fallback product and no legacy checkout mapping. The server remains the price authority.
 */

interface ProductBuyBoxProps {
  /** The product page's slug, e.g. 'elsewhere'. Chooses the checkout line from the config. */
  slug: string;
  /** Optional presentation-only price string. Checkout still uses the configured server-authoritative line. */
  displayPrice?: string;
  /** Quiet line below the price, matching the Grahak OS commerce pattern. */
  offerNote?: string;
}

const ProductBuyBox: React.FC<ProductBuyBoxProps> = ( {
  slug,
  displayPrice,
  offerNote = 'One-time purchase',
} ) => {
  const router = useRouter();
  const [ busy, setBusy ] = useState( false );
  const [ error, setError ] = useState<string | null>( null );

  const alive = useRef( true );
  React.useEffect( () => () => { alive.current = false; }, [] );

  const line = productCheckoutLine( slug );

  /**
   * Route pages expose ONE checkout action. The payment rail is chosen later, once, after the
   * customer has reviewed the cart on /cart/ and reached /checkout/.
   */
  const onContinue = useCallback( async () => {
    if ( !line || busy ) return;
    setError( null );
    setBusy( true );
    try {
      addProductLine( line );
      await router.push( CHECKOUT_PATH );
    } catch {
      if ( alive.current ) {
        setError( 'Something went wrong. Nothing has been charged. Please try again.' );
        setBusy( false );
      }
    }
  }, [ busy, router, line ] );

  // No fresh catalog line yet: keep the public product page, but offer no stale checkout action.
  if ( !line ) return null;

  return (
    <div className="pbb">
      <button
        type="button"
        className="pbb-cta"
        onClick={ () => { void onContinue(); } }
        disabled={ busy }
        aria-busy={ busy }
      >
        { busy ? 'One moment…' : 'Checkout' }
      </button>

      {/* Configured price and one supporting line are one canonical rail. */}
      <p className="pbb-buy">
        <span className="pbb-price" data-wc-no-translate="true">{ displayPrice ?? line.formattedPrice }</span>
      </p>
      <p className="pbb-offer-note">{ offerNote }</p>

      { error && <p className="pbb-error" role="alert">{ error }</p> }

      <style jsx>{`
        /* Secondary pill under the WhatsApp CTA — identical treatment to ServiceBuyBox so the two
           families match: white fill, 2px #1a3a2a edge and type, lime #d1f470 hover with the house
           lift, reduced-motion aware. */
        .pbb{display:flex;flex-direction:column;align-items:flex-start;gap:0;margin-top:12px}
        .pbb-cta{
          display:inline-flex;align-items:center;justify-content:center;min-height:var(--public-cta-height);
          padding:0 26px;border:var(--public-cta-border) solid var(--public-brand-green);border-radius:var(--public-cta-radius);
          background:#fff;color:var(--public-brand-green);font-size:var(--public-cta-font-size);font-weight:var(--public-cta-font-weight);cursor:pointer;
          transition:background-color .2s,transform .2s,box-shadow .2s;
        }
        .pbb-cta:hover:not(:disabled){
          background:var(--public-brand-lime);transform:translateY(-2px);box-shadow:var(--public-lift-shadow);
        }
        .pbb-cta:focus-visible{outline:3px solid var(--public-brand-green);outline-offset:3px}
        .pbb-cta:disabled{opacity:.5;cursor:default}

        .pbb-buy{display:flex;flex-wrap:wrap;align-items:baseline;gap:16px;margin:22px 0 0}
        .pbb-price{font-size:var(--public-card-size);font-weight:var(--public-card-weight);line-height:var(--public-card-leading);letter-spacing:var(--public-card-tracking);color:var(--public-brand-green);font-variant-numeric:tabular-nums}
        .pbb-offer-note{
          max-width:var(--public-copy-max);margin:7px 0 0;font-family:var(--font-sans);
          font-size:var(--public-body-size);font-weight:var(--public-body-weight);
          line-height:var(--public-body-leading);letter-spacing:var(--public-body-tracking);
          color:var(--public-muted);text-wrap:balance;
        }

        .pbb-error{margin:12px 0 0;font-size:14px;color:#b91c1c}

        @media(prefers-reduced-motion:reduce){
          .pbb-cta{transition:background-color .2s}
          .pbb-cta:hover:not(:disabled){transform:none;box-shadow:none}
        }
      `}</style>
    </div>
  );

  // ── helpers ────────────────────────────────────────────────────────────────────────────────
};

/**
 * Add the checkout line as an ordinary single-variant shop product. Built as a minimal ShopProduct
 * so `addItem` keys it on the real catalogue product id and variant, exactly like a /shop/ add.
 */
function addProductLine ( line: NonNullable<ReturnType<typeof productCheckoutLine>> ): CartItem[] {
  const product: ShopProduct = {
    id: line.productId,
    name: line.name,
    slug: line.slug,
    formattedPrice: line.formattedPrice,
    price: '',
    currency: 'INR',
    inStock: true,
    tagline: '',
    body: [],
    variants: [ { id: line.variantId, label: 'Standard', inStock: true } ],
  };
  return addItem( product, 1, line.variantId );
}

export default ProductBuyBox;
