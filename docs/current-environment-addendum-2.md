# Current environment — addendum 2: vendor deprecation and stale signals

Companion to [`current-environment.md`](current-environment.md),
[`current-environment-addendum.md`](current-environment-addendum.md) and
[`compatibility.md`](compatibility.md). Measured **2026-09-26** against account
`775261844268` / `us-east-1`, Meta's published changelogs, and the live site.

**Why a third file.** Four Kiro sessions worked this brief against one shared working tree.
The Phase 0 document set (`current-environment.md`, `spec.md`, `design.md`, `tasks.md`,
`security.md`, `operations.md`, `compatibility.md`) is the authority. This file **adds only
findings that appear in none of them** — each one was checked before inclusion — and it
re-rules and restates nothing. Written as a separate file for the same reason `addendum.md`
was: an append to a file another session is actively editing is silently lost.

Every row below is `LIVE` (measured against the account, the provider, or the live site during
this session) or `DOC` (read from current official vendor documentation during this session).
No secret value was read; `get-secret-value` was never called from any surface.

---

## 1. Graph API v26.0 — the recorded reason for avoiding it is wrong, and the pin expires in 31 days

**Severity: HIGH.** This is the only finding here with a hard external deadline.

`amplify/functions/messaging/meta-business-agent/handler.py:231-234` pins the version away from
v26.0:

> Deliberately NOT v26.0: that release blocked a batch of commerce endpoints, and
> `_tool_product_lookup` below reads `/{catalog_id}/products`.

Checked against Meta's own v26.0 changelog. **The stated reason does not hold.**

| Fact | Evidence |
|---|---|
| v26.0's commerce deprecation is the **Commerce Order Management API** — 47 endpoints, all shaped `/{commerce-order-id}/…`, `/{page-id}/commerce_orders`, `/{commerce-merchant-settings-id}/…`. It exists because checkout on Facebook and Instagram Shops was sunset. No replacement API | `DOC` v26.0 changelog |
| `GET /{catalog_id}/products` — what `_tool_product_lookup` actually calls, confirmed at `handler.py:105-118` — is the **Product Catalog API**. It is **not** among the 47 | `DOC` + `LIVE` repo read |
| This repository calls **none of the 47**. Grepped `amplify/`, `src/`, `scripts/` for `commerce_order`, `commerce-order`, `commerce_merchant_settings`, `commerce_returns`: **0 matches** | `LIVE` |
| It also uses **none** of the five legacy protocol features v26.0 removes — `pretty`, `debug`, `date_format`, root `GET /?ids=`, `If-None-Match`: **0 matches** | `LIVE` |

**And the pin protects nothing past 2026-10-27.** The changelog states the affected commerce
surfaces and the legacy protocol features are removed from **all remaining Graph API versions on
27 October 2026** — 31 days from this measurement. Staying on v25.0 buys a month, then behaves
identically.

Version horizons, for the record: v26.0 released 2026-07-29; v25.0 released 2026-02-18 and
expires **2028-07-29**, so v25.0 is supported rather than deprecated; **v20.0 was removed on
2026-09-24**, two days before this measurement; v21.0 is removed 2027-01-21.

**Still unverified, and it matters.** Whether `GET /{catalog_id}/products` actually answers on
v26.0 needs one live Graph call, which was **not** made. This finding establishes that the
documented blocker is unsubstantiated — not that the upgrade is safe. Treat it as grounds to
test, not as clearance.

**Recommended:** a CI gate refusing any use of the 47 endpoints or the 5 protocol features, so a
future addition fails the build rather than the 27 October cutover.

## 2. The Graph API version cannot be changed by configuration

**Severity: HIGH.** There is no `META_GRAPH_API_VERSION` symbol anywhere. The names in use are
`META_API_VERSION` and `META_GRAPH_BASE`, and there are three competing mechanisms:

| Mechanism | Count | Note |
|---|---|---|
| Env var with a per-function default | ~9 | Each function re-declares the default |
| **Hardcoded literal, no override** | **9** | Includes the **main sender**, `messaging/outbound-whatsapp/handler.py:341` |
| Deployed env var actually set | 4 functions + 1 `META_GRAPH_BASE` | `config/lambda-env-manifest.json` |

