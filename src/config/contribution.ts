/** Voluntary contribution catalog configuration.
 *
 * Production stays empty until the fresh SKU-first Contribute item is created. Tests receive one
 * synthetic choice so cart/contribution behavior remains covered without any retired identity.
 */

const TESTING = process.env.NODE_ENV === 'test';

export const CONTRIBUTION_CURRENCY = 'INR' as const;
export const CONTRIBUTE_CTA_HREF = 'https://wa.me/message/BYFLCAAMSZBXD1';
export const CONTRIBUTION_PRODUCT_ID: string =
  TESTING ? '77777777-7777-4777-8777-777777777777' : '24fa0f39-330b-5365-b7eb-9caf27ad37f1';

export interface ContributionChoice {
  readonly variantId: string;
  readonly rupees: number;
  readonly paise: number;
}

const TEST_CONTRIBUTION_CHOICES: readonly ContributionChoice[] = [
  { variantId:'7a7a7a7a-7a7a-47a7-87a7-7a7a7a7a7a7a', rupees:250, paise:25000 },
];

const LIVE_CONTRIBUTION_CHOICES: readonly ContributionChoice[] = [
  { variantId:'CNT5Q2M8', rupees:250, paise:25000 },
];

export const CONTRIBUTION_CHOICES: readonly ContributionChoice[] =
  TESTING ? TEST_CONTRIBUTION_CHOICES : LIVE_CONTRIBUTION_CHOICES;
export const CONTRIBUTION_AMOUNT_LABEL = '₹250';
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
