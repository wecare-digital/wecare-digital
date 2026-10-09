# Service design drafts and Vault delivery

Created through the existing WECARE Meta API credential handling on 9 October 2026. All six are DRAFT with zero Meta validation errors. Names/IDs/expiring preview links are in meta-drafts.json.

These are interactive design previews, not customer fulfillment routes. They use example orders and documents; no verified account lookup, payment, document storage or shipment provider has been connected to these new IDs. Do not publish or replace keyword/catalog routing with them before those contracts are completed.

| Service | Screens | Final button |
|---|---|---|
| Submit Request | Select existing order → describe issue → review | Submit request |
| Request Amendment | Select order → request number and change → review | Submit amendment |
| Drop Docs | Select order → request number, note and PDF/image picker | Submit documents |
| Vault | Catalog → native document list → payment → download template; no Flow | Access Vault |
| Shipments | Select order → sample status and tracking reference | Done |
| Leave Review | Mandatory idea → review | Submit idea |

All drafts reuse the approved review brand banner and native WhatsApp typography. Labels were shortened after checking Meta's mobile truncation warnings. Submit Request, Request Amendment, Drop Docs and Shipments have the same missing-order choice and manual order reference fallback, whose ownership must be verified by the future backend; this preview is not evidence that reconciliation is implemented. The Drop Docs picker accepts up to three PDF/JPG/PNG files, 10 MiB each; secure decryption, storage and association remain integration work. Vault draft 1735480734227899 is unused following the owner's correction. Do not publish or route to it; it is retained only as the previous design record. The generator now builds five active designs and leaves that historical asset untouched.

Published production review 1578178897413815 and paid Submit Request 1107164111921876 were preserved. Business API live stays at 79. Draft preparation ran on immutable, unaliased versions 80–82 with a fixed local asset allowlist. Version 82 hash: qPv6qP6tplGBeKhDN1P2ZMiVpeYfRsPZ2deLo84+z9Q=. Rollback/reference package is 79. No new infrastructure, permissions, live sends, payment operations, Flow publications or catalog mutations were used.

Owner explicitly requested one Flow for each service. Local implementation A1; immutable unaliased backend package A3 under standing authorization; Meta drafts/assets within this explicit request. Live production routing was not changed. Six guard tests passed; related paid Submit Request/review regression selection passed 30 tests total. Meta independently validated each uploaded JSON.

Canonical assets: amplify/functions/messaging/whatsapp-business-api/flows/design-drafts/*.json. build_drafts.py reproduces them. IAM-only serviceDesignDrafts rejects HTTP-shaped requests, publishes nothing, refuses ambiguous or published design names, and reuses each exact draft name on rerun.

Browser check: final Submit Request and Drop Docs upload screens render, with their native submission buttons. Clicking Next/Review in this browser preview did not produce a confirmed transition; inspect screens using the Screen selector. Real handset transition/upload tests remain required before publication. No actual customer file was uploaded.

Latest payment/artwork audit: see payment-artwork-check.md and payment-artwork-check.json. These distinguish live API checks, source behavior and integration gaps.
