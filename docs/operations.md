# Operations

Runbook for the customer identity, verification, address, account and public commerce
surface. Companion to [`docs/design.md`](design.md) and [`docs/security.md`](security.md).

Existing runbooks stay authoritative for what they already cover:
[`docs/RUNBOOK.md`](RUNBOOK.md), [`docs/CREDENTIAL-ROTATION-RUNBOOK.md`](CREDENTIAL-ROTATION-RUNBOOK.md),
[`docs/WEBHOOK-INVENTORY.md`](WEBHOOK-INVENTORY.md) and
[`docs/RESILIENCE_BLUEPRINT.md`](RESILIENCE_BLUEPRINT.md). This file adds the new surface and
does not restate them.

## Environment

| Thing | Value |
|---|---|
| Account / region | `775261844268` / `us-east-1` |
| Profile | `AWS_PROFILE=wecare-prod`, long-term key from `~/.aws/credentials` |
| API | `zllr9lrg7j`, stage `prod`, `AutoDeploy=true`, access logging on, base `https://api.wecare.digital` |
| Hosting | Amplify `d22dm4b0jn71jw`, repo `wecare-digital/wecare-digital`, 23 custom rules |
| Branch | `stack` — the only long-lived branch; there is no `main` |
| Customer pool | `us-east-1_46ULYuukt` |
| Staff pool | `us-east-1_cSx0RHCIR` |
| WABA / sender | `2094615664435155` / phone id `1016149501586345` = `+91 93309 94400` |
| Email sender | `one@wecare.digital`, SES config set `wecare-digital` |
| Google project | `wecaredigitalbw` (`756034744787`) |

Do not use `aws login` or `aws sso login`. `[default]` in `~/.aws/config` is bound to a
browser session that expires roughly every 12 hours and then blocks every AWS call;
`AWS_PROFILE` exists to override it. Verify with `aws sts get-caller-identity` — it must
report `775261844268`.

## Daily checks

```bash
# Auth and account
aws sts get-caller-identity

# Version policy. Fails on any error finding; warnings are recorded lags with reasons.
node scripts/check-versions.ts

# DLQ depth. Non-zero means a business event did not complete.
for q in bulk inbound notification outbound; do
  aws sqs get-queue-attributes \
    --queue-url "https://sqs.us-east-1.amazonaws.com/775261844268/stack-wecare-digital-${q}-dlq" \
    --attribute-names ApproximateNumberOfMessages \
    --query "Attributes.ApproximateNumberOfMessages" --output text
done

# SES health. EnforcementStatus must be HEALTHY; a rising bounce rate under p=reject is urgent.
aws sesv2 get-account --query '[EnforcementStatus,SendQuota,SuppressionAttributes]'

# WhatsApp sender quality. A drop from GREEN precedes throttling.
aws lambda invoke --function-name wecare-waba-management:live \
  --payload '{"httpMethod":"GET","path":"/waba/2094615664435155","pathParameters":{"wabaId":"2094615664435155"}}' \
  --cli-binary-format raw-in-base64-out .scratch/waba.json
```

Scratch output belongs in `.scratch/` inside the workspace, which is gitignored and needs no
permission grant. Writing to `/tmp` falls outside the registered workspace root and prompts
per filename.

## Deploying

Mandatory, and it is the **`live` alias** that makes it mandatory, not SnapStart — which is
`ApplyOn=None` on all 65 functions.

```bash
# 1. Gates first. A command exiting zero is not evidence of correct behaviour, but a
#    failing gate is conclusive evidence not to deploy.
npm run lint && npm run typecheck && npm run test && .venv/bin/pytest -q
node scripts/check-versions.ts

# 2. Capture the rollback target BEFORE changing anything.
aws lambda get-alias --function-name <fn> --name live --query FunctionVersion

# 3. Build, validate imports, upload to $LATEST.
.venv/bin/python scripts/deploy_all_lambdas.py <fn>

# 4. Publish a version, wait for State=Active, move the live alias.
.venv/bin/python scripts/snapstart_publish.py <fn>
```

