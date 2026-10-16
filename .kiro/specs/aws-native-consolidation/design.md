# Design — Current AWS-native architecture

Reconciled 2026-10-16. This replaces the pre-cutover proposal; `tasks.md` and
`docs/migrations/` retain the dated execution and rollback record. Source and live
configuration take precedence over older counts and proposed flags.

## Stores and public reads

The blog uses `stack-wecare-digital-SeoToolsTable` through the existing native storage
modules. The dedicated public reader and authenticated SEO tools have different deployment
packages; map their actual code before changing a route or assuming they are identical.
Do not provision the parallel BlogPostsTable proposed before the completed migration.

The catalog uses `stack-wecare-digital-ProductsTable`; storefront data is generated into
`src/content/catalog-snapshot.json`. Reuse the existing cart, checkout, reservations,
payment attempts, orders and invoice stores. Authoritative amounts stay server-side and
use integer paise. Razorpay verification and settlement behavior remain intact.

Meta publication reads the native catalog. The approved retailer namespace is
`WECARE.DIGITAL:`. The product stream mapping is enabled. Migration approval/readback and
consumer rollout evidence remain separate from decisions about products outside its scope.

## Frontend consolidation

CON1 Phase 1 uses thin Pages route entrypoints, shared public PageShell/ClosingBand,
breadcrumb/title helpers, a seven-link Contact request hub and a bounded Anew seed backed
by the complete client search index. Preserve current menus and URL behavior. Do not
move the GrahakOS/VayuLok route folders or retire routes as part of this phase.

Production exports fail if the native blog API cannot be read completely. They must retain
all blog URLs, metadata, structured data, sitemap and search-index entries. Full frontend,
Python, export and real-browser checks provide different evidence and must all be reported.

## Secrets and access

Use the existing `shared/lambda_utils/secrets_access.py` helper and domain-specific secrets.
Keep payment API/webhook keys, OTP pepper, flow signing key, backup passphrase, privileged
GitHub credentials and Meta tokens isolated. Discovery reads metadata only. Move config to
Parameter Store only after proving that it contains no secret fields.

Remove obsolete grants only after tracing consumers; preserve unrelated grants on shared
roles. Reconcile IAM changes with their provisioning source. Credential replacement and
backup retention remain separate coordinated actions; do not infer rotation from metadata.

## Voice host

The active host is `wecare-voice-bot-nano` (`nano_3_0`), with the existing static IP attached.
Asterisk/SIP and Meta Calling remain required. The Micro cutover and SMS-proxy retirement
are completed historical changes; a new downgrade or removal of SIP is not proposed here.
Host capacity, certificate and service claims require in-guest evidence. Keep the existing
migration/rollback scripts as history and recovery tooling rather than rerunning them.

## Deployment and operational evidence

Reuse Amplify app `d22dm4b0jn71jw`, branch `stack`, the current API and CloudFront rules.
Do not replace production routing while consolidating page source. Verify the deployed
commit and job status; a successful local build is not a deployment receipt.

The 2026-10-16 audit found a blog-ingest dead-letter message with recent missing
`blog_pipeline` imports. Inspect and repair the deployment package before any redrive.
Retain the failure evidence rather than deleting messages to make the alarm green.

Build and Route auth continue running as informational checks per owner instruction.
Passing checks do not substitute for live health, owner QA payments, secret rotation,
backup policy or unratified URL/product decisions.
