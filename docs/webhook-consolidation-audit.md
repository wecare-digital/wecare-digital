# Webhook consolidation — what is actually consolidatable, measured 2026-09-26

Answering "can we have one webhook instead of so many, for WhatsApp and for Plivo".
Every number here was measured against account `775261844268` / API `zllr9lrg7j`, not
read from an earlier document.

## The inventory

19 routes matched a webhook-shaped pattern. Stripping the ones that only *sound*
like callbacks (`/wa-business/webhooks` manages subscriptions, `/waba/events`
configures them, `/ai/fallbacks` is AI config) leaves these genuine provider
ingresses:

| Provider | Routes | Target function | Distinct endpoints |
|---|---|---|---|
| Meta WhatsApp | `POST /whatsapp/inbound` | `wecare-inbound-whatsapp:live` | **2** |
| Meta WhatsApp | `GET`+`POST /whatsapp` | `wecare-whatsapp-calling:live` | (the second) |
| Plivo | `POST /plivo/{answer,hangup,fallback,events,dial-events}` | `wecare-plivo-answer:live` | 5 routes, **1** function |
| Sinch RCS | `GET`+`POST /webhook/sinch-rcs` | `wecare-rcs-dlr:live` | 1 |
| Razorpay | `POST /razorpay-webhook` **and** `POST /payments/webhook` | `wecare-razorpay-webhook:live` | 2 routes, **1** function |
| Browser SDK | `POST /pstn/session/events` | `wecare-pstn-softphone:live` | 1 (internal, not a provider) |

## CORRECTION 2026-09-26: there is ONE Meta ingress, not two

**This section originally concluded there were two live Meta ingresses. That was
wrong, and the reasoning below shows how the evidence misled me.** Corrected after a
live test send to both WABAs proved the actual topology:

    Meta -> POST /whatsapp -> wecare-whatsapp-calling        the only Meta callback
                                    |
                                    | async lambda_client.invoke
                                    v
                              wecare-inbound-whatsapp        messages + statuses

`whatsapp-calling` forwards to `INBOUND_HANDLER_FUNCTION=wecare-inbound-whatsapp`
(handler.py:649). So `inbound-whatsapp`'s invocations are the **internal** async
invoke, not Meta. The route `POST /whatsapp/inbound` exists but Meta never calls it.

**How the original evidence fooled me:** both functions showed heavy traffic, and I
treated "receives traffic" as "is a Meta ingress". Invocation counts cannot tell an
external callback apart from an internal invoke — only the call chain can, and the
test send made it visible in the timestamps: `whatsapp-calling` logged
`webhook_received` at 16:58:09.696, `inbound-whatsapp` started at 16:58:09.821.

Confirmed directly against Meta via `GET /{app-id}/subscriptions`, which the original
audit could not do because no code path existed for it. App `2238810740192680` carries
**two subscriptions and both name one URL**:

| object | fields | callback |
|---|---:|---|
| `whatsapp_business_account` | 32 | `/whatsapp` |
| `catalog` | 2 | `/whatsapp` |

**So the WhatsApp consolidation this document was written to assess is already done.**
There is one callback URL. Nothing to merge. What the original analysis got right is
the dual app-secret detail — that matters for signature verification, not for ingress
count.

Still open: app `1143680903703001` (Business Agent) could not be read, because an app
access token is `{app_id}|{app_secret}` and neither `app_secret` nor
`app_secret_waba2` matches that app. Whether it has its own callback is unknown.

The superseded analysis follows, kept because the method error is instructive.

## SUPERSEDED: "there are two live Meta ingresses"

Not one, and not one dead plus one live. Both receive traffic:

    wecare-inbound-whatsapp    1,981 invocations / 14d
    wecare-whatsapp-calling    2,517 invocations / 14d

The second number needed checking, because `wecare-whatsapp-calling` also owns 11
dashboard routes, so its invocations could have been UI traffic. A Logs Insights
query over 7 days for webhook markers (`hub.challenge`, `x-hub-signature`,
`signature_valid`) returns hits **every single day** — 39 to 440 per day. So it is
genuinely serving Meta webhooks, not just the UI.

Its own docstring confirms the design:

    GET  /whatsapp   -> Webhook verification (hub.challenge)
    POST /whatsapp   -> Webhook events (calls + messages from Meta)

Note "calls **+ messages**" — that overlaps `/whatsapp/inbound` by intent, not just
by accident.

