/** Fresh SKU-first service catalog configuration.
 *
 * The previous Request product and variant GUIDs were retired with the old catalog.
 * Public service pages remain available, but no retired catalog identity is offerable.
 */

export const SERVICES_CURRENCY = 'INR' as const;
export const SERVICES_PRODUCT_ID: string = '';
export const SERVICES_OPTION_ID: string = '';

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

/** No legacy service catalog line is active. Fresh 8-character SKUs will be added next. */
export const SERVICE_CHOICES: readonly ServiceChoice[] = [];

export const NOT_OFFERED_SERVICE_VARIANT_IDS: readonly string[] = [];

export const serviceChoice = ( variantId: unknown ): ServiceChoice | null =>
  SERVICE_CHOICES.find(
    choice => choice.variantId === String( variantId || '' ).trim().toLowerCase(),
  ) || null;

export const serviceByKind = ( kind: unknown ): ServiceChoice | null =>
  SERVICE_CHOICES.find( choice => choice.kind === kind ) || null;

export const SERVICES_CONFIGURED = false;
