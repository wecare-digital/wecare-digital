# Blog Production System — work-item plan

Written to disk on 2026-09-29 because it had only ever existed in a conversation, which is
the failure mode `.kiro/steering/multi-session-parallel-agents.md` names explicitly: a
fifteen-item run degrades at the tail when the requirements are remembered rather than
re-read. Tasks 1-5 were already done and pushed when this file was created; they are
recorded here so the numbering in the commit messages resolves to something.

Owner approval to build: "ok under o and GO BUILD" (2026-09-29), following the PHASE 0
read-only audit.

## Standing constraints — these outrank any convenience

| Constraint | Source |
|---|---|
| Bucket is `wecare-digital-get`. Never create a bucket. | `.kiro/steering/blog-production-s3.md` |
| Internal source/working prefixes under `secure/blog-production/`; only published mirrors/catalog under `o/blog-production/`, composed through `media_paths` | owner hardening decision 2026-10-15 |
| `secure/` is the source/working security boundary; `o/` is public and reserved here for deliberate published outputs | measured + owner hardening decision 2026-10-15 |
| No auto-publish. Processing completion never implies publishing. | spec §38 |
| AI can never self-certify. The human gates are unreachable from any model write. | spec §29/§30 |
| Every total derived from records. No incremented counters. | spec §41 |
| Wix writes stay behind `wix_guard`; releasing records intent, it does not publish | repo state |
| One branch, `stack`. Stage by explicit path, chain `add && commit`. | `git-workflow`, `multi-session-parallel-agents` |

## Items

### 1. S3 steering + bucket-creation guard — DONE (`01abcb6f`)
`.kiro/steering/blog-production-s3.md`, `.kiro/hooks/block-s3-bucket-creation.json`,
`scripts/block_s3_bucket_creation.py`, `scripts/verify_s3_bucket_hook.py` (29 cases).

### 2. Wix kill switch on every credential loader — DONE (`01abcb6f`)
`lambda_utils/wix_guard.py`. Applied to the two blog write paths; deliberately NOT applied
to `_load_visitor_access_token`, which would take 1,165 live posts and the sitemap offline.

### 3. Published-corpus dedupe index — DONE (`01abcb6f`)
`scripts/blog_corpus_index.py` + committed `content/conversations/corpus-index.json`
(1,165 posts, 1.4 MB, bottom-k sketches K=128 at 32 bits). Before this the dedupe gate
compared against 383 committed records and reported PASS having checked a third of the
corpus.

### 4. Prefix rename and extract to S3 — DONE (`626cdef0`)
`o/blog-src/` → `o/blog-production/` while it held zero objects. On 2026-10-15 the source/working tree was hardened to `secure/blog-production/` before the first real production source; public catalog/post mirrors remain under `o/blog-production/`. Extract moved out of the
DynamoDB item: a 300-page book is ~450 kB of text against a 400 kB item cap, so the write
failed on exactly the documents the pipeline exists for.

### 5. Batch entity — DONE (`a6f0d578`)
`blog_batches.py`, `batchId-createdAt-index`, paginating `storage.query_index`. Exposed and
fixed the 500-item ceiling in `storage.list_records` that made the worker report
`remaining: 0` with work outstanding. GSI `NonKeyAttributes` capped at 20 by DynamoDB, so
`_view` and the projection were trimmed together to 17.

### 6. SourceAnalysis as a first-class record — DONE (`0c20d3a6`)
**Acceptance:** a source analysis is its own addressable artifact, not a field on the source
row; stored at `o/blog-production/source-analysis/<sourceId>.json` with a DynamoDB pointer;
records what the source says, the candidate distinction, the wrapper to remove, claims
needing a fact check and attribution obligations; is versioned so a re-analysis does not
destroy the one a reviewer read; is never handed out as a public URL even though the prefix
is public; and carries no field that can move an article forward.

### 7. Versioned content templates — DONE (`0c20d3a6`)
**Acceptance:** a template is addressed by `templateId` + integer `version`; editing a
template that any article has been published against creates a new version rather than
mutating it; an article records the exact template version it was written to; a batch's
default template flows onto its sources; the template constrains section order, required
sections and word band, and the gate reads it.

### 8. Generation / QA split with human gate sign-off — DONE (`7dc787a0`)
**Acceptance:** generation and QA are separate recorded operations with separate records; a
QA run is immutable once written, stored at `qa/<articleId>/<qaRunId>.json`; a human gate
sign-off is its own signed record naming the actor, the gates answered and the QA run it
relies on; `READY_TO_PUBLISH` is reachable only with a sign-off present; no model-writable
field can produce one; a sign-off is invalidated when the article body changes after it.

### 9. Collection-level AI repetition detection — DONE (`74f96859`)
**Acceptance:** repetition is detected across a whole batch, not only against the published
corpus; every pair above threshold is reported with both slugs and the score; the sweep is
not O(n²) in sketch comparisons — pairs are prefiltered by shared sketch hashes; the batch
rollup reports how many articles are implicated; and the result is advisory to a reviewer
rather than a mechanical publish block.

### 10. SQS fan-out for bulk ingestion — DONE (`19a1cced`)
**Acceptance:** confirming N sources enqueues N messages rather than starting a self-chaining
sweep; a message that fails repeatedly lands in a DLQ instead of blocking the queue; the
event source mapping is concurrency-capped so a flood cannot starve the API the same function
serves; the sweep survives as an explicit reconciliation route for records with no message;
and the queue is created by the deploy script, idempotently.

### 11. Publish queue with no auto-publish — DONE (`9db93b4b`)
**Acceptance:** an article enters the queue only on an explicit operator release; a release
is refused without a valid gate sign-off; the queue records intent durably and the Wix write
remains behind `wix_guard`, so with writes off a release is recorded and the publish is
refused with a reason; nothing in the batch or worker path can release; and a second release
of the same article is a no-op rather than a second post.

### 12. Thirteen-assertion Wix publish verification — DONE (`4dac67f1`)
**Acceptance:** thirteen named assertions run against the post read back from Wix after a
publish; the result is recorded at `verification/<articleId>/<runId>.json`; a failure is
recorded and surfaced, never silently retried; and the assertion list is enumerated in a test
so it cannot quietly shrink.

### 13. Dashboard routes — DONE (`f067033a`)
**Acceptance:** five pages under the SEO workspace — batches, batch detail, source review, QA
review, publish queue — each reading the routes above, each keyboard reachable and labelled,
and none of them offering a control that could publish without a sign-off.

### 14. Monitoring — DONE (`e89449fe`)
**Acceptance:** alarms for extraction failure rate, DLQ depth, and verification failure, each
routable to a human via the existing SNS topic; created idempotently by the deploy script;
and a test asserting each alarm names an action rather than being created actionless.

## Verification gate for every item

`python3 -m pytest -q` · `npx vitest run` · `npx eslint .` (0 errors) · `npx tsc --noEmit` ·
deploy · live check against the deployed function · remove every record and object the live
check created · commit by explicit path with `add && commit` chained.
