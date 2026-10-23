# Conversations archive triage

This directory documents the mechanical pre-editorial triage used for the remaining
Conversations archive.

The triage step exists to reduce repeated manual review. It is **not** an editorial
approval system and it must never set a record to `READY_TO_PUBLISH`.

## Inputs

The classifier consumes:

- the formal 1,952-source archive inventory;
- a pending-source CSV containing source file, title, date and archive index;
- the local/private `c4t2(1).zip` archive.

The archive itself is not committed to Git. Only metadata and finished Anew articles may
be committed.

## Mechanical buckets

- `LIKELY_EXISTING_COVERAGE` — strong prior merge/overlap signal. Requires a quick
  distinction-level confirmation against the live corpus before resolution.
- `DEDUPE_REVIEW` — moderate overlap signal. Requires body/distinction comparison.
- `CANDIDATE_NEW_ARTICLE` — title-pass suggests a distinct opportunity and no mechanical
  public-source/fact gate is present. Requires full source reading and human editorial gates.
- `SOURCE_REWORK` — the candidate depends on named source people/programs, source-specific
  terminology, or explicit source scaffolding. Public source/reference/attribution material
  must be removed or independently reconstructed; provenance stays internal-only.
- `PERSONAL_REFERENCE_REWORK` — first-person/private biography plus named-person dependency
  requires removal, generalisation, or omission from public copy.
- `FACT_CHECK_REQUIRED` — the source inventory already requires research in a current or
  specialist factual domain.

Bucket precedence deliberately sends strong overlap to dedupe before other review signals;
a source that is already covered should not receive a new article merely because it also
contains public-source or factual risks.

## Guardrail

A machine bucket is only a routing decision.

No triage result may:

- write human gate PASS values;
- change a record to `READY_TO_PUBLISH`;
- publish anything;
- convert source wording cosmetically;
- preserve or add public attribution as a workaround for source-dependent wording.

Public source/reference/attribution material has no publication exception. If a candidate
requires attribution to remain acceptable, that material must be removed, independently
rewritten where editorially justified, or omitted. Internal provenance may remain in private
metadata and audit records.

Publication belongs to AWS-native Blog Studio. `scripts/conversations_batch.py` validates
and audits Conversations batches and writes no post.

## Current 1,212-source triage

Generated 2026-09-30 from pending positions 26–1237. This table preserves the original
historical triage counts; the legacy `ATTRIBUTION_REVIEW` label now maps to
`SOURCE_REWORK` in active tooling.

| Bucket | Count |
|---|---:|
| SOURCE_REWORK | 722 |
| PERSONAL_REFERENCE_REWORK | 240 |
| LIKELY_EXISTING_COVERAGE | 153 |
| FACT_CHECK_REQUIRED | 58 |
| DEDUPE_REVIEW | 18 |
| CANDIDATE_NEW_ARTICLE | 15 |
| NO_DISTINCT_ARTICLE | 6 |
| **Total** | **1,212** |

Recommended review order for speed without lowering standards:

1. `LIKELY_EXISTING_COVERAGE` has been live-confirmed for all 153 records and is resolved;
2. close the 6 explicit `NO_DISTINCT_ARTICLE` placeholder/non-article sources;
3. review the 15 `CANDIDATE_NEW_ARTICLE` records for genuine new Anew articles;
4. resolve the 18 `DEDUPE_REVIEW` records;
5. process source-rework/privacy and factual-review queues with their required specialist
   checks.

The full generated CSV is retained as the persistent control file in the WECARE.DIGITAL
working Library.

## Reviewed checkpoint after full-source candidate + dedupe passes

The first two post-triage editorial queues are now exhausted.

Resolved from the 1,212-source automated queue:
- confirmed existing live coverage: **170**
- no distinct public article: **9**
- **total resolved: 179**

Active exception queue:
- source-dependent rework: **731**
- personal/private-provenance review: **241**
- factual/specialist review: **61**
- **total active: 1,033**

There are currently **0 clean CANDIDATE_NEW_ARTICLE records** and **0 DEDUPE_REVIEW records**
left after full-source review. The only new article currently surviving the broader
CONV-CONT-01 work is the separately validated `100wattl.html` reconstruction,
**Pleasant Feelings Can Be Reactive Too**.
