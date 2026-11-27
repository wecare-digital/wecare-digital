




export const GOOGLE_BUSINESS_PROFILE = {
  location: 'locations/11367616731342236672',
} as const;

export const PLAY_STORE = {
  developerUrl: 'https://play.google.com/store/apps/dev?id=5505420420345648842',
} as const;


/**
 * Meta asset identifiers for WECARE.DIGITAL.
 *
 * `pixelId` is read from env with the canonical value as the documented default, the same
 * way VERIFICATION reads its tokens - the number is public the moment the tag renders, but
 * it is account-binding, so deployment config gets the final say. `??` rather than `||`,
 * matching GTM_ID in _document.tsx: unset means "use the canonical id", while an explicit
 * empty string means "no Pixel", and `||` cannot tell those two apart.
 *
 * `datasetId` is the SERVER-SIDE Conversions API destination. It is recorded here so the
 * asset set reads as one list, and for no other reason: it must never be handed to fbq()
 * or used as a browser target. Events for it are sent server-to-server.
 *
 * `catalogId` is the canonical WECARE.DIGITAL service catalogue and mirrors the
 * existing Meta asset configuration. Automatic catalog publishing is retired.
 * The older ids 1607047307067517 and 1088514403989109 are RETIRED - they name catalogues
 * this property no longer syncs, and they survive only in dated evidence under docs/.
 *
 * `catalogName` is the human-readable handle for the catalogue whose numeric id is
 * `catalogId` above; it is the WhatsApp/Meta catalogue name, not an alternate id.
 *
 * `appId` mirrors the META_APP_ID default the five WhatsApp handlers carry.
 */
export const META = {
  pixelId: process.env.NEXT_PUBLIC_META_PIXEL_ID ?? '3411484995761247',
  datasetId: '4554612361454941',
  catalogId: '1457045652952851',
  catalogName: 'wecare_shop',
  appId: '2238810740192680',
} as const;

export const BING = {
  /** Canonical apex site; legacy www property should be retired in Bing settings. */
  siteUrl: 'https://wecare.digital/',
} as const;

/**
 * Search-console verification tokens, from env.
 *
 * Empty by default, and the meta tag is omitted entirely when empty - an empty
 * content="" verification tag is worse than none, because it looks configured.
 */
export const VERIFICATION = {
  google: process.env.NEXT_PUBLIC_GOOGLE_SITE_VERIFICATION || '',
  bing: process.env.NEXT_PUBLIC_BING_SITE_VERIFICATION || '',
} as const;
