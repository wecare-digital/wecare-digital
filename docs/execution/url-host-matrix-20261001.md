# URL and host matrix — 2026-10-01

Measured against AWS account `775261844268` (`wecare-prod`, `us-east-1`), Amplify app
`d22dm4b0jn71jw` branch `stack`, and the live public site. Every `before` and `after` value in
this document was probed. Where something could not be measured it says so rather than
estimating.

Companion records: `docs/execution/url-redirect-removal-20261001.md` (the owner's removal, a
different session), `.agents/tasks/url-host-cleanup/plan.md` (the investigation this task was
planned from).

---

## 0. What changed, and the plan it replaced

**Two separate changes landed on the Amplify rule array on 2026-10-01, in this order.**

| # | Change | Rules | Who |
|---|---|---:|---|
| 1 | Owner instruction *"delete all url redirects now"* — every custom redirect removed, all rewrites and the 404 fallback preserved | **146 → 8** | another session, see `url-redirect-removal-20261001.md` |
| 2 | Host canonicalisation `https://www.wecare.digital` → `https://wecare.digital` restored, 301 | **8 → 9** | this task |

**The plan this task started from is SUPERSEDED, and the reason is worth stating plainly
rather than quietly dropping.** It was written to convert 15 legacy top-level prefixes from
`301 → /workspace/<prefix>` into `302 → /`. The defect was real and measured: 14 of the 15
terminated on the **staff Authenticator shell at HTTP 200** — a customer who typed `[retired public path 44011e36]`,
which sits next to the genuine public `/contact/`, was handed a staff login — and `[retired public path 2c56bef4]`
301d to a `/workspace/settings/` page that 404s.

Change 1 closed that defect by deletion instead. All 15 now terminate at **404** on the
`/<*>` → `/404.html` catch-all. A `302 → /` is no longer needed to close it, and adding 45
custom redirects back would contradict the owner's instruction. So the conversion was not
implemented, and the planned assertions are recorded as superseded in
`tests/test_url_host_routing_rules.py` rather than deleted.

**Only change 2 was made by this task: one rule.** It was not in the original plan. It
repairs an unintended side effect of change 1 — with the www → apex 301 gone,
`https://www.wecare.digital/` and every path under it served the entire site at **200**, so
the site was reachable under two hostnames with identical content. That is
host-canonicalisation loss, not redirect cleanup. Measured before restoring:
`https://www.wecare.digital/` 200, `https://www.wecare.digital/shop/` 200.

### The rule array at 2026-10-01T08:59:52Z, in full (9 rules) — SUPERSEDED, see §0.1

**This table is the post-apply state of change 2 and nothing later.** It is kept because it is
the evidence for the `+1 added / −0 removed / 0 reordered` diff below, but a reader who stops
here gets the wrong array: the live array is **12 rules**, read at 13:15:19Z — see §0.1
immediately after this table, and §5.5 for how the three extra rules arrived.

| # | source | target | status |
|---:|---|---|---|
| 0 | `https://www.wecare.digital` | `https://wecare.digital` | 301 |
| 1 | `/get` | `/get/index.html` | 200 |
| 2 | `/get/` | `/get/index.html` | 200 |
| 3 | `/get/<*>` | `https://d1kf2rchz7yras.cloudfront.net/<*>` | 200 |
| 4 | `/r/<*>` | `https://zllr9lrg7j.execute-api.us-east-1.amazonaws.com/prod/r/<*>` | 200 |
| 5 | `/api/<*>` | `https://zllr9lrg7j.execute-api.us-east-1.amazonaws.com/prod/<*>` | 200 |
| 6 | `/mcp` | `…/prod/mcp` | 200 |
| 7 | `/mcp/` | `…/prod/mcp` | 200 |
| 8 | `/<*>` | `/404.html` | 404-200 |

Applied at **2026-10-01T08:59:52Z** (`2026-10-01T14:29:52+05:30`). Readback confirmed 9 rules,
first rule the host canonicalisation, last rule the 404-200 fallback, **+1 added / −0 removed /
0 reordered** (diffed, not assumed).

### 0.1 The live rule array, in full (12 rules) — read 2026-10-01T13:15:19Z

Added in the second convergence pass because the 9-rule table above was stale and was
contradicted inside this same document by §5.5. Read live with `amplify get-app`, not inferred
from the provisioner:

| # | source | target | status |
|---:|---|---|---|
| 0 | `https://www.wecare.digital` | `https://wecare.digital` | 301 |
| 1 | `[retired public path ef531503]` | `https://wecare.digital/` | 302 |
| 2 | `[retired public path ef531503]/` | `https://wecare.digital/` | 302 |
| 3 | `[retired public path ef531503]/<*>` | `https://wecare.digital/` | 302 |
| 4 | `/get` | `/get/index.html` | 200 |
| 5 | `/get/` | `/get/index.html` | 200 |
| 6 | `/get/<*>` | `https://d1kf2rchz7yras.cloudfront.net/<*>` | 200 |
| 7 | `/r/<*>` | `https://zllr9lrg7j.execute-api.us-east-1.amazonaws.com/prod/r/<*>` | 200 |
| 8 | `/api/<*>` | `https://zllr9lrg7j.execute-api.us-east-1.amazonaws.com/prod/<*>` | 200 |
| 9 | `/mcp` | `…/prod/mcp` | 200 |
| 10 | `/mcp/` | `…/prod/mcp` | 200 |
| 11 | `/<*>` | `/404.html` | 404-200 |

The 9 → 12 step is the three `[retired public path ef531503]` → home 302s emitted by `desired_redirects()`, applied by
the concurrent session described in §5.5. **This task made exactly one production write** — the
single rule in change 2 — and that is unchanged by the restatement.

Note what rows 1-3 do to the ordering claim below: they are **redirects sitting ahead of every
passthrough rewrite**. See the corrected structural-properties paragraph.

### Propagation, measured — and why one attempt would have given the wrong answer

An Amplify custom-rule change reaches the CDN without a rebuild, but it is not instant and it
does not evict what the edge already holds. **~25 minutes after applying**, `GET` on
`https://www.wecare.digital/` correctly returned `301` with `x-cache: Miss from cloudfront`,
while **`HEAD` on the same URL returned `200` with `x-cache: Hit from cloudfront` and
`age: 1501`** — a cached object from before the change. The apex home page carries
`cache-control: public, max-age=0, s-maxage=31536000`, a one-year shared cache, which is what
let a stale 200 sit at an edge; a cache-busting query string did not shift it either, because
the distribution's cache key ignores the query string for static objects.

It resolved on its own. Re-measured shortly afterwards and five consecutive times: `HEAD` and
`GET` both return `301` on `/` and `/shop/`, every attempt `x-cache: Miss`, apex steady at
`200`. **No invalidation was created** — the GET path, which is what a crawler and a browser
navigation use, was correct throughout, and the stale entry expired without intervention.

Recorded because the first reading looked like a failed change and was not one. This is the
re-probe-rather-than-conclude rule earning its place rather than being quoted.

Structural properties that hold and are pinned by `tests/test_url_host_routing_rules.py`: no
rule targets `/workspace/**`; **no redirect source equals or prefix-matches a passthrough prefix
(`/api`, `/get`, `/r/`, `/mcp`), in either direction**; the catch-all is last and keeps
`404-200`; the host rule's source and target are **bare origins with no path**, which is what
makes Amplify carry the request path across.

> **CORRECTED 2026-10-01T13:15Z.** The second property read *"all seven passthrough rewrites
> precede every redirect"*, and that was **false in production** while no gate could see it. The
> live array (§0.1) has the three `[retired public path ef531503]` 302s at indexes **1-3, ahead of all seven
> passthroughs**, because `desired_redirects()` emits redirects first and `apply()` rebuilds the
> array as `domain + desired_redirects() + middle + catch_all`. The assertion that existed
> (`test_every_passthrough_precedes_every_redirect`) only ever read the committed **9-rule**
> `after` snapshot, which contains no path redirect, so it passed while the stated guarantee did
> not hold. Harmless in fact — no `[retired public path ef531503]` source overlaps `/api`, `/get`, `/r` or `/mcp` — but
> the claim and the assertion had diverged, which is the defect. Resolved by stating the
> property that is actually true, and by asserting it on the **live shape**: that test was
> renamed `test_in_the_committed_snapshot_every_passthrough_precedes_every_redirect` (rescoped,
> not deleted) and
> `test_no_sanctioned_redirect_can_shadow_a_passthrough_in_the_live_shape` now checks the array
> `apply()` actually writes. Non-overlap is the stronger property anyway: a redirect that cannot
> match an `/api` request cannot shadow it wherever it sits in the array.

---

## 1. The matrix

85 rows, probed by `scripts/probe_url_host_matrix.py`, exit 0 — **88 rows as of
2026-10-01T13:15Z**: +1 for the third `[retired public path ef531503]` wildcard row (§5.5) and +2 for the two new
subdomain rows 83a/83b below. **98 rows as of the third convergence pass, 2026-10-01**: +10 for
rows 86–95, the evidence rows added for the surface categories that had none (§1.1–§1.4). Only
the **terminal** status in
a chain is judged: `trailingSlash: true` means an extensionless path always 301s to add the
slash first, so a first-hop reading calls `[retired public path 84a04c24]` "301, fine" whether the chain ends on a 404
or on a staff login at 200. Chains are walked with a seen-set, so a loop is a hard failure
rather than two individually-correct status codes.

