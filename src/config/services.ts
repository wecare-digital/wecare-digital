/**
 * WECARE.DIGITAL SERVICES, IN ONE PLACE - Submit Request, Request Amendment, Drop Docs, Vault and
 * Request Pickup, with a single definition so no amount or variant GUID is re-typed anywhere else.
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
 * FIVE SERVICES ARE OFFERED, all five variants of the one Wix product. Request Pickup joined on
 * 2026-10-10, when the live Wix storefront began returning it visible and in stock and
 * src/content/wix-catalog.json was refreshed from that read.
 * NOT_OFFERED_SERVICE_VARIANT_IDS is therefore EMPTY - it is kept, with the cart guard and the
 * drift test that read it, so the NEXT variant added in Wix can be refused by name rather than
 * sold as an ordinary product line.
 *
 * WHICH ID MEANS WHAT. `variantId` stays the primary cart reference - it is the value that travels
 * in `catalogReference.options` and the one the server's allow-list keys on. `choiceId` and `sku`
 * are REFERENCE METADATA ONLY: they are carried so this declaration matches the Wix snapshot
 * without a second hand-typed copy of the catalogue, and nothing in the payment path reads them.
 * Every one of them is read out of src/content/wix-catalog.json, which `fetch-wix-catalog.js`
 * writes from Wix itself.
 *
 * FOUR OF THE FIVE NEED A TARGET REQUEST (`needsTarget`): an amendment amends one, Drop Docs
 * sends documents for a request already under way, Vault asks for a copy of a document held
 * against one, and a pickup collects documents for one. The server owns that rule
 * (service_requests.py TARGET_REQUIRED_KINDS); this flag only decides whether the buy box asks
 * which request before calling for an intent.
 *
 * NO `NEXT_PUBLIC_*` OVERRIDE, for the reason contribution.ts records: a browser-only id change
 * would send a reference the server does not recognise as a service.
 */

/** The only currency services are taken in. */
export const SERVICES_CURRENCY = 'INR' as const;

/**
 * The Wix catalogue product `Request` (PHYSICAL in Wix, five variants). It was named
 * `WECARE.DIGITAL Services` until Wix renamed it on 2026-10-10; the slug is unchanged at
 * `wecaredigital-services`, so no URL moved with the rename. The `: string` annotation is
 * load-bearing for the same reason as CONTRIBUTION_PRODUCT_ID's.
 */
export const SERVICES_PRODUCT_ID: string = 'df976a0a-f582-4535-b2e1-d532f348bd27';

/**
 * The product's single main option (`Service`), which every `choiceId` below belongs to. ONE
 * const rather than a per-entry field, because all five variants share it - a second copy on each
 * entry would be five chances to mistype the same value.
 */
export const SERVICES_OPTION_ID: string = 'aee30ab6-72bd-4a04-ac83-0234652ad0ee';

export type ServiceKind =
  'SUBMIT_REQUEST' | 'REQUEST_AMENDMENT' | 'DROP_DOCS' | 'VAULT' | 'REQUEST_PICKUP';

/** The five public page slugs. The key the live-price payload is read by. */
export type ServiceSlug =
  'submit-request' | 'request-amendment' | 'drop-docs' | 'vault' | 'request-pickup';

/** One purchasable service: its kind, the Wix variant it buys, its label and its page. NO PRICE. */
export interface ServiceChoice {
  readonly kind: ServiceKind;
  /** The Wix variant id. This is what travels in the cart line's `catalogReference.options`. */
  readonly variantId: string;
  /** The label on the page and the cart row. */
  readonly label: string;
  /**
   * The slug this service's live price is published under, mirroring the server's
   * SERVICE_KIND_BY_SLUG. Each page reads ITS OWN slug, which is what keeps five pages showing
   * five prices rather than one.
   */
  readonly slug: ServiceSlug;
  /** The page a customer buys this service from. */
  readonly path: string;
  /** Does this service need a target Submit Request of the caller's own? */
  readonly needsTarget: boolean;
  /**
   * The Wix option-choice id of this service within SERVICES_OPTION_ID. Additive metadata that
   * mirrors the snapshot; the cart still travels on `variantId`.
   */
  readonly choiceId: string;
  /** The Wix variant SKU, as the snapshot reports it. Reference metadata, never a lookup key. */
  readonly sku: string;
}

/** THE ONLY FIVE SERVICES THAT CAN BE BOUGHT. */
export const SERVICE_CHOICES: readonly ServiceChoice[] = [
  {
    kind: 'SUBMIT_REQUEST', variantId: 'e9f0eb8b-ca76-4b4f-b00c-be909c02bb2b',
    label: 'Submit Request', slug: 'submit-request', path: '/submit-request/',
    needsTarget: false,
    choiceId: '2af81a87-24a8-4729-80bf-1d967a637bc2', sku: 'SERVICE-SUBMIT-REQUEST',
  },
  {
    kind: 'REQUEST_AMENDMENT', variantId: '864fc9a7-c326-4b4d-b0e5-6dc0ea5b764b',
    label: 'Request Amendment', slug: 'request-amendment', path: '/request-amendment/',
    needsTarget: true,
    choiceId: '7111e864-e789-4641-8f28-74240af61561', sku: 'SERVICE-REQUEST-AMENDMENT',
  },
  {
    kind: 'DROP_DOCS', variantId: 'db166bc8-a763-41ec-9f65-0f718f18155a',
    label: 'Drop Docs', slug: 'drop-docs', path: '/drop-docs/',
    needsTarget: true,
    choiceId: 'f981b729-748a-48ee-93b9-54ecc543b617', sku: 'SERVICE-DROP-DOCS',
  },
  {
    kind: 'VAULT', variantId: 'dcff995e-448c-493a-9259-f6a82ccdc2b4',
    label: 'Vault', slug: 'vault', path: '/vault/',
    needsTarget: true,
    choiceId: 'bdaafdcf-7998-4d43-b7dd-1ab40cc6566c', sku: 'SERVICE-VAULT',
  },
  {
    kind: 'REQUEST_PICKUP', variantId: '8ee7e325-d772-4452-a993-5c79e927d42b',
    label: 'Request Pickup', slug: 'request-pickup', path: '/request-pickup/',
    needsTarget: true,
    choiceId: 'faa3b648-1fba-41ad-a5f2-f84bd2524070', sku: 'SERVICE-REQUEST-PICKUP',
  },
] as const;

/**
 * Variants of the services product that are NOT offered. EMPTY: all five are offered. Referenced
 * only by the drift test and the cart guard, and kept so the next Wix variant can be named here
 * and refused rather than sold.
 */
export const NOT_OFFERED_SERVICE_VARIANT_IDS: readonly string[] = [] as const;

/** The service a variant id names, or null when it names none of the five. */
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
