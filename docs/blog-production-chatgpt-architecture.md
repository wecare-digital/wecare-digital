# Blog Production Architecture — ChatGPT Editorial / AWS Durable Pipeline

## Decision

ChatGPT is the editorial worker. AWS is the durable source of truth for files, extraction,
production state, article work, protected approvals, publishing, verification and recovery.

No backend AI model is required for Conversations or Gastronomy editorial production.
`AI_ENABLED=false`, `COST_MODE=FREE`, and `autoPublish=false` remain the production defaults.

## Record model

```
blogSource (one uploaded PDF/book/article)
  -> blogArticleIntent x N (should this article exist?)
  -> blogArticleWork x N (the actual independent article)
       -> QA run
       -> human sign-off
       -> publish job
       -> blogPost
       -> verification run
```

A source is evidence. An article work record is a publication unit. This removes the historical
one-source/one-draft constraint without creating a second publisher.

## Completion semantics

- ARTICLE_PRODUCTION_COMPLETE: every accepted article has a body or is HOLD.
- EDITORIAL_REVIEW_COMPLETE: every active article has a human sign-off or is HOLD.
- PIPELINE_COMPLETE: every active article is VERIFIED or HOLD.

Finishing ChatGPT writing releases the editorial lane for the next source. It does not imply
human approval, release, publication or verification.

## Master versioning

The current master is projected under
`secure/blog-production/02-masters/<category>/current/`.
Every prompt/master version is also written immutably under
`secure/blog-production/02-masters/<category>/history/<promptVersion>-<sha>/`.
Legacy `master-current.json`, `prompt-current.md` and `quality-policy.json` keys are retained
as compatibility projections.

Because bucket versioning is suspended, application-level master history is mandatory.

## Dedupe

The backend records deterministic evidence (exact slug/title, near-title, reserved-intent and
distinction/promise similarity). ChatGPT remains responsible for the editorial judgement:
whether an opportunity has a materially different inquiry and reader outcome. Deterministic hard
collisions cannot be overridden as net-new. Body-level corpus comparison still runs in QA before
a human sign-off can be recorded.

## Protected boundary

ChatGPT can write editorial fields only. It cannot write `sourceReviewedFully`, a gate object,
QA sign-off, release, publish or VERIFIED state. Parent source review is projected into child
article work only from the existing human review record.

## Runtime sequence

```
upload -> extract -> claim source -> full source review -> manifest + dedupe evidence
       -> article intents -> article-work children -> sample -> sample/master approval
       -> ChatGPT drafts + editorial QA -> ARTICLE_PRODUCTION_COMPLETE
       -> next source may be claimed

article-work child -> deterministic QA -> human sign-off -> release -> publish
                   -> public readback -> VERIFIED
```

The editorial lane and publication lane are intentionally decoupled: the next source can be
written while previously produced articles wait for protected human review or publication.