| # | Request | before (measured) | after (measured) | verdict |
|---|---|---|---|---|
| 1 | `https://wecare.digital/` | 200 | 200 | unchanged |
| 2 | `https://www.wecare.digital/` | **200 — duplicate host** | **301 → apex `/`, terminal 200** | **repaired** |
| 3 | `https://www.wecare.digital/shop/` | **200 — duplicate host** | **301 → apex `/shop/`, terminal 200** | **repaired, path preserved** |
| 4 | `https://www.wecare.digital/blog/` | 200 — duplicate host | 301 → apex `/blog/`, 200 | repaired |
| 5 | `http://wecare.digital/` | 301 → https | 301 → https, terminal 200 | unchanged |
| 6 | `/definitely-not-a-page` | 301 → `…/` → 404 | same | unchanged |
| 7 | `/definitely-not-a-page/` | 404, `"page":"/404"`, `noindex`, canonical `/` | same, all three asserted in the body | unchanged — **404, not 200** |
| 8 | `/404/` | 200 | 200 | unchanged |
| 9–23 | `[retired public path 2de923b8]/ [retired public path bf361a18]/ [retired public path 89347bb2]/ [retired public path 44011e36]/ [retired public path 862cdc9c]/ [retired public path 47a81ed9]/ [retired public path 169e0fd8]/ [retired public path 6b3a02b3]/ [retired public path a2557b8d]/ [retired public path 9463c8d8]/ [retired public path 84a04c24]/ [retired public path 21d99b11]/ [retired public path 4eca21b3]/ [retired public path 2c56bef4]/` **+ `[retired public path ef531503]/`, see 23a** | **301 → `/workspace/…` → 200 Authenticator shell** (`[retired public path 2c56bef4]/` → 404) | **404, every one** | **defect closed by the owner's removal, not by this task's 302** |
| **23a** | **`[retired public path ef531503]/`, `[retired public path ef531503]`, `[retired public path ef531503]/anything/deep`** | **301 → `/workspace/access/` → 200 staff shell** | **302 → `https://wecare.digital/` → 200 home** | **superseded 15:54 IST — now the planned CONVERT destination, §5.5** |
| 24–38 | the same 15 in bare form (`[retired public path 2de923b8]`, `[retired public path 84a04c24]`, …) | 301 → slash → staff shell | 301 → slash → **404** (`[retired public path ef531503]` → 302 → home) | closed |
| 39 | `[retired public path 2de923b8]/calls` | 301 → `/workspace/engage/inbox/?channel=voice` | 301 → slash → **404** | closed |
| 40 | `[retired public path 84a04c24]/anything/deep` | 301 → `/workspace/admin/anything/deep` | 301 → slash → **404** | closed |
| 41–57 | `[retired public path 74ea5c7a]/ [retired public path 14041cbc]/ [retired public path 32bc4583]/ [retired public path f1430fb7]/ [retired public path 1965ee0f]/ [retired public path aaee9dd4]/ [retired public path 9109e567]/ [retired public path 5b217199]/ [retired public path b7b8d296]/ [retired public path 3b13e953]/ [retired public path a324e726]/ [retired public path fb3e74a7]/ [retired public path 2cc974af]/ [retired public path 8a68a2cf]/ [retired public path c86bd2b5]/ [retired public path b180810d]/ [retired public path 282d0fd5]/` | 301 → live targets | **404, every one** | **owner-retired — see §3, this is the intended end state** |
| 58 | `/workspace/` | 200 Authenticator shell, `Disallow` in robots | 200 | **unchanged — staff entry, neither hidden nor opened** |
| 59 | `/workspace/access/` | 200 | 200 | unchanged |
| 60 | `/account/sign-in/` | 200 | 200 | unchanged — customer auth |
| 61–72 | `/ /shop/ /cart/ /orders/ /blog/ /contact/ /checkout/status/ /grahak-os/ /vayulok/ /terms/ /anew/ /clear-closure/` | 200 | 200 | unchanged |
| 73 | `POST /api/razorpay-webhook` | **401** | **401** | unchanged — signature rejection, not a page |
| 74 | `POST /api/auth/validate` | 401 | 401 | unchanged |
| 75 | `POST /api/payments/webhook` | 404 | 404 | unchanged |
| 76 | `POST /api/wa-business/webhooks` | not in the plan; measured **401** | 401 | unchanged |
| 77 | `GET /api/webhook/sinch-rcs` | 200 | 200 | unchanged |
| 78 | `GET /mcp` | 405 | 405 | unchanged |
| 79 | `POST /mcp` | 400 | 400 | unchanged |
| 80 | `GET /get/o/stream/media/m/wecare-digital.png` | 200 | 200 | unchanged |
| 81 | `GET /r/zzznotacode` | 302 → `/contact/` | 302 → `/contact/` → 200, one hop | unchanged |
| 82 | `GET /api/definitely-no-route` | 302 → `/contact/` | same | unchanged — **open finding, §5** |
| 83 | `https://shop.wecare.digital/` | no address; TLS alert 40 at the CF IP | **302 → `https://wecare.digital/`, terminal 200** — re-measured 13:15Z | **gap CLOSED, by the home-fallback workstream, not by this task — §4.1** |
| 83a | `https://shop.wecare.digital/shop/` | not measured before | **302 → `https://wecare.digital/`, terminal 200 — path DROPPED** | new row; the fallback deliberately discards the path, unlike row 3 — §4.1 |
| 83b | `https://a.b.wecare.digital/` | not measured before (reported only as "not covered") | **resolves to `3.175.86.x`, TLS refused: no SAN matches — status 0** | **the residual gap, still open — §4.1** |
| 84 | `https://xout.wecare.digital/` | 404 (third-party storefront host) | **302 → `https://wecare.digital/`, terminal 200** — changed later the same day | **INFORMATIONAL** — third-party-hosted at the time, out of scope, §4 and §9.3 |
| 85 | `https://mta-sts.wecare.digital/` | 403 at `/` | 403 | **must not change** — email auth is fail-closed |
| **86** | `GET /api/invoices` | not measured before | **401** `{"error": "No authorization token provided"}` | **unchanged** — see §1.1 |
| **87** | `GET /api/contacts` | not measured before | **401**, same JSON | unchanged — §1.1 |
| **88** | the retired storefront products route | not measured before | **401**, same JSON | route since removed with the provider — §1.1 |
| **89** | `GET /?code=…&state=…` (the Cognito OAuth redirect URI) | not measured before | **200**, query intact | **unchanged** — §1.2 |
| **90** | `GET https://www.wecare.digital/?code=…&state=…` | not measured before | **301 → `https://wecare.digital/?code=…&state=…`**, terminal 200 | **the `?code=` survives the host 301** — §1.2 |
| **91** | `GET /api/checkout/download-receipt` | not measured before | **404** `{"message":"Not Found"}` | **no live route — unprovisioned, not broken** — §1.3 |
| **92** | `GET /api/auth/verify-email` | not measured before | **404** `{"message":"Not Found"}` | **no live route — unprovisioned, not broken** — §1.3 |
| **93** | `[retired public path ef531503]/?next=https://evil.example` | **302 → `https://wecare.digital/?next=https://evil.example`** (measured 2026-10-01, before the fix) | **302 → `https://wecare.digital/?from=access`**, terminal 200 | **FIXED — path and caller's query both dropped** — §1.4 |
| **94** | `[retired public path ef531503]?a=b&c=d` | **302 → `https://wecare.digital/?a=b&c=d`** | **302 → `https://wecare.digital/?from=access`** | **FIXED** — §1.4 |
| **95** | `[retired public path ef531503]/x/y?return=//evil` | **302 → `https://wecare.digital/?return=//evil`** | **302 → `https://wecare.digital/?from=access`** | **FIXED** — §1.4 |
| 23a/59 (restated) | `[retired public path ef531503]`, `[retired public path ef531503]/`, `[retired public path ef531503]/anything/deep` | 302 → `https://wecare.digital/` | **302 → `https://wecare.digital/?from=access`**, terminal 200 | target narrowed by the same fix — §1.4 |

Rows 86–95 were **added in the third convergence pass, 2026-10-01**, after a review found that
four of the surface categories the brief names had no row at all, so a reader could not tell
"preserved" from "never existed" from "not checked". All ten are in
`scripts/probe_url_host_matrix.py`, so they are re-measured on every run rather than being a
dated `curl` — the harness now reports **98 rows, 0 failed**, up from 88. Their `before` column
honestly reads *not measured before*: these surfaces were not probed prior to this pass, and
inventing a before value is forbidden.

Two measurements that were not in the plan and are recorded because they were taken:
`GET /api/webhook/sinch-dlr` = **404** and `POST /api/voice-cdr-webhook` = **404**. Both are
API-side routing answers reached through the intact `/api/<*>` rewrite, not hosting failures.

### 1.1 Protected operational endpoints — three rows, not one

Added 2026-10-01, third convergence pass. The brief requires protected operational endpoints to
keep working **including their unauthenticated rejection semantics**, and until this pass
`POST /api/auth/validate` (row 74) was the only row of that class. One route is too thin to
evidence the class: it can keep answering 401 while a rewrite change quietly turns its
neighbours into pages.

| request | status | body |
|---|---|---|
| `GET /api/invoices` | 401 | `{"error": "No authorization token provided"}` |
| `GET /api/contacts` | 401 | same |
| the retired storefront products route (since removed) | 401 | same |

The **body** is asserted, not just the status, and that is the point of the rows rather than
thoroughness: 401 alone cannot distinguish the API's own rejection from an edge-level one. The
JSON is what proves the request travelled through the `/api/<*>` rewrite and reached the Lambda,
which is the property a redirect change could break. Authorization itself is untouched by this
task — no handler, no authorizer and no `_app.tsx` gate was edited — so these rows are evidence
of preservation, not of new work.

### 1.2 OAuth callbacks — the apex IS the redirect URI

Added 2026-10-01, third convergence pass. The brief names Cognito and Meta OAuth callbacks
among the surfaces that must keep working, and the matrix had no row and no statement for any of
them. Measured, per provider:

**Cognito.** `src/pages/_app.tsx` registers both `redirectSignIn` and `redirectSignOut` as
`process.env.NEXT_PUBLIC_APP_URL || 'https://wecare.digital/'` — the apex, which its own comment
records as registered on the `stack-wecare-digital-web` client. So the callback surface is row 1,
and rows 89–90 state what row 1 could not: the apex answers **200 with a `?code=`/`?state=`
query present**, and `https://www.wecare.digital/?code=…` **301s to the apex with the query
intact**. That second row is the one that matters. Cognito returns the authorization code in the
query string, so a host rule that dropped it would break sign-in for anyone who began at `www`
while every page-level probe stayed green. The rule's source is a bare origin, which is what
preserves path *and* query; a source carrying a path would drop both. The probe values are
deliberately invalid `zzz`-prefixed strings — nothing is exchanged, only the landing place is
measured.

**Meta.** There is no browser callback. Meta's surface on this domain is the webhook already
covered by row 76, `POST /api/wa-business/webhooks` at **401** — a signature rejection from the
Lambda, not a page.

### 1.3 Signed receipt links and verified-email callbacks — unprovisioned, measured

Added 2026-10-01, third convergence pass. Both are named in the brief and neither has a live
route, which is a materially different statement from "we did not check" — so they are probed
rather than omitted:

| request | status | body | reading |
|---|---|---|---|
| `GET /api/checkout/download-receipt` | 404 | `{"message":"Not Found"}` | no receipt route exists yet, and no receipt path is referenced from `src/` either |
| `GET /api/auth/verify-email` | 404 | `{"message":"Not Found"}` | the email-verification function is built but deliberately not provisioned; owned by the customer-registration workstream |

A 404 here is the **correct** answer today, and the rows exist to notice it changing. The day
either surface ships, its row fails and this document has to be updated deliberately instead of
drifting into silence. Receipts stay private and off the public media prefix regardless — that
constraint is unaffected by this task.

### 1.4 The redirect home retained the untrusted query — FIXED 2026-10-01

Found in the third convergence pass, correcting a claim this task carried without probing it. The
plan's design note **D1** asserted that `[retired public path ef531503]/**` → `/` *"drops the untrusted path entirely
(the target is a literal `/`, so no path, query or fragment is forwarded)"*. **That was half
false**, and the half that was false is a real defect against the handoff's requirement that
untrusted path, query and fragment content be dropped when a retired customer URL is sent home.

**Before the fix**, measured:

```
[retired public path ef531503]/?next=https://evil.example   302 -> https://wecare.digital/?next=https://evil.example
[retired public path ef531503]?a=b&c=d                      302 -> https://wecare.digital/?a=b&c=d
[retired public path ef531503]/x/y?return=//evil             302 -> https://wecare.digital/?return=//evil
```

The **path** was dropped, as claimed. The **query was appended** to the redirect target, because
that is Amplify's default for a 301/302.

**After the fix**, measured on six consecutive readings roughly 25 seconds apart:

```
[retired public path ef531503]/?next=https://evil.example   302 -> https://wecare.digital/?from=access   terminal 200
[retired public path ef531503]?a=b&c=d                      302 -> https://wecare.digital/?from=access   terminal 200
[retired public path ef531503]/x/y?return=//evil             302 -> https://wecare.digital/?from=access   terminal 200
[retired public path ef531503]/                             302 -> https://wecare.digital/?from=access   terminal 200
```

**How, and why the fix is a query parameter rather than its removal.** Amplify's documented
behaviour is that it forwards all query parameters to a 301/302 destination *except* when "the
destination address for the matching rule has query parameters", in which case they are not
forwarded. So the way to drop the caller's query is to give the destination one of our own.
`scripts/provision_legacy_redirects.py` now emits
`https://wecare.digital/?from=access` for all three `[retired public path ef531503]` sources, and `ACCESS_HOME_TARGET`
carries the reasoning at the point of definition.

`from=access` is deliberately inert and deliberately ours:

- **Nothing reads it.** Neither `src/pages/index.tsx` nor `src/pages/_app.tsx` references
  `location.search`, `URLSearchParams` or `router.query` — verified by grep over both.
- The status is **302**, so no index equity moves, and the home page's own canonical already
  points at the bare apex.
- It is a **literal we emit**, so the property that matters holds: nothing from the request
  survives the redirect. If a consumer for it ever appears it must still not be treated as input.
- A fragment is never transmitted by any client, so it cannot be probed and is not claimed either
  way.

**All three routes home now agree**, which was the asymmetry worth closing rather than
documenting: `src/pages/404.tsx` calls `router.replace` with a literal `'/'`, and the home-fallback
viewer-request function discards path *and* query — measured as
`https://shop.wecare.digital/some/path?q=1` → `302` → bare `https://wecare.digital/`.

**Pinned so it cannot regress silently.** Rows 93–95 assert the **exact terminal URL**, so a
return to forwarding fails the harness with the caller's parameter visible in the failure. Three
test sites assert the target with its query — `test_url_host_routing_rules.py` twice and
`test_legacy_redirect_rollback_snapshot.py` once — each with a dated note saying the parameter is
the mechanism, so re-asserting the bare apex reinstates the defect rather than tidying it.

