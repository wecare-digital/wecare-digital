/**
 * The single source of truth for every vendor, API and runtime version.
 *
 * Why this file exists
 * --------------------
 * Before it, the Meta Graph version reached the runtime three different ways:
 *
 *   1. an env var with a default        `os.environ.get('META_API_VERSION', 'v25.0')`   9 files
 *   2. a hard-coded module constant     `META_API_VERSION = 'v25.0'`                    7 files
 *   3. a literal inside a URL string    `f'https://graph.facebook.com/v25.0/{id}/...'`  3 files
 *
 * Shape 3 is the dangerous one, because a grep for the constant name does not find it.
 * It includes the payment-lookup call in `inbound-whatsapp-handler`, so a version bump
 * could silently leave payment reconciliation on an older API than everything else.
 *
 * This module is canonical for TypeScript. `config/vendor-versions.json` is generated
 * from it for the Python fleet, and `scripts/check-versions.ts` fails when the two drift.
 * Nothing should read a version from anywhere else.
 *
 * The three columns, and why all three are needed
 * -----------------------------------------------
 * `configured`     what this system actually uses. Changing it is a deployment.
 * `verifiedLatest` what the vendor published, as measured on `verifiedOn`.
 * `verifiedOn`     when that measurement was taken.
 *
 * Recording only `configured` hides that we are behind. Recording only `verifiedLatest`
 * invents a fact that rots the day after it is written. Recording the date is what makes
 * the other two auditable — a `verifiedLatest` with no date is a rumour.
 *
 * `configured !== verifiedLatest` is NOT automatically a defect. `v26.0` is newer than
 * `v25.0` and is deliberately not adopted; see `upgradeBlockedReason`.
 */

/** How a version was established. Mirrors the evidence classes in `docs/compatibility.md`. */
export type Evidence = 'LIVE' | 'DOC' | 'REPO' | 'BLOCKED';

/** Whether drift between `configured` and `verifiedLatest` is acceptable. */
export type DriftPolicy =
  /** Must match `verifiedLatest`. Any drift fails the check. */
  | 'must-be-latest'
  /** May lag, but only while `upgradeBlockedReason` explains why. */
  | 'lag-allowed-with-reason'
  /** Deliberately pinned. Drift is expected and is not reported as a problem. */
  | 'pinned'
  /** Cannot be measured automatically; needs a human reading vendor docs. */
  | 'manual-review';

export interface VendorVersion {
  /** Human name, as the vendor writes it. */
  readonly name: string;
  /** What this system uses today. */
  readonly configured: string;
  /** Latest the vendor offered, as measured on `verifiedOn`. `null` when unmeasurable. */
  readonly verifiedLatest: string | null;
  /** ISO date of the `verifiedLatest` measurement. */
  readonly verifiedOn: string;
  readonly evidence: Evidence;
  readonly drift: DriftPolicy;
  /**
   * Why `configured` lags, when it does. Required by `checkVersions` whenever
   * `drift === 'lag-allowed-with-reason'` and the two values differ — a lag with no
   * stated reason is indistinguishable from neglect.
   */
  readonly upgradeBlockedReason?: string;
  /**
   * ISO date after which the reason above stops being accepted.
   *
   * Exists because a *false* reason is worse than a missing one, and a true reason can
   * expire. The v26.0 pin is the case that motivated this: its recorded justification
   * turned out to be unsubstantiated, and the surfaces it claimed to protect are removed
   * from every remaining Graph version on a fixed date anyway — after which the pin
   * protects nothing while still reading as deliberate.
   *
   * Once this date passes, `checkVersions` escalates the finding from `warn` to `error`,
   * so the gate fails rather than a stale justification carrying indefinitely.
   */
  readonly lagExpiresOn?: string;
  /** How to re-measure `verifiedLatest`. Kept next to the number it produces. */
  readonly rederive: string;
}

