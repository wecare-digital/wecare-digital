"""Shared registry of outbound data integrations. READ only, by construction.

What this is for
----------------
Seven providers are named in the brief — Google Ads, GA4, Search Console, Business
Profile, Play Reporting, Bing Webmaster and Meta Ads/CTWA — and before this module
there was no record of which of them we can actually read, under whose account,
with which scopes, or how stale the answer is. Measured 2026-09-23:

    provider            adapter files    credential
    Google Ads              0            wecare/google/ads
    Search Console          0            wecare/seo/google-oauth
    Play Reporting          0            NONE
    GA4                     6            wecare/seo/google-oauth
    Business Profile        4            wecare/seo/google-oauth
    Bing Webmaster         14            wecare/bing/api
    Meta Ads / CTWA        26            wecare/meta-system-user-token

Three of the seven have no adapter, and one of those has no credential either. A
registry that listed all seven as available would be the same class of lie as the
Bedrock agent config that claimed a working agent for five months.

Three decisions this module exists to enforce
---------------------------------------------
**Access is three-state, never a boolean.** A credential existing is not a scope
being granted. That has already cost this project once: the Google OAuth client
exists and works, and `contacts.readonly` was never added to the consent screen, so
the identity import is blocked on a provider setting rather than on code.
`CREDENTIAL_ABSENT` / `SCOPE_UNVERIFIED` / `VERIFIED` keeps the difference visible,
and `VERIFIED` means a real authorised read succeeded and was recorded — nothing
here claims it, because nothing has.

**A read carries its provider request id, or records that it has none.** Without one
there is no support conversation to be had with Google or Meta; "it returned the
wrong number yesterday" is unactionable. Absent is recordable. Fabricated is not.

**Freshness is explicit and comparable.** A cached metric rendered without its age is
how a dashboard shows last week's numbers as today's. Every result carries
`fetched_at` and the provider's own `max_age_seconds`, and staleness is derived.

Read-only by construction. There is no write verb in this module — not a flag, not a
guard, nothing to switch on. It also makes no provider call and never reads a secret
value: existence is established with `DescribeSecret`, because pulling a credential
into the layer that renders a dashboard is how one ends up in a log.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from lambda_utils.masking import mask_secrets

# Access states. Ordered weakest to strongest.
ACCESS_CREDENTIAL_ABSENT = "CREDENTIAL_ABSENT"
ACCESS_SCOPE_UNVERIFIED = "SCOPE_UNVERIFIED"
ACCESS_VERIFIED = "VERIFIED"

ACCESS_STATES: Tuple[str, ...] = (
    ACCESS_CREDENTIAL_ABSENT, ACCESS_SCOPE_UNVERIFIED, ACCESS_VERIFIED)


@dataclass(frozen=True)
class Provider:
    key: str
    display_name: str
    #: Whose account the data belongs to. A registry without this cannot answer
    #: "who do we ask" when a read starts failing.
    owner: str
    #: Secrets Manager name, or "" when no credential exists. Never a value.
    secret_name: str
    access: str
    #: Scopes that grant reads ONLY. A write-capable scope must not be listed here;
    #: it goes in `write_capable_scopes` so the uncomfortable cases are explicit
    #: rather than hidden behind a name that happens to read as read-only.
    read_scopes: Tuple[str, ...]
    #: How long a cached answer stays meaningful, per the provider's own reporting
    #: latency. GA4 and Ads settle over hours; a search console lags a day or more.
    max_age_seconds: int
    #: Whether an adapter actually exists in this repo.
    adapter_built: bool
    #: The exact next action that would move `access` forward. "Blocked" without
    #: this is a status, not information.
    unblock: str
    #: Scopes the provider only offers in a write-capable form. Two of the seven are
    #: in this position and there is no read-only alternative to choose, so the
    #: registry cannot make them safe - it can only make them visible. The mitigation
    #: is a reviewed constraint on the adapter, recorded in `write_scope_mitigation`.
    write_capable_scopes: Tuple[str, ...] = ()
    write_scope_mitigation: str = ""
    notes: str = ""

    @property
    def all_scopes(self) -> Tuple[str, ...]:
        return tuple(self.read_scopes) + tuple(self.write_capable_scopes)


def _p(**kwargs: Any) -> Provider:
    return Provider(**kwargs)


REGISTRY: Dict[str, Provider] = {
    "google_ads": _p(
        key="google_ads", display_name="Google Ads",
        owner="WECARE.DIGITAL Google Ads account (owner-held)",
        secret_name="wecare/google/ads",
        access=ACCESS_SCOPE_UNVERIFIED,
        # Google Ads has a single coarse scope and it is read/write. It is listed
        # because there is no read-only alternative, and that is precisely why no
        # adapter may be built against it until the boundary below exists.
        read_scopes=(),
        max_age_seconds=6 * 3600,
        adapter_built=False,
        unblock=("No adapter exists. Google Ads offers only one coarse scope, which "
                 "grants writes as well as reads, so an adapter must be confined to "
                 "report endpoints and reviewed before it is built. Developer tokens "
                 "were SUNSET 2026-09-09 and are ignored by the API servers, so a "
                 "missing developer_token is NOT a blocker. Measured 2026-09-30 by "
                 "scripts/google_products_pull.py: OAuth alone reaches v22-v25 and "
                 "listAccessibleCustomers returns HTTP 200 with 2 customers "
                 "(8367589699 and manager 4270412231), so the ACCOUNT grant is already "
                 "done. The remaining blocker is the Cloud project's API access level: "
                 "a customer query returns CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION, "
                 "meaning project wecaredigitalbw (756034744787), which owns the "
                 "automation@ service account, is on Test access. Apply for EXPLORER on "
                 "the Google Ads API page in Cloud Console for that project, re-run the "
                 "probe, then build the report-only adapter."),
        notes=("Scope list deliberately empty: the only Google Ads scope is "
               "read/write, and declaring it here would put a write capability in a "
               "read-only registry."),
    ),
    "ga4": _p(
        key="ga4", display_name="Google Analytics 4",
        owner="WECARE.DIGITAL GA4 property (owner-held)",
        secret_name="wecare/seo/google-oauth",
        access=ACCESS_SCOPE_UNVERIFIED,
        read_scopes=("https://www.googleapis.com/auth/analytics.readonly",),
        max_age_seconds=4 * 3600,
        adapter_built=True,
        unblock=("Add analytics.readonly to the consent screen of the EXISTING "
                 "OAuth client and record the GA4 property id. Do not create a "
                 "second client - the current one already carries a working grant."),
        notes="6 files reference GA4; none has demonstrated an authorised read.",
    ),
    "search_console": _p(
        key="search_console", display_name="Google Search Console",
        owner="WECARE.DIGITAL Search Console property (owner-held)",
        secret_name="wecare/seo/google-oauth",
        access=ACCESS_SCOPE_UNVERIFIED,
        read_scopes=("https://www.googleapis.com/auth/webmasters.readonly",),
        # Search Console data lags by 2-3 days; a 24h cache is not the stale part.
        max_age_seconds=24 * 3600,
        adapter_built=False,
        unblock=("No adapter exists. Add webmasters.readonly to the existing OAuth "
                 "client's consent screen and confirm the property is verified, "
                 "then build the adapter."),
        notes=("Search Console reports lag 2-3 days at source. Freshness here is "
               "cache age, NOT data recency - a caller must not read a fresh cache "
               "as fresh data."),
    ),
    "business_profile": _p(
        key="business_profile", display_name="Google Business Profile",
        owner="WECARE.DIGITAL business listing (owner-held)",
        secret_name="wecare/seo/google-oauth",
        access=ACCESS_SCOPE_UNVERIFIED,
        read_scopes=(),
        write_capable_scopes=("https://www.googleapis.com/auth/business.manage",),
        write_scope_mitigation=(
            "Google offers no read-only scope for this API, so the grant cannot be "
            "narrowed. Confine the adapter to GET endpoints (locations, reviews, "
            "insights) and never construct a mutating request. The registry cannot "
            "enforce that; it has to hold at code review, which is why the scope is "
            "declared write-capable here instead of sitting in read_scopes."),
        max_age_seconds=12 * 3600,
        adapter_built=True,
        unblock=("Request business.manage on the existing OAuth client. Note it is "
                 "write-capable and cannot be narrowed - see "
                 "write_scope_mitigation before building against it."),
        notes="4 files reference Business Profile; none has demonstrated a read.",
    ),
    "play_reporting": _p(
        key="play_reporting", display_name="Google Play Reporting",
        owner="WECARE.DIGITAL Play Console (owner-held)",
        secret_name="",
        access=ACCESS_CREDENTIAL_ABSENT,
        read_scopes=(),
        write_capable_scopes=("https://www.googleapis.com/auth/androidpublisher",),
        write_scope_mitigation=(
            "androidpublisher is a single coarse scope that also permits uploading "
            "releases and changing store listings. Grant it to a service account "
            "whose Play Console ROLE is restricted to reporting, so the restriction "
            "lives in the Play Console rather than in the token - that is the only "
            "place it can be enforced."),
        max_age_seconds=24 * 3600,
        adapter_built=False,
        unblock=("No credential and no adapter. Create a Play Console service "
                 "account, grant it read-only reporting on the app, store it as a "
                 "new secret, then build the adapter. Native packaging is "
                 "POST-PROJECT, so this is not a closure blocker."),
        notes=("The only provider with NO credential at all. That is a different "
               "blocker from a missing scope and sends you to a different console."),
    ),
    "bing_webmaster": _p(
        key="bing_webmaster", display_name="Bing Webmaster Tools",
        owner="WECARE.DIGITAL Bing Webmaster site (owner-held)",
        secret_name="wecare/bing/api",
        access=ACCESS_SCOPE_UNVERIFIED,
        # An API-key product: no OAuth scopes exist to declare.
        read_scopes=(),
        max_age_seconds=24 * 3600,
        adapter_built=True,
        unblock=("Confirm the site is verified in Bing Webmaster Tools and that the "
                 "stored API key belongs to that account, then record a successful "
                 "read to move this to VERIFIED."),
        notes="API-key product, so there are no scopes to enumerate.",
    ),
    "meta_ads": _p(
        key="meta_ads", display_name="Meta Ads and click-to-WhatsApp",
        owner="WECARE.DIGITAL business portfolio (owner-held)",
        secret_name="wecare/meta-system-user-token",
        access=ACCESS_SCOPE_UNVERIFIED,
        read_scopes=("ads_read", "read_insights"),
        max_age_seconds=3 * 3600,
        adapter_built=True,
        unblock=("Confirm the system user token carries ads_read and read_insights "
                 "and that the ad account is in the portfolio. Do NOT re-issue the "
                 "token: the same secret serves WhatsApp messaging, and rotating it "
                 "to add a scope would interrupt live messaging."),
        notes=("Shares its credential with the WhatsApp messaging path, which is "
               "why scope changes here are not free."),
    ),
}


def resolve(key: str) -> Provider:
    """The registry entry, or `KeyError`. Never a default.

    A defaulted provider would silently attribute one account's data to another.
    """
    if key not in REGISTRY:
        raise KeyError(f"unknown integration: {key!r}")
    return REGISTRY[key]


def waiting_for_owner() -> Dict[str, str]:
    """Every provider not yet `VERIFIED`, with the exact action that would unblock it.

    Shaped for the phase report: the whole point is that "blocked" is useless without
    the next step, and the next step for six of these is in a provider console rather
    than in this repository.
    """
    return {p.key: p.unblock for p in REGISTRY.values()
            if p.access != ACCESS_VERIFIED}


def describe_registry() -> Dict[str, Any]:
    """The registry as data, for a status surface. Carries no credential material."""
    return {
        p.key: {
            "displayName": p.display_name,
            "owner": p.owner,
            # The NAME of a secret is safe and useful; the value never appears.
            "secretName": p.secret_name or None,
            "credentialPresent": bool(p.secret_name),
            "access": p.access,
            "readScopes": list(p.read_scopes),
            "writeCapableScopes": list(p.write_capable_scopes),
            "writeScopeMitigation": p.write_scope_mitigation or None,
            "maxAgeSeconds": p.max_age_seconds,
            "adapterBuilt": p.adapter_built,
            "unblock": p.unblock,
            "notes": p.notes,
        }
        for p in REGISTRY.values()
    }


@dataclass(frozen=True)
class ReadResult:
    """One provider read, with everything needed to argue about it later."""

    provider: str
    #: The provider's own request/trace id. "" means the provider returned none.
    request_id: str
    fetched_at: int
    payload: Dict[str, Any] = field(default_factory=dict)
    #: Quota as used/limit rather than a percentage: "can I make 400 more calls
    #: today" is the only question a caller actually has, and a percentage cannot
    #: answer it. `None` means the provider does not report quota, which is the
    #: opposite situation from `remaining == 0`.
    quota_used: Optional[int] = None
    quota_limit: Optional[int] = None

    def age_seconds(self, now: int) -> int:
        return max(0, int(now) - int(self.fetched_at))

    def is_stale(self, now: int) -> bool:
        """Derived from the PROVIDER's max age, not from a caller's opinion."""
        return self.age_seconds(now) > resolve(self.provider).max_age_seconds

    def describe(self, now: Optional[int] = None) -> Dict[str, Any]:
        if now is None:
            import time
            now = int(time.time())

        quota_known = self.quota_used is not None and self.quota_limit is not None
        remaining = (max(0, int(self.quota_limit) - int(self.quota_used))
                     if quota_known else None)

        return {
            "provider": self.provider,
            # None rather than "" so a consumer cannot render an empty id as one.
            "requestId": self.request_id or None,
            "requestIdAvailable": bool(self.request_id),
            "fetchedAt": int(self.fetched_at),
            "ageSeconds": self.age_seconds(now),
            "maxAgeSeconds": resolve(self.provider).max_age_seconds,
            "stale": self.is_stale(now),
            "quotaKnown": quota_known,
            "quotaUsed": self.quota_used,
            "quotaLimit": self.quota_limit,
            "quotaRemaining": remaining,
            # Masked: a provider payload can carry a refreshed token, and this
            # description is logged and rendered.
            "payload": mask_secrets(self.payload),
        }
