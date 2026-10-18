import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/router';

import { addItem, type CartItem } from '../lib/cart';
import type { ShopProduct } from '../content/shop';
import { getSession, restoreSession } from '../lib/customerAuth';
import { CHECKOUT_PATH, SIGN_IN_PATH } from '../lib/serviceEntry';
import { productCheckoutLine } from '../config/productCheckout';

/**
 * THE PRODUCT "CONTINUE TO CHECKOUT" ACTION, mounted under the WhatsApp CTA on nine pages (Expo
 * Week, Dastavez, Clear Closure, Ritual Guru, Anew, Prastuti, Niji Setu, Bharat Rx, Refer & Earn).
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
  /** Show the configured product price line. Default true. */
  showPrice?: boolean;
  /** Quiet line below the price, matching the Grahak OS commerce pattern. */
  offerNote?: string;
}

const ProductBuyBox: React.FC<ProductBuyBoxProps> = ( {
  slug,
  showPrice = true,
  offerNote = 'One-time purchase · final total confirmed at checkout',
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

  const label = 'Continue to checkout →';

  return (
    <div className="pbb">
      <button
        type="button"
        className="pbb-cta"
        onClick={ () => { void onContinue(); } }
        disabled={ busy }
        aria-busy={ busy }
      >
        { busy ? 'One moment…' : label }
      </button>

      {/* Configured price for the fresh catalog line. */}
      { showPrice && (
        <>
          <p className="pbb-buy">
            <span className="pbb-price" data-wc-no-translate="true">{ line.formattedPrice }</span>
          </p>
          <p className="pbb-offer-note">{ offerNote }</p>
        </>
      ) }

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
        .pbb-price{font-size:var(--public-card-size);font-weight:var(--public-card-weight);line-height:1.2;letter-spacing:var(--public-card-tracking);color:var(--public-brand-green);font-variant-numeric:tabular-nums}
        .pbb-offer-note{
          max-width:620px;margin:7px 0 0;
          font-size:var(--public-body-size);font-weight:var(--public-body-weight);
          line-height:var(--public-body-leading);letter-spacing:var(--public-body-tracking);
          color:var(--public-body);
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
