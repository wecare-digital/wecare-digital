import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/router';

import { addItem, type CartItem } from '../lib/cart';
import type { ShopProduct } from '../content/shop';
import { getSession, restoreSession } from '../lib/customerAuth';
import { CHECKOUT_PATH, SIGN_IN_PATH } from '../lib/serviceEntry';
import { productCheckoutLine, isPlaceholderCheckout } from '../config/productCheckout';

/**
 * THE PRODUCT "CONTINUE TO CHECKOUT" ACTION, mounted under the WhatsApp CTA on the nine product
 * pages (Elsewhere, Expo Week, Dastavez, Clear Closure, Ritual Guru, Anew, Hunar, Niji Setu,
 * Bharat Rx).
 *
 * SAME SHAPE AS ServiceBuyBox, DIFFERENT RAIL. A product is an ORDINARY cart line — no
 * pre-payment intent, no target order — so this uses the plain shop path: `addItem` writes a
 * catalogue reference + quantity, then it navigates to `/cart/`, where the existing checkout
 * prices and collects. The WhatsApp pill above is untouched; this renders beneath it through
 * ProductPage's `belowCta` slot.
 *
 * TEMPORARY ₹1 LINE. These products have no real Wix line yet, so the button checks out a REAL ₹1
 * catalogue product (see src/config/productCheckout.ts) — the whole format is live and paid end to
 * end, and going real for a product is a one-line edit in that config. The price shown is the
 * line's own `formattedPrice` (Wix's), in /anew/'s `.pdp-price` treatment; the server re-prices on
 * prepare, so the browser never sends an amount.
 */

interface ProductBuyBoxProps {
  /** The product page's slug, e.g. 'elsewhere'. Chooses the checkout line from the config. */
  slug: string;
}

const ProductBuyBox: React.FC<ProductBuyBoxProps> = ( { slug } ) => {
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
    if ( busy ) return;
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

  // ALWAYS "Continue to checkout →", signed in or out — the sign-in is a step on the way, not the
  // button's label. A signed-out tap still routes through the WhatsApp sign-in and returns.
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

      {/* The price, in /anew/'s own treatment: just the amount, no extra copy. While on the ₹1
          placeholder this reads ₹1.00; it becomes the product's real price the moment its config
          entry is added. */}
      <p className="pbb-buy">
        <span className="pbb-price" data-wc-no-translate="true">{ line.formattedPrice }</span>
      </p>

      { error && <p className="pbb-error" role="alert">{ error }</p> }

      <style jsx>{`
        /* Secondary pill under the WhatsApp CTA — identical treatment to ServiceBuyBox so the two
           families match: white fill, 2px #1a3a2a edge and type, lime #d1f470 hover with the house
           lift, reduced-motion aware. */
        .pbb{display:flex;flex-direction:column;align-items:flex-start;gap:0;margin-top:12px}
        .pbb-cta{
          display:inline-flex;align-items:center;justify-content:center;min-height:52px;
          padding:0 26px;border:2px solid #1a3a2a;border-radius:50px;
          background:#fff;color:#1a3a2a;font-size:17px;font-weight:600;cursor:pointer;
          transition:background-color .2s,transform .2s,box-shadow .2s;
        }
        .pbb-cta:hover:not(:disabled){
          background:#d1f470;transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.12);
        }
        .pbb-cta:focus-visible{outline:3px solid #1a3a2a;outline-offset:3px}
        .pbb-cta:disabled{opacity:.5;cursor:default}

        .pbb-buy{display:flex;flex-wrap:wrap;align-items:baseline;gap:16px;margin:22px 0 0}
        .pbb-price{font-size:22px;font-weight:700;line-height:1.2;letter-spacing:-.25px;color:#1a3a2a;font-variant-numeric:tabular-nums}

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
function addProductLine ( line: ReturnType<typeof productCheckoutLine> ): CartItem[] {
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

// Re-exported so a quiet "in testing" note could be shown per page if ever wanted.
export { isPlaceholderCheckout };
