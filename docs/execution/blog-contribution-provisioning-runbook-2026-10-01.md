# Blog contribution (BLOG_CONTRIBUTION) provisioning runbook (2026-10-01)

> STATUS: BLOCKED-ON-ENVIRONMENT. Not executed.
>
> This document is a runbook only. Nothing in it has been run. The sandbox has
> no AWS credentials: `aws sts get-caller-identity` fails, there is no `~/.aws`
> and no `wecare-prod` profile. Every live operation below (route wiring, IAM,
> alias move, live monetary test) is reported BLOCKED-ON-ENVIRONMENT and must be
> run by an authorized operator once credentials arrive through the sandbox
> environment, never from a key pasted into chat.
>
> This is the Section 5 sibling of
> `docs/execution/website-checkout-provisioning-runbook-2026-10-01.md`. The
> BLOG_CONTRIBUTION backend reuses the SAME `wecare-checkout` function, the SAME
> disabled initiation gate, and the SAME commerce-keys table as the website
> checkout, so most of the groundwork is already covered by that runbook. This
> document only adds what is specific to the voluntary-contribution purpose: the
> `/ecommerce/contribution` route the shipped UI calls, and the (unchanged)
> least-privilege and gate posture.

## Scope and safety rules (read before anything)

- **Account / profile / region:** account `775261844268`, profile `wecare-prod`,
  region `us-east-1`. Every command below assumes
  `--profile wecare-prod --region us-east-1`.
- **A chat-pasted AWS key must never be used, stored or echoed.** The only
  acceptable credential source is the sandbox environment / a configured
  `wecare-prod` profile.
- **Secrets are referenced, never read.** Never call
  `secretsmanager get-secret-value`, never print a secret value. The Razorpay
  API secret (`wecare/razorpay/api`) is referenced by ARN only; it is the SAME
  secret the website checkout already uses.
- **The initiation gate stays DISABLED.** No step here sets
  `CHECKOUT_INITIATION_ENABLED`, and the readiness inputs
  `EXPECTED_CONFIGURATION_NAME` / `EXPECTED_PROVIDER_MID` remain empty. With the
  gate off, `prepare_contribution` returns `PAYMENT_INITIATION_DISABLED`: no
  gateway order, no payable attempt. A contribution can never reach a live charge
  until an authorized operator deliberately turns the gate on, and no constant in
  the code can force it on.
- **A contribution is NOT an order.** A captured BLOG_CONTRIBUTION settles only
  the contribution record in the `BLOGCONTRIB#` namespace. It creates NO Wix
  Store product, NO purchase order, and mints NO public order number. Nothing in
  this runbook provisions any Wix-side object for contributions.
- **`_routes.json` is a dated inventory snapshot, not runtime config.** Routes
  live in the AWS HTTP API (apigatewayv2). Rediscover the current API id every
  time; never reuse a stale id.
- **Git workflow (this task):** the owner override commits all work to the
  already-checked-out branch `feature/customer-experience-upgrade`, explicit-path
  staging only, no push and no PR (the orchestrator pushes).

### How to confirm the environment blocker is cleared

Run this first. Until it prints the expected account, every section stays
blocked:

```sh
aws sts get-caller-identity --profile wecare-prod --region us-east-1
# expect: "Account": "775261844268"
```

---

## Section 1: the `/ecommerce/contribution` route on `wecare-checkout`

The contribution backend is handler-free business logic in
`amplify/functions/shared/lambda_utils/ecommerce/blog_contribution.py`
(`prepare_contribution` / `verify_contribution_callback` /
`settle_contribution_capture`), tested offline exactly like
`website_checkout.py`. It runs inside the EXISTING `wecare-checkout` function and
reuses its role, its `live` alias, its commerce-keys / payment-attempts tables
and its Razorpay API secret. There is nothing new to provision at the function
level; `scripts/provision_checkout.py` already leaves the gate DISABLED.

The ONE addition is the HTTP route the shipped UI
(`src/components/BlogContribution.tsx`) calls:

- **`POST /ecommerce/contribution`** — the initiation endpoint. The browser POSTs
  `{ purpose: "BLOG_CONTRIBUTION", postId, slug, amountPaise, currency }`. The
  handler dispatches to `blog_contribution.prepare_contribution`, which validates
  the amount SERVER-SIDE against the exact `CONTRIBUTION_PRESETS_PAISE` allow-list
  (₹100 / ₹250 / ₹500), so the browser cannot widen it or submit a custom amount,
  reserves the authoritative contribution record, and — only when the
  gate is on — creates and binds a Razorpay gateway order. Gate off (the default)
  returns `PAYMENT_INITIATION_DISABLED` with no gateway order.

