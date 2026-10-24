"""Contact identity: Google People sync, Truecaller verification, field provenance.

Measured before building, 2026-09-23
------------------------------------
Google OAuth credentials exist for future People API use. Truecaller remains intentionally
unprovisioned: there is no live callback route or runtime consumer, and the previously stored
`wecare/truecaller` credential is being retired. `scripts/store_provider_secret.py` remains
only as a future provisioning recipe if owner entitlement and callback registration are later
completed.

A grep for `people.googleapis`, `truecaller`, `pkce` and `code_verifier` across
`amplify/`, `src/` and `scripts/` finds no OAuth flow of any kind. So this is greenfield,
and no redirect URI has ever been exercised.

Shape
-----
    customer_uuid.py   the ONE public-facing customer id: uuid4, printable, loggable in full
    customer.py        CUS_<ULID> identity, phone/email normalisation, checkout readiness
    registration.py    the walk-up front door: throttle, OTP, then admin-provision a login
    provenance.py      which source may overwrite which Contact field
    oauth_pkce.py      PKCE, state, and the token lifecycle
    google_people.py   sync-token lifecycle and person -> Contact mapping
    truecaller.py      nonce issue/claim and the signed-assertion contract

`registration.py` exists because the customer pool is `AllowAdminCreateUserOnly = true` and that
is deliberate: a browser must never mint pool users. It proves the phone by OTP first and then
provisions the Cognito user from the backend. It is also the only layer that can see a client IP -
a Cognito trigger event carries none - so per-IP throttling lives there or nowhere.

`customer.py` is the newest and is a different axis from the rest: the others enrich a
`Contact` from a third party, while it defines the identity a checkout customer is keyed on.
Contact remains the CRM record; a customer is the person who can hold a verified phone, a
verified email and an order history. The two are related but not the same, and conflating them
is what made phone-as-identity look reasonable - a ported number then silently moves an order
history to whoever received it next.

Every module here is pure or store-backed; none performs network I/O. The HTTP calls
belong in the Lambda so that the decisions stay testable without credentials, which
matters because the live consent steps are owner-gated (see below).

The two security properties that drive the design
-------------------------------------------------
**1. Truecaller's callback tells us where to fetch the profile.** The body is

    {"requestId": "...", "accessToken": "...",
     "endpoint": "https://profile4-noneu.truecaller.com/v1/default"}

and that endpoint is attacker-controlled input. A forged callback could point it at any
host, which would then return any phone number, and we would record it as *verified*. That
is a complete authentication bypass dressed as a feature, and it is also an SSRF into
whatever the Lambda can reach. `truecaller.resolve_profile_endpoint` allowlists the host.

**2. Nothing may ask Truecaller who owns an arbitrary number.** The brief requires
consent-based verification of the *current user* only, with no bulk lookup. The structural
guarantee is that a profile fetch is reachable only with an access token Truecaller minted
for a nonce **we** issued, and the nonce is bound to the session that asked for it - so it
cannot verify a third party's number either.

What is owner-gated
-------------------
Neither provider can be exercised end to end from here:

* Google: the OAuth client needs `https://wecare.digital/api/auth/google/callback`
  registered as an authorised redirect URI, and `contacts.readonly` added to the consent
  screen. Both are Google Cloud console actions.
* Truecaller: no live credential or callback route exists. A future rollout must first
  register the callback on developer.truecaller.com, provision a fresh credential, and then
  enable the route; the deep link only resolves on a device with the Truecaller app installed.

So the contracts, state machines and guards remain as dormant scaffolding. The live feature is
`WAITING_FOR_OWNER`; no production route or stored credential should be inferred from this package.
"""

# Re-exported here and ONLY this one, deliberately. Every other module in this package pulls in
# a provider contract, a store or `lambda_utils.http`, so importing them from the package root
# would make `from lambda_utils.identity import customer_uuid` pay for all of it on a Lambda cold
# start. `customer_uuid` imports nothing but `uuid`, so it is free and is read on the payment
# path by handlers that want the attribute name without the rest of identity.
from lambda_utils.identity import customer_uuid  # noqa: F401

__all__ = ["customer_uuid"]