/**
 * Meta Graph API version.
 *
 * Moved v25.0 → v26.0 on 2026-10-01. The pin that held it at v25.0 rested on a false
 * premise, and the audit that established that is
 * `docs/execution/meta-graph-version-audit-20261001.md`.
 *
 * `meta-business-agent/handler.py:231-234` pinned away from v26.0 on the grounds that it
 * "blocked a batch of commerce endpoints" and that `_tool_product_lookup` reads
 * `/{catalog_id}/products`. Checked against Meta's v26.0 changelog, that does not hold:
 * v26.0 deprecates the **Commerce Order Management API** — 47 endpoints shaped
 * `/{commerce-order-id}/…`, `/{page-id}/commerce_orders`, `/{commerce-merchant-settings-id}/…`
 * — because checkout on Facebook and Instagram Shops was sunset. `/{catalog_id}/products` is
 * the Product Catalog API and is not among them. The audit enumerated ~50 endpoints across
 * 18 functions and 3 scripts and found **zero** affected, plus none of the five legacy
 * protocol features v26.0 removes.
 *
 * `upgradeBlockedReason` and `lagExpiresOn` are gone with the lag. Carrying an expired
 * justification is the failure mode `lagExpiresOn` exists to catch, and the honest remaining
 * gap is not a lag: it is that **no live Graph call has been made on v26.0 from this repo**,
 * because that needs a real token and reading a credential is prohibited here. That gap is
 * recorded as a deploy gate in the audit, not as a reason to stay on v25.0 — a doc audit is
 * grounds to move the repo constant, and the live Lambda environments pin v25.0 explicitly,
 * so production does not move until a separately authorized deploy.
 *
 * v25.0 is supported until 2028-07-29, so nothing here is an outage deadline.
 */
export const META_GRAPH: VendorVersion = {
  name: 'Meta Graph API / WhatsApp Cloud API',
  configured: 'v26.0',
  verifiedLatest: 'v26.0',
  verifiedOn: '2026-10-01',
  evidence: 'DOC',
  drift: 'lag-allowed-with-reason',
  rederive: 'https://developers.facebook.com/docs/graph-api/changelog/versions/',
} as const;

/**
 * The approved AUTHENTICATION template used for phone OTP.
 *
 * Not a version in the semver sense, but it is a vendor-side artifact that can be
 * rejected, paused or re-categorised without any code change here, so it belongs in the
 * same register. Verified live: APPROVED, category AUTHENTICATION, language en.
 *
 * The OTP is delivered as a `url` button parameter, not `copy_code`. Meta materialises an
 * AUTHENTICATION template's copy affordance as a real URL button, and sending `copy_code`
 * is rejected with `(#132018) buttons: Button at index 0 must be of type Url`.
 */
export const META_AUTH_TEMPLATE: VendorVersion = {
  name: 'Meta AUTHENTICATION template (wecare_otp)',
  configured: 'wecare_otp/en',
  verifiedLatest: 'wecare_otp/en',
  verifiedOn: '2026-09-26',
  evidence: 'LIVE',
  drift: 'must-be-latest',
  rederive:
    'aws lambda invoke --function-name wecare-whatsapp-templates:live ' +
    "--payload '{\"httpMethod\":\"GET\",\"path\":\"/wa-business/templates\"," +
    '"queryStringParameters":{"wabaId":"2094615664435155"}}\'',
} as const;

/**
 * Wix Stores catalog family.
 *
 * Was `BLOCKED` on the theory that confirming the site's catalog version needed the admin
 * credential. It did not, and the distinction is worth keeping: the code calling
 * `/stores/v3/*` proves what the code intends and nothing about the site, but Wix states the
 * site's version itself in an error. `POST /stores/v1/products/query` returns **HTTP 428**
 * with `applicationError.code = CATALOG_V3_CALLING_CATALOG_V1_API`. A visitor token minted
 * from the public `WIX_CLIENT_ID` is enough to elicit that — no secret involved.
 * Corroborated by 7 products returned through `/stores/v3/products/query`.
 */
export const WIX_CATALOG: VendorVersion = {
  name: 'Wix Stores Catalog',
  configured: 'V3',
  verifiedLatest: 'V3',
  verifiedOn: '2026-09-26',
  evidence: 'LIVE',
  drift: 'must-be-latest',
  rederive: '.venv/bin/python scripts/probe_wix_capabilities.py',
} as const;

