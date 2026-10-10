/**
 * Non-secret marketing and analytics IDENTIFIERS.
 *
 * WHAT BELONGS HERE: account numbers, property IDs, network codes, profile locations.
 * These are identifiers, not credentials - they appear in page source, in tag manager
 * payloads and in ad previews, and knowing one grants nothing.
 *
 * WHAT MUST NEVER BE HERE: the Google Ads developer token, the OAuth client secret, the
 * Unified API key, refresh tokens, the Bing API key. Those are credentials. They live in
 * Secrets Manager (wecare/google/ads, wecare/bing/api) and are read server-side by
 * Lambdas, exactly as wecare/wix/headless-api-key and wecare/google/translate already are. A
 * credential in this file would be bundled into the client JavaScript and served to
 * every visitor.
 *
 * Verification tokens are the one grey area and are read from env rather than hardcoded:
 * they are public once rendered, but they are account-binding, so the value belongs with
 * deployment config rather than in version control.
 */

/** Digits only - the Google Ads API rejects the dashed display form. */
export const GOOGLE_ADS = {
  /** WECARE.DIGITAL, displayed as 836-758-9699. */
  customerId: '8367589699',
  /** Manager (MCC) account, displayed as 427-041-2231. Sent as login-customer-id. */
  loginCustomerId: '4270412231',
} as const;

/** Google Ad Manager, displayed as 427-041-2231. */
export const GOOGLE_AD_MANAGER = {
  networkCode: '4270412231',
} as const;

export const GOOGLE_CLOUD = {
  projectName: 'WECARE-DIGITAL',
  projectId: 'wecaredigitalbw',
  projectNumber: '756034744787',
} as const;

export const GOOGLE_ANALYTICS = {
  /**
   * GA4 PROPERTY id. Note this is NOT the Measurement ID.
   *
   * gtag.js needs a Measurement ID shaped G-XXXXXXXXXX, which is per data stream and is
   * a different value from the property number. The property number is only usable from
   * the Admin and Data APIs, server-side. So this cannot be dropped into the gtag
   * snippet - NEXT_PUBLIC_GA_MEASUREMENT_ID still has to be set separately.
   */
  propertyId: '550346663',
} as const;

export const GOOGLE_BUSINESS_PROFILE = {
  location: 'locations/11367616731342236672',
} as const;

export const PLAY_STORE = {
  developerUrl: 'https://play.google.com/store/apps/dev?id=5505420420345648842',
} as const;

/**
 * Meta ad accounts. The one labelled WECARE.DIGITAL is marked primary; the rest were
 * supplied without labels and are kept in the order given so they can be identified
 * later rather than guessed at now.
 */
export const META_AD_ACCOUNTS = {
  primary: '757566744073180',
  all: [
    '2477665435963445',
    '1685177122467383',
    '757566744073180',
    '2107046253414284',
    '1574832283724191',
    '4437435039910843',
    '3770879209885614',
  ],
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
 * META_CATALOG_ID default in amplify/functions/ecommerce/meta-catalog-sync/handler.py.
 * The older ids 1607047307067517 and 1088514403989109 are RETIRED - they name catalogues
 * this property no longer syncs, and they survive only in dated evidence under docs/.
 *
 * `appId` mirrors the META_APP_ID default the five WhatsApp handlers carry.
 */
export const META = {
  pixelId: process.env.NEXT_PUBLIC_META_PIXEL_ID ?? '3411484995761247',
  datasetId: '4554612361454941',
  catalogId: '1457045652952851',
  appId: '2238810740192680',
} as const;

export const BING = {
  /** Site registered in Bing Webmaster Tools. Note it is the www apex, not stack.*. */
  siteUrl: 'https://www.wecare.digital/',
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
