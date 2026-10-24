"""Plivo X-Plivo-Signature-V3 validation, with no third-party dependency.

§18 requires V3 signature validation to replace token-only provider
authentication. The official SDK implements this, but `plivo` lives in
requirements-dev.txt and is not bundled into any Lambda package, so a runtime
handler cannot import it. This is a faithful reimplementation.

It is verified the only way that is meaningful: tests/test_plivo_signature.py
cross-checks this implementation against the installed SDK
(`plivo.utils.signature_v3.validate_v3_signature`) over a matrix of URLs,
parameter shapes and nonces. If Plivo changes the algorithm, that test fails
rather than this silently diverging.

THE ALGORITHM, and the parts the public docs leave out
-----------------------------------------------------
The docs describe concatenating the URL, the sorted POST parameters and the
nonce, then HMAC-SHA256 with the auth token and base64. Reading the SDK shows
four details that are load-bearing and not in the prose:

  1. The nonce is joined with a literal '.' separator:  f"{base_url}.{nonce}".
     Bare concatenation produces a different digest.
  2. For a POST, a '.' is appended after the query string - but only when the
     URL actually had a query string. So a URL with `?token=` gets
     `...?token=abc.` before the parameter blob, and a URL without one gets a
     bare trailing `?`.
  3. Sorted POST parameters are concatenated as key+value with NO separator
     between pairs and none between key and value.
  4. The header may carry SEVERAL comma-separated signatures. Any one matching
     is valid. Comparing against the whole header string fails whenever Plivo
     sends more than one.

Getting any of those wrong yields a validator that rejects every genuine
request, which in a fail-closed handler means every call is dropped.

WHICH HEADER, AND WHICH TOKEN
-----------------------------
  X-Plivo-Signature-V3     signed with the auth token of the account OR
                           SUBACCOUNT the request entity belongs to
  X-Plivo-Signature-Ma-V3  always signed with the MAIN account auth token

This account has 0 subaccounts (verified via /Subaccount/), so the two are
currently equivalent. Both are still checked, because acquiring a subaccount
later would otherwise silently break the V3 header while Ma-V3 kept working -
or worse, the reverse.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

HEADER_V3 = "x-plivo-signature-v3"
HEADER_MA_V3 = "x-plivo-signature-ma-v3"
HEADER_NONCE = "x-plivo-signature-v3-nonce"


def _string_format(value: Any) -> Any:
    """Mirror the SDK's coercion so digests match for non-string values."""
    if isinstance(value, bytes):
        return "".join(chr(x) for x in bytearray(value))
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return [_string_format(x) for x in value]
    return value