/**
 * Wix eCommerce — Orders, Order Transactions, Order Fulfillments.
 *
 * Split out of a single conflated `WIX_ECOM` entry on 2026-10-01. That entry was named
 * "(orders, transactions, fulfillments, cart, checkout)" and reported `[ ok ]` purely
 * because both of its columns said `V1` — it averaged two families with opposite verdicts
 * into one reassuring row.
 *
 * `/ecom/v1` is not one API. It is the version prefix shared by six separate Wix eCommerce
 * APIs, and only Cart and Checkout are in the 2027-02-01 removal. Orders, Order Transactions
 * and Order Fulfillments are current, carry no deprecation notice, and appear nowhere in the
 * Cart V2 migration mapping. V1 **is** latest for this family, so `must-be-latest` passing
 * here is a real measurement rather than an artefact.
 *
 * 14 of this repo's 16 `/ecom/v1` call sites belong here and are deliberately left alone.
 */
export const WIX_ECOM_ORDERS: VendorVersion = {
  name: 'Wix eCommerce Orders / Transactions / Fulfillments',
  configured: 'V1',
  verifiedLatest: 'V1',
  verifiedOn: '2026-10-01',
  evidence: 'DOC',
  drift: 'must-be-latest',
  rederive: 'https://dev.wix.com/docs/api-reference/business-solutions/e-commerce/orders/introduction',
} as const;

/**
 * Wix eCommerce — Cart and Checkout.
 *
 * The half of the old `WIX_ECOM` row that genuinely lags. Cart V2 unifies Cart V1 and
 * Checkout V1 into one Cart entity, and **those two APIs are removed on 2027-02-01**; a
 * V1 checkout id is a V2 cart id, so ids carry across.
 *
 * `configured: 'V1'` because V1 is what *serves*: `ecommerce/checkout/handler.py` resolves its
 * authoritative total through `wix_ecom.create_checkout` (`POST /ecom/v1/checkouts`) whenever
 * Cart V2 is not switched on. The Cart V2 path is complete — adapter, delivery methods, and the
 * `ecommerce/purchase_intent` quote producer — and `ecommerce/checkout` prices through
 * `cart_v2.CartV2.calculate` when it runs. It is **opt-in** behind `WIX_CART_V2_ENABLED`, and
 * that key is absent on every function in the fleet, so claiming `V2` here would be false.
 *
 * A revision on 2026-10-01 briefly inverted the gate into a `WIX_CART_V2_DISABLED` opt-out and
 * recorded `configured: 'V2'`. Both are reverted, and the reason is worth keeping: with neither
 * key set anywhere, "default on" did not mean anyone had chosen V2 — it meant the live price
 * authority would change at the next routine deploy, with no environment change. `configured`
 * means what this system uses, and a value that depends on nobody having deployed yet is not
 * that. `WIX_CART_V2_DISABLED` survives as an override on top of the opt-in, so the rollback
 * lever is still one environment variable.
 *
 * What the §3 delivery blocker turned out to be: Cart V2 replaces V1's silent adjustments with
 * explicit violations, so a real Calculate Cart against this site answers an address-less cart
 * with `ERROR`-severity `MISSING_DELIVERY_ADDRESS` and `MISSING_DELIVERY_METHOD`. That is the
 * contract working, not a defect — V1's total was obtainable only because nothing validated it.
 * The resolution is to supply the address from the authenticated customer's owned profile, and
 * `Estimate Cart` (verified: no address needed with `calculateDelivery`/`calculateTax` off) is
 * the documented pre-address state. A placeholder address is refused outright: in India the
 * delivery address is the place of supply, so a fake one yields the wrong CGST/SGST-versus-IGST
 * split on an invoice carrying seller GSTIN 19AAFFW7196L1Z8.
 *
 * `drift: 'lag-allowed-with-reason'` rather than `must-be-latest`, with an expiry. The lag is
 * real and it is one operator action wide, so it must be reported rather than passed off as
 * current — but failing the gate on it would say the code has not been migrated, which is no
 * longer true. `lagExpiresOn` is well inside the 2027-02-01 removal of Cart and Checkout V1, so
 * the justification cannot quietly outlive the thing it is waiting on.
 *
 * The remaining open item is NOT version lag, and is tracked in
 * `docs/execution/wix-cart-v2-migration-20261001.md` §10 rather than averaged into this row:
 *   - six V2 request shapes (set/remove-delivery-method, refresh, estimate, add/remove-coupon)
 *     are convention-derived and unverified against a live call — a deploy gate.
 *
 * `checkout/handler.py`'s `LOAD_OWNED_ADDRESS` seam is WIRED as of the Phase 1 checkout-identity
 * work: it reads `checkoutDeliveryAddress` off the authenticated session's CRM contact row, which
 * `auth/customer-profile` writes. The owner decision on where that address comes from is recorded
 * in that phase's design §12.1, so this is no longer an open question — the V2 path answers
 * `409 DELIVERY_DETAILS_REQUIRED` only when the customer has saved no usable address.
 */
