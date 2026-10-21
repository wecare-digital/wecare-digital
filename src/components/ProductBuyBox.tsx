import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/router';

import { addItem, type CartItem } from '../lib/cart';
import type { ShopProduct } from '../content/shop';
import { getSession, restoreSession } from '../lib/customerAuth';
import { CHECKOUT_PATH, SIGN_IN_PATH } from '../lib/serviceEntry';
import { productCheckoutLine } from '../config/productCheckout';
import CheckoutAction from './CheckoutAction';

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
  const [ signedIn, setSignedIn ] = useState( false );
  const [ busy, setBusy ] = useState( false );
  const [ error, setError ] = useState<string | null>( null );

  const alive = useRef( true );
  useEffect( () => () => { alive.current = false; }, [] );

  const line = productCheckoutLine( slug );

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

  /**
   * The click. Signed out → the one WhatsApp sign-in, returning to /cart/ (checkout is the
   * destination for a product, there is nothing to pick first). Signed in → add the catalogue
   * line and go to the cart. The line is a real in-stock product, so the server accepts it.
   */
  const onContinue = useCallback( async () => {
    if ( !line || busy ) return;
    setError( null );

    if ( !signedIn ) {
      // The cart survives the sign-in redirect in localStorage, so adding the line BEFORE the
      // redirect means it is already present on return — the same contract the shop cart uses.
      try {
        addProductLine( line );
      } catch {
        /* a malformed line writes nothing; the checkout still loads, just empty */
      }
      await router.push( `${ SIGN_IN_PATH }?return=${ encodeURIComponent( CHECKOUT_PATH ) }` );
      return;
    }

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
  }, [ busy, signedIn, router, line ] );

  // No fresh catalog line yet: keep the public product page, but offer no stale checkout action.
  if ( !line ) return null;

  const label = 'Checkout';

  return (
    <div className="pbb">
      <CheckoutAction
        onClick={ () => { void onContinue(); } }
        disabled={ busy }
        busy={ busy }
      >
        { busy ? 'One moment…' : label }
      </CheckoutAction>

      {/* Configured price and one supporting line are one canonical rail. */}
      <p className="pbb-buy">
        <span className="pbb-price" data-wc-no-translate="true">{ displayPrice ?? line.formattedPrice }</span>
      </p>
      <p className="pbb-offer-note">{ offerNote }</p>

      { error && <p className="pbb-error" role="alert">{ error }</p> }

      <style jsx>{`
        /* The action itself is CheckoutAction: the same compact treatment used by Elsewhere
           Activity results. This component owns only the price/supporting copy below it. */
        .pbb{display:flex;flex-direction:column;align-items:flex-start;gap:0;margin-top:12px}

        .pbb-buy{display:flex;flex-wrap:wrap;align-items:baseline;gap:16px;margin:22px 0 0}
        .pbb-price{font-size:var(--public-card-size);font-weight:var(--public-card-weight);line-height:var(--public-card-leading);letter-spacing:var(--public-card-tracking);color:var(--public-brand-green);font-variant-numeric:tabular-nums}
        .pbb-offer-note{
          max-width:var(--public-copy-max);margin:7px 0 0;font-family:var(--font-sans);
          font-size:var(--public-body-size);font-weight:var(--public-body-weight);
          line-height:var(--public-body-leading);letter-spacing:var(--public-body-tracking);
          color:var(--public-muted);text-wrap:balance;
        }

        .pbb-error{margin:12px 0 0;font-size:14px;color:#b91c1c}

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
