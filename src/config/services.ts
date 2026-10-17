/** Fresh SKU-first service catalog configuration.
 *
 * Production stays empty until the new catalog is created. Vitest receives synthetic identities
 * so generic cart/service behavior can be tested without preserving retired production UUIDs.
 */

const TESTING = process.env.NODE_ENV === 'test';

export const SERVICES_CURRENCY = 'INR' as const;
export const SERVICES_PRODUCT_ID: string =
  TESTING ? '11111111-1111-4111-8111-111111111111' : '';
export const SERVICES_OPTION_ID: string =
  TESTING ? '10101010-1010-4010-8010-101010101010' : '';

export type ServiceKind =
  'SUBMIT_REQUEST' | 'REQUEST_AMENDMENT' | 'DROP_DOCS' | 'VAULT' | 'REQUEST_PICKUP';

export type ServiceSlug =
  'submit-request' | 'request-amendment' | 'drop-docs' | 'vault' | 'request-pickup';

export interface ServiceChoice {
  readonly kind: ServiceKind;
  readonly variantId: string;
  readonly label: string;
  readonly slug: ServiceSlug;
  readonly path: string;
  readonly needsTarget: boolean;
  readonly choiceId: string;
  readonly sku: string;
}

const TEST_SERVICE_CHOICES: readonly ServiceChoice[] = [
  { kind:'SUBMIT_REQUEST', variantId:'22222222-2222-4222-8222-222222222222', label:'Submit Request',
    slug:'submit-request', path:'/submit-request/', needsTarget:false,
    choiceId:'21212121-2121-4121-8121-212121212121', sku:'TEST-SUBMIT' },
  { kind:'REQUEST_AMENDMENT', variantId:'33333333-3333-4333-8333-333333333333', label:'Request Amendment',
    slug:'request-amendment', path:'/request-amendment/', needsTarget:true,
    choiceId:'31313131-3131-4131-8131-313131313131', sku:'TEST-AMEND' },
  { kind:'DROP_DOCS', variantId:'44444444-4444-4444-8444-444444444444', label:'Drop Docs',
    slug:'drop-docs', path:'/drop-docs/', needsTarget:true,
    choiceId:'41414141-4141-4141-8141-414141414141', sku:'TEST-DROP' },
  { kind:'VAULT', variantId:'55555555-5555-4555-8555-555555555555', label:'Vault',
    slug:'vault', path:'/vault/', needsTarget:true,
    choiceId:'51515151-5151-4151-8151-515151515151', sku:'TEST-VAULT' },
  { kind:'REQUEST_PICKUP', variantId:'66666666-6666-4666-8666-666666666666', label:'Request Pickup',
    slug:'request-pickup', path:'/request-pickup/', needsTarget:true,
    choiceId:'61616161-6161-4161-8161-616161616161', sku:'TEST-PICKUP' },
];

/** Production is empty; synthetic test choices never ship in the export. */
export const SERVICE_CHOICES: readonly ServiceChoice[] = TESTING ? TEST_SERVICE_CHOICES : [];

export const NOT_OFFERED_SERVICE_VARIANT_IDS: readonly string[] = [];

export const serviceChoice = ( variantId: unknown ): ServiceChoice | null =>
  SERVICE_CHOICES.find(
    choice => choice.variantId === String( variantId || '' ).trim().toLowerCase(),
  ) || null;

export const serviceByKind = ( kind: unknown ): ServiceChoice | null =>
  SERVICE_CHOICES.find( choice => choice.kind === kind ) || null;

export const SERVICES_CONFIGURED = TESTING && SERVICE_CHOICES.length === 5;