export const WIX_ECOM_CART: VendorVersion = {
  name: 'Wix eCommerce Cart / Checkout',
  configured: 'V1',
  verifiedLatest: 'V2',
  verifiedOn: '2026-10-01',
  evidence: 'DOC',
  drift: 'lag-allowed-with-reason',
  upgradeBlockedReason:
    'Cart V2 is implemented and tested but opt-in behind WIX_CART_V2_ENABLED, which is absent on ' +
    'every function. Switching it on is an operator action: it changes the live price authority ' +
    'and needs one authorized live Calculate Cart to confirm six convention-derived request ' +
    'shapes, plus the LOAD_OWNED_ADDRESS profile read. See ' +
    'docs/execution/wix-cart-v2-migration-20261001.md.',
  lagExpiresOn: '2026-12-31',
  rederive:
    'https://dev.wix.com/docs/api-reference/business-solutions/e-commerce/purchase-flow/cart-v2/migration-guide',
} as const;

/**
 * Wix Blog.
 *
 * The API is still not called anywhere in this repo — the adapter is new work — but
 * availability is no longer unknown. `/blog/v3/posts/query` answers with
 * `metaData.total = 571` and `/blog/v3/categories` returns 200, both against a visitor
 * token. So `configured` describes the target *and* the site's actual version.
 *
 * "Absent by grep" was the right statement about this repository and the wrong statement
 * about the site. Worth keeping the two apart.
 */
export const WIX_BLOG: VendorVersion = {
  name: 'Wix Blog',
  configured: 'V3',
  verifiedLatest: 'V3',
  verifiedOn: '2026-09-26',
  evidence: 'LIVE',
  drift: 'must-be-latest',
  rederive: '.venv/bin/python scripts/probe_wix_capabilities.py',
} as const;

/**
 * Google Places.
 *
 * Corrected 2026-10-05: the code migration LANDED, and two facts recorded here were false
 * after it. `configured` read `legacy-web-service` and `upgradeBlockedReason` named
 * `wecare/google-maps-server` as the server-key store. Both are now wrong:
 *
 *   1. `messaging/whatsapp-templates/handler.py` no longer touches a legacy endpoint. Both
 *      server-side Places calls — Autocomplete and Place Details — go to
 *      `places.googleapis.com/v1`, and the legacy keyless-GET helper was deleted rather
 *      than left behind for a future call site to re-use. `maps.googleapis.com` appears in
 *      no Python in the repo. The remaining browser uses of `maps/api/js` are the Maps
 *      JavaScript API, a different product on the referrer-restricted browser key, and are
 *      not this entry.
 *   2. `wecare/google-maps-server` is RETIRED. The canonical store is `wecare/google/cloud`,
 *      which is what `scripts/provision_maps_server_key.py` writes and what every consumer
 *      reads. See `docs/security.md` and `docs/operations.md`.
 *
 * How the credential blocker closed is still worth keeping, because the first diagnosis was
 * wrong. The stated blocker was that the unified key's `apiTargets` omitted
 * `places.googleapis.com`. That was true, and adding it was **necessary but not
 * sufficient** — after the target was added the call still failed, with
 * `API_KEY_HTTP_REFERRER_BLOCKED`. The real refusal was about the key *type*: the unified
 * key is a browser key (`browserKeyRestrictions.allowedReferrers`), and Google rejects
 * referrer-restricted keys for server-side calls on both legacy Maps web services and
 * Places (New). No edit to a browser key can fix that.
 *
 * So `configured` tracks the ENDPOINT this system calls, and that is now the new one. The
 * open item is neither a version lag nor a credential design question: a server key with no
 * application restriction has to be minted into `wecare/google/cloud` before these calls
 * succeed in production, and until it is, Google answers `API_KEY_HTTP_REFERRER_BLOCKED`.
 * `_google_status_problem` in that handler exists so that refusal is reported as a 502
 * diagnosis rather than as an empty address list. Tracked in
 * `docs/vayulok-live-deploy.md`, not here.
 */
