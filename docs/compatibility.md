# Vendor capability and version compatibility

Phase 0 output for the WhatsApp conversational commerce build.
Measured against account `775261844268` / `us-east-1` on **2026-09-26**.

Two things this document refuses to do: report a documented-but-unmeasured fact as
verified, and carry a number forward without saying how it was obtained. Per
`.kiro/steering/00-current-owner-overrides.md` (retired 2026-10-09, af7858fa) the counts below are a dated snapshot and
must be rediscovered at the start of each phase, not trusted.

## Evidence classes

| Class | Meaning |
|---|---|
| `LIVE` | measured against the account or the provider during this session |
| `DOC` | read from current official vendor documentation during this session |
| `REPO` | asserted by this repository's own code or docs, dated, not re-measured |
| `BLOCKED` | could not be established, with the blocker named |

## 1. AWS runtime and platform

| Component | Configured / actual | Latest GA | Evidence | State |
|---|---|---|---|---|
| Lambda runtime, existing fleet | `python3.12` on 64 of 64 functions | `python3.13` | `LIVE` `list-functions` runtime histogram | ✅ supported, not latest |
| Lambda runtime, proposed for new API | none yet | `nodejs24.x` | `DOC` Lambda added Node.js 24 support Nov 2025; LTS security/bug fixes expected to Apr 2028 | ⚠️ new runtime for this fleet |
| Node.js 26 | not used | preview only | `DOC` | ➖ correctly excluded |
| HTTP APIs | 1 — `zllr9lrg7j` (`wecare-digital-api`) | n/a | `LIVE` `get-apis` | ⚠️ drift: owner-overrides snapshot said 2 |
| IaC | Amplify Gen 2 (`@aws-amplify/backend ^1.23.0`) + CDK escape hatches, `aws-cdk-lib` pinned `2.270.0` | n/a | `REPO` | ✅ |
| Deploy path | `scripts/deploy_all_lambdas.py` → publish version → move `live` alias | n/a | `REPO` `.kiro/steering/lambda-snapstart-deploy.md` (retired 2026-10-09, af7858fa) | ✅ |
| SnapStart | `ApplyOn=None` on all functions | n/a | `REPO` measured 2026-09-19 | ✅ off by design |

**Consequence for the architecture.** The prompt's `nodejs24.x` + CDK v2 + TypeScript
baseline is valid and GA, but it introduces a **second runtime and a second deploy
toolchain** into a fleet that is 64/64 Python with a bespoke Python deployer. Lambda's
Node.js 24 also dropped callback-style handlers, so any vendored sample using
`(event, context, callback)` will not run. `design.md` records the decision and its cost.

## 2. Meta WhatsApp Cloud API

| Item | Value | Evidence | State |
|---|---|---|---|
| Graph version in use | `v25.0` | `REPO` | ⚠️ sourced inconsistently, see below |
| `v26.0` | deliberately not adopted | `REPO` `meta-business-agent/handler.py:231-235` records that v26.0 "blocked a batch of commerce" calls | ⚠️ the prompt's `v26.0` baseline is **rejected** until re-tested |
| Business sender | `+919330994400`, phone id `1016149501586345`, WABA `2094615664435155` | `LIVE` re-measured 2026-09-30 | ✅ **healthy** — quality GREEN, `CLOUD_API`, official business account, WABA `APPROVED`. The `if False: # Phone 1 DISCONNECTED` comment was **stale and wrong** |
| Secondary sender | `+919903300044`, phone id `1055232054343117`, WABA `2513394156072604` | `REPO` | ✅ |
| Payment configurations | historically `WECAREDIGITAL` (Razorpay, MID `acc_TTFSyolquKEZEy`), `WECAREUPI` | `REPO` verified live 2026-08-23 | ⛔ **NOT currently present** — see the correction below |
| Payments India surface | `order_details`, `review_and_pay`, `reference_id`, per-WABA payment configuration, payment lookup `GET /{phone_id}/payments/{config}/{reference_id}`, webhook status notifications | `DOC` Meta Payments-in (PG + UPI intent) | ✅ matches the implemented payload |
| Live re-measurement | not possible this session | `BLOCKED` `wecare-whatsapp-business-api` returned `No authorization token provided`; minting an admin token to probe is out of scope | ⛔ |

### ⛔ Correction, 2026-09-30 — the payment configurations are not live

The row above records a reading taken on **2026-08-23**, and it was almost certainly true then.
It is not true now. Re-measured today through `wecare-whatsapp-business-api:live`:

```
GET /2094615664435155/payment_configurations   ->   HTTP 200, ZERO configurations
```

