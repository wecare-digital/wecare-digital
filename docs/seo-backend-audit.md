# SEO backend audit — what exists, what was missing, what it costs

Audited 2026-09-30 against the repository and the built export. Every count in this document was
measured, not estimated; the commands are named so each one can be re-run.

## The headline

**Almost all of the requested backend already exists, and the architecture is already the
preferred low-cost stack.** Two things were genuinely missing and both are now built. Nothing
was rebuilt.

The instruction was "do not rebuild working functionality", so the useful output of this audit is
mostly a list of things *not* to build.

---

## 1. What already exists

| Requirement | Status | Where |
|---|---|---|
| Backend-for-frontend API | **exists** | `wecare-seo-tools` Lambda, ~20 routes incl. `GET /blog-public` and `/blog-public/{slug}` |
| Blog API | **exists** | `/blog-public` — the static export builds through it |
| Category API | **exists** | category streams come from `blogIndexProps`, served from the same feed |
| Page API | **exists** | `/page-audit`, `/product-pages` |
| SEO metadata | **exists** | source `seoTitle` / `metaDescription` read through, never replaced |
| Structured data | **exists, extended** | `_app.tsx` (WebPage, BreadcrumbList, Service ×11), `[slug].tsx` (BlogPosting, Recipe ×448), `BlogIndexHead` (Blog, CollectionPage, BreadcrumbList, ItemList ×54) |
| Sitemap generation | **exists** | `scripts/generate-sitemap.js` → static `out/sitemap.xml`, 1355 URLs, 275 kB |
| robots configuration | **exists** | static `out/robots.txt`, with an audited Disallow policy |
| SEO monitoring | **exists** | `search_console_index_audit.py`, `search_console_sitemap.py`, `indexability_audit.py`, `tools/browser/seocheck.js` |
| Search support | **exists** | `out/blog/search-index.json` (446 kB, fetched lazily on first keystroke) + `/mcp` `search_blog` |
| Cache management | **exists** | `/cache-purge` route, CloudFront, `_cacheable()` helper |
| Derived SEO store | **exists** | `stack-wecare-digital-SeoToolsTable`, on-demand, 2 GSIs |
| Optional AI | **exists** | `ai.py` via Bedrock, reachable from one authenticated route |
| IaC | **exists** | AWS CDK (`amplify/*.ts`) — no second framework introduced |

### Measured AWS resource inventory

`grep -rhoE "new (dynamodb|lambda|sqs|events|apigatewayv2|…)\." amplify/*.ts`:

```
4  sqs.Queue
3  dynamodb.Table
2  lambda.Function        (+ 62 functions in scripts/deploy_all_lambdas.py)
1  events.Rule            (Amplify build-failure notification only)
1  apigatewayv2.HttpApi   (HTTP API, not REST — already the cheaper one)
```

**None of the prohibited defaults are present.** Searched for and found nothing: `Vpc`,
`NatGateway`, `FargateService`, `Cluster(`, RDS, Aurora, OpenSearch, ElastiCache, MSK, Kinesis,
EC2, ECS, EKS, App Runner. The site is a **static export** (`next.config.js`:
`output: 'export'`) on S3 + CloudFront, so there is no always-on compute serving pages at all.

---

## 2. What was missing, and is now built

### a. Approved FAQ never reached the page

The whole chain existed and was cut in exactly one place: the blog view returned
`'jsonLd': {}`, because the post source carried none of our schema. `ai.py` generated
FAQ, `_run_audit` stored it, the Admin approved it, and `src/pages/post/[slug].tsx` had rendered
`post.jsonLd.faqSchema` all along.

`faq.py` closes it at the `/blog-public/{slug}` route — the seam the static export builds
through. **Frontend diff is empty.** Only `approved` and `applied` statuses publish;
`pending_review`, `rejected` and `applying` are refused.

### b. The AI audit path had no change detection — a real cost leak

`_run_audit` called `ai.invoke_seo` unconditionally. Auditing a post twice with nothing changed
**paid Bedrock twice for the same answer**. The repository already hashes content for this purpose
in `blog_pipeline.content_hash`, `blog_gate.body_sha256` and `blog_sources`; the SEO audit path
was the one place that skipped it.

`seo_freshness.py` gates it at `_run_audit`, the single choke point both audit routes funnel
through:

```
audit #1   hash absent or different  ->  model called, hash stored
audit #2   hash matches              ->  stored audit returned, ZERO model calls
audit #3   hash matches              ->  same
content edited                       ->  hash differs, model called
```

`force: true` re-runs deliberately, because the hash covers the **content** and not the prompt —
when `ai.py`'s system prompt changes, identical content should be re-auditable without editing
the post, which is the source mutation this architecture forbids.

**`updatedAt` is deliberately excluded from the hash.** A CMS rewrites it for a tag change, a
republish or a migration, none of which change a word the model would read. Trusting the
timestamp would pay for a model call every time the CMS touched a record.

---

## 3. What must not be changed, and how that is enforced

Source content is read-only **structurally**, not by policy:

| Check | Result |
|---|---|
| `faq.py` write calls | none — it adds a field to an API *response* |
| `seo_freshness.py` — `put_item`, `update_item`, `now_iso`, `updatedAt`, `publishedAt`, `dateModified` | **none**, verified by source inspection |
| AI reachable from a public route | **no** — `ai.invoke_seo` has exactly one caller, behind `require_auth` |
| Anything scheduling AI | **nothing** — grepped active application and operational source |

