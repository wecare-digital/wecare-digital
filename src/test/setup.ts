import '@testing-library/jest-dom/vitest';

/**
 * NO CONTRIBUTION ENV STUBBING ANY MORE, and its removal is the point rather than an omission.
 *
 * This file used to set `NEXT_PUBLIC_CONTRIBUTION_PRODUCT_ID` and
 * `NEXT_PUBLIC_CONTRIBUTION_VARIANT_ID` before any module read them, because `shop.ts` resolved
 * both from the committed catalogue snapshot and the product did not exist in Wix yet - so without
 * the stubs the whole suite only ever exercised the honest-unavailable path.
 *
 * The ids are now committed constants in src/config/contribution.ts (the product id plus the three
 * variant ids), so `CONTRIBUTION_CONFIGURED` is true by default and the suite exercises the real
 * values rather than invented ones. Tests that are ABOUT the unconfigured state stub the module.
 */

/**
 * jsdom does not implement window.matchMedia, and calling it throws
 * "window.matchMedia is not a function" rather than returning undefined.
 *
 * Any component that gates animation on (prefers-reduced-motion: reduce) therefore
 * crashes on mount under test. That is a jsdom gap, not a bug in the page: the API
 * is universally available in real browsers. It stayed hidden because the VayuLok
 * page, which has gated its headline rotation this way from the start, has no test
 * of its own - the Home page rotation was the first one to be asserted on.
 *
 * Defaults to matches:false, i.e. "motion is allowed", so tests exercise the
 * animated path. A test that needs the reduced-motion branch should override this
 * per-test with vi.spyOn(window, 'matchMedia').
 */
if ( typeof window !== 'undefined' && typeof window.matchMedia !== 'function' )
{
  Object.defineProperty( window, 'matchMedia', {
    writable: true,
    configurable: true,
    value: ( query: string ): MediaQueryList => ( {
      media: query,
      matches: false,
      onchange: null,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      // Deprecated pair, still called by some libraries.
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => false,
    } as unknown as MediaQueryList ),
  } );
}
