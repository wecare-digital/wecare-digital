/**
 * Shared shape for the long legal documents in this directory.
 *
 * WHY THIS FILE EXISTS: terms.ts and privacy.ts each declared their own identical copy
 * of this interface, and LegalDocument imported the one from terms.ts. The two copies
 * then drifted - `inShort` was added to the privacy copy only, so the component could
 * not read the field it was being passed and the summaries silently rendered as
 * nothing. Structural typing hid it: the extra optional property still satisfied the
 * older interface, so the build stayed green. One declaration, imported by all three.
 */
export interface LegalSection {
  /**
   * "14" or "14.11". PRESERVED VERBATIM. Numbers are cross-referenced from outside this
   * directory - src/pages/orders.tsx points at section 14 - and by anyone who has ever
   * cited a clause to us. Renumbering
   * is a breaking change to those references even when the wording is untouched.
   */
  number: string;
  heading: string;
  /** URL-safe anchor, e.g. "s14-11". Stable for the same reason as `number`. */
  id: string;
  /**
   * Plain-language summary shown above the clause text.
   *
   * NOT BINDING, and the document says so where these are rendered. A summary that
   * reads as if it replaces the clause is worse than no summary, because it invites a
   * reader to rely on wording that was written for brevity rather than for accuracy.
   * Top-level sections only; sub-clauses are short enough already.
   */
  inShort?: string;
  paragraphs: string[];
}
