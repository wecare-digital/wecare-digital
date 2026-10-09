# SCOPE EXTENSION #2 — Vault order→download sequence + session continuity (owner, 2026-10-09)

Binding for all remaining steps (investigate, design-review, plan, build-loop, finalize),
additive to the original A–U brief and SCOPE-EXTENSION-whatsapp-hub.md. All safety rules
still bind. DESIGN/AUDIT only — keep every gate CLOSED, change nothing live.

## A — Vault order + download message sequence (new section in outputs/whatsapp-customer-service-architecture.md)
Document, grounded in ACTUAL current code with file:line, how a Vault purchase delivers
the file:

1. **Order message then download-template message.** After a Vault purchase is
   payment-verified and the file-access grant is created: (a) the Vault order/confirmation
   message is sent to the verified customer in WhatsApp, then (b) the download-template
   message `wecare_default_download` (URL `https://wecare.digital/vault/?file={{1}}`) is
   sent. Cite where each send happens, the ordering/guards, and the preconditions (payment
   verified, grant exists, 24h session window vs template requirement; dynamic-download
   release flag — which stays CLOSED).

2. **File origin = S3, time-limited link.** The document is served FROM S3 via a
   short-lived signed URL / secure download token. State the ACTUAL TTL/expiry from current
   code (cite the constant/line; live-evidence.json notes response-content-disposition
   signed prefixes with ~300 seconds). State the object is PRIVATE from first write and that
   ownership/authorization is checked BEFORE any signed URL is issued — a signed URL is not
   the access control, and knowledge of a file ID is not authorization.

3. **Customer delay / link expiry.** If the customer delays and the signed URL/token
   expires: they must re-request access WITHOUT paying again — resume from authoritative
   backend state (paid Vault order → re-issue a fresh short-lived signed download for the
   SAME entitled file; no second charge; idempotent). Trace the actual re-issue code path if
   it exists; if it does NOT exist, record a GAP with severity, smallest-safe-change, and a
   failing-test spec. Do not invent behavior.

4. **Catalog description/availability stays current.** The Vault catalog item's
   description/availability is maintained through the Wix→AWS→Meta sync pipeline (currently
   `read_failed` on the live catalog per findings G/H), with force-out-of-stock until the
   enable gates pass. Cross-reference the catalog-sync root-cause finding.

Format: if current code already does a thing, cite file:line + exact behavior; if partial
or missing, record a GAP in the F-item format (severity, smallest-safe-change, failing-test
spec).

## B — Session-continuity requirement (finalize step must guarantee)
This work must survive a session ending mid-run. The finalize step (and any paused state)
must ensure:
- All durable evidence lives under `.kiro/work/deep-integration-audit/` in the worktree:
  `findings.md`, `answers.md`, `design.md`, `design-review.md/json`, `plan.md`, this file,
  `SCOPE-EXTENSION-whatsapp-hub.md`, and the `outputs/` deliverables.
- A fresh session can resume from these files on disk alone (not chat memory). The master
  continuation prompt for a new session is maintained at
  `outputs/kiro-new-session-continue-prompt.md` (orchestrator writes it; finalize refreshes
  it with the latest re-verified HEAD/origin and workflow status).
- `docs/whatsapp/service-rollout/continue-prompt.txt` is updated ONLY with re-verified facts.

## C — Concurrency reality (re-verify; it keeps changing)
As of this writing a parallel session ("xcodex") is landing commits + Lambda releases
concurrently: local `stack`=53ed298e is now 0 ahead / 10 BEHIND `origin/stack`=e9e377ce,
and extra worktrees exist (`/private/tmp/wd-baseline-e9e377ce`,
`.worktrees/wa-native-payment` at 4e259800). Any new session MUST re-fetch and re-derive
HEAD/origin/live-alias state before trusting any number here. Never overwrite the parallel
session's work; integrate by merge, never force. Every proposed alias move stays
`--revision-id`-conditional and re-read immediately before acting.
