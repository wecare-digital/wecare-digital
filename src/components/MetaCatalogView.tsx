import { useEffect } from 'react';

import { trackMetaViewContent } from '../lib/metaPixel';

interface MetaCatalogViewProps {
  productId: string;
  variantId: string;
  name: string;
  value?: number;
  currency?: string;
}

/** View-only Meta catalog tracker for current catalog pages that do not expose checkout here. */
export default function MetaCatalogView ( {
  productId,
  variantId,
  name,
  value,
  currency = 'INR',
}: MetaCatalogViewProps ): null {
  useEffect( () => {
    trackMetaViewContent( { productId, variantId, name, value, currency } );
  }, [ productId, variantId, name, value, currency ] );
  return null;
}