def _map_from_query(query: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in urllib.parse.parse_qs(query, keep_blank_values=True).items():
        out[_string_format(key)] = _string_format(value)
    return out


def _sorted_query_string(params: Dict[str, Any]) -> str:
    parts: List[str] = []
    for key in sorted(params.keys()):
        value = params[key]
        if isinstance(value, list):
            parts.append("&".join(
                f"{_string_format(key)}={val}" for val in sorted(_string_format(value))))
        else:
            parts.append(f"{_string_format(key)}={_string_format(value)}")
    return "&".join(parts)


def _sorted_params_string(params: Dict[str, Any]) -> str:
    """key+value concatenated, sorted by key, no separators at all."""
    parts: List[str] = []
    for key in sorted(params.keys()):
        value = params[key]
        if isinstance(value, list):
            parts.append("".join(
                f"{_string_format(key)}{val}" for val in sorted(_string_format(value))))
        elif isinstance(value, dict):
            parts.append(f"{_string_format(key)}{_sorted_params_string(value)}")
        else:
            parts.append(f"{_string_format(key)}{_string_format(value)}")
    return "".join(parts)


def _construct_get_url(uri: str, params: Dict[str, Any],
                       empty_post_params: bool = True) -> str:
    parsed = urllib.parse.urlparse(uri)
    base = urllib.parse.urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
    merged = dict(params)
    merged.update(_map_from_query(parsed.query))
    query = _sorted_query_string(merged)
    if query or not empty_post_params:
        base = base + "?" + query
    if query and not empty_post_params:
        base = base + "."
    return base


def _construct_post_url(uri: str, params: Dict[str, Any]) -> str:
    base = _construct_get_url(uri, {}, empty_post_params=(len(params) == 0))
    return base + _sorted_params_string(params)


def compute_signature(auth_token: str, base_url: str, nonce: str) -> str:
    """HMAC-SHA256 over f"{base_url}.{nonce}", base64, stripped."""
    payload = f"{base_url}.{nonce}".encode("utf-8")
    digest = hmac.new(auth_token.encode("utf-8"), payload, hashlib.sha256).digest()
    return base64.encodebytes(digest).strip().decode("utf-8")


def expected_signature(method: str, uri: str, nonce: str, auth_token: str,
                       params: Optional[Dict[str, Any]] = None) -> str:
    params = params or {}
    method = (method or "POST").upper()
    base = (_construct_get_url(uri, dict(params)) if method == "GET"
            else _construct_post_url(uri, dict(params)))
    return compute_signature(auth_token, base, nonce)


def validate_signature(method: str, uri: str, nonce: str, auth_token: str,
                       signature_header: str,
                       params: Optional[Dict[str, Any]] = None) -> bool:
    """True when any comma-separated signature in the header matches.

    Comparison is constant-time. A plain == on a signature leaks timing that can
    be used to forge one byte at a time, and this is the only thing standing
    between the internet and a handler with side effects.
    """
    if not (nonce and auth_token and signature_header):
        return False
    expected = expected_signature(method, uri, nonce, auth_token, params)
    for candidate in signature_header.split(","):
        if hmac.compare_digest(expected, candidate.strip()):
            return True
    return False


# --------------------------------------------------------------------------
# API Gateway helpers
# --------------------------------------------------------------------------
# Stage-prefix normalization moved to lambda_utils/http_path.py on 2026-09-21.
#
# It lived here because the Plivo signature check was the first thing the stage
# prefix broke, but the WhatsApp ingress and the short-link service depend on the
# same rule, and nobody auditing WhatsApp routing would look for it in a Plivo
# module. Re-exported so existing imports and tests keep working unchanged.
#
# The moved version also handles a path that is exactly "/{stage}", which this one
# did not - see http_path for why that mattered to url-shortener.
from lambda_utils.http_path import normalize_path  # noqa: E402,F401  (re-export)


def reconstruct_url(event: Dict[str, Any], *, force_host: str = "",
                    force_path_prefix: str = "") -> str:
    """Rebuild the exact URL Plivo requested, from an HTTP API v2 event.

    The signature covers the full URL including the query string, so this has to
    match byte for byte. Three things matter behind API Gateway:

      * the custom domain, not the execute-api hostname.
        `requestContext.domainName` carries it when the request arrived through
        one, and `PLIVO_CALLBACK_HOST` overrides when it does not.
      * rawQueryString, not queryStringParameters. The latter is a parsed dict
        and reserialising it can reorder or re-encode, changing the digest. The
        `?token=` on these URLs makes this concrete: the token is part of the
        signed payload.
      * any path segment consumed by a proxy in front of the API.

    THE PATH PREFIX, AND THE OUTAGE THAT ADDED IT
    ---------------------------------------------
    On 2026-09-26 the callbacks moved from `https://wecare.digital/api/plivo/*` to
    `https://wecare.digital/api/plivo/*`, served by an Amplify rewrite
    `/api/<*>` -> `execute-api/prod/<*>`. That rewrite CONSUMES the `/api`
    segment, so Plivo signs `/api/plivo/answer` while the Lambda only ever sees
    `/plivo/answer` after `normalize_path` strips the stage. Every callback then
    failed with `signature_mismatch` — inbound IVR answered nothing.

    It was not caught beforehand because the pre-migration checks compared status
    codes on UNSIGNED requests, and an unsigned request is rejected identically on
    either URL. A signature that covers the URL cannot be validated by a probe
    that carries no signature; only a real signed call exercises it.

    `PLIVO_CALLBACK_PATH_PREFIX` restores the segment the proxy ate. It is
    deliberately explicit rather than inferred from a header: `x-forwarded-*` is
    not present on this path, and guessing the public path from the private one is
    how a signature check starts silently passing the wrong thing.
    """
    rc = event.get("requestContext") or {}
    host = (force_host or os.environ.get("PLIVO_CALLBACK_HOST")
            or rc.get("domainName") or "")
    prefix = (force_path_prefix or os.environ.get("PLIVO_CALLBACK_PATH_PREFIX") or "")
    prefix = ("/" + prefix.strip("/")) if prefix.strip("/") else ""
    path = normalize_path(event)
    query = event.get("rawQueryString") or ""
    url = f"https://{host}{prefix}{path}"
    return f"{url}?{query}" if query else url


def parse_form_params(event: Dict[str, Any]) -> Dict[str, Any]:
    """Plivo posts application/x-www-form-urlencoded.

    Values stay as LISTS, matching parse_qs, because the signature algorithm
    sorts multi-valued parameters. Collapsing single-element lists to scalars
    here would change the digest for any repeated parameter.
    """
    body = event.get("body") or ""
    if event.get("isBase64Encoded") and body:
        try:
            body = base64.b64decode(body).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            return {}
    if not body:
        return {}
    stripped = body.lstrip()
    if stripped.startswith("{"):
        # JSON callbacks are not signature-covered by the form algorithm.
        return {}
    return {k: v for k, v in
            urllib.parse.parse_qs(body, keep_blank_values=True).items()}


def headers_lower(event: Dict[str, Any]) -> Dict[str, str]:
    return {str(k).lower(): v for k, v in (event.get("headers") or {}).items()}


def verify_request(event: Dict[str, Any], auth_token: str,
                   main_auth_token: str = "") -> Tuple[bool, str]:
    """Verify an inbound Plivo callback. Returns (ok, reason).

    Fail closed: no auth token configured means REJECT. An endpoint with side
    effects that accepts unverified requests when misconfigured is worse than one
    that refuses, because the failure is silent.
    """
    if not auth_token:
        return False, "auth_token_not_configured"

    hdrs = headers_lower(event)
    nonce = hdrs.get(HEADER_NONCE, "")
    if not nonce:
        return False, "missing_nonce_header"

    sig_v3 = hdrs.get(HEADER_V3, "")
    sig_ma = hdrs.get(HEADER_MA_V3, "")
    if not (sig_v3 or sig_ma):
        return False, "missing_signature_header"

    method = ((event.get("requestContext") or {}).get("http") or {}).get(
        "method", "POST").upper()
    uri = reconstruct_url(event)
    params = parse_form_params(event) if method == "POST" else {}

    if sig_v3 and validate_signature(method, uri, nonce, auth_token, sig_v3, params):
        return True, "v3"
    # Ma-V3 is always the MAIN account token. Equivalent today (no subaccounts)
    # but not guaranteed to stay so.
    ma_token = main_auth_token or auth_token
    if sig_ma and validate_signature(method, uri, nonce, ma_token, sig_ma, params):
        return True, "ma_v3"
    return False, "signature_mismatch"