The browser-result verify step reuses the SAME handler action pattern the website
checkout uses (`verify_contribution_callback`, HMAC over the server-stored order
id plus an authoritative capture readback). It can be exposed either as an action
on the same `/ecommerce/contribution` route (the handler branches on an `action`
field, matching `ecommerce/checkout/handler.py`) or as a sibling
`POST /ecommerce/contribution/verify`. The shipped UI currently only drives
initiation and never treats a browser callback as proof, so wiring the verify
action is required before the gate is ever enabled, not before the UI renders.

> FRONTEND CONTRACT MATCH: the handler's response `status` values MUST be the
> website-checkout contract strings the UI branches on —
> `PAYMENT_INITIATION_DISABLED`, `CHECKOUT_OPTIONS_READY`, `CHECKOUT_REJECTED`,
> `CHECKOUT_AMBIGUOUS` — which `blog_contribution` already returns verbatim. The
> UI's base URL is `${NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api'}` and
> the path is `/ecommerce/contribution`, so the route key below matches the
> shipped client with no UI change.

### Ordered operator commands

1. **Rediscover the current HTTP API id.** Never reuse a stale id.

   ```sh
   aws apigatewayv2 get-apis --profile wecare-prod --region us-east-1 \
     --query "Items[?Name=='wecare'] || Items[].{Name:Name,ApiId:ApiId,Endpoint:ApiEndpoint}"
   ```

   ```sh
   API_ID=<the id printed above>
   ```

2. **Confirm the checkout function and gate are already provisioned and the gate
   is OFF** (Section 1 of the website-checkout runbook). No new function is
   created here:

   ```sh
   AWS_PROFILE=wecare-prod AWS_REGION=us-east-1 \
     .venv/bin/python scripts/provision_checkout.py --verify
   # expect: "initiation: OFF (expected)"
   ```

3. **Add the `/ecommerce/contribution` route and integration**, targeting the
   `live` alias of `wecare-checkout`. Create the integration, grant the
   alias-qualified invoke permission BEFORE the route is reachable, then create
   the route.

   ```sh
   ALIAS_ARN=arn:aws:lambda:us-east-1:775261844268:function:wecare-checkout:live

   CONTRIB_INT=$(aws apigatewayv2 create-integration --profile wecare-prod --region us-east-1 \
     --api-id "$API_ID" --integration-type AWS_PROXY \
     --integration-uri "$ALIAS_ARN" --payload-format-version 2.0 \
     --query IntegrationId --output text)

   aws lambda add-permission --profile wecare-prod --region us-east-1 \
     --function-name wecare-checkout --qualifier live \
     --statement-id apigw-contribution \
     --action lambda:InvokeFunction --principal apigateway.amazonaws.com \
     --source-arn "arn:aws:execute-api:us-east-1:775261844268:$API_ID/*/*/ecommerce/contribution"

   aws apigatewayv2 create-route --profile wecare-prod --region us-east-1 \
     --api-id "$API_ID" --route-key "POST /ecommerce/contribution" \
     --target "integrations/$CONTRIB_INT"
   ```

   > If the verify step is wired as a sibling route rather than an `action` on
   > the same path, repeat the three calls above with
   > `--route-key "POST /ecommerce/contribution/verify"` and a distinct
   > `--statement-id apigw-contribution-verify`.

### IAM

No new policy is required. The contribution path reads and writes the SAME
commerce-keys table (`stack-wecare-digital-WixOrderIds`, which holds the
`BLOGCONTRIB#`, `GATEWAYORDER#`, `REQUESTKEY#` and `CAPTUREQUARANTINE#` rows) and
the SAME payment-attempts table, and reads the SAME `wecare/razorpay/api` secret
by ARN that the `CheckoutWebsiteLeastPrivilege` policy in Section 1 of the
website-checkout runbook already grants. Confirm that policy is attached:

```sh
aws iam get-role-policy --profile wecare-prod --region us-east-1 \
  --role-name wecare-checkout-role --policy-name CheckoutWebsiteLeastPrivilege
```

### Environment variables

No new environment variables. The contribution path reuses
`COMMERCE_KEYS_TABLE` and `PAYMENT_ATTEMPTS_TABLE`, and the SAME gate inputs that
stay empty / unset so the gate is DISABLED:

- `CHECKOUT_INITIATION_ENABLED`: unset (absent). Do not set it.
- `EXPECTED_CONFIGURATION_NAME`: empty string.
- `EXPECTED_PROVIDER_MID`: empty string.

### Verification reads

```sh
aws apigatewayv2 get-routes --profile wecare-prod --region us-east-1 --api-id "$API_ID" \
  --query "Items[?contains(RouteKey, '/ecommerce/contribution')].{RouteKey:RouteKey,Target:Target}"
```

With the gate off, a POST to `/ecommerce/contribution` must return
`PAYMENT_INITIATION_DISABLED` and create no gateway order. Confirm no
`GATEWAYORDER#` row is written for the test contribution id.

### Rollback

Delete the route then its integration:

