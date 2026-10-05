/**
 * Wix Headless — non-secret identifiers only.
 *
 * WIX IS THE COMMERCE BACKEND, HEADLESS. The owner has confirmed the architecture: the old
 * Wix *site* is retired and this repo owns every page, but Wix stays as a headless service
 * for catalog, inventory, cart and orders, reached over its REST APIs. There is no Wix
 * Editor or Velo runtime in this project - that CLI/Velo project is already deleted.
 *
 * NOTHING SECRET IS IN THIS FILE, and nothing secret may be added to it. The API key is a
 * bearer credential: anything holding it can read and write this account's commerce data.
 * It lives in AWS Secrets Manager and reaches the runtime through the environment. See
 * docs/wix-headless.md for the exact commands and the rotation note.
 *
 * The values below are safe to commit for the same reason a GA4 measurement ID is: they
 * identify which account and site to talk to, and grant nothing on their own.
 *
 * HOW THESE WERE OBTAINED, so they can be re-derived rather than trusted:
 *   - ACCOUNT_ID came out of the API key itself. A Wix API key is an "IST."-prefixed JWT
 *     whose payload carries { tenant: { type: "account", id } }. Decoding the payload is
 *     base64, needs no network and no secret handling, and is why the account ID did not
 *     have to be looked up anywhere. The owner has since confirmed the same value
 *     independently, so two sources agree on it.
 *   - SITE_ID was supplied directly by the owner as the "Headless Site ID". This is the
 *     only Wix site identifier this repository is allowed to use.
 */

/** Wix account that owns the site and the API key. */
export const WIX_ACCOUNT_ID = '478bf907-96cc-4cab-9220-bb96f1d35cbb';

/**
 * The only Wix site this repo talks to.
 *
 * Retired Wix Editor site identifiers are intentionally not retained here. Keeping a
 * superseded ID beside the live one makes accidental reuse more likely.
 */
export const WIX_SITE_ID = 'c993128b-26be-41cd-9fcd-904abe23462f';

/**
 * OAuth app / client id for Wix Headless visitor sessions.
 *
 * This is the PUBLIC half of the headless client and is designed to ship in a browser
 * bundle - it is what identifies the app when minting a visitor token. It is not the API
 * key and confers no admin access.
 */
export const WIX_CLIENT_ID = '42b3cdbf-d90e-4138-a06c-ddda4fb8da01';

/**
 * The application identity the API key acts as, from the key's own payload. Recorded for
 * audit - useful when reading Wix activity logs - and not used to authenticate.
 */
export const WIX_APP_ID = '5d23ddbd-72f9-4fc9-9b92-95d77f09655d';

/** Base URL for every Wix REST call. */
export const WIX_API_BASE = 'https://www.wixapis.com';

/**
 * Secrets Manager name the API key is stored under. Referenced by name so the Lambda that
 * needs it and the documentation cannot drift apart.
 */
export const WIX_API_KEY_SECRET = 'wecare/wix/headless-api-key';

/** Environment variable the key is read from at runtime. Never a literal. */
export const WIX_API_KEY_ENV = 'WIX_API_KEY';

/**
 * Headers every authenticated Wix admin call needs.
 *
 * Takes the key as an argument rather than reading it here, so this module stays free of
 * credential handling and can be imported from client-side code without dragging a secret
 * into the bundle.
 */
export const wixAdminHeaders = ( apiKey: string ): Record<string, string> => ( {
  Authorization: apiKey,
  'wix-account-id': WIX_ACCOUNT_ID,
  'wix-site-id': WIX_SITE_ID,
  'Content-Type': 'application/json',
} );
