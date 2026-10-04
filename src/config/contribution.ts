/**
 * BLOG CONTRIBUTION CHOICES, IN ONE PLACE - the three "Contribute" amounts and the Wix variant
 * each one buys, with a single definition so no amount or GUID is re-typed.
 *
 * COMMON CONTRIBUTION AMOUNTS
 * ---------------------------
 * Blog posts and VayuLok use the same three contribution choices from this module. The browser
 * never invents or widens an amount: it names one of these CHOICES and the backend independently
 * mirrors this exact allow-list before any payable order can be created.
 *
 * WHY THIS FILE EXISTS
 * --------------------
 * The brief for the voluntary-contribution section on every blog post asks that the offered
 * amounts be "centrally configurable rather than duplicating hard-coded amounts throughout the
 * codebase". src/config/share.ts is the precedent for that shape: one config module imported where
 * needed, with a test (ShareMeta.test.tsx there, BlogContribution.test.tsx here) holding the
 * rendered values equal to the ones declared here so the two cannot drift. Everything that renders
 * a contribution amount - BlogContribution, the cart row, and their tests - reads THIS module.
 * Nothing re-states 100/250/500, 10000/25000/50000, 'INR' or a variant GUID anywhere else.
 *
 * CANONICAL UNIT IS INTEGER PAISE, NEVER RUPEES-AS-FLOAT
 * -----------------------------------------------------
 * The backend money core (amplify/functions/shared/lambda_utils/ecommerce/money.py and
 * checkout_pricing.py) is integer paise with Decimal rounding and refuses fractional paise, so the
 * two halves cannot be allowed to disagree about what "₹250" means. Each choice therefore carries
 * its paise figure, and the rupee number exists only as the display label. There is no arithmetic
 * on a customer-supplied number anywhere in this file: both figures are committed constants.
 *
 * THE SERVER IS THE AUTHORITY - this is the load-bearing security note.
 * ---------------------------------------------------------------------
 * Nothing declared here is ever treated as approved to charge. The browser names a CHOICE; the
 * server decides what that choice collects and Wix prices the line. `POST
 * /api/ecommerce/contribution` does not exist and is never built: a contribution is a product line
 * in the existing cart, paid on `POST /ecommerce/prepare-checkout`, and
 * `amplify/functions/ecommerce/checkout/handler.py:_contribution_request` re-derives the expected
 * collection from its OWN committed copy of the three choices before any Wix call or DynamoDB
 * write. `cart_v2.calculate` remains the sole price authority; no price, amount or currency is ever
 * sent from the browser.
 *
 * WHAT THE 2026-10-04 OWNER MODEL CHANGE REMOVED FROM THIS FILE
 * ------------------------------------------------------------
 * `CONTRIBUTION_PRESETS_PAISE`, `CONTRIBUTION_MIN_PAISE`, `CONTRIBUTION_MAX_PAISE`,
 * `isAllowedContributionPaise` and `rupeesToPaise` are gone, not relocated. They existed to police
 * a free-text custom amount; there is no custom amount any more, so there is nothing to police and
 * nothing to parse. Three fixed choices need a list and a label helper, and that is all that is
 * left here.
 */

/** The only currency contributions are taken in. */
export const CONTRIBUTION_CURRENCY = 'INR' as const;

/**
 * The Wix catalogue product id of the live `Contribute` product.
 *
 * ONE product with THREE fixed-price variants, measured against the live catalogue on 2026-10-04:
 * `PHYSICAL`, `visible: true`, one option named "Amount" rendered as text choices, three visible
 * in-stock variants at ₹100 / ₹250 / ₹500.
 *
 * THERE IS NO `NEXT_PUBLIC_*` OVERRIDE, and its removal is deliberate rather than an omission.
 * It was here as "a bridge for a window where the product id changes before this constant does",
 * and tracing that window shows the bridge cannot work and fails in the one direction that costs
 * the customer money:
 *
 *   - It could never work alone. The server recognises a contribution by the product id in its
 *     OWN committed set plus its `CONTRIBUTION_PRODUCT_ID` env key, and the three VARIANT ids
 *     below have no override at all - a different product has different variant ids, so pointing
 *     the browser at one would send a reference whose variants are not these three.
 *   - Set alone, the failure is SILENT and not fail-closed. The cart line carries a product the
 *     server does not recognise, so `_contribution_request` returns `None` and the basket is an
 *     ordinary one: `compute_quote` adds the 2.5% convenience fee and 18% GST, `requires_delivery`
 *     comes back true from `productType`, and the customer is sent to the address editor and
 *     charged more than the button offered. No guard fires, because nothing unusual happened from
 *     the server's point of view.
 *
 * Moving the product therefore means editing this constant and the three variants below together,
 * with the Lambda's `CONTRIBUTION_PRODUCT_ID` moved in the same release - which is a code change
 * either way, so a build-time env key bought nothing.
 *
 * The `: string` annotation is load-bearing, not noise: `shop.ts` and `cart.ts` guard on
 * `!!CONTRIBUTION_PRODUCT_ID` and the unconfigured-state tests stub it to `''`, both of which a
 * narrowed literal type would make nonsense of.
 */
