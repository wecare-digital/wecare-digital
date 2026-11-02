/** Fresh SKU-first service catalog configuration. */
export const SERVICES_CURRENCY = 'INR' as const;
export const SERVICES_PRODUCT_ID: string = '';
/** Legacy-compatible option-group symbol; live services are separate products. */
export const SERVICES_OPTION_ID: string = '';

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

export const SERVICE_CHOICES: readonly ServiceChoice[] = [
  { kind:'SUBMIT_REQUEST', productId:'f829697a-b1db-5c4e-bfce-51d1487278a7', variantId:'RSR7M2P9', label:'Submit Request', slug:'submit-request', path:'/workspace/service?view=requests', needsTarget:true, choiceId:'RSR7M2P9', sku:'RSR7M2P9' },
  { kind:'REQUEST_AMENDMENT', productId:'7133c98d-de8d-5e56-94ff-8d9fea7aa331', variantId:'RAM5Q8K4', label:'Request Amendment', slug:'request-amendment', path:'/workspace/service?view=requests', needsTarget:true, choiceId:'RAM5Q8K4', sku:'RAM5Q8K4' },
  { kind:'DROP_DOCS', productId:'e1ca7833-5d7d-567b-837c-face04647598', variantId:'RDD9P3M7', label:'Drop Docs', slug:'drop-docs', path:'/workspace/service?view=requests', needsTarget:true, choiceId:'RDD9P3M7', sku:'RDD9P3M7' },
  { kind:'VAULT', productId:'d4cfc6e8-10b3-5c47-94c8-3c69f4c03907', variantId:'RVT6K4Q8', label:'Vault', slug:'vault', path:'/workspace/payments?view=vault', needsTarget:true, choiceId:'RVT6K4Q8', sku:'RVT6K4Q8' },
  { kind:'REQUEST_PICKUP', productId:'166370fe-69a8-5ad2-9f9a-e9ce3f92839c', variantId:'SHP7Q4N9', label:'Request Pickup', slug:'request-pickup', path:'/workspace/service?view=requests', needsTarget:true, choiceId:'SHP7Q4N9', sku:'SHP7Q4N9' },
];

export const SERVICE_PRODUCT_IDS: ReadonlySet<string> =
  new Set( SERVICE_CHOICES.map( choice => choice.productId ) );
export const NOT_OFFERED_SERVICE_VARIANT_IDS: readonly string[] = [];

export const serviceChoice = ( variantId: unknown ): ServiceChoice | null =>
  SERVICE_CHOICES.find( choice => choice.variantId === String( variantId || '' ).trim() ) || null;
export const serviceByKind = ( kind: unknown ): ServiceChoice | null =>
  SERVICE_CHOICES.find( choice => choice.kind === kind ) || null;
export const SERVICES_CONFIGURED = SERVICE_CHOICES.length === 5;