export const GOOGLE_PLACES: VendorVersion = {
  name: 'Google Places',
  configured: 'places-api-new',
  verifiedLatest: 'places-api-new',
  verifiedOn: '2026-09-26',
  evidence: 'LIVE',
  drift: 'must-be-latest',
  rederive:
    '.venv/bin/python scripts/provision_maps_server_key.py --verify, and ' +
    'https://developers.google.com/maps/documentation/places/web-service/op-overview',
} as const;

/** Address Validation, enabled on the project and on the key. Used to verify addresses. */
export const GOOGLE_ADDRESS_VALIDATION: VendorVersion = {
  name: 'Google Address Validation API',
  configured: 'v1',
  verifiedLatest: 'v1',
  verifiedOn: '2026-09-26',
  evidence: 'LIVE',
  drift: 'must-be-latest',
  rederive: 'gcloud services list --enabled --filter=config.name:addressvalidation.googleapis.com',
} as const;

/**
 * Lambda runtime for the existing fleet.
 *
 * `python3.13` is GA and newer. Moving 64 functions is a fleet migration, not a config
 * change, and `python3.12` is fully supported, so the lag is deliberate.
 */
export const LAMBDA_PYTHON_RUNTIME: VendorVersion = {
  name: 'AWS Lambda Python runtime',
  configured: 'python3.12',
  verifiedLatest: 'python3.13',
  verifiedOn: '2026-09-26',
  evidence: 'LIVE',
  drift: 'lag-allowed-with-reason',
  upgradeBlockedReason:
    '64 of 65 functions run python3.12 and it remains supported. A fleet-wide runtime ' +
    'move is its own change with its own verification, not a side effect of this build.',
  rederive: "aws lambda list-functions --query 'Functions[].Runtime' | sort -u",
} as const;

/** Node.js. `.nvmrc` pins the major; the local toolchain and CI must agree. */
export const NODE_RUNTIME: VendorVersion = {
  name: 'Node.js',
  configured: '24',
  verifiedLatest: '24',
  verifiedOn: '2026-09-26',
  evidence: 'LIVE',
  drift: 'must-be-latest',
  upgradeBlockedReason: undefined,
  rederive: 'node -v against .nvmrc and package.json engines.node',
} as const;

/**
 * Frontend framework.
 *
 * The brief names Astro. This repo is Next.js with 127 pages and a static export, and a
 * second framework would split the build for no gain. Recorded as a pin so the check does
 * not report it as drift every run.
 */
export const FRONTEND_FRAMEWORK: VendorVersion = {
  name: 'Next.js (storefront and admin shell)',
  configured: '16.2.9',
  verifiedLatest: '16.3.6',
  verifiedOn: '2026-09-26',
  evidence: 'LIVE',
  drift: 'lag-allowed-with-reason',
  upgradeBlockedReason:
    'Patch-level lag only. Bump with the normal dependency gate; not on the critical path.',
  rederive: 'npm view next version',
} as const;

/** TypeScript. A full major behind, which is worth surfacing rather than burying. */
export const TYPESCRIPT: VendorVersion = {
  name: 'TypeScript',
  configured: '6.0.3',
  verifiedLatest: '7.0.2',
  verifiedOn: '2026-09-26',
  evidence: 'LIVE',
  drift: 'lag-allowed-with-reason',
  upgradeBlockedReason:
    'A major version behind. Upgrading is a typecheck-wide change across 127 pages and ' +
    'must land as its own commit with `npm run typecheck` green, not inside a feature.',
  rederive: 'npm view typescript version',
} as const;

export const AWS_CDK: VendorVersion = {
  name: 'aws-cdk-lib',
  configured: '2.270.0',
  verifiedLatest: '2.271.0',
  verifiedOn: '2026-09-26',
  evidence: 'LIVE',
  drift: 'pinned',
  upgradeBlockedReason:
    'Pinned exactly (no caret) on purpose: Amplify Gen 2 resolves CDK transitively and a ' +
    'floating range has produced construct-version conflicts here before.',
  rederive: 'npm view aws-cdk-lib version',
} as const;