```sh
aws apigatewayv2 delete-route --profile wecare-prod --region us-east-1 \
  --api-id "$API_ID" --route-id <ROUTE_ID>
aws apigatewayv2 delete-integration --profile wecare-prod --region us-east-1 \
  --api-id "$API_ID" --integration-id <INTEGRATION_ID>
```

### Unblock actions

- **AWS credentials via the sandbox environment** (not chat). Confirm with
  `aws sts get-caller-identity --profile wecare-prod --region us-east-1`
  returning account `775261844268`.
- The website-checkout runbook Section 1 must already be applied (function, role,
  `CheckoutWebsiteLeastPrivilege` policy, `live` alias).
- A thin HTTP handler that routes `/ecommerce/contribution` to
  `blog_contribution.prepare_contribution` (and the verify action to
  `verify_contribution_callback`), reusing `ecommerce/checkout/handler.py`'s
  gate-AND-readiness evaluation and auth posture. The business logic is complete
  and tested; only the request/response wiring is deferred to deploy time, the
  same way the website-checkout `prepare_checkout` / `verify_callback` handlers
  are.

---

## Section 2: the Razorpay webhook already routes BLOG_CONTRIBUTION

No webhook provisioning is needed. The existing `razorpay-webhook` function's
`_handle_payment_captured` already branches on
`notes.purpose == "BLOG_CONTRIBUTION"` to `_handle_blog_contribution_captured`,
which calls `blog_contribution.settle_contribution_capture`. That path:

- re-derives the amount from the STORED contribution record, NEVER from
  `payment.notes` (a forged notes amount is ignored);
- verifies the capture against Razorpay's API (`razorpay_verify.payment_is_captured`);
- makes a conditional one-time settlement claim keyed by the payment id BEFORE
  any state write, so a redelivery settles exactly once;
- quarantines a paid-but-unresolvable capture (no record, amount mismatch, wrong
  currency, not captured) via `record_capture_quarantine` for human
  reconciliation;
- creates NO Wix Store product or order.

Deploy the updated `razorpay-webhook` with the fleet deploy script when the next
deploy runs:

```sh
AWS_PROFILE=wecare-prod AWS_REGION=us-east-1 \
  .venv/bin/python scripts/deploy_all_lambdas.py razorpay-webhook
```

Take the pre-deploy alias checkpoint first (Section 3 of the website-checkout
runbook) so the alias move is reversible with one command.

### Unblock actions

- **AWS credentials via the sandbox environment.** Confirm with
  `aws sts get-caller-identity --profile wecare-prod --region us-east-1`.

---

## Section 3: Authorized cancel-only live monetary test (contribution)

> NEVER agent-executed. BLOCKED-ON-ENVIRONMENT.
>
> This is identical in posture to Section 4 of the website-checkout runbook: a
> live test is performed only by an authorized human operator with explicit owner
> sign-off, only after AWS credentials and provider access exist, and is
> self-reversing (cancel/refund) so nothing settles. The agent never runs it and
> no live result is fabricated.

### Preconditions (all must hold)

- Owner sign-off recorded for a live cancel-only contribution verification.
- `aws sts get-caller-identity` succeeds for `wecare-prod`.
- Razorpay live access available to the operator out of band; secret values are
  never printed and never placed on a command line.
- The initiation gate is turned on ONLY for this deliberate, time-boxed,
  owner-authorized test and returned to DISABLED immediately after.

### Minimal steps for the authorized operator

1. POST the smallest allowed contribution (`CONTRIBUTION_MIN_PAISE`, integer
   paise) to `/ecommerce/contribution` for the test customer, through the
   owner-authorized gate-on window.
2. Drive the verify action with the provider-returned
   `razorpay_payment_id|razorpay_order_id|razorpay_signature`, exactly as the
   browser relays them. The handler re-verifies the HMAC against the server-stored
   gateway order id and STILL requires the authenticated captured-payment
   readback.
3. **Immediately cancel or refund** so no money is captured or retained: cancel
   the order if not yet captured, else issue a full refund at once. Target zero
   settled value.

### Reads to confirm no settled value remains

- Confirm via the authoritative provider readback
  (`lambda_utils/integrations/razorpay_verify`) that no captured, unrefunded
  payment exists for the test contribution.
- Confirm the `BLOGCONTRIB#<id>` record is either still `INITIATED` (cancelled
  before capture) or `CAPTURED` then marked refunded (`refundState`) with net
  zero retained.
- Confirm NO Wix Store product or order was created and NO public order number
  was minted for the contribution.

### Rollback / cleanup

Self-reversing by design. Return the gate to DISABLED and verify with
`scripts/provision_checkout.py --verify`.

### Unblock actions

- **Owner authorization** for the live cancel-only contribution test, recorded
  before any step is run.
- **AWS credentials via the sandbox environment.** Confirm with
  `aws sts get-caller-identity --profile wecare-prod --region us-east-1`.
- Razorpay live access for the operator, handled out of band with no secret value
  printed.
