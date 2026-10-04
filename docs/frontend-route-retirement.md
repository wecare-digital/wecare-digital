# Frontend route retirement

Measured **2026-09-25** against Amplify app `d22dm4b0jn71jw` (`GetApp.customRules`) and
`docs/execution/runtime-inventory.json`.

`bw-crm.md` requires that no page is deleted from static-reference counts alone, and
that every retirement records owner, dependencies, replacement, redirect, tests and
rollback. This file is the register. It is **not** a deletion authority: a row here
with no redirect and no replacement is a candidate, not a decision.

## Why redirects live in Amplify, not in Next

Production is a Next.js **static export** (`output: export`). Next `redirects()` and
`headers()` do not apply — the build says so explicitly. So every redirect below is an
Amplify `customRules` entry, which is the hosting layer that actually serves them, and
the app-level rules **override** anything the repository implies. Verify against
`GetApp`, never against `next.config.js`.

## Live redirect rules — 23 total

Measured, in the order Amplify evaluates them. Order matters: the catch-all must stay
last or it shadows everything after it.

| # | Source | Target | Status | Purpose |
|--:|---|---|:-:|---|
| 1 | `https://www.wecare.digital` | `https://wecare.digital` | 301 | apex canonicalisation |
| 2 | `/get` | `/get/index.html` | 200 | rewrite, not a retirement |
| 3 | `/get/` | `/get/index.html` | 200 | trailing-slash form |
| 4 | `/get/<*>` | `d1kf2rchz7yras.cloudfront.net/<*>` | 200 | secure-file delivery origin |
| 5 | `[retired public path 2de923b8]/calls` | `[retired public path 2de923b8]/inbox/?channel=voice` | **301** | provider inbox → Common Inbox filter |
| 6 | `[retired public path 2de923b8]/calls/` | `[retired public path 2de923b8]/inbox/?channel=voice` | **301** | trailing-slash form |
| 7 | `[retired public path 2de923b8]/rcs/inbox` | `[retired public path 2de923b8]/inbox/?channel=rcs` | **301** | provider inbox → filter |
| 8 | `[retired public path 2de923b8]/rcs/inbox/` | `[retired public path 2de923b8]/inbox/?channel=rcs` | **301** | trailing-slash form |
| 9 | `[retired public path 2de923b8]/ses/inbox` | `[retired public path 2de923b8]/inbox/?channel=email` | **301** | provider inbox → filter |
| 10 | `[retired public path 2de923b8]/ses/inbox/` | `[retired public path 2de923b8]/inbox/?channel=email` | **301** | trailing-slash form |
| 11 | `[retired public path 2de923b8]/whatsapp/logs` | `[retired public path 2de923b8]/logs/?channel=whatsapp` | **301** | per-provider log page → one log page |
| 12 | `[retired public path 2de923b8]/whatsapp/logs/` | `[retired public path 2de923b8]/logs/?channel=whatsapp` | **301** | trailing-slash form |
| 13 | `[retired public path 2de923b8]/rcs/logs` | `[retired public path 2de923b8]/logs/?channel=rcs` | **301** | per-provider log page → one log page |
| 14 | `[retired public path 2de923b8]/rcs/logs/` | `[retired public path 2de923b8]/logs/?channel=rcs` | **301** | trailing-slash form |
| 15 | `[retired public path 2de923b8]/ses/logs` | `[retired public path 2de923b8]/logs/?channel=email` | **301** | per-provider log page → one log page |
| 16 | `[retired public path 2de923b8]/ses/logs/` | `[retired public path 2de923b8]/logs/?channel=email` | **301** | trailing-slash form |
| 17 | `[retired public path 2de923b8]/rcs/campaign` | `[retired public path 2de923b8]/broadcast/` | **301** | per-provider campaign → one broadcast |
| 18 | `[retired public path 2de923b8]/rcs/campaign/` | `[retired public path 2de923b8]/broadcast/` | **301** | trailing-slash form |
| 19 | `[retired public path 2de923b8]/ses/campaign` | `[retired public path 2de923b8]/broadcast/` | **301** | per-provider campaign → one broadcast |
| 20 | `[retired public path 2de923b8]/ses/campaign/` | `[retired public path 2de923b8]/broadcast/` | **301** | trailing-slash form |
| 21 | `[retired public path 21d99b11]/logs` | `[retired public path 21d99b11]/` | **301** | sub-page folded into its parent |
| 22 | `[retired public path 21d99b11]/logs/` | `[retired public path 21d99b11]/` | **301** | trailing-slash form |
| 23 | `/<*>` | `/index.html` | 404-200 | SPA catch-all. **Must stay last** |

**18 of the 23 are 301 retirements**, covering 9 distinct retired paths in both their
bare and trailing-slash forms. Both forms are required: a static host does not treat
`[retired public path 2de923b8]/calls` and `[retired public path 2de923b8]/calls/` as the same key, so a single rule leaves one of them 404.

Every retired path preserves intent rather than dumping the user at a hub: the channel
becomes a query parameter (`?channel=voice|rcs|email`) on the surviving page. That is
the difference between a redirect and a dead end.

