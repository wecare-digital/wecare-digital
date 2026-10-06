# Customer Cognito authentication over WhatsApp

## Decision

Create a **separate customer Cognito user pool**. Do not modify the existing
WECARE.DIGITAL admin pool `us-east-1_cSx0RHCIR`.

The customer pool uses Cognito `CUSTOM_AUTH` with a six-digit challenge sent
through the existing production WhatsApp Business API Lambda. Cognito owns the
authentication session and token issuance; the challenge Lambda owns OTP
generation, expiry and comparison.

## Supported WABAs and their senders

A customer's OTP is sent from the WABA that customer belongs to. Both WABAs below
are supported; there is no default and no fallback.

| WABA ID | WABA name | WhatsApp sender | Meta phone-number ID | Template | Category | Language |
|---|---|---|---|---|---|---|
| `2094615664435155` | `WECARE.DIGITAL` | `+91 93309 94400` | `1016149501586345` | `wecare_otp` | `AUTHENTICATION` | `en` |
| `2513394156072604` | second WABA | `+91 99033 00044` | `1055232054343117` | `wecare_otp` | `AUTHENTICATION` | `en` |

WABA1's template ID is `1292079089453029`, verified `APPROVED` against the live
Meta-facing backend on 2026-09-23.

**Both WABAs have a template named `wecare_otp`; do not infer the sender from the
template name.** The sender is chosen from the customer's `custom:partner_waba_id`,
never from the template.

**Approval does not cross WABAs.** Meta approves an AUTHENTICATION template per
WABA, so `wecare_otp` being `APPROVED` on `2094615664435155` says nothing about
`2513394156072604`. If it is not approved in that WABA's own template list, Meta
answers `132001` ("template name does not exist in en"), no code is delivered, and
the auth Lambda logs:

```json
{"event": "customer_whatsapp_otp_send_failed", "wabaId": "...", "metaCode": 132001}
```

That is a clean fail-closed, not a crash — but it is still a non-delivery, so
confirm approval in WABA2's template list before pointing a customer at it. This
repo does not check it: a Graph call with a token is out of scope here.

No new Meta template is required.

### The supported set lives in one env var

The set of WABAs that can send an OTP is defined by `OTP_WABA_MAP` on
`wecare-customer-whatsapp-auth`:

```json
{"<waba_id>": {"phone_number_id": "...", "template_name": "...", "template_language": "..."}}
```

It is mirrored in `scripts/provision_customer_whatsapp_auth.py`
(`otp_waba_map()` / `expected_environment()`), recorded in
`config/lambda-env-manifest.json`, and the three are pinned to each other by
`tests/test_customer_whatsapp_auth.py`. `--verify` compares the value on the
**`live` alias version**, not `$LATEST`.

**This table and that map must stay in sync.** A WABA in the doc but not in the map
is a customer who cannot sign in; a WABA in the map but not in the doc is a sender
nobody knows about. `template_name` is per entry precisely so a WABA with a
differently-named approved template needs a configuration change, not a code change.

If `OTP_WABA_MAP` is absent the handler rebuilds a **single-entry** map from the
legacy `META_WABA_ID` / `META_PHONE_NUMBER_ID` pair, so a missed env apply degrades
to WABA1-only rather than taking OTP down entirely — and WABA2 then fails closed.

## Delivery path

```text
customer app
  -> Cognito InitiateAuth(CUSTOM_AUTH)
  -> DefineAuthChallenge
  -> CreateAuthChallenge
  -> wecare-customer-whatsapp-auth:live
  -> wecare-whatsapp-business-api:live
  -> Meta Graph API / wecare_otp
  -> customer WhatsApp
  -> RespondToAuthChallenge(CUSTOM_CHALLENGE)
  -> VerifyAuthChallengeResponse
  -> Cognito tokens
```

The challenge Lambda invokes `wecare-whatsapp-business-api:live` directly.
It does not use `wecare-outbound-whatsapp`, because that path performs normal
CRM/message side effects that authentication traffic does not need.

## Security properties

