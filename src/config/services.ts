/**
 * WECARE.DIGITAL SERVICES, IN ONE PLACE - Submit Request and Request Amendment, with a single
 * definition so no amount or variant GUID is re-typed anywhere else.
 *
 * Mirrors src/config/contribution.ts's shape on purpose: a service is bought exactly the way a
 * contribution is - ONE fixed-price variant of ONE Wix product, added to the existing cart at
 * quantity 1 and paid on the one live checkout path (`POST /ecommerce/prepare-checkout`). There is
 * no second payment implementation for a service.
 *
 * THE SERVER IS THE AUTHORITY. Nothing declared here is treated as approved to charge. The
 * browser names a CHOICE; `cart_v2.calculate` prices the line, and the server asserts that line
 * against its OWN committed copy of these figures
 * (amplify/functions/shared/lambda_utils/ecommerce/service_requests.py, SERVICE_CHOICES_PAISE), so
 * a Wix price edit refuses the purchase rather than charging a figure this page did not promise.
 * tests/test_service_requests.py fails if the two declarations drift.
 *
 * PRICING IS ORDINARY ORDER PRICING. Unlike a contribution, a service is NOT fee-exempt: the
 * checkout adds the same convenience fee and GST on that fee as any order, which is why the page
 * says "a convenience fee is added at checkout" beside the ₹99.
 *
 * O-1 OFFERS TWO SERVICES. Drop Docs and Vault are variants of the same Wix product and belong to
 * a later phase; they are listed in NOT_OFFERED_SERVICE_VARIANT_IDS only so a drift test and the
 * cart guard can name them. Nothing in the UI offers them, and the server refuses them.
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

export type ServiceKind = 'SUBMIT_REQUEST' | 'REQUEST_AMENDMENT';

/** One purchasable service: its kind, the Wix variant it buys, its label and its line price. */
export interface ServiceChoice {
  readonly kind: ServiceKind;
  /** The Wix variant id. This is what travels in the cart line's `catalogReference.options`. */
  readonly variantId: string;
  /** The label on the page and the cart row. */
  readonly label: string;
  /** Whole rupees, for display only. */
  readonly rupees: number;
  /** The same amount in integer paise, the unit the server and the money core speak. */
  readonly paise: number;
  /** The page a customer buys this service from. */
  readonly path: string;
}

/** THE ONLY TWO SERVICES THAT CAN BE BOUGHT IN THIS PHASE. */
export const SERVICE_CHOICES: readonly ServiceChoice[] = [
  {
    kind: 'SUBMIT_REQUEST', variantId: 'e9f0eb8b-ca76-4b4f-b00c-be909c02bb2b',
    label: 'Submit Request', rupees: 99, paise: 9900, path: '/submit-request/',
  },
  {
    kind: 'REQUEST_AMENDMENT', variantId: '864fc9a7-c326-4b4d-b0e5-6dc0ea5b764b',
    label: 'Request Amendment', rupees: 99, paise: 9900, path: '/request-amendment/',
  },
] as const;

/**
 * Variants of the services product that are NOT offered in this phase (Drop Docs, Vault).
 * Referenced only by the drift test and the cart guard - never rendered as a choice.
 */
export const NOT_OFFERED_SERVICE_VARIANT_IDS: readonly string[] = [
  'db166bc8-a763-41ec-9f65-0f718f18155a', // Drop Docs
  'dcff995e-448c-493a-9259-f6a82ccdc2b4', // Vault
] as const;

/** The service a variant id names, or null when it names neither of the two. */
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