export const CONTRIBUTION_PRODUCT_ID: string = 'af326b8c-f373-45ea-ad0d-b7a38b8ce0cc';

/** One choice: the variant that is added to the cart, and the amount it collects. */
export interface ContributionChoice {
  /** The Wix variant id. This is what travels in the cart line's `catalogReference.options`. */
  readonly variantId: string;
  /** Whole rupees, for the button face and the cart row. */
  readonly rupees: number;
  /** The same amount in integer paise, which is the unit the server and the money core speak. */
  readonly paise: number;
}

/**
 * THE ONLY THREE CONTRIBUTIONS THAT CAN BE MADE. Owner model change, 2026-10-04.
 *
 * What this replaced, because the shape of the change is the point: a contribution used to be one
 * ₹1 product whose QUANTITY carried the amount, with ₹10–₹1,00,000 bounds and a free-text "Other"
 * field. There is now no custom amount, no bounds, and no quantity arithmetic - a choice is a
 * fixed-price variant added at quantity 1. That deletes the client-side amount validation, the
 * rupee-to-paise parsing and the server's `quantity × 100` re-derivation rather than relocating
 * them, which is why this file is shorter than it was.
 *
 * DECLARED IN BOTH LANGUAGES ON PURPOSE. The authoritative copy is
 * amplify/functions/shared/lambda_utils/ecommerce/blog_contribution.py
 * (CONTRIBUTION_CHOICES_PAISE), kept as a separate declaration so the browser cannot widen the
 * trusted set. tests/test_blog_contribution.py::test_server_choices_mirror_the_frontend_contract
 * fails if the two drift.
 *
 * `paise` IS NOT A PRICE THE BROWSER SENDS. No amount, price or currency ever leaves the browser;
 * `cart_v2.calculate` prices the line. The figure is here so the button can say what it is about
 * to collect, and the server asserts Wix's computed total against its own copy of it - so a Wix
 * price edit refuses the contribution rather than charging a figure the button did not promise.
 */
export const CONTRIBUTION_CHOICES: readonly ContributionChoice[] = [
  { variantId: '166ba5b0-a0da-4ea2-b1d2-032af12e916d', rupees: 100, paise: 10000 },
  { variantId: '81d2d73a-b4ab-43fb-8043-505971763bcc', rupees: 250, paise: 25000 },
  { variantId: '8594562c-286e-48fc-b854-b09a863ba031', rupees: 500, paise: 50000 },
] as const;

/** One hundred paise to the rupee. Named so no magic 100 appears in the conversion helpers. */
export const PAISE_PER_RUPEE = 100;

/**
 * The rupee value of a paise amount, as an integer, for a DISPLAY label only. Every choice is a
 * whole number of rupees by construction, so this is exact for all three. It is deliberately a
 * floor rather than a rounding: a label is never the authority on what is charged.
 */
export const paiseToRupees = ( paise: number ): number => Math.floor( paise / PAISE_PER_RUPEE );

/** The choice a variant id names, or null when it names none of the three. */
export const contributionChoice = ( variantId: unknown ): ContributionChoice | null =>
  CONTRIBUTION_CHOICES.find(
    choice => choice.variantId === String( variantId || '' ).trim().toLowerCase() ) || null;

/** The purpose tag the backend keys a blog contribution under. Mirrors FEAT-004's BLOG_CONTRIBUTION. */
export const CONTRIBUTION_PURPOSE = 'BLOG_CONTRIBUTION' as const;
