/**
 * Frontend feature flags. Default OFF, always.
 *
 * Phase 7.3 asks for the Growth and Commerce module homes "behind feature flags". There
 * was no flag mechanism in the frontend at all before this, so a flag would have meant
 * a hardcoded `false` somebody later flips by editing a component — which is not a flag,
 * it is a comment.
 *
 * THE DEFAULT IS THE WHOLE DESIGN
 * -------------------------------
 * Every flag reads `false` unless an env var explicitly says otherwise. That matters
 * more than it sounds: a flag defaulting ON means a missing env var in a new environment
 * silently enables the thing the flag was protecting. This project already has the
 * inverse of that lesson written down for `WA_LIVE_SMOKE_TEST`, where switching a flag
 * ON *narrows* sending — a safety switch should fail toward the safe state, and so
 * should its absence.
 *
 * WHAT THESE FLAGS DO NOT CONTROL
 * -------------------------------
 * They gate a **read-only UI surface**. They are not send flags, and they cannot become
 * send flags: the growth and storefront APPLY tools are disabled in
 * `lambda_utils/agent/governance.py`, which no frontend value reaches. `01-standing-
 * authorization.md` lists enabling any live-send path as a refusal, so there is
 * deliberately no flag here that could be mistaken for one.
 *
 * NEXT_PUBLIC_ IS NOT A SECRET
 * ----------------------------
 * These are inlined into the browser bundle at build time, which is correct for "should
 * this panel render" and wrong for anything else. A flag here must never gate
 * authorization — the handler does that, and `require_auth` is not something a browser
 * value can talk its way past.
 */

/** Read a NEXT_PUBLIC_ boolean. Anything other than an explicit truthy string is false. */
function flag ( raw: string | undefined ): boolean {
  return [ '1', 'true', 'yes', 'on' ].includes( String( raw ?? '' ).trim().toLowerCase() );
}

export const featureFlags = {
  // `growthModule` (NEXT_PUBLIC_ENABLE_GROWTH_MODULE) was here. Removed 2026-09-25 along
  // with /growth/index.tsx, its only consumer. A flag with no reader is dead config that
  // still looks like a control, which is worse than no flag: someone sets the env var,
  // nothing changes, and they go looking for the bug in the wrong place.

  /**
   * The Commerce module home: catalog, storefront and order surfaces in one place.
   * OFF because the Wix site is live and production, and a new surface over it should
   * be opened deliberately rather than by deploying.
   */
  commerceModule: flag( process.env.NEXT_PUBLIC_ENABLE_COMMERCE_MODULE ),

  /**
   * Per-order invoice download on /orders/. OFF until `POST /ecommerce/my-invoice` is
   * deployed and its `live` alias moved. While it is OFF every Invoice cell renders the
   * terminal "No invoice yet" text — no button, and **no request is issued at all**.
   *
   * That last part is the reason the gate exists rather than being a nicety. The page
   * would otherwise depend on what an unmatched `/api/*` path returns through the Amplify
   * rewrite; that rewrite is console-side configuration, it is not in this repo, and
   * nobody has measured it. If it answered 200 with an HTML SPA body, `response.ok` would
   * be true, `response.json()` would throw, and every paid order would show a failure with
   * a retry that can never succeed. A flag is cheaper than a measurement we cannot take.
   *
   * Enabling it is an env change plus a REBUILD, not a code edit: NEXT_PUBLIC_ values are
   * inlined at build time, so setting the variable alone changes nothing.
   *
   * The name is `invoiceDownload` and not `myInvoiceRouteLive` because
   * `src/test/FeatureFlags.test.tsx` sweeps flag names for `send`/`live`/`smoke`/`apply`/
   * `routing` — and correctly so: a reader scanning flag names should not have to decide
   * whether "…Live" means "the route is live" or "live sending".
   */
  invoiceDownload: flag( process.env.NEXT_PUBLIC_ENABLE_INVOICE_DOWNLOAD ),
} as const;

export type FeatureFlagName = keyof typeof featureFlags;

/** Every flag and its state, for the diagnostics panel and for tests. */
export function allFlags (): { name: FeatureFlagName; enabled: boolean }[] {
  return ( Object.keys( featureFlags ) as FeatureFlagName[] )
    .map( ( name ) => ( { name, enabled: featureFlags[ name ] } ) );
}
