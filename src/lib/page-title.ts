const BRAND = 'WECARE.DIGITAL';

/** Public document titles share one suffix, including titles supplied by authored content. */
export function buildPageTitle( page: string ): string {
  const label = page.trim().replace( /\s*(?:[|—–-]\s*|by\s+)wecare(?:\.digital)?(?:\s+Blog)?\s*$/i, '' ).trim();
  return `${label} | ${BRAND}`;
}