`update-function-code` alone updates `$LATEST` and **changes nothing in production** for any
function carrying a `live` alias. `deploy_all_lambdas.py` calls the publisher itself; a manual
deploy must run it explicitly or the API keeps serving old code.

Frontend deploys through Amplify on push to `stack`. Redirects and headers are Amplify
`customRules`, **not** `next.config.js` — a static export emits no server redirects, and the
`headers()` block in `next.config.js` does not apply.

### Adding a public route — three steps, not one

Getting this wrong produces a page that returns HTTP 200 with an empty body, which is a 404
that does not look like one and is invisible until someone loads the URL.

1. Create the page under `src/pages/`.
2. Add the exact pathname to the allowlist in `src/pages/_app.tsx`.
3. Extend `src/test/PublicRouteRegistration.test.ts`.

A public page must not import the authenticated `Layout`. That combination once served the
entire staff sidebar publicly at HTTP 200, because a prerendered export has no session so
`Layout` rendered in full. The test now fails it.

## Secrets

Read by reference, lazily, at request time. Never at import scope — a module-scope read is
cached for the life of the execution environment, so replacing a value does not change what a
warm sandbox serves.

```bash
# Inventory. Names only; never fetch a value.
aws secretsmanager list-secrets --query 'SecretList[].Name' --output text | tr '\t' '\n' | sort

# Wix credential state, without reading it
.venv/bin/python scripts/set_wix_credential.py --status

# After changing a secret, recycle its consumers so warm sandboxes stop serving the old value
.venv/bin/python scripts/refresh_secret_consumers.py <secret-id>
.venv/bin/python scripts/check_secrets_live.py
```

`aws secretsmanager get-secret-value` is denied by `block-catastrophic`. That is the point, not
an obstacle: a value pulled into a shell is a value in a log, a transcript, and potentially a
permissions file. Never put a credential on a command line — four live credentials reached
Kiro's permissions file in cleartext exactly that way, and `block-inline-secrets` now denies
the shape.

New secrets this build needs:

| Secret | Holds | Consumer |
|---|---|---|
| `wecare/otp/pepper` | HMAC pepper for OTP challenges | `OtpService` |
| `wecare/session/signing` | session and CSRF signing material | customer API functions |
| `wecare/tracking/token-pepper` | tracking-token hashing pepper | tracking and billing readers |
| `wecare/google-maps-server` | ❌ **BROKEN as of 2026-09-30** — the secret still holds a key, but that key was DELETED in Google Cloud the same day, so it is expired. See the note below before relying on any of it | `AddressService`, and the Places proxy once repointed |
| `wecare/google-maps-browser` | ⏳ restricted **browser** Maps key | frontend build injection |

`wecare/google-maps-server` was minted on 2026-09-26 by
`scripts/provision_maps_server_key.py --create` and was proven live at the time. Do **not**
extend the existing unified key to cover server use — it is a browser key, and Google refuses
referrer-restricted keys for server-side calls whatever their `apiTargets` say. That was tried
first and it does not work.

**Where the server key goes now, corrected 2026-10-05.** `provision_maps_server_key.py` no
longer writes `wecare/google-maps-server`. It writes the canonical **`wecare/google/cloud`**,
replacing only that secret's `api_key` and `unified_google_api_key` fields through a
read-merge-write so the project metadata siblings survive, and printing the preserved field
names so the merge is checkable without reading the secret back. The canonical id is the one
all three consumers (`site-language`, `whatsapp-templates`, `vayulok-environment`) already
default to, and `tests/test_one_google_key.py` enforces that — which is what makes the
owner's single deferred rotation reach every consumer instead of one. The row above and the
BROKEN callout below remain accurate history for `wecare/google-maps-server`; they are not
the current target.

