# Phase 4e — Google People sync and Truecaller verification

Contracts, state machines and guards built and tested. Both live grants are owner-gated;
the exact unblock actions are at the bottom.

## Measured before building

Both credentials already existed in Secrets Manager and **nothing read either of them**:

| Secret | Fields | Created | Read by |
|---|---|---|---|
| `wecare/seo/google-oauth` | `client_id`, `client_secret` | 2026-04-18 | nothing |
| `wecare/truecaller` | `app_key`, `app_name`, `app_domain`, `callback_url` | 2026-09-19 | nothing |

`scripts/store_provider_secret.py` records the intent for both. For Google it says outright:
*"Reuse this client for People API contact sync rather than minting a second one."* For
Truecaller: *"POST /auth/truecaller/callback - NOT BUILT YET."*

A grep for `people.googleapis`, `truecaller`, `pkce` and `code_verifier` across `amplify/`,
`src/` and `scripts/` found no OAuth flow of any kind. Greenfield, and no redirect URI has
ever been exercised.

## What was built

`amplify/functions/shared/lambda_utils/identity/`

| Module | Responsibility |
|---|---|
| `provenance.py` | which source may overwrite which Contact field |
| `oauth_pkce.py` | PKCE, state, and the token lifecycle |
| `google_people.py` | sync-token lifecycle and `Person` → Contact mapping |
| `truecaller.py` | nonce lifecycle, endpoint allowlist, profile mapping |

All four are pure. HTTP lives in the Lambda so the decisions stay testable without
credentials — which is the point, given the live grants are gated.

## The security boundary: Truecaller's callback names its own profile host

Truecaller POSTs to our callback:

```json
{"requestId": "...", "accessToken": "...",
 "endpoint": "https://profile4-noneu.truecaller.com/v1/default"}
```

The callback is public and unauthenticated — it has to be, because Truecaller calls it. So
`endpoint` is **attacker-controlled input**. Point it at your own host, return
`{"phoneNumbers": ["919999999999"]}`, and we record that number as verified for the current
user. That is a complete authentication bypass wearing the costume of a feature, and the same
primitive is an SSRF into the VPC and the instance metadata service.

`resolve_profile_endpoint` refuses everything except an exact-match host in
`ALLOWED_PROFILE_HOSTS`, and each check closes a specific bypass:

| Refused | Why |
|---|---|
| `http://…truecaller.com/…` | interception even of an allowlisted host |
| `…truecaller.com.evil.example` | a suffix test on `truecaller.com` would accept it |
| `evil.example/profile4-noneu.truecaller.com/…` | a substring test would accept it |
| `https://profile4-noneu.truecaller.com@evil.example/…` | real host is after the `@` |
| `…truecaller.com:8443/…` | allowlisted name pointing at another service |
| `?next=…` / `#…` | places to smuggle a redirect |
| `169.254.169.254`, `localhost`, `10.0.0.1` | the SSRF target that makes this matter |

It **refuses rather than defaulting** to a known host: substituting one would make the check
decorative and hide an attack in progress.

## No bulk lookup, structurally

The brief allows consent-based verification of the current user only. The guarantee is that a
profile fetch is reachable solely with an access token Truecaller minted against a nonce *we*
issued, and `nonce_record` requires a `session_id` — so the flow cannot verify a third
party's number either, only the person holding the handset.

`TestNoBulkLookup` asserts it three ways: no function here accepts a phone number to resolve,
nothing in `amplify/` references a Truecaller search endpoint, and the allowlist contains only
the two profile hosts.

## Field provenance, and why it is per field

A Contact's `phone` can come from an inbound WhatsApp message — where Meta has told us the
number the message genuinely came from — or from a Google contact card, where it is whatever
someone typed into their address book. Those are not the same quality of fact, and a sync that
writes everything it receives lets a stale address-book entry overwrite a number we have proof
of. The row still looks well formed; the next message goes to the wrong person.

```
VERIFIED  4   provider proved it: a wamid's sender, a Truecaller consent
DECLARED  3   the customer typed it in our own Flow
OPERATOR  2   a human on our side
IMPORTED  1   a third-party address book or bulk upload
INFERRED  0   derived by us
```

Per field, not per row, because one contact legitimately mixes sources — phone VERIFIED from
WhatsApp, company IMPORTED from Google, address DECLARED from a Flow. A row-level
`source: google` would either block the import entirely or admit it wholesale.