/** Browser automation, required by the brief for cross-browser tests. Not yet installed. */
export const PLAYWRIGHT: VendorVersion = {
  name: '@playwright/test',
  configured: 'not-installed',
  verifiedLatest: '1.63.0',
  verifiedOn: '2026-09-26',
  evidence: 'LIVE',
  drift: 'lag-allowed-with-reason',
  upgradeBlockedReason:
    'Not a dependency yet. tools/browser/ vendors playwright-core as a measurement ' +
    'harness, deliberately outside the app package. The E2E suite introduces the runner.',
  rederive: 'npm view @playwright/test version',
} as const;

/** Every tracked version, keyed by a stable id used in reports and in the JSON mirror. */
export const VENDOR_VERSIONS = {
  metaGraph: META_GRAPH,
  metaAuthTemplate: META_AUTH_TEMPLATE,
  wixCatalog: WIX_CATALOG,
  wixEcomOrders: WIX_ECOM_ORDERS,
  wixEcomCart: WIX_ECOM_CART,
  wixBlog: WIX_BLOG,
  googlePlaces: GOOGLE_PLACES,
  googleAddressValidation: GOOGLE_ADDRESS_VALIDATION,
  lambdaPythonRuntime: LAMBDA_PYTHON_RUNTIME,
  nodeRuntime: NODE_RUNTIME,
  frontendFramework: FRONTEND_FRAMEWORK,
  typescript: TYPESCRIPT,
  awsCdk: AWS_CDK,
  playwright: PLAYWRIGHT,
} as const;

export type VendorKey = keyof typeof VENDOR_VERSIONS;

/**
 * Runtimes this project refuses in production, and why.
 *
 * Brief §51 requires preview and deprecated runtimes to be rejected. Encoding the refusal
 * as data means the check enforces it instead of a reviewer remembering it.
 */
export const REJECTED_RUNTIMES: ReadonlyArray<{ readonly id: string; readonly reason: string }> = [
  { id: 'nodejs26.x', reason: 'preview; not GA' },
  { id: 'python3.9', reason: 'the local interpreter is 3.9 but the fleet is 3.12; never deploy 3.9' },
  { id: 'nodejs18.x', reason: 'end of support' },
  { id: 'nodejs20.x', reason: 'superseded by 22/24 for new functions' },
] as const;

/** `v<major>.<minor>`, which is the only shape Meta accepts in a Graph URL. */
const GRAPH_VERSION_PATTERN = /^v\d+\.\d+$/;

/**
 * The Graph version, validated.
 *
 * Every Meta call must route through this rather than reading the constant directly, so a
 * malformed value fails loudly at the first call instead of producing a 404 from Meta that
 * looks like a missing resource. Brief §47 / requirements R1.3.
 */
export function graphApiVersion(): string {
  const value = META_GRAPH.configured;
  if (!GRAPH_VERSION_PATTERN.test(value)) {
    throw new Error(
      `Meta Graph version must look like v<major>.<minor>; got ${JSON.stringify(value)}`,
    );
  }
  return value;
}

/** Base URL for a Meta Graph call. The only place a Graph URL is assembled. */
export function graphApiBase(): string {
  return `https://graph.facebook.com/${graphApiVersion()}`;
}

/** Whether a Lambda runtime id is refused in production, with the reason. */
export function runtimeRejection(runtimeId: string): string | null {
  const hit = REJECTED_RUNTIMES.find((entry) => entry.id === runtimeId);
  return hit ? hit.reason : null;
}

export interface DriftFinding {
  readonly key: VendorKey;
  readonly name: string;
  readonly configured: string;
  readonly verifiedLatest: string | null;
  /** `error` fails the check; `warn` reports without failing; `ok` is silent. */
  readonly severity: 'error' | 'warn' | 'ok';
  readonly message: string;
}

/**
 * Compare `configured` against `verifiedLatest` for every tracked version.
 *
 * Pure and dependency-free so it is unit-testable without network or AWS. The CLI in
 * `scripts/check-versions.ts` is a thin wrapper around this.
 */