> **BROKEN 2026-09-30, and the break is invisible from the secret.** The key that secret holds
> — Google Cloud API key `WECARE Address Capture Server Key`, uid `d936bd15-...`, created
> 2026-09-26 — was **deleted on 2026-09-30**. `gcloud services api-keys list --show-deleted`
> shows the deletion; `scripts/check_secrets_live.py` reports the consequence:
>
> ```
> wecare/google-maps-server   INVALID   REQUEST_DENIED: The provided API key is expired.
> ```
>
> It is the ONLY INVALID credential in the account (VALID 7, INVALID 1, UNTESTABLE 14).
>
> **Why this is worth a callout rather than a line edit.** Nothing about the secret looks
> wrong: it exists, it parses, it holds an `api_key` of the correct 39-character shape. Only a
> live call reveals it. So the failure mode is a server-side Maps call that fails in
> production while every piece of configuration inspects as healthy — which is precisely the
> situation the checklist below was written to diagnose, and it would previously have sent a
> reader to item 1 ("which key is the caller reading?") when the answer is "the right one, and
> it is dead".
>
> **Re-mint with `scripts/provision_maps_server_key.py --create`.** Deliberately NOT done when
> found: minting a provider credential is reserved to the owner, and the owner has deferred
> all key work until project completion. Until then, treat every server-side Maps and Places
> path as unavailable rather than merely unbuilt.

```bash
.venv/bin/python scripts/provision_maps_server_key.py --status   # key + secret + live probe
.venv/bin/python scripts/provision_maps_server_key.py --verify   # live probe only
```

## Alarms

| Alarm | Condition | Why |
|---|---|---|
| DLQ depth | any queue > 0 | a business event did not complete |
| Reconciliation failure | any | a captured payment is unreconciled; money has moved |
| `WebhookSignatureFailed` | > 0 sustained | forged or misconfigured webhook |
| OTP send failure rate | > 5% over 15 min | Meta or SES degradation, or a template problem |
| OTP rate-limit hits | sharp rise | enumeration or abuse in progress |
| SES bounce rate | > 2% | under `p=reject` a bounce spiral becomes a sending suspension |
| SES complaint rate | > 0.1% | reputation |
| WhatsApp quality | not `GREEN` | precedes throttling |
| Duplicate order prevented | > 0 | the control is working, and something is retrying hard |
| Lambda throttles | > 0 on customer-facing functions | capacity or a burst |
| Amplify build failed | any | `wecare-amplify-build-failed` rule already exists |

## Incidents

### OTP not arriving on WhatsApp

Check in this order — the cheap, likely causes first.

1. Sender quality and account state: `GET /waba/{wabaId}` as above. `enableSending` must be
   true, quality `GREEN`, `accountReviewStatus APPROVED`.
2. Template state: list templates and confirm `wecare_otp` is still `APPROVED` and still
   `AUTHENTICATION`. Meta can pause or re-categorise a template with no change on our side.
3. Is the customer stamped with `custom:partner_waba_id` matching the configured WABA? The
   trigger raises `PermissionError` before any send if not, so an unstamped user can never
   receive a code.
4. Was a `copy_code` button parameter introduced? Meta rejects it with
   `(#132018) buttons: Button at index 0 must be of type Url`, which surfaces only as
   "sender returned HTTP 400". It must be `url`.
5. Rate limits: is this number over budget? Limiters fail closed by design.
6. `wecare-whatsapp-business-api:live` logs. Note the sender is that function, not
   `wecare-outbound-whatsapp`.

`codeVerificationStatus` on the sender is currently `EXPIRED`. That is **not** the cause of a
delivery failure — the number is registered, sending is enabled and quality is GREEN. It
matters only if the number has to be re-registered, which is owner-only work.

### OTP not arriving by email

1. `aws sesv2 get-account` — `EnforcementStatus` must be `HEALTHY`.
2. Is the address on the suppression list?
   `aws sesv2 get-suppressed-destination --email-address <addr>`
3. Is `ConfigurationSetName: wecare-digital` being passed? The `one@wecare.digital` identity
   has **no default configuration set**, so omitting it silently skips reputation tracking and
   suppression.
