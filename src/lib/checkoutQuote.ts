/**
 * A read-only checkout quote from the authenticated ProductsTable pricing path.
 * Catalogue display prices are NEVER a financial source of truth.
 */
export interface CheckoutQuoteItem {
  name: string;
  quantity: number;
  unitPricePaise: number;
  totalPaise: number;
}
export interface CheckoutQuoteCharges {
  merchandisePaise: number;
  supplyGstPaise: number;
  deliveryPaise: number;
  discountPaise: number;
  convenienceFeePaise: number;
  convenienceGstPaise: number;
  totalPaise: number;
  discountLabel?: string;
}
export interface CheckoutQuote {
  currency: 'INR';
  items: CheckoutQuoteItem[];
  charges: CheckoutQuoteCharges;
}

const wholePaise = ( value: unknown ): value is number =>
  typeof value === 'number' && Number.isSafeInteger( value ) && value >= 0;

/** Reject incomplete, negative or non-reconciling price summaries. */
export function parseCheckoutQuote ( body: unknown ): CheckoutQuote | null {
  if ( !body || typeof body !== 'object' ) return null;
  const payload = body as { status?: unknown; quote?: unknown };
  if ( payload.status !== 'QUOTE_READY' || !payload.quote
      || typeof payload.quote !== 'object' ) return null;
  const quote = payload.quote as { currency?: unknown; items?: unknown; charges?: unknown };
  if ( quote.currency !== 'INR' || !Array.isArray( quote.items )
      || quote.items.length < 1 || quote.items.length > 100
      || !quote.charges || typeof quote.charges !== 'object' ) return null;
  const items: CheckoutQuoteItem[] = [];
  for ( const item of quote.items ) {
    if ( !item || typeof item !== 'object' ) return null;
    const row = item as Record<string, unknown>;
    if ( typeof row.name !== 'string' || !row.name.trim()
        || !wholePaise( row.unitPricePaise ) || !wholePaise( row.totalPaise )
        || !wholePaise( row.quantity ) || row.quantity < 1
        || row.totalPaise !== row.unitPricePaise * row.quantity ) return null;
    items.push( { name: row.name.slice( 0, 120 ), quantity: row.quantity,
      unitPricePaise: row.unitPricePaise, totalPaise: row.totalPaise } );
  }

  const c = quote.charges as Record<string, unknown>;
  const keys = [ 'merchandisePaise', 'supplyGstPaise', 'deliveryPaise',
    'discountPaise', 'convenienceFeePaise', 'convenienceGstPaise',
    'totalPaise' ] as const;
  if ( keys.some( key => !wholePaise( c[ key ] ) ) ) return null;
  const charges = Object.fromEntries( keys.map( key => [ key, c[ key ] ] ) )
    as unknown as CheckoutQuoteCharges;
  const merchandise = items.reduce( ( sum, item ) => sum + item.totalPaise, 0 );
  if ( !Number.isSafeInteger( merchandise )
      || merchandise !== charges.merchandisePaise
      || charges.totalPaise < 1
      || merchandise + charges.supplyGstPaise + charges.deliveryPaise
        - charges.discountPaise + charges.convenienceFeePaise
        + charges.convenienceGstPaise !== charges.totalPaise ) return null;
  if ( typeof c.discountLabel === 'string' ) {
    charges.discountLabel = c.discountLabel.slice( 0, 70 );
  }
  return { currency: 'INR', items, charges };
}
