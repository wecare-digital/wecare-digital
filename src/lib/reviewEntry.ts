/**
 * The published private review Flow and its verified customer entry — the ONE TypeScript
 * source of truth for the Leave Review door.
 *
 * WHY A MODULE RATHER THAN A LITERAL PER FILE. Five surfaces describe this one door: the
 * public `/leave-review/` page CTA and four workspace tables that staff read when telling a
 * customer what to type. Before this, each restated the id and a keyword list of its own, and
 * four of them restated a Flow id that was not present on the WABA at all — so the workspace
 * confidently advertised a door that did not exist. One module makes a one-sided edit
 * impossible rather than merely discouraged.
 *
 * `tests/test_leave_review_wiring.py` asserts this file against
 * `DEFAULT_FLOW_TRIGGERS['leave_review']` in the inbound handler, and asserts that each of the
 * five surfaces REFERENCES these constants instead of restating them.
 */

/**
 * WD_Leave_Review_v2, the published review Flow on WABA 1.
 *
 * Shared with the `customer_idea` inbound door: Meta has no per-door Flow identity, so one
 * room with two doors is the only available shape. The Flow is ENDPOINTLESS (no
 * `data_api_version`, first screen `FEEDBACK` carries no `data` block), which is why the
 * handler must open it with `navigate` — see `STATIC_ENTRY_SCREENS`.
 */
export const REVIEW_FLOW_ID = '1578178897413815';

/**
 * The owner's WhatsApp short link, and the one public CTA on these pages that is not the
 * contact page.
 *
 * It resolves to WABA 1 (919330994400) with the prefill `Leave Review`. Lowercased that is
 * `leave review`, the FIRST entry in `REVIEW_ENTRY_KEYWORDS`, so the customer's own outbound
 * message lands on an exact keyword match and opens the Flow. Tapping it composes a message
 * the visitor still has to send — nothing here sends anything.
 */
export const REVIEW_ENTRY_URL = 'https://wa.me/message/ZM74K2H2BIFOA1';

/**
 * The owner-decided ordered keyword set, mirroring `DEFAULT_FLOW_TRIGGERS['leave_review']`.
 *
 * ORDER IS LOAD-BEARING. The first keyword is the Meta-side prefill on `REVIEW_ENTRY_URL`, and
 * the handler's dispatch is an exact match over this collection — so this is asserted as an
 * ordered list, not a set.
 */
export const REVIEW_ENTRY_KEYWORDS = [
  'leave review', 'leave a review', 'review', 'reviews', 'feedback',
  'leave feedback', 'give feedback', 'share feedback', 'rate', 'rate us',
  'rate service', 'rating', 'ratings', 'testimonial', 'write a review',
  'give a review', 'share your experience', 'how was it', '⭐ leave review',
];