**Why two exist:** Meta allows exactly one callback URL *per app*, and this account
has two apps — primary `2238810740192680` and Business Agent `1143680903703001`.
Two apps, two callbacks, two ingresses. That is consistent with the evidence and
explains it without anything being broken.

**Route precedence is already correct** and worth stating because it looks alarming:
`POST /whatsapp/{proxy+}` also targets `whatsapp-calling` and would appear to
swallow `/whatsapp/inbound`. It does not — API Gateway HTTP APIs prefer the more
specific route, so the exact `POST /whatsapp/inbound` wins. Nothing to fix.

### Can it be one? Yes, with three real constraints

1. **Two app secrets, not one.** `whatsapp-calling` reads `app_secret` *and*
   `app_secret_waba2` from Secrets Manager and verifies `X-Hub-Signature-256`
   against the relevant one. A merged ingress must try both, because a signature
   valid for app A is invalid for app B. Verifying against one secret only would
   silently reject half the traffic — and it would look like Meta had stopped
   sending.
2. **The Meta side is not readable from here.** Per `.kiro/steering`, neither Meta
   MCP has ever authenticated, so the configured callback URL for each app cannot
   be read, only inferred. Any claim about which app points where would be invented.
   This is the part to do manually.
3. **It touches the calling path.** `bw-crm.md` routes WhatsApp Calling as
   Meta -> `sip.wecare.digital:5061` -> Lightsail Asterisk, and the standing rules
   forbid disturbing number/WABA registration. A webhook re-point is not a
   deregistration, but it is the ingress for live calls, so it wants a QA call
   afterwards rather than a config change and a shrug.

### Recommended target, if consolidating

Point **both** apps at one URL:

    https://wecare.digital/api/whatsapp

That endpoint already does `hub.challenge` verification and dual-secret signature
checking, so it is the one with fewer unknowns. `/whatsapp/inbound` would then need
its message/status handling folded in, or `whatsapp-calling` should forward
message-type payloads to it internally.

**Do not consolidate by deleting a route first.** Re-point at Meta, watch both
functions' invocation counts for a full day, and only then retire the unused
ingress — in that order, because a deleted route returns 404 to Meta and Meta
retries then disables a failing callback.

## Plivo: five routes, but already one function — consolidating gains nothing

All five already resolve to `wecare-plivo-answer:live`, so there is no fan-out of
Lambdas to collapse. 245 invocations / 14d.

Plivo's model is separate configuration *fields* — `answer_url`, `hangup_url`,
`fallback_url` — and they may all hold the same URL. So one URL is possible. It is
just not an improvement:

- the handler dispatches on the **path**, so the path is carrying the event class
  cheaply and unambiguously before any parsing;
- collapsing to one URL means re-deriving the event class from the payload, which
  is strictly more code and more ways to be wrong;
- `fallback_url` exists precisely so a failure of the answer URL has somewhere else
  to go. Pointing both at the same URL removes the fallback's entire purpose.

**Recommendation: leave Plivo as five routes.** This is a case where the count looks
like duplication but is actually the provider's event taxonomy. One Lambda, five
labelled doors.

## Razorpay: a genuine duplicate

`POST /razorpay-webhook` and `POST /payments/webhook` both hit
`wecare-razorpay-webhook:live` (10,390 invocations / 14d combined). Two public
signature-verified entrances to the same handler, and only one can be the one
configured at Razorpay.

Not removed here: which one Razorpay actually calls is a dashboard setting on the
provider, and CloudWatch cannot separate them because both routes land on the same
function's metrics. Determine it from the provider dashboard or by splitting the log
line to include the request path, then retire the unused route.

## Sinch RCS: correct as-is

`GET` + `POST /webhook/sinch-rcs` on one function. The `GET` is the verification
handshake and the `POST` is delivery receipts — the same GET/POST pair pattern Meta
uses. 1,212 invocations / 14d. Nothing to consolidate.

## Summary

| Ask | Answer |
|---|---|
| One WhatsApp webhook | **Possible**, and there are currently 2. Needs the Meta-side callback change (not readable from here) plus dual-secret verification. Re-point first, retire after. |
| One Plivo webhook | **Possible but not advisable.** Already one function; the five paths are Plivo's event taxonomy and `fallback_url` must differ to be a fallback. |
| Fewer webhooks overall | **One real duplicate found:** the two Razorpay routes. |