This is not a failed call. `_check_payment_gateway` populates `metaApiResponse` only when the
Graph result carries an `error`, and it came back `null` — so Meta answered, and answered "none".
Both names report `status: local_only`, `canReceivePayments: false`.

**So `WECAREDIGITAL` and `WECAREUPI` currently exist only as Python constants.** Read the 2026-08-23
row as *historically verified*, not *currently verified*; that distinction is the whole reason this
document exists. Meta's own reference warns that when `configuration_name` is invalid the customer
is simply unable to pay, so nothing may send an `order_details` message until it is restored —
which is owner-administrative work in WhatsApp Manager, not something application code may do.

Two more names survive from before the 2026-08-23 rebuild, in
`.kiro/steering/META-BETA-REQUEST-EMAIL.md` (retired 2026-10-09, af7858fa): `WECARE-RAZOR-PAY` (WABA1) and
`Razorpay_ManishAgarwal` (WABA2). Four configuration names across three files; none at Meta.

### ⚠️ Correction, 2026-09-30 — the Razorpay MID and UPI VPA both conflict

Neither value may be hard-coded until a restored configuration can be read back and compared.
They are not symmetric, though, and the asymmetry is the useful part:

| Value | Evidence | Weight |
|---|---|---|
| Retired account | Previously present in Lambda environment and historical webhook events. Removed from current source identifiers on 2026-10-02. | Retired; do not use for new payments |
| `acc_TTFSyolquKEZEy` | Owner-confirmed merchant decision, documented in `lambda_utils/payment_readiness.py` and pinned in the deployment manifest. | Authoritative merchant ID; API-key ownership still requires verification |

They are also different *fields*: one is the Razorpay merchant account, the other was only ever
claimed as the Meta configuration's `provider_mid`. `lambda_utils/payment_readiness.py` refuses
to enable payments unless the two agree.

The same shape applies to the UPI VPA: live env says `[retired UPI VPA]`, the code's
documented fallback says `wecaredigitalbh511413.rzp@rxairtel` — a different handle **and** a
different PSP suffix.

---

**Graph version sourcing is the real defect**, not the version number. `v25.0` reaches the
runtime three different ways: an env var with a default (9 files), a hard-coded module
constant with no env override (7 files), and a literal embedded in a URL string (3 files,
including the payment-lookup call). A single configurable source does not exist, so the
prompt's "must be upgradeable without rewriting business logic" requirement is currently
**unmet**.

## 3. Commerce and blog — native AWS

Commerce and the blog have no third-party backend, so there is no external commerce or blog API
version to track here.

| Item | Implementation | State |
|---|---|---|
| Catalogue | `stack-wecare-digital-ProductsTable` | ✅ native |
| Cart | `stack-wecare-digital-CartTable` | ✅ native |
| Order identity / idempotency keys | `stack-wecare-digital-CommerceKeys` | ✅ native |
| Orders | `stack-wecare-digital-OrderTable`, written only after verified payment | ✅ native |
| Checkout | `wecare-checkout`, payment through Razorpay | ✅ native |
| Invoices / receipts | homegrown: `payments/invoice-engine` + 5 tables + per-FY sequence | ✅ native |
| Blog | posts in `stack-wecare-digital-SeoToolsTable`, served by `wecare-blog-public` | ✅ native |

## 4. Frontend

| Item | Value | Evidence | State |
|---|---|---|---|
| Framework | Next.js 16 + React 19, `pages` router, `output: 'export'` | `REPO` | ⚠️ conflicts with prompt's Astro default |
| Hosting | Amplify app `d22dm4b0jn71jw` | `REPO` | ✅ |
| Server-side code | **none** — static export has no server, so no middleware and no route handlers | `REPO` `next.config.js` | ⚠️ constrains tracking-token handling |

The static export is load-bearing for the design: there is no server-side session layer in
the frontend, and a tracking token cannot be validated there. Both live in Lambda.
`design.md` §Tracking security depends on this.

## 5. Drift watch

Re-derive before each phase rather than trusting this table.

| Fact | Snapshot | How to re-derive |
|---|---|---|
| Function count / runtimes | 64, all `python3.12` | `aws lambda list-functions --query 'Functions[].Runtime'` |
| HTTP APIs | 1 (`zllr9lrg7j`) | `aws apigatewayv2 get-apis` |
| Functions with a `live` alias | drifts as aliases are provisioned | `ListFunctions` + `ListAliases`, sequentially, reporting the error total |
| Secret inventory | 25 | `aws secretsmanager list-secrets` |
| Meta payment configs | 2 per WABA, dated 2026-08-23 | `/whatsapp-business/payment-config/check` with an admin token |
| Graph version | `v25.0`, v26.0 rejected | `grep -rn META_API_VERSION amplify/` |