### What these rules replaced

Per-provider inboxes, per-provider log pages and per-provider campaign pages. The
consolidation target is the three-entry communications rule: **Common Inbox**,
**WhatsApp Business**, **Business Calling** — so a provider-specific inbox cannot
survive as a fourth entry. It survives as a filter.

## Rollback

`docs/execution/snapshots/amplify-custom-rules-before-8.4.json` holds the pre-8.4 rule
set. Restore with `aws amplify update-app --app-id d22dm4b0jn71jw --custom-rules ...`.
Amplify also retains every build, so the frontend itself rolls back by redeploying an
earlier job.

Removing a rule is not free: the source path 404s again for anyone holding a bookmark
or an indexed link. Prefer leaving a 301 in place indefinitely over reclaiming the
tidiness.

## Candidates, not decisions

`117` route **API** paths are mentioned by no frontend file
(`anomalies.routesWithoutFrontendCaller` in the runtime inventory, re-derived
2026-09-25; the earlier figure of 95 was stale against 361 live routes).

That number is **not** a deletion list, for three reasons measured rather than assumed:

1. Most are provider webhooks — Meta, Razorpay, Plivo and Sinch callbacks — which by
   definition no frontend calls.
2. Some are invoked Lambda-to-Lambda, where the caller is Python, not `src/**`.
3. The join is textual. A path assembled by string concatenation is missed, so absence
   from the list is weaker evidence than presence on it.

Before any route is deleted it needs: the integration and caller resolved, traffic
evidence over a stated window, a signed-webhook-versus-unintended-public
classification, and an exported route + integration JSON for rollback — the same gate
`docs/prohibited-provider-retirement.md` applies to provider surfaces. Two dangling
routes were removed that way in September, and the deletions are recorded in
`docs/deleted-routes-*.json`.

### The 117, classified (OPS-002, 2026-09-25)

Classified by evidence rather than by name. **42**, not 117, are even candidates.

| Class | Count | What it means |
|---|--:|---|
| Provider webhook | 13 | Meta, Razorpay, Plivo, Sinch callbacks and DLRs. No frontend calls these **by definition** |
| Referenced in Python | 41 | The path appears in `amplify/functions/**/*.py` — Lambda-to-Lambda invocation or handler self-reference. The caller is Python, not `src/**` |
| Parameterised, textually unmatchable | 21 | Contains `{invoiceId}`, `{fileId}`, `{documentId}` and similar. The frontend builds these as template literals, so the literal form **can never** match. For **12** of the 21 the path prefix *is* present in `src/**`, which is positive evidence they are live — `/secure-files/{fileId}/download` is the obvious one |
| Literal, unreferenced | **42** | The only genuine candidates |

And even that 42 is not a deletion list:

* **34** are `/wa-business/*` on `wecare-whatsapp-business-api` — appointments, reviews, FAQ, flow tooling, username management. A block that uniform points at one of two causes, and they need opposite actions: either the WhatsApp Business admin UI reaches them through a path-building helper the textual join cannot see, or those capabilities are backend-only and never had a UI. Resolve which before touching any of them.
* **4** are `/voice-in/obd/{create,upload-audio,upload-csv,clear-logs}`, which **deliberately answer** `_retired_campaign_endpoint` — an explicit "this capability was retired" response rather than a 404, so an operator sees why it vanished. Present on purpose.
* **3** are `/store/*` on `wecare-product-image-gen`, and `/voice-aws/send` is a send path.

So the honest count is: **0 proven dead**, 42 needing a caller resolved, and a method that structurally cannot see template-literal or Python callers. Reproduce with the classifier logic against
`anomalies.routesWithoutFrontendCaller` in `docs/execution/runtime-inventory.json`.

## Verify

```bash
aws amplify get-app --app-id d22dm4b0jn71jw --query 'app.customRules'
python scripts/generate_runtime_inventory.py   # re-derives the 117
curl -sI [retired public path 0e838b48]/calls       # expect 301
```

Use **`wecare.digital`**, not `retired legacy frontend host`. The `stack` CNAME
(`d2av2go6w170k.cloudfront.net`) was removed on 2026-09-25 and no longer resolves;
the snapshot is at
`docs/execution/snapshots/route53-stack-cname-before-removal.json`. Older documents,
including `bw-crm.md` itself, still name `retired legacy frontend host` as the live host.

Probed on 2026-09-25 against `wecare.digital`, all four confirmed **301** with the
filter intent intact:

| Probe | Result |
|---|---|
| `[retired public path 2de923b8]/calls` | `301 → [retired public path 2de923b8]/inbox/?channel=voice` |
| `[retired public path 2de923b8]/rcs/inbox` | `301 → [retired public path 2de923b8]/inbox/?channel=rcs` |
| `[retired public path 2de923b8]/ses/logs` | `301 → [retired public path 2de923b8]/logs/?channel=email` |
| `[retired public path 21d99b11]/logs` | `301 → [retired public path 21d99b11]/` |