Every value found is `v25.0`. Consequence: acting on §1 is a nine-file edit and a fleet redeploy,
not a config change. Also present outside the fleet: `src/pages/_app.tsx:1022` and `:1093`
(Facebook JS SDK), `src/components/wa/selectors.tsx:39`, `src/pages/dm/whatsapp/template-builder.tsx:231`.

`DOC` + `LIVE`.

## 3. Stale monitoring references — RESOLVED

**Resolved 2026-10-24.** Live remeasurement shows 67 WECARE metric alarms and no alarm
dimension referencing a missing HTTP API, SQS queue, or SNS topic. The obsolete alarms for
retired API `79g3bbufdh` and the removed blog-ingest queues were deleted. The SNS delivery
failure alarm now watches the live `stack-wecare-digital` topic, whose Lambda subscriber is
`wecare-inbound-whatsapp`.

`LIVE` `DescribeAlarms` + `ListQueues` + `GetApis` + `ListTopics`.

## 4. SES engagement tracking is on for an account that sends OTP mail

**Severity: LOW.** `sesv2 GetAccount` reports:

```
VdmEnabled                              ENABLED
DashboardAttributes.EngagementMetrics   ENABLED
GuardianAttributes.OptimizedSharedDelivery  ENABLED
```

This resolves a question left open in `docs/kiro-handoff.md` ("still unverified whether it
injects a tracking pixel into OTP mail") **at the account level only**: the switch is on.
Whether Cognito OTP mail actually carries a pixel is still unverified and needs one delivered
message inspected. Account posture for context: production access enabled, `HEALTHY`, 50,000/day,
14/s, 0 sent in the last 24h. `LIVE`.

## 5. `live` alias coverage is 58 of 65

The release contract in `.kiro/steering/lambda-snapstart-deploy.md` (retired 2026-10-09, af7858fa) only binds where the alias
exists. Measured sequentially with **0 call errors** — a concurrent count that swallows failures
reports this wrong, which has happened before:

```
61 functions   60x python3.12 + 1 container image
57 with a `live` alias
 4 without: wecare-docs-scraper, wecare-get-miss-redirect,
            wecare-partner-token-refresh, wecare-seo-tools
```

For those 7, `update-function-code` takes effect immediately. The steering's dated snapshot said
53/9 and then 58/7; the count drifts as aliases are provisioned, so re-derive it. `LIVE`.

## 6. A pitfall when verifying WAF association

`wafv2 ListResourcesForWebACL` defaults `ResourceType` to **`APPLICATION_LOAD_BALANCER`**. Called
without it against `wecare-cognito-waf` it returns an empty list, which reads as "associated with
nothing."

Measured with the type set explicitly:

| `ResourceType` | Result |
|---|---|
| `COGNITO_USER_POOL` | `us-east-1_cSx0RHCIR` — the **staff** pool |
| `API_GATEWAY` | none |
| `APPSYNC` | none |

The Amplify web ACL is confirmed a different way, via `amplify GetApp` →
`wafConfiguration.wafStatus = ASSOCIATION_SUCCESS`, because Amplify's CloudFront distribution is
not in this account's `ListDistributions`. Recorded so a future audit does not conclude "no WAF"
from a default-parameter call. `LIVE`.

---

## Findings, as a checklist

| § | Finding | Severity | Deadline |
|---|---|---|---|
| 1 | v26.0 avoidance reason unsubstantiated; commerce surfaces vanish from **all** versions | **HIGH** | **2026-10-27** |
| 2 | Graph version not centrally configurable — 9 hardcoded, incl. the main sender | **HIGH** | blocks §1 |
| 3 | 4 alarms can never fire | LOW | — |
| 4 | SES engagement tracking on an OTP-sending account | LOW | — |
| 5 | `live` alias on 58 of 65; 7 deploy immediately | INFORMATIONAL | — |
| 6 | `ListResourcesForWebACL` default hides Cognito association | INFORMATIONAL | — |

§1 and §2 are the only ones with a date attached. Everything else is a correctness or
signal-quality item with no external clock.
