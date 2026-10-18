/**
 * Optional frontend feature flags default OFF. Commerce is always available and has no flag.
 * These switches gate a read-only UI surface, never server authorization or payment sending.
 * Backend apply controls remain in lambda_utils/agent/governance.py.
 * NEXT_PUBLIC_ values are public build-time configuration, not credentials.
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

  /**
   * The attributed "Leave a review" action on /orders/. It opens a customer-initiated
   * WhatsApp message carrying the order reference. The public menu's unattributed Leave Review
   * action is always available through REVIEW_ENTRY_URL and is not controlled by this flag.
   *
   * OFF until the per-order attribution flow is ready end to end. With it OFF, /orders/
   * renders no review row. This gates a link, never a send.
   */
  reviewCta: flag( process.env.NEXT_PUBLIC_ENABLE_REVIEW_CTA ),
} as const;

export type FeatureFlagName = keyof typeof featureFlags;

/** Every flag and its state, for the diagnostics panel and for tests. */
export function allFlags (): { name: FeatureFlagName; enabled: boolean }[] {
  return ( Object.keys( featureFlags ) as FeatureFlagName[] )
    .map( ( name ) => ( { name, enabled: featureFlags[ name ] } ) );
}