One path does write, and it is legitimate: `storage.apply_blog_audit` writes `seoTitle`,
`metaDescription` and `jsonLd` onto a `blogPost` record in **SeoToolsTable**, and it requires an authenticated `/apply` on an
already-`approved` audit. That is the application's own workflow, which the rules permit.

Worth flagging: it also sets `updatedAt: now_iso()`. Correct for a human-approved apply that
genuinely changes the record, and it must never be reached by a background task.

---

## 4. Cost review

Every resource, and whether it earns its place.

| Resource | Purpose | Required? | Idle cost | Usage cost | Free tier | Cheaper alternative |
|---|---|---|---|---|---|---|
| S3 (`wecare-digital-get`) | media, sitemap, static artifacts | yes | storage only | per GB + requests | 5 GB | none — already cheapest |
| CloudFront | serves the static site | yes | none | per GB + requests | 1 TB/month | none |
| API Gateway **HTTP API** | the BFF | yes | **none** | $1.00/M requests | 1M/month 12mo | already the cheap tier (REST is 3.5×) |
| Lambda (62 functions) | all compute | yes | **none** | per ms | 1M req + 400k GB-s | none |
| DynamoDB on-demand ×3 | app + SEO derived store | yes | **near-zero** | per request | 25 GB | none |
| SQS ×4 | async retry/DLQ | yes | none | per request | 1M/month | none |
| EventBridge Rule ×1 | Amplify build-failure alert | yes | none | negligible | — | none |
| **Bedrock** | optional AI audits | **no** | none | **per token** | none | deterministic templates |

**The only resource that can generate meaningful charges is Bedrock**, and it is reachable from
one authenticated admin route with no scheduler. The freshness gate now makes a repeat audit cost
**zero tokens** instead of a full generation.

### Cost risks found

1. **CloudWatch log retention is not set in CDK.** `grep -rn "logRetention" amplify/*.ts` returns
   nothing — the matches for `retentionPeriod` are **SQS** message retention, not logs. Log
   groups with no retention keep data forever and bill for storage indefinitely. Across 62
   Lambdas this grows quietly. **Recommended: set 14 or 30 days.** Not changed here because it
   touches deployed infrastructure and is an owner decision.
2. **`AI_ENABLED` / `AI_DAILY_BUDGET` / `COST_MODE` do not exist as flags.** AI is gated
   *structurally* (one authenticated route, nothing scheduled), which is stronger than a flag for
   preventing accidental invocation — but there is no spend ceiling. **Recommended** if Bedrock
   use grows.

---

## 5. Running it free / near-free

This is the current default, with nothing to switch off:

- **AI: effectively off.** No scheduler invokes it; it runs only when an admin calls
  `/ai-seo-audit`. A public page request can never trigger a model call.
- **OpenSearch: not deployed.** Blog search is a 446 kB static JSON fetched lazily on the first
  keystroke, so a visitor who never searches downloads none of it. `/mcp` `search_blog` covers
  agents. No evidence yet that this is insufficient.
- **Scheduler: one rule**, for build failures — not polling.
- **Sitemap and robots: static files** built once per deploy, served from CloudFront. No Lambda
  runs to serve them.
- **Structured data: computed at render time**, so it costs nothing at runtime and — more
  importantly — **cannot drift**. A table copy of schema is a second source of truth; that is the
  exact defect that had `/mcp` serving 21 pages while the repo declared 23, fixed in PR #152.
- `SEO_FAQ_PUBLISH=0` stops FAQ publication without a deploy.

---

## 6. Optional paid features — not enabled

| Feature | Trigger | Cost shape |
|---|---|---|
| Bedrock SEO audits | authenticated `/ai-seo-audit` | per token, now deduplicated by `sourceHash` |
| Bedrock FAQ suggestions | same route | same |
| Google Search Console | needs OAuth + project production approval | free API, blocked on approval |
| Google Ads API | blocked: `CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION` | free API |

---

## 7. Deliberately not built

Recording these so the next reader does not mistake them for oversights.

- **A second BFF.** `/blog-public` already is one.
- **A DynamoDB copy of structured data.** Render-time computation cannot go stale; a stored copy
  can. See PR #152.
- **An EventBridge SEO scheduler.** The corpus only changes when a human publishes, and
  publishing already runs the audit route. A daily scan would re-read 1279 posts to find nothing
  changed — the freshness gate makes that cheap, but not running it at all is cheaper.
- **`FAQPage` for ranking.** Google deprecated FAQ rich results on **2026-05-07**, a date
  `src/pages/grahak-os/index.tsx` already records as its reason for removing FAQPage. FAQ is an
  AI/LLM-discovery asset here, not a SERP feature.
- **Merging the 11 near-duplicate post clusters.** The owner has said they are *similar*, not
  duplicate.

---

## 8. Remaining manual AWS configuration

Nothing in this audit's changes requires any. Pre-existing items, unchanged:

1. **CloudWatch log retention** — recommended, see Cost risks.
2. **Google Cloud production access** for `wecaredigitalbw` — blocks the Ads API and Search
   Console tooling.
3. **Rotate the OAuth client secret and Ads developer token** that were pasted into chat.
4. **`/mcp` redeploy** — it carries its own copy of `config/public-pages.json`; the drift check
   added in PR #152 now reports when it is stale.
