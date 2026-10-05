# Wix Headless

Wix is our **commerce backend**, headless. The old Wix *site* is retired — this repo owns
every page — but catalog, inventory, cart and orders still live in Wix and are reached over
its REST APIs and SDK. There is no Wix Editor and no Velo runtime in this project; that
CLI/Velo project has already been deleted.

## Identifiers

Non-secret, committed in [`src/config/wix.ts`](../src/config/wix.ts):

| What | Value |
|---|---|
| Account ID | `15f02319-40ff-4288-b8e6-69c791adae5e` |
| Site ID (headless) | `fcd82f0c-9572-49c7-acfb-88fb05042ece` |
| Site name | WECARE.DIGITAL |
| Headless client ID | `197cd718-e4ec-4e2e-b380-46c297eb18a2` |
| App ID (key identity) | `35d5f45b-ccc3-433b-886e-ca73a9379935` |

### How the account and site IDs were found

Worth recording, because both can be re-derived instead of trusted:

- **Account ID came out of the API key itself.** A Wix API key is an `IST.`-prefixed JWT
  whose payload contains `{ tenant: { type: "account", id } }`. Decoding it is base64 — no
  network call, no secret sent anywhere.
- **Site ID was supplied by the owner** as the "Headless Site ID". The only accepted Wix
  Site ID for this repository is `fcd82f0c-9572-49c7-acfb-88fb05042ece`. Retired Editor site identifiers are
  deliberately omitted from current configuration and runbooks.

  To verify the current site from an environment that legitimately holds the admin key:

  ```bash
  curl -X POST https://www.wixapis.com/site-list/v2/sites/query \
    -H "Authorization: $WIX_API_KEY" \
    -H "wix-account-id: 15f02319-40ff-4288-b8e6-69c791adae5e" \
    -H 'Content-Type: application/json' -d '{}'
  ```

  Confirm `fcd82f0c-9572-49c7-acfb-88fb05042ece` appears with the expected display name.

## The API key is a secret and is not in this repo

The key is a bearer credential: anything holding it can read and write this account's
commerce data. It is **not committed**, and `src/config/wix.ts` must never hold a literal.

Store it in Secrets Manager under the name `src/config/wix.ts` already references
(`wecare/wix/headless-api-key`):

```bash
aws secretsmanager create-secret \
  --name wecare/wix/headless-api-key \
  --description "Wix Headless admin API key for the WECARE.DIGITAL account" \
  --secret-string 'PASTE_THE_IST_KEY_HERE'
```

Rotating later (the owner plans to rotate once the project is complete):

```bash
# 1. Mint a new key in the Wix dashboard, then:
aws secretsmanager put-secret-value \
  --secret-id wecare/wix/headless-api-key \
  --secret-string 'PASTE_THE_NEW_KEY'
# 2. Revoke the old key in Wix. Do this second, so there is no window with no valid key.
```

Grant the Lambda read access to that one secret and expose it as `WIX_API_KEY`. Nothing
should read the key at module scope — fetch it per invocation or cache it in the handler,
so a rotation is picked up without a redeploy.

> **This key was pasted into a chat and must be treated as compromised on that basis
> alone**, independently of the planned rotation. Chat transcripts are not a secret store.

## Client ID vs API key

These are different credentials and are handled differently:

- **Client ID** (`WIX_CLIENT_ID`) is the *public* half of the headless client. It is designed
  to ship in a browser bundle and identifies the app when minting a visitor token. Safe to
  commit.
- **API key** is admin-level and server-only. Never in a bundle, never in git.

## Reference implementation

Wix's own Next.js minimal examples are vendored at
[`docs/reference/wix-headless-nextjs/`](reference/wix-headless-nextjs/) so the patterns are
readable without a network round trip. Fetched from
[wix/headless-templates](https://github.com/wix/headless-templates) (`nextjs/minimal-examples`).

Two files were dropped: `yarn.lock`, and a 2.9 MB vendored `yarn` binary under `.yarn/` —
a package-manager executable is not reference material.

The pattern it establishes, which is what we should follow:

```js
import { createClient, OAuthStrategy } from '@wix/sdk';
import { products } from '@wix/stores';

const client = createClient({
  modules: { products },
  auth: OAuthStrategy({ clientId: WIX_CLIENT_ID }),
});
```

Relevant SDK packages: `@wix/sdk`, `@wix/stores`, `@wix/ecom`, `@wix/redirects`,
`@wix/members`, `@wix/bookings`, `@wix/data`.

Note the examples target Next 13 and the `pages` router with `middleware.js` holding the
visitor session in a cookie. We are on Next 16 with `output: 'export'`, so **middleware does
not run** — a static export has no server. Any visitor-session handling has to happen
client-side or in a Lambda, and the middleware pattern in these examples cannot be copied
across as-is.

## Current integration in this repo

| Piece | Role |
|---|---|
| `amplify/functions/ecommerce/wix-store/handler.py` | Lambda `wecare-wix-store`, registered in `amplify/backend-resources.ts` |
| `src/api/client.ts` | 18 exported Wix symbols — products, orders, collections, sites |
| `src/pages/store/index.tsx` | Store admin UI (authenticated; not public, not in the sitemap) |
| `amplify/functions/operations/seo-tools/wix.py` | SEO tooling; imported by `seo-tools/handler.py` |

## MCP

Wix exposes an MCP server at `https://mcp.wix.com/mcp`. Not wired into this project — adding
it means registering it in the Kiro MCP config, and it would need its own credential
handling rather than reusing the admin key above.

## New-site Wix Stores IDs (recorded 2026-10-05)

After the full migration to the new storefront site `c993128b-26be-41cd-9fcd-904abe23462f`:

| Value | ID | Where it is used |
|---|---|---|
| Stores app **definition** id | `215238eb-22a5-4c36-9e7b-e7c08025e04e` | Constant across every Wix site (Wix's built-in Stores app). Already in `cart_v2.py` as `STORES_APP_ID`, used in `catalogReference.appId`. **Unchanged by the migration.** |
| Stores **instance** id (this site) | `0dc9e5f8-d16a-4dbc-b504-54d62ae93a81` | Site-specific. NOT consumed by any live storefront/cart/webhook code — those read `metadata.instanceId` from each event's JWT at request time. The ONLY configured consumer is the gift-card SPI (`gift_card_spi_auth.py`, `SECRET_ID = wecare/wix/giftcard-spi`, field `instance_id`), which is **not provisioned live** (no function, routes, or secret). |

**Action required: none today.** Record only. When/if the gift-card Service Plugin is
provisioned, set `instance_id` in the `wecare/wix/giftcard-spi` secret to
`0dc9e5f8-d16a-4dbc-b504-54d62ae93a81`. Do not hardcode the instance id into storefront
code — it is not needed there and the webhook/SPI paths receive it per-request in the JWT.