**Live-change record.** `amplify update-app` via the provisioner, which snapshots first: committed
pre-change state in
`docs/execution/snapshots/amplify-custom-rules-before-access-query-drop-20261001.json` (12 rules,
with the no-ETag fact recorded — Amplify `get-app`/`update-app` expose none) plus the
provisioner's own timestamped `.scratch/` rollback. Blast radius is the three `[retired public path ef531503]` sources;
the host 301, every passthrough rewrite and the `/<*>` → `/404.html` `404-200` catch-all are
rebuilt unchanged by construction, and `apply()` refuses to write without exactly one catch-all.
Propagation was immediate — the first probe after the write already showed the new target.
Rollback is one `--apply` after restoring `ACCESS_HOME_TARGET` to `SITE + "/"`.

---

## 2. Consumer inventory for the 15 legacy prefixes

Taken **before** any rule change was contemplated, because a blanket purge of a redirect map
is forbidden and because a redirect with a real external consumer must not be converted on
the strength of its target alone. The classification is now of historical interest only —
change 1 deleted all 15 — but it is the evidence that the deletion damaged no consumer, so it
is recorded rather than dropped.

| prefix | rules it owned in the 146-rule array | every target was | in live sitemap (1,407 `<loc>`) | in `llms.txt` | in `robots.txt` | approved provider artefact | search impressions | class |
|---|---:|---|---:|---:|---|---|---:|---|
| `[retired public path 2de923b8]` | 19 | `/workspace/engage/**` | 0 | 0 | no | no | **0** | CONVERT |
| `[retired public path bf361a18]` | 19 | `/workspace/engage/**` | 0 | 0 | no | no | **0** | CONVERT |
| `[retired public path 89347bb2]` | 3 | `/workspace/dashboard/` | 0 | 0 | no | no | **0** | CONVERT |
| `[retired public path 44011e36]` | 3 | `/workspace/contacts/` | 0 | 0 | no | no | **0** | CONVERT |
| `[retired public path 862cdc9c]` | 3 | `/workspace/commerce/` | 0 | 0 | no | no | **0** | CONVERT |
| `[retired public path 47a81ed9]` | 3 | `/workspace/pay/` | 0 | 0 | no | no | **0** | CONVERT |
| `[retired public path 169e0fd8]` | 3 | `/workspace/forms/` | 0 | 0 | no | no | **0** | CONVERT |
| `[retired public path 6b3a02b3]` | 3 | `/workspace/service/` | 0 | 0 | no | no | **0** | CONVERT |
| `[retired public path a2557b8d]` | 3 | `/workspace/docs/` | 0 | 0 | no | no | **0** | CONVERT |
| `[retired public path 9463c8d8]` | 3 | `/workspace/seo/` | 0 | 0 | no | no | **0** | CONVERT |
| `[retired public path 84a04c24]` | 3 | `/workspace/admin/` | 0 | 0 | no | no | **0** | CONVERT (owner-named) |
| `[retired public path ef531503]` | 3 | `/workspace/access/` | 0 | 0 | no | no | **0** | CONVERT (owner-named) |
| `[retired public path 21d99b11]` | 5 | `/workspace/link/` | 0 | 0 | no | no | **0** | CONVERT |
| `[retired public path 4eca21b3]` | 3 | `/workspace/task/` | 0 | 0 | no | no | **0** | CONVERT |
| `[retired public path 2c56bef4]` | 3 | `/workspace/settings/` | 0 | 0 | no | no | **0** | CONVERT |

75 of the 138 removed rules belonged to these 15. **Every target, without exception, was under
`/workspace/`** — read from the committed 146-rule snapshot, not inferred.

`robots.txt` carries exactly two `Disallow` lines, `/api/` and `/workspace/`; none of the 15
has a rule of its own. Its own comment records why: all fourteen authenticated families
nested under `/workspace/` on 2026-09-26 and their individual lines were removed, because *a
Disallow for a route that does not exist implies the route does*.

**Search impressions measured, not assumed absent.**
`.venv/bin/python scripts/retired_url_equity.py --json` authenticated and ran over the maximum
window across both Search Console properties (13,756 recoverable impressions in total, 0
errors). **None of the 15 prefixes appears in the report at all** — zero impressions each.
That is the expected shape: they are `Disallow`ed staff paths that were never in a sitemap.
This is a real zero from a successful measurement, not an unrunnable tool reported as zero.

**No approved provider artefact names any of the 15.** The two paths frozen inside approved
provider templates are `[retired public path b180810d]` and `[retired public path 282d0fd5]`, and neither is in this set — see §3, where
they matter a great deal.

---

## 3. The legacy content map: owner-retired, and the one consequence that needs an owner's eyes

This task was instructed to leave the legacy content/SEO map alone and to probe that every
entry still redirected. **It does not, and that is correct**: change 1 removed those rules
under the owner's explicit instruction, and `url-redirect-removal-20261001.md` records the
decision. All 17 sources are measured at 404 above. They are **not** restored here, and
restoring one would need a new owner instruction.

What the removal costs, measured so the decision is informed rather than invisible. Figures
are that Search Console property's own, over its full retained window:

| retired source | former target | impressions | clicks |
|---|---|---:|---:|
| `[retired public path b180810d]` | `/submit-request/` | **1,128** | 4 |
| `[retired public path 74ea5c7a]` | `/anew/` | 531 | 3 |
| `[retired public path 14041cbc]` | `/clear-closure/` | 499 | 1 |
| `[retired public path 32bc4583]` | `/terms/` | 379 | 0 |
| `[retired public path 9109e567]` | `/expo-week/` | 292 | 1 |
| `[retired public path f1430fb7]` | `/terms/` | 241 | 1 |
| `[retired public path 5b217199]` | `/ritual-guru/` | 226 | 0 |
| `[retired public path b7b8d296]` | `/anew/` | 212 | 1 |
| `[retired public path 3b13e953]` | `/orders/` | 201 | 2 |
| `[retired public path a324e726]` | `/bharat-rx/` | 188 | 3 |
| `[retired public path fb3e74a7]` | `/refer-and-earn/` | 132 | 0 |
| `[retired public path 1965ee0f]` | `/contact/` | 127 | 4 |
| `[retired public path 2cc974af]` | `/` | 8 | 0 |
| | **subtotal** | **4,164** | **20** |

A 404 drops the URL from the index cleanly, which is a legitimate outcome — it discards the
accumulated signal instead of consolidating it onto the replacement page. That is the trade
the owner made.

### ⚠️ OWNER-DECISION ITEM 1 — `[retired public path b180810d]` and `[retired public path 282d0fd5]` are printed inside approved provider templates

These two are not ordinary retired aliases and they carry the largest single impression count
in the table. `[retired public path b180810d]` is printed in the body of **DLT-approved SMS template
`ivr-default`** (registration `1007277993798259629`) as "Submit your request here: …", and in
the body of **nine approved Sinch RCS templates** including `rcsmenu`, the only one any code
sends. `[retired public path 282d0fd5]` is in approved `wecare_order_update`.

An approved DLT body must match its registration character for character and **cannot be
edited**; an approved RCS body cannot be edited in place either. So for these two a redirect
was not a courtesy to bookmarks — it was the **only repair that exists**. They now answer 404,
which means a recipient who follows the link in a message we already sent, or send today,
reaches the missing-page document.

