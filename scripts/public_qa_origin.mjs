/** Distinguish immutable PR exports from a deliberately live observation. */
export const canonicalOrigin = new URL('https://wecare.digital/');
export const snapshotOrigin = new URL('https://127.0.0.1:4173/');
export function qaOrigin() {
  const snapshot = process.env.PUBLIC_QA_SNAPSHOT === '1';
  const origin = new URL(process.env.PUBLIC_QA_BASE || canonicalOrigin.href);
  if (origin.href !== (snapshot ? snapshotOrigin.href : canonicalOrigin.href)) {
    throw new Error('Use only the approved public origin or the fixed loopback snapshot.');
  }
  return {origin, snapshot};
}
export const pathOf = path => path === '/' ? '/' : path.replace(/\/+$/, '') + '/';
export function authGateMatches(url, origin, returnPath) {
  const u = new URL(url);
  const value = u.searchParams.get('return');
  return u.origin === origin.origin && pathOf(u.pathname) === '/auth/' &&
    typeof value === 'string' && pathOf(value) === returnPath &&
    !value.includes('?') && !value.includes('#') && !value.includes('//');
}
export async function verifyAuthGate(page, origin, returnPath) {
  await page.waitForURL(url => authGateMatches(url.href, origin, returnPath), {waitUntil:'domcontentloaded',timeout:15000});
  if (!authGateMatches(page.url(), origin, returnPath)) throw new Error('Unexpected sign-in destination');
}
