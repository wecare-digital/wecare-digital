# Catalog copy and event repair — 9 October 2026

Owner requested short catalog names and customer-facing descriptions, and repair of paused matching and missing catalog product events.

## Verified live

- Wix-to-Meta projection Lambda `wecare-meta-catalog-sync:live` is version 6. Readback shows zero pending changes, with Submit Request / Get help with your existing order. and Vault / Access and download your documents. Existing prices, artwork, identifiers and gated stock state are retained.
- Catalog matching was resumed in Commerce Manager. The matching-paused notice disappeared.
- Checkout version 40 exposes only catalog IDs, quantities, captured amount and currency on an authenticated PAID attempt with an order number and frozen product references. OPTIONS returned 200 and an unauthenticated status request returned 401.

## Website implementation

- Pixel 3411484995761247 loads only after an explicit optional-cookie choice, on the production website hosts. Tracking is absent from preview hosts and the authenticated workspace shell.
- ViewContent identifies the two published service variants. AddToCart occurs after the service line is actually written. Purchase requires authenticated paid status facts and is deduplicated by payment attempt; URL parameters alone cannot trigger it.
- Unknown products and mixed baskets are omitted rather than attributing an entire payment to one catalog service. No phone number, customer ID, name, address, document or request text is in the event payload.
- The public JavaScript AppEvents page-view logger is removed. Meta documents that SDK approach as deprecated; the website uses the Pixel instead. This does not change authenticated Facebook integration scripts or the WhatsApp app/catalog assignment.
- App-source advertising connection review and provider event-receipt verification are recorded separately from source implementation. An empty mobile app event source is not repaired by inventing mobile SDK events.

## Validation

113 catalog projection/handler checks; 54 checkout/package/purchase-fact checks (including 14 new fact checks); 66 frontend checks. Typecheck and production static export passed with locked dependencies. New analytics files have no lint errors. Two pre-existing warnings remain in the shared app/status files. The live checkout archive's handler matched the committed baseline before the scoped overlay, and alias revisions guard against concurrent replacement.

Meta's historical match-rate report is not a code-quality score. Real consented product interactions and a real verified purchase are required for its missing-event diagnostics to clear. No fake purchases or ad spend are part of this repair. A browser Purchase requires that the customer visit the verified status page; a WhatsApp-only purchase without a website visit needs a separate consented server event path before it can be reported here.

## Rollback

Catalog sync: restore live alias version 5. Checkout: restore live alias version 38. Website: revert this scoped source commit and deploy. Consent denial/revocation stops future Pixel calls. Event-source advertising association can be reconnected in Manage connections if a supported product-tracking app is introduced.

The companion JSON records the pre-website-deployment snapshot. Final provider readback is saved separately after deployment so this document does not imply that a source build proves live event delivery.

References: [Meta Pixel reference](https://developers.facebook.com/docs/meta-pixel/reference/), [Meta cookie consent guidance](https://developers.facebook.com/docs/meta-pixel/implementation/gdpr/), [JavaScript AppEvents deprecation](https://developers.facebook.com/docs/app-events/gamesonfacebook/).
