# File audit, repository cleanup and integration closure — 9 October 2026

Reviewed every tracked path at baseline9dc8882e:2091unique files,937tooling/documentation/platform/config files,698backend/test files and456frontend/assets/fixture files. Per-file evidence includes complete metadata hashes, purpose/reference classification, TS-config import resolution and Python/JSON parsing.621Python files parse; frontend local imports all resolve. This establishes complete tracked-file coverage and targeted semantic review, not manual proof of every historical statement or every external provider branch. The full generated inventories stay outside production source to keep the repository light.

## Applied source cleanup and integration

Removed11 proven unused files: AddressMessageComposer, ComingSoon, LocationRequestComposer, OTPTemplateUI, RichTextEditor, unused InfraTab, the selfservice re-export, retired WebRTC hook, exclusive formatters helper and two unused stylesheets. No active route consumer imported these files. Active interactive-location, template, calling, money and shared layout behavior remains. This removes143806tracked bytes. Together with87641626, the two reviewed passes remove128files and1281044current tracked bytes (about1.22MiB), without rewriting Git history. Migration globs, platform resources, public verification assets and dated evidence have real or implicit consumers and remain. ErrorState is retained as an active workspace-MCP patch-policy target; Wix configuration is retained for actual script/test readers.

The shared product vocabulary now drives the active channels hub; labels and descriptions are capability-based and deep links are preserved. The RCS description no longer inaccurately limits all delivery to India. The layout guide publishes the current tree and frontend/backend/script ownership. Active tooling no longer requires deleted steering/skills. Three Kiro resource lists now point to existing guidance; tools, prompts, permissions and foreign hooks are unchanged. Three unused lint suppression comments were retired.

The CSS census fixture was regenerated from its existing scanner after stylesheet retirement and a previously retired pay-link page. It now records62select rules across20files and27geometry rules; checkbox/radio rules remain unchanged. CI compares the committed fixture against current source before tests, closing the previous stale-fixture blind spot rather than weakening its no-new-skins gate.

## Completed payment and scheduling contracts

The payment-address helper rejects unsupported channels before any country/address acceptance; valid website and WhatsApp rules are preserved. Checkout/outbound rollouts change only that archive member.

Scheduling now refuses malformed/nonobject requests and invalid/naive/past timestamps with400, stores explicit instants as UTC, and queries at most50due rows. A conditional exact-PENDING snapshot claim happens before outbound invocation; competing workers, concurrent cancellation and stale edits cannot submit that claimed snapshot again. Stale update/cancel attempts return409. True outbound acknowledgement plus a nonempty provider identifier is required forSENT; dry-run does not becomeSENT. Uncertain invocation/response/storage outcomes remainDISPATCH_UNKNOWN orDISPATCHING for review, with no automatic requeue or Lambda transport retry. This prevents repeated scheduler submissions; existing outbound provider retries remain, so globally exactly-once provider delivery is not claimed.

The client/page now requests explicit status='' for All status, preserving the backend's default pending-only behavior for existing dashboard consumers. Failed/malformed list reads cannot become a fake empty queue. Sending and Needs delivery review are visible, with no automatic resend. Fresh status/timestamp-only inventory found0existing scheduled rows; no customer records were migrated or changed.

| Runtime | Prior live | New live | Archive change |
|---|---|---|---|
| wecare-checkout |37|38|payment_address.py only|
| wecare-outbound-whatsapp |55|56|payment_address.py only|
| wecare-scheduled-messages |24|25|handler.py only|

Account775261844268/us-east-1, owner-authorized root, original-hash/revision/alias guards, preserved unrelated ZIP members and Active/hash readback. Rollback moves each live alias to its recorded prior version using a fresh revision. No provider settings, credentials, payment captures/refunds or customer sends were performed. Inert OPTIONS and invalid-body probes returned the expected200/400; source-owned authentication/send gates remain.

## Verification and practical limits

Full offline Python:10273passed,6skipped,3expected failures. Full frontend:1590passed,2skipped across123files. Typecheck and full static build passed;1521exported pages carry6261JSON-LD blocks, blog reconciliation10checks passed. Exact archive fixtures121passed; UI labels, metadata-only secret verification and current census match passed. Lint0errors191warnings. All five browser suites passed. Current-SHA GitHub CI is recorded in delivery evidence after publication.

The static export was built in an isolated archive without Git history, so sitemap warnings about missing/shared lastmod dates are an archive limitation; current CI uses the real checkout. No fabricated lastmod data was substituted. Passing these checks does not establish live handset, paid checkout or customer/provider journey certification.

Remaining operational prerequisites are explicit: Wix12missing-product intent (mass-disappearance stop preserved), durable tenant-scoped coexistence ingestion plus account consent/routing evidence, authorized live journey/device checks, compatible patches for the known dependency advisories, and per-operation IAM resource mapping before shared-role narrowing. These are not closed by deleting guards, inventing successful provider data or enabling flags. Historical marker inventories remain review evidence rather than permission to remove real capabilities.

Foreign Amplify locks, hooks, inventories, permission tooling, upgrade documentation and active session data are excluded from the scoped commit. The source changes are normal forward commits; no broad staging/reset/history rewrite is used. Root project and publication authority comes from the owner's direct instructions.
