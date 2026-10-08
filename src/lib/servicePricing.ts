/**
 * The browser client for the LIVE Wix price of each WECARE.DIGITAL service.
 *
 *   GET /ecommerce/service-prices  ->  { currency: 'INR', prices: { <slug>: ... } }
 *
 * WHY IT EXISTS. Owner decision 2026-10-08: a price must be changeable in Wix with no deploy, so
 * no figure is declared in the frontend any more (src/config/services.ts kept the variant ids and
 * dropped the amounts). The endpoint is anonymous and takes no input, because a visitor reads the
 * price BEFORE signing in — the price is what decides whether they sign in at all.
 *
 * IT FAILS CLOSED, AND THAT IS THE WHOLE DESIGN. Every rejection answers `{ available: false }`
 * for the affected slug, which the buy box renders as "This service may be temporarily
 * unavailable." with NO pay button. There is no fallback figure anywhere in this file: a page that
 * guesses a price offers a customer a number the checkout will not honour, which is worse than
 * not selling. Rejected outright: a network failure, a non-2xx, a currency that is not exactly
 * `INR`, a malformed payload, and a `paise` that is not a positive safe integer.
 *
 * NO FLOAT ARITHMETIC. `rupeesFromPaise` below is `Math.trunc` plus a modulo — the same
 * integer-only pattern `src/lib/paymentVocabulary.ts` records, and for the reason recorded there:
 * `formatters.formatCurrency` divides and calls `toFixed(2)`, which is the float path R6.1
 * forbids on the payment path. That function is not reused directly only because it always emits
 * two decimals (`99.00`), and the service card has always shown whole rupees (`₹99`); changing
 * what a customer reads is not this change's business. The arithmetic is identical.
 */

import { SERVICE_CHOICES, type ServiceSlug } from '../config/services';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api';

/** The one price endpoint. GET, no query string, no body. */
export const SERVICE_PRICES_URL = `${ API_BASE }/ecommerce/service-prices`;

/** The only currency a service is sold in. Compared explicitly, never inferred from an amount. */
export const SERVICES_PRICE_CURRENCY = 'INR' as const;

/** One service's live price, or an honest "no price". An unavailable price carries no number. */
export type ServicePrice =
  | { readonly available: true; readonly paise: number; readonly rupees: string }
  | { readonly available: false };

const UNAVAILABLE: ServicePrice = { available: false };

/**
 * Every slug unavailable. The answer to every failure, so no caller sees a partial shape.
 *
 * DERIVED FROM `SERVICE_CHOICES`, never re-typed. The four slugs were literalled here, which made
 * this the THIRD hand-typed copy of the vocabulary after `src/config/services.ts` and the
 * server's `service_requests.SERVICE_KIND_BY_SLUG`. Drift failed closed, so nothing would have
 * broken loudly — a fifth service would simply never have received a price, on a page that said
 * "temporarily unavailable" forever. Deriving it means adding a service to `SERVICE_CHOICES` is
 * all it takes, and `ServicePricing.test.ts` pins the equality either way.
 */
export const allUnavailable = (): Record<string, ServicePrice> =>
  Object.fromEntries( SERVICE_CHOICES.map( choice => [ choice.slug, UNAVAILABLE ] as const ) );

/**
 * `99`, `350`, `1,234.50`, `50,000` — whole rupees when the paise are zero, two decimals when
 * they are not, and the rupee part grouped Indian-style.
 *
 * Integer division and modulo only; the grouping is `toLocaleString('en-IN')` on the already
 * truncated WHOLE rupees, which is exactly what `src/lib/paymentVocabulary.ts` does and is not
 * arithmetic. Grouping matters now in a way it did not when the figure was fixed at 49/99/350:
 * the price is Wix's and the catastrophe rail admits up to ₹50,000, which read as `₹50000`.
 */
export function rupeesFromPaise ( paise: number ): string {
  const whole = Math.trunc( paise / 100 );
  const minor = paise % 100;
  const grouped = whole.toLocaleString( 'en-IN' );
  return minor === 0 ? grouped : `${ grouped }.${ String( minor ).padStart( 2, '0' ) }`;
}

/** Is this a `paise` we are willing to show a customer? Positive, integer, and safely exact. */
function usablePaise ( value: unknown ): value is number {
  return typeof value === 'number' && Number.isSafeInteger( value ) && value > 0;
}

function readPrice ( raw: unknown ): ServicePrice {
  if ( !raw || typeof raw !== 'object' ) return UNAVAILABLE;
  const row = raw as { available?: unknown; paise?: unknown };
  if ( row.available !== true ) return UNAVAILABLE;
  if ( !usablePaise( row.paise ) ) return UNAVAILABLE;
  return { available: true, paise: row.paise, rupees: rupeesFromPaise( row.paise ) };
}

/**
 * Every service's live price, keyed by slug. Never throws and never returns a partial map: on any
 * failure every slug is `{ available: false }`.
 *
 * A PER-SLUG failure from the server is preserved rather than widened — one service Wix cannot
 * price is no reason to take the other three off sale, which is the same rule the server applies.
 */
export async function fetchServicePrices (): Promise<Record<string, ServicePrice>> {
  try
  {
    const response = await fetch( SERVICE_PRICES_URL, {
      method: 'GET',
      headers: { Accept: 'application/json' },
    } );
    if ( !response.ok ) return allUnavailable();
    const data = ( await response.json().catch( () => null ) ) as
      { currency?: unknown; prices?: unknown } | null;
    if ( !data || data.currency !== SERVICES_PRICE_CURRENCY ) return allUnavailable();
    if ( !data.prices || typeof data.prices !== 'object' ) return allUnavailable();
    const prices = data.prices as Record<string, unknown>;
    const out = allUnavailable();
    for ( const slug of Object.keys( out ) as ServiceSlug[] )
    {
      out[ slug ] = readPrice( prices[ slug ] );
    }
    return out;
  }
  catch
  {
    return allUnavailable();
  }
}
