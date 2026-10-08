/**
 * The website "Leave a review" door: a `wa.me` link that opens WhatsApp with a prefilled
 * message, carrying the order being reviewed.
 *
 * WHY A LINK AND NOT A SEND
 * -------------------------
 * A WhatsApp Flow can only be delivered inside the 24-hour customer-service window, and
 * the customer's own message is what opens it. So the direction here matters: this link
 * makes the CUSTOMER message US. Nothing in this module sends anything, which is also why
 * it needs no template and why it cannot violate the standing rule against live sends.
 * The inbound handler recognises the prefilled text and replies with the Flow.
 *
 * WHICH NUMBER ANSWERS, AND WHY IT IS NOT A CHOICE
 * ------------------------------------------------
 * WABA 1 — 919330994400. `DEFAULT_FLOW_TRIGGERS['leave_review']` declares a `flowId` and
 * NO `flowId2`, and `_send_generic_flow` falls back to a plain CTA URL button when the
 * conversation arrived on WABA 2 because Flows exist only on the WABA that created them.
 * Pointing this door at WABA 2 would therefore land the customer in a link, not the form.
 * `src/test/ReviewCta.test.tsx` asserts the number as a property, so a future edit cannot
 * repoint it at a WABA whose review Flow does not exist.
 *
 * THE REFERENCE IS VALIDATED, NOT SANITISED
 * -----------------------------------------
 * `reviewWaLink` DROPS a reference it cannot vouch for rather than cleaning it up, and that
 * is the important decision in this file. Order numbers come in three live shapes:
 *
 *   `WD-ORD-A7K2M9PQ`            current minted form  (order_keys.PUBLIC_ORDER_NUMBER_*)
 *   `A7K2M9PQ3WXY`               legacy bare 12-char form, still valid for lookup
 *   `WD-ORD - A1B2C3D4 - 2026…`  legacy SPACED form from the Wix sync path
 *
 * The first two satisfy the bound below and travel. The third does not, and the tempting
 * fix — strip everything outside `[A-Z0-9-]` — would mint `WD-ORD-A1B2C3D4-2026…`, a string
 * that matches NO order in the table. Attribution would then look successful and point at
 * nothing, which is worse for the staff member reading it than an honest absence. So a
 * reference that does not already satisfy the bound is dropped and the customer gets the
 * unattributed door, which is a fully supported path.
 *
 * The bound is `^[A-Z0-9][A-Z0-9-]{3,39}$`, the same expression
 * `inbound-whatsapp-handler._REVIEW_REF_PATTERN` enforces on arrival. Both ends share it
 * deliberately: a reference this builder would send but that end would refuse is a door
 * that silently does nothing.
 */

/** WABA 1, the only WABA with a published review Flow. Never a different business number. */
export const REVIEW_WA_NUMBER = '919330994400';

/** The keyword the inbound handler matches. `review` alone is already a `leave_review` keyword. */
export const REVIEW_KEYWORD = 'review';

/**
 * The agreed reference shape, identical to the Lambda's `_REVIEW_REF_PATTERN` capture group.
 * Anchored both ends: a reference is a whole token, never a prefix of a sentence.
 */
const REFERENCE_BOUND = /^[A-Z0-9][A-Z0-9-]{3,39}$/;

/** True if `reference` is a shape both ends of this door agree to carry. */
export function isCarriableReference ( reference: string | undefined | null ): boolean {
  return REFERENCE_BOUND.test( String( reference ?? '' ).trim().toUpperCase() );
}

/**
 * The `wa.me` URL for the review door.
 *
 * @param reference An order number or payment reference. Omitted, empty, or any value
 *                  outside {@link REFERENCE_BOUND} yields the unattributed link rather
 *                  than a mangled one — see the note above.
 */
export function reviewWaLink ( reference?: string | null ): string {
  const base = `https://wa.me/${ REVIEW_WA_NUMBER }?text=`;
  const candidate = String( reference ?? '' ).trim().toUpperCase();
  if ( !isCarriableReference( candidate ) ) {
    return `${ base }${ encodeURIComponent( REVIEW_KEYWORD ) }`;
  }
  return `${ base }${ encodeURIComponent( `${ REVIEW_KEYWORD } ${ candidate }` ) }`;
}
