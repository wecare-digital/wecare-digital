# Current environment — addendum from an independent read-only pass

Companion to [`current-environment.md`](current-environment.md) and
[`compatibility.md`](compatibility.md). Measured **2026-09-26** against account
`775261844268` / `us-east-1` and Google project `wecaredigitalbw`.

This file **adds measured facts and does not restate, re-rule or overwrite** the other two.
It was written as a separate file rather than appended because `current-environment.md` was
rewritten mid-session by its author, and an append would have been silently lost.

The discovery pass itself changed nothing. One finding was then **fixed** — §1, the
unprotected customer Cognito pool — and that is marked below. No secret value was read at
any point; `get-secret-value` was never called, from any surface.

## Status of the findings in this document

| § | Finding | Status |
|---|---|---|
| 1 | Customer Cognito pool had no web ACL | ✅ **FIXED 2026-09-26** — associated and read back; 8 regression tests |
| 1 | OTP abuse control is per-IP only | ⏳ **PENDING** — spec gap G5, per-phone counter in the handler |
| 1 | HTTP API cannot take a WAF | ⚠️ **DESIGN DECISION REQUIRED** — service limit, not an omission |
| 2 | Blog build fail-open | ➖ **NOT REQUIRED** — already guarded; my `HIGH` rating was wrong |
| 3 | No `ap-south-1` EUM origination identity | ⏳ **PENDING** |
| 3 | `whatsapp-payments-india-reference.md` is 0 bytes | ⏳ **PENDING** — spec task 1.5, owned elsewhere |
| 3 | No CSP on the public site | ⏳ **PENDING** |
| 3 | Google key spans browser + server; Places (New) not allowlisted | ⛔ **OWNER-ONLY** — credential work in GCP |

---

## 1. WAF: the customer-facing pool was the one without protection — now fixed

`current-environment.md` G8 records "no WebACL on `zllr9lrg7j`". Both halves of that need a
correction, and the corrected version is a more serious finding.

| Resource | WebACL before | WebACL now | Measured via |
|---|---|---|---|
| Amplify app `d22dm4b0jn71jw` | `wecare-amplify-waf` | unchanged | `amplify get-app` (`wafStatus: ASSOCIATION_SUCCESS`) |
| Cognito **staff** pool `us-east-1_cSx0RHCIR` | `wecare-cognito-waf` | unchanged | `wafv2 get-web-acl-for-resource` |
| Cognito **customer** pool `us-east-1_46ULYuukt` | **none** | **`wecare-cognito-waf`** | same call, both before and after |
| HTTP API `zllr9lrg7j` | cannot have one | cannot have one | service limit, see below |

**The unprotected pool was the internet-facing one.** `WECARE.DIGITAL-CUSTOMERS` is the
pool this brief puts behind public WhatsApp/email OTP registration; the staff pool is not
internet-facing in the same way, and only the staff pool had an ACL. `scripts/provision_waf.py`
covered one pool, so the gap was invisible to the tool meant to catch it.

**Resolved 2026-09-26.** `scripts/provision_waf.py` now takes a list of resources per ACL
instead of a single one, reports and verifies association **per resource** so a partial
association can no longer read as protected, and associates the customer pool with the
existing regional ACL. Read-back confirms both pools return `wecare-cognito-waf`, and the
Amplify enforcement probe still passes (`GET /` → 200, Log4Shell probe in the query → 403),
so nothing regressed.

One regional ACL protects both pools rather than a second ACL: the rule posture both pools
want is identical, and it avoids another ~$8/month. The cost is coupling — the rate-based
rule aggregates per IP across both pools. Split it when OTP economics demand a tighter,
blocking limit on the customer pool alone.

**This does not close the OTP abuse problem, and should not be read as doing so.** Indian
carriers CGNAT heavily, so a per-IP limit tight enough to stop OTP abuse would refuse real
customers. The rate rule stops a crude single-host flood. The actual control is per-phone
and per-identity in the handler with a persisted send counter — that is spec gap G5, still
open, and still `HIGH`.

**`zllr9lrg7j` cannot be WAF-protected at all.** WAF's protected resource types are
CloudFront, API Gateway **REST**, ALB, AppSync, Cognito user pools, App Runner, Amplify and
Verified Access. `zllr9lrg7j` is apigatewayv2. So the owner's "WAF implemented and
live-verified" target cannot be met for the API by attaching an ACL; it needs a decision —
front the API with CloudFront and attach the CLOUDFRONT-scope ACL, migrate to REST, or
record handler-level controls as the accepted strategy. `scripts/provision_waf.py` already
documents this constraint; `current-environment.md` G8 states it as a gap without noting it
is a service limit rather than an omission.

**A verification trap, recorded because I hit it.** `wafv2 list-resources-for-web-acl`
returns an **empty list** for `wecare-cognito-waf` even with both pools associated — that
call does not enumerate Cognito user pools, Amplify apps or CloudFront. Reading the empty
list as "protects nothing" would be wrong. `get_web_acl_for_resource` per ARN is the
authoritative check.