export function checkVersions(
  versions: Readonly<Record<string, VendorVersion>> = VENDOR_VERSIONS,
  now: Date = new Date(),
): readonly DriftFinding[] {
  const findings: DriftFinding[] = [];

  for (const [key, entry] of Object.entries(versions)) {
    const base = {
      key: key as VendorKey,
      name: entry.name,
      configured: entry.configured,
      verifiedLatest: entry.verifiedLatest,
    };
    const matches = entry.configured === entry.verifiedLatest;

    if (entry.drift === 'must-be-latest') {
      findings.push(
        matches
          ? { ...base, severity: 'ok', message: 'current' }
          : {
              ...base,
              severity: 'error',
              message: `must be latest but is ${entry.configured}, latest ${String(entry.verifiedLatest)}`,
            },
      );
      continue;
    }

    if (entry.drift === 'lag-allowed-with-reason') {
      if (matches) {
        findings.push({ ...base, severity: 'ok', message: 'current' });
      } else if (!entry.upgradeBlockedReason) {
        // The whole point of this policy is that the reason is mandatory. A lag with no
        // stated reason is indistinguishable from nobody having looked.
        findings.push({
          ...base,
          severity: 'error',
          message: 'lags latest with no upgradeBlockedReason recorded',
        });
      } else if (entry.lagExpiresOn && new Date(entry.lagExpiresOn).getTime() <= now.getTime()) {
        // The reason had a deadline and the deadline passed. Keeping it at `warn` would let
        // an expired justification carry indefinitely, which is the failure this field exists
        // to catch.
        findings.push({
          ...base,
          severity: 'error',
          message: `justification expired on ${entry.lagExpiresOn}: ${entry.upgradeBlockedReason}`,
        });
      } else {
        const suffix = entry.lagExpiresOn ? ` [justification expires ${entry.lagExpiresOn}]` : '';
        findings.push({
          ...base,
          severity: 'warn',
          message: entry.upgradeBlockedReason + suffix,
        });
      }
      continue;
    }

    if (entry.drift === 'manual-review') {
      findings.push({
        ...base,
        severity: 'warn',
        message: entry.upgradeBlockedReason ?? 'needs manual review against vendor docs',
      });
      continue;
    }

    findings.push({ ...base, severity: 'ok', message: 'pinned deliberately' });
  }

  return findings;
}

/** The shape mirrored into `config/vendor-versions.json` for the Python fleet. */
export interface VendorVersionsJson {
  readonly generatedBy: string;
  readonly metaGraphApiVersion: string;
  readonly metaGraphApiBase: string;
  readonly metaAuthTemplateName: string;
  readonly metaAuthTemplateLanguage: string;
  readonly wixCatalogVersion: string;
  /**
   * Orders / Transactions / Fulfillments. Replaces the former `wixEcomVersion`, which
   * conflated this family with Cart and Checkout even though only the latter is being
   * removed. Renamed rather than narrowed in place so no reader silently gets a different
   * meaning for the same key.
   */
  readonly wixEcomOrdersVersion: string;
  /** Cart / Checkout. Lags: V2 is latest, V1 is removed 2027-02-01. */
  readonly wixEcomCartVersion: string;
  readonly lambdaPythonRuntime: string;
  readonly rejectedRuntimes: readonly string[];
}

/**
 * Build the JSON mirror.
 *
 * Python cannot import a `.ts` module, and duplicating the version by hand in a Python
 * constant is exactly the drift this file exists to remove. So TS stays canonical and the
 * JSON is generated; `check-versions.ts --write` regenerates it and the plain run fails
 * when it is stale.
 */
export function toJsonMirror(): VendorVersionsJson {
  const [templateName, templateLanguage] = META_AUTH_TEMPLATE.configured.split('/');
  return {
    generatedBy: 'packages/config/vendorVersions.ts via scripts/check-versions.ts --write',
    metaGraphApiVersion: graphApiVersion(),
    metaGraphApiBase: graphApiBase(),
    metaAuthTemplateName: templateName ?? 'wecare_otp',
    metaAuthTemplateLanguage: templateLanguage ?? 'en',
    wixCatalogVersion: WIX_CATALOG.configured,
    wixEcomOrdersVersion: WIX_ECOM_ORDERS.configured,
    wixEcomCartVersion: WIX_ECOM_CART.configured,
    lambdaPythonRuntime: LAMBDA_PYTHON_RUNTIME.configured,
    rejectedRuntimes: REJECTED_RUNTIMES.map((entry) => entry.id),
  };
}