4. Confirm the sender identity is still verified: `aws sesv2 list-email-identities`.
5. Alignment. The domain is `DMARC p=reject` with MTA-STS `enforce`, so an unaligned message
   **hard-bounces**; it does not go to spam. Run `scripts/verify-email-auth.ps1` and treat a
   non-zero exit as do-not-proceed.
6. Never set `aspf=s`. Wix/SendGrid sends with envelope-from `sg.wecare.digital` against
   header From `wecare.digital`, and only relaxed SPF alignment lets that pass.

### Address autocomplete returning nothing

Check in this order. The first item is first because it is the failure that already happened
and it masquerades as every other cause.

1. **Which key is the caller reading?** A server-side caller must read
   `wecare/google-maps-server`. If it reads `wecare/google-maps` it is holding the **browser**
   key, and Google refuses it outright — `API_KEY_HTTP_REFERRER_BLOCKED` on Places (New), and
   `REQUEST_DENIED: API keys with referer restrictions cannot be used with this API` on legacy
   Maps. No `apiTargets` edit fixes this; the key type is the problem.
   ```bash
   .venv/bin/python scripts/check_secrets_live.py --only google-maps
   ```
   Expect `wecare/google-maps` UNTESTABLE — a browser key genuinely cannot be validated from a
   server, which is a statement about the test, not a fault in the key.

   `wecare/google-maps-server` **used** to be the VALID half of that pair and is not any more:
   since 2026-09-30 it reports `INVALID — REQUEST_DENIED: The provided API key is expired`,
   because the underlying Google Cloud key was deleted. So if you reach this step and find the
   caller IS reading `wecare/google-maps-server`, item 1 is satisfied and the fault is further
   down: the key itself is dead and needs re-minting. Do not read an INVALID here as "wrong
   secret".
2. Is `places.googleapis.com` in that key's `apiTargets`?
   `gcloud services api-keys list --format='json(displayName,restrictions)'`. Being enabled on
   the project is **not** sufficient; the key restriction is separate.
3. Is the query at least 3 characters?
4. Is the key resolving from Secrets Manager at all — lazily, at request time?
5. Quota or billing on project `wecaredigitalbw`.
6. Autocomplete must degrade to manual structured entry, never block registration. If a
   Places outage is blocking signups, that is a bug in the fallback, not in Google.

### A customer has two accounts

This should be impossible; `TransactWriteItems` on both `UNIQUE#` markers prevents it. If it
happens, the control was bypassed, so find the bypass before merging anything.

1. Query both `UNIQUE#PHONE#` and `UNIQUE#EMAIL#` markers and confirm which `customerId` each
   points at.
2. Look for a write path that does not go through the transaction — that is the defect.
3. Do **not** silently merge. Identity resolution is an explicit, audited action.
4. Preserve both audit trails. Orders follow `customerId`, so a merge has to move order
   references deliberately.

### Reconciliation failed after a captured payment

Money has moved. Treat as urgent, and do not retry blindly.

1. Identify the order from the `reference_id` in the failure log.
2. Confirm the payment at the provider before touching order state.
3. If amount or currency mismatched, reconciliation **failed closed** — that is correct
   behaviour, and the mismatch is the thing to investigate.
4. If Wix was unavailable, the order is in a recoverable state: retry from the admin surface.
   Retries are idempotent; the same event resolves to the same order.
5. Never create a second Wix order and never call a Wix API that would charge again.
   Recording a payment is not collecting one.

### Rollback

```bash
# Lambda: move the alias back to the version captured before deploying
aws lambda update-alias --function-name <fn> --name live --function-version <previous>

# Frontend: redeploy the previous Amplify job, or revert the commit on stack
```

