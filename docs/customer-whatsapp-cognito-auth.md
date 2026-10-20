# Customer Cognito authentication over WhatsApp

## Decision

Create a **separate customer Cognito user pool**. Do not modify the existing
WECARE.DIGITAL admin pool `us-east-1_cSx0RHCIR`.

The customer pool uses Cognito `CUSTOM_AUTH` with a six-digit challenge sent
through the existing production WhatsApp Business API Lambda. Cognito owns the
authentication session and token issuance; the challenge Lambda owns OTP
generation, expiry and comparison.

## Supported transaction sender

Customer OTP is transaction-channel traffic and is pinned to the WECARE.DIGITAL transaction
identity. There is no second-WABA route and no sender fallback.

| WABA ID | WhatsApp sender | Meta phone-number ID | Template | Category | Language |
|---|---|---|---|---|---|
| `2094615664435155` | `+91 93309 94400` | `1016149501586345` | `wecare_otp` | `AUTHENTICATION` | `en` |

The live Meta-facing backend reports `wecare_otp` APPROVED on this WABA. Any customer whose
`custom:partner_waba_id` is missing or differs from `2094615664435155` fails closed and no OTP
is sent.

The deployed `OTP_WABA_MAP`, provisioner, manifest and tests all contain exactly this one route.

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
`phone_number_verified=true`, set `custom:partner_waba_id=2094615664435155`, confirm the user,
and add it to the `Partner` group. Any other WABA value fails closed and no OTP is sent.

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