---

## 2. The blog fail-open is real but already guarded — withdrawing my own finding

I first recorded this as a `HIGH` unmitigated gap. That was wrong, and the correction is
worth more than the original claim.

The fail-open exists exactly as described: `src/lib/public-blog.ts` wraps its `fetch` in
`try { … } catch { return [] }` and also returns `[]` on any non-`ok` response, and
`src/pages/post/[slug].tsx` feeds that into `getStaticPaths` with **`fallback: false`** under
`output: 'export'`. A network blip during a build really does produce zero post pages.

**But the outcome is asserted downstream, and it fails the deploy.**
`scripts/generate-sitemap.js` refuses to write a sitemap when 0 post pages were exported and
exits 1. `package.json` defines `build` as `next build && node scripts/generate-sitemap.js`,
and `amplify.yml` runs `npm run build` — so the guard runs inside the Amplify build and a
non-zero exit fails it. Nothing ships.

The guard also documents the incident that motivated it, on 2026-09-24: one build emitted
125 URLs with 109 post pages, the next emitted 16 with none, from an unchanged tree. And it
explains why it asserts on the **outcome** rather than making `listPublicBlogPosts()` throw:
that function is also safe to call from a browser, where returning `[]` for an unreachable
API beats a crashed page. The build wants the opposite. Asserting on the outcome keeps both.
That is the right call and I am not changing it.

The `ALLOW_EMPTY_BLOG=1` escape hatch has to be typed deliberately.

Measured healthy right now: the endpoint returns `ok: true` with **571 posts**, 0 duplicate
slugs, 0 empty slugs; the live `sitemap.xml` carries **587 URLs = 571 posts + 16 pages**.

Residual risk, stated precisely and **not** inflated: the guard's floor is 1, not a
percentage, on the documented reasoning that the failure mode is all-or-nothing. That
reasoning holds — `listPublicBlogPosts()` performs a single unpaginated fetch of the whole
list, so a truncated-but-non-empty result is not a shape the code can produce. Severity
`LOW`, no action recommended.

### A trap for anyone auditing this repo

The local `out/` directory is a **stale developer artifact** — 520 post pages, built before
the newest 51 posts were published on 2026-09-25. It is not what is deployed. I initially
read `out/` and concluded 51 posts were 404ing in production; fetching the live URLs showed
HTTP 200 with fully rendered content, and the live sitemap carries all 571. **Audit the live
site, not `out/`.**

---

## 3. Smaller measured items not in the other two documents

| Item | Severity | Measured |
|---|---|---|
| **No `ap-south-1` EUM origination identity** | `MEDIUM` | `describe-phone-numbers` in `ap-south-1` returns **empty**; `us-east-1` has `+18444891209` (TOLL_FREE) and `+14255556333` (SIMULATOR). India SMS depends on DLT plus sender registration — verify before relying on India SMS as an OTP fallback |
| **`.kiro/steering/whatsapp-payments-india-reference.md` is 0 bytes** | `LOW` | Injected into every session as an empty rule. Either write it or delete it; an empty steering file is worse than none because it reads as coverage |
| No CSP on the public site | `MEDIUM` | `wecare.digital` returns HSTS, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy` — and no `Content-Security-Policy` |
| 6 retired-provider CloudFormation stacks | `LOW` | `wecare-elevenlabs-{init,mcp,mcp-enable,call-hooks,postcall-sms}` and `wecare-temp-code-inspector`, all 2026-09-19. Retirement candidates; deletion needs pointwise confirmation |
| 8 stale `chatgpt/*` Amplify branches | `LOW` | Auto-build disabled on all 8; `stack` is the only PRODUCTION branch |
| No CodePipeline or CodeBuild | `INFORMATIONAL` | Both empty. CI/CD is GitHub Actions plus Amplify — so "existing deployment pipelines" means those two, not CodePipeline |
| EventBridge is the only scheduler | `INFORMATIONAL` | 6 rules on `default`; EventBridge Scheduler has 0 schedules |

---

## 4. Reproducing everything in this document

```bash
python scripts/provision_waf.py --verify      # WAF association, per resource
python -m pytest tests/test_waf_coverage.py
python scripts/generate_runtime_inventory.py  # Lambda, routes, tables, traffic
python scripts/session_map.py                 # who else is writing to this tree
aws sts get-caller-identity                   # must report 775261844268
```

Note the blog post count moves: 571 at the first probe, 575 an hour later. The endpoint is
live and content is being added, so treat every count here as a timestamp rather than a
constant — which is what `.kiro/steering/00-current-owner-overrides.md` requires anyway.

The WAF associations, SES state, EUM phone numbers and CloudFormation stacks were read with
plain `boto3` `List*`/`Get*`/`Describe*` calls under profile `wecare-prod`. The Google key
restrictions came from `gcloud services api-keys list`, which returns the restriction set
without returning the key string.