Rollback notes worth knowing before you need them. DMARC is one Route 53 record at a 300 s
TTL, so it reverts in about 5 minutes. **MTA-STS does not** — senders honour a cached policy
for up to `max_age` (604800 s), and reducing `max_age` does not shorten an already-cached
entry. Treat MTA-STS enforce changes as effectively one-way for a week. Changing MX requires
7 days of lead time for the same reason.

## Git

Single branch. Commit directly to `stack`; do not create feature branches unless asked by
name. Push with `git push origin stack`.

Stage by explicit path, always — `git add .`, `-A`, `-u`, `git commit -a` and bare
`git stash` are denied by `block-broad-git-staging`. Several sessions share this working tree
and index, so a tree-wide stage sweeps another session's files into your commit. Check
`git status --short` and `.venv/bin/python scripts/session_map.py` first; if a modified file
is not yours, leave it.

One committer at a time. Concurrent pushes to `stack` race and the loser gets a
non-fast-forward.

## Cost

| Driver | Control |
|---|---|
| WhatsApp authentication messages | per-phone and per-IP OTP limits, failing closed |
| SES | 50,000/day quota; suppression consumed so bounces are not retried |
| Google Places | session tokens bundle keystrokes plus the details call into one billable session; 3-character minimum |
| Lambda | reserved concurrency on customer-facing functions |
| DynamoDB | TTL on OTP challenges, carts, sessions and tracking tokens so tables do not grow without bound |
| CloudWatch | log retention set explicitly; the default is never-expire |

## Reports

```bash
.venv/bin/python scripts/maintenance_report.py          # local, timestamped
.venv/bin/python scripts/maintenance_report.py --s3     # plus SSE-KMS sync
```

Historical reports are never overwritten; each run gets its own directory. Reports may carry
account ids, ARNs, function names and versions, secret **names**, rotation status, commit
hashes and test results. They must never carry a password, token, API key, secret access key,
private key, session token, or a raw Secrets Manager value — the generator refuses to write
when credential-shaped material is detected.

## Known open operational items

Inherited, outside this build's scope, and recorded so they are not rediscovered as surprises.

- **`/plivo/answer` is unauthenticated and can send SMS.** Closing it needs both sides, in
  this order: add `?token=` to all three Plivo URLs **first** (harmless while the Lambda has
  no token, because the gate stays off), then set the token on the Lambda. Reverse that order
  and every inbound WhatsApp call 403s in between and the caller hears silence.
- **No WAF coverage anywhere, as of 2026-09-28.** Both web ACLs were deleted by owner cost
  decision, so `wecare-cognito-waf` no longer covers the Cognito pools and
  `wecare-amplify-waf` no longer fronts the Amplify app. Separately, and still true, a WebACL
  could never have covered the API: WAFv2 does not support API Gateway HTTP APIs, and
  `GetWebACLForResource` on the `zllr9lrg7j` stage ARN returns
  `WAFInvalidParameterException`. Rate limiting therefore comes from per-route throttling plus the
  handler-level `RateLimitTable`, unless the API is moved behind CloudFront. Do not raise a
  ticket to "attach a WebACL to the HTTP API" — it will not succeed.
- **Wix is live as of 2026-09-26.** The credential is stored, Catalog V3 is measured rather
  than inferred (`/stores/v1/*` returns HTTP 428 `CATALOG_V3_CALLING_CATALOG_V1_API`), and the
  site holds 7 products and 571 blog posts. Two things follow. **Wix Invoices is NOT
  available** — `/invoices/v2/invoices` returns 404, which corroborates keeping the homegrown
  engine. And the catalog is **thin**: 7 products, 1 category, 0 brands. A commerce launch
  needs that populated, which is content work, not engineering.
- **SES DKIM anomaly:** three Easy DKIM tokens are listed as current but AWS publishes a key
  for only one. SES signs with one selector per message, so one published key is sufficient
  and status is `SUCCESS`. Unverified: which selector SES actually uses. Confirm by reading
  `s=` in a real message's `DKIM-Signature`. Do not rotate SES DKIM casually while
  `p=reject` is live — during propagation mail fails closed.