- Public self-sign-up is disabled. Customer users are created administratively.
- `PreventUserExistenceErrors=ENABLED` on the app client.
- Unknown-user challenge events do not send WhatsApp messages.
- OTPs are six digits, expire after 10 minutes, and allow at most three attempts.
- OTP comparison uses `secrets.compare_digest`.
- OTPs and complete phone numbers are never logged.
- The user's `custom:partner_waba_id` must be **one of the supported WABA ids**
  defined by the OTP WABA map (`OTP_WABA_MAP`, see above) before any OTP is sent.
  This is the cross-WABA isolation gate, and it is a membership test, not a
  default. An unsupported, empty or missing value **fails closed**: no message is
  sent, the challenge raises, and the Lambda logs
  `{"event": "customer_whatsapp_otp_denied", "reason": "unknown_waba"}`. There is
  no fallback to WABA1 — a customer's code never leaves from a number their tenant
  does not belong to.
- The auth Lambda has no Meta token. Its IAM role can invoke only the existing
  WhatsApp sender Lambda and write its own CloudWatch logs.
- Cognito points to the auth Lambda's `live` alias so normal version/alias
  rollback practices continue to apply.

## Provision

Use the repo-supported authenticated deployment environment.

```bash
python scripts/provision_customer_whatsapp_auth.py --dry-run
python scripts/provision_customer_whatsapp_auth.py
python scripts/provision_customer_whatsapp_auth.py --verify
```

The provisioner creates:

- IAM role `wecare-customer-whatsapp-auth-role`
- Lambda `wecare-customer-whatsapp-auth`
- Lambda `live` alias
- 30-day CloudWatch log retention
- Cognito pool `WECARE.DIGITAL-CUSTOMERS`
- public app client `wecare-customer-whatsapp-otp`
- Cognito group `Partner`
- the three Cognito custom-challenge triggers
- a scoped Cognito-to-Lambda invoke permission

The existing admin pool is read back during `--verify` and is expected to
remain without these custom-auth triggers.

## Subsequent Lambda code deployments

Once the function exists, use the fleet's normal deployment path:

```bash
python scripts/deploy_all_lambdas.py --dry-run wecare-customer-whatsapp-auth
python scripts/deploy_all_lambdas.py wecare-customer-whatsapp-auth
```

The deploy script publishes a version and moves `live`; Cognito continues to
invoke the alias rather than `$LATEST`.

## Create a customer user

Do not use the WhatsApp **sender** number as the customer's login identity
unless that is explicitly the customer's own login number.

For each customer login, provision an E.164 phone number, set
`phone_number_verified=true`, set `custom:partner_waba_id` to **one of the
supported WABA ids** — the WABA whose number that customer should receive their
code from — confirm the user, and add it to the `Partner` group. Keep user
provisioning administrative; do not expose `SignUp` for this pool.

| `custom:partner_waba_id` | Code arrives from |
|---|---|
| `2094615664435155` | `+91 93309 94400` |
| `2513394156072604` | `+91 99033 00044` |

Any other value — including a missing attribute — fails closed: the sign-in raises
and **no OTP is sent**. This line previously named `2513394156072604`
unconditionally while the gate above accepted only `2094615664435155`, so following
it produced a user whose every sign-in failed with no code and no explanation.

`2094615664435155` is also what
`amplify/functions/auth/customer-registration/handler.py` and
`amplify/functions/core/secure-files/handler.py` write for self-registered
customers, so **WABA1 must remain in the map** regardless of which WABAs are added
later.

The current branch intentionally does not create a customer user because the
customer's login/recipient phone number was not supplied with the implementation
request.

## Client integration

The existing admin frontend still points to the admin Cognito pool and should
stay that way. A customer login surface must initialize Cognito against the
new customer pool/app-client IDs and perform:

1. `InitiateAuth(AuthFlow=CUSTOM_AUTH)` with the customer's phone-number
   username.
2. Receive `CUSTOM_CHALLENGE`.
3. Ask for the WhatsApp code.
4. `RespondToAuthChallenge(ChallengeName=CUSTOM_CHALLENGE)` with
   `ANSWER=<otp>` and the returned session.
5. Use the resulting Cognito tokens.

Before exposing customer tokens to existing protected APIs, update those API
authorizers/middleware to trust the customer pool as a separate issuer. Do not
replace the admin pool issuer globally.