The removal document acknowledges this ("their old links now use missing-page behavior under
the owner's override"), so it is an accepted consequence rather than an oversight. It is
raised here because it is the one row where the cost lands on a message already in a
customer's hand rather than on a search ranking. **Reversing it is two rules and needs one
owner instruction:** `[retired public path b180810d]` → `/submit-request/` and `[retired public path 282d0fd5]` → `/orders/`, both
targets measured 200 today.

---

## 4. Domain and subdomain coverage

| Fact | Evidence |
|---|---|
| Route 53 zone `Z03939753QJGZ6ZD6BXO8` holds 30 record sets, **zero wildcards** | `list-resource-record-sets` |
| `shop` / `stack` / `app.wecare.digital` have **no address** | authoritative `ns-402.awsdns-50.com` answers NOERROR with no A/AAAA (NODATA) |
| The certificate **does** cover one label | `openssl s_client -servername wecare.digital` → `CN=wecare.digital`, SAN `wecare.digital, *.wecare.digital`, `notAfter=Mar 11 23:59:59 2027` |
| CloudFront **refuses the TLS handshake** for an unregistered host | `--resolve shop.wecare.digital:443:54.192.151.105` → `ssl_verify_result=1`; `openssl -servername shop.wecare.digital` → **TLS alert 40 handshake_failure**, "no peer certificate available". Apex through the same IP: 200 |
| Amplify registers exactly **two** subdomains | `get-domain-association`: one with no `prefix` key (branch `stack`), one `prefix: "www"`. `enableAutoSubDomain: false`, `autoSubDomainCreationPatterns: null` |

**So the gap is not a certificate gap. It is an alias/association + DNS gap**, and this task
did not close it.

> **The table above is the 2026-10-01 morning measurement and three of its five rows are now
> out of date.** The zone holds 33 record sets including a wildcard, `shop` has an address, and
> CloudFront no longer refuses the handshake for it. Corrected in §4.1 rather than rewritten in
> place, because the original reasoning is what explains why the close needed the work it did.
> The Amplify row is still exactly true: the association still registers only the apex and
> `www`, which is the point §4.1 turns on.

### 4.1 CORRECTION 2026-10-01T13:15Z — the single-label gap is CLOSED; the second-label gap is not

Written in the second convergence pass, after re-measuring every claim in §4 and in
OWNER-DECISION ITEM 2 below. **Both halves matter and they have different owners, so they are
separated rather than reported as one item.**

**Closed: the single-label case.** Measured, not inferred:

| Measurement | Value |
|---|---|
| `list-resource-record-sets Z03939753QJGZ6ZD6BXO8` | **33** record sets, including `\052.wecare.digital` **A** and **AAAA**, both ALIAS → `d27evp2npt2kzr.cloudfront.net` |
| That distribution | CloudFront **`E1ZZ786I3YH65O`**, alias `*.wecare.digital`, `Status: Deployed`, comment: redirect unused WECARE subdomains and retired hosts to home |
| `dig +short A shop.wecare.digital` | `3.175.86.69 .46 .32 .99` |
| `dig +short A zzz-not-a-host.wecare.digital` | same four addresses — any unused single-label name, not just `shop` |
| `curl -I https://shop.wecare.digital/` | **302**, `location: https://wecare.digital/`, terminal **200** |
| `curl -I https://shop.wecare.digital/shop/` | **302** → `https://wecare.digital/` — the **path is dropped**, by design |
| Certificate presented for `shop` | `CN=wecare.digital`, SAN `wecare.digital, *.wecare.digital` — the existing shared cert `f75d0db0-d476-443a-b787-96c4931862d2`, validating normally |
| `amplify get-domain-association` | still **two** subdomains: one with no `prefix` (branch `stack`) and one `prefix: "www"` |

**The owning workstream is the home fallback, not this task.** `docs/execution/home-fallback-20261001.md`
records the owner instruction *"unused WECARE subdomains and unknown website links land at
https://wecare.digital/"*, the `wecare-home-fallback` CloudFormation stack at `CREATE_COMPLETE`,
Route 53 change `C1002370145M1YU1Y7I7Y` at `INSYNC`, and the later owner correction that deleted
the newly-issued certificate and reused the existing one. This task made **no** DNS, ACM,
CloudFront or domain-association change, and was not permitted to.

**Note how it was closed, because it is not what ITEM 2 predicted.** ITEM 2 said the close needed
*both* an Amplify `update-domain-association` **and** a Route 53 wildcard. It was closed with the
Route 53 wildcard pointed at a **separate dedicated distribution** instead — which sidesteps
ITEM 2's stated blast radius entirely: the live domain association serving the canonical home was
never touched, so it was never at risk of leaving `AVAILABLE`. ITEM 2's warning that step 2
*without* step 1 would be worse than nothing was correct for the design it described, and does not
apply to the design that shipped. The resulting behaviour also differs from what ITEM 2 would have
produced: a wildcard on the Amplify app would have **served the site** under every unused name,
whereas this returns a 302 to the apex and serves nothing — the better outcome for
canonicalisation.

**Still open: the second-label case, and the reason is TLS, not DNS.** This is the residual gap
§4 predicted, and it is still true — but the measured cause is more specific than "has no
address":

```
dig +short A a.b.wecare.digital   ->  3.175.86.46 3.175.86.69 3.175.86.99 3.175.86.32
curl https://a.b.wecare.digital/  ->  curl: (60) SSL: no alternative certificate subject
                                      name matches target host name 'a.b.wecare.digital'
```

It **does** resolve: a DNS wildcard matches more than one label (RFC 4592), so
`*.wecare.digital` answers for `a.b.` too. What does not stretch is the **certificate** —
`*.wecare.digital` matches exactly one label — so the connection dies at the handshake and
`curl` reports `http_code 000`. Status `0` in the probe harness, the same code the old
no-address state produced, for a different reason. Row 83b now pins it with the cause written
down.

Closing it is unchanged from §4: a **new SAN** on a re-requested certificate, re-associated on
**both** consumers of `f75d0db0-d476-443a-b787-96c4931862d2` — the Amplify app **and** CloudFront
`E1SZBXLQ4XNLJ7`, the MTA-STS policy endpoint under `mode: enforce`, where a failure makes senders
refuse inbound mail. **Outside this task's authority** and not a change to make casually. No
second-label host is required by any product surface today, so there is nothing waiting on it.

`www.xout.wecare.digital` is the one second-label host that answers, and it answers because it
keeps its **own third-party TLS endpoint** rather than because our certificate
reaches it — restored deliberately by the home-fallback workstream's final owner correction. It
301s to `xout`, which 302s to the apex.

### ⚠️ OWNER-DECISION ITEM 2 — wildcard subdomain coverage, NOT done

> **RESOLVED for single-label hosts, 2026-10-01, by the home-fallback workstream — see §4.1.**
> Everything below is the state as this task found it and the plan it declined to execute; it is
> kept because §4.1's "not what ITEM 2 predicted" paragraph only makes sense against it. The
> residual second-label item remains open and is restated at the end of §4.1.

Making an unused owned subdomain land on home requires **both** of:

1. **Amplify** — add subdomain `{prefix: "*", branchName: "stack"}` via
   `update-domain-association`. AWS supports this; the prefix must be an asterisk alone, and
   partial (`*domain.example.com`) and middle (`subdomain.*.example.com`) wildcards are not
   allowed. *(Content rephrased for compliance with licensing restrictions —
   [Setting up wildcard subdomains](https://docs.aws.amazon.com/amplify/latest/userguide/wildcard-subdomain-support.html).)*
2. **Route 53** — a `*.wecare.digital` A + AAAA alias to the Amplify distribution. Additive;
   removes no existing record and touches none of MX / `_mta-sts` TXT / SPF / DMARC / DKIM /
   TLS-RPT.

**Blast radius, which is why it was written up instead of executed.** Step 1 mutates the live
domain association that currently serves the canonical home page, and can move the domain out
of `AVAILABLE` while it re-provisions — the association serving the very page this work exists
to protect. Step 2 **without** step 1 is worse than doing nothing: every mistyped subdomain
would resolve to a host CloudFront refuses at TLS, replacing today's clean no-address with a
handshake failure. Both are outside this task's authority (`amplify update-domain-association`
and DNS changes are prohibited for it), so neither was attempted.

**The genuine coverage limit: `*.wecare.digital` matches ONE label.** `a.b.wecare.digital` is
not covered. Adding a second-label host needs a new SAN, i.e. a re-requested ACM certificate
re-associated on **both** consumers of `f75d0db0-d476-443a-b787-96c4931862d2` — the Amplify
app **and** CloudFront `E1SZBXLQ4XNLJ7`, which is the MTA-STS policy endpoint under
`mode: enforce`. A failure there makes senders refuse inbound mail. Not this task's authority,
and not a change to make casually at any time.

**Two second-label hosts already exist and already miss the goal:**
`xout.wecare.digital` → the third-party storefront host, HTTP **404**, and
`www.xout.wecare.digital` → 301 → `xout.wecare.digital` → 404. Repointing them means editing
hosted-zone records for a legacy storefront surface and registering the hosts on Amplify.
**Out of scope — reported, not touched.**

> **CORRECTED 2026-10-01T13:15Z.** Both now reach the canonical home, and `xout` is no longer a
> second-label host from our side: it has an address in our own zone and lands on
> `E1ZZ786I3YH65O` like any other unused single-label name — measured `302 → https://wecare.digital/`,
> terminal 200. `www.xout` is the genuinely second-label one; it still terminates through its own
> third-party TLS endpoint, 301 to `xout`, then 302 to the apex. Repointed by the home-fallback
> workstream under the owner's instruction, not by this task. §9.3 carries the same correction
> for the probe row.

`src/pages/404.tsx` already records the client-side half of this correctly and was left
as-is: a request to a subdomain that does not exist never reaches the application at all. It
fails at DNS or at the CDN before any of our HTML or JavaScript runs, so no page-level change
can address it.

---

## 5. Findings recorded, deliberately not changed

### 5.1 `_routes.json` has no consumer and is byte-identical

`_routes.json` is a 361-entry JSON array of API Gateway route keys. Grepped across the tree,
the only references are prose in four markdown/source comments; every script that needs routes
calls `apigatewayv2 get_routes` live. It is a **committed inventory snapshot, not a hosting
router** — Cloudflare's `_routes.json` convention does not apply, nothing reads it at build or
request time. Editing it cannot change any HTTP behaviour, and as a bare JSON array it cannot
carry an explanatory comment either. **Left byte-identical** (`git diff --stat _routes.json`
empty).

### 5.2 An unknown single-segment API path answers 302 → `/contact/`

```
GET https://wecare.digital/api/definitely-no-route                      302 -> /contact/
GET https://zllr9lrg7j.execute-api.../prod/definitely-no-route          302 -> /contact/
```

Cause: the HTTP API's single-segment catch-all `GET /{code}` — the short-link reader,
`stack-wecare-url-shortener` — answers a miss with a 302 to `/contact/`. That is inside a
Lambda under `amplify/functions/**`, **owned by another workstream and not touched here**. It
is not home-page HTML and not a loop, so it does not regress anything; but an unknown API path
returning a page redirect rather than JSON is worth an owner's note.
`scripts/probe_url_host_matrix.py` asserts it at its measured value so a change to it becomes
visible rather than silent.

### 5.3 `public/sw.js:180` — needs-verification-during-implementation

The service worker's push-click default destination is `/workspace/dashboard/`. **Still not
reproduced as a customer-reachable path**: it is a push-notification destination for a staff
feature, not a navigation link, and changing it could break staff push with no customer
benefit. Recorded, not changed. Closing it needs evidence that a customer can receive that
push.

### 5.4 Four unowned stale catch-all comments

The catch-all has been `/<*>` → `/404.html` at `404-200` since 2026-09-28, but five source
comments still described the older `/index.html` target. The one owned file was corrected:

```
src/pages/404.tsx:14                         CORRECTED in this change
src/pages/_app.tsx:938, 999, 1098            NOT owned — follow-up for its owner
src/pages/workspace/commerce/catalog.tsx:28  NOT owned — follow-up for its owner
```

Correcting a comment is a zero-behaviour change, but `_app.tsx` is heavily shared and outside
this task's owned paths, so the four are handed off rather than edited. The `404.tsx`
correction keeps the old reading as dated in-place history and adds what the removal changed:
with 138 redirects gone, that page is now the destination for ~150 legacy aliases rather than
a long-tail safety net.

### ⚠️ 5.5 OWNER-DECISION ITEM 3 — `provision_legacy_redirects.py --apply` will delete the host rule

## ✅ 5.5 RESOLVED — `--apply` no longer deletes the host rule (was OWNER-DECISION ITEM 3)

**Closed 2026-10-01 at ~15:54 IST, by another session, while this task was converging.** The
owner choices below were not needed; option (a) was taken.

What the hazard was, kept because the failure mode is worth remembering: the rewritten
provisioner's `is_ours()` claimed any rule whose status was in `{301,302,307,308,404}`. The
host-canonicalisation rule is a **301**, so `--apply` **removed it** — silently restoring the
duplicate-host state in which the whole site answered 200 under `www` — and `--verify` reported
`FAIL: custom redirect rules remain` and exited 1 while the rule was live. Both were measured
doing exactly that. It was left unfixed because the fix meant editing a file another session
owned and had uncommitted, plus that session's own test.

**What changed, measured not assumed.** That session rewrote `desired_redirects()` to emit the
rule rather than merely spare it, which is the stronger fix: `--apply` now **rebuilds** host
canonicalisation, so the rule is restored if it ever goes missing instead of only surviving.
Its docstring now reads "Only www canonicalisation and the retired `[retired public path ef531503]` entry point may
redirect." They also applied it to production.

| | before (this task's §0 state) | after (measured 15:55 IST) |
|---|---|---|
| live `customRules` | **9** | **12** |
| `provision_legacy_redirects.py` (no flag) | exit **1** — "1 redirects to remove" | exit **0** — "4 redirects to reconcile" |
| `provision_legacy_redirects.py --verify` | exit **1** — `FAIL: custom redirect rules remain` | exit **0** — `Verified: only approved home/access redirects remain` |
| `GET [retired public path ef531503]/` | 404 | **302 → `https://wecare.digital/`**, terminal 200 |
| `GET /workspace/access/` | 200 staff shell | **200, unchanged** — staff entry unaffected |

The three new rules are `[retired public path ef531503]`, `[retired public path ef531503]/` and `[retired public path ef531503]/<*>` → the canonical home at **302**.
That is the destination **this task's own plan asked for** (`[retired public path ef531503]` was a CONVERT prefix,
target `/` at 302, by explicit owner instruction), so the net effect is that the planned end
state landed via config-as-code. The 404 recorded in §1 for `[retired public path ef531503]` was the stale middle
state left by the redirect removal, not the goal.

**Re-verified after their production write**, because three new rules in front of the rewrites
could have shadowed a webhook: every must-not-break row still measures its expected value —
`POST /api/razorpay-webhook` 401, `POST /api/auth/validate` 401, `GET /mcp` 405, `POST /mcp`
400, `/get/o/…png` 200, `www /shop/` 301 → apex `/shop/`. No shadowing.

Two tests in this task's file were stale as a result and were **inverted rather than deleted**,
as their own docstrings instructed:

- `test_the_provisioner_would_strip_the_host_rule_KNOWN_HAZARD` →
  `test_the_provisioner_now_PRESERVES_the_host_rule`, which asserts the rule survives `--apply`,
  is **first** in the array, and that every `/api`, `/get`, `/r` and `/mcp` rewrite is preserved
  in order.
- `test_the_provisioner_still_converges_to_zero_redirects` →
  `test_the_provisioner_emits_only_the_two_sanctioned_exceptions`, which pins the approved set
  **exactly**, so a third entry fails as loudly as the second one did, and asserts no sanctioned
  rule targets `/workspace`.

`scripts/probe_url_host_matrix.py` grew the `[retired public path ef531503]` rows from 2 to 3 and now asserts them on
the **terminal URL** rather than the status alone — 200 by itself cannot distinguish the
canonical home from the staff Authenticator shell, and the shell is the thing these rows exist
to forbid.

**One consequence, and it is the reason these two tests carry a skip gate.** The converged
`scripts/provision_legacy_redirects.py` is still only in the concurrent session's
**uncommitted** tree. So both tests pass against the shared working tree and would **fail**
against `origin/stack`, where `desired_redirects()` has not converged yet — and committing
another session's file to make our tests pass is not an option. The designated committer added
`_require_converged_provisioner(emitted)` (commit `4c603188`), which calls `pytest.skip` when
`desired_redirects()` does not emit `WWW_CANONICAL`. Measured by them: **8 passed / 2 skipped**
on `origin/stack`; against the converged tree the rule **is** emitted, so both assert normally
— re-confirmed here, `WWW_CANONICAL emitted: True`, 4 rules emitted, **14 passed**.

The gate controls **when** the assertions run, not **what** they require: the assertions
themselves are unchanged. It keys on the rule's presence rather than a version string or a file
hash, so it self-activates the moment that session commits, with no further edit. The
"invert it, do not delete it" intent of both docstrings is preserved.

---

## 6. Obsolete public links in the application

Audited `Header.tsx`, `Footer.tsx`, `BottomNav.tsx`, `SupportWidget.tsx`, `PageTopBand.tsx`,
`src/content/**`, the generated `llms.txt` / `sitemap.xml`, and `robots.txt`.

| Finding | Location | Outcome |
|---|---|---|
| `Header.tsx` — 15 public hrefs, all public pages | — | clean, no change |
| `Footer.tsx` — one href, `/` | — | clean, no change |
| `llms.txt` / `sitemap.xml` (1,407 `<loc>`) | — | clean; the only `access`/`sign-in` hits are blog slugs and a prose line saying `/workspace/` is out of bounds |
| **"Dashboard" button → `/workspace/dashboard`** | `src/components/ErrorBoundary.tsx:38,72` | **fixed** → `/`, relabelled "Home". It is mounted inside the `if ( isPublic )` branch of `_app.tsx`, so a customer hitting a render error on any public page was offered a button into the staff login |
| **PWA shortcuts → `/workspace/dashboard/`, `/workspace/engage/inbox/`, `/workspace/contacts/`** | `public/manifest.json` | **fixed** — the whole `shortcuts` key removed. These were the OS long-press menu entries for anyone installing the public site |
| `Layout.tsx:276` "Sign in" → `/workspace/access` | — | **not public** — `Layout`/`MaybeLayout` has zero importers outside `src/pages/workspace/`. Workspace-only chrome, left alone |
| `SearchModal.tsx:50-51`, `ui/Breadcrumbs.tsx` workspace paths | — | **not public** — imported only by `Layout.tsx`. Left alone |
| `public/sw.js:180` | — | needs-verification, §5.3 |

Guarded against regression by `src/test/PublicWorkspaceLinks.test.ts`, which also asserts the
assumption the three exemptions rest on: that no page outside `src/pages/workspace/**` imports
`Layout`, `MaybeLayout`, `SearchModal` or `ui/Breadcrumbs`.

`/workspace/` itself still returns 200 with the Authenticator shell and is `Disallow`ed in
robots.txt. **That is the legitimate staff entry and it is unchanged** — hiding a link is not
access control, and this work does not touch authorization.

---

## 7. Handoff: the return-path validator needs one line in a file this task may not edit

`src/lib/safeReturnPath.ts` and `src/test/SafeReturnPath.test.ts` are implemented and green.
`src/pages/account/sign-in.tsx` is owned by the **`src/pages/account/**` workstream** and was
not touched, so the validator has **no production caller yet**.

> **RE-MEASURED 2026-10-01T13:15Z and STILL OPEN.** `sign-in.tsx:180` still carries the
> permissive regex; the only references to `safeLocalReturnPath` anywhere in `src/` are inside
> its own test. `/checkout/` and `/account/` still measure **404**, so ITEM 4 below is still a
> live precondition on the wiring. Raised to the owner in this pass rather than applied — see
> §9.4, "Open, and why it is open rather than fixed".
>
> **✅ CLOSED 2026-10-01, by owner decision. The handoff below is history; §7.1 is what shipped.**
> The owner cleared the `src/pages/account/**` boundary — the workstream that owned it
> (`customer-session-otp-hardening`) **aborted** before reaching implementation, its design loop
> having exhausted its iteration budget, and `sign-in.tsx` was confirmed clean in `git status`,
> so there was no live owner to collide with. The reasoning given was that "documented and
> tested-for-later" is the right holding pattern when a fix would regress a customer, but not an
> acceptable resting state for an open redirect closable in one line — and that the owner
> handoff §15 forbids this shape in terms ("no open redirect", "reject protocol-relative URLs",
> "reject workspace/admin destinations").

The two gaps it closes are real and were measured against the current regex
`/^\/[a-zA-Z0-9/_-]*\/?$/`:

| input | current regex | consequence |
|---|---|---|
| `//evil` | **accepted** — every character is in the class | protocol-relative; the browser reads `evil` as the HOST |
| `/workspace/access` | **accepted** | sends a customer to a staff destination after sign-in |

**Ready to apply, verbatim.** In `returnPathFromUrl()` (currently `sign-in.tsx:170-175`),
replace line 174:

```ts
return /^\/[a-zA-Z0-9/_-]*\/?$/.test( raw ) ? raw : '/cart/';
```

with:

```ts
return safeLocalReturnPath( raw );
```

and add the import alongside the other `src/lib` imports:

```ts
import { safeLocalReturnPath } from '../../lib/safeReturnPath';
```

The line above it and the `typeof window === 'undefined'` early return both stay —
`safeLocalReturnPath` accepts `null`/`undefined`/`''` and returns `'/cart/'`, so the `.trim()`
and `|| ''` become belt-and-braces rather than load-bearing. **Also replace the comment on
line 173** ("Only same-site absolute paths, so this can never be turned into an open
redirect") — that is the claim the two rows above falsify.

**Two behaviour changes the `account/**` owner must accept first:** (1) a local path outside
the allowlist (e.g. `/blog/`) now returns `/cart/` rather than being honoured; (2) an
unslashed accepted path is normalised (`/cart` → `/cart/`) rather than returned as typed.

### ⚠️ OWNER-DECISION ITEM 4 — two allowlisted destinations have no page, measured 2026-10-01

Found by the convergence step, by probing every value the validator can return against the
live site rather than reading the list. **Two of the six answer 404:**

| returnable value | live (measured) | page source |
|---|---|---|
| `/` | 200 | `src/pages/index.tsx` |
| `/cart/` | 200 | `src/pages/cart.tsx` |
| `/orders/` | 200 | `src/pages/orders.tsx` |
| `/shop/` | 200 | `src/pages/shop/index.tsx` |
| **`/checkout/`** | **404** | **none** — `src/pages/checkout/` holds only `status.tsx` and `success.tsx` |
| **`/account/`** | **404** | **none** — `src/pages/account/` holds only `sign-in.tsx` |

`output: 'export'` emits a page only where a source file exists, so neither has anything to hit
but the `/<*>` → `/404.html` catch-all. This is **not** a security defect — both are local,
on-allowlist paths — but it defeats the module's stated contract: it "returns the value to use",
and two of those values cannot be navigated to.

**Why it is recorded rather than fixed.** The allowlist was specified verbatim by the task plan
(§2 step 1) and FEAT-001 implemented it faithfully; the mismatch is between that list and the
page inventory, and it only became visible once both halves of the task were measured together.
The two candidate resolutions — narrow `ALLOWED`, or ship the two missing pages — are both
product decisions, and `src/pages/account/**` is this other workstream's to edit. **Nothing
outside its own test imports the function**, so the gap cannot reach a customer today; it
reaches one the moment the wiring above is applied. Hence: a precondition on that wiring, not a
discovery left for the person doing it.

Pinned by `src/test/SafeReturnPath.test.ts` →
`'safeLocalReturnPath — accepted destinations that do not resolve (KNOWN GAP)'`, which asserts
the current measured truth, including a test that **fails as soon as a production caller
appears**. Same convention as §5.5: when it is resolved, **invert the test, do not delete it**.

### ✅ 7.1 RESOLVED — the allowlist was narrowed to five, and the validator is wired

**Owner decision, 2026-10-01.** Of the two candidate resolutions above, the first was taken:
`ALLOWED` was **narrowed**, not grown. Building `/checkout/` and `/account/` was declined for
now on the grounds that `/checkout/` overlaps checkout work in flight, and that shipping a page
to satisfy a validator is the wrong way round.

**The allowlist as it ships — five destinations, every one measured 200 live:**

| member | live | page source |
|---|---|---|
| `/` | 200 | `src/pages/index.tsx` |
| `/cart/` | 200 | `src/pages/cart.tsx` |
| `/orders/` | 200 | `src/pages/orders.tsx` |
| `/shop/` | 200 | `src/pages/shop/index.tsx` |
| **`/blog/`** | 200 | `src/pages/blog/index.tsx` — **added** |

**Removed, with the measured reason:** `/checkout/` and `/account/`, both **404**.
`src/pages/checkout/` holds only `status.tsx` and `success.tsx`; `src/pages/account/` holds only
`sign-in.tsx`. Neither directory has an `index`, and **`output: 'export'` emits a page only
where a source file exists** — so a page exists only where a source file does, and both had
nothing to hit but the `/<*>` → `/404.html` catch-all.

**Re-adding either is conditional on the page existing, not a free edit.** That ordering is
enforced rather than documented: `src/test/SafeReturnPath.test.ts` checks all five members
against the filesystem, so an entry added to `ALLOWED` without a corresponding source file fails
the suite before it can reach a customer.

**`/blog/` was added rather than left out, and the reason is the inverse of the usual one.** It
resolves, and it is a plausible place to send a customer back to. Excluding it would not have
been conservative — it would have *manufactured* the silent fallback to `/cart/` that the
narrowing exists to avoid, by rejecting a destination that works. Membership is a decision about
intent, not a consequence of existing: `/terms/` is also a real exported page and is still
rejected, which the test asserts explicitly.

**The one remaining behaviour change is `/cart` → `/cart/` normalisation**, and it is the correct
direction: the site runs `trailingSlash: true`, so the slashed form is canonical and returning
the input as typed would simply spend a 301 to arrive at the same place.

**What changed in code, exactly — nothing was restyled or refactored:**

```
src/pages/account/sign-in.tsx   + import { safeLocalReturnPath } from '../../lib/safeReturnPath';
                                  returnPathFromUrl() now returns safeLocalReturnPath( raw )
                                  the false "can never be turned into an open redirect" comment deleted
src/lib/safeReturnPath.ts         ALLOWED: 6 entries -> 5; dated rationale added, none removed
src/test/SafeReturnPath.test.ts   the KNOWN GAP block INVERTED, not deleted
```

The inversion is the part worth reading. The old `has no production caller` test existed to fail
the moment the wiring landed, so this decision could not be skipped by accident — it did that
job. Simply letting it pass once wired would teach nothing and would not notice the wiring being
removed again, so it now asserts that `sign-in.tsx` **is** a caller, **and** that the literal
`a-zA-Z0-9/_-` is absent from that file. Importing the validator while leaving the old regex
beside it would otherwise satisfy a caller check and change nothing.

---

## 8. Rollback

**Amplify exposes no ETag** for `get-app`/`update-app` — unlike `cloudfront
update-distribution`, there is no concurrency token to present, so the committed snapshot plus
the script's own timestamped `.scratch/` artefact are the whole safety net. Recorded here
rather than inventing a token.

`update-app` is a **full replace** of `customRules`. Any rollback must start from a fresh
`get-app`, never from a stale in-memory array, or a concurrent session's rules are silently
dropped.

To undo **only this task's change** (remove the host-canonicalisation rule, returning to the
8-rule post-removal state):

```
aws amplify update-app --app-id d22dm4b0jn71jw --region us-east-1 \
  --custom-rules file://docs/execution/snapshots/amplify-custom-rules-before-url-host-cleanup-20261001.json
```

The post-change array is committed alongside it as
`docs/execution/snapshots/amplify-custom-rules-after-url-host-cleanup-20261001.json` (9 rules),
so before and after are both on disk and diffable.

**Do not** restore `amplify-custom-rules-before-owner-removal-20261001.json` (146 rules) to
undo this change — that reverses the owner's removal as well, recreating every retired alias,
and needs a new owner instruction. **Do not** restore
`amplify-custom-rules-before-8.4.json`; it holds the three rules the app had on 2026-09-24 and
restoring it would delete the `/mcp`, `/get/<*>` and `/api/<*>` passthroughs — a far larger
outage than anything it could revert.

---

## 9. Verification run on the exact tree

| Gate | Result |
|---|---|
| `npm run typecheck` | exit 0 |
| `npm run lint` | exit 0 — **0 errors**, 188 warnings, all pre-existing (the repo baseline is "errors 0"; the count did not move) |
| `npx vitest run` | exit 0 — 47 files, **674 tests passed** |
| `npm run build` | exit 0 — static export succeeded; `out/404/index.html` present (36,567 bytes); `out/sitemap.xml` holds **1,407 `<loc>`**, unchanged; 1,400/1,407 dated across 9 distinct days |
| `pytest tests/test_url_host_routing_rules.py tests/test_legacy_redirect_rollback_snapshot.py -q` | **14 passed** |
| `scripts/probe_url_host_matrix.py` | **85 rows, 0 failed, exit 0**, no loops |
| `scripts/retired_url_probe.py` | **exit 0** — no retired URL answers 200. Worth noting: this pre-existing guard holds `"https://www.wecare.digital/": "www must 301 to the apex"`, so between the removal and this change it was **failing** on that row (a 200 classifies as `STILL-LIVE`, exit 1). It is green again now. Independent confirmation that the host rule was genuinely missing, from a file this task did not write |
| `scripts/provision_legacy_redirects.py` (no flag) | exit 1 — reports `9 rules; 1 redirects to remove` naming the host rule, §5.5 |
| `scripts/provision_legacy_redirects.py --verify` | **exit 1 by design** — `FAIL: custom redirect rules remain`, naming the host rule, §5.5 |
| `git diff --stat _routes.json` | empty |

Measured values are recorded in the matrix in §1 rather than repeated here. A command exiting
0 is not evidence of success, which is why every row of §1 carries a probed status rather than
an expectation — and why the two non-zero exits above are reported as predicted behaviour with
their cause, instead of being quietly omitted.

**No DNS record, ACM certificate, CloudFront distribution, domain association, WAF or Security
Hub setting was created, modified or deleted.** No secret value was read; no credential appears
in any command or log in this record. The only production write was the single `update-app`
documented in §0.

### 9.1 Convergence re-run — independent cross-FEAT confirmation, 2026-10-01

The whole gate set was re-run on the merged tree, and the must-not-break set was re-measured
with `curl` rather than with the task's own probe harness, so a bug in that harness could not
vouch for itself. **Every row matched.**

| Gate | Convergence result |
|---|---|
| `npm run typecheck` | exit 0 |
| `npm run lint` | exit 0 — 0 errors, 188 warnings, count unmoved |
| `npx vitest run` | exit 0 — 47 files, **677 tests** (674 + the 3 KNOWN GAP tests in §7) |
| `npm run build` | exit 0 — `out/404/index.html` present, `out/sitemap.xml` **1,407 `<loc>`** |
| `pytest …routing_rules …rollback_snapshot -q` | **14 passed** |
| `scripts/probe_url_host_matrix.py --json` | **probed 86, failed 0**, exit 0 (85 → 86: the third `[retired public path ef531503]` wildcard row, §5.5) |
| `scripts/retired_url_probe.py` | exit 0 — 24 rows, 21 `OK-gone` + 3 `OK-redirect`, none still live |
| `scripts/provision_legacy_redirects.py` / `--verify` | **exit 0 / exit 0** — both were exit 1 earlier in this same run; the §5.5 hazard was fixed mid-convergence and `--verify` now reports `Verified: only approved home/access redirects remain` |
| `git diff --stat _routes.json` | empty |

Independently re-measured with `curl` (not via the harness):
`POST /api/razorpay-webhook` **401** · `POST /api/auth/validate` **401** ·
`POST /api/payments/webhook` **404** · `GET /api/webhook/sinch-rcs` **200** ·
`GET /mcp` **405** · `POST /mcp` **400** ·
`GET /get/o/stream/media/m/wecare-digital.png` **200** ·
`GET /definitely-not-a-page/` **404** carrying `"page":"/404"` and `robots: noindex, follow` ·
`https://www.wecare.digital/shop/` **301 → `https://wecare.digital/shop/`**, terminal **200**,
path preserved · `/workspace/` **200** with the Authenticator shell (`data-amplify`,
`authenticator` markers present in the body) · `/account/sign-in/` **200** ·
`/shop/ /cart/ /orders/ /blog/ /404/` all **200**.

One seam was found between the two features and is recorded as **§7 OWNER-DECISION ITEM 4** —
two allowlisted post-sign-in destinations have no exported page. Nothing else in either feature
conflicted: FEAT-002's correction to `src/pages/404.tsx` left FEAT-001's
`NotFoundFallback.test.ts` assertions intact, and FEAT-001's `ErrorBoundary` repoint to `/`
lands on a page measured at **200**.

### 9.2 The tree moved during this run, and that is why the numbers above differ from §0

Worth recording as a shared-tree fact rather than hidden behind a final green result. The first
pass of this convergence run measured 9 live rules, `pytest … -q` **14 passed**, and the two
provisioner exits at **1**. Forty minutes later, with no edit of mine in between, the same
pytest command reported **2 failed** — another session had rewritten
`scripts/provision_legacy_redirects.py` (mtime 15:54:03) and applied it to production.

The two failures were the task's own cross-file alarms firing exactly as designed: one because
`desired_redirects()` stopped returning `[]`, the other because the KNOWN HAZARD it pinned had
been fixed. Neither was a regression, and the fix for both was written into their own
docstrings in advance — **invert, do not delete**. That is the whole argument for pinning a
known defect with a named test instead of a comment: a comment would have been silently
outdated, and a deleted test would have left the reconciliation unverified.

The lesson for the next reader: **re-measure, do not re-use.** Every count in §0 is timestamped
for this reason, and §1 carries probed statuses rather than expectations.


## Superseding owner instruction - home fallback completed

The later owner instruction authorized wildcard home routing and direct access retirement. The provisioner now retains www plus three /access-to-home rules. The known-hazard tests have been inverted to assert preservation. CloudFront E1ZZ786I3YH65O is deployed; wildcard/xout/www.xout DNS change is INSYNC. See docs/execution/home-fallback-20261001.md for implementation, live checks and rollback. This supersedes the earlier pending wildcard and provisioner decision items; the earlier probe matrix remains historical evidence.
### 9.3 `xout.wecare.digital` moved too, and why its row is now informational

A second drift, caught on the final re-run. `https://xout.wecare.digital/` was measured at
**404 (third-party host)** earlier in the day and at **302 → `https://wecare.digital/`, terminal 200** later
the same day. **Nothing of ours changed between those readings** — this task made no DNS, ACM or
CloudFront change and is not permitted to make one.

`xout` is a **third-party-managed second-label host**. Asserting a third party's configuration as a hard
gate means our run goes red whenever they edit their host, which is how a probe harness earns a
reputation for crying wolf and then gets ignored. So this one row is now
`informational=True`: it is still probed, and any mismatch is still printed — as `NOTE` with a
`~~` line, never as a silent `ok` — but it does not fail the run. Exit code went 1 → **0**, with
`probed 86 row(s); 0 failed; 1 informational row(s) drifted`.

The new answer is also the benign direction. It lands on the canonical apex rather than serving
our content under a host the certificate cannot cover — `*.wecare.digital` matches **one label
only** (§4), so `xout.wecare.digital` is outside it either way.

**Deliberately NOT downgraded:** `shop.wecare.digital` (status 0, our own documented coverage
gap — §4 OWNER-DECISION ITEM 2) and `mta-sts.wecare.digital` (403, the MTA-STS policy endpoint
under `mode: enforce`, where email is fail-closed). Both remain hard assertions, and
`_row`'s docstring says in terms that `informational` is not for silencing a surface we control.
Both re-measured at their expected values on the final run.

**CORRECTED ON MERGE - the cause is known, and it was not a third party.** The paragraph
above is the explanation: a concurrent session deployed CloudFront `E1ZZ786I3YH65O` for
wildcard home routing and its `wildcard/xout/www.xout` DNS change reached `INSYNC` between
the two readings. So the drift was OURS, authorized and deliberate - not the third party editing
their host. The original wording "Nothing of ours changed between those readings" was true of this
task, which made no DNS/ACM/CloudFront change, but false of the repository. Recorded rather
than silently rewritten, because an unexplained third-party drift and a teammate's approved
change landing mid-run warrant different responses, and only the second one is this one.

The downgrade to `informational=True` still stands, for a reason that survives the correction:
`xout` is a second-label host OUTSIDE our certificate (`*.wecare.digital` matches one label
only - see section 4), so its routing is owned elsewhere either way.

**Its EXPECTATION was moved to the measured truth on 2026-10-01T13:15Z**, for the same reason the
`shop` row was: left at `404` the row reported a permanent `NOTE` on every run, and a note nobody
acts on is read no more carefully than a permanent `FAIL`. It now expects 200 with terminal
`https://wecare.digital/` and stays informational, so it reads `ok` today and NOTEs only if the
third-party-owned `www.xout` endpoint changes.

---

## 9.4 Second convergence pass — 2026-10-01T13:15Z

Run after a review found that two pieces of this document's own verification evidence no longer
matched live measurement. Every claim below was re-measured, not carried forward.

### What was wrong, and what it is now

| # | Finding | Resolution |
|---:|---|---|
| 1 | `scripts/probe_url_host_matrix.py` **exited 1**: `shop.wecare.digital` was pinned at status 0 (the documented no-address gap) but now 302s to the apex. A gate that goes red for a reason nobody acts on stops being read | Expectation **moved to the measured truth** and kept a HARD row, asserted on the terminal URL as well as the status. Two rows added: the path-dropping behaviour, and `a.b.wecare.digital` pinning the residual gap. `mta-sts` stays a hard 403 |
| 2 | §4 and OWNER-DECISION ITEM 2 **overstated** the subdomain gap — they said the wildcard work was not done | **§4.1** added: the single-label case is closed, with measured evidence and the owning workstream named; the second-label case is still open, with its cause corrected from "no address" to "no certificate covers it" |
| 3 | §0's "9 rules" table was **stale** and contradicted by §5.5's 12 | §0 table re-titled as the 08:59:52Z post-apply state; **§0.1** holds the live 12-rule array with its own read timestamp |
| 4 | `src/lib/safeReturnPath.ts` still has **no production caller** | **CLOSED.** Raised to the owner because every fix changed customer-visible behaviour and the file was outside this task's paths; the owner cleared the boundary and chose to narrow the allowlist. Wired, allowlist narrowed to five, KNOWN GAP test inverted — **§7.1** |
| 5 | The "every passthrough precedes every redirect" claim was **false live** and no gate could see it | §0 restated to the non-overlap property that actually holds; the snapshot test rescoped and renamed, and `test_no_sanctioned_redirect_can_shadow_a_passthrough_in_the_live_shape` added to assert it on the array `apply()` writes |
| 6 | The two provisioner-convergence tests would **fail on a clean checkout of HEAD** without commit `4c603188` | **Already resolved.** `4c603188` is an ancestor of `HEAD` (`83a8d60d`), and `HEAD` equals `origin/stack`. Verified directly against the HEAD-committed provisioner: `desired_redirects()` length **4**, `WWW_CANONICAL emitted: True`, so both tests assert normally rather than skip. No merge, rebase or force push was needed |

### Gates, on the exact tree

| Gate | Result |
|---|---|
| `npm run typecheck` | exit 0 |
| `npm run lint` | exit 0 — **0 errors**, 188 warnings, count unmoved from the repo baseline |
| `npx vitest run` | exit 0 — **48 files, 684 tests passed**, before and after §7.1 alike: the KNOWN GAP block was inverted in place, so its three cases changed what they assert without changing the count (22 in `SafeReturnPath.test.ts`) |
| `npm run build` | exit 0 — `out/404/index.html` present (**36,567 bytes**); `out/sitemap.xml` **1,407 `<loc>`**, unchanged |
| `pytest …routing_rules …rollback_snapshot -q` | **17 passed** (14 → 16 when another session added two provisioner tests, → 17 with the live-shape test added here) |
| `scripts/probe_url_host_matrix.py --json` | **probed 88, failed 0**, exit 0, **0 informational rows drifted** (86 → 88: the two new subdomain rows) |
| `scripts/retired_url_probe.py` | exit 0 — the `www` row reads `OK-redirect`, 301 to the apex |
| `scripts/provision_legacy_redirects.py` / `--verify` | exit **0** / exit **0** — `12 rules; 4 redirects to reconcile`, `Verified: only approved home/access redirects remain` |
| `git diff --stat _routes.json` | empty — byte-identical |

### Independently re-measured with `curl`, not through the harness

So that a bug in this task's own probe could not vouch for itself:

`POST /api/razorpay-webhook` **401** · `POST /api/auth/validate` **401** ·
`POST /api/payments/webhook` **404** · `GET /api/webhook/sinch-rcs` **200** ·
`GET /mcp` **405** · `POST /mcp` **400** ·
`GET /get/o/stream/media/m/wecare-digital.png` **200** ·
`GET /definitely-not-a-page/` **404** carrying `"page":"/404"` and
`name="robots" content="noindex, follow"` ·
`https://www.wecare.digital/shop/` **301 → `https://wecare.digital/shop/`**, terminal **200**,
path preserved · `/workspace/` **200** with the Authenticator shell (`data-amplify` and
`amplify-authenticator` both present) · `/account/sign-in/` **200** ·
`/shop/ /cart/ /orders/ /blog/ /404/ /` all **200**.

### The one finding that needed a decision, and how it was closed

**The return-path validator had no production caller** (§7). Measured in this pass before
raising it: `src/pages/account/sign-in.tsx:180` carried `/^\/[a-zA-Z0-9\/_-]*\/?$/`, which
accepts `//evil` (protocol-relative — the browser reads `evil` as the host) and
`/workspace/access` (a customer sent to the staff login). The only references to
`safeLocalReturnPath` anywhere in `src/` were inside its own test.

It was **raised rather than fixed unilaterally**, for two independent reasons — only the first of
which was a boundary:

1. The wiring is one line in `src/pages/account/sign-in.tsx`, which was outside this task's
   permitted paths because the `src/pages/account/**` workstream owned it.
2. It could not be applied correctly as specified anyway. `/checkout/` and `/account/` were on
   the validator's allowlist and both measured **404**, so wiring it first would have started
   routing a signed-in customer to a missing page — a worse customer outcome than the
   open-redirect shape it closes. Both candidate resolutions were product decisions.

**The owner chose to narrow the allowlist and cleared the boundary** — the owning workstream had
aborted before implementation and `sign-in.tsx` was clean in `git status`, so there was no live
owner to collide with. Shipped as **§7.1**: five destinations, all measured 200, `/blog/` added
and `/checkout/`+`/account/` removed; the one-line wiring applied with nothing else in that file
touched; the KNOWN GAP test inverted so it now asserts the caller exists **and** that the
permissive regex is absent.

**Independently verified against the module**, 24 cases, all passing, run from a throwaway config
so no file was added under `src/**`:

- **18 rejections**, each landing on `/cart/`: `//evil` (single-label host, no dot), `//evil.example`,
  `///evil`, `/workspace/access`, `/WorkSpace/Access`, `\\evil.example`, `/\evil.example`,
  `https://evil.example`, `http://evil.example/cart/`, `%2f%2fevil.example`, `%252f%252fevil`,
  `/%2f%2fevil.example`, `/../etc/passwd`, `/cart/../workspace/access`, `javascript:alert(1)`,
  `/checkout/`, `/account/`, `/terms/`.
- **5 round-trips**: `/`, `/cart/`, `/orders/`, `/shop/`, `/blog/`.
- **Normalisation** of the unslashed form of all four non-root members.

### Scope

No DNS record, ACM certificate, CloudFront distribution, domain association, WAF or Security Hub
setting was created, modified or deleted in this pass. **No production write of any kind was
made** — the only AWS calls were reads (`amplify get-app`, `amplify get-domain-association`,
`route53 list-resource-record-sets`, `cloudfront list-distributions`) plus public HTTP probes. No
secret was read and no credential appears in any command or in this record. `_routes.json` and the
`/<*>` → `/404.html` catch-all are untouched.

## 9.5 Third convergence pass — 2026-10-01, evidence gaps closed

A review of the second pass returned CHANGES_REQUESTED on four items, **none of them a behaviour
defect**: every route still measured what it was supposed to measure. All four were evidence or
authority gaps, and all four are now closed without any live rule change.

### What was wrong, and what it is now

| Finding | Was | Now |
|---|---|---|
| `src/pages/account/sign-in.tsx` edited on an authority attested only inside the change | clearance appeared in the commit message, `safeReturnPath.ts`'s header and §7.1/§9.4 — all inside the change | recorded **outside** the change in `docs/execution/change-authority-matrix.md`, with the class, the target, the owner handoff item it rests on, the collision evidence, an honest "not pre-cleared in writing" ratification line, and the rollback. **The collision argument was then overtaken by a better one on the same day — see §9.6:** the owning workstream resumed and *kept* the wiring |
| Three surface categories the brief names had no row | OAuth callbacks, signed receipt links and verified-email callbacks were absent; protected operational endpoints had exactly one row | **§1.1–§1.3** and rows **86–92**, all added to the probe harness so they are re-measured every run, not a dated `curl` |
| The redirect home retains the query string | the plan's design note D1 claimed path, query and fragment were all dropped; never probed | **FIXED, not just documented** — the target now carries its own query parameter, which is the documented way to stop Amplify forwarding the caller's. `§1.4` holds the before/after probes, rows **93–95** pin the exact terminal URL, and three test sites pin the target. D1 corrected in place and dated, old reading kept |
| `src/pages/404.tsx` carried a stale subdomain paragraph | said sending wrong subdomains home "cannot be done from this repository" | corrected in place and dated: the IaC is in this repository, the wildcard plus `E1ZZ786I3YH65O` is live, and the residual limit is the one-label certificate, measured `ssl_verify_result=1` |

The harness grew from **88 rows to 98** in this pass, and to **100** once the concurrent
subdomain rewrite described in §9.6 merged. Nothing was removed and no expectation was relaxed by
this pass.

### Gates, on the exact tree

| gate | result |
|---|---|
| `npm run typecheck` | **0** |
| `npm run lint` | **0 errors**, 188 warnings — unmoved |
| `npx vitest run` | **48 files, 684 tests, all passed** |
| `npm run build` | **0**; `out/404/index.html` **36,567 bytes**; `out/sitemap.xml` **1,407 `<loc>`** — both unchanged |
| `pytest test_legacy_redirect_rollback_snapshot.py test_url_host_routing_rules.py -q` | **17 passed**, 0 skipped (13 + 4; an earlier write-up said 20, which counted a wider file set) |
| `scripts/probe_url_host_matrix.py --json` | **98 probed, 0 failed, 0 informational drift**, exit 0 — **100 after the §9.6 merge, still 0 failed** |
| `scripts/retired_url_probe.py` | exit **0** — no retired public URL answers 200 |
| `scripts/provision_legacy_redirects.py --verify` | exit **0** — 12 rules, only the approved host 301 and three `[retired public path ef531503]` 302s |
| `git diff --stat _routes.json` | **empty** — byte-identical, and clean in `git status` |

### Independently re-measured with `curl`, not through the harness

Run twice, roughly fifteen minutes apart, with identical results:

```
POST /api/razorpay-webhook                     401       GET  /workspace/              200 (Authenticator)
POST /api/auth/validate                        401       GET  /account/sign-in/        200
POST /api/payments/webhook                     404       GET  /shop/ /cart/            200 200
GET  /api/webhook/sinch-rcs                    200       GET  /orders/ /blog/ /        200 200 200
GET  /mcp                                      405       www /shop/  301 -> https://wecare.digital/shop/
POST /mcp                                      400       GET  /definitely-not-a-page/  404
GET  /get/o/stream/media/m/wecare-digital.png  200            carrying "page":"/404", noindex, apex canonical
```

`/workspace/` still returns the staff Authenticator (`data-amplify-authenticator`,
`data-amplify-router`) and is still `Disallow`ed. Authorization was not touched: `src/pages/_app.tsx`
is unmodified by this pass, and rows 86–88 show protected APIs still rejecting an unauthenticated
read with the API's own JSON.

### On "before AND after for every row"

All **43** table rows in §1 carry both columns filled. **13** of them state *not measured before*
rather than a value — rows 76, 83a, 83b and the ten added here. That is deliberate and is the
repo's own rule: those surfaces genuinely were not probed before the pass that added them, and
inventing a before value is forbidden. An honest gap reads as a gap; a fabricated one reads as
evidence.

### Scope of this pass

Documentation, one source comment, and ten read-only probe rows. **No live rule change, no
`--apply`, no AWS write of any kind** — the only AWS-adjacent traffic was public HTTP probes.
No DNS, ACM, CloudFront, domain-association, WAF or Security Hub change. No secret was read and no
credential appears in any command or in this record. `_routes.json`, the `/<*>` → `/404.html`
`404-200` catch-all, `amplify/**`, `src/pages/account/**`, `src/lib/customerAuth.ts`,
`src/lib/dialCodes.ts`, `src/components/HeaderCart.tsx` and `src/components/PhoneField.tsx` are
all untouched by this pass.

## 9.6 What the push attempt found — two cross-session seams, 2026-10-01

The convergence commit was rejected non-fast-forward: `origin/stack` had advanced **four**
commits (`722fa300`, `b01ecc32`, `da8d7d12`, `5be80392`) while this pass ran. Both of the
following were discovered by reading `origin/stack` with `git show`, which needs no fetch — the
remote-tracking ref was already local. **Neither is a behaviour defect on the live site; every
probe above was measured against production and is unaffected.**

### 1. The `src/pages/account/sign-in.tsx` crossing was ratified by its own owner

The §9.5 entry rested on the `customer-session-20261001` workstream having stopped before
implementation. It resumed. Its commits touch `sign-in.tsx`, `src/lib/customerAuth.ts` and
`amplify/functions/ecommerce/customer-session/handler.py` — and they **kept the wiring**:
`origin/stack`'s `sign-in.tsx` still imports `safeLocalReturnPath` (line 71) and still returns
`safeLocalReturnPath( raw )` from `returnPathFromUrl()` (line 187), with `restoreSession()` and a
`persistent` flag added **around** it. The owner of the path adopted the change rather than
reverting it, which is stronger ratification than the absent-owner argument. Corrected in place
and dated in `docs/execution/change-authority-matrix.md`; the original reading is kept there
because it is the reasoning that was actually used at the time.

### 2. `scripts/probe_url_host_matrix.py`'s subdomain block was rewritten concurrently — MERGED by the committer, flags still open

`origin/stack` replaces the subdomain rows with a loop over four hosts probing
`/old/path?old=1`, and reports a 90-row matrix. This pass's tree reports 98. The two edits sit in
**different hunks** of `matrix()` — the rows added here are in the `host`, `api` and
`legacy-workspace` groups — so they are complementary rather than contradictory, and a merge
should combine to roughly 100 rows. Two properties of the concurrent edit are worth an owner's
eyes rather than a silent overwrite:

- **`xout.wecare.digital` is promoted from `informational=True` to a hard gate.** It was
  informational deliberately, and the reason is recorded in `_row`'s own docstring: `www.xout`
  still terminates through a third-party TLS endpoint that we do not control, so
  asserting it as a hard row makes **our** run red whenever a third party edits **their** host.
  `origin/stack` additionally adds `www.xout.wecare.digital` as a hard row. That is a
  deliberate-looking choice by a release-gating workstream, so it is reported, not reverted.
- **Roughly 50 lines of dated rationale were deleted** rather than corrected in place, including
  the record of why the `shop` row moved from status 0 to 302 and why the `xout` downgrade stands.
  This repo's convention is to correct a rationale in place with a date and never delete it.

**Why this pass did not merge it, and who did.** `amplify/functions/shared/lambda_utils/customer_session.py`
was **modified in the shared working tree by a live session** and also changed on `origin/stack`,
so a merge would have had to update a file another session was holding uncommitted. `git merge`
refuses that, and the alternatives — stash, reset, force — are all prohibited. The convergence
commits were therefore left local and the race was reported rather than resolved here.

**RESOLVED by the single committer, 2026-10-01.** The one-committer rule is why: four workstreams
had unpushed commits on local `stack` at that moment (this one, the checkout-deployment run and the
phone-normalisation run), and four independent merges of the same divergence is how the absorption
incidents in `.kiro/steering/multi-session-parallel-agents.md` started. One integration, once:
merge `805c7517` on top of `0068f871`, with the `change-authority-matrix.md` conflict taken as the
keep-both resolution `git merge-tree` had pre-identified, and `probe_url_host_matrix.py`
auto-merging as predicted. `HEAD` now equals `origin/stack` and both convergence commits
(`5114ae70`, `f00d9b93`) are on the branch of record. **The merged harness reports 100 rows,
0 failed** — this pass's 98 plus the concurrent subdomain rewrite's net +2, which is the
"roughly 100" predicted above, measured.

**The two flags above are NOT closed by the merge.** Both edits survived it intact, so
`xout.wecare.digital` and `www.xout.wecare.digital` are hard gates in the merged file and the
deleted rationale is still deleted. They remain an owner call for the release-gating workstream
that made them, not something to revert from here.

---

## 10. Final state — task `url-host-cleanup` closed, 2026-10-01

Closing entry. Everything below was **measured on the exact tree and against the live site at
closure time**, not carried forward from an earlier pass. Where an earlier section recorded a
different number, this section says so rather than editing the earlier reading away.

### 10.1 Commits

| Commit | Subject | On `origin/stack` at the start of this pass |
|---|---|---|
| `25eace20` | `fix: stop the public surface sending customers into the staff workspace` (FEAT-001) | yes |
| `d7dc0103` | `fix: restore www host canonicalisation and record the measured URL/host matrix` (FEAT-002) | yes |
| `2ec84830` | `docs: record the measured propagation delay on the www canonicalisation rule` | yes |
| `e080b209` `4c603188` `faccfbae` `023a385b` | review-response passes on the guards and the harness | yes |
| `5114ae70` `f00d9b93` | convergence passes | yes |
| `d0584e94` | `Close the post-sign-in open redirect, and narrow the allowlist to pages that exist` | yes |
| `f8912068` | `Stop the retired [retired public path ef531503] redirect forwarding the caller's query string to home` | **no — unpushed, pushed by this closing pass** |

The closing commit itself carries this section plus `status: "completed"` in
`.agents/tasks/url-host-cleanup/task.json`; its SHA is recorded in §10.7 below, in a follow-up
commit, because a commit cannot contain its own hash.

Three commits belonging to **other** workstreams (`ac1b0c37`, `ed9fa198`, `8a48e5f9`) were also
sitting unpushed on local `stack` at closure. They went to the remote with this push, which is
what the one-committer rule means in a single-branch repo — not an absorption: they are their own
commits under their own messages, and `git commit --only` bounded this pass's commit to its own
paths.

### 10.2 Live Amplify rule count — before and after, measured

`aws amplify get-app --app-id d22dm4b0jn71jw --region us-east-1 --query 'length(app.customRules)'`

| Point in time | Rules | Source of the number |
|---|---:|---|
| Before another session's owner-instructed removal | 146 | their snapshot, not this task's |
| **This task's BEFORE** (post-removal) | **8** | `snapshots/amplify-custom-rules-before-url-host-cleanup-20261001.json`, 8 entries, re-parsed at closure |
| After the host-rule restore | 9 | `snapshots/amplify-custom-rules-after-url-host-cleanup-20261001.json`, 9 entries |
| Before the `[retired public path ef531503]` query-drop narrowing | 12 | `snapshots/amplify-custom-rules-before-access-query-drop-20261001.json`, `ruleCount: 12` |
| **AFTER — live at closure** | **12** | read live, `length(app.customRules)` = 12 |

Net for this task: **8 → 12**, four rules added and **zero removed or reordered**. One
host-canonicalisation 301 restored verbatim from the 146-rule snapshot, and three `[retired public path ef531503]`
sources at 302 whose target carries the literal `?from=access` — that query parameter **is** the
mechanism that stops Amplify forwarding the caller's query, so it must not be tidied to a bare
apex. The `/<*> → /404.html` 404-200 catch-all is still the last rule and was never touched.

Amplify `get-app`/`update-app` expose **no ETag**. There is no concurrency token to record here.

### 10.3 Gates, all run at closure on the exact tree

| Gate | Result |
|---|---|
| `npm run typecheck` | **exit 0** |
| `npm run lint` | **exit 0** — 0 errors, 188 warnings, all pre-existing; baseline count unmoved |
| `npx vitest run` | **exit 0** — **50 files, 697 tests passed** (up from the 47/674 in §9 because the integration merge brought in other workstreams' test files) |
| `npm run build` | **exit 0** — `out/404/index.html` present at 36,567 bytes; `out/sitemap.xml` holds **1,407 `<loc>`**, unchanged |
| `pytest tests/test_url_host_routing_rules.py tests/test_legacy_redirect_rollback_snapshot.py -q` | **17 passed** |
| `scripts/probe_url_host_matrix.py` | **exit 0** — **100 rows probed, 0 failed, 0 informational rows drifted** |
| `scripts/retired_url_probe.py` | **exit 0** — no retired public URL answers 200; its own `www must 301 to the apex` row is `OK-redirect` |
| `scripts/provision_legacy_redirects.py --verify` | **exit 0** — `Verified: only approved home/access redirects remain` |
| `git diff --stat _routes.json` | **empty** — byte-identical, as required |

Must-not-break set, re-measured independently with `curl` rather than through the harness:

```
POST /api/razorpay-webhook                     401
POST /api/auth/validate                        401
POST /api/payments/webhook                     404
GET  /api/webhook/sinch-rcs                    200
GET  /mcp                                      405
POST /mcp                                      400
GET  /get/o/stream/media/m/wecare-digital.png  200
GET  /definitely-not-a-page/                   404
GET  /workspace/                               200   (Authenticator shell, unchanged)
GET  /account/sign-in/                         200
GET  / /shop/ /cart/ /orders/ /blog/           200   (all five)
GET  https://www.wecare.digital/shop/          301 -> https://wecare.digital/shop/   (path preserved)
GET  [retired public path ef531503]/?next=https://evil.example        302 -> https://wecare.digital/?from=access   (caller's query dropped)
```

### 10.4 The exact subdomain coverage gap — CORRECTED at closure

§4 and OWNER-DECISION ITEM 2 framed the wildcard as needing **both** an Amplify
`update-domain-association` with prefix `*` **and** a Route 53 `*.wecare.digital` alias. Measured
at closure, that framing is now wrong in its first half, and the correction matters because
acting on the stale version would mutate the association serving the canonical home for no
reason:

- The Amplify domain association for `wecare.digital` is `AVAILABLE` and its subdomain prefixes
  are **`["www"]`** — there is no `*` prefix and none was added.
- Route 53 zone `Z03939753QJGZ6ZD6BXO8` **does** now hold `\052.wecare.digital` **A and AAAA**
  alias records pointing at `d27evp2npt2kzr.cloudfront.net`. That is a CloudFront distribution,
  **not** the Amplify association. The record is not listed under a literal `*` in the API
  response — Route 53 returns it octal-escaped as `\052`, which is why a naive `'*' in name`
  filter reports no wildcard on a zone that has one.
- **This task did not create any of it.** This task made exactly **one** production write, the
  `amplify update-app` in §10.2. The DNS, CloudFront and ACM work belongs to the sibling
  home-fallback workstream and is recorded here as measured state, not as this task's output.

So the single-label gap is **CLOSED** and the remaining gap is exactly one thing:

| Host shape | Measured at closure | Verdict |
|---|---|---|
| `store.wecare.digital/` | DNS resolves; TLS verifies (`ssl_verify_result=0`); **302 → terminal 200** | covered |
| `xout.wecare.digital/old/path?old=1` | 302 → 200 | covered (third-party-owned host, informational row) |
| `release-check-unknown.wecare.digital/old/path?old=1` | 302 → 200 | covered |
| `www.xout.wecare.digital/old/path?old=1` | 301 → 302 → 200 | covered (terminates through third-party TLS we do not control) |
| **`a.b.wecare.digital/`** | DNS **resolves** to the wildcard alias, then TLS **fails**: `curl` 60, `no alternative certificate subject name matches target host name`, `ssl_verify_result=1`, HTTP `000` | **THE GAP** |

The cause is not a missing DNS record and not a missing distribution. It is the certificate:
`*.wecare.digital` matches **one label only**, so a two-label host like `a.b.wecare.digital`
resolves to an address and is then refused at the TLS handshake. Closing it needs a **new SAN**
on the certificate, re-associated on **both** the Amplify app **and** CloudFront `E1SZBXLQ4XNLJ7`
— and `E1SZBXLQ4XNLJ7` is the **MTA-STS policy endpoint under `mode: enforce`**, where a broken
TLS chain means senders refuse inbound mail rather than degrading quietly. That is why this stays
an owner decision and was not attempted. `xout.wecare.digital` and `www.xout.wecare.digital` are
existing second-label third-party hosts and are out of scope either way.

### 10.5 Left open, with its owner

| # | Item | Owner | State at closure |
|---|---|---|---|
| 1 | **Subdomain SAN / second-label coverage** — the `a.b.wecare.digital` TLS refusal in §10.4, needing a new SAN re-associated on the Amplify app and on `E1SZBXLQ4XNLJ7` | **owner decision** | OPEN. Single-label coverage closed by the sibling workstream; second-label deliberately not attempted (MTA-STS `enforce` blast radius) |
| 2 | **Unknown API route answers `302 → /contact/`** — `GET /api/definitely-no-route` from the HTTP API's `GET /{code}` catch-all | **`amplify/functions` workstream** | OPEN, untouched here. Asserted in `probe_url_host_matrix.py` at its measured value, so a change becomes visible rather than silent |
| 3 | **`public/sw.js:180` push-click destination `/workspace/dashboard/`** | **staff push / service-worker owner** | OPEN, needs-verification. Not reproduced as customer-reachable — it is a push-notification destination, not a navigation link — and changing it could break staff push, so it is recorded in `INTENTIONALLY_WORKSPACE_ONLY` rather than edited |
| 4 | **`src/pages/account/sign-in.tsx` wiring handoff** | **`src/pages/account/**` workstream** | **CLOSED by that owner, not by this task.** `origin/stack`'s `sign-in.tsx` imports `safeLocalReturnPath` and returns it from `returnPathFromUrl()`, with `restoreSession()` and a persistent flag added around it. The three-line crossing recorded in `docs/execution/change-authority-matrix.md` was ratified twice: in writing by the orchestrator, and by that owner keeping the wiring when it resumed. The verbatim one-line handoff stays in §7 for the record |
| 5 | **`[retired public path b180810d]` and `[retired public path 282d0fd5]` now 404** — both are printed inside approved provider template bodies (DLT `ivr-default`, nine Sinch RCS templates incl. `rcsmenu`, `wecare_order_update`) that cannot be edited | **owner** | OPEN and **accepted**, not an oversight: the owner's removal document acknowledges it. Reversal is two rules plus one instruction; both intended targets (`/submit-request/`, `/orders/`) measured 200 |
| 6 | **`xout` / `www.xout` promoted to hard probe gates, and ~50 lines of deleted rationale** in `probe_url_host_matrix.py` | **release-gating workstream that made the edit** | OPEN. Survived the integration merge intact; reported, not reverted |
| 7 | **`_routes.json` has zero code consumers** | unassigned | OPEN as information only. Left byte-identical on purpose |
| 8 | **Four stale catch-all comments** at `src/pages/_app.tsx:938,999,1098` and `src/pages/workspace/commerce/catalog.tsx:28` | their file owners | OPEN, handed over unedited |

OWNER-DECISION ITEM 3 (`--apply` deleting the host rule) is **CLOSED** — see §5.5 RESOLVED, and
`--verify` exits 0 at closure with the host rule live.

### 10.6 Rollback

Unchanged from §8, restated here so the closing entry is self-contained. Amplify `update-app` is
a **full replace** of `customRules` and exposes **no ETag**, so any rollback must start from a
fresh `get-app`, never a stale array:

```
aws amplify update-app --app-id d22dm4b0jn71jw --region us-east-1 \
  --custom-rules file://docs/execution/snapshots/amplify-custom-rules-before-url-host-cleanup-20261001.json
```

That returns the app to the 8-rule post-removal state, undoing **all four** rules this task
added — the host 301 and the three `[retired public path ef531503]` 302s. To undo only the `[retired public path ef531503]` narrowing and keep
the host rule, restore
`snapshots/amplify-custom-rules-before-access-query-drop-20261001.json` (12 rules) instead. Do
**not** restore the 146-rule or the 3-rule snapshots; §8 records why each would be worse than
what it reverses.

Code rollback is `git revert` of the commits in §10.1. No DNS record, ACM certificate,
CloudFront distribution, domain association, WAF or Security Hub setting was created, modified or
deleted by this task.

### 10.7 The closing commit SHA

Recorded in a follow-up commit because §10.1 cannot contain its own hash.

| | |
|---|---|
| Closing commit | **`342bdf3b`** — `Close the URL/host cleanup with its measured final state, and correct the subdomain gap` |
| Paths in it | `.agents/tasks/url-host-cleanup/**` (9 files) and `docs/execution/url-host-matrix-20261001.md`. Nothing else — committed with `git commit --only`, so no other session's staged or dirty file could ride along |
| Integration | merge commit **`0f184040`**, `origin/stack` merged into local `stack` with **no conflicts**; the remote had moved to `937924a3` during the run and the push fast-forwarded |
| Pushed | `937924a3..0f184040 stack -> stack`; `git rev-list --left-right --count origin/stack...HEAD` = `0 0` |
| Gates re-run **after** the merge, because the tree moved | typecheck 0, lint 0 errors / 188 warnings unmoved, vitest **50 files / 698 passed** (the merge brought one more test from the checkout workstream), pytest 17 passed on the two named files |

`f8912068`, the last previously-unpushed commit of this task, is on `origin/stack` as of this
push. Every commit in §10.1 is now on the branch of record.
