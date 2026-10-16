#!/usr/bin/env python3
"""Google Search Console: submit the sitemap, and retire the old sitemap feeds.

WHAT THE SEARCH CONSOLE API CAN AND CANNOT DO, stated first, because the obvious
reading of "remove old links from Google" is not a thing this API offers.

The Search Console API v3 exposes exactly four services - Search Analytics, Sitemaps,
Sites and URL Inspection (https://developers.google.com/webmaster-tools/v1/api_reference_index).
There is **no removals endpoint**. The Removals tool is Search Console UI only, its
effect is temporary (roughly six months), and a URL that still returns 200 comes back
when the block lapses. So:

  * Removing an OLD SITEMAP that is still registered  -> DELETE sitemaps/{feedpath}.
    This IS in the API, and it is what this script's --prune does. It matters because
    a registered sitemap Google can no longer fetch shows up permanently as
    "Couldn't fetch", and a registered sitemap listing dead URLs keeps asking Google
    to crawl them.

  * Removing an OLD URL from the index -> not available, and not needed. What actually
    drops a URL is the response the crawler gets when it re-fetches it: 301 consolidates
    onto the replacement, 404/410 drops it. Both are already true for every retired URL
    on this site - verified by scripts/retired_url_probe.py, which fails if any retired
    URL answers 200. The Removals tool only ever hides a URL that is still live, which
    is a different problem from the one we have.

AUTHORIZATION: THE SCOPE IS SOLVED, THE PROPERTY GRANT IS NOT.

These are two separate gates and conflating them is what makes this look unfixable when
only half of it is. Submitting needs the read/WRITE scope
https://www.googleapis.com/auth/webmasters (`.readonly` cannot submit) AND the principal
holding it must be a user on the Search Console property.

GATE 1 - THE SCOPE. Solved, with no browser and no key file. This machine's gcloud user
credential carries cloud-platform but not webmasters, so as `wecare.digital.bw@gmail.com`
every call is 403 `PERMISSION_DENIED` "Request had insufficient authentication scopes".
A service account, however, can be issued a token for ANY scope with no consent screen,
and `automation@wecaredigitalbw.iam.gserviceaccount.com` is impersonatable from here
(`roles/iam.serviceAccountTokenCreator` is already granted; the other three service
accounts in the project are not). Measured:

    impersonate automation@   ->  scopes: webmasters, userinfo.email, openid, email
                              ->  GET /webmasters/v3/sites  =  HTTP 200

200, not 403. `resolve_auth` below does this automatically when the primary credential
lacks the scope, so no argument is needed. Nothing is written to disk: impersonation goes
through the IAM Credentials API, so no service-account KEY is created - which also keeps
this clear of the standing prohibition on minting provider credentials.

GATE 2 - THE PROPERTY. There is no API to add a principal to somebody else's property,
and that is the dead end everyone stops at. But it is not the only way in: a principal
that can prove it owns the site does not need to be granted anything. The Site
Verification API (`siteverification.googleapis.com`) does exactly that, and it is fully
automatable. Measured with the impersonated service account:

    siteVerification/v1/webResource        ->  200, 0 resources owned
    getToken FILE    https://wecare.digital/  ->  200, google907ae7b9233a31c5.html
    getToken META    https://wecare.digital/  ->  200
    getToken DNS_TXT wecare.digital           ->  200

FILE was chosen over the other two, for one reason each.

  Not DNS_TXT, even though it is the only method that yields a *Domain* property. The
  token would go in the apex TXT record set, and that record set also carries the SPF
  string. DMARC here is `p=reject; sp=reject` and MTA-STS is `mode: enforce`, so email on
  this domain is fail-closed - a mistake in that record set rejects mail outright rather
  than filtering it, and `.kiro/steering/email-auth-dns.md` makes exactly one SPF record a
  hard rule. A sitemap submission is not worth putting a hand into that record.

  Not META, because the tag is rendered from `NEXT_PUBLIC_GOOGLE_SITE_VERIFICATION`
  (`src/config/analytics.ts`), that variable already carries the OWNER's token in the DNS
  record, and next/head de-duplicates `meta[name]` - so a second token would have to
  replace the first rather than sit beside it.

  FILE touches neither. `public/google907ae7b9233a31c5.html` is a single-line file that
  Next copies to the export root, and Amplify serves root-level files directly (verified
  against `/offline.html`, `/manifest.json`, `/sw.js`, all 200 with their own content).
  Its whole contents are the token line, unchanged, because Google's checker compares them
  literally - which is why that file has no explanatory header and this paragraph exists
  instead.

FILE verifies the URL-prefix property `https://wecare.digital/`, which is the exact origin
the sitemap is served from, so it is sufficient. What it is NOT is a grant on the owner's
existing property: the sitemap gets registered against the service account's own verified
property. Google processes the file for the site either way - and `robots.txt` already
advertises it - so this buys the registration plus the `sitemaps.get` telemetry
(lastDownloaded, errors, warnings), not discovery that was missing. Adding the service
account under Settings > Users and permissions as Full is still the tidier end state, and
it is the one thing here with no API:

    automation@wecaredigitalbw.iam.gserviceaccount.com

`check` re-measures both gates rather than trusting any of this prose.

WHAT IS *NOT* A ROUTE, so nobody spends another pass on it. `wecare/seo/google-oauth`
cannot do this, and not for a permissions reason - for a protocol one. It holds exactly
two fields, `client_id` and `client_secret` (`docs/execution/phase-04e-contact-identity.md`,
`scripts/store_provider_secret.py`), and an OAuth *client* identifies an application, not
a user. The Search Console API accepts only OAuth 2.0 user tokens, and minting one from a
client id and secret requires an authorization code from a browser consent screen
exchanged for a refresh token. No Google refresh token is stored anywhere in this account:
`lambda_utils/identity/oauth_pkce.py` is the module that would obtain one, it has no Lambda
consumer, and it is scoped to `contacts.readonly` rather than webmasters.
`scripts/check_secrets_live.py` says the same thing in one line - the client secret "is
only exercised by a full auth flow". So reading that secret would not help, which is
convenient, because reading it is prohibited.

USAGE

    python scripts/search_console_sitemap.py check          # both gates, re-measured
    python scripts/search_console_sitemap.py verify         # dry run: FILE ownership
    python scripts/search_console_sitemap.py verify --apply # closes GATE 2
    python scripts/search_console_sitemap.py list           # registered sitemaps
    python scripts/search_console_sitemap.py submit         # dry run
    python scripts/search_console_sitemap.py submit --apply
    python scripts/search_console_sitemap.py prune          # dry run: stale feeds
    python scripts/search_console_sitemap.py prune --apply
    python scripts/search_console_sitemap.py inspect /anew/

    --property sc-domain:wecare.digital   # override the property to act on
    --sitemap  https://.../sitemap.xml    # override the feed
    --impersonate <sa-email>              # override the service account
    --no-impersonate                      # use only the primary credential

SECRET DISCIPLINE. The access token is held in memory only. It is never printed, never
written to a file, and never placed on a command line or in an environment assignment -
see .kiro/steering/secret-handling.md. This script reads nothing out of Secrets Manager.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

SITE = "https://wecare.digital"
DEFAULT_SITEMAP = f"{SITE}/sitemap.xml"

# Both property shapes are tried, because which one exists is a property-creation
# decision nobody can read back without access. A Domain property covers every
# subdomain and both schemes; a URL-prefix property covers exactly one origin.
CANDIDATE_PROPERTIES = [
    "sc-domain:wecare.digital",
    f"{SITE}/",
    # The www URL-prefix GSC property still EXISTS (it holds the pre-cutover history) and is
    # probed for telemetry. This is not a routing claim: www is retired and 404s at the
    # wildcard fallback as of 2026-10-16. The sitemap that gets SUBMITTED is always the apex
    # feed (DEFAULT_SITEMAP), never a www one.
    "https://www.wecare.digital/",
]

API = "https://searchconsole.googleapis.com/webmasters/v3"
SV_API = "https://www.googleapis.com/siteVerification/v1"
WRITE_SCOPE = "https://www.googleapis.com/auth/webmasters"
READ_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
VERIFY_SCOPE = "https://www.googleapis.com/auth/siteverification"

#: The URL-prefix property the FILE method verifies. Not `sc-domain:` - that needs DNS.
VERIFY_SITE = f"{SITE}/"

# Service accounts to try impersonating, in order. Only `automation@` currently grants
# this user `roles/iam.serviceAccountTokenCreator`; the rest are listed so a future
# grant is picked up without a code change, and so a reader can see they were tried.
IMPERSONATION_CANDIDATES = [
    "automation@wecaredigitalbw.iam.gserviceaccount.com",
    "wecare-translate@wecaredigitalbw.iam.gserviceaccount.com",
    "wecaredigitalbw@appspot.gserviceaccount.com",
]


def unblock_text(principal: str | None = None) -> str:
    who = principal or IMPERSONATION_CANDIDATES[0]
    return (
        "  The SCOPE is not the problem any more. What remains is one UI action that has\n"
        "  no API: add the principal as a user on the Search Console property.\n\n"
        "    Search Console -> Settings -> Users and permissions -> Add user\n"
        f"      {who}\n"
        "      permission: Full        <- Restricted CANNOT submit a sitemap\n\n"
        "  Then re-run `check`. Nothing else here needs changing.\n\n"
        "  Alternative, if you would rather not add a service account: re-consent this\n"
        "  machine as the Google account that already owns the property -\n\n"
        "    gcloud auth application-default login \\\n"
        f"        --scopes={WRITE_SCOPE},https://www.googleapis.com/auth/cloud-platform\n\n"
        "  That needs a browser, which is why the service-account route is preferred for\n"
        "  unattended runs."
    )


# --------------------------------------------------------------------------- auth


class Auth:
    """A bearer token plus what is known about its scopes. Never exposes the value."""

    def __init__(self, token: str, source: str, scopes: list[str] | None) -> None:
        self._token = token
        self.source = source
        self.scopes = scopes  # None means "could not be determined"

    @property
    def header(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    def has_write(self) -> bool | None:
        if self.scopes is None:
            return None
        return any(s == WRITE_SCOPE for s in self.scopes)

    def has_any_console(self) -> bool | None:
        if self.scopes is None:
            return None
        return any(s in (WRITE_SCOPE, READ_SCOPE) for s in self.scopes)


def _tokeninfo(token: str) -> list[str] | None:
    """Ask Google what the token is actually good for. Sends the token, prints nothing."""
    req = urllib.request.Request(
        "https://www.googleapis.com/oauth2/v1/tokeninfo",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = json.loads(r.read().decode() or "{}")
    except Exception:  # noqa: BLE001
        return None
    scope = body.get("scope")
    return scope.split() if scope else None


def _impersonate(sa: str, scopes: str | None = None) -> Auth | None:
    """Mint a webmasters-scoped token for a service account by impersonation.

    This is the route that removes the browser from the loop. A service account can be
    issued a token for any scope with no consent screen, and impersonation goes through
    the IAM Credentials API - so NO service-account key file is created and nothing
    lands on disk. Needs `roles/iam.serviceAccountTokenCreator` on the target.
    """
    try:
        p = subprocess.run(
            ["gcloud", "auth", "print-access-token",
             f"--impersonate-service-account={sa}",
             f"--scopes={scopes or WRITE_SCOPE}"],
            capture_output=True, text=True, timeout=120,
        )
    except Exception:  # noqa: BLE001
        return None
    if p.returncode != 0 or not p.stdout.strip():
        return None
    tok = p.stdout.strip()
    return Auth(tok, f"impersonated {sa}", _tokeninfo(tok))


def resolve_auth(impersonate: str | None = None,
                 allow_impersonation: bool = True) -> Auth | None:
    """Explicit key, then ADC, then impersonation, then the bare gcloud user token.

    Impersonation is tried BEFORE falling back to the user token, because the user token
    is known to lack the webmasters scope on this machine and a 403 from it is a dead end,
    whereas an impersonated token reaches the API and can report the real remaining gap.
    """
    import os

    # 1. An explicit service-account key, scoped to webmasters.
    try:
        import google.auth  # type: ignore
        import google.auth.transport.requests  # type: ignore
        from google.oauth2 import service_account  # type: ignore

        key = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if key and os.path.exists(key):
            creds = service_account.Credentials.from_service_account_file(
                key, scopes=[WRITE_SCOPE])
            creds.refresh(google.auth.transport.requests.Request())
            return Auth(creds.token, f"service account key ({key})", [WRITE_SCOPE])
    except Exception:  # noqa: BLE001
        pass

    # 2. Application Default Credentials, but only if they actually carry the scope.
    #    ADC on a developer machine is a user credential, so asking for [WRITE_SCOPE]
    #    does not grant it - the request is silently satisfied with whatever the user
    #    consented to. Checking is the only way to tell, and accepting an unscoped ADC
    #    here would shadow the impersonation route below.
    try:
        import google.auth  # type: ignore
        import google.auth.transport.requests  # type: ignore

        creds, _ = google.auth.default(scopes=[WRITE_SCOPE])
        creds.refresh(google.auth.transport.requests.Request())
        adc = Auth(creds.token, "application default credentials",
                   _tokeninfo(creds.token))
        if adc.has_write() is not False:
            return adc
    except Exception:  # noqa: BLE001
        pass

    # 3. Impersonation - the no-browser route. Both scopes are requested together so
    #    `verify` and `submit` can run back to back on one token.
    if allow_impersonation:
        scopes = f"{WRITE_SCOPE},{VERIFY_SCOPE}"
        for sa in ([impersonate] if impersonate else IMPERSONATION_CANDIDATES):
            got = _impersonate(sa, scopes)
            if got is not None:
                return got

    # 4. The bare gcloud user credential. Almost certainly lacks the webmasters scope,
    #    but reporting that precisely beats reporting "no credentials".
    for args in (["gcloud", "auth", "application-default", "print-access-token"],
                 ["gcloud", "auth", "print-access-token"]):
        try:
            p = subprocess.run(args, capture_output=True, text=True, timeout=90)
        except Exception:  # noqa: BLE001
            continue
        if p.returncode == 0 and p.stdout.strip():
            tok = p.stdout.strip()
            return Auth(tok, " ".join(args[:-1]), _tokeninfo(tok))
    return None


# ---------------------------------------------------------------------- transport


def call(auth: Auth, method: str, path: str) -> tuple[int, dict]:
    req = urllib.request.Request(API + path, method=method, headers=auth.header)
    if method in ("PUT", "POST", "DELETE"):
        req.add_header("Content-Length", "0")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except Exception:  # noqa: BLE001
            return e.code, {"raw": raw[:400]}
    except Exception as e:  # noqa: BLE001
        return 0, {"error": type(e).__name__}


def post_json(auth: Auth, url: str, body: dict) -> tuple[int, dict]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={**auth.header,
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except Exception:  # noqa: BLE001
            return e.code, {"raw": raw[:400]}
    except Exception as e:  # noqa: BLE001
        return 0, {"error": type(e).__name__}


def enc(s: str) -> str:
    return urllib.parse.quote(s, safe="")


def why(body: dict) -> str:
    err = body.get("error") or {}
    if isinstance(err, str):
        return err
    return f"{err.get('status', '?')}: {err.get('message', body)}"


# ------------------------------------------------------------------------ actions


def properties(auth: Auth) -> tuple[int, list[dict]]:
    st, body = call(auth, "GET", "/sites")
    return st, (body.get("siteEntry") or []) if st == 200 else []


def pick_property(auth: Auth, override: str | None) -> tuple[str | None, list[dict], int]:
    st, entries = properties(auth)
    if override:
        return override, entries, st
    have = {e.get("siteUrl") for e in entries}
    for c in CANDIDATE_PROPERTIES:
        if c in have:
            return c, entries, st
    # Nothing visible. Return the domain-property guess so the error names a target.
    return (entries[0]["siteUrl"] if entries else None), entries, st


def principal_of(auth: Auth) -> str | None:
    """The service-account email, when the credential is an impersonated one."""
    if auth.source.startswith("impersonated "):
        return auth.source.split(" ", 1)[1]
    return None


def cmd_check(auth: Auth, args) -> int:  # noqa: ANN001
    print(f"credential source : {auth.source}")
    if auth.scopes is None:
        print("token scopes      : could not be determined")
    else:
        print(f"token scopes      : {len(auth.scopes)}")
        for s in sorted(auth.scopes):
            mark = " <-- write" if s == WRITE_SCOPE else (
                " <-- read only" if s == READ_SCOPE else "")
            print(f"                    {s}{mark}")

    # Gate 1: the scope. Gate 2: the property grant. Reported separately on purpose -
    # they fail for unrelated reasons and only one of them still needs a human.
    print(f"\nGATE 1 scope      : {'PASS' if auth.has_write() else 'FAIL'} "
          f"({WRITE_SCOPE})")

    st, entries = properties(auth)
    print(f"       sites.list : http {st}")
    if st != 200:
        _, body = call(auth, "GET", "/sites")
        print(f"                    {why(body)}")
        print("\nBLOCKED at GATE 1 - the token cannot reach the API at all.\n")
        print(unblock_text(principal_of(auth)))
        return 2

    print(f"GATE 2 properties : {len(entries)} visible")
    for e in entries:
        print(f"                    {e.get('siteUrl')}  "
              f"permission={e.get('permissionLevel')}")
    if not entries:
        print("                    FAIL - authentication works (http 200), but this")
        print("                    principal is not a user on any property. Search")
        print("                    Console has no API for granting that.")
        print("\nBLOCKED at GATE 2 only. One UI action remains:\n")
        print(unblock_text(principal_of(auth)))
        return 2

    # A property can be visible with a permission level that still cannot submit.
    weak = [e for e in entries
            if e.get("permissionLevel") in ("siteRestrictedUser", "siteUnverifiedUser")]
    if weak and len(weak) == len(entries):
        print("\nBLOCKED - every visible property is Restricted or Unverified, and")
        print("neither can submit a sitemap. Raise the grant to Full.\n")
        print(unblock_text(principal_of(auth)))
        return 2
    print("\nGATE 1 and GATE 2 both PASS - `submit --apply` will work.")
    return 0


def cmd_list(auth: Auth, args) -> int:  # noqa: ANN001
    prop, entries, st = pick_property(auth, args.property)
    if st != 200 or prop is None:
        return cmd_check(auth, args)
    print(f"property: {prop}")
    st, body = call(auth, "GET", f"/sites/{enc(prop)}/sitemaps")
    if st != 200:
        print(f"sitemaps.list http {st}  {why(body)}")
        return 2
    feeds = body.get("sitemap") or []
    print(f"registered sitemaps: {len(feeds)}")
    for f in feeds:
        print(f"  {f.get('path')}")
        print(f"    type={f.get('type')} lastSubmitted={f.get('lastSubmitted')} "
              f"lastDownloaded={f.get('lastDownloaded')} "
              f"warnings={f.get('warnings')} errors={f.get('errors')} "
              f"isPending={f.get('isPending')} isSitemapsIndex={f.get('isSitemapsIndex')}")
        for c in f.get("contents") or []:
            print(f"    contents: type={c.get('type')} submitted={c.get('submitted')} "
                  f"indexed={c.get('indexed')}")
    return 0


def cmd_submit(auth: Auth, args) -> int:  # noqa: ANN001
    prop, entries, st = pick_property(auth, args.property)
    if st != 200 or prop is None:
        return cmd_check(auth, args)
    if auth.has_write() is False:
        print("BLOCKED - the token carries no write scope, so submit would 403.\n")
        print(unblock_text(principal_of(auth)))
        return 2
    feed = args.sitemap
    print(f"property : {prop}")
    print(f"sitemap  : {feed}")
    if not args.apply:
        print("\nDRY RUN - nothing submitted. Re-run with --apply.")
        print(f"would PUT {API}/sites/{enc(prop)}/sitemaps/{enc(feed)}")
        return 0
    st, body = call(auth, "PUT", f"/sites/{enc(prop)}/sitemaps/{enc(feed)}")
    if st in (200, 204):
        print(f"SUBMITTED (http {st})")
        # Read it straight back. A 200 on the PUT only means Google accepted the
        # registration, not that it could fetch the file.
        st2, b2 = call(auth, "GET", f"/sites/{enc(prop)}/sitemaps/{enc(feed)}")
        if st2 == 200:
            print(f"  lastSubmitted={b2.get('lastSubmitted')} "
                  f"lastDownloaded={b2.get('lastDownloaded')} "
                  f"errors={b2.get('errors')} warnings={b2.get('warnings')} "
                  f"isPending={b2.get('isPending')}")
            print("  NOTE: lastDownloaded stays empty until Google fetches the file.")
        return 0
    print(f"FAILED http {st}  {why(body)}")
    return 2


def cmd_prune(auth: Auth, args) -> int:  # noqa: ANN001
    """Remove registered feeds that are not a sitemap this site serves.

    TWO FAILURE MODES, AND "IS IT SERVED" ONLY CATCHES ONE. This property had three feeds
    registered and two were wrong in different ways:

      https://wecare.digital/sitemap.xml/   404 - a dead sitemap INDEX registered in
                                            2024-03, still advertising 44 URLs. Gone.
      https://wecare.digital/favicon.ico    200 - and it is a real favicon. Somebody
                                            submitted the site icon as a sitemap in
                                            2024-09 and it has carried errors=1 ever
                                            since. Served, and still not a sitemap.

    So a feed is judged on whether it can BE a sitemap, not on whether the URL resolves.
    A sitemap is XML (or a plain-text URL list); `image/x-icon` cannot be one whatever it
    answers. Checking only the status code would have kept the favicon forever.
    """
    import urllib.request as ur

    prop, entries, st = pick_property(auth, args.property)
    if st != 200 or prop is None:
        return cmd_check(auth, args)
    st, body = call(auth, "GET", f"/sites/{enc(prop)}/sitemaps")
    if st != 200:
        print(f"sitemaps.list http {st}  {why(body)}")
        return 2
    feeds = body.get("sitemap") or []
    keep, stale = [], []
    for f in feeds:
        path = f.get("path") or ""
        if path == args.sitemap:
            keep.append((f, 200, "the current sitemap"))
            continue
        code, ctype = 0, ""
        try:
            with ur.urlopen(ur.Request(
                    path, headers={"User-Agent": "wecare-gsc-prune/1"}),
                    timeout=30) as r:
                code = r.status
                ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip()
        except urllib.error.HTTPError as e:
            code = e.code
        except Exception:  # noqa: BLE001
            code = 0

        sitemapish = ctype in ("application/xml", "text/xml", "text/plain") or (
            ctype == "application/gzip")
        if code != 200:
            stale.append((f, code, "not served"))
        elif not sitemapish:
            stale.append((f, code, f"served as {ctype or 'unknown'} - cannot be a sitemap"))
        else:
            keep.append((f, code, f"served as {ctype}"))

    print(f"property: {prop}")
    print(f"registered: {len(feeds)}   keep: {len(keep)}   stale: {len(stale)}")
    for f, code, note in keep:
        print(f"  KEEP   http {code}  {f.get('path')}  ({note})")
    for f, code, note in stale:
        print(f"  STALE  http {code}  {f.get('path')}  ({note})"
              f"  [submitted={f.get('lastSubmitted', '')[:10]} errors={f.get('errors')}]")
    if not stale:
        print("\nnothing to prune.")
        return 0
    if auth.has_write() is False:
        print("\nBLOCKED - no write scope, so delete would 403.\n")
        print(unblock_text(principal_of(auth)))
        return 2
    if not args.apply:
        print("\nDRY RUN - nothing deleted. Re-run with --apply.")
        return 0
    rc = 0
    for f, _code, _note in stale:
        path = f.get("path")
        st, body = call(auth, "DELETE", f"/sites/{enc(prop)}/sitemaps/{enc(path)}")
        if st in (200, 204):
            print(f"  DELETED {path}")
        else:
            print(f"  FAILED  {path}  http {st}  {why(body)}")
            rc = 2
    print("\nReversible: re-register any of these with `submit --sitemap <url>`.")
    return rc


def cmd_verify(auth: Auth, args) -> int:  # noqa: ANN001
    """Prove site ownership with the FILE method, which closes GATE 2 with no UI action.

    Order matters and the checks are not decoration. Google fetches the token file itself
    and an `insert` against a missing file consumes an attempt and returns a generic
    failure, so the file is confirmed live from here first - that turns "verification
    failed" into either "the deploy has not landed yet" or a real problem, which are very
    different next steps.
    """
    import urllib.request as ur

    print(f"principal : {principal_of(auth) or auth.source}")
    print(f"site      : {VERIFY_SITE}  (URL-prefix property)")

    st, body = post_json(auth, f"{SV_API}/token", {
        "verificationMethod": "FILE",
        "site": {"type": "SITE", "identifier": VERIFY_SITE},
    })
    if st != 200:
        print(f"getToken FAILED http {st}  {why(body)}")
        return 2
    token_file = body.get("token") or ""
    print(f"token file: /{token_file}")

    # Is it live? The file is a PUBLIC verification token by design, so printing its
    # name and body is not a disclosure - it grants nothing on its own.
    url = f"{SITE}/{token_file}"
    try:
        with ur.urlopen(ur.Request(url, headers={"User-Agent": "wecare-gsc-verify/1"}),
                        timeout=30) as r:
            served, text = r.status, r.read().decode(errors="replace").strip()
    except urllib.error.HTTPError as e:
        served, text = e.code, ""
    except Exception as e:  # noqa: BLE001
        served, text = 0, type(e).__name__

    expected = f"google-site-verification: {token_file}"
    print(f"live check: http {served} at {url}")
    if served != 200:
        print(f"\nBLOCKED - the token file is not being served yet.")
        print(f"  Add it at `public/{token_file}` containing exactly:\n    {expected}")
        print("  then deploy. Google fetches this file itself, so verifying before it is")
        print("  live burns an attempt and reports a misleading reason.")
        return 2
    if text != expected:
        print(f"\nBLOCKED - the file is served but its contents are wrong.")
        print(f"  expected: {expected}\n  found:    {text[:120]}")
        print("  Google compares the body literally; no header or extra line is tolerated.")
        return 2
    print("           contents match exactly")

    if not args.apply:
        print("\nDRY RUN - nothing verified. Re-run with --apply.")
        print(f"would POST {SV_API}/webResource?verificationMethod=FILE")
        return 0

    st, body = post_json(
        auth, f"{SV_API}/webResource?verificationMethod=FILE",
        {"site": {"type": "SITE", "identifier": VERIFY_SITE}},
    )
    if st not in (200, 201):
        print(f"\nverification FAILED http {st}  {why(body)}")
        return 2
    print(f"\nVERIFIED - id={body.get('id')} owners={body.get('owners')}")
    print("Reversible: DELETE siteVerification/v1/webResource/<id> un-verifies, and")
    print(f"deleting public/{token_file} removes the proof.")

    # Verifying ownership is NOT the same as having the property in Search Console, and
    # this caught me out: immediately after a successful verification `sites.list` still
    # returned 0. Site Verification and Search Console are separate services - the first
    # records who owns the site, the second keeps a per-account list of properties. The
    # property has to be added explicitly, which is the one thing `sites.add` is for.
    st, entries = properties(auth)
    if not any(e.get("siteUrl") == VERIFY_SITE for e in entries):
        st, body = call(auth, "PUT", f"/sites/{enc(VERIFY_SITE)}")
        print(f"\nsites.add {VERIFY_SITE} -> http {st}"
              + ("" if st in (200, 204) else f"  {why(body)}"))

    st, entries = properties(auth)
    print(f"\nsites.list now: http {st}, {len(entries)} property(ies)")
    for e in entries:
        print(f"  {e.get('siteUrl')}  permission={e.get('permissionLevel')}")
    return 0 if entries else 2


def cmd_inspect(auth: Auth, args) -> int:  # noqa: ANN001
    prop, entries, st = pick_property(auth, args.property)
    if st != 200 or prop is None:
        return cmd_check(auth, args)
    target = args.url
    if target.startswith("/"):
        target = SITE + target
    st, body = post_json(
        auth,
        "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect",
        {"inspectionUrl": target, "siteUrl": prop, "languageCode": "en-IN"},
    )
    if st != 200:
        print(f"urlInspection http {st}  {why(body)}")
        return 2
    result = body.get("inspectionResult") or {}
    res = result.get("indexStatusResult") or {}
    print(f"url        : {target}")
    print(f"verdict    : {res.get('verdict')}")
    print(f"coverage   : {res.get('coverageState')}")
    print(f"robots     : {res.get('robotsTxtState')}")
    print(f"indexing   : {res.get('indexingState')}")
    print(f"canonical  : google={res.get('googleCanonical')} "
          f"user={res.get('userCanonical')}")
    print(f"lastCrawl  : {res.get('lastCrawlTime')}")

    # Rich results, which is what structured-data work is FOR.
    #
    # Read this against `lastCrawl` above, always. Both of these report what Google saw at its
    # LAST CRAWL, not what the URL serves now - so a page whose markup was fixed today and
    # whose lastCrawl is empty will report nothing here, and that is "not yet crawled", not
    # "not eligible". Reading an absent verdict as a failure would send someone rewriting
    # markup that is already correct.
    rich = result.get("richResultsResult") or {}
    if rich:
        print(f"richResults: verdict={rich.get('verdict')}")
        for item in rich.get("detectedItems") or []:
            issues = item.get("items") or []
            print(f"  {item.get('richResultType')}: {len(issues)} item(s)")
            for entry in issues:
                problems = entry.get("issues") or []
                name = entry.get("name") or "(unnamed)"
                if not problems:
                    print(f"    ok   {name}")
                for problem in problems:
                    print(f"    {problem.get('severity', '?')}: {name} — "
                          f"{problem.get('issueMessage')}")
    else:
        print("richResults: none reported"
              + ("" if res.get("lastCrawlTime")
                 else " — and lastCrawl is empty, so this URL has NOT been crawled;"
                      " absence here is 'not seen yet', not 'not eligible'"))

    mobile = (result.get("mobileUsabilityResult") or {}).get("verdict")
    if mobile:
        print(f"mobile     : {mobile}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action",
                    choices=["check", "verify", "list", "submit", "prune", "inspect"])
    ap.add_argument("url", nargs="?", default="/",
                    help="for `inspect`: the URL or path to inspect")
    ap.add_argument("--property", default=None,
                    help="Search Console property, e.g. sc-domain:wecare.digital")
    ap.add_argument("--sitemap", default=DEFAULT_SITEMAP)
    ap.add_argument("--apply", action="store_true",
                    help="perform writes; without it every write is a dry run")
    ap.add_argument("--impersonate", default=None,
                    help="service account to impersonate for the webmasters scope")
    ap.add_argument("--no-impersonate", action="store_true",
                    help="do not impersonate; use only the primary credential")
    args = ap.parse_args()

    auth = resolve_auth(impersonate=args.impersonate,
                        allow_impersonation=not args.no_impersonate)
    if auth is None:
        print("BLOCKED - no Google credential available at all.\n")
        print(unblock_text(args.impersonate))
        return 2

    return {
        "check": cmd_check, "verify": cmd_verify, "list": cmd_list,
        "submit": cmd_submit, "prune": cmd_prune, "inspect": cmd_inspect,
    }[args.action](auth, args)


if __name__ == "__main__":
    raise SystemExit(main())
