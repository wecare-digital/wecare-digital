/** Shared shape for numbered legal provisions. */
export interface LegalSection {
  /** Stable clause number, e.g. "14" or "14.11". */
  number: string;
  heading: string;
  /** Stable URL-safe anchor, e.g. "s14-11". */
  id: string;
  paragraphs: string[];
}
