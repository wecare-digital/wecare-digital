/**
 * WECARE.DIGITAL SERVICES, IN ONE PLACE - Submit Request, Request Amendment, Drop Docs and Vault,
 * with a single definition so no amount or variant GUID is re-typed anywhere else.
 *
 * Mirrors src/config/contribution.ts's shape on purpose: a service is bought exactly the way a
 * contribution is - ONE fixed-price variant of ONE Wix product, added to the existing cart at
 * quantity 1 and paid on the one live checkout path (`POST /ecommerce/prepare-checkout`). There is
 * no second payment implementation for a service.
 *
 * NO PRICE IS DECLARED HERE, SINCE 2026-10-08. Owner decision: "price 49 or 99 can change any
 * time so make dynamic". Each page reads its own variant's LIVE Wix price from
 * `GET /ecommerce/service-prices` (src/lib/servicePricing.ts), so a price edited in Wix appears
 * on the page within about a minute with no deploy. What survives here is stable catalogue
 * IDENTITY — which variant each service buys — which is exactly the part that does not change
 * when a price does.
 *
 * THE SERVER IS STILL THE AUTHORITY, and now so is Wix. The browser names a CHOICE;
 * `cart_v2.calculate` prices the line and
 * amplify/functions/shared/lambda_utils/ecommerce/service_requests.py asserts WIX'S OWN line
 * price inside a wide catastrophe rail rather than against a committed figure — so a Wix price
 * edit is CHARGED instead of refusing the purchase, which is what it used to do.
 * tests/test_service_requests.py fails if the two declarations drift.
 *
 * PRICING IS ORDINARY ORDER PRICING. Unlike a contribution, a service is NOT fee-exempt: the
 * checkout adds the same convenience fee and GST on that fee as any order, which is why each page
 * says "a convenience fee is added at checkout" beside its amount.
 *
 * FOUR SERVICES ARE OFFERED, all four variants of the one Wix product.
 * NOT_OFFERED_SERVICE_VARIANT_IDS is therefore EMPTY - it is kept, with the cart guard and the
 * drift test that read it, so the NEXT variant added in Wix can be refused by name rather than
 * sold as an ordinary product line.
 *
 * THREE OF THE FOUR NEED A TARGET REQUEST (`needsTarget`): an amendment amends one, Drop Docs
 * sends documents for a request already under way, and Vault asks for a copy of a document held
 * against one. The server owns that rule (service_requests.py TARGET_REQUIRED_KINDS); this flag
 * only decides whether the buy box asks which request before calling for an intent.
 *
 * NO `NEXT_PUBLIC_*` OVERRIDE, for the reason contribution.ts records: a browser-only id change
 * would send a reference the server does not recognise as a service.
 */

/** The only currency services are taken in. */
export const SERVICES_CURRENCY = 'INR' as const;

/**
 * The Wix catalogue product `WECARE.DIGITAL Services` (PHYSICAL in Wix, four variants). The
 * `: string` annotation is load-bearing for the same reason as CONTRIBUTION_PRODUCT_ID's.
 */
export const SERVICES_PRODUCT_ID: string = 'df976a0a-f582-4535-b2e1-d532f348bd27';

export type ServiceKind = 'SUBMIT_REQUEST' | 'REQUEST_AMENDMENT' | 'DROP_DOCS' | 'VAULT';

/** The four public page slugs. The key the live-price payload is read by. */
export type ServiceSlug = 'submit-request' | 'request-amendment' | 'drop-docs' | 'vault';

/** One purchasable service: its kind, the Wix variant it buys, its label and its page. NO PRICE. */
export interface ServiceChoice {
  readonly kind: ServiceKind;
  /** The Wix variant id. This is what travels in the cart line's `catalogReference.options`. */
  readonly variantId: string;
  /** The label on the page and the cart row. */
  readonly label: string;
  /**
   * The slug this service's live price is published under, mirroring the server's
   * SERVICE_KIND_BY_SLUG. Each page reads ITS OWN slug, which is what keeps four pages showing
   * four prices rather than one.
   */
  readonly slug: ServiceSlug;
  /** The page a customer buys this service from. */
  readonly path: string;
  /** Does this service need a target Submit Request of the caller's own? */
  readonly needsTarget: boolean;
}

/** THE ONLY FOUR SERVICES THAT CAN BE BOUGHT. */
export const SERVICE_CHOICES: readonly ServiceChoice[] = [
  {
    kind: 'SUBMIT_REQUEST', variantId: 'e9f0eb8b-ca76-4b4f-b00c-be909c02bb2b',
    label: 'Submit Request', slug: 'submit-request', path: '/submit-request/',
    needsTarget: false,
  },
  {
    kind: 'REQUEST_AMENDMENT', variantId: '864fc9a7-c326-4b4d-b0e5-6dc0ea5b764b',
    label: 'Request Amendment', slug: 'request-amendment', path: '/request-amendment/',
    needsTarget: true,
  },
  {
    kind: 'DROP_DOCS', variantId: 'db166bc8-a763-41ec-9f65-0f718f18155a',
    label: 'Drop Docs', slug: 'drop-docs', path: '/drop-docs/',
    needsTarget: true,
  },
  {
    kind: 'VAULT', variantId: 'dcff995e-448c-493a-9259-f6a82ccdc2b4',
    label: 'Vault', slug: 'vault', path: '/vault/',
    needsTarget: true,
  },
] as const;

/**
 * Variants of the services product that are NOT offered. EMPTY: all four are offered. Referenced
 * only by the drift test and the cart guard, and kept so the next Wix variant can be named here
 * and refused rather than sold.
 */
export const NOT_OFFERED_SERVICE_VARIANT_IDS: readonly string[] = [] as const;

/** The service a variant id names, or null when it names none of the four. */
export const serviceChoice = ( variantId: unknown ): ServiceChoice | null =>
  SERVICE_CHOICES.find(
    choice => choice.variantId === String( variantId || '' ).trim().toLowerCase() ) || null;

/** The service of a kind, or null. */
export const serviceByKind = ( kind: unknown ): ServiceChoice | null =>
  SERVICE_CHOICES.find( choice => choice.kind === kind ) || null;

/** Is a service offerable by this build at all? */
export const SERVICES_CONFIGURED: boolean =
  !!SERVICES_PRODUCT_ID && SERVICE_CHOICES.length > 0
  && SERVICE_CHOICES.every( choice => !!choice.variantId );
