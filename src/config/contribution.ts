/** Voluntary contribution catalog configuration.
 *
 * The previous contribution product was part of the retired catalog and is no longer offerable.
 * A fresh contribution product can be added later under the new SKU-first catalog.
 */

export const CONTRIBUTION_CURRENCY = 'INR' as const;
export const CONTRIBUTE_CTA_HREF = 'https://wa.me/message/BYFLCAAMSZBXD1';
export const CONTRIBUTION_PRODUCT_ID: string = '';

export interface ContributionChoice {
  readonly variantId: string;
  readonly rupees: number;
  readonly paise: number;
}

export const CONTRIBUTION_CHOICES: readonly ContributionChoice[] = [];
export const CONTRIBUTION_AMOUNT_LABEL = '';
export const PAISE_PER_RUPEE = 100;

export const paiseToRupees = ( paise: number ): number =>
  Math.floor( paise / PAISE_PER_RUPEE );

export const contributionChoice = ( variantId: unknown ): ContributionChoice | null =>
  CONTRIBUTION_CHOICES.find(
    choice => choice.variantId === String( variantId || '' ).trim().toLowerCase(),
  ) || null;

export const CONTRIBUTION_PURPOSE = 'BLOG_CONTRIBUTION' as const;