Two extra protections:

- **`LOCKED_FIELDS` = {`phone`, `bsuid`}.** Once recorded at VERIFIED these never change
  automatically, not even from another VERIFIED source. Two verified numbers mean two people,
  or a number that genuinely changed — both need a human. `needs_review` queues it, and the
  field is **not** applied while it waits.
- **`NEVER_SYNCED`** includes every opt-in and allowlist flag. Those are consent records; an
  address book cannot consent on a customer's behalf, and letting an import set them would
  manufacture permission to message someone. That is the one item here with a regulator
  attached.

## The Google sync-token trap

`people.connections.list` supports incremental sync via `nextSyncToken`. The part that is not
optional: **a sync token expires and Google signals it with HTTP 410 GONE**, and the documented
recovery is to discard it and run a full sync. Code that treats 410 as a generic error retries
forever and the sync silently stops advancing — no contact changes for weeks, and there is no
error to notice.

`interpret_error(410)` → `(EXPIRED_SYNC_TOKEN, must_full_sync=True)`, and
`next_request_params(force_full=True)` refuses to resend a token known to be dead.

Three more, each pinned by a test:

- A sync token is returned on the **last page only**. `sync_token_from` yields nothing while
  `nextPageToken` is present — storing one mid-pagination produces a token that skips the
  remaining pages and never self-corrects.
- `personFields` is baked into the token, so `PERSON_FIELDS` is a module constant, not a
  caller argument. A caller changing it would invalidate every stored token and see 410s that
  look like expiry.
- Deletions arrive as tombstones (`metadata.deleted`). Mapping one as an ordinary person
  writes a contact with every field blank. `to_contact_fields` raises on a tombstone.

403 is split deliberately: Google uses it for both quota and missing scope, which need
opposite responses. An unlabelled 403 is assumed to be quota, because backing off on a scope
problem only delays a clear failure, whereas treating quota as a scope problem tears down a
working authorisation.

## The four OAuth failures that are silent

| Failure | Guard |
|---|---|
| `expires_in` stored as if absolute — 3599 always beats "now", so the token reads as fresh forever | `token_record` converts to absolute `expiresAt` at exchange |
| A re-auth returns no `refresh_token` and a wholesale store wipes the only copy, killing the integration hours later | `merge_token_record` never overwrites a stored refresh token with an absent one |
| Refreshing exactly at expiry fails mid-request under clock skew | `needs_refresh` applies a 120s skew |
| The user quietly declines a scope; the token is valid, the API 403s, the sync "finds nothing" | `missing_scopes` compares granted against required at exchange |

`access_type=offline` **and** `prompt=consent` are both sent; omitting either is why
long-lived Google integrations mysteriously stop working. PKCE is S256-only — `plain` sends
the verifier as the challenge, and `CHALLENGE_METHOD` is not a parameter so no call site can
weaken it. Scope is `contacts.readonly`: sync reads an address book and must never edit a
customer's own Google contacts.

## Tests

`tests/test_identity.py`, **97 assertions**. Suite 2082 → 2179. typecheck clean, provider
policy 8/8, webhook gate 17/17.

## WAITING_FOR_OWNER

Neither provider can be exercised end to end from here. Nothing is deployed for this phase,
so there is nothing to roll back.

**1. Google — two console actions on the existing OAuth client** (`wecare/seo/google-oauth`;
do not mint a second client):

- Add the authorised redirect URI `https://wecare.digital/api/auth/google/callback`
- Add the scope `https://www.googleapis.com/auth/contacts.readonly` to the consent screen

`contacts.readonly` is a sensitive scope. Internal use within the Workspace org needs no
Google verification; exposing it to external users does.

**2. Truecaller — one portal action** on developer.truecaller.com:

- Register the callback URL that matches `callback_url` in `wecare/truecaller`, pointing at
  `https://wecare.digital/api/auth/truecaller/callback`

The deep link only resolves on a device with the Truecaller app installed, so handset QA
needs a real Android device. The owner-nominated QA recipient `+918100640044` is available
for it (`.kiro/steering/02-qa-recipient.md`).

**Not built, and deliberately:** the two Lambdas and their API routes. Building an
unauthenticated public callback before its provider registration exists would put a live
endpoint on the internet with no traffic to validate it, and `Phase 4f` is where the
authorised API surface is designed. The route, its auth posture and the manual-review UI
belong there.
