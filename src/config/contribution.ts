/** Live contribution configuration. Server-side ProductsTable remains the authoritative price source. */

export const CONTRIBUTION_CURRENCY = 'INR' as const;
export const CONTRIBUTE_CTA_HREF = 'https://wa.me/message/BYFLCAAMSZBXD1';
export const CONTRIBUTION_PRODUCT_ID: string = '24fa0f39-330b-5365-b7eb-9caf27ad37f1';

export interface ContributionChoice {
  readonly variantId: string;
  readonly rupees: number;
  readonly paise: number;
}

export const CONTRIBUTION_CHOICES: readonly ContributionChoice[] = [
  { variantId:'CNT5Q2M8', rupees:300, paise:30000 },
];

export const CONTRIBUTION_AMOUNT_LABEL = '₹300';
export const PAISE_PER_RUPEE = 100;

export const paiseToRupees = ( paise: number ): number =>
  Math.floor( paise / PAISE_PER_RUPEE );

export const contributionChoice = ( variantId: unknown ): ContributionChoice | null =>
  CONTRIBUTION_CHOICES.find(
    // Case-insensitive on BOTH sides: the live variantId is 'CNT5Q2M8' (mixed case), and the
    // old form lowercased only the input, so a lookup for the real variant never matched and the
    // website checkout silently wrote nothing. Normalise both ends so any casing resolves.
    choice => choice.variantId.toLowerCase() === String( variantId || '' ).trim().toLowerCase(),
  ) || null;

export const CONTRIBUTION_PURPOSE = 'BLOG_CONTRIBUTION' as const;
