/**
 * COMMON CONTRIBUTION AMOUNTS
 * ---------------------------
 * Blog posts and VayuLok use the same three contribution choices from this module. The browser
 * never invents or widens an amount: it sends one of these integer-paise values and the backend
 * independently mirrors this exact allow-list before any payable order can be created.
 *
 * Keep this file and
 * amplify/functions/shared/lambda_utils/ecommerce/blog_contribution.py::CONTRIBUTION_PRESETS_PAISE
 * in sync. tests/test_blog_contribution.py pins the backend copy to this public contract.
 */

/** The only currency contributions are taken in. */
export const CONTRIBUTION_CURRENCY = 'INR' as const;

/** Common choices: ₹100 / ₹250 / ₹500, stored canonically as integer paise. */
export const CONTRIBUTION_PRESETS_PAISE: readonly number[] = [ 10000, 25000, 50000 ] as const;

/** One hundred paise to the rupee. */
export const PAISE_PER_RUPEE = 100;

/** Convert an integer-paise amount to the whole-rupee label used by the preset buttons. */
export const paiseToRupees = ( paise: number ): number => Math.floor( paise / PAISE_PER_RUPEE );

/** The purpose tag the backend keys a blog contribution under. */
export const CONTRIBUTION_PURPOSE = 'BLOG_CONTRIBUTION' as const;
