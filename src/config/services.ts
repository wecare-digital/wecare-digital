/** Fresh SKU-first service catalog configuration. */
const TESTING = process.env.NODE_ENV === 'test';

export const SERVICES_CURRENCY = 'INR' as const;
export const SERVICES_PRODUCT_ID: string =
  TESTING ? '11111111-1111-4111-8111-111111111111' : '';
/** Legacy option-group symbol retained only for synthetic tests; fresh live services are separate products. */
export const SERVICES_OPTION_ID: string =
  TESTING ? '10101010-1010-4010-8010-101010101010' : '';

export type ServiceKind =
  'SUBMIT_REQUEST' | 'REQUEST_AMENDMENT' | 'DROP_DOCS' | 'VAULT' | 'REQUEST_PICKUP';
export type ServiceSlug =
  'submit-request' | 'request-amendment' | 'drop-docs' | 'vault' | 'request-pickup';

export interface ServiceChoice {
  readonly kind: ServiceKind;
  readonly productId: string;
  readonly variantId: string;
  readonly label: string;
  readonly slug: ServiceSlug;
  readonly path: string;
  readonly needsTarget: boolean;
  readonly choiceId: string;
  readonly sku: string;
}

const TEST_SERVICE_CHOICES: readonly ServiceChoice[] = [
  { kind:'SUBMIT_REQUEST', productId:SERVICES_PRODUCT_ID, variantId:'22222222-2222-4222-8222-222222222222', label:'Submit Request', slug:'submit-request', path:'/workspace/service?view=requests', needsTarget:true, choiceId:'21212121-2121-4121-8121-212121212121', sku:'TEST-SUBMIT' },
  { kind:'REQUEST_AMENDMENT', productId:SERVICES_PRODUCT_ID, variantId:'33333333-3333-4333-8333-333333333333', label:'Request Amendment', slug:'request-amendment', path:'/workspace/service?view=requests', needsTarget:true, choiceId:'31313131-3131-4131-8131-313131313131', sku:'TEST-AMEND' },
  { kind:'DROP_DOCS', productId:SERVICES_PRODUCT_ID, variantId:'44444444-4444-4444-8444-444444444444', label:'Drop Docs', slug:'drop-docs', path:'/workspace/service?view=requests', needsTarget:true, choiceId:'41414141-4141-4141-8141-414141414141', sku:'TEST-DROP' },
  { kind:'VAULT', productId:SERVICES_PRODUCT_ID, variantId:'55555555-5555-4555-8555-555555555555', label:'Vault', slug:'vault', path:'/workspace/payments?view=vault', needsTarget:true, choiceId:'51515151-5151-4151-8151-515151515151', sku:'TEST-VAULT' },
  { kind:'REQUEST_PICKUP', productId:SERVICES_PRODUCT_ID, variantId:'66666666-6666-4666-8666-666666666666', label:'Request Pickup', slug:'request-pickup', path:'/workspace/service?view=requests', needsTarget:true, choiceId:'61616161-6161-4161-8161-616161616161', sku:'TEST-PICKUP' },
];

const LIVE_SERVICE_CHOICES: readonly ServiceChoice[] = [
  { kind:'SUBMIT_REQUEST', productId:'f829697a-b1db-5c4e-bfce-51d1487278a7', variantId:'RSR7M2P9', label:'Submit Request', slug:'submit-request', path:'/workspace/service?view=requests', needsTarget:true, choiceId:'RSR7M2P9', sku:'RSR7M2P9' },
  { kind:'REQUEST_AMENDMENT', productId:'7133c98d-de8d-5e56-94ff-8d9fea7aa331', variantId:'RAM5Q8K4', label:'Request Amendment', slug:'request-amendment', path:'/workspace/service?view=requests', needsTarget:true, choiceId:'RAM5Q8K4', sku:'RAM5Q8K4' },
  { kind:'DROP_DOCS', productId:'e1ca7833-5d7d-567b-837c-face04647598', variantId:'RDD9P3M7', label:'Drop Docs', slug:'drop-docs', path:'/workspace/service?view=requests', needsTarget:true, choiceId:'RDD9P3M7', sku:'RDD9P3M7' },
  { kind:'VAULT', productId:'d4cfc6e8-10b3-5c47-94c8-3c69f4c03907', variantId:'RVT6K4Q8', label:'Vault', slug:'vault', path:'/workspace/payments?view=vault', needsTarget:true, choiceId:'RVT6K4Q8', sku:'RVT6K4Q8' },
  { kind:'REQUEST_PICKUP', productId:'166370fe-69a8-5ad2-9f9a-e9ce3f92839c', variantId:'SHP7Q4N9', label:'Request Pickup', slug:'request-pickup', path:'/workspace/service?view=requests', needsTarget:true, choiceId:'SHP7Q4N9', sku:'SHP7Q4N9' },
];

export const SERVICE_CHOICES: readonly ServiceChoice[] =
  TESTING ? TEST_SERVICE_CHOICES : LIVE_SERVICE_CHOICES;
export const SERVICE_PRODUCT_IDS: ReadonlySet<string> =
  new Set( SERVICE_CHOICES.map( choice => choice.productId ) );
export const NOT_OFFERED_SERVICE_VARIANT_IDS: readonly string[] = [];

export const serviceChoice = ( variantId: unknown ): ServiceChoice | null =>
  SERVICE_CHOICES.find( choice => choice.variantId === String( variantId || '' ).trim() ) || null;
export const serviceByKind = ( kind: unknown ): ServiceChoice | null =>
  SERVICE_CHOICES.find( choice => choice.kind === kind ) || null;
export const SERVICES_CONFIGURED = SERVICE_CHOICES.length === 5;
