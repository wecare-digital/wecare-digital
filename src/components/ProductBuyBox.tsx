import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/router';

import { addItem, type CartItem } from '../lib/cart';
import type { ShopProduct } from '../content/shop';
import { CHECKOUT_PATH } from '../lib/serviceEntry';
import { productCheckoutLine } from '../config/productCheckout';
import CheckoutAction from './CheckoutAction';
import PublicNotice from './public/PublicNotice';
import { rupeesFromFormattedPrice, trackMetaAddToCart, trackMetaViewContent } from '../lib/metaPixel';

/**
 * THE PRODUCT CHECKOUT ACTION.
 *
 * Product routes expose one compact Checkout action only. It adds the authoritative catalogue
 * identity to the browser cart and moves to /checkout/. The customer reviews one selected product
 * and chooses Pay here or Pay on WhatsApp directly in that cart, without another chooser page.
 *
 * No sign-in happens on the product route and no display price is sent to checkout. The server
 * remains the price authority.
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
  useEffect( () => () => { alive.current = false; }, [] );

  const line = productCheckoutLine( slug );

  useEffect( () => {
    if ( !line ) return;
    trackMetaViewContent( {
      productId: line.productId,
      variantId: line.variantId,
      name: line.name,
      value: rupeesFromFormattedPrice( line.formattedPrice ),
      currency: 'INR',
    } );
  }, [ line ] );

  const onContinue = useCallback( async () => {
    if ( !line || busy ) return;
    setError( null );
    setBusy( true );
    try {
      addProductLine( line );
      trackMetaAddToCart( {
        productId: line.productId,
        variantId: line.variantId,
        name: line.name,
        value: rupeesFromFormattedPrice( line.formattedPrice ),
        currency: 'INR',
      } );
      await router.push( CHECKOUT_PATH );
    } catch {
      if ( alive.current ) {
        setError( 'Checkout could not start. No charge made. Try again.' );
        setBusy( false );
      }
    }
  }, [ busy, router, line ] );

  // No fresh catalog line yet: keep the public product page, but offer no stale checkout action.
  if ( !line ) return null;

  return (
    <div className="pbb">
      <CheckoutAction
        onClick={ () => { void onContinue(); } }
        disabled={ busy }
        busy={ busy }
      >
        { busy ? 'One moment…' : 'Checkout' }
      </CheckoutAction>

      {/* Configured price and one supporting line are one canonical rail. */}
      <p className="pbb-buy">
        <span className="pbb-price" data-wc-no-translate="true">{ displayPrice ?? line.formattedPrice }</span>
      </p>
      <p className="pbb-offer-note">{ offerNote }</p>

      { error && <PublicNotice mode="inline" tone="error" message={ error } /> }

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

      `}</style>
    </div>
  );
};

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
