/**
 * THE MATERIAL SYMBOLS LIGATURES THE SITE RENDERS, AND THE ONE STYLESHEET THAT SHIPS THEM.
 *
 * WHY A SUBSET. _document.tsx used to request the whole Material Symbols Rounded variable font:
 * every glyph, every axis. Measured 2026-10-27 with a mobile Chrome user agent:
 *
 *   full family request              3,124,872 bytes of woff2
 *   the same axes + icon_names below    15,788 bytes
 *
 * The browser only downloads an icon font once some element on the page renders text in it, and
 * PublicShare does that on every public route. So every first visit to every public page paid
 * 3.1 MB for about seventeen icons, under `display=block`, competing with the LCP for bandwidth.
 * Google Fonts' `icon_names` parameter returns only the named glyphs; the axis ranges are kept
 * exactly as before, so every `font-variation-settings` a component declares still resolves.
 *
 * THE LIST IS THE CONTRACT. A ligature missing from the subset renders as its literal name
 * ("shopping_cart_checkout") instead of an icon, and nothing would fail. That is why every
 * component that renders a ligature passes it through `symbol()` (or types it as
 * `MaterialSymbol`): `tsc --noEmit`, which already gates the production build, then refuses any
 * name that is not in this list. To add an icon, add its name here and nowhere else.
 *
 * Google requires icon_names in alphabetical order, so the list is kept sorted and the URL sorts
 * it again rather than trusting edit order.
 */
export const MATERIAL_SYMBOLS = [
  'arrow_upward',
  'check',
  'chevron_right',
  'close',
  'currency_rupee',
  'directions_bus',
  'directions_car',
  'flight',
  'hotel',
  'ios_share',
  'link',
  'local_activity',
  'notifications_active',
  'redeem',
  'share',
  'shopping_cart_checkout',
  'train',
] as const;

export type MaterialSymbol = typeof MATERIAL_SYMBOLS[ number ];

/** Identity at runtime. At compile time it refuses a ligature the subset does not contain. */
export const symbol = ( name: MaterialSymbol ): MaterialSymbol => name;

/** The axes are unchanged from the full-family request; only the glyph set is narrowed. */
export const MATERIAL_SYMBOLS_STYLESHEET =
  'https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@20..48,400..600,0..1,0'
  + `&icon_names=${ [ ...MATERIAL_SYMBOLS ].sort().join( ',' ) }&display=block`;
