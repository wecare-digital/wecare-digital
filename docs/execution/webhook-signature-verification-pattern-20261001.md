# Webhook signature verification — the shared pattern, and two gaps

**2026-10-01. Phase A reference note. No code was changed to produce this file.**

The shared Python verifiers are the one implementation of the question that decides whether a
webhook request is trustworthy. A second implementation of that question is the exact failure mode
`lambda_utils/integrations/razorpay_verify.py` was created to avoid. Two genuine gaps were found
while reviewing them, and they are recorded below as Phase B/C follow-ups rather than fixed here.

## The pattern, and where each element lives

Reviewed: `amplify/functions/shared/lambda_utils/meta_signature.py`,
`.../sinch_signature.py`, and `_verify_signature` in
`amplify/functions/payments/razorpay-webhook/handler.py`.

| Discipline | `meta_signature` | `sinch_signature` | razorpay `_verify_signature` |
|---|---|---|---|
| Key is pinned, never read from the request | yes — candidates from Secrets Manager | yes | yes — Secrets Manager first, env as fallback |
| Digest over the exact delivered bytes, before any parse | yes — `raw_body()` refuses a non-`str` body (`body_not_raw`), and `verify` runs before `json.loads` | yes | yes — verified before `json.loads`; a failed base64 decode leaves the body undecoded, so it fails closed |
| Constant-time comparison | `hmac.compare_digest` | `hmac.compare_digest` | `hmac.compare_digest` |
| Algorithm allowlist | n/a | yes — `unsupported_algorithm` | n/a |
| Opaque failure, no oracle | stable reason tokens; never the secret, signature or body | same | mismatch log records `bodyLen` only |
| Fails closed when no key is configured | `no_app_secret_configured` → `False` | `no_secret_configured` → `False` | logs, returns `False` |
| Replay window | **n/a** — Meta sends no timestamp; bounded by handler dedup | yes — `timestamp_outside_window` | **n/a** — Razorpay sends no timestamp; bounded by `payment_status.dedup_key` idempotency |
| Body size cap | absent | absent | absent |

So the four core disciplines — pinned key not taken from the request, raw-bytes digest,
constant-time compare, opaque failure — are present in all three shared paths. `sinch_signature`
additionally carries a replay window and an algorithm allowlist.

## GAP-SIG-1 — a non-ASCII signature header raises instead of rejecting

**Severity: MEDIUM. Owning phase: B/C. Not fixed in Phase A (runtime code is out of scope).**

`hmac.compare_digest` raises `TypeError` when either `str` argument contains a non-ASCII character.
Neither `meta_signature.verify` nor `sinch_signature.verify` guards the header before comparing, and
neither call site wraps the call:

- `amplify/functions/messaging/inbound-whatsapp-handler/handler.py:682` — `meta_signature.verify(event, _meta_app_secrets())`, bare
- `amplify/functions/messaging/whatsapp-business-api/handler.py:5675` — `meta_signature.verify(event, [primary, secondary])`, bare

Measured, 2026-10-01, against the real module:

```
X-Hub-Signature-256: sha256=café   ->  RAISED TypeError: comparing strings with non-ASCII
                                       characters is not supported
X-Hub-Signature-256: sha256=deadbeef -> (False, 'signature_mismatch')
```

**This is fail-closed in effect** — no forged request is accepted, and nothing is processed. The
defect is the failure *shape*: an attacker-controlled header converts a clean `401 invalid_signature`
into an unhandled exception, which on the public `POST /whatsapp/inbound` route
(`AuthorizationType=NONE`) surfaces as a 5xx with a stack trace in CloudWatch and a Lambda error
metric, and loses the `inbound_http_signature_rejected` log line the route was given deliberately.

The repo has already fixed this exact bug class once and documented why it matters:
`amplify/functions/messaging/plivo-answer/handler.py:398-407` records that `compare_digest` raises on
a non-ASCII `str` and that `?token=café` turning a 403 into a 500 mattered, because a 500 on
`/plivo/answer` is a non-XML body and the caller hears silence. The same reasoning applies here, so
the fix is the same shape: encode both sides, or reject a non-ASCII header with a stable reason token
before comparing.

## GAP-SIG-2 — no body size cap before the HMAC

**Severity: INFORMATIONAL. Owning phase: B/C, optional.**

No Python verifier caps the body before hashing.

Recorded rather than escalated, because the exposure is already bounded by the platform: API Gateway
caps a payload at 10 MB and Lambda at 6 MB for a synchronous invoke, and an HMAC-SHA256 over 6 MB is
a few milliseconds. An explicit cap would make the refusal legible at the verifier rather than
implicit in the platform, which is worth something but is not a security gap.
